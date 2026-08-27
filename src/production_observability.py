"""本地 Minimal 生产检索观测的隐私边界与封存工具。

该模块独立于 G1-S synthetic capture；默认关闭时不创建目录、不写文件。
仅保存匿名化的诊断字段，Exact replay 保留为不可用占位，不保存明文输入或响应。
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import shutil
import time
import uuid
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 1
RETENTION_DAYS = 30
EVENT_TYPES = (
    "trace.begin", "rewrite.decided", "decompose.decided", "retrieve.dense",
    "retrieve.bm25", "fusion.rrf", "merge.rewrite_drift", "cutoff.dynamic_top_k",
    "refusal.decided", "rerank.applied", "selector.applied",
    "expand.parent_adjacent", "context.built", "generation.completed", "trace.end",
)


class ConsentLevel(str, Enum):
    OFF = "off"
    MINIMAL = "minimal"
    EXACT = "exact"


class TraceDeletedError(RuntimeError):
    pass


def _canonical(value: dict[str, Any]) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True,
                       separators=(",", ":")) + "\n").encode("utf-8")


def canonical_event_bytes(event: dict[str, Any], *, include_hash: bool = True) -> bytes:
    value = dict(event)
    if not include_hash:
        value.pop("line_sha256", None)
    return _canonical(value)


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _script(text: str) -> str:
    if any("\u4e00" <= char <= "\u9fff" for char in text):
        return "cjk"
    if any(char.isalpha() for char in text):
        return "latin"
    return "other"


def salted_digest(text: str, salt: bytes) -> tuple[str, int, str]:
    raw = text.encode("utf-8")
    return _sha256(salt + raw), len(text), _script(text)


def _safe_id(value: str) -> bool:
    return bool(re.fullmatch(r"[0-9a-f]{32}", value))


def _module_repo_root() -> Path:
    """仓库工作树根：本模块物理上位于 <repo>/src/ 下，parents[1] 即仓库根。

    刻意不用 Path.cwd() 推导——产品可能从任意目录启动，防泄漏守卫的
    参照系不能随进程 CWD 漂移。
    """
    return Path(__file__).resolve().parents[1]


def _is_within(child: Path, ancestor: Path) -> bool:
    """normcase 后判断 child 是否等于或位于 ancestor 之内。

    Windows 文件系统大小写不敏感且分隔符可混用，比较前必须统一；
    守卫宁可误拒也不放过任何一个落在仓库内的路径。
    """
    child_str = os.path.normcase(str(child))
    ancestor_str = os.path.normcase(str(ancestor))
    if child_str == ancestor_str:
        return True
    return child_str.startswith(ancestor_str.rstrip("\\/") + os.sep)


@dataclass
class _Consent:
    level: ConsentLevel = ConsentLevel.OFF
    session_id: str = ""
    salt: bytes = b""


class TraceStore:
    def __init__(self, traces_root: Path):
        self.root = Path(traces_root).expanduser().resolve()
        self._validate_root(self.root)
        self.consent = self._load_consent()
        self._active: dict[str, list[dict[str, Any]]] = {}

    @classmethod
    def from_environment(cls) -> "TraceStore":
        data_dir = os.getenv("MNEME_DATA_DIR", "").strip()
        base = Path(data_dir).expanduser() if data_dir else Path.home() / ".mneme"
        return cls(base / "traces")

    @staticmethod
    def _validate_root(root: Path) -> None:
        if not root.is_absolute():
            raise ValueError("trace root must be absolute")
        # P1.1-E 防泄漏守卫（owner PUSH_SAFETY 决策）：trace 数据与
        # consent.json 属 owner 个人本地数据，任何情况下不得落入 git
        # 工作树。命中即在任何 mkdir/写盘之前 fail-closed 拒绝启动，
        # 且不提供绕过开关；旧的四子树检查保留作纵深防御。
        repo_root = _module_repo_root()
        if _is_within(root, repo_root):
            raise ValueError(
                f"trace root 位于仓库工作树内（{repo_root}），"
                "观测数据绝不允许写入代码库：请把 MNEME_DATA_DIR 指向"
                "仓库外的私有数据目录（默认 ~/.mneme），或将该 traces "
                "目录移出仓库后重试"
            )
        cwd = Path.cwd().resolve()
        protected = [cwd / "src", cwd / "plans", cwd / "evaluation", cwd / "tests"]
        if root == cwd or any(root == item or item in root.parents for item in protected):
            raise ValueError("trace path is inside a protected repository tree")
        if root.name != "traces":
            raise ValueError("trace path must end with traces")

    @property
    def _consent_path(self) -> Path:
        return self.root / "consent.json"

    @property
    def _tombstone_path(self) -> Path:
        return self.root / "tombstones.json"

    def _load_consent(self) -> _Consent:
        if not self._consent_path.is_file():
            return _Consent()
        try:
            value = json.loads(self._consent_path.read_text(encoding="utf-8"))
            level = ConsentLevel(value.get("level", "off"))
            if level is ConsentLevel.EXACT:
                level = ConsentLevel.OFF
            return _Consent(level=level, session_id=value.get("session_id", ""),
                            salt=secrets.token_bytes(32))
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            return _Consent()

    def _write_json(self, path: Path, value: Any) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(_canonical(value) if isinstance(value, dict) else
                         (json.dumps(value, ensure_ascii=False, sort_keys=True,
                                     separators=(",", ":")) + "\n").encode("utf-8"))

    def set_consent(self, level: ConsentLevel, *, confirmed: bool = False) -> bool:
        if not confirmed:
            return False
        level = ConsentLevel(level)
        if level is ConsentLevel.EXACT:
            return False
        if level is ConsentLevel.OFF:
            self.revoke_consent()
            return True
        self.root.mkdir(parents=True, exist_ok=True)
        self.consent = _Consent(level, uuid.uuid4().hex, secrets.token_bytes(32))
        consent = {
            "schema_version": SCHEMA_VERSION,
            "level": level.value,
            "session_id": self.consent.session_id,
            "updated_at": int(time.time()),
        }
        consent["self_sha256"] = _sha256(_canonical(consent))
        self._write_json(self._consent_path, consent)
        self.prune()
        return True

    def revoke_consent(self) -> None:
        self.consent = _Consent()
        trace_ids = [path.stem for path in self.root.glob("*.jsonl")] if self.root.exists() else []
        for trace_id in trace_ids:
            self.delete_trace(trace_id)
        if self._consent_path.exists():
            try:
                self._consent_path.unlink()
            except OSError:
                pass

    def begin_trace(self, planning_profile: str, retrieval_k: int | None) -> str:
        if self.consent.level is not ConsentLevel.MINIMAL:
            return ""
        trace_id = uuid.uuid4().hex
        self._active[trace_id] = [{
            "schema_version": SCHEMA_VERSION,
            "trace_id": trace_id,
            "session_id": self.consent.session_id,
            "turn_index": len(self._active),
            "event_type": "trace.begin",
            "pii_level": "hashed",
            "planning_profile": planning_profile,
            "retrieval_k": retrieval_k,
            "consent": self.consent.level.value,
        }]
        return trace_id

    def minimum_payload(self, event_type: str) -> dict[str, Any]:
        if event_type not in EVENT_TYPES:
            raise ValueError(f"unknown event type: {event_type}")
        return {"status": "unavailable"}

    def emit(self, event_type: str, payload: dict[str, Any], *, trace_id: str = "") -> bool:
        if self.consent.level is not ConsentLevel.MINIMAL or not trace_id:
            return False
        if event_type not in EVENT_TYPES or event_type == "trace.begin":
            raise ValueError("invalid production-observability event")
        if not isinstance(payload, dict) or any(isinstance(v, (bytes, bytearray)) for v in payload.values()):
            raise ValueError("event payload must be JSON-safe")
        forbidden = {
            "query", "history", "rewritten_query", "sub_queries", "answer",
            "model_response", "prompt", "document", "api_key", "authorization",
            "base_url", "path",
        }
        if forbidden.intersection(payload):
            raise ValueError("sensitive raw fields are forbidden in Minimal trace")
        try:
            json.dumps(payload, ensure_ascii=False)
        except (TypeError, ValueError) as exc:
            raise ValueError("event payload must be JSON-safe") from exc
        event = {
            "schema_version": SCHEMA_VERSION,
            "trace_id": trace_id,
            "session_id": self.consent.session_id,
            "turn_index": len(self._active[trace_id]),
            "event_type": event_type,
            "pii_level": "none" if event_type not in {"rewrite.decided", "decompose.decided"} else "hashed",
            **payload,
        }
        self._active[trace_id].append(event)
        return True

    def emit_sensitive(self, event_type: str, text: str, *, trace_id: str) -> bool:
        digest, length, script = salted_digest(text, self.consent.salt)
        return self.emit(event_type, {"result_sha256": digest, "result_length": length,
                                      "result_script": script}, trace_id=trace_id)

    def capture_answer(self, query: str, answer: str, *, planning_profile: str,
                       retrieval_k: int | None, citation_state: str = "unknown") -> bool:
        """在回答完成后尾随封存 Minimal 诊断；任何失败均返回 False。"""
        if self.consent.level is not ConsentLevel.MINIMAL:
            return False
        trace_id = self.begin_trace(planning_profile, retrieval_k)
        if not trace_id:
            return False
        try:
            self.emit_sensitive("rewrite.decided", query, trace_id=trace_id)
            self.emit_sensitive("decompose.decided", query, trace_id=trace_id)
            for event_type in EVENT_TYPES[3:-1]:
                self.emit(event_type, self.minimum_payload(event_type), trace_id=trace_id)
            digest, length, _ = salted_digest(answer, self.consent.salt)
            self.emit("generation.completed", {
                "result_sha256": digest, "result_length": length,
                "token_count": len(answer.split()), "latency_ms": 0,
                "citation_state": citation_state,
            }, trace_id=trace_id)
            return self.finish_trace(trace_id)
        except Exception:
            self._active.pop(trace_id, None)
            return False

    def finish_trace(self, trace_id: str) -> bool:
        if not trace_id or trace_id not in self._active:
            return False
        self._active[trace_id].append({
            "schema_version": SCHEMA_VERSION, "trace_id": trace_id,
            "session_id": self.consent.session_id,
            "turn_index": len(self._active[trace_id]), "event_type": "trace.end",
            "pii_level": "none", "end_reason": "normal",
        })
        events = self._active.pop(trace_id)
        try:
            self._seal(trace_id, events)
            return True
        except (OSError, ValueError, TypeError):
            return False

    def discard_trace(self, trace_id: str) -> None:
        """异常安全清理：丢弃尚未封存的 active trace，不写任何文件。"""
        self._active.pop(trace_id, None)

    def _seal(self, trace_id: str, events: list[dict[str, Any]]) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        lines = []
        hashes = []
        for event in events:
            line_hash = _sha256(canonical_event_bytes(event, include_hash=False))
            event = dict(event, line_sha256=line_hash)
            lines.append(canonical_event_bytes(event))
            hashes.append(line_hash)
        segment = self.root / f"{trace_id}.jsonl"
        segment.write_bytes(b"".join(lines))
        manifest = {
            "schema_version": SCHEMA_VERSION,
            "trace_id": trace_id,
            "line_sha256": hashes,
            "segment_sha256": _sha256(segment.read_bytes()),
            "deleted": False,
        }
        manifest["self_sha256"] = _sha256(_canonical(manifest))
        self._write_json(segment.with_suffix(".manifest.json"), manifest)

    def verify_integrity(self, trace_id: str) -> bool:
        if not _safe_id(trace_id):
            raise ValueError("invalid trace id")
        segment = self.root / f"{trace_id}.jsonl"
        manifest_path = self.root / f"{trace_id}.manifest.json"
        if not segment.is_file() or not manifest_path.is_file():
            raise FileNotFoundError("trace is unavailable")
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            if manifest.get("segment_sha256") != _sha256(segment.read_bytes()):
                raise ValueError("trace integrity check failed")
            lines = segment.read_bytes().splitlines(keepends=True)
            expected = manifest.get("line_sha256")
            if not isinstance(expected, list) or len(expected) != len(lines):
                raise ValueError("trace integrity receipt mismatch")
            for line, receipt in zip(lines, expected):
                event = json.loads(line.decode("utf-8"))
                if event.get("line_sha256") != receipt:
                    raise ValueError("trace integrity receipt mismatch")
                if _sha256(canonical_event_bytes(event, include_hash=False)) != receipt:
                    raise ValueError("trace integrity receipt mismatch")
            unsigned = dict(manifest)
            self_sha = unsigned.pop("self_sha256", None)
            if self_sha != _sha256(_canonical(unsigned)):
                raise ValueError("trace integrity manifest mismatch")
        except (OSError, UnicodeDecodeError, json.JSONDecodeError, TypeError) as exc:
            raise ValueError("trace integrity check failed") from exc
        return True

    def exact_replay(self, trace_id: str) -> None:
        raise NotImplementedError("Exact replay is forbidden for Minimal trace")

    def replay(self, trace_id: str) -> dict[str, Any]:
        if not _safe_id(trace_id):
            raise ValueError("invalid trace id")
        tombstones = self._read_tombstones()
        if any(item.get("trace_id") == trace_id for item in tombstones):
            raise TraceDeletedError("trace has been deleted")
        segment = self.root / f"{trace_id}.jsonl"
        manifest = self.root / f"{trace_id}.manifest.json"
        if not segment.is_file() or not manifest.is_file():
            raise FileNotFoundError("trace is unavailable")
        value = json.loads(manifest.read_text(encoding="utf-8"))
        self.verify_integrity(trace_id)
        return value

    def delete_trace(self, trace_id: str) -> bool:
        if not _safe_id(trace_id):
            raise ValueError("invalid trace id")
        self.root.mkdir(parents=True, exist_ok=True)
        for suffix in (".jsonl", ".manifest.json"):
            path = self.root / f"{trace_id}{suffix}"
            if path.exists():
                path.unlink()
        tombstones = self._read_tombstones()
        if not any(item.get("trace_id") == trace_id for item in tombstones):
            tombstones.append({"trace_id": trace_id, "deleted_at": int(time.time())})
            self._write_json(self._tombstone_path, tombstones)
        return True

    def _read_tombstones(self) -> list[dict[str, Any]]:
        if not self._tombstone_path.is_file():
            return []
        value = json.loads(self._tombstone_path.read_text(encoding="utf-8"))
        return value if isinstance(value, list) else []

    def prune(self, now: float | None = None) -> int:
        if not self.root.is_dir():
            return 0
        cutoff = (time.time() if now is None else now) - RETENTION_DAYS * 86400
        removed = 0
        for path in self.root.glob("*.jsonl"):
            if path.stat().st_mtime < cutoff:
                trace_id = path.stem
                self.delete_trace(trace_id)
                removed += 1
        return removed

    def patrol(self) -> dict[str, Any]:
        """只读完整性巡检（owner 锁定 PATROL_INTERVAL = every_50_traces）。

        输出 trace 计数、逐条 verify_integrity 结论与磁盘占用；失败条目
        仅列 trace_id 与原因类别，不读取/回显任何事件内容，不修改任何
        文件——巡检只看完整性，不看语义、不改策略。
        """
        segments = sorted(self.root.glob("*.jsonl")) if self.root.is_dir() else []
        verified = 0
        failed: list[dict[str, str]] = []
        total_bytes = 0
        for segment in segments:
            trace_id = segment.stem
            total_bytes += segment.stat().st_size
            try:
                self.verify_integrity(trace_id)
                verified += 1
            except FileNotFoundError:
                failed.append({"trace_id": trace_id, "reason": "manifest_missing"})
            except ValueError:
                failed.append({"trace_id": trace_id, "reason": "integrity_failed"})
        return {
            "root": str(self.root),
            "trace_count": len(segments),
            "verified": verified,
            "failed": failed,
            "total_bytes": total_bytes,
            "integrity": "ok" if not failed else "failed",
        }


def main(argv: list[str] | None = None) -> int:
    """``python -m src.production_observability`` 入口；唯一子命令 ``patrol``。

    退出码约定：0 = 全部通过（含零 trace 的空库）；1 = 存在完整性失败；
    2 = 用法/路径非法（含仓库内 root 被防泄漏守卫拒绝）。输出为 JSON
    摘要，绝不包含事件正文。
    """
    import argparse

    parser = argparse.ArgumentParser(
        prog="python -m src.production_observability",
        description="本地 Minimal 观测 trace 的只读巡检工具",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    patrol_parser = subparsers.add_parser(
        "patrol", help="只读完整性巡检：trace 计数 / 完整性结论 / 磁盘占用")
    patrol_parser.add_argument(
        "--root", default="",
        help="traces 根目录（默认 MNEME_DATA_DIR/traces，未设时 ~/.mneme/traces）")
    args = parser.parse_args(argv)

    if args.root:
        root = Path(args.root).expanduser().resolve()
    else:
        data_dir = os.getenv("MNEME_DATA_DIR", "").strip()
        base = Path(data_dir).expanduser() if data_dir else Path.home() / ".mneme"
        root = (base / "traces").resolve()
    try:
        store = TraceStore(root)
    except ValueError as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False))
        return 2
    report = store.patrol()
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 1 if report["failed"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
