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

import json
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from evaluation.schema import EvalCase, load_dataset
from evaluation.citation_metrics import (
    CitationMetrics,
    evaluate_citations,
)


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

    # Token usage (if available)
    prompt_tokens: int | None = None
    completion_tokens: int | None = None


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
        """Run generation for a single evaluation case."""
        if not self._index_built:
            raise RuntimeError("Call build_index() before run_case()")

        from src.rag import (
            retrieve_hybrid_with_sources,
            _build_context,
            dynamic_top_k,
            retrieval_refused,
        )
        from src.citations import make_citation_records
        from src.domain import RetrievalCandidate, compute_context_k

        # Step 1: Retrieval
        retrieval_start = time.perf_counter()
        indices, docs, scores = retrieve_hybrid_with_sources(
            query=case.query,
            model=self._model,
            collection=self._collection,
            bm25=self._bm25,
            documents=self._all_docs,
            metadatas=self._all_metadatas,
        )
        retrieval_ms = (time.perf_counter() - retrieval_start) * 1000

        # Step 2: Check refusal
        refused = retrieval_refused(scores)

        # Step 3: Build context
        top_k = dynamic_top_k(scores)
        top_indices = indices[:top_k]
        context_k = compute_context_k(
            [RetrievalCandidate(index=i, chunk_id="", source_id="", source_name="")
             for i in top_indices],
        )
        context = _build_context(top_indices, self._all_docs, self._all_metadatas, context_k=context_k)

        # Step 4: Generate answer
        generation_start = time.perf_counter()
        if refused:
            answer = "未找到足够可靠的文档依据，暂时无法回答该问题。"
            generation_ms = 0.0
        else:
            answer = self._generate_answer(case.query, context)
            generation_ms = (time.perf_counter() - generation_start) * 1000

        total_ms = retrieval_ms + generation_ms

        # Step 5: Compute citation metrics
        # Build valid citation IDs from the context
        selected_indices = top_indices[:5]
        records = make_citation_records(
            selected_indices, self._all_docs, self._all_metadatas,
        )
        valid_ids = {r.citation_id for r in records}

        # Build relevant chunk IDs from ground truth
        relevant_chunk_ids: set[str] = set()
        for rc in case.relevant_chunks:
            source_id = rc.source_id
            for idx, meta in enumerate(self._all_metadatas):
                meta_source = (
                    meta.get("source_id")
                    or meta.get("source_name")
                    or meta.get("source", "")
                )
                if meta_source == source_id:
                    chunk_id = meta.get("chunk_id", f"chunk_{idx}")
                    relevant_chunk_ids.add(chunk_id)

        all_retrieved_ids: set[str] = set()
        for idx in indices[:top_k]:
            meta = self._all_metadatas[idx] if idx < len(self._all_metadatas) else {}
            chunk_id = meta.get("chunk_id", f"chunk_{idx}")
            all_retrieved_ids.add(chunk_id)

        citation_metrics = evaluate_citations(
            answer=answer,
            valid_ids=valid_ids,
            relevant_chunk_ids=relevant_chunk_ids,
            all_retrieved_ids=all_retrieved_ids,
            answer_points=case.acceptable_answer_points,
            context=context,
            should_refuse=case.should_refuse,
        )

        return GenerationResult(
            case_id=case.id,
            query=case.query,
            query_type=case.query_type.value,
            language=case.language.value,
            should_refuse=case.should_refuse,
            answer=answer,
            context=context[:500],  # Truncate for storage
            citation_metrics=citation_metrics,
            total_ms=total_ms,
            retrieval_ms=retrieval_ms,
            generation_ms=generation_ms,
        )

    def _generate_answer(self, query: str, context: str) -> str:
        """Generate an answer using the LLM.

        This calls the same LLM generation function as the production
        pipeline.  Override this method for testing with mock LLMs.
        """
        try:
            from src.rag import answer_query
            # answer_query returns the answer string
            result = answer_query(
                query=query,
                context=context,
            )
            return result if isinstance(result, str) else str(result)
        except Exception as e:
            return f"[Generation error: {e}]"

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

        # Timing
        total_times = [r.total_ms for r in results]
        retrieval_times = [r.retrieval_ms for r in results]
        generation_times = [r.generation_ms for r in results]

        return {
            "case_count": len(results),
            "refusal_case_count": len(refusal_cases),
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
