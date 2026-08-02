"""Retrieval evaluation runner for Mneme RAG.

Calls the actual Mneme pipeline (parser → embedding → Chroma → BM25 → RRF)
for each evaluation case and computes retrieval quality metrics.

Usage::

    python -m evaluation.run --dataset v1 --output results/baseline.json

The runner is designed to be reproducible: same dataset + same code +
same model → same scores.
"""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from evaluation.schema import EvalCase, load_dataset, QueryType
from evaluation.metrics import (
    compute_retrieval_metrics,
    compute_stratified_metrics,
    source_recall_at_k,
)


# ── Per-case result ─────────────────────────────────────────────────

@dataclass
class RetrievalResult:
    """Result of running one evaluation case through the retrieval pipeline."""

    case_id: str
    query: str
    query_type: str
    language: str
    should_refuse: bool

    # Retrieved chunk IDs in rank order
    retrieved_chunk_ids: list[str]
    # Retrieved source IDs in rank order (deduplicated, preserving first occurrence)
    retrieved_source_ids: list[str]
    # RRF scores for each retrieved chunk
    scores: list[float]

    # Ground truth
    relevant_chunk_ids: set[str]
    relevant_source_ids: set[str]

    # Timing
    retrieval_ms: float

    def per_case_metrics(self, ks: tuple[int, ...] = (5, 10, 20)) -> dict[str, float]:
        """Compute per-case retrieval metrics."""
        metrics: dict[str, float] = {}
        for k in ks:
            from evaluation.metrics import recall_at_k, ndcg_at_k
            metrics[f"recall@{k}"] = recall_at_k(
                self.retrieved_chunk_ids, self.relevant_chunk_ids, k,
            )
            metrics[f"ndcg@{k}"] = ndcg_at_k(
                self.retrieved_chunk_ids, self.relevant_chunk_ids, k,
            )
            metrics[f"source_recall@{k}"] = source_recall_at_k(
                self.retrieved_source_ids, self.relevant_source_ids, k,
            )
        # MRR
        for rank, cid in enumerate(self.retrieved_chunk_ids, start=1):
            if cid in self.relevant_chunk_ids:
                metrics["mrr"] = 1.0 / rank
                break
        else:
            metrics["mrr"] = 0.0
        return metrics


# ── Runner ──────────────────────────────────────────────────────────

class RetrievalRunner:
    """Run retrieval evaluation against the actual Mneme pipeline.

    The runner builds the index once, then queries it for each
    evaluation case.  This matches real-world usage where the index
    is built from a document corpus and then queried repeatedly.
    """

    def __init__(
        self,
        dataset_path: Path,
        corpus_dir: Path | None = None,
        collection_name: str = "eval_retrieval",
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
        """Build the Mneme index from the evaluation corpus.

        Uses the same ``prepare_index()`` function as the production
        pipeline, ensuring the evaluation measures real-world behavior.
        """
        from src.rag import prepare_index

        # Collect all unique source files from the dataset
        cases = load_dataset(self.dataset_path)
        source_files: set[str] = set()
        for case in cases:
            source_files.update(case.relevant_source_ids)

        # Resolve source file paths
        file_paths: list[str] = []
        if self.corpus_dir is not None:
            for source_id in sorted(source_files):
                # Try exact match in corpus_dir
                candidate = self.corpus_dir / source_id
                if candidate.exists():
                    file_paths.append(str(candidate))
                else:
                    # Try case-insensitive match
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

    def run_case(self, case: EvalCase) -> RetrievalResult:
        """Run retrieval for a single evaluation case."""
        if not self._index_built:
            raise RuntimeError("Call build_index() before run_case()")

        from src.rag import retrieve_hybrid_with_sources

        start = time.perf_counter()
        indices, docs, scores = retrieve_hybrid_with_sources(
            query=case.query,
            model=self._model,
            collection=self._collection,
            bm25=self._bm25,
            documents=self._all_docs,
            metadatas=self._all_metadatas,
        )
        elapsed_ms = (time.perf_counter() - start) * 1000

        # Extract chunk IDs and source IDs from retrieved results
        retrieved_chunk_ids: list[str] = []
        retrieved_source_ids: list[str] = []
        seen_sources: set[str] = set()

        for idx in indices:
            meta = self._all_metadatas[idx] if idx < len(self._all_metadatas) else {}
            chunk_id = meta.get("chunk_id", f"chunk_{idx}")
            retrieved_chunk_ids.append(chunk_id)

            source_id = meta.get("source_id") or meta.get("source_name") or meta.get("source", "")
            if source_id and source_id not in seen_sources:
                retrieved_source_ids.append(source_id)
                seen_sources.add(source_id)

        # Build ground truth chunk IDs from relevant_chunks annotations
        relevant_chunk_ids: set[str] = set()
        for rc in case.relevant_chunks:
            # Match by source_id + snippet overlap
            relevant_chunk_ids.add(rc.source_id)  # At minimum, the source is relevant

        # Also try to match specific chunks by source_id prefix
        for rc in case.relevant_chunks:
            source_id = rc.source_id
            for idx, meta in enumerate(self._all_metadatas):
                meta_source = meta.get("source_id") or meta.get("source_name") or meta.get("source", "")
                if meta_source == source_id:
                    chunk_id = meta.get("chunk_id", f"chunk_{idx}")
                    relevant_chunk_ids.add(chunk_id)

        return RetrievalResult(
            case_id=case.id,
            query=case.query,
            query_type=case.query_type.value,
            language=case.language.value,
            should_refuse=case.should_refuse,
            retrieved_chunk_ids=retrieved_chunk_ids,
            retrieved_source_ids=retrieved_source_ids,
            scores=scores,
            relevant_chunk_ids=relevant_chunk_ids,
            relevant_source_ids=set(case.relevant_source_ids),
            retrieval_ms=elapsed_ms,
        )

    def run_all(self) -> tuple[list[RetrievalResult], dict[str, Any]]:
        """Run retrieval for all cases and compute aggregate metrics.

        Returns:
            (per_case_results, aggregate_report) tuple.
        """
        cases = load_dataset(self.dataset_path)
        if not self._index_built:
            self.build_index()

        results: list[RetrievalResult] = []
        for i, case in enumerate(cases):
            print(f"  [{i+1}/{len(cases)}] {case.id}: {case.query[:50]}...")
            result = self.run_case(case)
            results.append(result)

        # Compute aggregate metrics
        all_retrieved = [r.retrieved_chunk_ids for r in results]
        all_relevant = [r.relevant_chunk_ids for r in results]
        all_languages = [r.language for r in results]
        all_query_types = [r.query_type for r in results]

        overall = compute_retrieval_metrics(all_retrieved, all_relevant)
        by_language = compute_stratified_metrics(
            all_retrieved, all_relevant, all_languages,
        )
        by_query_type = compute_stratified_metrics(
            all_retrieved, all_relevant, all_query_types,
        )

        # Source recall
        source_recalls = []
        for r in results:
            sr = source_recall_at_k(
                r.retrieved_source_ids, r.relevant_source_ids, k=10,
            )
            source_recalls.append(sr)
        overall["source_recall@10"] = (
            sum(source_recalls) / len(source_recalls) if source_recalls else 0.0
        )

        # Refusal accuracy (for should_refuse cases)
        refusal_cases = [r for r in results if r.should_refuse]
        if refusal_cases:
            # A refusal case is "correctly refused" if no relevant chunks
            # appear in top results (max score is very low)
            from src.rag import DEFAULT_REFUSAL_THRESHOLD
            correctly_refused = sum(
                1 for r in refusal_cases
                if not r.scores or max(r.scores) < DEFAULT_REFUSAL_THRESHOLD
            )
            overall["refusal_precision"] = correctly_refused / len(refusal_cases)
        else:
            overall["refusal_precision"] = None

        # Timing
        retrieval_times = [r.retrieval_ms for r in results]
        overall["retrieval_ms_avg"] = (
            sum(retrieval_times) / len(retrieval_times) if retrieval_times else 0.0
        )
        overall["retrieval_ms_p50"] = (
            sorted(retrieval_times)[len(retrieval_times) // 2]
            if retrieval_times else 0.0
        )

        report = {
            "overall": overall,
            "by_language": by_language,
            "by_query_type": by_query_type,
            "case_count": len(results),
            "refusal_case_count": len(refusal_cases),
        }

        return results, report


# ── Report output ───────────────────────────────────────────────────

def save_report(report: dict[str, Any], path: Path) -> None:
    """Save aggregate report as JSON."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2, default=_json_default)


def save_per_case_results(results: list[RetrievalResult], path: Path) -> None:
    """Save per-case results as JSONL."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        for r in results:
            d = asdict(r)
            d["relevant_chunk_ids"] = sorted(d["relevant_chunk_ids"])
            d["relevant_source_ids"] = sorted(d["relevant_source_ids"])
            f.write(json.dumps(d, ensure_ascii=False, default=_json_default) + "\n")


def _json_default(obj: Any) -> Any:
    """JSON serializer for non-standard types."""
    if isinstance(obj, set):
        return sorted(obj)
    raise TypeError(f"Object of type {type(obj)} is not JSON serializable")


def print_report(report: dict[str, Any]) -> None:
    """Print a human-readable summary of the evaluation report."""
    print("\n" + "=" * 60)
    print("  Mneme Retrieval Evaluation Report")
    print("=" * 60)

    overall = report.get("overall", {})
    print(f"\n  Cases: {report.get('case_count', 0)} "
          f"(refusal: {report.get('refusal_case_count', 0)})")

    print("\n  Overall Metrics:")
    for key in ["recall@5", "recall@10", "recall@20", "mrr", "ndcg@5", "ndcg@10",
                "source_recall@10", "retrieval_ms_avg", "retrieval_ms_p50"]:
        val = overall.get(key)
        if val is not None:
            if isinstance(val, float):
                print(f"    {key:25s} {val:.4f}")
            else:
                print(f"    {key:25s} {val}")

    refusal = overall.get("refusal_precision")
    if refusal is not None:
        print(f"    {'refusal_precision':25s} {refusal:.4f}")

    # By language
    by_lang = report.get("by_language", {})
    if by_lang:
        print("\n  By Language:")
        for lang, metrics in sorted(by_lang.items()):
            r5 = metrics.get("recall@5", 0)
            r10 = metrics.get("recall@10", 0)
            mrr = metrics.get("mrr", 0)
            print(f"    {lang:8s}  recall@5={r5:.3f}  recall@10={r10:.3f}  mrr={mrr:.3f}")

    # By query type
    by_qt = report.get("by_query_type", {})
    if by_qt:
        print("\n  By Query Type:")
        for qt, metrics in sorted(by_qt.items()):
            r5 = metrics.get("recall@5", 0)
            r10 = metrics.get("recall@10", 0)
            mrr = metrics.get("mrr", 0)
            print(f"    {qt:20s}  recall@5={r5:.3f}  recall@10={r10:.3f}  mrr={mrr:.3f}")

    print("\n" + "=" * 60)
