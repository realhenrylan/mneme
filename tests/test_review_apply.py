"""Tests for evaluation.review_apply — review pack 严格导入与消费门禁。

验证：
- apply 流水线：真实 review_pack 生成 pack → 人工填写 → 严格导入 → overlay
- 确定性输出 / manifest SHA 陈旧拒绝 / 空/非法/重复/缺失/未知行拒绝且无 partial output
- confirmed/reject 显式映射（reject 绝不当作 confirmed）、relevance_level 按 case_id 保存
- compare 侧 overlay 应用（唯一匹配、未消费/重复匹配失败）与真值门禁
- main 级：overlay 与 GT 不匹配在 prepare_index 前拒绝、门禁在 LLM 前失败、
  source-only 放行、无 overlay 兼容
"""

import hashlib
import json
from unittest.mock import patch

import pytest

from evaluation.compare import (
    GroundTruthEntry,
    apply_reviewed_truth_overlay,
    enforce_truth_gate,
    load_reviewed_truth_overlay,
)
from evaluation.review_apply import (
    REVIEW_APPLY_VERSION,
    ReviewApplyError,
    apply_review_pack,
    build_overlay,
    main,
)
from evaluation.schema import EvalCase, Language, QueryType


# ── Fixtures / helpers ───────────────────────────────────────────────

def _write_jsonl(path, rows):
    with open(path, "w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def _sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.fixture
def dataset_path(tmp_path):
    """合成数据集：y-001 有 overlap 标注；x-001 可回答但缺 chunk 真值。"""
    rows = [
        {
            "id": "y-001", "query": "cross doc compare?", "query_type": "cross_document",
            "language": "en", "relevant_source_ids": ["doc_y.pdf"],
            "relevant_chunks": [{
                "source_id": "doc_y.pdf",
                "chunk_text_snippet": "alpha beta gamma delta",
                "page": None, "section": None,
            }],
            "acceptable_answer_points": ["gamma"], "should_refuse": False,
            "metadata": {"difficulty": "medium"},
        },
        {
            "id": "x-001", "query": "doc 元数据？", "query_type": "metadata",
            "language": "zh", "relevant_source_ids": ["doc_x.pdf"],
            "relevant_chunks": [],
            "acceptable_answer_points": ["2024"], "should_refuse": False,
            "metadata": {"difficulty": "easy"},
        },
    ]
    path = tmp_path / "dataset.jsonl"
    _write_jsonl(path, rows)
    return path


@pytest.fixture
def ground_truth_path(tmp_path):
    """合成 base GT：y-001 一条 overlap needs_review。"""
    rows = [{
        "case_id": "y-001", "source_id": "doc_y.pdf",
        "normalized_snippet": "alpha beta gamma delta",
        "matched_chunk_ids": ["chunk_y"], "match_method": "overlap",
        "reviewer_status": "needs_review",
    }]
    path = tmp_path / "ground-truth-map.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(rows, f, ensure_ascii=False, indent=2)
    return path


@pytest.fixture
def pack_dir(tmp_path, dataset_path, ground_truth_path):
    """用真实 review_pack 生成待审阅 pack，然后人工填写。"""
    from evaluation.review_pack import build_review_pack
    d = tmp_path / "pack"
    build_review_pack(dataset_path, ground_truth_path, d)
    # 人工填写：overlap → confirmed；missing → source
    rows = []
    with open(d / "review-overlap.jsonl", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                row = json.loads(line)
                row["review_decision"] = "confirmed"
                row["reviewer_notes"] = "ok"
                rows.append(row)
    _write_jsonl(d / "review-overlap.jsonl", rows)

    mrows = []
    with open(d / "missing-chunk-truth.jsonl", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                row = json.loads(line)
                row["relevance_level"] = "source"
                row["reviewer_notes"] = "metadata only"
                mrows.append(row)
    _write_jsonl(d / "missing-chunk-truth.jsonl", mrows)
    return d


def _filled_pack(tmp_path, dataset_path, ground_truth_path, *,
                 overlap_fill=None, missing_fill=None):
    """生成 pack 并应用自定义填写（默认全 confirmed / 全 source）。"""
    from evaluation.review_pack import build_review_pack
    d = tmp_path / "pack"
    build_review_pack(dataset_path, ground_truth_path, d)
    overlap_fill = overlap_fill or (lambda r: r.update(review_decision="confirmed"))
    missing_fill = missing_fill or (lambda r: r.update(relevance_level="source"))
    rows = []
    with open(d / "review-overlap.jsonl", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                row = json.loads(line)
                overlap_fill(row)
                rows.append(row)
    _write_jsonl(d / "review-overlap.jsonl", rows)
    mrows = []
    with open(d / "missing-chunk-truth.jsonl", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                row = json.loads(line)
                missing_fill(row)
                mrows.append(row)
    _write_jsonl(d / "missing-chunk-truth.jsonl", mrows)
    return d


def _overlay_dict(dataset_path, entries=None, levels=None):
    return {
        "version": REVIEW_APPLY_VERSION,
        "dataset_sha256": _sha256(dataset_path) if dataset_path else "0" * 64,
        "ground_truth_sha256": "0" * 64,
        "entries": entries or [],
        "case_relevance_levels": levels or [],
        "counts": {
            "overlap_decisions": len(entries or []),
            "confirmed": sum(1 for e in (entries or [])
                             if e["review_decision"] == "confirmed"),
            "rejected": sum(1 for e in (entries or [])
                            if e["review_decision"] == "rejected"),
            "case_relevance_decisions": len(levels or []),
            "chunk_level": sum(1 for c in (levels or [])
                               if c["relevance_level"] == "chunk"),
            "source_only": sum(1 for c in (levels or [])
                               if c["relevance_level"] == "source"),
        },
        "notes": "",
    }


# ── apply 流水线：确定性 / 内容 / 陈旧拒绝 ──────────────────────────

class TestApplyPipeline:
    def test_apply_produces_overlay_and_manifest(
        self, dataset_path, ground_truth_path, pack_dir, tmp_path,
    ):
        out = tmp_path / "out"
        result = apply_review_pack(dataset_path, ground_truth_path, pack_dir, out)
        assert result["version"] == REVIEW_APPLY_VERSION
        assert (out / "reviewed-truth-overlay.json").exists()
        assert (out / "review-apply-manifest.json").exists()

        overlay = json.loads(
            (out / "reviewed-truth-overlay.json").read_text(encoding="utf-8"),
        )
        assert overlay["dataset_sha256"] == _sha256(dataset_path)
        assert overlay["ground_truth_sha256"] == _sha256(ground_truth_path)
        assert len(overlay["entries"]) == 1
        e = overlay["entries"][0]
        assert e["case_id"] == "y-001"
        assert e["review_decision"] == "confirmed"
        assert len(overlay["case_relevance_levels"]) == 1
        assert overlay["case_relevance_levels"][0] == {
            "case_id": "x-001", "relevance_level": "source",
            "reviewer_notes": "metadata only",
        }

    def test_deterministic_output(
        self, dataset_path, ground_truth_path, pack_dir, tmp_path,
    ):
        out1 = tmp_path / "out1"
        out2 = tmp_path / "out2"
        apply_review_pack(dataset_path, ground_truth_path, pack_dir, out1)
        apply_review_pack(dataset_path, ground_truth_path, pack_dir, out2)
        assert (out1 / "reviewed-truth-overlay.json").read_bytes() == (
            out2 / "reviewed-truth-overlay.json").read_bytes()
        assert (out1 / "review-apply-manifest.json").read_bytes() == (
            out2 / "review-apply-manifest.json").read_bytes()

    def test_reject_maps_to_rejected_not_confirmed(
        self, dataset_path, ground_truth_path, tmp_path,
    ):
        """reject 显式映射为 rejected，绝不与 confirmed 混淆。"""
        d = _filled_pack(
            tmp_path, dataset_path, ground_truth_path,
            overlap_fill=lambda r: r.update(review_decision="reject"),
        )
        out = tmp_path / "out"
        apply_review_pack(dataset_path, ground_truth_path, d, out)
        overlay = json.loads(
            (out / "reviewed-truth-overlay.json").read_text(encoding="utf-8"),
        )
        assert overlay["entries"][0]["review_decision"] == "rejected"
        assert overlay["counts"]["rejected"] == 1
        assert overlay["counts"]["confirmed"] == 0

    def test_inputs_never_modified(
        self, dataset_path, ground_truth_path, pack_dir, tmp_path,
    ):
        ds_before = _sha256(dataset_path)
        gt_before = _sha256(ground_truth_path)
        apply_review_pack(dataset_path, ground_truth_path, pack_dir, tmp_path / "out")
        assert _sha256(dataset_path) == ds_before
        assert _sha256(ground_truth_path) == gt_before

    def test_output_dir_must_differ_from_pack_dir(
        self, dataset_path, ground_truth_path, pack_dir,
    ):
        with pytest.raises(ReviewApplyError):
            apply_review_pack(dataset_path, ground_truth_path, pack_dir, pack_dir)

    def test_overlay_contains_no_secrets(
        self, dataset_path, ground_truth_path, pack_dir, tmp_path,
    ):
        out = tmp_path / "out"
        apply_review_pack(dataset_path, ground_truth_path, pack_dir, out)
        text = (out / "reviewed-truth-overlay.json").read_text(
            encoding="utf-8").lower()
        for hint in ("://", "@", "sk-", "password", "secret"):
            assert hint not in text


class TestApplyManifestStaleRejected:
    def test_dataset_changed_rejected(
        self, dataset_path, ground_truth_path, pack_dir, tmp_path,
    ):
        dataset_path.write_text(dataset_path.read_text(encoding="utf-8") + "x",
                                encoding="utf-8")
        with pytest.raises(ReviewApplyError) as exc:
            apply_review_pack(dataset_path, ground_truth_path, pack_dir,
                              tmp_path / "out")
        assert any("dataset" in e for e in exc.value.errors)

    def test_ground_truth_changed_rejected(
        self, dataset_path, ground_truth_path, pack_dir, tmp_path,
    ):
        ground_truth_path.write_text("[]", encoding="utf-8")
        with pytest.raises(ReviewApplyError) as exc:
            apply_review_pack(dataset_path, ground_truth_path, pack_dir,
                              tmp_path / "out")
        assert any("ground_truth" in e for e in exc.value.errors)

    def test_stale_rejection_produces_no_output(
        self, dataset_path, ground_truth_path, pack_dir, tmp_path,
    ):
        out = tmp_path / "out"
        dataset_path.write_text("corrupt", encoding="utf-8")
        with pytest.raises(ReviewApplyError):
            apply_review_pack(dataset_path, ground_truth_path, pack_dir, out)
        assert not out.exists() or list(out.iterdir()) == []


# ── 严格校验：空/非法/重复/缺失/未知行，无 partial output ───────────

class TestApplyValidationRejected:
    def _apply_with_fill(self, dataset_path, ground_truth_path, tmp_path,
                         overlap_fill, missing_fill=None):
        d = _filled_pack(tmp_path, dataset_path, ground_truth_path,
                         overlap_fill=overlap_fill, missing_fill=missing_fill)
        out = tmp_path / "out"
        with pytest.raises(ReviewApplyError) as exc:
            apply_review_pack(dataset_path, ground_truth_path, d, out)
        assert not out.exists() or list(out.iterdir()) == []
        return exc.value

    def test_empty_review_decision_rejected(self, dataset_path, ground_truth_path, tmp_path):
        err = self._apply_with_fill(
            dataset_path, ground_truth_path, tmp_path,
            overlap_fill=lambda r: r.update(review_decision=""),
        )
        assert any("review_decision" in e for e in err.errors)

    def test_invalid_review_decision_rejected(self, dataset_path, ground_truth_path, tmp_path):
        err = self._apply_with_fill(
            dataset_path, ground_truth_path, tmp_path,
            overlap_fill=lambda r: r.update(review_decision="yes"),
        )
        assert any("review_decision" in e for e in err.errors)

    def test_invalid_relevance_level_rejected(self, dataset_path, ground_truth_path, tmp_path):
        err = self._apply_with_fill(
            dataset_path, ground_truth_path, tmp_path,
            overlap_fill=lambda r: r.update(review_decision="confirmed"),
            missing_fill=lambda r: r.update(relevance_level="doc"),
        )
        assert any("relevance_level" in e for e in err.errors)

    def test_empty_relevance_level_rejected(self, dataset_path, ground_truth_path, tmp_path):
        err = self._apply_with_fill(
            dataset_path, ground_truth_path, tmp_path,
            overlap_fill=lambda r: r.update(review_decision="confirmed"),
            missing_fill=lambda r: r.update(relevance_level=""),
        )
        assert any("relevance_level" in e for e in err.errors)

    def test_duplicate_overlap_row_rejected(self, dataset_path, ground_truth_path, tmp_path):
        def fill(rows):
            # 复制第一行 → 重复
            rows.append(dict(rows[0]))
            for r in rows:
                r["review_decision"] = "confirmed"
        d = tmp_path / "pack"
        from evaluation.review_pack import build_review_pack
        build_review_pack(dataset_path, ground_truth_path, d)
        rows = [json.loads(l) for l in open(d / "review-overlap.jsonl", encoding="utf-8") if l.strip()]
        fill(rows)
        _write_jsonl(d / "review-overlap.jsonl", rows)
        out = tmp_path / "out"
        with pytest.raises(ReviewApplyError) as exc:
            apply_review_pack(dataset_path, ground_truth_path, d, out)
        assert any("duplicate" in e for e in exc.value.errors)
        assert not out.exists() or list(out.iterdir()) == []

    def test_missing_row_rejected(self, dataset_path, ground_truth_path, tmp_path):
        d = _filled_pack(tmp_path, dataset_path, ground_truth_path,
                         overlap_fill=lambda r: r.update(review_decision="confirmed"))
        # 删除唯一一行 → 行数 < manifest 计数
        rows = [json.loads(l) for l in open(d / "review-overlap.jsonl", encoding="utf-8") if l.strip()]
        rows = rows[1:]
        _write_jsonl(d / "review-overlap.jsonl", rows)
        out = tmp_path / "out"
        with pytest.raises(ReviewApplyError) as exc:
            apply_review_pack(dataset_path, ground_truth_path, d, out)
        assert any("rows count" in e for e in exc.value.errors)
        assert not out.exists() or list(out.iterdir()) == []

    def test_unknown_extra_row_rejected(self, dataset_path, ground_truth_path, tmp_path):
        d = _filled_pack(tmp_path, dataset_path, ground_truth_path,
                         overlap_fill=lambda r: r.update(review_decision="confirmed"))
        rows = [json.loads(l) for l in open(d / "review-overlap.jsonl", encoding="utf-8") if l.strip()]
        extra = dict(rows[0])
        extra["case_id"] = "zz-999"
        rows.append(extra)
        _write_jsonl(d / "review-overlap.jsonl", rows)
        out = tmp_path / "out"
        with pytest.raises(ReviewApplyError) as exc:
            apply_review_pack(dataset_path, ground_truth_path, d, out)
        assert any("rows count" in e for e in exc.value.errors)
        assert not out.exists() or list(out.iterdir()) == []

    def test_unknown_column_rejected(self, dataset_path, ground_truth_path, tmp_path):
        d = _filled_pack(tmp_path, dataset_path, ground_truth_path,
                         overlap_fill=lambda r: r.update(review_decision="confirmed"))
        rows = [json.loads(l) for l in open(d / "review-overlap.jsonl", encoding="utf-8") if l.strip()]
        rows[0]["hacked_field"] = 1
        _write_jsonl(d / "review-overlap.jsonl", rows)
        out = tmp_path / "out"
        with pytest.raises(ReviewApplyError) as exc:
            apply_review_pack(dataset_path, ground_truth_path, d, out)
        assert any("keys mismatch" in e for e in exc.value.errors)

    def test_cli_invalid_fill_exits_nonzero(
        self, dataset_path, ground_truth_path, tmp_path,
    ):
        d = _filled_pack(tmp_path, dataset_path, ground_truth_path,
                         overlap_fill=lambda r: r.update(review_decision="maybe"))
        out = tmp_path / "out"
        rc = main(["--dataset", str(dataset_path),
                   "--ground-truth", str(ground_truth_path),
                   "--review-pack", str(d),
                   "--output", str(out)])
        assert rc == 1
        assert not out.exists() or list(out.iterdir()) == []

    def test_cli_success(self, dataset_path, ground_truth_path, pack_dir, tmp_path):
        out = tmp_path / "out"
        rc = main(["--dataset", str(dataset_path),
                   "--ground-truth", str(ground_truth_path),
                   "--review-pack", str(pack_dir),
                   "--output", str(out)])
        assert rc == 0
        assert (out / "reviewed-truth-overlay.json").exists()


# ── compare 侧：overlay 应用 ─────────────────────────────────────────

def _gt_entry(case_id="y-001", source_id="doc_y.pdf",
              snippet="alpha beta gamma delta", chunks=("chunk_y",),
              method="overlap", status="needs_review"):
    return GroundTruthEntry(
        case_id=case_id, source_id=source_id, normalized_snippet=snippet,
        matched_chunk_ids=list(chunks), match_method=method,
        reviewer_status=status,
    )


class TestOverlayApplication:
    def test_confirmed_applied(self):
        gt = [_gt_entry()]
        overlay = _overlay_dict(
            dataset_path=None,
            entries=[{
                "case_id": "y-001", "source_id": "doc_y.pdf",
                "normalized_snippet": "alpha beta gamma delta",
                "candidate_chunk_ids": ["chunk_y"],
                "review_decision": "confirmed", "reviewer_notes": "",
            }],
        )
        updated, source_only = apply_reviewed_truth_overlay(gt, overlay)
        assert updated[0].reviewer_status == "confirmed"
        assert source_only == []

    def test_reject_applied_as_rejected(self):
        gt = [_gt_entry()]
        overlay = _overlay_dict(
            dataset_path=None,
            entries=[{
                "case_id": "y-001", "source_id": "doc_y.pdf",
                "normalized_snippet": "alpha beta gamma delta",
                "candidate_chunk_ids": ["chunk_y"],
                "review_decision": "rejected", "reviewer_notes": "",
            }],
        )
        updated, _ = apply_reviewed_truth_overlay(gt, overlay)
        # reject → rejected（显式），绝不等于 confirmed
        assert updated[0].reviewer_status == "rejected"

    def test_unconsumed_overlay_entry_fails(self):
        gt = [_gt_entry()]
        overlay = _overlay_dict(
            dataset_path=None,
            entries=[{
                "case_id": "y-001", "source_id": "doc_y.pdf",
                "normalized_snippet": "completely different snippet",
                "candidate_chunk_ids": ["chunk_y"],
                "review_decision": "confirmed", "reviewer_notes": "",
            }],
        )
        with pytest.raises(ValueError) as exc:
            apply_reviewed_truth_overlay(gt, overlay)
        assert "not consumed" in str(exc.value)

    def test_duplicate_overlay_match_fails(self):
        """同键两条 overlay entries → 重复匹配失败。"""
        gt = [_gt_entry()]
        entries = [
            {
                "case_id": "y-001", "source_id": "doc_y.pdf",
                "normalized_snippet": "alpha beta gamma delta",
                "candidate_chunk_ids": ["chunk_y"],
                "review_decision": "confirmed", "reviewer_notes": "",
            },
            {
                "case_id": "y-001", "source_id": "doc_y.pdf",
                "normalized_snippet": "alpha beta gamma delta",
                "candidate_chunk_ids": ["chunk_y"],
                "review_decision": "rejected", "reviewer_notes": "",
            },
        ]
        overlay = _overlay_dict(dataset_path=None, entries=entries)
        with pytest.raises(ValueError) as exc:
            apply_reviewed_truth_overlay(gt, overlay)
        assert "duplicate" in str(exc.value)

    def test_unlisted_gt_entries_untouched(self):
        """不在 overlay 的 GT entry（如 exact auto）原样保留。"""
        gt = [_gt_entry(method="exact", status="auto")]
        overlay = _overlay_dict(dataset_path=None, entries=[])
        updated, _ = apply_reviewed_truth_overlay(gt, overlay)
        assert updated[0].reviewer_status == "auto"

    def test_source_only_case_ids_extracted(self):
        gt = [_gt_entry()]
        overlay = _overlay_dict(
            dataset_path=None,
            entries=[{
                "case_id": "y-001", "source_id": "doc_y.pdf",
                "normalized_snippet": "alpha beta gamma delta",
                "candidate_chunk_ids": ["chunk_y"],
                "review_decision": "confirmed", "reviewer_notes": "",
            }],
            levels=[{"case_id": "x-001", "relevance_level": "source",
                     "reviewer_notes": ""}],
        )
        _, source_only = apply_reviewed_truth_overlay(gt, overlay)
        assert source_only == ["x-001"]

    def test_load_overlay_rejects_bad_version(self, tmp_path, dataset_path):
        p = tmp_path / "overlay.json"
        p.write_text(json.dumps({"version": 99}), encoding="utf-8")
        with pytest.raises(ValueError):
            load_reviewed_truth_overlay(p)


# ── 真值门禁 ─────────────────────────────────────────────────────────

def _case(cid, should_refuse=False):
    return EvalCase(
        id=cid, query="q", query_type=QueryType.SINGLE_FACT,
        language=Language.ZH, relevant_source_ids=[],
        should_refuse=should_refuse,
    )


class TestTruthGate:
    def test_source_only_passes(self):
        cases = [_case("x-001")]
        overlay = _overlay_dict(
            dataset_path=None,
            levels=[{"case_id": "x-001", "relevance_level": "source",
                     "reviewer_notes": ""}],
        )
        errors = enforce_truth_gate(
            cases, {"x-001": False}, overlay, ["x-001"],
        )
        assert errors == []

    def test_chunk_level_without_truth_fails_with_case_id(self):
        cases = [_case("x-001")]
        overlay = _overlay_dict(
            dataset_path=None,
            levels=[{"case_id": "x-001", "relevance_level": "chunk",
                     "reviewer_notes": ""}],
        )
        errors = enforce_truth_gate(cases, {"x-001": False}, overlay, [])
        assert len(errors) == 1
        assert "x-001" in errors[0]
        assert "chunk" in errors[0]

    def test_no_decision_without_truth_fails(self):
        """overlap 全 reject 导致无真值且无显式 source 决定 → 失败。"""
        cases = [_case("y-001")]
        overlay = _overlay_dict(dataset_path=None, entries=[], levels=[])
        errors = enforce_truth_gate(cases, {"y-001": False}, overlay, [])
        assert len(errors) == 1
        assert "y-001" in errors[0]
        assert "no explicit source-level decision" in errors[0]

    def test_reliable_truth_passes(self):
        cases = [_case("y-001")]
        overlay = _overlay_dict(dataset_path=None, entries=[], levels=[])
        errors = enforce_truth_gate(cases, {"y-001": True}, overlay, [])
        assert errors == []

    def test_refuse_cases_skipped(self):
        cases = [_case("r-001", should_refuse=True)]
        overlay = _overlay_dict(dataset_path=None, entries=[], levels=[])
        errors = enforce_truth_gate(cases, {"r-001": False}, overlay, [])
        assert errors == []


# ── main 级：前置拒绝 / 放行 / 无 overlay 兼容 ───────────────────────

def _main_mock_patches():
    return (
        patch("evaluation.compare.save_retrieval_results_by_alpha"),
        patch("evaluation.compare.run_retrieval_grid"),
        patch("evaluation.compare.build_query_plan_cache"),
        patch("evaluation.compare.validate_reranker"),
        patch("evaluation.compare.build_ground_truth_map"),
        patch("src.rag.prepare_index"),
    )


def _set_main_mocks(mock_prepare, mock_gt, mock_val, mock_cache, mock_grid, mock_save):
    mock_prepare.return_value = (None, None, None, [], [])
    mock_gt.return_value = [_gt_entry()]
    mock_val.return_value = None
    mock_cache.return_value = {}
    mock_grid.return_value = []


def _write_overlay(tmp_path, dataset_path, entries, levels):
    p = tmp_path / "overlay.json"
    p.write_text(
        json.dumps(_overlay_dict(dataset_path, entries, levels),
                   ensure_ascii=False),
        encoding="utf-8",
    )
    return p


_Y_ENTRY = {
    "case_id": "y-001", "source_id": "doc_y.pdf",
    "normalized_snippet": "alpha beta gamma delta",
    "candidate_chunk_ids": ["chunk_y"],
    "review_decision": "confirmed", "reviewer_notes": "",
}


class TestMainReviewedTruth:
    @patch("evaluation.compare.save_retrieval_results_by_alpha")
    @patch("evaluation.compare.run_retrieval_grid")
    @patch("evaluation.compare.build_query_plan_cache")
    @patch("evaluation.compare.validate_reranker")
    @patch("evaluation.compare.build_ground_truth_map")
    @patch("src.rag.prepare_index")
    def test_overlay_stale_dataset_rejected_before_index(
        self, mock_prepare, mock_gt, mock_val, mock_cache, mock_grid, mock_save,
        dataset_path, ground_truth_path, tmp_path,
    ):
        """overlay dataset SHA 与当前 dataset 不一致 → prepare_index 前拒绝。"""
        _set_main_mocks(mock_prepare, mock_gt, mock_val, mock_cache, mock_grid, mock_save)
        overlay_path = tmp_path / "overlay.json"
        overlay_path.write_text(json.dumps({
            "version": REVIEW_APPLY_VERSION,
            "dataset_sha256": "0" * 64,  # 与当前 dataset 不匹配 → 陈旧
            "ground_truth_sha256": "0" * 64,
            "entries": [_Y_ENTRY], "case_relevance_levels": [],
            "counts": {}, "notes": "",
        }), encoding="utf-8")
        rc = _run_main([
            "--dataset", str(dataset_path),
            "--corpus-dir", str(tmp_path),
            "--arms", "standard",
            "--split", "development",
            "--reviewed-truth", str(overlay_path),
            "--output", str(tmp_path / "out"),
        ])
        assert rc == 1
        mock_prepare.assert_not_called()

    @patch("evaluation.compare.save_retrieval_results_by_alpha")
    @patch("evaluation.compare.run_retrieval_grid")
    @patch("evaluation.compare.build_query_plan_cache")
    @patch("evaluation.compare.validate_reranker")
    @patch("evaluation.compare.build_ground_truth_map")
    @patch("src.rag.prepare_index")
    def test_overlay_missing_annotation_rejected_before_index(
        self, mock_prepare, mock_gt, mock_val, mock_cache, mock_grid, mock_save,
        dataset_path, ground_truth_path, tmp_path,
    ):
        """overlay 引用 dataset 中不存在的标注 → prepare_index 前拒绝。"""
        _set_main_mocks(mock_prepare, mock_gt, mock_val, mock_cache, mock_grid, mock_save)
        bad_entry = dict(_Y_ENTRY)
        bad_entry["normalized_snippet"] = "not in dataset"
        overlay_path = _write_overlay(tmp_path, dataset_path, [bad_entry], [])
        rc = _run_main([
            "--dataset", str(dataset_path),
            "--corpus-dir", str(tmp_path),
            "--arms", "standard",
            "--split", "development",
            "--reviewed-truth", str(overlay_path),
            "--output", str(tmp_path / "out"),
        ])
        assert rc == 1
        mock_prepare.assert_not_called()

    @patch("evaluation.compare.save_retrieval_results_by_alpha")
    @patch("evaluation.compare.run_retrieval_grid")
    @patch("evaluation.compare.build_query_plan_cache")
    @patch("evaluation.compare.validate_reranker")
    @patch("evaluation.compare.build_ground_truth_map")
    @patch("src.rag.prepare_index")
    def test_overlay_not_consumed_by_gt_rejected_before_llm(
        self, mock_prepare, mock_gt, mock_val, mock_cache, mock_grid, mock_save,
        dataset_path, ground_truth_path, tmp_path,
    ):
        """GT 与 overlay 不匹配（未消费）→ 在 QueryPlan/LLM 调用前拒绝。"""
        _set_main_mocks(mock_prepare, mock_gt, mock_val, mock_cache, mock_grid, mock_save)
        # GT mock 返回空 → overlay entry 未消费
        mock_gt.return_value = []
        overlay_path = _write_overlay(tmp_path, dataset_path, [_Y_ENTRY], [])
        rc = _run_main([
            "--dataset", str(dataset_path),
            "--corpus-dir", str(tmp_path),
            "--arms", "standard",
            "--split", "development",
            "--reviewed-truth", str(overlay_path),
            "--output", str(tmp_path / "out"),
        ])
        assert rc == 1
        mock_prepare.assert_called_once()
        mock_cache.assert_not_called()  # 第一个 LLM 调用（query plan）未发生

    @patch("evaluation.compare.save_retrieval_results_by_alpha")
    @patch("evaluation.compare.run_retrieval_grid")
    @patch("evaluation.compare.build_query_plan_cache")
    @patch("evaluation.compare.validate_reranker")
    @patch("evaluation.compare.build_ground_truth_map")
    @patch("src.rag.prepare_index")
    def test_source_only_proceeds_to_llm(
        self, mock_prepare, mock_gt, mock_val, mock_cache, mock_grid, mock_save,
        dataset_path, ground_truth_path, tmp_path,
    ):
        """confirmed + source-only 组合：应用成功、门禁放行、到达 LLM 阶段。"""
        _set_main_mocks(mock_prepare, mock_gt, mock_val, mock_cache, mock_grid, mock_save)
        overlay_path = _write_overlay(
            tmp_path, dataset_path, [_Y_ENTRY],
            [{"case_id": "x-001", "relevance_level": "source",
              "reviewer_notes": ""}],
        )
        rc = _run_main([
            "--dataset", str(dataset_path),
            "--corpus-dir", str(tmp_path),
            "--arms", "standard",
            "--split", "development",
            "--reviewed-truth", str(overlay_path),
            "--output", str(tmp_path / "out"),
        ])
        assert rc == 0
        mock_cache.assert_called_once()
        # GT mock 的 entry 被应用为 confirmed（可靠）→ cache 收到 alpha_values
        assert mock_cache.call_args.kwargs["alpha_values"] == [0.7]

    @patch("evaluation.compare.save_retrieval_results_by_alpha")
    @patch("evaluation.compare.run_retrieval_grid")
    @patch("evaluation.compare.build_query_plan_cache")
    @patch("evaluation.compare.validate_reranker")
    @patch("evaluation.compare.build_ground_truth_map")
    @patch("src.rag.prepare_index")
    def test_chunk_level_without_truth_gate_fails_before_llm(
        self, mock_prepare, mock_gt, mock_val, mock_cache, mock_grid, mock_save,
        dataset_path, ground_truth_path, tmp_path,
    ):
        """relevance_level=chunk 但无可靠真值 → 门禁失败，LLM 未启动。"""
        _set_main_mocks(mock_prepare, mock_gt, mock_val, mock_cache, mock_grid, mock_save)
        mock_gt.return_value = []  # x-001 无 GT entry
        overlay_path = _write_overlay(
            tmp_path, dataset_path, [],
            [{"case_id": "x-001", "relevance_level": "chunk",
              "reviewer_notes": ""}],
        )
        rc = _run_main([
            "--dataset", str(dataset_path),
            "--corpus-dir", str(tmp_path),
            "--arms", "standard",
            "--split", "development",
            "--reviewed-truth", str(overlay_path),
            "--output", str(tmp_path / "out"),
        ])
        assert rc == 1
        mock_prepare.assert_called_once()
        mock_cache.assert_not_called()

    @patch("evaluation.compare.save_retrieval_results_by_alpha")
    @patch("evaluation.compare.run_retrieval_grid")
    @patch("evaluation.compare.build_query_plan_cache")
    @patch("evaluation.compare.validate_reranker")
    @patch("evaluation.compare.build_ground_truth_map")
    @patch("src.rag.prepare_index")
    def test_without_overlay_old_behavior(
        self, mock_prepare, mock_gt, mock_val, mock_cache, mock_grid, mock_save,
        dataset_path, ground_truth_path, tmp_path,
    ):
        """不传 --reviewed-truth → 无 overlay 旧行为，正常运行。"""
        _set_main_mocks(mock_prepare, mock_gt, mock_val, mock_cache, mock_grid, mock_save)
        rc = _run_main([
            "--dataset", str(dataset_path),
            "--corpus-dir", str(tmp_path),
            "--arms", "standard",
            "--split", "development",
            "--output", str(tmp_path / "out"),
        ])
        assert rc == 0
        mock_prepare.assert_called_once()
        mock_cache.assert_called_once()


def _run_main(argv):
    import evaluation.compare as compare_mod
    return compare_mod.main(argv)
