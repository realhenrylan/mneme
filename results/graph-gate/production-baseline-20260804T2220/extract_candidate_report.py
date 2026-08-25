"""生产基线候选报告数据提取（dev + holdout 只读分析）。

从评测产物的 summary.json / generation-summary.json 提取检索、
source、生成与 citation v2（契约 v2 唯一聚合块）指标，输出
candidate-report-data.json 供正式候选报告引用。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
OUT = Path(__file__).resolve().parent

RETRIEVAL_KEYS = (
    "recall@5", "recall@10", "recall@20", "ndcg@5", "ndcg@10", "ndcg@20",
    "mrr", "context_recall", "context_precision", "n_chunk_valid",
    "excluded_no_chunk_truth", "source_recall@5", "source_recall@10",
    "context_source_recall", "context_source_coverage", "n_source_valid",
    "n_source_only", "retrieval_ms_p50", "retrieval_ms_p95",
)
GEN_KEYS = (
    "answer_point_coverage", "citation_id_validity",
    "context_supported_citation_validity", "fabricated_citation_avg",
    "retrieved_not_in_context_avg", "false_answer_rate",
    "false_refusal_rate", "total_ms_p50", "total_ms_p95", "error_rate",
)


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> None:
    data = {"runs": {}}
    for split in ("dev", "holdout"):
        base = OUT / f"{split}-full"
        run = {"dir": str(base.relative_to(ROOT))}
        sm = _load(base / "summary.json")
        gen = _load(base / "generation-summary.json")
        arm_name = "standard"
        run["summary_overall"] = {
            k: sm[arm_name]["overall"][k] for k in RETRIEVAL_KEYS
            if k in sm[arm_name]["overall"]
        }
        gen_ov = gen[arm_name]["overall"]
        run["generation_overall"] = {k: gen_ov[k] for k in GEN_KEYS if k in gen_ov}
        run["citation_v2"] = gen_ov.get("citation_v2")
        data["runs"][split] = run
    out_path = OUT / "candidate-report-data.json"
    out_path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"written: {out_path.relative_to(ROOT)}")
    for split, run in data["runs"].items():
        cv = run["citation_v2"]
        print(f"  {split}: coverage={run['generation_overall'].get('answer_point_coverage')} "
              f"micro={cv['metrics']['context_supported_citation_validity_micro']['value']} "
              f"answer_rate={cv['metrics']['context_supported_answer_rate']['value']:.4f}")


if __name__ == "__main__":
    main()
