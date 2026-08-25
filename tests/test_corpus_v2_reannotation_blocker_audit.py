import json
from pathlib import Path

import pytest

from scripts import corpus_v2_reannotation_blocker_audit as audit


def test_classification_is_mutually_exclusive_and_scope_expansion_is_not_auto_applicable():
    blockers = [{"case_id": "c", "chunk_id": "x", "source_id": "s", "reason": "invalid rationale"}]
    draft = [{"id": "c", "acceptable_answer_points": ["目标答案"], "relevant_chunk_ids": ["x"]}]
    chunks = [
        {"chunk_id": "x", "source": "s", "text": "这里没有答案"},
        {"chunk_id": "y", "source": "s", "text": "目标答案在另一个块"},
    ]
    catalog = audit.build_anchor_catalog(chunks)
    rows, spans = audit.audit_rows(blockers, draft, chunks, catalog)
    assert len(rows) == 1
    assert rows[0]["root_cause_category"] == "source_scope_expansion_required"
    assert rows[0]["requires_owner_authorization"] is True
    assert rows[0]["auto_applicable"] is False
    assert len(spans) == 1
    assert spans[0]["auto_applicable"] is False
    assert set(audit.CATEGORIES).issuperset({rows[0]["root_cause_category"]})


def test_anchor_insufficient_differs_from_absent():
    blockers = [{"case_id": "c", "chunk_id": "x", "source_id": "s", "reason": "invalid"}]
    draft = [{"id": "c", "acceptable_answer_points": ["目标答案"], "relevant_chunk_ids": ["x"]}]
    chunks = [{"chunk_id": "x", "source": "s", "text": "目标\n答案"}]
    rows, _ = audit.audit_rows(blockers, draft, chunks, audit.build_anchor_catalog(chunks))
    assert rows[0]["root_cause_category"] == "anchor_catalog_insufficient"


def test_integrity_blocker_is_fail_closed():
    blockers = [{"case_id": "c", "chunk_id": "missing", "source_id": "s", "reason": "invalid"}]
    draft = [{"id": "c", "acceptable_answer_points": ["答案"], "relevant_chunk_ids": ["missing"]}]
    rows, _ = audit.audit_rows(blockers, draft, [], [])
    assert rows[0]["root_cause_category"] == "integrity_or_contract_blocker"
    assert rows[0]["auto_applicable"] is False


def test_real_target_gate_and_deterministic_build(tmp_path):
    result = audit.run(tmp_path)
    assert result["counts"]["total"] == 13
    assert sum(result["counts"]["categories"].values()) == 13
    assert result["manifest"]["activation_blocked"] is True
    assert not (tmp_path / "draft-after.jsonl").exists()
    assert not (tmp_path / "evidence-after.jsonl").exists()
    assert not (tmp_path / "overlay").exists()

    other = tmp_path.parent / "audit-again"
    result2 = audit.run(other)
    for name in audit.OUTPUT_FILES:
        assert (tmp_path / name).read_bytes() == (other / name).read_bytes()
