"""generation_runner 薄 CLI 测试：stride 采样、数据集解析、密封产物自哈希。

口径（章程 M1 + 密封范式沿 parentchild_ab run-3）：
- ``--limit`` 等距 stride 采样（确定性、保序、覆盖全谱），manifest 记录；
- 密封目录已存在 → 拒绝（fail-closed）；
- manifest 自哈希：manifest_sha256 = 对去除该字段后的 body 规范化序列化
  求 SHA256，outcomes/report 的 sha 与落盘字节一致。
"""

import hashlib
import json
from pathlib import Path

import pytest

from evaluation.citation_metrics import CitationMetrics
from evaluation.answer_metrics import AnswerHitResult
from evaluation.generation_runner import (
    GenerationResult,
    resolve_generation_dataset,
    stride_sample,
    write_sealed_outputs,
)
from evaluation.run import EVAL_ROOT


class TestStrideSample:
    def test_limit_none_or_full_returns_all_in_order(self):
        items = list("abcde")
        assert stride_sample(items, None) == items
        assert stride_sample(items, 5) == items

    def test_limit_below_size_yields_deterministic_stride(self):
        items = list(range(150))
        sampled = stride_sample(items, 10)
        assert sampled == [items[i] for i in range(0, 150, 15)]
        assert len(sampled) == 10

    def test_limit_one_returns_first_item(self):
        assert stride_sample(list("xyz"), 1) == ["x"]

    def test_limit_exceeding_size_is_clamped_to_all(self):
        items = list("ab")
        assert stride_sample(items, 10) == items


class TestResolveGenerationDataset:
    def test_bare_name_resolves_via_registry(self):
        path = resolve_generation_dataset("v2.1")
        assert path == EVAL_ROOT / "datasets" / "v2.1.jsonl"
        assert path.exists()

    def test_explicit_path_passes_through(self):
        assert resolve_generation_dataset("some/where/ds.jsonl") == Path("some/where/ds.jsonl")


def _make_result(case_id: str, hit_rate: float | None) -> GenerationResult:
    return GenerationResult(
        case_id=case_id, query="q", query_type="single_fact", language="zh",
        should_refuse=False, answer="答案文本", context="ctx",
        citation_metrics=CitationMetrics(
            citation_id_validity=1.0, invalid_citation_count=0,
            total_citation_count=1, citation_precision=1.0,
            citation_recall=0.5, faithfulness=1.0, correctly_refused=True,
        ),
        total_ms=10.0, retrieval_ms=0.0, generation_ms=10.0,
        prompt_tokens=100, completion_tokens=20,
        answer_hit=AnswerHitResult(
            point_results=(), hit_count=int(hit_rate or 0),
            effective_point_count=0 if hit_rate is None else 2,
            answer_hit_rate=hit_rate,
        ),
    )


_REPORT = {
    "case_count": 2,
    "answer_hit_rate_avg": 0.5,
    "total_tokens_sum": 240,
}


class TestWriteSealedOutputs:
    def _write(self, out_dir: Path):
        results = [
            _make_result("case-a", 1.0),
            _make_result("case-b", None),
        ]
        write_sealed_outputs(
            out_dir,
            results=results,
            report=_REPORT,
            dataset_name="v2.1",
            dataset_path=Path("evaluation/datasets/v2.1.jsonl"),
            corpus_dir=Path("data/v2-corpus/documents/processed"),
            sampling={"strategy": "stride", "limit": 2, "dataset_size": 150},
        )
        return results

    def test_writes_outcomes_report_manifest(self, tmp_path):
        out_dir = tmp_path / "run-x"
        self._write(out_dir)
        assert (out_dir / "outcomes.jsonl").exists()
        assert (out_dir / "report.json").exists()
        assert (out_dir / "manifest.json").exists()

    def test_manifest_hashes_match_written_bytes(self, tmp_path):
        out_dir = tmp_path / "run-x"
        self._write(out_dir)
        manifest = json.loads((out_dir / "manifest.json").read_text(encoding="utf-8"))

        outcomes_bytes = (out_dir / "outcomes.jsonl").read_bytes()
        report_bytes = (out_dir / "report.json").read_bytes()
        assert manifest["outcomes_sha256"] == hashlib.sha256(outcomes_bytes).hexdigest()
        assert manifest["report_sha256"] == hashlib.sha256(report_bytes).hexdigest()

        # 自哈希：manifest_sha256 覆盖去除该字段后的规范化 body
        body = dict(manifest)
        recorded = body.pop("manifest_sha256")
        recomputed = hashlib.sha256(
            (json.dumps(body, ensure_ascii=False, indent=1, sort_keys=True) + "\n").encode("utf-8")
        ).hexdigest()
        assert recorded == recomputed
        assert manifest["metric_version"] == "al1-containment-v1"
        assert manifest["lineage"] == "answer-level-baseline"
        assert manifest["chunk_id_domain"] == "12hex-normalized"

    def test_outcomes_rows_carry_answer_hit_audit_fields(self, tmp_path):
        out_dir = tmp_path / "run-x"
        self._write(out_dir)
        rows = [json.loads(l) for l in
                (out_dir / "outcomes.jsonl").read_text(encoding="utf-8").splitlines()]
        by_id = {r["case_id"]: r for r in rows}
        assert by_id["case-a"]["answer_hit"]["answer_hit_rate"] == 1.0
        assert by_id["case-b"]["answer_hit"]["answer_hit_rate"] is None

    def test_refuses_to_overwrite_existing_dir(self, tmp_path):
        out_dir = tmp_path / "run-x"
        self._write(out_dir)
        with pytest.raises(Exception, match="已存在"):
            self._write(out_dir)
