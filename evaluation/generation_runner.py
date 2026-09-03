"""Generation evaluation runner for Mneme RAG.

Runs the full generation pipeline (retrieval → LLM answer) for each
evaluation case and computes generation quality metrics including
correctness, faithfulness, citation quality, and refusal accuracy.

This runner is intentionally separate from the retrieval runner so
that retrieval failures and generation failures are not conflated.

Usage::

    python -m evaluation.generation_runner --dataset v1 --output results/gen_baseline.json

Note: This runner requires an external LLM API and incurs costs.
      It should only be run manually or on a schedule, not on every PR.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from evaluation.schema import EvalCase, load_dataset
from evaluation.citation_metrics import (
    CitationMetrics,
    evaluate_citations_context_aware,
    parse_sources_citation_map,
)
from evaluation.answer_metrics import (
    ANSWER_HIT_METRIC_VERSION,
    AnswerHitResult,
    compute_answer_hit,
)


# ── 真值 chunk 口径与 token 实耗 ────────────────────────────────────

# 索引侧运行时 chunk_id 形态：{source_sha256(64-hex 全长)}_chunk_{n}；
# 真值/registry 侧冻结格式：{source_sha256_prefix(12-hex)}_chunk_{n}
# （index_contract 冻结契约）。二者是同一哈希的两种截断。
_INDEX_HEX64_CHUNK_RE = re.compile(r"^([0-9a-f]{64})_chunk_(\d+)$")
_TRUTH_HEX12_CHUNK_RE = re.compile(r"^([0-9a-f]{12})_chunk_(\d+)$")


def _normalize_chunk_id(chunk_id: str) -> str:
    """评测侧 chunk_id 归一：64-hex 截断为 12-hex 前缀，其余形态原样返回。

    只影响评测侧比对（比对双方统一到 12-hex 域后交集非空），不改产品
    侧 ID 形态——v2 语料 13 个 source 前缀零碰撞，截断映射唯一。
    """
    m = _INDEX_HEX64_CHUNK_RE.match(chunk_id)
    if m:
        return f"{m.group(1)[:12]}_chunk_{m.group(2)}"
    if _TRUTH_HEX12_CHUNK_RE.match(chunk_id):
        return chunk_id
    return chunk_id


def _normalize_source_chunk_ids(sources: str) -> str:
    """把 ``format_sources`` 输出行内 ``chunk_id=<64hex>`` 归一为 12-hex。

    引用指标（evaluate_citations_context_aware）内部从 sources 原文解析
    chunk_id（S#→chunk 映射），若只归一集合侧而 sources 原文保留 64-hex，
    解析结果与归一域永不相等（M1.1 端到端测试的 RED 证据：fabricated）。
    归一后证据记录与报告口径统一为 12-hex。
    """
    return re.sub(
        r"chunk_id=([0-9a-f]{64})",
        lambda m: f"chunk_id={m.group(1)[:12]}",
        sources,
    )


def resolve_relevant_chunk_ids(
    case: EvalCase,
    all_metadatas: list[dict],
    all_docs: list[str],
) -> set[str]:
    """解析一个 case 的真值相关 chunk 集合（citation recall 的 ground truth）。

    v2.1 的 ``relevant_chunk_ids`` 是人工终审确认的权威 chunk ID
    （与索引 metadata 的 chunk_id 同源）——非空时**直接采用**，禁止再走
    snippet 模糊匹配稀释口径；v1 数据集无该字段，回退到 snippet 匹配
    （仅 exact/overlap 计入，与既有行为一致）。
    """
    if case.relevant_chunk_ids:
        return set(case.relevant_chunk_ids)

    from evaluation.compare import match_snippet_to_chunks
    matched: set[str] = set()
    for rc in case.relevant_chunks:
        if rc.chunk_text_snippet:
            ids, method = match_snippet_to_chunks(
                rc.chunk_text_snippet, rc.source_id, all_metadatas, all_docs,
            )
            if method in ("exact", "overlap"):
                matched.update(ids)
    return matched


def _collect_case_tokens() -> tuple[int | None, int | None, int | None]:
    """聚合当前进程内 llm_gateway 调用记录的 token 实耗。

    调用约定：``run_case`` 在调用 ``answer_query`` 前先
    ``clear_call_records()``，结束后本函数取到的记录即全部属于该 case
    （评测进程独占 gateway 记录列表；先清后取也天然规避
    MAX_CALL_RECORDS 截断导致的切片错位）。无用量记录（含失败调用）
    时返回 None，不臆造 0。
    """
    from src.llm_gateway import get_call_records

    records = get_call_records()
    usages = [r.token_usage for r in records if r.token_usage is not None]
    if not usages:
        return None, None, None
    prompt = sum(u.prompt_tokens for u in usages)
    completion = sum(u.completion_tokens for u in usages)
    total = sum(u.total_tokens for u in usages)
    return prompt, completion, total


# ── Per-case generation result ──────────────────────────────────────

@dataclass
class GenerationResult:
    """Result of running one evaluation case through the full generation pipeline."""

    case_id: str
    query: str
    query_type: str
    language: str
    should_refuse: bool

    # Generated answer
    answer: str
    # Context provided to the LLM
    context: str

    # Citation metrics
    citation_metrics: CitationMetrics

    # Timing
    total_ms: float
    retrieval_ms: float
    generation_ms: float

    # Token usage (aggregated from llm_gateway call records)
    prompt_tokens: int | None = None
    completion_tokens: int | None = None

    # M1.1 诊断字段（12-hex 归一域）：citation 报告要区分两类缺口——
    # 检索缺口（context 不含真值 chunk）与引用未覆盖（context 含真值但
    # 答案未引用）。outcomes 落盘这两个集合供 M2 分析，context 截断
    # 500 字符仅用于可读性。
    context_chunk_ids: list[str] = field(default_factory=list)
    relevant_chunk_ids: list[str] = field(default_factory=list)

    # Answer-hit 机械指标（containment 族）；拒答例/无要点例为 None
    answer_hit: AnswerHitResult | None = None


# ── Generation Runner ───────────────────────────────────────────────

class GenerationRunner:
    """Run generation evaluation against the Mneme pipeline.

    Unlike the retrieval runner, this calls the full answer generation
    pipeline and evaluates the quality of the generated answer.
    """

    def __init__(
        self,
        dataset_path: Path,
        corpus_dir: Path | None = None,
        collection_name: str = "eval_generation",
    ) -> None:
        self.dataset_path = dataset_path
        self.corpus_dir = corpus_dir
        self.collection_name = collection_name
        self._index_built = False
        self._model = None
        self._collection = None
        self._bm25 = None
        self._all_docs: list[str] = []
        self._all_metadatas: list[dict] = []

    def build_index(self) -> None:
        """Build the Mneme index from the evaluation corpus."""
        from src.rag import prepare_index

        cases = load_dataset(self.dataset_path)
        source_files: set[str] = set()
        for case in cases:
            source_files.update(case.relevant_source_ids)

        file_paths: list[str] = []
        if self.corpus_dir is not None:
            for source_id in sorted(source_files):
                candidate = self.corpus_dir / source_id
                if candidate.exists():
                    file_paths.append(str(candidate))
                else:
                    for f in self.corpus_dir.iterdir():
                        if f.name.lower() == source_id.lower():
                            file_paths.append(str(f))
                            break

        if not file_paths:
            raise FileNotFoundError(
                f"No source files found for dataset {self.dataset_path}. "
                f"Looked in {self.corpus_dir}"
            )

        print(f"Building index from {len(file_paths)} source files...")
        self._model, self._collection, self._bm25, self._all_docs, self._all_metadatas = (
            prepare_index(file_paths, self.collection_name, force_rebuild=True)
        )
        self._index_built = True
        print(f"Index built: {len(self._all_docs)} chunks")

    def run_case(self, case: EvalCase) -> GenerationResult:
        """Run generation for a single evaluation case.

        Calls the production answer_query() pipeline directly, ensuring
        the evaluation measures real-world behavior including query
        rewrite, decomposition, reranking, parent-child/adjacent
        expansion, and citation validation (evaluation plan §2.2 item 5).
        """
        if not self._index_built:
            raise RuntimeError("Call build_index() before run_case()")

        from src.rag import answer_query, REFUSAL_MESSAGE
        from src.citations import referenced_citation_ids

        # token 实耗按 case 切片：先清空 gateway 记录，answer_query 内部
        # （rewrite/decompose/生成）的调用全部归属本 case。
        from src.llm_gateway import clear_call_records
        clear_call_records()

        # Call the full production pipeline
        total_start = time.perf_counter()
        try:
            answer, sources = answer_query(
                query=case.query,
                model=self._model,
                collection=self._collection,
                bm25=self._bm25,
                documents=self._all_docs,
                metadatas=self._all_metadatas,
            )
        except Exception as e:
            answer = f"[Generation error: {e}]"
            sources = ""
        total_ms = (time.perf_counter() - total_start) * 1000
        prompt_tokens, completion_tokens, _total_tokens = _collect_case_tokens()

        # ── 引用指标（契约 v2：context-aware，禁止占位） ──
        # runner 无独立检索网格：生产路径 context 与 sources 同源同截断
        # （_build_context 与 format_sources 使用同一 top_indices[:context_k]），
        # 故以 sources 解析的 chunk 作为 context 证据（文档化于实现报告）。
        # Ground truth 相关 chunk：v2.1 权威 relevant_chunk_ids 优先，
        # v1 回退 snippet 匹配（resolve_relevant_chunk_ids 统一口径）。
        relevant_chunk_ids = resolve_relevant_chunk_ids(
            case, self._all_metadatas, self._all_docs,
        )
        parsed = parse_sources_citation_map(sources)
        chunk_to_source = {
            str(m.get("chunk_id")): (
                m.get("source_name") or m.get("source")
                or m.get("source_id") or ""
            )
            for m in self._all_metadatas if m.get("chunk_id")
        }
        # M1.1：比对双方统一归一到 12-hex 域（真值侧冻结格式与索引侧
        # 64-hex 全长是同一哈希的两种截断，直接字符串比对永不相交）。
        # 只影响评测度量，不改产品侧 ID 形态。
        chunk_to_source_normalized = {
            _normalize_chunk_id(k): v for k, v in chunk_to_source.items()
        }
        context_chunk_ids = sorted({
            _normalize_chunk_id(c) for c in parsed.values()
        })
        context_source_ids = sorted({
            chunk_to_source_normalized[c] for c in context_chunk_ids
            if c in chunk_to_source_normalized
            and chunk_to_source_normalized[c]
        })
        citation_metrics = evaluate_citations_context_aware(
            answer=answer,
            sources=_normalize_source_chunk_ids(sources),
            context_chunk_ids=context_chunk_ids,
            context_source_ids=context_source_ids,
            candidate_chunk_ids=context_chunk_ids,
            chunk_to_source=chunk_to_source_normalized,
            relevant_chunk_ids={
                _normalize_chunk_id(c) for c in relevant_chunk_ids
            },
            answer_points=case.acceptable_answer_points,
            context_text=_normalize_source_chunk_ids(sources),
            should_refuse=case.should_refuse,
        )
        relevant_chunk_ids_normalized = sorted({
            _normalize_chunk_id(c) for c in relevant_chunk_ids
        })

        return GenerationResult(
            case_id=case.id,
            query=case.query,
            query_type=case.query_type.value,
            language=case.language.value,
            should_refuse=case.should_refuse,
            answer=answer,
            context=sources[:500],  # Store truncated sources as context
            citation_metrics=citation_metrics,
            # 答案级机械下界：拒答例（无要点）→ None，聚合时自动排除
            answer_hit=compute_answer_hit(answer, case.acceptable_answer_points),
            context_chunk_ids=context_chunk_ids,
            relevant_chunk_ids=relevant_chunk_ids_normalized,
            total_ms=total_ms,
            retrieval_ms=0.0,  # Not separately timed in production pipeline
            generation_ms=total_ms,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
        )

    def run_all(self) -> tuple[list[GenerationResult], dict[str, Any]]:
        """Run generation for all cases and compute aggregate metrics."""
        cases = load_dataset(self.dataset_path)
        if not self._index_built:
            self.build_index()

        results: list[GenerationResult] = []
        for i, case in enumerate(cases):
            print(f"  [{i+1}/{len(cases)}] {case.id}: {case.query[:50]}...")
            try:
                result = self.run_case(case)
                results.append(result)
            except Exception as e:
                print(f"    ERROR: {e}")
                continue

        # Aggregate metrics
        report = self._aggregate(results)
        return results, report

    def _aggregate(self, results: list[GenerationResult]) -> dict[str, Any]:
        """Compute aggregate generation metrics."""
        if not results:
            return {"case_count": 0}

        # Citation ID validity
        validity_scores = [r.citation_metrics.citation_id_validity for r in results]
        avg_validity = sum(validity_scores) / len(validity_scores)

        # Citation precision/recall
        precisions = [r.citation_metrics.citation_precision for r in results]
        recalls = [r.citation_metrics.citation_recall for r in results]
        avg_precision = sum(precisions) / len(precisions)
        avg_recall = sum(recalls) / len(recalls)

        # Faithfulness
        faithfulness_scores = [r.citation_metrics.faithfulness for r in results]
        avg_faithfulness = sum(faithfulness_scores) / len(faithfulness_scores)

        # Refusal accuracy
        refusal_results = [
            r for r in results if r.citation_metrics.correctly_refused is not None
        ]
        refusal_cases = [r for r in results if r.should_refuse]
        if refusal_cases:
            correct_refusals = sum(
                1 for r in refusal_cases
                if r.citation_metrics.correctly_refused is True
            )
            refusal_precision = correct_refusals / len(refusal_cases)
        else:
            refusal_precision = None

        # Non-refusal cases: check if system incorrectly refused
        answerable_cases = [r for r in results if not r.should_refuse]
        if answerable_cases:
            incorrect_refusals = sum(
                1 for r in answerable_cases
                if r.citation_metrics.correctly_refused is False
            )
            false_refusal_rate = incorrect_refusals / len(answerable_cases)
        else:
            false_refusal_rate = None

        # Answer-hit 机械下界：只对有有效要点的例平均（拒答例/空要点例
        # 的 None 不摊薄命中率），"无可判定"案例单独计数披露。
        hit_rates = [
            r.answer_hit.answer_hit_rate for r in results
            if r.answer_hit is not None
            and r.answer_hit.answer_hit_rate is not None
        ]
        cases_without_effective_points = sum(
            1 for r in results
            if r.answer_hit is None or r.answer_hit.answer_hit_rate is None
        )
        answer_hit_avg = (
            sum(hit_rates) / len(hit_rates) if hit_rates else None
        )

        # Token 实耗合计与均值（None 例不计入均值分母，全 None → None）
        prompt_vals = [r.prompt_tokens for r in results if r.prompt_tokens is not None]
        completion_vals = [
            r.completion_tokens for r in results if r.completion_tokens is not None
        ]
        total_vals = [
            (r.prompt_tokens or 0) + (r.completion_tokens or 0)
            for r in results if r.prompt_tokens is not None
            or r.completion_tokens is not None
        ]
        n_tok = len(total_vals)

        # Timing
        total_times = [r.total_ms for r in results]
        retrieval_times = [r.retrieval_ms for r in results]
        generation_times = [r.generation_ms for r in results]

        return {
            "case_count": len(results),
            "refusal_case_count": len(refusal_cases),
            "answer_hit_rate_avg": round(answer_hit_avg, 4) if answer_hit_avg is not None else None,
            "cases_without_effective_points": cases_without_effective_points,
            "prompt_tokens_sum": sum(prompt_vals),
            "completion_tokens_sum": sum(completion_vals),
            "total_tokens_sum": sum(total_vals),
            "prompt_tokens_avg": round(sum(prompt_vals) / n_tok, 1) if n_tok else None,
            "completion_tokens_avg": round(sum(completion_vals) / n_tok, 1) if n_tok else None,
            "total_tokens_avg": round(sum(total_vals) / n_tok, 1) if n_tok else None,
            "citation_id_validity_avg": round(avg_validity, 4),
            "citation_precision_avg": round(avg_precision, 4),
            "citation_recall_avg": round(avg_recall, 4),
            "faithfulness_avg": round(avg_faithfulness, 4),
            "refusal_precision": round(refusal_precision, 4) if refusal_precision is not None else None,
            "false_refusal_rate": round(false_refusal_rate, 4) if false_refusal_rate is not None else None,
            "total_ms_avg": round(sum(total_times) / len(total_times), 1),
            "retrieval_ms_avg": round(sum(retrieval_times) / len(retrieval_times), 1),
            "generation_ms_avg": round(sum(generation_times) / len(generation_times), 1),
        }


# ── Report output ───────────────────────────────────────────────────

def save_generation_report(report: dict[str, Any], path: Path) -> None:
    """Save generation evaluation report as JSON."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2, default=_json_default)


def save_generation_results(results: list[GenerationResult], path: Path) -> None:
    """Save per-case generation results as JSONL."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        for r in results:
            d = asdict(r)
            f.write(json.dumps(d, ensure_ascii=False, default=_json_default) + "\n")


def _json_default(obj: Any) -> Any:
    """JSON serializer for non-standard types."""
    if isinstance(obj, set):
        return sorted(obj)
    if isinstance(obj, CitationMetrics):
        return asdict(obj)
    raise TypeError(f"Object of type {type(obj)} is not JSON serializable")


def print_generation_report(report: dict[str, Any]) -> None:
    """Print a human-readable summary of the generation evaluation."""
    print("\n" + "=" * 60)
    print("  Mneme Generation Evaluation Report")
    print("=" * 60)

    print(f"\n  Cases: {report.get('case_count', 0)} "
          f"(refusal: {report.get('refusal_case_count', 0)})")

    print("\n  Citation Quality:")
    print(f"    {'ID validity avg':25s} {report.get('citation_id_validity_avg', 0):.4f}")
    print(f"    {'Precision avg':25s} {report.get('citation_precision_avg', 0):.4f}")
    print(f"    {'Recall avg':25s} {report.get('citation_recall_avg', 0):.4f}")

    print("\n  Faithfulness:")
    print(f"    {'Faithfulness avg':25s} {report.get('faithfulness_avg', 0):.4f}")

    refusal = report.get("refusal_precision")
    if refusal is not None:
        print(f"\n  Refusal:")
        print(f"    {'Refusal precision':25s} {refusal:.4f}")

    false_ref = report.get("false_refusal_rate")
    if false_ref is not None:
        print(f"    {'False refusal rate':25s} {false_ref:.4f}")

    print("\n  Timing:")
    print(f"    {'Total avg (ms)':25s} {report.get('total_ms_avg', 0):.1f}")
    print(f"    {'Retrieval avg (ms)':25s} {report.get('retrieval_ms_avg', 0):.1f}")
    print(f"    {'Generation avg (ms)':25s} {report.get('generation_ms_avg', 0):.1f}")

    print("\n" + "=" * 60)


# ── 薄 CLI（答案级评测线 M1，密封产物沿 parentchild run-3 范式） ────

def stride_sample(items: list, limit: int | None) -> list:
    """等距 stride 采样：确定性、保序、覆盖全数据集谱段。

    冒烟（--limit N, N < len）取 0, stride, 2*stride... 而非前 N 个——
    冒烟数字要能外推全量成本与指标，覆盖比前缀更代表总体。
    """
    if limit is None or limit >= len(items):
        return list(items)
    stride = -(-len(items) // limit)  # ceil
    return items[::stride][:limit]


def resolve_generation_dataset(name_or_path: str) -> Path:
    """裸名数据集经注册表解析（单一事实源：evaluation.run），路径原样透传。"""
    from evaluation.run import resolve_dataset_path

    if "/" in name_or_path or "\\" in name_or_path or name_or_path.endswith(".jsonl"):
        return Path(name_or_path)
    return resolve_dataset_path(name_or_path)


def _dump(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=1, sort_keys=True) + "\n"


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _git_commit() -> str:
    """当前 HEAD 短哈希（lineage 溯源）；非 git 环境返回 unknown。"""
    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"], capture_output=True, text=True,
            check=True, timeout=10,
        ).stdout.strip()
    except Exception:
        return "unknown"


def write_sealed_outputs(
    out_dir: Path,
    *,
    results: list[GenerationResult],
    report: dict[str, Any],
    dataset_name: str,
    dataset_path: Path,
    corpus_dir: Path | None,
    sampling: dict[str, Any],
) -> None:
    """写密封产物：outcomes.jsonl + report.json + 自哈希 manifest.json。

    目录拒绝已存在（fail-closed，沿 parentchild_ab.write_outputs 范式）；
    manifest 自哈希覆盖其 body（去除 manifest_sha256 字段本身）。
    """
    out_dir = Path(out_dir)
    if out_dir.exists():
        raise RuntimeError(f"输出目录已存在，拒绝覆盖（fail-closed）: {out_dir}")
    out_dir.mkdir(parents=True)

    outcomes_bytes = ("\n".join(
        json.dumps(asdict(r), ensure_ascii=False, sort_keys=True,
                   default=_json_default) for r in results)
        + ("\n" if results else "")).encode("utf-8")
    (out_dir / "outcomes.jsonl").write_bytes(outcomes_bytes)

    report_bytes = _dump(report).encode("utf-8")
    (out_dir / "report.json").write_bytes(report_bytes)

    manifest_body = {
        "lineage": "answer-level-baseline",
        "metric_version": ANSWER_HIT_METRIC_VERSION,
        # M1.1：citation 比对统一在 12-hex 域（真值冻结格式 == 索引 64-hex
        # 前 12 位截断）；产品侧 ID 形态未改，仅评测侧归一记录于此。
        "chunk_id_domain": "12hex-normalized",
        "dataset_name": dataset_name,
        "dataset_path": str(dataset_path),
        "dataset_sha256": _sha256_bytes(Path(dataset_path).read_bytes()),
        "corpus_dir": str(corpus_dir) if corpus_dir else None,
        "sampling": sampling,
        "case_count": len(results),
        "git_commit": _git_commit(),
        "aggregates": report,
        "outcomes_sha256": _sha256_bytes(outcomes_bytes),
        "report_sha256": _sha256_bytes(report_bytes),
    }
    manifest_body["manifest_sha256"] = _sha256_bytes(
        _dump(manifest_body).encode("utf-8"))
    (out_dir / "manifest.json").write_text(_dump(manifest_body), encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    """答案级评测基线 CLI（真实生成调用，产生 API 成本——手工执行）。

    Usage::

        python -m evaluation.generation_runner --dataset v2.1 \
            --limit 10 --output results/answer-level/m1-smoke/
    """
    parser = argparse.ArgumentParser(
        description="Mneme generation-level answer evaluation (sealed outputs)")
    parser.add_argument(
        "--dataset", default="v2.1",
        help="Dataset name (e.g. 'v2.1') or path to JSONL file (default: v2.1)")
    parser.add_argument(
        "--corpus-dir", default=None,
        help="Directory containing source documents "
             "(bare dataset names fall back to the registered default)")
    parser.add_argument(
        "--limit", type=int, default=None,
        help="Run only N cases via deterministic stride sampling (smoke runs)")
    parser.add_argument(
        "--output", required=True,
        help="Sealed output directory (must not exist)")
    args = parser.parse_args(argv)

    from evaluation.run import resolve_corpus_dir
    from evaluation.schema import load_dataset

    dataset_path = resolve_generation_dataset(args.dataset)
    corpus_dir = (
        Path(args.corpus_dir) if args.corpus_dir
        else resolve_corpus_dir(args.dataset, None)
    )
    cases = load_dataset(dataset_path)
    selected = stride_sample(cases, args.limit)
    print(f"[dataset] {args.dataset} -> {dataset_path} "
          f"({len(cases)} cases, selected {len(selected)})")
    print(f"[corpus] {corpus_dir}")

    runner = GenerationRunner(dataset_path, corpus_dir)
    runner.build_index()

    results: list[GenerationResult] = []
    failed = 0
    for i, case in enumerate(selected):
        print(f"  [{i+1}/{len(selected)}] {case.id}: {case.query[:50]}...")
        try:
            results.append(runner.run_case(case))
        except Exception as e:
            failed += 1
            print(f"    ERROR: {e}")

    report = runner._aggregate(results)
    report["cases_failed"] = failed
    write_sealed_outputs(
        args.output,
        results=results,
        report=report,
        dataset_name=args.dataset,
        dataset_path=dataset_path,
        corpus_dir=corpus_dir,
        sampling={
            "strategy": "stride" if args.limit and args.limit < len(cases) else "all",
            "limit": args.limit,
            "dataset_size": len(cases),
        },
    )
    print(f"[sealed] {args.output}")
    print_generation_report(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
