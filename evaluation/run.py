"""CLI entry point for Mneme evaluation.

Usage::

    # Run retrieval evaluation with dataset v1
    python -m evaluation.run --dataset v1 --output results/baseline.json

    # Run with custom corpus directory
    python -m evaluation.run --dataset v1 --corpus-dir ./test_texts --output results/baseline.json

    # Validate dataset integrity only (no retrieval)
    python -m evaluation.run --dataset v1 --validate-only

    # Show per-case details
    python -m evaluation.run --dataset v1 --output results/baseline.json --verbose
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Package root directory (evaluation/)
EVAL_ROOT = Path(__file__).parent
DATASETS_DIR = EVAL_ROOT / "datasets"


def resolve_dataset_path(name: str) -> Path:
    """Resolve a dataset name to its JSONL file path.

    Accepts:
    - A bare name like "v1" → evaluation/datasets/v1.jsonl
    - A relative/absolute path ending in .jsonl
    """
    if name.endswith(".jsonl"):
        p = Path(name)
        if p.is_absolute():
            return p
        return DATASETS_DIR / p
    return DATASETS_DIR / f"{name}.jsonl"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Mneme RAG evaluation runner",
    )
    parser.add_argument(
        "--dataset",
        default="v1",
        help="Dataset name (e.g. 'v1') or path to JSONL file (default: v1)",
    )
    parser.add_argument(
        "--corpus-dir",
        type=Path,
        default=None,
        help="Directory containing source documents for the evaluation corpus",
    )
    parser.add_argument(
        "--output",
        "-o",
        type=Path,
        default=None,
        help="Output path for the aggregate report JSON (default: results/<dataset>.json)",
    )
    parser.add_argument(
        "--per-case-output",
        type=Path,
        default=None,
        help="Output path for per-case results JSONL",
    )
    parser.add_argument(
        "--validate-only",
        action="store_true",
        help="Only validate the dataset, do not run retrieval",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Print per-case details",
    )
    parser.add_argument(
        "--collection-name",
        default="eval_retrieval",
        help="ChromaDB collection name for the evaluation index",
    )

    args = parser.parse_args(argv)
    dataset_path = resolve_dataset_path(args.dataset)

    # ── Validate dataset ────────────────────────────────────────────
    if not dataset_path.exists():
        print(f"Error: Dataset not found: {dataset_path}", file=sys.stderr)
        return 1

    from evaluation.schema import load_dataset, validate_dataset

    print(f"Loading dataset: {dataset_path}")
    cases = load_dataset(dataset_path)
    print(f"  Loaded {len(cases)} cases")

    warnings = validate_dataset(cases)
    if warnings:
        print(f"\n  ⚠ Dataset validation warnings ({len(warnings)}):")
        for w in warnings:
            print(f"    - {w}")
    else:
        print("  ✓ Dataset validation passed")

    if args.validate_only:
        return 0 if not warnings else 2

    # ── Run retrieval evaluation ────────────────────────────────────
    from evaluation.runner import (
        RetrievalRunner,
        save_report,
        save_per_case_results,
        print_report,
    )

    output_path = args.output
    if output_path is None:
        results_dir = EVAL_ROOT.parent / "results"
        output_path = results_dir / f"{args.dataset}.json"

    runner = RetrievalRunner(
        dataset_path=dataset_path,
        corpus_dir=args.corpus_dir,
        collection_name=args.collection_name,
    )

    results, report = runner.run_all()

    # Print report
    print_report(report)

    # Save outputs
    save_report(report, output_path)
    print(f"\n  Report saved to: {output_path}")

    if args.per_case_output:
        save_per_case_results(results, args.per_case_output)
        print(f"  Per-case results saved to: {args.per_case_output}")

    # Verbose: print per-case details
    if args.verbose:
        print("\n  Per-case details:")
        for r in results:
            metrics = r.per_case_metrics()
            print(
                f"    {r.case_id:20s}  "
                f"recall@5={metrics.get('recall@5', 0):.3f}  "
                f"recall@10={metrics.get('recall@10', 0):.3f}  "
                f"mrr={metrics.get('mrr', 0):.3f}  "
                f"({r.retrieval_ms:.1f}ms)"
            )

    return 0


if __name__ == "__main__":
    sys.exit(main())
