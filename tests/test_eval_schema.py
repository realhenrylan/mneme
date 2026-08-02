"""Tests for evaluation.schema module."""

import json
import tempfile
from pathlib import Path

import pytest

from evaluation.schema import (
    EvalCase,
    Language,
    QueryType,
    RelevantChunk,
    SCHEMA_VERSION,
    load_dataset,
    save_dataset,
    split_dataset,
    validate_dataset,
)


# ── EvalCase serialization ──────────────────────────────────────────

class TestEvalCaseSerialization:
    """Round-trip serialization tests for EvalCase."""

    def test_to_dict_round_trip(self):
        case = EvalCase(
            id="test-001",
            query="What is RAG?",
            query_type=QueryType.SINGLE_FACT,
            language=Language.EN,
            relevant_source_ids=["doc1.pdf"],
            relevant_chunks=[
                RelevantChunk(
                    source_id="doc1.pdf",
                    chunk_text_snippet="RAG combines retrieval and generation",
                    page=3,
                    section="Introduction",
                )
            ],
            acceptable_answer_points=["RAG combines retrieval and generation"],
            should_refuse=False,
            metadata={"difficulty": "easy"},
        )
        d = case.to_dict()
        assert d["id"] == "test-001"
        assert d["query_type"] == "single_fact"
        assert d["language"] == "en"
        assert d["schema_version"] == SCHEMA_VERSION
        assert len(d["relevant_chunks"]) == 1
        assert d["relevant_chunks"][0]["source_id"] == "doc1.pdf"

        # Round-trip
        restored = EvalCase.from_dict(d)
        assert restored.id == case.id
        assert restored.query_type == case.query_type
        assert restored.language == case.language
        assert len(restored.relevant_chunks) == 1
        assert restored.relevant_chunks[0].page == 3

    def test_from_dict_ignores_schema_version(self):
        d = {
            "schema_version": 99,
            "id": "test-002",
            "query": "测试",
            "query_type": "single_fact",
            "language": "zh",
            "relevant_source_ids": [],
            "relevant_chunks": [],
            "acceptable_answer_points": ["答案"],
            "should_refuse": False,
        }
        case = EvalCase.from_dict(d)
        assert case.id == "test-002"

    def test_minimal_case(self):
        case = EvalCase(
            id="min-001",
            query="Hello",
            query_type=QueryType.SINGLE_FACT,
            language=Language.EN,
        )
        d = case.to_dict()
        assert d["relevant_source_ids"] == []
        assert d["should_refuse"] is False
        assert d["metadata"] == {}


# ── Dataset I/O ─────────────────────────────────────────────────────

class TestDatasetIO:
    """JSONL file I/O tests."""

    def test_save_and_load(self, tmp_path):
        cases = [
            EvalCase(
                id="io-001",
                query="Query 1",
                query_type=QueryType.SINGLE_FACT,
                language=Language.EN,
                relevant_source_ids=["a.pdf"],
                acceptable_answer_points=["Answer 1"],
            ),
            EvalCase(
                id="io-002",
                query="查询2",
                query_type=QueryType.SINGLE_FACT,
                language=Language.ZH,
                relevant_source_ids=["b.docx"],
                acceptable_answer_points=["答案2"],
            ),
        ]
        path = tmp_path / "test.jsonl"
        save_dataset(cases, path)

        # Verify JSONL format (one JSON per line)
        with open(path, encoding="utf-8") as f:
            lines = f.readlines()
        assert len(lines) == 2
        for line in lines:
            json.loads(line.strip())  # should not raise

        # Load and verify
        loaded = load_dataset(path)
        assert len(loaded) == 2
        assert loaded[0].id == "io-001"
        assert loaded[1].query == "查询2"

    def test_load_skips_blank_lines(self, tmp_path):
        path = tmp_path / "blanks.jsonl"
        with open(path, "w", encoding="utf-8") as f:
            f.write('\n')
            f.write(json.dumps({
                "id": "x", "query": "q", "query_type": "single_fact",
                "language": "en", "acceptable_answer_points": ["a"],
            }) + '\n')
            f.write('  \n')
        cases = load_dataset(path)
        assert len(cases) == 1

    def test_load_invalid_json_raises(self, tmp_path):
        path = tmp_path / "bad.jsonl"
        with open(path, "w", encoding="utf-8") as f:
            f.write("not json\n")
        with pytest.raises(ValueError, match="line 1"):
            load_dataset(path)


# ── Dataset split ───────────────────────────────────────────────────

class TestDatasetSplit:
    """Stratified train/holdout split tests."""

    def _make_cases(self, n: int, qtype: QueryType) -> list[EvalCase]:
        return [
            EvalCase(
                id=f"{qtype.value}-{i:03d}",
                query=f"Query {i}",
                query_type=qtype,
                language=Language.EN,
                relevant_source_ids=["doc.pdf"],
                acceptable_answer_points=[f"Answer {i}"],
            )
            for i in range(n)
        ]

    def test_split_preserves_all_cases(self):
        cases = self._make_cases(20, QueryType.SINGLE_FACT) + self._make_cases(15, QueryType.MIXED_INTENT)
        train, holdout = split_dataset(cases, holdout_ratio=0.12, seed=42)
        assert len(train) + len(holdout) == len(cases)

    def test_split_is_deterministic(self):
        cases = self._make_cases(30, QueryType.SINGLE_FACT)
        train1, holdout1 = split_dataset(cases, seed=42)
        train2, holdout2 = split_dataset(cases, seed=42)
        assert [c.id for c in train1] == [c.id for c in train2]
        assert [c.id for c in holdout1] == [c.id for c in holdout2]

    def test_single_case_group_goes_to_train(self):
        cases = self._make_cases(1, QueryType.MIXED_INTENT)
        train, holdout = split_dataset(cases, holdout_ratio=0.12)
        assert len(train) == 1
        assert len(holdout) == 0

    def test_stratified_by_query_type(self):
        cases = (
            self._make_cases(10, QueryType.SINGLE_FACT)
            + self._make_cases(10, QueryType.MIXED_INTENT)
            + self._make_cases(10, QueryType.NO_ANSWER)
        )
        train, holdout = split_dataset(cases, holdout_ratio=0.2, seed=42)
        # Each type should have some holdout cases
        holdout_types = {c.query_type for c in holdout}
        assert QueryType.SINGLE_FACT in holdout_types
        assert QueryType.MIXED_INTENT in holdout_types
        assert QueryType.NO_ANSWER in holdout_types


# ── Dataset validation ──────────────────────────────────────────────

class TestDatasetValidation:
    """Integrity check tests."""

    def test_valid_dataset_no_warnings(self):
        cases = [
            EvalCase(
                id="v-001",
                query="Q",
                query_type=QueryType.SINGLE_FACT,
                language=Language.EN,
                relevant_source_ids=["doc.pdf"],
                acceptable_answer_points=["A"],
            ),
        ]
        warnings = validate_dataset(cases)
        # May have missing type coverage warnings, but no per-case issues
        per_case = [w for w in warnings if "v-001" in w]
        assert len(per_case) == 0

    def test_duplicate_id_warning(self):
        cases = [
            EvalCase(id="dup", query="Q1", query_type=QueryType.SINGLE_FACT,
                     language=Language.EN, relevant_source_ids=["a"],
                     acceptable_answer_points=["A"]),
            EvalCase(id="dup", query="Q2", query_type=QueryType.SINGLE_FACT,
                     language=Language.EN, relevant_source_ids=["b"],
                     acceptable_answer_points=["B"]),
        ]
        warnings = validate_dataset(cases)
        assert any("Duplicate" in w for w in warnings)

    def test_refuse_with_sources_warning(self):
        cases = [
            EvalCase(
                id="bad-refuse",
                query="Q",
                query_type=QueryType.NO_ANSWER,
                language=Language.EN,
                relevant_source_ids=["doc.pdf"],
                acceptable_answer_points=[],
                should_refuse=True,
            ),
        ]
        warnings = validate_dataset(cases)
        assert any("should_refuse=True but has relevant_source_ids" in w for w in warnings)

    def test_no_answer_points_warning(self):
        cases = [
            EvalCase(
                id="no-points",
                query="Q",
                query_type=QueryType.SINGLE_FACT,
                language=Language.EN,
                relevant_source_ids=["doc.pdf"],
                acceptable_answer_points=[],
                should_refuse=False,
            ),
        ]
        warnings = validate_dataset(cases)
        assert any("no acceptable_answer_points" in w for w in warnings)

    def test_missing_type_coverage_warning(self):
        cases = [
            EvalCase(
                id="only-one",
                query="Q",
                query_type=QueryType.SINGLE_FACT,
                language=Language.EN,
                relevant_source_ids=["doc.pdf"],
                acceptable_answer_points=["A"],
            ),
        ]
        warnings = validate_dataset(cases)
        missing_types = [w for w in warnings if "Missing query type" in w]
        assert len(missing_types) > 0  # Not all 8 types covered
