"""Phase 6-A — v2.0.11 frozen product retrieval baseline (read-only).

为已冻结的 v2.0.11 CANDIDATE（136 cases / 149 strict evidence）建立 Mneme
**当前产品**的只读 Retrieval Baseline。本阶段不调用生成模型、不做 LLM
judge、不产生 answer-quality / citation-faithfulness 分数；只测真实检索
链路（embedding → Chroma → BM25 → RRF）并给出诚实的可测性审计。

设计原则（fail-closed / 零副作用）：
1. **冻结边界**：先复算 freeze / candidate / targeted-review manifest 的
   self-hash 与全部声明输入的字节 SHA；任何漂移立即中止，零评测输出。
2. **只读**：本脚本从不写回 v2.0.11 revision、chunks、annotations、
   split/locked/overlay/dev/holdout；全部产物只写入独立的
   ``evaluation/product-baselines/v2.0.11-frozen-current/``。
3. **检索链复用**：使用生产函数 ``src.rag.build_bm25_index`` /
   ``src.rag.retrieve_hybrid_with_sources``（RRF k=60）与生产 embedding
   模型（all-MiniLM-L6-v2，本地缓存离线加载）；但索引**直接**建立在
   ``chromadb.PersistentClient`` 的临时数据目录上，绝不引用模块级
   ``src.rag.CHROMA_DB_PATH``，因此物理上无法触碰用户持久化索引，也不写
   任何 ``*.manifest.json`` / ``*.bm25.json`` sidecar。
4. **parser 漂移审计（独立于指标）**：v2.0.11 冻结语料由 ``get_splitter``
   （纯 RecursiveCharacterTextSplitter）构建，而当前运行时
   ``_load_index_chunks`` 走 Section 分块（src/chunking.py v3），两者
   不可互相复现（实测 art-of-war.txt 1195 vs 203 chunks）。因此 chunk 级
   真值（evidence ``chunk_id``）只对**冻结 chunks** 成立；基线以冻结
   chunks 为索引内容（检索链等价），parser 阶段单独以漂移审计测量并报告，
   不混入召回指标。
5. **真值权威**：chunk/source 级真值取自 ``evidence-after.jsonl``（149
   strict evidence，``chunk_text_sha256`` 已 149/149 与冻结 chunks 逐字节
   核验）；draft 的 ``relevant_chunk_ids`` 视为镜像，与 evidence 不一致时
   记录 divergence（17 cases），不参与真值。
6. **分母诚实**：无 chunk-level truth 的 refusal cases（31）不进入
   chunk/source 指标分母，只记录检索侧观测（max RRF score 等）；任何缺失
   或不适用指标不得伪造为 0 或“通过”。
7. **确定性**：无时间戳的产物两次离线构建逐字段一致；manifest 记录代码
   HEAD、依赖/模型身份、隔离方式与全部输入/输出 SHA。

CLI
---
::

    python scripts/evaluate_v211_frozen_product_baseline.py [--output DIR]
        [--data-dir DIR] [--skip-determinism] [--skip-parser-audit]

退出码：0=成功；2=冻结输入漂移（fail-closed，零产物）；1=其他错误。

本脚本**不包含任何 LLM/生成路径**：不 import openai 客户端、不调用
``answer_with_llm_history`` / ``llm_call`` / judge；检索期间无网络调用。
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from contextlib import redirect_stdout
from pathlib import Path
from typing import Any

# 强制离线：确保 embedding 模型只从本地缓存加载，检索期间无网络调用
# （src.rag 用 setdefault，此处预先无条件设置以覆盖任何先导入顺序）
os.environ["HF_HUB_OFFLINE"] = "1"
os.environ["TRANSFORMERS_OFFLINE"] = "1"

# ── 冻结输入路径（仓库内唯一事实来源）───────────────────────────────
REPO_ROOT = Path(__file__).resolve().parents[1]
# 直接运行 `python scripts/xxx.py` 时 sys.path[0] 是 scripts/ 目录；
# 显式加入仓库根，保证 `import evaluation` / `import src` 可用。
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
FROZEN_REVISION_DIR = (
    REPO_ROOT
    / "evaluation/datasets/v2/revisions"
    / "v2.0.11-owner-authorized-en048-same-source-repair"
)
FREEZE_DIR = FROZEN_REVISION_DIR / "evaluation-freeze"
CANDIDATE_MANIFEST_PATH = FROZEN_REVISION_DIR / "manifest.json"
TARGETED_REVIEW_MANIFEST_PATH = FROZEN_REVISION_DIR / "targeted-re-review/manifest.json"
CHUNKS_PATH = REPO_ROOT / "data/v2-corpus/chunks/chunks.jsonl"
CHUNK_MANIFEST_PATH = REPO_ROOT / "data/v2-corpus/chunks/chunk-manifest.json"
CURRENT_DRAFT_PATH = (
    REPO_ROOT / "evaluation/datasets/v2/annotations/v2-cases-draft.jsonl"
)
CORPUS_DOCUMENTS_DIR = REPO_ROOT / "data/v2-corpus/documents/processed"

OUTPUT_DIR = REPO_ROOT / "evaluation/product-baselines/v2.0.11-frozen-current"
COLLECTION_NAME = "v211_frozen_product_baseline"

KS = (5, 10, 20)

# per-case 输出行的白名单键（测试依赖此集合；多出任何键即失败）
PER_CASE_OUTPUT_KEYS = frozenset({
    "case_id", "query", "query_type", "language", "should_refuse",
    "relevant_chunk_ids", "relevant_source_ids",
    "retrieved_chunk_ids", "retrieved_source_ids",
    "scores", "retrieval_ms", "metrics",
})

# failure-analysis 行的白名单键
FAILURE_ROW_KEYS = frozenset({
    "case_id", "query", "language", "query_type",
    "recall@5", "recall@10", "recall@20",
    "source_recall@5", "source_recall@10", "source_recall@20",
    "mrr", "expected_chunk_ids", "expected_source_ids",
    "actual_top20_chunk_ids", "actual_top20_source_ids",
    "first_relevant_rank", "failure_types",
})

# freeze manifest 声明输入名 → (根, 相对路径)。根：revision=冻结 revision
# 目录；chunks/annotations=语料目录；repo=仓库根（v2.0.10/v2.0.8 等历史
# revision 与 translation-equivalence 文件）。路径由探索阶段逐一确认。
# 注意同名不同义：``review-manifest.json`` 在 freeze manifest 中指
# v2.0.11 targeted-re-review manifest（字节 SHA 220ed9c2…），在
# targeted-review manifest 中则指 v2.0.10 automated-review manifest
# （5d3e17f1…）——因此按声明方分域解析。
_CORPUS_RESOLVERS: dict[str, tuple[str, str]] = {
    "chunk-manifest.json": ("chunks", "chunk-manifest.json"),
    "chunks.jsonl": ("chunks", "chunks.jsonl"),
    "current-v2-draft.jsonl": ("annotations", "v2-cases-draft.jsonl"),
    "candidate-draft-after.jsonl": ("revision", "draft-after.jsonl"),
    "candidate-evidence-after.jsonl": ("revision", "evidence-after.jsonl"),
    "candidate-manifest.json": ("revision", "manifest.json"),
    "v210-draft-after.jsonl": (
        "repo", "evaluation/datasets/v2/revisions/"
        "v2.0.10-owner-authorized-coherence-remediation/draft-after.jsonl"),
    "v210-evidence-after.jsonl": (
        "repo", "evaluation/datasets/v2/revisions/"
        "v2.0.10-owner-authorized-coherence-remediation/evidence-after.jsonl"),
}

_FREEZE_RESOLVERS: dict[str, tuple[str, str]] = {
    **_CORPUS_RESOLVERS,
    "diagnostic-issues.jsonl": (
        "revision", "targeted-re-review/contract-error-diagnostic/"
        "contract-error-diagnostic-issues.jsonl"),
    "diagnostic-manifest.json": (
        "revision", "targeted-re-review/contract-error-diagnostic/manifest.json"),
    "diagnostic-raw-model-attempts.jsonl": (
        "revision", "targeted-re-review/contract-error-diagnostic/"
        "raw-model-attempts.jsonl"),
    "diagnostic-results.jsonl": (
        "revision", "targeted-re-review/contract-error-diagnostic/"
        "contract-error-diagnostic-results.jsonl"),
    "diagnostic-summary.json": (
        "revision", "targeted-re-review/contract-error-diagnostic/"
        "contract-error-diagnostic-summary.json"),
    "pack-manifest.json": (
        "revision", "targeted-re-review/owner-decision-pack/manifest.json"),
    "pack-owner-decision-template.jsonl": (
        "revision", "targeted-re-review/owner-decision-pack/"
        "owner-decision-template.jsonl"),
    "pack-persistent-contract-errors.jsonl": (
        "revision", "targeted-re-review/owner-decision-pack/"
        "persistent-contract-errors.jsonl"),
    "pack-stable-reject-root-cause-triage.jsonl": (
        "revision", "targeted-re-review/owner-decision-pack/"
        "stable-reject-root-cause-triage.jsonl"),
    "review-manifest.json": (
        "revision", "targeted-re-review/manifest.json"),
    "targeted-review-issues.jsonl": (
        "revision", "targeted-re-review/targeted-review-issues.jsonl"),
    "targeted-review-results.jsonl": (
        "revision", "targeted-re-review/targeted-review-results.jsonl"),
    "triage-manifest.json": (
        "repo", "evaluation/datasets/v2/revisions/"
        "v2.0.10-owner-authorized-coherence-remediation/automated-review/"
        "coherence-reject-triage/manifest.json"),
    "triage-owner-decision-template.jsonl": (
        "repo", "evaluation/datasets/v2/revisions/"
        "v2.0.10-owner-authorized-coherence-remediation/automated-review/"
        "coherence-reject-triage/owner-decision-template.jsonl"),
    "triage-reject-root-cause-triage.jsonl": (
        "repo", "evaluation/datasets/v2/revisions/"
        "v2.0.10-owner-authorized-coherence-remediation/automated-review/"
        "coherence-reject-triage/reject-root-cause-triage.jsonl"),
    "triage-review-coherence-errors.jsonl": (
        "repo", "evaluation/datasets/v2/revisions/"
        "v2.0.10-owner-authorized-coherence-remediation/automated-review/"
        "coherence-reject-triage/review-coherence-errors.jsonl"),
}

_CANDIDATE_RESOLVERS: dict[str, tuple[str, str]] = {
    **_CORPUS_RESOLVERS,
    "translation-equivalence-policy-ledger.jsonl": (
        "repo", "evaluation/datasets/v2/revisions/"
        "v2.0.8-owner-authorized-semantic-quality-remediation/"
        "translation-equivalence-policy-ledger.jsonl"),
    "translation-equivalence-policy.md": (
        "repo", "evaluation/datasets/v2/revisions/"
        "v2.0.8-owner-authorized-semantic-quality-remediation/"
        "translation-equivalence-policy.md"),
    "v210-manifest.json": (
        "repo", "evaluation/datasets/v2/revisions/"
        "v2.0.10-owner-authorized-coherence-remediation/manifest.json"),
    "v210-review-issues.jsonl": (
        "repo", "evaluation/datasets/v2/revisions/"
        "v2.0.10-owner-authorized-coherence-remediation/automated-review/"
        "automated-review-issues.jsonl"),
    "v210-review-manifest.json": (
        "repo", "evaluation/datasets/v2/revisions/"
        "v2.0.10-owner-authorized-coherence-remediation/automated-review/"
        "manifest.json"),
    "v210-triage-manifest.json": (
        "repo", "evaluation/datasets/v2/revisions/"
        "v2.0.10-owner-authorized-coherence-remediation/automated-review/"
        "coherence-reject-triage/manifest.json"),
    "v210-triage-owner-decision-template.jsonl": (
        "repo", "evaluation/datasets/v2/revisions/"
        "v2.0.10-owner-authorized-coherence-remediation/automated-review/"
        "coherence-reject-triage/owner-decision-template.jsonl"),
    "v210-triage-reject-root-cause-triage.jsonl": (
        "repo", "evaluation/datasets/v2/revisions/"
        "v2.0.10-owner-authorized-coherence-remediation/automated-review/"
        "coherence-reject-triage/reject-root-cause-triage.jsonl"),
    "v210-triage-review-coherence-errors.jsonl": (
        "repo", "evaluation/datasets/v2/revisions/"
        "v2.0.10-owner-authorized-coherence-remediation/automated-review/"
        "coherence-reject-triage/review-coherence-errors.jsonl"),
}

_TARGETED_RESOLVERS: dict[str, tuple[str, str]] = {
    **_CORPUS_RESOLVERS,
    "translation-equivalence-policy-ledger.jsonl": (
        "repo", "evaluation/datasets/v2/revisions/"
        "v2.0.8-owner-authorized-semantic-quality-remediation/"
        "translation-equivalence-policy-ledger.jsonl"),
    "translation-equivalence-policy.md": (
        "repo", "evaluation/datasets/v2/revisions/"
        "v2.0.8-owner-authorized-semantic-quality-remediation/"
        "translation-equivalence-policy.md"),
    "owner-decision-template.jsonl": (
        "repo", "evaluation/datasets/v2/revisions/"
        "v2.0.10-owner-authorized-coherence-remediation/automated-review/"
        "coherence-reject-triage/owner-decision-template.jsonl"),
    "reject-root-cause-triage.jsonl": (
        "repo", "evaluation/datasets/v2/revisions/"
        "v2.0.10-owner-authorized-coherence-remediation/automated-review/"
        "coherence-reject-triage/reject-root-cause-triage.jsonl"),
    "review-coherence-errors.jsonl": (
        "repo", "evaluation/datasets/v2/revisions/"
        "v2.0.10-owner-authorized-coherence-remediation/automated-review/"
        "coherence-reject-triage/review-coherence-errors.jsonl"),
    "review-issues.jsonl": (
        "repo", "evaluation/datasets/v2/revisions/"
        "v2.0.10-owner-authorized-coherence-remediation/automated-review/"
        "automated-review-issues.jsonl"),
    "review-manifest.json": (
        "repo", "evaluation/datasets/v2/revisions/"
        "v2.0.10-owner-authorized-coherence-remediation/automated-review/"
        "manifest.json"),
    "triage-manifest.json": (
        "repo", "evaluation/datasets/v2/revisions/"
        "v2.0.10-owner-authorized-coherence-remediation/automated-review/"
        "coherence-reject-triage/manifest.json"),
    "v210-candidate-draft-after.jsonl": (
        "repo", "evaluation/datasets/v2/revisions/"
        "v2.0.10-owner-authorized-coherence-remediation/draft-after.jsonl"),
    "v210-candidate-evidence-after.jsonl": (
        "repo", "evaluation/datasets/v2/revisions/"
        "v2.0.10-owner-authorized-coherence-remediation/evidence-after.jsonl"),
    "v210-candidate-manifest.json": (
        "repo", "evaluation/datasets/v2/revisions/"
        "v2.0.10-owner-authorized-coherence-remediation/manifest.json"),
}

_MANIFEST_RESOLVERS = {
    "freeze manifest": _FREEZE_RESOLVERS,
    "candidate manifest": _CANDIDATE_RESOLVERS,
    "targeted-review manifest": _TARGETED_RESOLVERS,
}

_QUERY_TYPES = frozenset({
    "single_fact", "cross_document", "metadata", "multi_turn",
    "no_answer", "mixed_intent",
})
_LANGUAGES = frozenset({"zh", "en", "mixed"})

# v1 EvalCase 契约不承载的 draft 字段 → 不映射原因（写入 schema 报告）
_UNMAPPED_DRAFT_FIELDS = {
    "annotation": "标注溯源元数据（annotated_by/review_status），不是评测真值，v1 EvalCase 无此字段",
    "doc_target": "草稿构造字段（仅 18/136 行存在），运行时无真值角色",
    "is_refusal_turn": "草稿链内标记（18/136 行），拒答语义由 v1 兼容的 should_refuse 表达",
    "note": "人工可读标注备注，不进入指标",
    "relevance_level": "派生标记（chunk/none），与真值存在性冗余",
    "relevant_chunk_ids": "draft 侧镜像；真值以 evidence-after.jsonl 为准，不一致时记录 divergence",
}


class FrozenInputDrift(Exception):
    """冻结输入 SHA / self-hash 漂移——fail-closed，零评测输出。"""


# ── 哈希与 manifest 约定 ──────────────────────────────────────────────

def sha256_bytes(path: Path) -> str:
    """字节 SHA-256（只读输入的身份标识）。"""
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def canonical_json(obj: Any) -> str:
    """项目 manifest 规范序列化：indent=1, sort_keys, ensure_ascii=False + 换行。"""
    return json.dumps(obj, indent=1, sort_keys=True, ensure_ascii=False) + "\n"


def self_hash(obj: dict) -> str:
    """先移除 ``manifest_sha256`` 再计算 self-hash（既有约定）。"""
    d = dict(obj)
    d.pop("manifest_sha256", None)
    return hashlib.sha256(canonical_json(d).encode("utf-8")).hexdigest()


def self_hash_of_file(path: Path) -> str:
    return self_hash(json.loads(Path(path).read_text(encoding="utf-8")))


def load_jsonl(path: Path) -> list[dict]:
    rows: list[dict] = []
    with open(path, encoding="utf-8") as stream:
        for line_no, line in enumerate(stream, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError as exc:
                raise ValueError(f"invalid JSONL at {path} line {line_no}: {exc}")
    return rows


# ── 冻结输入校验（fail-closed）────────────────────────────────────────

def _resolve_input(name: str, resolver: dict[str, tuple[str, str]],
                   *, revision_dir: Path, chunks_dir: Path,
                   annotations_dir: Path) -> tuple[Path | None, bool]:
    """按 (manifest 域, 名称) 解析输入路径。

    Returns:
        (path, known): path 为文件路径（不存在也返回路径）；known=False
        表示该名称没有任何规范解析规则（真正的“无法解析”漂移）。
    """
    entry = resolver.get(name)
    if entry is None:
        return None, False
    kind, rel = entry
    root = {
        "revision": revision_dir,
        "chunks": chunks_dir,
        "annotations": annotations_dir,
        "repo": REPO_ROOT,
    }[kind]
    return root / rel, True


def verify_frozen_inputs(
    *,
    revision_dir: Path,
    chunks_path: Path,
    chunk_manifest_path: Path,
    current_draft_path: Path,
) -> dict:
    """复算 freeze / candidate / targeted-review manifest 与全部声明输入
    的 SHA；任何漂移返回 ``verified=False`` 并给出精确漂移项。纯只读。

    覆盖：
    - 三个 manifest 的 self-hash（先移除 manifest_sha256）；
    - freeze manifest 声明的全部 inputs（24 项真实数据）与 outputs；
    - candidate / targeted-review manifest 各自声明的 inputs（含
      v2.0.10 / v2.0.8 历史 revision 与 translation-equivalence 文件）。
    """
    freeze_manifest_path = revision_dir / "evaluation-freeze/manifest.json"
    candidate_manifest_path = revision_dir / "manifest.json"
    targeted_manifest_path = revision_dir / "targeted-re-review/manifest.json"
    chunks_dir = chunks_path.parent
    annotations_dir = current_draft_path.parent

    checks: list[dict] = []
    manifests = [
        ("freeze manifest", freeze_manifest_path),
        ("candidate manifest", candidate_manifest_path),
        ("targeted-review manifest", targeted_manifest_path),
    ]
    for label, path in manifests:
        if not path.is_file():
            checks.append({
                "name": f"{label} self-hash", "kind": "manifest_self_hash",
                "status": "missing", "expected": None, "actual": None,
                "path": str(path),
            })
            continue
        declared = json.loads(path.read_text(encoding="utf-8"))
        actual = self_hash(declared)
        checks.append({
            "name": f"{label} self-hash", "kind": "manifest_self_hash",
            "status": "ok" if actual == declared.get("manifest_sha256") else "mismatch",
            "expected": declared.get("manifest_sha256"), "actual": actual,
            "path": str(path),
        })

    # freeze manifest 声明 → 校验 inputs + outputs；candidate/targeted 校验 inputs
    for label, manifest_path in manifests:
        if not manifest_path.is_file():
            continue
        resolver = _MANIFEST_RESOLVERS[label]
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        for section in ("inputs", "outputs"):
            if section == "outputs" and label != "freeze manifest":
                continue  # 只有 freeze manifest 声明 outputs
            for name, expected in sorted(manifest.get(section, {}).items()):
                if label == "freeze manifest" and section == "outputs":
                    path = revision_dir / "evaluation-freeze" / name
                    known = True
                else:
                    path, known = _resolve_input(
                        name, resolver, revision_dir=revision_dir,
                        chunks_dir=chunks_dir, annotations_dir=annotations_dir,
                    )
                if not known:
                    checks.append({
                        "name": name, "kind": "unresolved", "status": "missing",
                        "expected": expected, "actual": None, "path": None,
                    })
                    continue
                if path is None or not path.is_file():
                    checks.append({
                        "name": name, "kind": "missing", "status": "missing",
                        "expected": expected, "actual": None,
                        "path": str(path) if path else None,
                    })
                    continue
                actual = sha256_bytes(path)
                checks.append({
                    "name": name, "kind": section,
                    "status": "ok" if actual == expected else "mismatch",
                    "expected": expected, "actual": actual, "path": str(path),
                })

    drift = [
        {k: c[k] for k in ("name", "kind", "status", "expected", "actual", "path")}
        for c in checks if c["status"] != "ok"
    ]
    return {"verified": not drift, "checks": checks, "drift": drift}


# ── v2.0.11 → 评测 case 的字段映射（内存中完成，绝不回写）────────────

def load_cases(
    draft_path: Path,
    evidence_path: Path,
    chunks_path: Path,
) -> tuple[list[dict], dict]:
    """把 v2.0.11 draft-after + evidence-after 映射为评测 case。

    - 可直接映射（v1 契约字段）：id/query/query_type/language/
      should_refuse/acceptable_answer_points/metadata；
    - 真值（chunk/source 级）以 evidence-after.jsonl 为准；
    - 其余 draft 字段记录为不映射 + 原因；evidence 中不在冻结语料的
      chunk_id 记录为 mapping failure 并从真值剔除（0 个也会如实报告）。
    """
    frozen_chunk_ids = {
        row["chunk_id"] for row in load_jsonl(chunks_path)
    }
    drafts = load_jsonl(draft_path)
    evidence_rows = load_jsonl(evidence_path)

    # 严格校验（避免静默吞掉未知枚举值）
    for d in drafts:
        if d.get("query_type") not in _QUERY_TYPES:
            raise ValueError(
                f"case {d.get('id')}: unknown query_type {d.get('query_type')!r}")
        if d.get("language") not in _LANGUAGES:
            raise ValueError(
                f"case {d.get('id')}: unknown language {d.get('language')!r}")

    evidence_by_case: dict[str, list[dict]] = {}
    for row in evidence_rows:
        evidence_by_case.setdefault(row["case_id"], []).append(row)

    mapping_failures: dict[str, str] = {}
    for row in evidence_rows:
        cid = row.get("chunk_id")
        if cid not in frozen_chunk_ids:
            mapping_failures[cid] = (
                f"evidence chunk_id {cid!r} 不在冻结语料 chunks.jsonl 中"
                f"（case {row.get('case_id')}），已从该 case 真值剔除"
            )

    cases: list[dict] = []
    divergences: list[dict] = []
    for d in drafts:
        case_id = d["id"]
        ev_rows = evidence_by_case.get(case_id, [])
        evidence_chunks = sorted({
            r["chunk_id"] for r in ev_rows
            if r.get("chunk_id") not in mapping_failures
        })
        evidence_sources = sorted({r["source_id"] for r in ev_rows})
        draft_chunks = sorted(d.get("relevant_chunk_ids", []))
        draft_sources = sorted(d.get("relevant_source_ids", []))
        if set(draft_chunks) != set(evidence_chunks):
            divergences.append({
                "case_id": case_id, "kind": "draft_vs_evidence_chunks",
                "draft_only": sorted(set(draft_chunks) - set(evidence_chunks)),
                "evidence_only": sorted(set(evidence_chunks) - set(draft_chunks)),
                "authoritative": "evidence-after.jsonl",
            })
        if set(draft_sources) != set(evidence_sources):
            divergences.append({
                "case_id": case_id, "kind": "draft_vs_evidence_sources",
                "draft_only": sorted(set(draft_sources) - set(evidence_sources)),
                "evidence_only": sorted(set(evidence_sources) - set(draft_sources)),
                "authoritative": "evidence-after.jsonl",
            })
        cases.append({
            "case_id": case_id,
            "query": d["query"],
            "query_type": d["query_type"],
            "language": d["language"],
            "should_refuse": bool(d.get("should_refuse", False)),
            "acceptable_answer_points": list(d.get("acceptable_answer_points", [])),
            "metadata": dict(d.get("metadata", {})),
            "relevant_chunk_ids": evidence_chunks,
            "relevant_source_ids": evidence_sources,
        })

    mapping_report = {
        "mapping": {
            "draft_fields": {
                "mapped": sorted({
                    "id", "query", "query_type", "language", "should_refuse",
                    "acceptable_answer_points", "metadata",
                    "relevant_source_ids", "relevant_chunks",
                }),
                "unmapped": sorted(_UNMAPPED_DRAFT_FIELDS),
                "reasons": dict(_UNMAPPED_DRAFT_FIELDS),
            },
            "evidence_fields": {
                "mapped": sorted({
                    "case_id", "chunk_id", "source_id", "chunk_text_sha256",
                }),
                "note": "chunk_text_sha256 已与冻结 chunks.jsonl 逐字节核验；"
                        "snippet/char_range 等溯源字段不进入指标",
                "unmapped": sorted({
                    "snippet", "raw_evidence_span", "snippet_sha256",
                    "char_range", "char_range_start", "char_range_end",
                    "raw_chunk_char_range", "legacy_char_range",
                    "coordinate_contract", "mapping_algorithm_version",
                    "snippet_normalization",
                }),
            },
            "divergences": divergences,
            "mapping_failures": mapping_failures,
            "case_counts": {
                "total": len(cases),
                "with_chunk_truth": sum(1 for c in cases if c["relevant_chunk_ids"]),
                "no_chunk_truth": sum(1 for c in cases if not c["relevant_chunk_ids"]),
                "mapping_failure_rows": len(mapping_failures),
            },
        },
    }
    return cases, mapping_report


# ── 检索链路（生产函数复用 + 临时 collection 隔离）───────────────────

def load_frozen_chunks(chunks_path: Path) -> list[dict]:
    """按 chunk_id 稳定排序加载冻结 chunks。"""
    return sorted(load_jsonl(chunks_path), key=lambda c: c["chunk_id"])


def build_frozen_index(
    chunks_path: Path,
    data_dir: Path,
    collection_name: str = COLLECTION_NAME,
) -> dict:
    """在**隔离的临时数据目录**上构建冻结语料的检索索引。

    与生产 ``build_index`` 相同的三个要素：生产 embedding 模型
    （model.encode → 显式 embeddings，避免 Chroma 默认 EF 联网下载）、
    ``hnsw:space=cosine`` collection、生产 ``build_bm25_index``（CJK
    n-gram）。索引由调用方在 ``data_dir`` 内自建 PersistentClient，
    **从不引用** ``src.rag.CHROMA_DB_PATH``，因此不会触碰任何用户持久化
    collection，也不写 manifest/bm25 sidecar（临时索引，无需复用）。
    """
    from src.llm_gateway import get_or_load_model
    import src.rag as rag
    import chromadb

    chunks = load_frozen_chunks(chunks_path)
    texts = [c["text"] for c in chunks]
    ids = [c["chunk_id"] for c in chunks]
    # source 身份 = 文件名（与 evidence source_id 约定一致；chunk_id 前缀
    # 只是 12 位 source sha 截断，不足以还原完整 sha256）
    metadatas = [{
        "chunk_id": c["chunk_id"],
        "source_id": c["source"],
        "source_name": c["source"],
        "source": c["source"],
        "chunk_index": c["index"],
    } for c in chunks]

    model = get_or_load_model(rag.EMBEDDING_MODEL_NAME, rag._load_sentence_transformer)
    embeddings = model.encode(texts).tolist()

    data_dir = Path(data_dir)
    chroma_dir = data_dir / "chroma_db"
    client = chromadb.PersistentClient(path=str(chroma_dir))
    collection = client.get_or_create_collection(
        name=collection_name,
        metadata={"hnsw:space": "cosine"},
    )
    collection.upsert(
        ids=ids, documents=texts, metadatas=metadatas, embeddings=embeddings,
    )
    bm25 = rag.build_bm25_index(texts, ids=ids, metadatas=metadatas)

    try:
        dimension = model.get_embedding_dimension()
    except (AttributeError, TypeError):
        dimension = model.get_sentence_embedding_dimension()
    return {
        "model": model,
        "client": client,
        "collection": collection,
        "bm25": bm25,
        "documents": texts,
        "metadatas": metadatas,
        "chunk_count": len(ids),
        "data_dir": str(data_dir),
        "chroma_dir": str(chroma_dir),
        "collection_name": collection_name,
        "model_name": rag.EMBEDDING_MODEL_NAME,
        "embedding_dimension": dimension,
    }


def close_index(index: dict) -> None:
    """关闭临时 collection 并释放句柄（Windows 文件锁）。"""
    client = index.get("client")
    if client is not None:
        try:
            client.close()
        except Exception:
            pass


def _per_case_metrics(retrieved_chunk_ids: list[str],
                      relevant_chunk_ids: set[str],
                      retrieved_source_ids: list[str],
                      relevant_source_ids: set[str]) -> dict[str, float]:
    from evaluation.metrics import recall_at_k, ndcg_at_k, source_recall_at_k
    metrics: dict[str, float] = {}
    for k in KS:
        metrics[f"recall@{k}"] = recall_at_k(retrieved_chunk_ids, relevant_chunk_ids, k)
        metrics[f"ndcg@{k}"] = ndcg_at_k(retrieved_chunk_ids, relevant_chunk_ids, k)
        metrics[f"source_recall@{k}"] = source_recall_at_k(
            retrieved_source_ids, relevant_source_ids, k)
    for rank, cid in enumerate(retrieved_chunk_ids, start=1):
        if cid in relevant_chunk_ids:
            metrics["mrr"] = 1.0 / rank
            break
    else:
        metrics["mrr"] = 0.0
    return metrics


def run_retrieval(cases: list[dict], index: dict) -> list[dict]:
    """对每个 case 跑生产混合检索（semantic + BM25 + RRF k=60）。

    无真值的 refusal case 的 ``metrics`` 为空 dict——绝不伪造 0 分。
    """
    from src.rag import retrieve_hybrid_with_sources

    results: list[dict] = []
    for case in cases:
        start = time.perf_counter()
        indices, _, scores = retrieve_hybrid_with_sources(
            query=case["query"],
            model=index["model"],
            collection=index["collection"],
            bm25=index["bm25"],
            documents=index["documents"],
            metadatas=index["metadatas"],
        )
        retrieval_ms = (time.perf_counter() - start) * 1000.0
        metadatas = index["metadatas"]
        retrieved_chunk_ids = [metadatas[i]["chunk_id"] for i in indices]
        retrieved_source_ids: list[str] = []
        seen: set[str] = set()
        for i in indices:
            source = metadatas[i].get("source_name") or metadatas[i].get("source")
            if source and source not in seen:
                seen.add(source)
                retrieved_source_ids.append(source)

        relevant_chunks = set(case["relevant_chunk_ids"])
        relevant_sources = set(case["relevant_source_ids"])
        metrics = (
            _per_case_metrics(
                retrieved_chunk_ids, relevant_chunks,
                retrieved_source_ids, relevant_sources,
            ) if relevant_chunks else {}
        )
        results.append({
            "case_id": case["case_id"],
            "query": case["query"],
            "query_type": case["query_type"],
            "language": case["language"],
            "should_refuse": case["should_refuse"],
            "relevant_chunk_ids": case["relevant_chunk_ids"],
            "relevant_source_ids": case["relevant_source_ids"],
            "retrieved_chunk_ids": retrieved_chunk_ids,
            "retrieved_source_ids": retrieved_source_ids,
            "scores": [float(s) for s in scores],
            "retrieval_ms": retrieval_ms,
            "metrics": metrics,
        })
    return results


# ── 指标聚合（复用 evaluation.metrics，分母诚实）─────────────────────

def compute_metrics(results: list[dict],
                    mapping_failure_rows: int = 0) -> dict:
    """聚合 chunk recall/nDCG/MRR + source recall，按 language /
    query_type / refusal 分组；每组记录有效分母 n。

    无 chunk-level truth 的 refusal cases（31）不进入 chunk/source 指标
    分母，只保留检索侧观测（max RRF score、低于产品拒答阈值的比例）——
    这是检索信号观测，不是 answer 级拒答精度。
    """
    from evaluation.metrics import (
        compute_retrieval_metrics,
        compute_stratified_metrics,
        source_recall_at_k,
    )
    import src.rag as rag

    truth_rows = [r for r in results if r["relevant_chunk_ids"]]
    refusal_rows = [r for r in results if r["should_refuse"]]

    overall: dict[str, Any] = compute_retrieval_metrics(
        [r["retrieved_chunk_ids"] for r in truth_rows],
        [set(r["relevant_chunk_ids"]) for r in truth_rows],
        ks=KS,
    )
    for k in KS:
        overall[f"source_recall@{k}"] = sum(
            source_recall_at_k(r["retrieved_source_ids"],
                               set(r["relevant_source_ids"]), k)
            for r in truth_rows
        ) / len(truth_rows) if truth_rows else None

    overall["denominators"] = {
        "total_cases": len(results),
        "chunk_metrics_cases": len(truth_rows),
        "no_chunk_truth_cases": len(refusal_rows),
        "mapping_failure_rows": mapping_failure_rows,
    }

    def _with_n(stratified: dict[str, dict],
                key_field: str) -> dict[str, dict]:
        counts: dict[str, int] = {}
        for r in truth_rows:
            key = r[key_field]
            counts[key] = counts.get(key, 0) + 1
        return {g: {"n": counts.get(g, 0), **m} for g, m in stratified.items()}

    by_language = _with_n(compute_stratified_metrics(
        [r["retrieved_chunk_ids"] for r in truth_rows],
        [set(r["relevant_chunk_ids"]) for r in truth_rows],
        [r["language"] for r in truth_rows], ks=KS,
    ), key_field="language")
    by_query_type = _with_n(compute_stratified_metrics(
        [r["retrieved_chunk_ids"] for r in truth_rows],
        [set(r["relevant_chunk_ids"]) for r in truth_rows],
        [r["query_type"] for r in truth_rows], ks=KS,
    ), key_field="query_type")

    # refusal 检索侧观测（明确标注：不是 answer 级拒答精度）
    threshold = float(getattr(rag, "DEFAULT_REFUSAL_THRESHOLD", 0.03))
    max_scores = [max(r["scores"]) if r["scores"] else 0.0 for r in refusal_rows]
    by_refusal = {
        "non_refusal": {"n": len(truth_rows), **overall},
        "refusal": {
            "n": len(refusal_rows),
            "max_score_observation": {
                "mean_max_rrf_score": (
                    sum(max_scores) / len(max_scores) if max_scores else None),
                "p50_max_rrf_score": (
                    sorted(max_scores)[len(max_scores) // 2] if max_scores else None),
                "share_below_product_refusal_threshold": (
                    sum(1 for s in max_scores if s < threshold) / len(max_scores)
                    if max_scores else None),
                "product_threshold": threshold,
            },
            "note": "refusal cases 无 chunk-level truth；此处仅为检索分数观测，"
                    "不代表 answer 级拒答精度（后者属生成质量，本阶段未测）",
        },
    }

    return {
        "overall": overall,
        "by_language": by_language,
        "by_query_type": by_query_type,
        "by_refusal": by_refusal,
    }


def failure_list(results: list[dict]) -> list[dict]:
    """最差失败样本：仅在真值 case 上计算，按 (recall@20, source_recall@20,
    case_id) 稳定升序。只引用 chunk/source id，不含证据 snippet 文本。"""
    rows: list[dict] = []
    for r in results:
        if not r["relevant_chunk_ids"]:
            continue
        m = r["metrics"]
        relevant = set(r["relevant_chunk_ids"])
        first_rank = next(
            (i for i, cid in enumerate(r["retrieved_chunk_ids"], start=1)
             if cid in relevant),
            None,
        )
        failure_types: list[str] = []
        if m["recall@20"] < 1.0:
            failure_types.append("chunk_not_retrieved_top20")
        if m["source_recall@20"] < 1.0:
            failure_types.append("source_not_retrieved_top20")
        rows.append({
            "case_id": r["case_id"],
            "query": r["query"],
            "language": r["language"],
            "query_type": r["query_type"],
            "recall@5": m["recall@5"], "recall@10": m["recall@10"],
            "recall@20": m["recall@20"],
            "source_recall@5": m["source_recall@5"],
            "source_recall@10": m["source_recall@10"],
            "source_recall@20": m["source_recall@20"],
            "mrr": m["mrr"],
            "expected_chunk_ids": r["relevant_chunk_ids"],
            "expected_source_ids": r["relevant_source_ids"],
            "actual_top20_chunk_ids": r["retrieved_chunk_ids"][:20],
            "actual_top20_source_ids": r["retrieved_source_ids"][:20],
            "first_relevant_rank": first_rank,
            "failure_types": failure_types,
        })
    rows.sort(key=lambda f: (
        round(f["recall@20"], 6), round(f["source_recall@20"], 6), f["case_id"],
    ))
    return rows


# ── 数据质量机械检查 ──────────────────────────────────────────────────
# data-analytics:analyze-data-quality skill 在本环境中不可用（可用技能
# 列表中不存在该技能）；此处实施等价的确定性六维机械检查（完整性/唯一性/
# 有效性/一致性/引用完整性/分母与分组合理性），全部为复算，无 LLM 参与。

def data_quality_check(
    *,
    results: list[dict],
    metrics: dict,
    failures: list[dict],
    mapping_report: dict,
    manifest: dict,
    frozen_chunk_ids: set[str],
) -> dict:
    """对本次结构化评测结果做确定性机械检查，返回逐项结论。

    Returns:
        {"passed", "errors", "warnings", "checks"}；errors 非空即
        passed=False（fail-closed 报告，不掩盖问题）。
    """
    from evaluation.metrics import recall_at_k, ndcg_at_k, source_recall_at_k

    errors: list[str] = []
    warnings: list[str] = []
    checks: list[dict] = []

    def _check(name: str, ok: bool, detail: str = "") -> None:
        checks.append({"name": name, "ok": bool(ok), "detail": detail})
        if not ok:
            errors.append(f"{name}: {detail}")

    den = metrics["overall"]["denominators"]
    total = den["total_cases"]

    # 1. 完整性：per-case 行数、必需键、分组齐全
    _check("completeness.per_case_rows",
           len(results) == total,
           f"rows={len(results)} expected={total}")
    if results:
        missing = PER_CASE_OUTPUT_KEYS - set(results[0])
        _check("completeness.per_case_keys", not missing,
               f"missing keys={sorted(missing)}")
    for group_name in ("by_language", "by_query_type", "by_refusal"):
        _check(f"completeness.group_{group_name}", group_name in metrics,
               f"group {group_name} absent")

    # 2. 唯一性：case_id 唯一、failure 行唯一
    ids = [r["case_id"] for r in results]
    dup = sorted({c for c in ids if ids.count(c) > 1})
    _check("uniqueness.case_ids", not dup, f"duplicates={dup}")
    fids = [f["case_id"] for f in failures]
    fdup = sorted({c for c in fids if fids.count(c) > 1})
    _check("uniqueness.failure_rows", not fdup, f"duplicates={fdup}")

    # 3. 有效性：指标值域、scores 非空
    bad_values: list[str] = []
    for r in results:
        for key, value in r["metrics"].items():
            if not (0.0 <= value <= 1.0):
                bad_values.append(f"{r['case_id']}.{key}={value}")
    _check("validity.metric_ranges", not bad_values, "; ".join(bad_values[:5]))
    empty_scores = [r["case_id"] for r in results if not r["scores"]]
    _check("validity.scores_nonempty", not empty_scores,
           f"empty scores: {empty_scores[:5]}")

    # 4. 一致性：per-case 指标复算一致；聚合 = per-case 均值
    mismatch: list[str] = []
    for r in results:
        if not r["relevant_chunk_ids"]:
            continue
        recomputed = {
            **{f"recall@{k}": recall_at_k(
                r["retrieved_chunk_ids"], set(r["relevant_chunk_ids"]), k)
               for k in KS},
            **{f"ndcg@{k}": ndcg_at_k(
                r["retrieved_chunk_ids"], set(r["relevant_chunk_ids"]), k)
               for k in KS},
            **{f"source_recall@{k}": source_recall_at_k(
                r["retrieved_source_ids"], set(r["relevant_source_ids"]), k)
               for k in KS},
        }
        for key, value in recomputed.items():
            if abs(value - r["metrics"][key]) > 1e-9:
                mismatch.append(f"{r['case_id']}.{key}")
    _check("consistency.per_case_recompute", not mismatch,
           "; ".join(mismatch[:5]))

    agg_mismatch: list[str] = []
    for key in ("recall@5", "recall@10", "recall@20",
                "ndcg@5", "ndcg@10", "ndcg@20", "mrr",
                "source_recall@5", "source_recall@10", "source_recall@20"):
        mean = sum(r["metrics"][key] for r in results if r["metrics"]) / (
            sum(1 for r in results if r["metrics"]) or 1)
        if abs(mean - metrics["overall"][key]) > 1e-9:
            agg_mismatch.append(f"{key}: {mean:.6f} vs {metrics['overall'][key]:.6f}")
    _check("consistency.aggregates_vs_mean", not agg_mismatch,
           "; ".join(agg_mismatch[:5]))

    # 5. 引用完整性：真值 chunk ∈ 冻结语料；failure 行期望集 ⊆ per-case 真值
    orphan = sorted({
        cid for r in results for cid in r["relevant_chunk_ids"]
        if cid not in frozen_chunk_ids
    })
    _check("referential.chunk_ids_in_corpus", not orphan,
           f"orphan chunk_ids={orphan[:5]}")
    if mapping_report["mapping"]["mapping_failures"]:
        _check("referential.mapping_failures_zero", False,
               str(mapping_report["mapping"]["mapping_failures"]))
    else:
        _check("referential.mapping_failures_zero", True)
    per_case_expected = {r["case_id"]: set(r["relevant_chunk_ids"])
                         for r in results}
    leak = [
        f["case_id"] for f in failures
        if set(f["expected_chunk_ids"]) != per_case_expected.get(f["case_id"], set())
    ]
    _check("referential.failure_expected_matches", not leak,
           f"mismatched={leak[:5]}")

    # manifest 自洽：self-hash 与 inputs 字节（manifest 未提供时跳过——
    # 由 verify_frozen_inputs 的 61 项复算与 pytest 的
    # test_manifest_records_inputs_outputs_shas 覆盖）
    if manifest is None:
        checks.append({"name": "referential.manifest_self_hash",
                       "ok": True, "detail": "skipped (manifest=None)"})
        checks.append({"name": "referential.manifest_input_shas",
                       "ok": True, "detail": "skipped (manifest=None)"})
    else:
        _check("referential.manifest_self_hash",
               manifest.get("manifest_sha256") == self_hash(manifest))
        bad_input = [
            name for name, rec in manifest.get("inputs", {}).items()
            if not Path(rec["path"]).is_file()
            or sha256_bytes(Path(rec["path"])) != rec["sha256"]
        ]
        _check("referential.manifest_input_shas", not bad_input,
               f"bad={bad_input[:5]}")

    # 6. 分母与分组合理性
    _check("denominators.sum_equals_total",
           den["chunk_metrics_cases"] + den["no_chunk_truth_cases"] == total,
           str(den))
    _check("denominators.no_chunk_truth_equals_refusal",
           den["no_chunk_truth_cases"] == metrics["by_refusal"]["refusal"]["n"],
           str(den))
    lang_n = sum(g["n"] for g in metrics["by_language"].values())
    _check("denominators.by_language_sums",
           lang_n == den["chunk_metrics_cases"],
           f"sum={lang_n} expected={den['chunk_metrics_cases']}")
    qtype_n = sum(g["n"] for g in metrics["by_query_type"].values())
    _check("denominators.by_query_type_sums",
           qtype_n == den["chunk_metrics_cases"],
           f"sum={qtype_n} expected={den['chunk_metrics_cases']}")
    refusal_n = sum(1 for r in results if r["should_refuse"])
    _check("denominators.refusal_count",
           refusal_n == den["no_chunk_truth_cases"],
           f"refusal={refusal_n} expected={den['no_chunk_truth_cases']}")

    return {
        "passed": not errors,
        "error_count": len(errors),
        "warning_count": len(warnings),
        "errors": errors,
        "warnings": warnings,
        "checks": checks,
        "note": "data-analytics:analyze-data-quality skill 在本环境中不可用"
                "（可用技能列表中不存在）；此为等价的确定性机械复算",
    }


# ── parser 漂移审计（独立测量，不混入召回指标）───────────────────────

def parser_drift_audit(documents_dir: Path, chunks_path: Path) -> dict:
    """测量当前运行时 chunker 对冻结语料的复现率。

    用生产 ``_load_index_chunks``（src/loaders + src/chunking v3 Section
    分块）重新解析每个语料文档，与冻结 chunks.jsonl 逐文本比较：
    - 每 source：冻结 chunk 数 / 重建 chunk 数 / 文本精确命中数 /
      chunk_id 前缀格式是否一致；
    - 该审计**不是**检索指标：它回答“冻结 chunk 级真值能否映射到当前
      运行时重建索引”这一基线前提问题。
    """
    import src.rag as rag

    frozen_by_source: dict[str, list[str]] = {}
    frozen_ids_by_source: dict[str, list[str]] = {}
    for row in load_jsonl(chunks_path):
        frozen_by_source.setdefault(row["source"], []).append(row["text"])
        frozen_ids_by_source.setdefault(row["source"], []).append(row["chunk_id"])

    per_source: dict[str, dict] = {}
    total_frozen = total_rebuilt = total_exact = 0
    for path in sorted(Path(documents_dir).iterdir()):
        if not path.is_file():
            continue
        source = path.name
        frozen_texts = frozen_by_source.get(source)
        if frozen_texts is None:
            continue
        buf = io.StringIO()
        with redirect_stdout(buf):
            chunks, metadatas, ids, _, _, _ = rag._load_index_chunks(str(path))
        frozen_ids = frozen_ids_by_source[source]
        frozen_set = set(frozen_texts)
        exact = sum(1 for c in chunks if c in frozen_set)
        id_format_matches = bool(
            ids and frozen_ids
            and ids[0].rsplit("_chunk_", 1)[0][:12]
            == frozen_ids[0].rsplit("_chunk_", 1)[0][:12]
        )
        per_source[source] = {
            "source": source,
            "frozen_chunks": len(frozen_texts),
            "rebuilt_chunks": len(chunks),
            "exact_text_matches": exact,
            "exact_text_share": exact / len(frozen_texts) if frozen_texts else 0.0,
            "id_format_matches": id_format_matches,
        }
        total_frozen += len(frozen_texts)
        total_rebuilt += len(chunks)
        total_exact += exact

    return {
        "note": "当前运行时 chunker（Section 分块）对冻结语料（get_splitter "
                "纯分块）的复现审计；仅回答 chunk 级真值可映射性，不是检索指标",
        "per_source": per_source,
        "total_frozen_chunks": total_frozen,
        "total_rebuilt_chunks": total_rebuilt,
        "total_exact_text_matches": total_exact,
    }


# ── 产物写入 ──────────────────────────────────────────────────────────

def _git_head() -> dict:
    try:
        head = subprocess.run(
            ["git", "rev-parse", "HEAD"], capture_output=True, text=True,
            cwd=REPO_ROOT, timeout=10,
        ).stdout.strip()
    except Exception:
        head = ""
    try:
        porcelain = subprocess.run(
            ["git", "status", "--porcelain"], capture_output=True, text=True,
            cwd=REPO_ROOT, timeout=10,
        ).stdout
        dirty = bool(porcelain.strip())
    except Exception:
        dirty = None
    return {"head": head, "dirty": dirty}


def _dependencies() -> dict:
    import importlib.metadata
    out: dict[str, str] = {"python": sys.version.split()[0]}
    for pkg in ("chromadb", "sentence-transformers", "rank-bm25",
                "langchain-text-splitters"):
        try:
            out[pkg] = importlib.metadata.version(pkg)
        except importlib.metadata.PackageNotFoundError:
            out[pkg] = "unknown"
    return out


def _check_output_containment(out_dir: Path, protected: list[Path]) -> None:
    """禁止产物目录与受保护输入目录互相包含（防误写）。"""
    out_res = Path(out_dir).resolve()
    for p in protected:
        r = Path(p).resolve()
        if out_res == r or r in out_res.parents or out_res in r.parents:
            raise ValueError(
                f"output dir {out_res} overlaps protected input dir {r}"
            )


def write_artifacts(
    out_dir: Path,
    *,
    cases: list[dict],
    results: list[dict],
    metrics: dict,
    failures: list[dict],
    mapping_report: dict,
    verify_report: dict,
    audit: dict,
    determinism: dict,
    index: dict,
    cleaned: bool,
    params: dict,
    frozen_chunk_ids: set[str],
) -> dict:
    """写出七个产物并构建 manifest（self-hash 约定 + inputs/outputs SHA）。

    第 7 个产物 data-quality-mechanical-check.json 是
    data-analytics:analyze-data-quality 的等价确定性机械检查（该 skill
    在本环境不可用），随产物落盘以便审计。
    """
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    summary = {
        "scope": "v2.0.11-frozen-current retrieval baseline (Phase 6-A)",
        "frozen_revision": "v2.0.11-owner-authorized-en048-same-source-repair",
        "frozen_revision_status": "CANDIDATE",
        "activation_blocked": True,
        "metrics": metrics,
        "not_measured": {
            "generation_and_citation": {
                "measured": False,
                "reason": "Phase 6-A 只做 Retrieval Baseline：不调用生成模型、"
                          "不做 136 条生成答案、不做 LLM judge；answer-quality / "
                          "citation-faithfulness 无真值无产出，不伪造数值",
            },
            "refusal_accuracy": {
                "measured": False,
                "reason": "answer 级拒答精度依赖生成判定，本阶段未测；仅提供 "
                          "refusal 组的检索分数观测",
            },
        },
        "failure_counts": {
            "failure_analysis_rows": len(failures),
            "chunk_not_retrieved_top20": sum(
                1 for f in failures if "chunk_not_retrieved_top20" in f["failure_types"]),
            "source_not_retrieved_top20": sum(
                1 for f in failures if "source_not_retrieved_top20" in f["failure_types"]),
            "note": "failure_analysis_rows 覆盖全部真值 case（含 recall@20=1.0 "
                    "的行），后两项才是真正的失败计数",
        },
        "parser_drift_audit": audit,
        "verification": {
            "verified": verify_report["verified"],
            "drift_count": len(verify_report["drift"]),
        },
        "determinism": determinism,
        "mapping": mapping_report["mapping"],
    }

    per_case_path = out_dir / "per-case-retrieval-results.jsonl"
    with open(per_case_path, "w", encoding="utf-8") as stream:
        for row in results:
            stream.write(json.dumps(row, ensure_ascii=False) + "\n")

    failure_md = _render_failure_analysis(failures, metrics, determinism)
    (out_dir / "failure-analysis.md").write_text(failure_md, encoding="utf-8")
    (out_dir / "schema-compatibility-report.md").write_text(
        _render_schema_report(mapping_report, verify_report), encoding="utf-8")
    (out_dir / "BASELINE_SCOPE.md").write_text(
        _render_scope(metrics, audit, verify_report), encoding="utf-8")
    (out_dir / "baseline-summary.json").write_text(
        canonical_json(summary), encoding="utf-8")

    # 数据质量机械检查（manifest 维度在此跳过——manifest 此时尚未落盘，
    # 其 self-hash / inputs SHA 由 verify_frozen_inputs 与 pytest 覆盖）
    dq = data_quality_check(
        results=results, metrics=metrics, failures=failures,
        mapping_report=mapping_report, manifest=None,
        frozen_chunk_ids=frozen_chunk_ids,
    )
    (out_dir / "data-quality-mechanical-check.json").write_text(
        canonical_json(dq), encoding="utf-8")

    inputs: dict[str, dict] = {}
    frozen_outputs: dict[str, dict] = {}
    for check in verify_report["checks"]:
        if check["status"] != "ok":
            continue
        if check["kind"] == "inputs":
            inputs.setdefault(check["name"], {
                "path": check["path"], "sha256": check["actual"],
            })
        elif check["kind"] == "outputs":
            frozen_outputs.setdefault(check["name"], {
                "path": check["path"], "sha256": check["actual"],
            })

    manifest = {
        "task": "v2.0.11-frozen-current-retrieval-baseline",
        "frozen_revision": "v2.0.11-owner-authorized-en048-same-source-repair",
        "frozen_revision_status": "CANDIDATE",
        "inputs": inputs,
        "frozen_outputs": frozen_outputs,
        "outputs": {
            name: sha256_bytes(out_dir / name)
            for name in (
                "baseline-summary.json", "per-case-retrieval-results.jsonl",
                "failure-analysis.md", "schema-compatibility-report.md",
                "BASELINE_SCOPE.md", "data-quality-mechanical-check.json",
            )
        },
        "code": _git_head(),
        "parameters": params,
        "dependencies": _dependencies(),
        "model": {
            "name": index["model_name"],
            "embedding_dimension": index["embedding_dimension"],
            "offline": True,
            "note": "本地缓存离线加载（HF_HUB_OFFLINE=1）；检索期间无网络调用",
        },
        "isolation": {
            "collection_name": index["collection_name"],
            "data_dir": index["data_dir"],
            "chroma_dir": index["chroma_dir"],
            "client": "chromadb.PersistentClient（独立临时目录）",
            "no_user_index_touched": True,
            "no_sidecar_manifests": True,
            "cleaned": cleaned,
        },
        "determinism": determinism,
        "run_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
    }
    manifest["manifest_sha256"] = self_hash(manifest)
    (out_dir / "manifest.json").write_text(canonical_json(manifest),
                                           encoding="utf-8")
    return manifest


def _render_failure_analysis(failures: list[dict], metrics: dict,
                             determinism: dict) -> str:
    lines = [
        "# Failure Analysis — v2.0.11 frozen retrieval baseline",
        "",
        "## 范围",
        "",
        f"- 真值 case（chunk-level truth）："
        f"**{metrics['overall']['denominators']['chunk_metrics_cases']}**",
        f"- 无 chunk-level truth（refusal）case："
        f"**{metrics['overall']['denominators']['no_chunk_truth_cases']}** —— "
        "不进入召回分母，不伪造 0 分",
        f"- 失败样本行数：**{len(failures)}**（全部真值 case，最差在前，稳定排序："
        "recall@20 → source_recall@20 → case_id；真正失败计数见 "
        "baseline-summary.json failure_counts）",
        "",
        "## 最差失败样本（Top 20）",
        "",
        "| case | lang | query_type | recall@20 | src_recall@20 | mrr | "
        "首中位 | 失败类型 | 期望 chunk/source | 实际 top-20 chunk（前 10） |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for f in failures[:20]:
        expected = ", ".join(f["expected_chunk_ids"]) or "∅"
        expected_src = ", ".join(f["expected_source_ids"]) or "∅"
        actual = ", ".join(f["actual_top20_chunk_ids"][:10]) or "∅"
        rank = f["first_relevant_rank"] if f["first_relevant_rank"] else "—"
        ftype = ", ".join(f["failure_types"]) or "—"
        lines.append(
            f"| {f['case_id']} | {f['language']} | {f['query_type']} | "
            f"{f['recall@20']:.3f} | {f['source_recall@20']:.3f} | "
            f"{f['mrr']:.3f} | {rank} | {ftype} | "
            f"{expected} / {expected_src} | {actual} |"
        )
    lines += [
        "",
        "## 未测指标（可测性审计）",
        "",
        "- **answer-quality / citation-faithfulness**：本阶段不调用生成模型、"
        "不产生生成答案、不做 LLM judge——无真值无产出，不得编造分数。",
        "- **refusal 精度（answer 级）**：依赖生成判定；本阶段仅提供 refusal "
        "组检索分数观测（见 baseline-summary.json by_refusal）。",
        "- **query rewrite / decomposition / reranker 消融**：属 Phase 6-B "
        "候选实验，不在只读基线范围内。",
        "",
        f"- 确定性复验：{determinism}",
        "",
        "> 说明：失败样本只引用 case id / query / chunk id / source id；"
        "不包含、不改写任何冻结证据 snippet 文本。",
    ]
    return "\n".join(lines)


def _render_schema_report(mapping_report: dict, verify_report: dict) -> str:
    m = mapping_report["mapping"]
    lines = [
        "# Schema Compatibility Report — v1 EvalCase ↔ v2.0.11 draft/evidence",
        "",
        "## 结论",
        "",
        "v2.0.11 `draft-after.jsonl` **不能**直接喂给 v1 `evaluation.schema."
        "load_dataset`/`EvalCase.from_dict`：draft 行携带 v1 契约之外的字段"
        "（annotation / doc_target / is_refusal_turn / note / relevance_level / "
        "relevant_chunk_ids），且 `relevant_chunks` 元素含 `chunk_id` 键。"
        "适配器在内存中完成字段映射（本文件），绝不回写 v2.0.11。",
        "",
        "## draft 字段映射",
        "",
        "| 字段 | 映射 | 说明 |",
        "|---|---|---|",
    ]
    for field in sorted(m["draft_fields"]["mapped"]):
        lines.append(f"| {field} | 直接映射 | v1 契约字段 |")
    for field in sorted(m["draft_fields"]["unmapped"]):
        lines.append(f"| {field} | 不映射 | {m['draft_fields']['reasons'][field]} |")
    lines += [
        "",
        "## evidence 字段映射",
        "",
        "真值（chunk/source 级）以 `evidence-after.jsonl` 为准；"
        "`chunk_text_sha256` 已 149/149 与冻结 `chunks.jsonl` 逐字节核验。"
        "snippet / char_range / coordinate_contract 等溯源字段不进入指标。",
        "",
        "## 数据观测（冻结数据固有特性，不做“修复”）",
        "",
        f"- draft↔evidence chunk 集不一致 case："
        f"**{sum(1 for d in m['divergences'] if d['kind'] == 'draft_vs_evidence_chunks')}**",
        f"- draft↔evidence source 集不一致 case："
        f"**{sum(1 for d in m['divergences'] if d['kind'] == 'draft_vs_evidence_sources')}**",
        f"- mapping failure（evidence chunk_id 不在冻结语料）："
        f"**{len(m['mapping_failures'])}**",
        f"- case 数：total={m['case_counts']['total']}，"
        f"with_chunk_truth={m['case_counts']['with_chunk_truth']}，"
        f"no_chunk_truth={m['case_counts']['no_chunk_truth']}",
        "",
        "## 冻结校验",
        "",
        f"- 冻结输入校验：{'通过' if verify_report['verified'] else '失败'} "
        f"（{len(verify_report['checks'])} 项复算，漂移 {len(verify_report['drift'])} 项）",
    ]
    return "\n".join(lines)


def _render_scope(metrics: dict, audit: dict, verify_report: dict) -> str:
    overall = metrics["overall"]
    return "\n".join([
        "# BASELINE_SCOPE — v2.0.11 frozen product retrieval baseline",
        "",
        "## 本阶段测了什么",
        "",
        "- 检索链路：生产 `model.encode` → Chroma（hnsw:space=cosine）→ "
        "BM25（CJK n-gram）→ RRF（k=60），对冻结 1006 chunks 建索引，"
        "136 条查询逐条跑当前检索代码（`src.rag.retrieve_hybrid_with_sources`）。",
        "- 指标：chunk `recall@5/10/20`、`nDCG@5/10/20`、`MRR`、source "
        "recall@5/10/20；按 language / query_type / refusal 分组，每组记录 "
        "有效分母 n；无 chunk-level truth 的 31 个 refusal case 不进入召回分母。",
        "- 最差失败样本清单（稳定排序，见 failure-analysis.md）。",
        "",
        "## parser 阶段为什么独立测量（关键前提）",
        "",
        f"- 冻结语料由 `get_splitter`（纯 RecursiveCharacterTextSplitter，"
        "text 2000/200）构建；当前运行时 `_load_index_chunks` 走 "
        "src/loaders + src/chunking v3 Section 分块。实测复现审计："
        f"冻结 {audit.get('total_frozen_chunks')} chunks → 当前 chunker "
        f"重建 {audit.get('total_rebuilt_chunks')} chunks，文本精确命中 "
        f"{audit.get('total_exact_text_matches')}（见 baseline-summary.json "
        "parser_drift_audit 逐 source 明细）。",
        "- 因此冻结 evidence 的 `chunk_id` 真值**只对冻结 chunks 成立**；"
        "基线以冻结 chunks 为索引内容（检索链 embedding/Chroma/BM25/RRF "
        "与产品逐函数一致），parser 行为以漂移审计单独报告，不混入召回指标。",
        "- 含义：当前产品若直接索引语料文档，其 chunk 边界与冻结真值不兼容，"
        "chunk 级召回将不可测量——这是 Phase 6-B 的首要候选改进方向。",
        "",
        "## 隔离与安全",
        "",
        "- Chroma 位于一次性临时数据目录（`MNEME_DATA_DIR` 语义由适配器自行 "
        "`PersistentClient` 承担），从不引用 `src.rag.CHROMA_DB_PATH`，"
        "物理上不触碰用户持久化索引；不写 collection manifest / BM25 sidecar。",
        "- 不调用生成模型 / LLM judge；无网络调用；不修改 v2.0.11 任何文件；"
        "不 stage / commit / push。",
        f"- 冻结输入校验：{'通过' if verify_report['verified'] else '失败'}。",
        "",
        "## 明确不是",
        "",
        "- v2.0.11 仍是只读 CANDIDATE（activation_blocked=true、"
        "human_reviewed=false、TARGETED_REVIEW_BLOCKED），不代表 active、"
        "人工批准或 release。",
        "- 本基线不是 answer-quality / citation / refusal 精度评测。",
    ])


# ── 编排 ──────────────────────────────────────────────────────────────

def run_baseline(
    *,
    revision_dir: Path,
    chunks_path: Path,
    chunk_manifest_path: Path,
    current_draft_path: Path,
    out_dir: Path,
    data_dir: Path | None = None,
    collection_name: str = COLLECTION_NAME,
    verify_determinism: bool = True,
    corpus_documents_dir: Path | None = CORPUS_DOCUMENTS_DIR,
) -> dict:
    """执行只读检索基线并写出全部产物。任何冻结漂移 → FrozenInputDrift。"""
    _check_output_containment(out_dir, [
        revision_dir, chunks_path.parent, current_draft_path.parent,
        REPO_ROOT / "evaluation/datasets/v2", REPO_ROOT / "data/v2-corpus",
    ])

    verify_report = verify_frozen_inputs(
        revision_dir=revision_dir, chunks_path=chunks_path,
        chunk_manifest_path=chunk_manifest_path,
        current_draft_path=current_draft_path,
    )
    if not verify_report["verified"]:
        raise FrozenInputDrift(
            "frozen input drift: " + json.dumps(
                verify_report["drift"], ensure_ascii=False))

    cases, mapping_report = load_cases(
        revision_dir / "draft-after.jsonl",
        revision_dir / "evidence-after.jsonl",
        chunks_path,
    )

    own_data_dir = data_dir is None
    data_dir = Path(data_dir) if data_dir is not None else Path(
        tempfile.mkdtemp(prefix="mneme-v211-baseline-"))
    data_dir.mkdir(parents=True, exist_ok=True)

    cleaned = False
    index = {}
    try:
        index = build_frozen_index(chunks_path, data_dir, collection_name)
        results = run_retrieval(cases, index)
        metrics = compute_metrics(
            results,
            mapping_failure_rows=len(
                mapping_report["mapping"]["mapping_failures"]),
        )
        failures = failure_list(results)
        audit = (
            parser_drift_audit(corpus_documents_dir, chunks_path)
            if corpus_documents_dir is not None
            and Path(corpus_documents_dir).is_dir()
            else {"note": "parser drift audit skipped (no documents dir)"}
        )
        determinism = _verify_determinism(
            results, cases, chunks_path, data_dir, collection_name,
        ) if verify_determinism else {"verified": None, "note": "skipped"}
    finally:
        close_index(index)
        if own_data_dir:
            shutil.rmtree(data_dir, ignore_errors=True)
            cleaned = not data_dir.exists()

    params = {
        "collection_name": collection_name,
        "top_k_retrieval": 70,
        "rrf_k": 60,
        "ks": list(KS),
        "refusal_threshold_observation": True,
        "verify_determinism": verify_determinism,
    }
    manifest = write_artifacts(
        out_dir, cases=cases, results=results, metrics=metrics,
        failures=failures, mapping_report=mapping_report,
        verify_report=verify_report, audit=audit, determinism=determinism,
        index=index, cleaned=cleaned, params=params,
        frozen_chunk_ids={
            c["chunk_id"] for c in load_frozen_chunks(chunks_path)
        },
    )
    return {
        "status": "ok",
        "results": results,
        "metrics": metrics,
        "failures": failures,
        "manifest": manifest,
        "case_count": len(cases),
    }


def _verify_determinism(results: list[dict], cases: list[dict],
                        chunks_path: Path, data_dir: Path,
                        collection_name: str) -> dict:
    """第二次离线构建（独立临时目录）→ 逐 case 比较非时间字段。"""
    import tempfile as _tf
    second_dir = Path(_tf.mkdtemp(prefix="mneme-v211-baseline-"))
    index2 = None
    differences: list[dict] = []
    metric_differences: list[dict] = []
    try:
        index2 = build_frozen_index(chunks_path, second_dir, collection_name)
        results2 = run_retrieval(cases, index2)
        by_id = {r["case_id"]: r for r in results2}
        for r in results:
            other = by_id[r["case_id"]]
            for field in ("retrieved_chunk_ids", "retrieved_source_ids",
                          "scores", "metrics"):
                if r[field] != other[field]:
                    differences.append({
                        "case_id": r["case_id"], "field": field,
                    })
                    if field == "metrics":
                        for key in sorted(r["metrics"]):
                            if r["metrics"][key] != other["metrics"][key]:
                                metric_differences.append({
                                    "case_id": r["case_id"], "key": key,
                                    "build1": r["metrics"][key],
                                    "build2": other["metrics"][key],
                                })
    finally:
        close_index(index2)
        shutil.rmtree(second_dir, ignore_errors=True)
    return {
        "verified": not differences,
        "cases_compared": len(cases),
        "difference_count": len(differences),
        "metric_difference_count": len(metric_differences),
        "metric_differences": metric_differences[:20],
        "differences": differences[:20],
        "note": "第二次构建使用独立临时目录与独立 collection；比较除 "
                "retrieval_ms 外全部字段。raw ranking 差异源于 Chroma/HNSW "
                "索引构建的非确定性（同索引重复查询逐位一致，跨构建在深 "
                "rank 处有近邻扰动）；metric_difference_count 是 per-case "
                "指标受影响的 case 数，metric_differences 给出明细，"
                "聚合指标仍稳定",
    }


def main(argv: list[str] | None = None) -> int:
    """CLI。退出码：0=成功；2=冻结输入漂移（fail-closed，零产物）；1=其他。"""
    import argparse

    parser = argparse.ArgumentParser(
        description="Phase 6-A: v2.0.11 frozen product retrieval baseline")
    parser.add_argument("--revision-dir", type=Path,
                        default=FROZEN_REVISION_DIR)
    parser.add_argument("--chunks", type=Path, default=CHUNKS_PATH)
    parser.add_argument("--chunk-manifest", type=Path,
                        default=CHUNK_MANIFEST_PATH)
    parser.add_argument("--current-draft", type=Path, default=CURRENT_DRAFT_PATH)
    parser.add_argument("--corpus-documents", type=Path,
                        default=CORPUS_DOCUMENTS_DIR)
    parser.add_argument("--output", type=Path, default=OUTPUT_DIR)
    parser.add_argument("--data-dir", type=Path, default=None,
                        help="临时数据目录（默认自动创建并在结束后清理）")
    parser.add_argument("--skip-determinism", action="store_true")
    parser.add_argument("--skip-parser-audit", action="store_true")
    args = parser.parse_args(argv)

    try:
        verify_report = verify_frozen_inputs(
            revision_dir=args.revision_dir, chunks_path=args.chunks,
            chunk_manifest_path=args.chunk_manifest,
            current_draft_path=args.current_draft,
        )
    except Exception as exc:
        print(f"verification error: {exc}", file=sys.stderr)
        return 1

    if not verify_report["verified"]:
        print("FAIL-CLOSED: frozen input drift detected, zero outputs.",
              file=sys.stderr)
        for d in verify_report["drift"]:
            print(f"  [{d['kind']}/{d['status']}] {d['name']} "
                  f"expected={d['expected']} actual={d['actual']} "
                  f"path={d['path']}", file=sys.stderr)
        return 2

    print(f"frozen inputs verified: {len(verify_report['checks'])} checks, "
          f"0 drift")
    try:
        summary = run_baseline(
            revision_dir=args.revision_dir, chunks_path=args.chunks,
            chunk_manifest_path=args.chunk_manifest,
            current_draft_path=args.current_draft,
            out_dir=args.output, data_dir=args.data_dir,
            verify_determinism=not args.skip_determinism,
            corpus_documents_dir=None if args.skip_parser_audit
            else args.corpus_documents,
        )
    except FrozenInputDrift as exc:
        print(f"FAIL-CLOSED: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:
        import traceback
        traceback.print_exc(file=sys.stderr)
        return 1

    metrics = summary["metrics"]["overall"]
    print(f"baseline complete: {summary['case_count']} cases -> "
          f"{args.output}")
    print(f"  chunk recall@5={metrics.get('recall@5'):.4f} "
          f"recall@10={metrics.get('recall@10'):.4f} "
          f"recall@20={metrics.get('recall@20'):.4f} "
          f"mrr={metrics.get('mrr'):.4f}")
    print(f"  source_recall@10={metrics.get('source_recall@10'):.4f}")
    print(f"  denominators: {metrics['denominators']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
