"""G1-S synthetic query-plan capture / seal / replay — 显式 harness 入口。

范围（与 Phase 6-G1-S / G1-S.1 授权一致）：
- capture 仅在 issuer 签发的 SyntheticCaptureCapability（绑定
  SyntheticCaptureContext：新建输出根 + synthetic chunks 文件）下写盘；
  默认产品路径（answer_query/answer_query_stream）零 I/O、不感知本模块；
- chunks contract 强制：capture 记录 chunks 字节 SHA/行数/稳定 chunk_id
  映射并校验与 metadatas 一一对应；replay 必须提供同一 chunks 输入，
  缺失/漂移/映射漂移一律 fail-closed，不兼容无契约的旧 capture；
- synthetic 边界运行时强制：输出根与 chunks 输入解析后落入受保护评测
  资产树（冻结基线所在树）的，在读写前拒绝；输出根必须是新建目标；
  这是误用防护 + fail-closed 边界强制，不是安全沙箱（不宣称抵抗同进程
  恶意代码）；
- 不捕获原始 LLM response、不实现 observability/加密/留存/撤销（G1-P）。

对象边界：_RuntimeQueryPlan（运行期，src.rag）→ CapturedQueryPlan（本模块
序列化/反序列化，src.domain）→ _ReplayQueryPlan（本模块，chunk_id→index
映射，注入 prepare_answer_evidence(query_plan=...)，零 LLM/零检索）。

profile 隔离：capture 只接受 planning_profile="sync" 且 retrieval_k=None
（prepare_answer_evidence 普通分支）的 runtime plan；answer_query_stream
产生的 plan（profile="stream"）或检索宽度与 sync contract 不一致的 plan
在写文件前 fail-closed。

seal 字节约定（沿用仓库惯例，Windows 显式 LF）：
- JSONL 行：ensure_ascii=False, sort_keys=True, separators=(",", ":") + "\\n"
- manifest：ensure_ascii=False, indent=1, sort_keys=True + "\\n"
- line_sha256 = 移除自身字段后的 canonical 行 SHA
- manifest 覆盖：有序 line_hashes、原始 JSONL bytes SHA、有序 outputs
  receipt SHA、pop 自身后的 manifest self-hash；无时间戳/路径进入 canonical。
"""
from __future__ import annotations

import hashlib
import inspect
import json
import math
import os
import warnings
from dataclasses import dataclass
from pathlib import Path

from src.domain import (
    CapturedCandidateHit,
    CapturedEvidenceReceipt,
    CapturedQueryPlan,
    StageProvenance,
)

CAPTURE_SCHEMA_VERSION = 1
REPLAY_ENGINE_SEMVER = "g1s-replay-engine-1.0"
CAPTURE_MODE = "synthetic_only"
CAPTURE_FILE_NAME = "capture.jsonl"
MANIFEST_FILE_NAME = "capture.manifest.json"
SYNC_PLANNING_PROFILE = "sync"

# ═══════════════════════════════════════════════════════════════
# capability + synthetic context（误用防护，非安全边界）
# ═══════════════════════════════════════════════════════════════

@dataclass(frozen=True, slots=True)
class SyntheticCaptureContext:
    """issuer 绑定的 synthetic capture 上下文：新建输出根 + chunks 文件。

    - output_root：capture 的新建目标（capture 前必须不存在）；
    - chunks_path：synthetic chunks 文件（capture 记录契约；replay 必供）。
    路径边界由 issuer 强制（create_context / create_capability / 每次
    使用时三重校验），不把边界责任交给调用方。
    """
    output_root: Path
    chunks_path: Path


class SyntheticCaptureCapability:
    """synthetic capture 授权对象：仅 SYNTHETIC_CAPTURE_ISSUER 可签发。

    - 身份校验：issuer 私有 marker 的 identity 比对——普通调用方直接构造
      ``SyntheticCaptureCapability(object(), ctx)`` 会被拒绝；
    - context 绑定：output_root 与 chunks_path 只能来自 issuer 校验过的
      SyntheticCaptureContext，任意 Path 不构成 escape hatch；
    - 使用期每次 _require_capability 都重校验路径边界（context 事后被
      篡改指向受保护树也必须 fail-closed）。
    这是误用防护（防止把生产流量无意识写入 trace），不宣称抵抗同进程
    恶意反射。
    """
    __slots__ = ("_token", "_context")

    def __init__(self, token: object, context: SyntheticCaptureContext):
        self._token = token
        self._context = context

    def __reduce__(self):
        raise TypeError("SyntheticCaptureCapability is not serializable")

    @property
    def context(self) -> SyntheticCaptureContext:
        return self._context


class _SyntheticCaptureIssuer:
    """唯一可签发 SyntheticCaptureCapability 的 issuer（测试/harness 使用）。"""

    def __init__(self):
        self._marker = object()

    def create_context(self, output_root, chunks_path) -> SyntheticCaptureContext:
        """创建 synthetic capture context（先做路径边界校验）。"""
        output_root = Path(output_root)
        chunks_path = Path(chunks_path)
        _assert_synthetic_boundary(output_root, chunks_path)
        return SyntheticCaptureContext(
            output_root=output_root, chunks_path=chunks_path,
        )

    def create_capability(self, context) -> SyntheticCaptureCapability:
        """从 context 签发 capability（再次校验路径，防绕过 create_context）。"""
        if not isinstance(context, SyntheticCaptureContext):
            raise TypeError(
                "capability requires a SyntheticCaptureContext "
                "from create_context",
            )
        _assert_synthetic_boundary(context.output_root, context.chunks_path)
        return SyntheticCaptureCapability(self._marker, context)


SYNTHETIC_CAPTURE_ISSUER = _SyntheticCaptureIssuer()


def _protected_eval_tree() -> Path:
    """仓库内受保护评测资产树的根（运行时解析，不依赖调用方）。"""
    return Path(__file__).resolve().parents[1] / "evaluation"


def _assert_synthetic_boundary(output_root: Path, chunks_path: Path) -> None:
    """synthetic 路径边界（运行时强制）：解析后路径落入受保护评测资产树
    （含冻结基线所在树）一律拒绝。

    相对路径 / ``..`` / 未创建路径经 resolve 归一后判定；Windows 大小写
    不敏感比较。这是 fail-closed 的边界强制，不是安全沙箱——不宣称抵抗
    同进程恶意代码（恶意代码可直接篡改本模块）。
    """
    protected = _protected_eval_tree().resolve()
    protected_key = os.path.normcase(str(protected))
    for raw in (output_root, chunks_path):
        resolved = Path(raw).resolve()
        key = os.path.normcase(str(resolved))
        if key == protected_key or key.startswith(protected_key + os.sep):
            raise ValueError(
                f"synthetic boundary violation: {resolved} is inside the "
                f"protected evaluation tree {protected}",
            )


def _require_capability(capability) -> SyntheticCaptureCapability:
    if not isinstance(capability, SyntheticCaptureCapability):
        raise ValueError(
            "capture/replay requires a SyntheticCaptureCapability issued by "
            "SYNTHETIC_CAPTURE_ISSUER; plain dict/string scopes are rejected",
        )
    if capability._token is not SYNTHETIC_CAPTURE_ISSUER._marker:
        raise ValueError(
            "capability was not issued by SYNTHETIC_CAPTURE_ISSUER "
            "(directly constructed objects are rejected)",
        )
    # 使用期路径重校验（context 事后被篡改也必须 fail-closed）
    _assert_synthetic_boundary(
        capability.context.output_root, capability.context.chunks_path,
    )
    return capability


# ═══════════════════════════════════════════════════════════════
# canonical 序列化与写盘（LF-only）
# ═══════════════════════════════════════════════════════════════

def _canonical_row_json(obj) -> str:
    """JSONL 行 canonical 化：ensure_ascii=False + sort_keys + 紧凑分隔符。"""
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _canonical_manifest_json(obj) -> str:
    """manifest canonical 化：与 bl6a.canonical_json 同约定（indent=1）。"""
    return json.dumps(obj, ensure_ascii=False, indent=1, sort_keys=True)


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _write_text_lf(path: Path, text: str) -> None:
    """Windows 写盘显式 LF（newline="\\n"），防 CRLF 改变字节 SHA。"""
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)


# ═══════════════════════════════════════════════════════════════
# score 规范化与有序候选指纹
# ═══════════════════════════════════════════════════════════════

def normalize_score(score: float) -> str:
    """有限 float → 规范化可往返字符串（repr 最短表示）。禁止 NaN/Inf/bool。"""
    if isinstance(score, bool) or not isinstance(score, (int, float)):
        raise ValueError(f"score must be a finite float, got {type(score).__name__}")
    value = float(score)
    if not math.isfinite(value):
        raise ValueError("non-finite score is not capturable")
    return repr(value)


def validate_score_str(score_str: str) -> float:
    """规范化 score 字符串 → float；非 canonical（非 repr 往返）fail-closed。"""
    if not isinstance(score_str, str):
        raise ValueError("score must be a string")
    try:
        value = float(score_str)
    except ValueError as exc:
        raise ValueError(f"non-canonical score string: {score_str!r}") from exc
    if not math.isfinite(value) or repr(value) != score_str:
        raise ValueError(f"non-canonical score string: {score_str!r}")
    return value


def compute_base_candidates_fingerprint(hits: list[tuple[int, str, str]]) -> str:
    """有序 [rank, chunk_id, score] 的 SHA-256（保序；交换同分候选改变指纹）。

    与 order-insensitive 的 retrieval_fingerprint 职责不同：本指纹唯一
    证明候选顺序（capture 观察顺序 → replay 注入顺序）。
    """
    payload = [[rank, chunk_id, score] for rank, chunk_id, score in hits]
    return _sha256_text(_canonical_row_json(payload))


def _history_fingerprint(history) -> str | None:
    if history is None:
        return None
    payload = [[q, a] for q, a in history]
    return _sha256_text(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
    )


# ═══════════════════════════════════════════════════════════════
# pipeline contract（capture 记录实际生效值，replay 阻断比对）
# ═══════════════════════════════════════════════════════════════

def effective_pipeline_contract() -> dict:
    """当前进程实际生效的 pipeline 参数快照。

    阻断项（影响 base_candidates → evidence 下游计算）：schema/engine
    semver、reranker 模式、remote_context_limit、compute_context_k 默认
    参数、selector 上限、dynamic top-k 默认范围、adjacent max_expand、
    refusal threshold 解析后生效值（与 rag.retrieval_refused 同一解析
    逻辑：env 有效则取解析值，否则回退 default）。原始 env 字符串只作
    provenance 记录（见 _provenance_block），不参与阻断。prompt/model/
    history 属 provenance（不阻断）。
    """
    from src import rag
    from src.security import remote_context_limit
    from src.domain import compute_context_k
    from src.chunking import expand_with_adjacent

    raw_threshold = os.getenv("RAG_REFUSAL_THRESHOLD")
    try:
        effective_refusal_threshold = (
            float(raw_threshold)
            if raw_threshold is not None
            else rag.DEFAULT_REFUSAL_THRESHOLD
        )
    except (TypeError, ValueError):
        effective_refusal_threshold = rag.DEFAULT_REFUSAL_THRESHOLD

    context_k_sig = inspect.signature(compute_context_k)
    adjacent_sig = inspect.signature(expand_with_adjacent)
    return {
        "schema_version": CAPTURE_SCHEMA_VERSION,
        "replay_engine_semver": REPLAY_ENGINE_SEMVER,
        "reranker_mode": rag.RAG_RERANKER_MODE,
        "remote_context_limit": remote_context_limit(),
        "compute_context_k_defaults": {
            name: context_k_sig.parameters[name].default
            for name in ("token_budget", "avg_chunk_tokens", "min_k", "max_k")
        },
        "selector_max_per_source": rag.SELECTOR_MAX_PER_SOURCE,
        "dynamic_top_k_defaults": [rag.DEFAULT_MIN_K, rag.DEFAULT_MAX_K],
        "adjacent_max_expand": adjacent_sig.parameters["max_expand"].default,
        "refusal_threshold": effective_refusal_threshold,
    }


def _require_reranker_none() -> None:
    """G1-S 首版 replay 仅支持 reranker=none；其它配置 fail-closed。

    直接读 RAG_RERANKER_MODE（不依赖 _get_reranker 对未知值的静默 None 降级）。
    """
    from src import rag
    if rag.RAG_RERANKER_MODE != "none":
        raise ValueError(
            "G1-S capture/replay requires RAG_RERANKER_MODE='none', "
            f"got {rag.RAG_RERANKER_MODE!r}",
        )


# ═══════════════════════════════════════════════════════════════
# chunks contract（G1-S.1：强制）
# ═══════════════════════════════════════════════════════════════

def _chunks_contract(chunks_path: Path) -> dict:
    """synthetic chunks 文件契约：字节 SHA + 行数 + 有序 chunk_id 映射。

    每行必须是含稳定 chunk_id 的 JSON；chunk_id 缺失/重复/非 JSON 行
    fail-closed。chunk_id 映射是 replay 的 chunks 输入与捕获时一致性的
    显式证明（除字节 SHA 外的自描述契约）。
    """
    data = Path(chunks_path).read_bytes()
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError("chunks file is not UTF-8") from exc
    chunk_ids: list[str] = []
    for line_no, line in enumerate(text.splitlines(), start=1):
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"chunks line {line_no} is not valid JSON") from exc
        if not isinstance(obj, dict):
            raise ValueError(f"chunks line {line_no} is not a JSON object")
        chunk_id = obj.get("chunk_id")
        if not isinstance(chunk_id, str) or not chunk_id:
            raise ValueError(f"chunks line {line_no} missing stable chunk_id")
        if chunk_id in chunk_ids:
            raise ValueError(f"duplicate chunk_id in chunks file: {chunk_id}")
        chunk_ids.append(chunk_id)
    return {
        "chunks_bytes_sha256": hashlib.sha256(data).hexdigest(),
        "chunks_line_count": len(data.splitlines()),
        "chunks_chunk_ids": chunk_ids,
    }


def _require_chunks_match_metadatas(chunk_ids: list[str],
                                    metadatas: list[dict]) -> None:
    """chunks 的 chunk_id 映射必须与 metadatas 顺序一一对应（capture 与
    replay 共用）：缺失 / 重复 / 额外 / 顺序变化均 fail-closed。"""
    meta_ids: list[str] = []
    seen: set[str] = set()
    for index, meta in enumerate(metadatas):
        chunk_id = (meta or {}).get("chunk_id")
        if not chunk_id:
            raise ValueError(
                f"metadatas[{index}] missing stable chunk_id — chunks "
                "contract requires a 1:1 mapping",
            )
        if chunk_id in seen:
            raise ValueError(f"duplicate chunk_id in metadatas: {chunk_id}")
        seen.add(chunk_id)
        meta_ids.append(chunk_id)
    if meta_ids != chunk_ids:
        raise ValueError(
            "chunks chunk_id mapping does not match metadatas order "
            "(1:1 contract violated)",
        )


# ═══════════════════════════════════════════════════════════════
# capture
# ═══════════════════════════════════════════════════════════════

def _provenance_block(history) -> dict:
    from src.rag_query_rewriter import REWRITE_PROMPT
    from src.rag_query_decomposer import DECOMPOSE_PROMPT
    return {
        "rewrite_prompt_sha256": _sha256_text(REWRITE_PROMPT),
        "decompose_prompt_sha256": _sha256_text(DECOMPOSE_PROMPT),
        "history_sha256": _history_fingerprint(history),
        # 原始 env 仅 provenance：生效值见 pipeline_contract.refusal_threshold
        "refusal_threshold_env": os.getenv("RAG_REFUSAL_THRESHOLD"),
    }


def _outputs_closure_sha(receipt_shas: list[str]) -> str:
    """有序 outputs receipt SHA 列表的闭环 SHA（顺序敏感，禁用 set）。"""
    return _sha256_text(
        json.dumps(receipt_shas, ensure_ascii=False, separators=(",", ":")),
    )


def _write_sealed(output_root: Path, rows: list[dict], run_id: str,
                  turn_id: str) -> None:
    """写 sealed JSONL + manifest（低层写入；capture 负责防覆盖检查）。"""
    output_root = Path(output_root)
    output_root.mkdir(parents=True, exist_ok=True)

    line_hashes: list[str] = []
    lines: list[str] = []
    receipt_shas: list[str] = []
    for row in rows:
        row_without_sha = {k: v for k, v in row.items() if k != "line_sha256"}
        line_sha = _sha256_text(_canonical_row_json(row_without_sha))
        row["line_sha256"] = line_sha
        line_hashes.append(line_sha)
        lines.append(_canonical_row_json(row) + "\n")
        receipt_shas.append(_sha256_text(_canonical_row_json(row["evidence"])))

    jsonl_text = "".join(lines)
    _write_text_lf(output_root / CAPTURE_FILE_NAME, jsonl_text)

    manifest_payload = {
        "schema_version": CAPTURE_SCHEMA_VERSION,
        "mode": CAPTURE_MODE,
        "run_id": run_id,
        "turn_id": turn_id,
        "file": CAPTURE_FILE_NAME,
        "line_count": len(rows),
        "line_hashes": line_hashes,
        "file_bytes_sha256": hashlib.sha256(jsonl_text.encode("utf-8")).hexdigest(),
        "outputs_sha256": _outputs_closure_sha(receipt_shas),
    }
    manifest_payload["manifest_sha256"] = _sha256_text(
        _canonical_manifest_json(manifest_payload),
    )
    _write_text_lf(
        output_root / MANIFEST_FILE_NAME,
        _canonical_manifest_json(manifest_payload) + "\n",
    )


def capture_synthetic_plan(
        runtime_plan,
        evidence,
        capability,
        metadatas: list[dict],
        history=None,
        run_id: str = "synthetic-run",
        turn_id: str = "turn-1",
) -> Path:
    """把一次 synthetic 规划 + evidence 收据写入 sealed JSONL + manifest。

    fail-closed（任一失败零写入）：
    - capability 未由 issuer 签发 / 路径边界违规（任何读写之前）；
    - reranker 非 none；planning profile 非 sync 或检索宽度非默认；
    - output_root 已存在（必须新建目标，禁止向已有目录混写）；
    - chunks 文件缺失/非 UTF-8/非 JSON/chunk_id 缺失重复/与 metadatas
      映射不一致（chunks contract 强制）；
    - provenance 缺失、evidence 与 runtime plan 指纹不一致、候选
      chunk_id 缺失/重复、非有限 score。
    返回 JSONL 路径。
    """
    from src.rag import _RuntimeQueryPlan, _plan_fingerprint

    cap = _require_capability(capability)
    _require_reranker_none()
    if not isinstance(runtime_plan, _RuntimeQueryPlan):
        raise ValueError(
            "runtime_plan must be a _RuntimeQueryPlan (from _plan_query_runtime)",
        )
    if runtime_plan.planning_profile != SYNC_PLANNING_PROFILE:
        raise ValueError(
            "capture only accepts the sync prepare_answer_evidence profile; "
            f"got planning_profile={runtime_plan.planning_profile!r} "
            "(stream plans are not capturable)",
        )
    if runtime_plan.retrieval_k is not None:
        raise ValueError(
            "capture requires the default sync retrieval width "
            f"(retrieval_k=None), got {runtime_plan.retrieval_k!r}",
        )
    if runtime_plan.rewrite_stage is None or runtime_plan.decompose_stage is None:
        raise ValueError(
            "planner provenance unavailable (planner was patched?) — "
            "capture requires unpatched planner execution",
        )
    if evidence.plan_fingerprint != _plan_fingerprint(
            runtime_plan.rewritten_query, runtime_plan.sub_queries):
        raise ValueError("evidence.plan_fingerprint does not match runtime plan")

    output_root = cap.context.output_root
    if output_root.exists():
        raise ValueError(
            f"capture output_root must not exist (new target required): "
            f"{output_root}",
        )
    chunks_contract = _chunks_contract(cap.context.chunks_path)
    _require_chunks_match_metadatas(
        chunks_contract["chunks_chunk_ids"], metadatas,
    )

    # ── 观察顺序候选 → 稳定 chunk_id（不含运行期 chunk_index）──
    hits: list[CapturedCandidateHit] = []
    seen: set[str] = set()
    for rank, index in enumerate(runtime_plan.merged):
        meta = metadatas[index] or {}
        chunk_id = meta.get("chunk_id")
        if not chunk_id:
            raise ValueError(f"metadatas[{index}] missing stable chunk_id")
        if chunk_id in seen:
            raise ValueError(f"duplicate chunk_id in observation order: {chunk_id}")
        seen.add(chunk_id)
        hits.append(CapturedCandidateHit(
            rank=rank,
            chunk_id=chunk_id,
            score=normalize_score(runtime_plan.best_score[index]),
        ))

    fingerprint = compute_base_candidates_fingerprint(
        [[h.rank, h.chunk_id, h.score] for h in hits],
    )
    plan = CapturedQueryPlan(
        query=runtime_plan.query,
        rewritten_query=runtime_plan.rewritten_query,
        rewrite_log=runtime_plan.rewrite_log,
        sub_queries=runtime_plan.sub_queries,
        base_candidates=tuple(hits),
        base_candidates_fingerprint=fingerprint,
        rewrite_stage=runtime_plan.rewrite_stage,
        decompose_stage=runtime_plan.decompose_stage,
    )
    receipt = CapturedEvidenceReceipt(
        plan_fingerprint=evidence.plan_fingerprint,
        base_candidates_fingerprint=fingerprint,
        retrieval_fingerprint=evidence.retrieval_fingerprint,
        context_sha256=evidence.context_sha256,
        candidate_chunk_ids=tuple(evidence.candidate_chunk_ids),
        context_chunk_ids=tuple(evidence.context_chunk_ids),
        refused=evidence.refused,
        refusal_reason=evidence.refusal_reason,
    )

    contract = effective_pipeline_contract()
    contract.update(chunks_contract)

    row = {
        "schema_version": CAPTURE_SCHEMA_VERSION,
        "mode": CAPTURE_MODE,
        "run_id": run_id,
        "turn_id": turn_id,
        "plan": {
            "query": plan.query,
            "rewritten_query": plan.rewritten_query,
            "rewrite_log": plan.rewrite_log,
            "sub_queries": plan.sub_queries,
            "base_candidates": [
                [h.rank, h.chunk_id, h.score] for h in plan.base_candidates
            ],
            "base_candidates_fingerprint": plan.base_candidates_fingerprint,
            "rewrite_stage": plan.rewrite_stage.__dict__,
            "decompose_stage": plan.decompose_stage.__dict__,
        },
        "evidence": receipt.__dict__,
        "pipeline_contract": contract,
        "provenance": _provenance_block(history),
    }
    _write_sealed(output_root, [row], run_id, turn_id)
    return output_root / CAPTURE_FILE_NAME


# ═══════════════════════════════════════════════════════════════
# replay
# ═══════════════════════════════════════════════════════════════

@dataclass
class _ReplayQueryPlan:
    """回放对象（私有）：稳定 chunk_id 映射回当前 index，供 prepare 注入。

    base_candidates 按捕获 rank 顺序插入 dict——prepare 的 query_plan 分支
    按 score 稳定排序，同分候选保持插入顺序 → 观察顺序得以保留
    （验收：test_replay_preserves_captured_equal_score_rank）。
    """
    query: str
    rewritten_query: str
    rewrite_log: dict
    sub_queries: list[str]
    base_candidates: dict[int, float]  # 插入顺序 = 捕获 rank 顺序


def _parse_captured_plan(payload: dict) -> CapturedQueryPlan:
    hits = tuple(
        CapturedCandidateHit(rank=h[0], chunk_id=h[1], score=h[2])
        for h in payload["base_candidates"]
    )
    return CapturedQueryPlan(
        query=payload["query"],
        rewritten_query=payload["rewritten_query"],
        rewrite_log=payload["rewrite_log"],
        sub_queries=payload["sub_queries"],
        base_candidates=hits,
        base_candidates_fingerprint=payload["base_candidates_fingerprint"],
        rewrite_stage=StageProvenance(**payload["rewrite_stage"]),
        decompose_stage=StageProvenance(**payload["decompose_stage"]),
    )


def _chunk_id_to_index(metadatas: list[dict]) -> dict[str, int]:
    """chunk_id → index 映射；索引侧重复 chunk_id fail-closed。"""
    mapping: dict[str, int] = {}
    for index, meta in enumerate(metadatas):
        chunk_id = (meta or {}).get("chunk_id")
        if not chunk_id:
            continue
        if chunk_id in mapping:
            raise ValueError(f"duplicate chunk_id in index metadata: {chunk_id}")
        mapping[chunk_id] = index
    return mapping


def _validate_candidates(plan: CapturedQueryPlan,
                         metadatas: list[dict]) -> dict[int, float]:
    """候选完整性校验（rank 连续 / score canonical / fingerprint / 映射），
    通过后按捕获 rank 顺序还原 dict[chunk_index, float]。"""
    hits = list(plan.base_candidates)
    for position, hit in enumerate(hits):
        if hit.rank != position:
            raise ValueError(f"non-contiguous rank at position {position}: {hit.rank}")
    score_floats = [validate_score_str(hit.score) for hit in hits]
    fingerprint = compute_base_candidates_fingerprint(
        [[h.rank, h.chunk_id, h.score] for h in hits],
    )
    if fingerprint != plan.base_candidates_fingerprint:
        raise ValueError("base_candidates_fingerprint mismatch (tampered or stale)")

    mapping = _chunk_id_to_index(metadatas)
    replay_scores: dict[int, float] = {}
    seen_hits: set[str] = set()
    for hit, score in zip(hits, score_floats):
        if hit.chunk_id in seen_hits:
            raise ValueError(f"duplicate chunk_id in captured candidates: {hit.chunk_id}")
        seen_hits.add(hit.chunk_id)
        if hit.chunk_id not in mapping:
            raise ValueError(f"chunk_id missing from current index: {hit.chunk_id}")
        replay_scores[mapping[hit.chunk_id]] = score
    return replay_scores


_CHUNKS_CONTRACT_KEYS = (
    "chunks_bytes_sha256", "chunks_line_count", "chunks_chunk_ids",
)


def _validate_pipeline_contract(recorded: dict) -> None:
    """硬阻断契约比对：任一阻断项漂移 → fail-closed。chunks 项单独校验。"""
    _require_reranker_none()
    current = effective_pipeline_contract()
    for key, value in recorded.items():
        if key in _CHUNKS_CONTRACT_KEYS:
            continue
        if current.get(key) != value:
            raise ValueError(
                f"pipeline contract drift on {key!r}: "
                f"captured={value!r}, current={current.get(key)!r}",
            )
    for key in current:
        if key not in recorded:
            raise ValueError(f"pipeline contract missing key: {key!r}")


def _validate_chunks_contract(recorded: dict, chunks_path: Path) -> dict:
    """chunks 契约强校验：无契约的旧 capture 一律拒绝（fail-closed）。

    返回当前 chunks 文件的契约（供 replay 侧对当前 index metadata 做
    完整映射比对）。
    """
    if "chunks_bytes_sha256" not in recorded:
        raise ValueError(
            "trace has no chunks contract (legacy capture without chunks "
            "is not replayable)",
        )
    current = _chunks_contract(chunks_path)
    if current["chunks_bytes_sha256"] != recorded.get("chunks_bytes_sha256"):
        raise ValueError("chunks contract drift (bytes sha256)")
    if current["chunks_line_count"] != recorded.get("chunks_line_count"):
        raise ValueError("chunks contract drift (line count)")
    if current["chunks_chunk_ids"] != recorded.get("chunks_chunk_ids"):
        raise ValueError("chunks contract drift (chunk_id mapping)")
    return current


def _warn_provenance_drift(recorded: dict, plan: CapturedQueryPlan) -> None:
    """planner provenance 差异只告警，不阻断已捕获 plan 的 replay。

    对 replay 时所有可提供的 provenance 做 warning-only 比较：
    - prompt：当前 REWRITE_PROMPT / DECOMPOSE_PROMPT SHA；
    - model：captured stage 的 requested_model 与当前默认模型（"unknown"
      表示无可靠来源，不比较）；
    - history：零 LLM replay 无 history 输入可比，仅提示已记录。
    不为比较调用任何 LLM。
    """
    from src import rag
    from src.rag_query_rewriter import REWRITE_PROMPT
    from src.rag_query_decomposer import DECOMPOSE_PROMPT
    from src.domain import STAGE_SERVED_VERSION_UNKNOWN
    if _sha256_text(REWRITE_PROMPT) != recorded.get("rewrite_prompt_sha256"):
        warnings.warn("G1-S provenance drift: REWRITE_PROMPT changed", UserWarning)
    if _sha256_text(DECOMPOSE_PROMPT) != recorded.get("decompose_prompt_sha256"):
        warnings.warn("G1-S provenance drift: DECOMPOSE_PROMPT changed", UserWarning)
    for stage_name, stage in (
            ("rewrite", plan.rewrite_stage), ("decompose", plan.decompose_stage)):
        requested = stage.requested_model
        if requested not in (None, STAGE_SERVED_VERSION_UNKNOWN) and \
                requested != rag.DEFAULT_LLM_MODEL:
            warnings.warn(
                f"G1-S provenance drift: {stage_name} model was {requested!r} "
                f"but current default model is {rag.DEFAULT_LLM_MODEL!r}",
                UserWarning,
            )
    if recorded.get("history_sha256") is not None:
        warnings.warn(
            "G1-S provenance note: history provenance was recorded at "
            "capture; zero-LLM replay has no history input to compare",
            UserWarning,
        )


def _validate_line(row: dict) -> None:
    recorded = row.get("line_sha256")
    without = {k: v for k, v in row.items() if k != "line_sha256"}
    if _sha256_text(_canonical_row_json(without)) != recorded:
        raise ValueError("row line_sha256 mismatch (tampered line)")


def _validate_manifest(payload: dict, jsonl_bytes: bytes) -> None:
    if payload.get("mode") != CAPTURE_MODE:
        raise ValueError(f"unsupported manifest mode: {payload.get('mode')!r}")
    if payload.get("schema_version") != CAPTURE_SCHEMA_VERSION:
        raise ValueError(
            f"unsupported manifest schema_version: "
            f"{payload.get('schema_version')!r}",
        )
    if payload.get("file") != CAPTURE_FILE_NAME:
        raise ValueError(
            f"manifest file mismatch: {payload.get('file')!r} "
            f"(expected {CAPTURE_FILE_NAME!r})",
        )
    recorded_self_hash = payload.get("manifest_sha256")
    if not recorded_self_hash:
        raise ValueError("manifest missing manifest_sha256")
    recomputed = {k: v for k, v in payload.items() if k != "manifest_sha256"}
    if _sha256_text(_canonical_manifest_json(recomputed)) != recorded_self_hash:
        raise ValueError("manifest self-hash mismatch")
    if payload.get("file_bytes_sha256") != hashlib.sha256(jsonl_bytes).hexdigest():
        raise ValueError("manifest file_bytes_sha256 mismatch")
    lines = jsonl_bytes.splitlines()
    line_hashes = []
    for line in lines:
        row = json.loads(line.decode("utf-8"))
        without = {k: v for k, v in row.items() if k != "line_sha256"}
        line_hashes.append(_sha256_text(_canonical_row_json(without)))
    if list(payload.get("line_hashes", [])) != line_hashes:
        raise ValueError("manifest line_hashes mismatch (order-sensitive)")
    # outputs closure：逐行 evidence receipt 有序 SHA 的闭环（顺序敏感）
    receipt_shas = []
    for line in lines:
        row = json.loads(line.decode("utf-8"))
        receipt_shas.append(_sha256_text(_canonical_row_json(row["evidence"])))
    if _outputs_closure_sha(receipt_shas) != payload.get("outputs_sha256"):
        raise ValueError("manifest outputs_sha256 mismatch (receipt closure)")


def _validate_receipt(evidence, recorded: dict,
                      base_candidates_fingerprint: str) -> None:
    recomputed = {
        "plan_fingerprint": evidence.plan_fingerprint,
        "base_candidates_fingerprint": base_candidates_fingerprint,
        "retrieval_fingerprint": evidence.retrieval_fingerprint,
        "context_sha256": evidence.context_sha256,
        "candidate_chunk_ids": list(evidence.candidate_chunk_ids),
        "context_chunk_ids": list(evidence.context_chunk_ids),
        "refused": evidence.refused,
        "refusal_reason": evidence.refusal_reason,
    }
    if recomputed != recorded:
        diffs = ", ".join(
            f"{k}={recomputed.get(k)!r} vs {recorded.get(k)!r}"
            for k in recomputed if recomputed.get(k) != recorded.get(k)
        )
        raise ValueError(f"evidence receipt mismatch: {diffs}")


def replay_synthetic_plan(
        capability,
        model,
        collection,
        bm25,
        documents: list[str],
        metadatas: list[dict],
) -> list:
    """读 sealed capture → 逐行校验 → 零 LLM/零生成的 plan/evidence replay。

    capability 绑定 capture 输出根与 chunks 文件；路径边界在任何 read
    之前校验。任一 fail-closed 条件触发即抛异常；provenance 漂移仅告警
    （warnings）。不调用 rewrite/decompose/检索/生成（query_plan 注入
    分支零规划零检索）。
    """
    from src.rag import prepare_answer_evidence

    cap = _require_capability(capability)
    capture_root = cap.context.output_root
    chunks_path = cap.context.chunks_path

    jsonl_path = capture_root / CAPTURE_FILE_NAME
    manifest_path = capture_root / MANIFEST_FILE_NAME
    if not jsonl_path.exists() or not manifest_path.exists():
        raise FileNotFoundError(f"sealed capture incomplete: {capture_root}")

    jsonl_bytes = jsonl_path.read_bytes()
    if b"\r" in jsonl_bytes:
        raise ValueError("capture.jsonl contains CR — sealed bytes must be LF-only")

    # manifest 同样先按原始字节拒绝 CR（read_text 的 universal newlines
    # 会掩盖 CRLF 篡改），再做 UTF-8 decode / JSON parse
    manifest_bytes = manifest_path.read_bytes()
    if b"\r" in manifest_bytes:
        raise ValueError(
            "capture.manifest.json contains CR — sealed bytes must be LF-only",
        )
    try:
        manifest_payload = json.loads(manifest_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("capture.manifest.json is not valid UTF-8 JSON") from exc

    raw_rows = [json.loads(line) for line in jsonl_bytes.splitlines()]
    if len(raw_rows) != manifest_payload["line_count"]:
        raise ValueError("manifest line_count does not match capture.jsonl")
    # 先逐行 line_sha（行级精确诊断），再 manifest 字节闭环
    for row in raw_rows:
        _validate_line(row)
    _validate_manifest(manifest_payload, jsonl_bytes)

    evidences = []
    for row in raw_rows:
        if row.get("mode") != CAPTURE_MODE:
            raise ValueError(f"unsupported capture mode: {row.get('mode')!r}")
        if row.get("schema_version") != CAPTURE_SCHEMA_VERSION:
            raise ValueError(
                f"unsupported schema_version: {row.get('schema_version')!r}",
            )
        plan = _parse_captured_plan(row["plan"])
        # chunks 契约是 replay 的基础契约，先于 pipeline 契约校验
        # （legacy 无 chunks 契约的 trace 在此精确 fail-closed）
        current_chunks = _validate_chunks_contract(
            row["pipeline_contract"], chunks_path,
        )
        # 当前 index metadata 的稳定 chunk_id 有序列表必须与 chunks
        # contract 完全一致（缺失/重复/额外/顺序/未命中候选的 metadata
        # 漂移全部 fail-closed）——在任何 prepare_answer_evidence 调用
        # 之前完成，未命中候选的漂移同样不可放过。
        _require_chunks_match_metadatas(
            current_chunks["chunks_chunk_ids"], metadatas,
        )
        _validate_pipeline_contract(row["pipeline_contract"])
        _warn_provenance_drift(row.get("provenance", {}), plan)
        replay_scores = _validate_candidates(plan, metadatas)
        replay_plan = _ReplayQueryPlan(
            query=plan.query,
            rewritten_query=plan.rewritten_query,
            rewrite_log=plan.rewrite_log,
            sub_queries=plan.sub_queries,
            base_candidates=replay_scores,
        )
        evidence = prepare_answer_evidence(
            plan.query, model, collection, bm25, documents, metadatas,
            query_plan=replay_plan,
        )
        _validate_receipt(evidence, row["evidence"],
                          plan.base_candidates_fingerprint)
        evidences.append(evidence)
    return evidences
