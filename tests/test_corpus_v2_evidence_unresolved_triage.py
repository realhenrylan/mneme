from pathlib import Path
import json
import pytest

import scripts.corpus_v2_evidence_unresolved_triage as triage

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "evaluation/datasets/v2/revisions/v2.0.2-evidence-coordinate-repair"


def test_real_input_has_exactly_thirteen_rows_and_five_categories():
    result = triage.run(out_dir=ROOT / "evaluation/datasets/v2/revisions/v2.0.2-evidence-coordinate-repair/unresolved-triage-test")
    rows = result["rows"]
    assert len(rows) == 13
    categories = {row["root_cause_category"] for row in rows}
    assert categories <= set(triage.CATEGORIES)
    assert sum(result["summary"]["category_counts"].values()) == 13


def test_whitespace_mapping_is_reversible():
    text = "标题\r\n值：  alpha\u2003beta"
    start, end = triage.locate_whitespace_candidate(text, "标题\n值： alpha beta")
    assert text[start:end] == text
    assert triage.display_snippet(text[start:end]) == triage.display_snippet("标题\n值： alpha beta")


def test_duplicate_requires_two_sided_context():
    row = triage.diagnose_row(
        {"case_id": "x", "chunk_id": "c", "source_id": "s", "legacy_char_range": {"start": 0, "end": 3}, "old_snippet": "same"},
        {"chunk_id": "c", "source": "s", "text": "same A same B"},
    )
    assert row["candidate_auto_resolution"] is False
    assert row["root_cause_category"] != "legacy_range_disambiguable_duplicate"


def test_format_and_semantic_never_auto_resolve():
    formatted = triage.classify_difference("hello", "**hello**")
    semantic = triage.classify_difference("中文释义", "English translation")
    assert formatted[0] == "format_transform_requires_policy"
    assert formatted[1] is False
    assert semantic[0] == "semantic_or_content_drift"
    assert semantic[1] is False


def test_manifest_self_hash_and_no_activation():
    out = ROOT / "evaluation/datasets/v2/revisions/v2.0.2-evidence-coordinate-repair/unresolved-triage-test"
    result = triage.run(out_dir=out)
    assert result["manifest"]["activation_blocked"] is True
    assert triage.verify_manifest(result["manifest"])
    assert not (out / "activation.json").exists()
    assert not (out / "overlay.jsonl").exists()
