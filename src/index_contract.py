"""Chunk snapshot index contract — manifest-constrained reproducible indexing.

Phase 6-B0 产品能力：把 "chunk 身份可复现" 做成受 manifest 约束的显式契约。

背景（Phase 6-A 结论）：冻结 v2.0.11 语料的 chunks 由 ``get_splitter``（纯
RecursiveCharacterTextSplitter）构建；当前运行时 ``_load_index_chunks`` 走
src/loaders + src/chunking v3 Section 分块，重建为 2947 chunks（1006 冻结
chunks 仅 27% 精确复现），因此冻结 evidence 的 chunk 级真值无法直接映射到
当前 parser 输出。本模块提供**显式请求时**的替代输入：调用方给出经过验证的
chunks snapshot（chunks.jsonl + chunk-manifest.json + corpus-manifest.json +
源文件集合），contract 全量验证通过后交给 ``src.rag.prepare_index`` /
``build_index`` 建索引；默认从原文件解析的产品路径行为不变。

验证全部发生在任何 collection / sidecar 写入之前；任一检查失败即抛
``SnapshotContractError``（fail-closed，绝不回退为 parser，零残留）。
Phase 6-B0.1 硬化：snapshot 保留输入身份（chunks / chunk-manifest /
corpus-manifest 路径），产品入口（``src.rag.prepare_index`` /
``build_index``）在使用时经 ``verify_snapshot_current`` **重新执行**验证
并比对重建指纹 / chunk 内容 / source 集合——对象必须仍可由其受验证输入
重建（伪造、dataclasses.replace 篡改、载入后输入漂移一律拒绝），且拒绝
发生在任何 client / 模型 / collection / sidecar 写入之前。

身份规则（与产品一致）：
- ``source_id`` = ``src.rag.source_id_for_path``（sha256(normcase(realpath))，
  全 64 位）；冻结 chunk_id 的 12 位前缀必须等于 ``source_id[:12]``；
- 禁止用 basename 或正文文本作为删除/映射/身份主键——basename 仅作展示与
  evidence 对齐字段（source_name），身份主键始终是 source_id/source_path；
- 指纹 = sha256(contract_version + 三个输入 SHA + source 身份 + 逐 chunk
  文本哈希)；指纹进入 collection manifest 的 ``config.snapshot``，变化触发
  安全重建，绝不误复用旧索引。

CLI：``python -m src.index_contract build --chunks ... --chunk-manifest ...
--corpus-manifest ... --collection ... [--data-dir ...] [--force-rebuild]``
退出码：0=成功；2=contract 验证失败（fail-closed，零写入）；1=其他错误。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

# 仓库根：corpus-manifest.json 的 path 字段是相对仓库根的路径
REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

# contract 版本参与指纹；版本变化 → 指纹变化 → 安全重建
CONTRACT_VERSION = "chunk-snapshot-contract-1"

# 冻结 chunk_id 标准格式：{source_sha256_prefix12}_chunk_{n}
_CHUNK_ID_RE = re.compile(r"^([0-9a-f]{12})_chunk_(\d+)$")


class SnapshotContractError(ValueError):
    """Contract 验证失败——fail-closed，零写入。

    ``drift`` 是结构化失败清单（name/kind/detail），供报告与测试断言。
    """

    def __init__(self, message: str, drift: list[dict]) -> None:
        super().__init__(message)
        self.drift = drift


# ── 哈希与序列化（与项目 manifest 约定一致）───────────────────────────

def sha256_bytes(path: Path) -> str:
    """文件字节 SHA-256。"""
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def compact_json(obj: Any) -> str:
    """指纹序列化：紧凑、sort_keys、ensure_ascii=False。"""
    return json.dumps(obj, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"))


def fingerprint_of(payload: dict) -> str:
    """对 payload 计算契约指纹。"""
    return sha256_text(compact_json(payload))


# ── 领域对象 ──────────────────────────────────────────────────────────

@dataclass(frozen=True)
class SnapshotSource:
    """一份已验证的源文档身份（全部字段来自 corpus-manifest + 磁盘复算）。"""
    id: str                 # 全 64 位 source_id（sha256(normcase(realpath))）
    path: str               # canonical 绝对路径
    name: str               # basename（展示 / evidence 对齐字段）
    file_type: str          # "text" | "pdf" | "docx"（按扩展名检测）
    content_sha256: str     # 源文件内容 SHA（已与磁盘字节核验）
    size: int               # 源文件字节数（已核验）
    chunk_ids: tuple[str, ...]  # 该 source 的 chunk_id 集合（已核验前缀）

    def to_manifest_record(self, mtime_ns: int) -> dict:
        """转为 collection manifest 的 source record（与 _manifest_source_record 同形）。"""
        return {
            "source_id": self.id,
            "source_path": self.path,
            "source_name": self.name,
            "source": self.name,
            "file_type": self.file_type,
            "content_sha256": self.content_sha256,
            "source_size": self.size,
            "source_mtime_ns": mtime_ns,
            "chunk_ids": sorted(self.chunk_ids),
        }


@dataclass(frozen=True)
class ChunkSnapshot:
    """验证通过的 chunks snapshot——不可变，可直接交给产品索引入口。

    ``config()`` 返回进入 collection manifest ``config.snapshot`` 的段；
    ``to_index_data()`` 返回产品索引所需的 (texts, metadatas, ids,
    source_records)。

    provenance 字段（chunks_path / chunk_manifest_path /
    corpus_manifest_path / repo_root）保留输入身份：产品入口
    （``src.rag.prepare_index`` / ``build_index``）在使用时**重新执行**
    ``load_chunk_snapshot`` 验证并比对重建指纹/内容/来源集合——对象必须
    仍可由其受验证输入重建，内存对象本身不被信任（Phase 6-B0.1 硬化）。
    """
    contract_version: str
    chunks: tuple[dict, ...]              # 按 chunk_id 排序的 {chunk_id,index,source,text}
    sources: tuple[SnapshotSource, ...]   # 按 id 排序
    chunk_text_sha256: dict[str, str]     # chunk_id -> sha256(text)
    chunks_sha256: str                    # chunk-manifest 声明的文件级哈希（已验证）
    chunk_manifest_sha256: str            # chunk-manifest.json 字节 SHA
    corpus_manifest_sha256: str           # corpus-manifest.json 字节 SHA
    validation: tuple[dict, ...]          # 逐项检查记录（全部 ok）
    fingerprint: str                      # 契约指纹（进入 manifest config.snapshot）
    # ── provenance：载入时的输入身份（入口复核用）──
    chunks_path: str = ""
    chunk_manifest_path: str = ""
    corpus_manifest_path: str = ""
    repo_root: str = ""

    def config(self) -> dict:
        """进入 collection manifest config.snapshot 的契约段。"""
        return {
            "contract_version": self.contract_version,
            "fingerprint": self.fingerprint,
            "chunks_sha256": self.chunks_sha256,
            "chunk_manifest_sha256": self.chunk_manifest_sha256,
            "corpus_manifest_sha256": self.corpus_manifest_sha256,
        }

    def source_paths(self) -> list[str]:
        """声明并已验证的源文件 canonical 路径（顺序 = sources 排序）。"""
        return [s.path for s in self.sources]

    def to_index_data(self) -> tuple[list[str], list[dict], list[str], list[dict]]:
        """产品索引数据：(texts, metadatas, ids, source_records)。

        metadata 保留稳定 chunk_id / source_id / source_name / 内容 SHA /
        chunk index——citation lineage 依赖这些字段。
        """
        import src.rag as rag

        texts = [c["text"] for c in self.chunks]
        ids = [c["chunk_id"] for c in self.chunks]
        src_by_name = {s.name: s for s in self.sources}
        metadatas: list[dict] = []
        for c in self.chunks:
            src = src_by_name[c["source"]]
            metadatas.append({
                "chunk_id": c["chunk_id"],
                "chunk_index": c["index"],
                "source_id": src.id,
                "source_path": src.path,
                "source_name": src.name,
                "source": src.name,          # 兼容字段（与产品一致）
                "file_type": src.file_type,
                "content_sha256": src.content_sha256,
                "source_size": src.size,
                "source_mtime_ns": os.stat(src.path).st_mtime_ns,
            })
        source_records = [
            s.to_manifest_record(os.stat(s.path).st_mtime_ns)
            for s in self.sources
        ]
        return texts, metadatas, ids, source_records


# ── 载入与验证（fail-closed）──────────────────────────────────────────

def _read_jsonl(path: Path) -> list[dict]:
    """解析 JSONL，行级解码错误给出精确行号。"""
    rows: list[dict] = []
    with open(path, encoding="utf-8") as stream:
        for line_no, line in enumerate(stream, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError as exc:
                raise ValueError(
                    f"invalid JSONL at {path} line {line_no}: {exc}") from exc
    return rows


def _load_sources(
    per_source: dict[str, int],
    chunk_sources: set[str],
    corpus_manifest: dict,
    repo_root: Path,
    checks: list[dict],
) -> dict[str, SnapshotSource]:
    """把 per_source 名 ↔ corpus-manifest 文档 ↔ 磁盘文件三方对齐。"""
    import src.rag as rag

    sources: dict[str, SnapshotSource] = {}
    docs_by_name: dict[str, dict] = {}
    for d in corpus_manifest.get("documents", []):
        name = Path(str(d.get("path", "")).replace("\\", "/")).name
        docs_by_name.setdefault(name, []).append(d)
    for name in sorted(per_source):
        docs = docs_by_name.get(name, [])
        if len(docs) != 1:
            checks.append({
                "name": "source_declared_in_corpus_manifest",
                "ok": False,
                "detail": f"source {name!r}: corpus-manifest 匹配文档数={len(docs)}（应为 1）",
            })
            continue
        doc = docs[0]
        rel = str(doc.get("path", "")).replace("\\", "/")
        path = rag.canonical_source_path(str(repo_root / rel))
        ok_file = os.path.isfile(path)
        checks.append({
            "name": "source_file_exists",
            "ok": ok_file,
            "detail": f"{name}: {path}",
        })
        if not ok_file:
            continue
        actual_sha = sha256_bytes(path)
        checks.append({
            "name": "source_content_sha256",
            "ok": actual_sha == doc.get("file_sha256"),
            "detail": f"{name}: actual={actual_sha} declared={doc.get('file_sha256')}",
        })
        stat = os.stat(path)
        checks.append({
            "name": "source_size",
            "ok": stat.st_size == doc.get("size"),
            "detail": f"{name}: actual={stat.st_size} declared={doc.get('size')}",
        })
        try:
            file_type = rag.detect_file_type(path)
        except ValueError as exc:
            file_type = "unknown"
            checks.append({
                "name": "source_file_type",
                "ok": False,
                "detail": f"{name}: {exc}",
            })
        sources[name] = SnapshotSource(
            id=rag.source_id_for_path(path),
            path=path,
            name=name,
            file_type=file_type,
            content_sha256=doc.get("file_sha256", ""),
            size=int(doc.get("size", -1)),
            chunk_ids=tuple(),
        )
    return sources


def load_chunk_snapshot(
    *,
    chunks_path: Path,
    chunk_manifest_path: Path,
    corpus_manifest_path: Path,
    source_paths: list[str] | None = None,
    repo_root: Path | None = None,
    contract_version: str | None = None,
) -> ChunkSnapshot:
    """载入并全量验证 chunks snapshot；任一检查失败 → SnapshotContractError。

    验证（全部发生在任何 collection / sidecar 写入之前）：
    - chunk-manifest self 一致性（chunks_sha256 复算、n_chunks/n_documents/
      per_source 计数）；
    - chunk_id 唯一性 / 格式 {12hex}_chunk_{n} / index 连续 / text 非空；
    - source 身份：corpus-manifest 声明的 canonical path + 内容 SHA + size 与
      磁盘一致；source_id 全 64 位且 chunk_id 前缀 == source_id[:12]；
    - 调用方提供的 source_paths 与声明集合**精确一致**（无缺失/无额外）；
    - 逐 chunk 文本完整性哈希（进入指纹）。
    """
    repo_root = Path(repo_root or REPO_ROOT)
    # 调用期解析：CONTRACT_VERSION 可被测试替换，版本变化 → 指纹变化 → 重建
    if contract_version is None:
        contract_version = CONTRACT_VERSION
    checks: list[dict] = []
    def _check(name: str, ok: bool, detail: str = "") -> None:
        checks.append({"name": name, "ok": bool(ok), "detail": detail})

    # ── 1. chunk-manifest.json ──
    try:
        chunk_manifest = json.loads(
            Path(chunk_manifest_path).read_text(encoding="utf-8"))
        _check("chunk_manifest_parses", isinstance(chunk_manifest, dict))
    except (OSError, ValueError) as exc:
        _check("chunk_manifest_parses", False, str(exc))
        chunk_manifest = {}

    # ── 2. chunks.jsonl 解析 ──
    try:
        rows = _read_jsonl(Path(chunks_path))
        _check("chunks_parse", True)
    except (OSError, ValueError) as exc:
        _check("chunks_parse", False, str(exc))
        rows = []

    # ── 3. chunks_sha256 复算（corpus_v2_prepare 约定：逐行 canonical JSON
    #    以 \n 连接后 sha256——内容级验证，与文件排版无关）──
    declared_sha = chunk_manifest.get("chunks_sha256", "")
    recomputed = sha256_text("\n".join(
        json.dumps(r, ensure_ascii=False, sort_keys=True) for r in rows))
    _check("chunks_sha256", bool(rows) and recomputed == declared_sha,
           f"recomputed={recomputed} declared={declared_sha}")

    # ── 4. 计数与 per_source ──
    n_rows = len(rows)
    _check("n_chunks", chunk_manifest.get("n_chunks") == n_rows,
           f"declared={chunk_manifest.get('n_chunks')} actual={n_rows}")
    per_source = chunk_manifest.get("per_source", {})
    if not isinstance(per_source, dict):
        per_source = {}
    actual_counts: dict[str, int] = {}
    for r in rows:
        actual_counts[r.get("source", "")] = actual_counts.get(r.get("source", ""), 0) + 1
    _check("n_documents",
           chunk_manifest.get("n_documents") == len(actual_counts),
           f"declared={chunk_manifest.get('n_documents')} actual={len(actual_counts)}")
    _check("per_source_counts", actual_counts == per_source,
           f"actual={actual_counts} declared={per_source}")

    # ── 5. chunk_id 唯一性 / 格式 / index / source / text ──
    seen_ids: set[str] = set()
    dup_ids: list[str] = []
    for r in rows:
        cid = r.get("chunk_id", "")
        if cid in seen_ids:
            dup_ids.append(cid)
        seen_ids.add(cid)
    _check("chunk_id_uniqueness", not dup_ids, f"duplicates={sorted(set(dup_ids))[:5]}")

    bad_format: list[str] = []
    for r in rows:
        cid = r.get("chunk_id", "")
        m = _CHUNK_ID_RE.match(cid)
        if not m or int(m.group(2)) != r.get("index"):
            bad_format.append(cid)
    _check("chunk_id_format", not bad_format,
           f"bad={bad_format[:5]}（期望 {12}hex_chunk_n 格式）"
           if bad_format else "ok")

    # per-source index 连续性
    indexes_by_source: dict[str, list[int]] = {}
    for r in rows:
        indexes_by_source.setdefault(r.get("source", ""), []).append(r.get("index"))
    bad_contiguity: list[str] = []
    for source, indexes in indexes_by_source.items():
        if sorted(indexes) != list(range(len(indexes))):
            bad_contiguity.append(f"{source}: {sorted(indexes)}")
    _check("chunk_index_contiguity", not bad_contiguity,
           "; ".join(bad_contiguity[:5]))

    bad_source: list[str] = []
    empty_texts: list[str] = []
    for r in rows:
        if r.get("source") not in per_source:
            bad_source.append(r.get("chunk_id", ""))
        if not r.get("text"):
            empty_texts.append(r.get("chunk_id", ""))
    _check("source_name_in_per_source", not bad_source,
           f"bad={bad_source[:5]}")
    _check("chunk_text_nonempty", not empty_texts,
           f"empty={empty_texts[:5]}")

    # ── 6. corpus-manifest.json ──
    try:
        corpus_manifest = json.loads(
            Path(corpus_manifest_path).read_text(encoding="utf-8"))
        _check("corpus_manifest_parses", isinstance(corpus_manifest, dict)
               and isinstance(corpus_manifest.get("documents", []), list))
    except (OSError, ValueError) as exc:
        _check("corpus_manifest_parses", False, str(exc))
        corpus_manifest = {}

    if isinstance(corpus_manifest, dict):
        docs_sorted = sorted(
            corpus_manifest.get("documents", []), key=lambda d: d.get("id", ""))
        # 复现 evaluation.corpus_v2.build_corpus_manifest 的 canonical 约定
        # （json.dumps ensure_ascii=False sort_keys=True，默认分隔符）
        self_sha = sha256_text(json.dumps({
            "corpus_version": corpus_manifest.get("corpus_version"),
            "documents": docs_sorted,
        }, ensure_ascii=False, sort_keys=True))
        _check("corpus_manifest_self_hash",
               self_sha == corpus_manifest.get("manifest_sha256"),
               f"recomputed={self_sha} declared={corpus_manifest.get('manifest_sha256')}")

    # ── 7. source 身份三方对齐（per_source ↔ corpus-manifest ↔ 磁盘）──
    sources = _load_sources(per_source, set(actual_counts), corpus_manifest,
                            repo_root, checks)

    # chunk_id 前缀 == source_id[:12]
    prefix_bad: list[str] = []
    for r in rows:
        src = sources.get(r.get("source", ""))
        if src is None:
            continue
        m = _CHUNK_ID_RE.match(r.get("chunk_id", ""))
        if m and m.group(1) != src.id[:12]:
            prefix_bad.append(r["chunk_id"])
    _check("chunk_id_prefix_matches_source", not prefix_bad,
           f"bad={prefix_bad[:5]}")

    # ── 8. 调用方 source_paths 与声明集合精确一致 ──
    if source_paths is not None:
        import src.rag as rag
        declared_set = {rag.canonical_source_path(s.path) for s in sources.values()}
        provided_set = {rag.canonical_source_path(p) for p in source_paths}
        _check("source_paths_exact_match", declared_set == provided_set,
               f"missing={sorted(declared_set - provided_set)[:3]} "
               f"extra={sorted(provided_set - declared_set)[:3]}")

    # ── fail-closed：任一检查失败 → 抛错，零写入 ──
    drift = [
        {"name": c["name"], "detail": c["detail"]}
        for c in checks if not c["ok"]
    ]
    if drift:
        raise SnapshotContractError(
            f"chunk snapshot contract validation failed: "
            f"{len(drift)} drift item(s)", drift)

    # ── 9. 逐 chunk 文本完整性哈希 + source 组装 + 指纹 ──
    chunk_text_sha256 = {
        r["chunk_id"]: sha256_text(r["text"]) for r in rows
    }
    chunks = tuple(sorted(rows, key=lambda r: r["chunk_id"]))
    source_objs: list[SnapshotSource] = []
    for name in sorted(sources):
        src = sources[name]
        source_objs.append(SnapshotSource(
            id=src.id, path=src.path, name=src.name, file_type=src.file_type,
            content_sha256=src.content_sha256, size=src.size,
            chunk_ids=tuple(sorted(
                r["chunk_id"] for r in rows if r["source"] == name)),
        ))
    sources_tuple = tuple(source_objs)

    fingerprint = fingerprint_of({
        "contract_version": contract_version,
        "chunks_sha256": recomputed,
        "chunk_manifest_sha256": sha256_bytes(chunk_manifest_path),
        "corpus_manifest_sha256": sha256_bytes(corpus_manifest_path),
        "sources": [
            {"id": s.id, "path": s.path, "name": s.name,
             "file_type": s.file_type, "content_sha256": s.content_sha256,
             "size": s.size, "chunk_count": len(s.chunk_ids)}
            for s in sources_tuple
        ],
        "chunk_text_sha256": dict(sorted(chunk_text_sha256.items())),
    })

    return ChunkSnapshot(
        contract_version=contract_version,
        chunks=chunks,
        sources=sources_tuple,
        chunk_text_sha256=chunk_text_sha256,
        chunks_sha256=recomputed,
        chunk_manifest_sha256=sha256_bytes(chunk_manifest_path),
        corpus_manifest_sha256=sha256_bytes(corpus_manifest_path),
        validation=tuple(checks),
        fingerprint=fingerprint,
        # provenance：保留输入身份，供产品入口使用时重新验证
        chunks_path=str(Path(chunks_path)),
        chunk_manifest_path=str(Path(chunk_manifest_path)),
        corpus_manifest_path=str(Path(corpus_manifest_path)),
        repo_root=str(repo_root),
    )


def verify_snapshot_current(
    snapshot: ChunkSnapshot,
    *,
    contract_version: str | None = None,
) -> ChunkSnapshot:
    """产品入口复核（Phase 6-B0.1 硬化）：snapshot 必须仍可由其受验证
    输入重建。

    ``src.rag.prepare_index`` / ``build_index`` 在**任何 PersistentClient /
    模型加载 / collection / manifest / BM25 sidecar 写入之前**调用本函数；
    任一漂移 → ``SnapshotContractError``（fail-closed，绝不回退 parser）。

    复核项（对 snapshot 保留的输入路径重跑全量验证后逐项比对）：
    1. 输入文件（chunks / chunk-manifest / corpus-manifest / 源文件）当前
       状态重跑 ``load_chunk_snapshot`` 验证——载入后任何漂移 → 失败；
    2. 重建契约指纹 == 原 snapshot.fingerprint——伪造 fingerprint → 失败；
    3. 重建 chunk 内容 == 原 snapshot.chunks——dataclasses.replace 篡改
       文本/ID（即使保留原指纹）→ 失败；
    4. 重建 source 集合 == 原 snapshot 集合——身份主键始终是 canonical
       path 与全 64 位 source_id，不用 basename。

    返回**重建后的新 snapshot**：索引内容永远来自磁盘受验证输入的重建，
    绝不来自内存对象。
    """
    if contract_version is None:
        contract_version = CONTRACT_VERSION
    fresh = load_chunk_snapshot(
        chunks_path=Path(snapshot.chunks_path),
        chunk_manifest_path=Path(snapshot.chunk_manifest_path),
        corpus_manifest_path=Path(snapshot.corpus_manifest_path),
        source_paths=snapshot.source_paths(),
        repo_root=Path(snapshot.repo_root) if snapshot.repo_root else None,
        contract_version=contract_version,
    )
    drift: list[dict] = []
    if fresh.fingerprint != snapshot.fingerprint:
        drift.append({
            "name": "snapshot_revalidation_fingerprint",
            "detail": f"recomputed={fresh.fingerprint[:16]}… "
                      f"declared={snapshot.fingerprint[:16]}…",
        })
    if fresh.chunks != snapshot.chunks:
        drift.append({
            "name": "snapshot_revalidation_chunks",
            "detail": "rebuilt chunk content differs from the in-memory "
                      "snapshot (tampered chunks)",
        })
    fresh_paths = {s.path for s in fresh.sources}
    snapshot_paths = {s.path for s in snapshot.sources}
    if fresh_paths != snapshot_paths:
        drift.append({
            "name": "snapshot_revalidation_sources",
            "detail": f"missing={sorted(fresh_paths - snapshot_paths)[:3]} "
                      f"extra={sorted(snapshot_paths - fresh_paths)[:3]}",
        })
    if drift:
        raise SnapshotContractError(
            "snapshot revalidation failed (forged, tampered, or inputs "
            f"changed since load): {len(drift)} drift item(s)", drift)
    return fresh


# ── CLI ───────────────────────────────────────────────────────────────

def _cmd_build(args: argparse.Namespace) -> int:
    """build：验证 snapshot → 全产品索引入口建索引。失败零写入。"""
    if args.source_paths:
        declared_sources = list(args.source_paths)
    else:
        corpus_docs = json.loads(
            Path(args.corpus_manifest).read_text(encoding="utf-8"))
        root = Path(args.repo_root or REPO_ROOT)
        declared_sources = [
            str(root / d["path"].replace("\\", "/"))
            for d in corpus_docs.get("documents", [])
        ]
    try:
        snapshot = load_chunk_snapshot(
            chunks_path=args.chunks,
            chunk_manifest_path=args.chunk_manifest,
            corpus_manifest_path=args.corpus_manifest,
            source_paths=declared_sources,
            repo_root=args.repo_root,
        )
    except SnapshotContractError as exc:
        print("FAIL-CLOSED: chunk snapshot contract validation failed, "
              "zero writes.", file=sys.stderr)
        for d in exc.drift:
            print(f"  [{d['name']}] {d['detail']}", file=sys.stderr)
        return 2
    except (OSError, ValueError) as exc:
        print(f"contract load error: {exc}", file=sys.stderr)
        return 1

    if args.data_dir is not None:
        chroma_path = Path(args.data_dir)
        chroma_path.mkdir(parents=True, exist_ok=True)
    else:
        from src.config import get_settings
        chroma_path = get_settings().chroma_db_path

    import src.rag as rag

    try:
        model, collection, bm25, docs, metas = rag.prepare_index(
            file_paths=snapshot.source_paths(),
            collection_name=args.collection,
            force_rebuild=args.force_rebuild,
            snapshot=snapshot,
            chroma_path=str(chroma_path),
        )
    except Exception as exc:
        import traceback
        traceback.print_exc(file=sys.stderr)
        return 1

    manifest = rag.load_index_manifest(args.collection, chroma_path=str(chroma_path))
    print(f"index ready: collection={args.collection} "
          f"chunks={collection.count()} sources={len(snapshot.sources)}")
    print(f"  snapshot fingerprint={snapshot.fingerprint}")
    print(f"  manifest_version={manifest.get('manifest_version') if manifest else None} "
          f"config.snapshot={'recorded' if manifest and manifest.get('config', {}).get('snapshot') else 'missing'}")
    return 0


def main(argv: list[str] | None = None) -> int:
    """CLI 入口。退出码：0=成功；2=contract 验证失败（零写入）；1=其他。"""
    parser = argparse.ArgumentParser(
        prog="python -m src.index_contract",
        description="Chunk snapshot index contract (Phase 6-B0)")
    sub = parser.add_subparsers(dest="command", required=True)

    build = sub.add_parser("build", help="validate snapshot and build index "
                                         "through the full product path")
    build.add_argument("--chunks", type=Path, required=True)
    build.add_argument("--chunk-manifest", type=Path, required=True)
    build.add_argument("--corpus-manifest", type=Path, required=True)
    build.add_argument("--collection", required=True)
    build.add_argument("--data-dir", type=Path, default=None,
                       help="Chroma 数据目录（默认：产品 settings 的 chroma_db_path）")
    build.add_argument("--repo-root", type=Path, default=None,
                       help="corpus-manifest 相对路径的解析根（默认：仓库根）")
    build.add_argument("--source-paths", nargs="*", default=None,
                       help="调用方源文件集合；默认取 corpus-manifest 声明集合")
    build.add_argument("--force-rebuild", action="store_true")

    args = parser.parse_args(argv)
    if args.command == "build":
        return _cmd_build(args)
    parser.error(f"unknown command: {args.command}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
