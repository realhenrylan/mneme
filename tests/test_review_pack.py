"""Tests for evaluation.review_pack — P1 真值人工确认审阅包生成器。

验证：
- relevance_level schema 校验与导入格式（validate_relevance_level /
  ground_truth_from_dict / load_ground_truth_map）
- 27 类 needs_review 条目的离线导出（字段齐全、reviewer 字段为空）
- 12 类缺 chunk 真值 case 的导出（relevance_level 为空）
- 审阅包可复现（两次运行字节一致）且绝不修改输入文件
- 匹配证据（bigram overlap）计算
- CLI 入口（不调用 LLM/API/网络）
"""

import hashlib
import json

import pytest

from evaluation.compare import (
    GroundTruthEntry,
    validate_relevance_level,
    ground_truth_from_dict,
    load_ground_truth_map,
)
from evaluation.review_pack import (
    REVIEW_DECISION_VALUES,
    RELEVANCE_LEVEL_VALUES,
    build_missing_truth_rows,
    build_overlap_review_rows,
    build_review_pack,
    chunk_evidence,
    load_corpus_chunks,
    main,
)


# ── Fixtures ─────────────────────────────────────────────────────────

def _write_jsonl(path, rows):
    with open(path, "w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


@pytest.fixture
def dataset_path(tmp_path):
    """合成数据集：exact / overlap / 缺 chunk 真值 / 应拒答 四类 case。"""
    rows = [
        {
            "id": "a-001", "query": "南京面积？", "query_type": "single_fact",
            "language": "zh", "relevant_source_ids": ["doc_a.pdf"],
            "relevant_chunks": [{
                "source_id": "doc_a.pdf",
                "chunk_text_snippet": "南京市总面积6587平方公里",
                "page": None, "section": None,
            }],
            "acceptable_answer_points": ["6587"], "should_refuse": False,
            "metadata": {"difficulty": "easy"},
        },
        {
            "id": "b-001", "query": "cross doc compare?", "query_type": "cross_document",
            "language": "en", "relevant_source_ids": ["doc_b.pdf"],
            "relevant_chunks": [{
                "source_id": "doc_b.pdf",
                "chunk_text_snippet": "alpha beta gamma delta",
                "page": None, "section": None,
            }],
            "acceptable_answer_points": ["gamma"], "should_refuse": False,
            "metadata": {"difficulty": "medium"},
        },
        {
            "id": "c-001", "query": "doc 元数据？", "query_type": "metadata",
            "language": "zh", "relevant_source_ids": ["doc_c.pdf"],
            "relevant_chunks": [],  # 缺 chunk 真值
            "acceptable_answer_points": ["2024"], "should_refuse": False,
            "metadata": {"difficulty": "easy"},
        },
        {
            "id": "d-001", "query": "不存在的事实？", "query_type": "no_answer",
            "language": "zh", "relevant_source_ids": [],
            "relevant_chunks": [], "acceptable_answer_points": [],
            "should_refuse": True, "metadata": {"difficulty": "easy"},
        },
    ]
    path = tmp_path / "dataset.jsonl"
    _write_jsonl(path, rows)
    return path


@pytest.fixture
def ground_truth_path(tmp_path):
    """合成 ground truth：exact(auto) + overlap(needs_review)×2 + fallback(needs_review)。"""
    rows = [
        {
            "case_id": "a-001", "source_id": "doc_a.pdf",
            "normalized_snippet": "南京市总面积6587平方公里",
            "matched_chunk_ids": ["chunk_a"], "match_method": "exact",
            "reviewer_status": "auto",
        },
        {
            "case_id": "b-001", "source_id": "doc_b.pdf",
            "normalized_snippet": "alpha beta gamma delta",
            "matched_chunk_ids": ["chunk_b1"], "match_method": "overlap",
            "reviewer_status": "needs_review",
        },
        {
            "case_id": "b-001", "source_id": "doc_b2.pdf",
            "normalized_snippet": "alpha beta gamma delta",
            "matched_chunk_ids": ["chunk_b2"], "match_method": "overlap",
            "reviewer_status": "needs_review",
        },
        {
            "case_id": "c-001", "source_id": "doc_c.pdf",
            "normalized_snippet": "", "matched_chunk_ids": ["chunk_c"],
            "match_method": "source_fallback", "reviewer_status": "needs_review",
        },
    ]
    path = tmp_path / "ground-truth-map.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(rows, f, ensure_ascii=False, indent=2)
    return path


@pytest.fixture
def corpus_json_path(tmp_path):
    rows = [
        {"chunk_id": "chunk_b1", "source_id": "doc_b.pdf",
         "text": "alpha beta gamma delta epsilon zeta"},
        {"chunk_id": "chunk_b2", "source_id": "doc_b2.pdf",
         "text": "unrelated content here"},
    ]
    path = tmp_path / "chunks.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(rows, f, ensure_ascii=False)
    return path


def _file_sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        h.update(f.read())
    return h.hexdigest()


# ── relevance_level schema 校验与导入格式 ────────────────────────────

class TestRelevanceLevelSchema:
    def test_valid_levels_pass(self):
        validate_relevance_level(None)
        validate_relevance_level("chunk")
        validate_relevance_level("source")

    def test_invalid_level_rejected(self):
        with pytest.raises(ValueError):
            validate_relevance_level("doc")
        with pytest.raises(ValueError):
            validate_relevance_level("")
        with pytest.raises(ValueError):
            validate_relevance_level("CHUNK")

    def test_review_constants_match_schema(self):
        assert set(RELEVANCE_LEVEL_VALUES) == {"chunk", "source"}
        assert set(REVIEW_DECISION_VALUES) == {"confirmed", "reject"}


class TestGroundTruthImport:
    def test_from_dict_with_level(self):
        e = ground_truth_from_dict({
            "case_id": "x", "source_id": "s.pdf",
            "normalized_snippet": "snip", "matched_chunk_ids": ["c1"],
            "match_method": "overlap", "reviewer_status": "needs_review",
            "relevance_level": "source",
        })
        assert e.relevance_level == "source"

    def test_from_dict_legacy_without_level(self):
        """旧版 ground-truth-map.json 无 relevance_level 字段，必须兼容。"""
        e = ground_truth_from_dict({
            "case_id": "x", "source_id": "s.pdf",
            "normalized_snippet": "snip", "matched_chunk_ids": ["c1"],
            "match_method": "exact", "reviewer_status": "auto",
        })
        assert e.relevance_level is None

    def test_from_dict_rejects_invalid_level(self):
        with pytest.raises(ValueError):
            ground_truth_from_dict({
                "case_id": "x", "source_id": "s.pdf",
                "normalized_snippet": "snip", "matched_chunk_ids": ["c1"],
                "match_method": "overlap", "reviewer_status": "needs_review",
                "relevance_level": "file",
            })

    def test_load_ground_truth_map_roundtrip(self, ground_truth_path):
        entries = load_ground_truth_map(ground_truth_path)
        assert len(entries) == 4
        assert all(isinstance(e, GroundTruthEntry) for e in entries)
        assert all(e.relevance_level is None for e in entries)


# ── 审阅行构建 ───────────────────────────────────────────────────────

class TestOverlapReviewRows:
    def test_only_needs_review_exported(self, dataset_path, ground_truth_path):
        from evaluation.schema import load_dataset
        cases = load_dataset(dataset_path)
        entries = load_ground_truth_map(ground_truth_path)
        rows = build_overlap_review_rows(entries, {c.id: c for c in cases}, {})

        # 只有 needs_review 的 3 条（exact auto 不导出）
        assert len(rows) == 3
        assert all(r["reviewer_status"] == "needs_review" for r in rows)

    def test_fields_and_blank_reviewer_fields(self, dataset_path, ground_truth_path):
        from evaluation.schema import load_dataset
        cases = load_dataset(dataset_path)
        entries = load_ground_truth_map(ground_truth_path)
        rows = build_overlap_review_rows(entries, {c.id: c for c in cases}, {})

        row = next(r for r in rows if r["case_id"] == "b-001")
        assert row["query"] == "cross doc compare?"
        assert row["query_type"] == "cross_document"
        assert row["language"] == "en"
        assert row["source_id"] == "doc_b.pdf"
        assert row["normalized_snippet"] == "alpha beta gamma delta"
        assert row["candidate_chunk_ids"] == ["chunk_b1"]
        # 工具不替人判定：审阅字段必须为空
        assert row["review_decision"] == ""
        assert row["reviewer_notes"] == ""

    def test_deterministic_order(self, dataset_path, ground_truth_path):
        from evaluation.schema import load_dataset
        cases = load_dataset(dataset_path)
        entries = load_ground_truth_map(ground_truth_path)
        by_id = {c.id: c for c in cases}
        rows1 = build_overlap_review_rows(entries, by_id, {})
        rows2 = build_overlap_review_rows(entries, by_id, {})
        assert rows1 == rows2

    def test_evidence_filled_with_corpus(self, dataset_path, ground_truth_path, corpus_json_path):
        from evaluation.schema import load_dataset
        cases = load_dataset(dataset_path)
        entries = load_ground_truth_map(ground_truth_path)
        chunk_texts = load_corpus_chunks(corpus_json_path)
        rows = build_overlap_review_rows(entries, {c.id: c for c in cases}, chunk_texts)

        row = next(r for r in rows if r["source_id"] == "doc_b.pdf")
        assert len(row["match_evidence"]) == 1
        ev = row["match_evidence"][0]
        assert ev["chunk_id"] == "chunk_b1"
        # snippet bigrams 全部命中 → overlap 1.0
        assert ev["bigram_overlap"] == 1.0
        assert ev["text_preview"].startswith("alpha beta gamma")

    def test_evidence_empty_without_corpus(self, dataset_path, ground_truth_path):
        from evaluation.schema import load_dataset
        cases = load_dataset(dataset_path)
        entries = load_ground_truth_map(ground_truth_path)
        rows = build_overlap_review_rows(entries, {c.id: c for c in cases}, {})
        assert all(r["match_evidence"] == [] for r in rows)


class TestMissingTruthRows:
    def test_only_answerable_without_chunk_truth(self, dataset_path):
        from evaluation.schema import load_dataset
        cases = load_dataset(dataset_path)
        rows = build_missing_truth_rows(cases)

        # c-001 缺 chunk 真值；d-001 应拒答不导出；a/b 有 relevant_chunks 不导出
        assert len(rows) == 1
        row = rows[0]
        assert row["case_id"] == "c-001"
        assert row["relevance_level"] == ""  # 待人工判定，不得预填
        assert row["reviewer_notes"] == ""
        assert row["relevant_source_ids"] == ["doc_c.pdf"]
        assert row["acceptable_answer_points"] == ["2024"]


class TestChunkEvidence:
    def test_exact_bigram_overlap(self):
        ev = chunk_evidence("abcde", "abcde fgh")
        assert ev["bigram_overlap"] == 1.0
        assert "abcde fgh" in ev["text_preview"]

    def test_partial_overlap(self):
        ev = chunk_evidence("abcdef", "xyz abc xy")
        assert 0.0 < ev["bigram_overlap"] < 1.0

    def test_empty_inputs_do_not_crash(self):
        ev = chunk_evidence("", "text")
        assert ev["bigram_overlap"] == 0.0
        ev2 = chunk_evidence("text", "")
        assert ev2["bigram_overlap"] == 0.0

    def test_preview_truncated(self):
        ev = chunk_evidence("ab", "x" * 500)
        assert len(ev["text_preview"]) <= 120


# ── 审阅包生成：可复现、只读输入 ─────────────────────────────────────

class TestBuildReviewPack:
    def test_outputs_and_manifest(self, dataset_path, ground_truth_path, tmp_path):
        out = tmp_path / "pack"
        manifest = build_review_pack(dataset_path, ground_truth_path, out)

        assert (out / "review-overlap.jsonl").exists()
        assert (out / "missing-chunk-truth.jsonl").exists()
        assert (out / "review-pack-manifest.json").exists()
        assert manifest["overlap_needs_review_count"] == 3
        assert manifest["missing_chunk_truth_count"] == 1
        assert manifest["dataset_sha256"] == _file_sha256(dataset_path)
        assert manifest["ground_truth_sha256"] == _file_sha256(ground_truth_path)

        with open(out / "review-pack-manifest.json", encoding="utf-8") as f:
            on_disk = json.load(f)
        assert on_disk == manifest

    def test_reproducible_byte_identical(self, dataset_path, ground_truth_path, tmp_path):
        out1 = tmp_path / "pack1"
        out2 = tmp_path / "pack2"
        build_review_pack(dataset_path, ground_truth_path, out1)
        build_review_pack(dataset_path, ground_truth_path, out2)
        for name in ("review-overlap.jsonl", "missing-chunk-truth.jsonl",
                     "review-pack-manifest.json"):
            b1 = (out1 / name).read_bytes()
            b2 = (out2 / name).read_bytes()
            assert b1 == b2, f"{name} differs between runs"

    def test_inputs_never_modified(self, dataset_path, ground_truth_path, tmp_path):
        ds_before = _file_sha256(dataset_path)
        gt_before = _file_sha256(ground_truth_path)
        build_review_pack(dataset_path, ground_truth_path, tmp_path / "pack")
        assert _file_sha256(dataset_path) == ds_before
        assert _file_sha256(ground_truth_path) == gt_before

    def test_with_corpus_json(self, dataset_path, ground_truth_path, corpus_json_path, tmp_path):
        out = tmp_path / "pack"
        build_review_pack(dataset_path, ground_truth_path, out, corpus_json_path)
        with open(out / "review-pack-manifest.json", encoding="utf-8") as f:
            manifest = json.load(f)
        assert manifest["corpus_json_sha256"] == _file_sha256(corpus_json_path)
        with open(out / "review-overlap.jsonl", encoding="utf-8") as f:
            rows = [json.loads(line) for line in f if line.strip()]
        assert any(len(r["match_evidence"]) > 0 for r in rows)


class TestLoadCorpusChunks:
    def test_normal(self, corpus_json_path):
        chunks = load_corpus_chunks(corpus_json_path)
        assert chunks["chunk_b1"] == "alpha beta gamma delta epsilon zeta"

    def test_none_returns_empty(self):
        assert load_corpus_chunks(None) == {}

    def test_missing_chunk_id_rejected(self, tmp_path):
        p = tmp_path / "bad.json"
        with open(p, "w", encoding="utf-8") as f:
            json.dump([{"text": "no id"}], f)
        with pytest.raises(ValueError):
            load_corpus_chunks(p)

    def test_not_a_list_rejected(self, tmp_path):
        p = tmp_path / "bad.json"
        with open(p, "w", encoding="utf-8") as f:
            json.dump({"chunk_id": "x"}, f)
        with pytest.raises(ValueError):
            load_corpus_chunks(p)


# ── CLI ──────────────────────────────────────────────────────────────

class TestCli:
    def test_main_success(self, dataset_path, ground_truth_path, tmp_path):
        out = tmp_path / "cli-pack"
        rc = main(["--dataset", str(dataset_path),
                   "--ground-truth", str(ground_truth_path),
                   "--output", str(out)])
        assert rc == 0
        assert (out / "review-pack-manifest.json").exists()

    def test_main_invalid_ground_truth_exits_nonzero(self, dataset_path, tmp_path):
        bad = tmp_path / "bad-gt.json"
        with open(bad, "w", encoding="utf-8") as f:
            json.dump([{
                "case_id": "x", "source_id": "s.pdf",
                "normalized_snippet": "s", "matched_chunk_ids": [],
                "match_method": "overlap", "reviewer_status": "needs_review",
                "relevance_level": "illegal",
            }], f)
        rc = main(["--dataset", str(dataset_path),
                   "--ground-truth", str(bad),
                   "--output", str(tmp_path / "pack")])
        assert rc == 2

    def test_main_missing_input_exits_nonzero(self, dataset_path, tmp_path):
        rc = main(["--dataset", str(dataset_path),
                   "--ground-truth", str(tmp_path / "nope.json"),
                   "--output", str(tmp_path / "pack")])
        assert rc == 2
