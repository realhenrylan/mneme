"""Tests for scripts.corpus_v2_review — evidence-driven second-pass review.

Covers: deterministic evidence-review pack (no split identity, per-case
evidence SHA-256), fail-closed gates (evidence drift / missing chunk /
non-contiguous snippet / broken multi-turn chain / draft rewrite), the
mocked LLM review flow (fixed reviewer identity LLM_ASSISTED_SECOND_PASS,
never gpt-5.6-sol), and the audit artifacts contract.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

import scripts.corpus_v2_review as rv

# ── synthetic fixtures ────────────────────────────────────────────────

CHUNK_TEXT_1 = ("X is defined as Y in the spec. Additional trailing text "
                "that extends the chunk beyond the snippet boundary.")
CHUNK_TEXT_2 = ("The component mounts when the page loads, and unmounts "
                "when the page is destroyed. Lifecycle notes follow.")


def _annotation() -> dict:
    return {
        "annotated_by": "mock-draft", "annotation_version": "v2-draft",
        "created_at": "", "review_notes": "LLM_ASSISTED",
        "review_status": "pending", "reviewed_by": "",
    }


def _base_case(cid: str, query: str, **over) -> dict:
    case = {
        "id": cid, "query": query, "language": "en",
        "query_type": "single_fact", "should_refuse": False,
        "is_refusal_turn": None, "relevance_level": "chunk",
        "doc_target": "", "note": "",
        "acceptable_answer_points": ["X is defined as Y."],
        "relevant_source_ids": ["src-a"], "relevant_chunk_ids": ["chunk-1"],
        "relevant_chunks": [{
            "chunk_id": "chunk-1",
            "chunk_text_snippet": "X is defined as Y in the spec.",
            "source_id": "src-a", "page": "", "section": "",
        }],
        "annotation": _annotation(),
        "metadata": {"chain_id": None, "follow_up_to": None, "turn": 1,
                     "difficulty": "easy", "band_target": "B",
                     "construction": "seed"},
    }
    case.update(over)
    return case


@pytest.fixture
def synthetic(tmp_path: Path) -> dict[str, Path]:
    """4-case draft: single_fact, multi-turn pair, refusal no_answer."""
    cases = [
        _base_case("t-001", "What is X?"),
        _base_case(
            "t-002", "Why does X appear twice?", query_type="multi_turn",
            metadata={"chain_id": "t-002", "follow_up_to": None, "turn": 1,
                      "difficulty": "medium", "band_target": "B",
                      "construction": "chain"},
            acceptable_answer_points=["The spec mentions X twice."],
            relevant_chunks=[{
                "chunk_id": "chunk-2",
                "chunk_text_snippet": "The component mounts when the page "
                                      "loads, and unmounts when the page is "
                                      "destroyed.",
                "source_id": "src-b", "page": "", "section": "",
            }], relevant_chunk_ids=["chunk-2"], relevant_source_ids=["src-b"],
        ),
        _base_case(
            "t-003", "And after it unmounts, what happens to its state?",
            query_type="multi_turn",
            metadata={"chain_id": "t-002", "follow_up_to": "t-002", "turn": 2,
                      "difficulty": "medium", "band_target": "B",
                      "construction": "chain"},
            acceptable_answer_points=["State is discarded on unmount."],
            relevant_chunks=[{
                "chunk_id": "chunk-2",
                "chunk_text_snippet": "The component mounts when the page "
                                      "loads, and unmounts when the page is "
                                      "destroyed.",
                "source_id": "src-b", "page": "", "section": "",
            }], relevant_chunk_ids=["chunk-2"], relevant_source_ids=["src-b"],
        ),
        _base_case(
            "t-004", "What is the password to the staging server?",
            query_type="no_answer", should_refuse=True,
            is_refusal_turn=True, relevance_level="none",
            acceptable_answer_points=[], relevant_source_ids=[],
            relevant_chunk_ids=[], relevant_chunks=[],
        ),
    ]
    draft = tmp_path / "draft.jsonl"
    draft.write_text(
        "\n".join(json.dumps(c, ensure_ascii=False) for c in cases) + "\n",
        encoding="utf-8")
    chunks = tmp_path / "chunks.jsonl"
    chunks.write_text(
        "\n".join([
            json.dumps({"chunk_id": "chunk-1", "index": 0,
                        "source": "src-a", "text": CHUNK_TEXT_1},
                       ensure_ascii=False),
            json.dumps({"chunk_id": "chunk-2", "index": 0,
                        "source": "src-b", "text": CHUNK_TEXT_2},
                       ensure_ascii=False),
        ]) + "\n", encoding="utf-8")
    manifest = tmp_path / "chunk-manifest.json"
    manifest.write_text(json.dumps({"n_chunks": 2, "corpus_version": "v2"}) + "\n",
                        encoding="utf-8")
    return {"tmp": tmp_path, "draft": draft, "chunks": chunks,
            "manifest": manifest, "out": tmp_path / "review"}


def _fake_llm(decision: str, category: str | None = None):
    """Build a fake llm_fn returning one canned decision for every case."""
    cat = [] if category is None else [category]

    def fake(call_type: str, messages: list[dict], model: str | None = None,
             **kwargs):
        assert model != "gpt-5.6-sol", "禁止使用 gpt-5.6-sol"
        payload = {"decision": decision, "confidence": "high",
                   "rationale": f"mock: {decision}",
                   "issue_categories": cat}
        return (SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(
            content=json.dumps(payload, ensure_ascii=False)))]), None)

    return fake


def _build_pack(synth) -> tuple[Path, Path]:
    out = rv.build_pack(draft_path=synth["draft"], chunks_path=synth["chunks"],
                        chunk_manifest_path=synth["manifest"],
                        out_dir=synth["out"])
    return out, out.with_name("evidence-review-pack-manifest.json")


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


# ── pack: determinism / schema / no split identity ────────────────────

def test_pack_schema_has_no_split_identity(synthetic):
    pack, _ = _build_pack(synthetic)
    rows = [json.loads(l) for l in pack.open(encoding="utf-8") if l.strip()]
    assert len(rows) == 4
    assert {r["case_id"] for r in rows} == {"t-001", "t-002", "t-003", "t-004"}
    expected = {"case_id", "query", "language", "query_type", "turn",
                "previous_turns", "draft", "evidence", "evidence_sha256"}
    for r in rows:
        assert set(r) == expected
        assert set(r["draft"]) == {"should_refuse", "is_refusal_turn",
                                   "relevance_level", "doc_target", "note",
                                   "acceptable_answer_points"}
        for ev in r["evidence"]:
            assert set(ev) == {"chunk_id", "source_id", "snippet",
                               "snippet_sha256", "chunk_text_sha256",
                               "chunk_text"}
        payload = {k: v for k, v in r.items() if k != "evidence_sha256"}
        assert r["evidence_sha256"] == rv.canonical_sha(payload)


def test_pack_deterministic_bytes(synthetic):
    pack1, _ = _build_pack(synthetic)
    pack2, _ = _build_pack(synthetic)
    assert pack1.read_bytes() == pack2.read_bytes()
    rows = [json.loads(l) for l in pack1.open(encoding="utf-8") if l.strip()]
    assert [r["case_id"] for r in rows] == sorted(r["case_id"] for r in rows)


def test_pack_manifest_records_input_shas(synthetic):
    _, mf = _build_pack(synthetic)
    m = json.loads(mf.read_text(encoding="utf-8"))
    assert m["n_cases"] == 4
    assert m["inputs"]["draft"]["sha256"] == _sha(synthetic["draft"])
    assert m["inputs"]["chunks"]["sha256"] == _sha(synthetic["chunks"])
    assert m["inputs"]["chunk_manifest"]["sha256"] == _sha(synthetic["manifest"])
    assert m["reviewer_identity"] == "LLM_ASSISTED_SECOND_PASS"
    assert not any(k in m for k in ("dev", "holdout", "split"))


def test_pack_includes_previous_turns_for_multi_turn(synthetic):
    pack, _ = _build_pack(synthetic)
    rows = {json.loads(l)["case_id"]: json.loads(l)
            for l in pack.open(encoding="utf-8") if l.strip()}
    t3 = rows["t-003"]
    assert t3["turn"] == 2
    assert [p["case_id"] for p in t3["previous_turns"]] == ["t-002"]
    assert rows["t-001"]["previous_turns"] == []


# ── pack: fail-closed ─────────────────────────────────────────────────

def test_pack_fails_on_missing_chunk(synthetic):
    cases = [json.loads(l) for l in
             synthetic["draft"].open(encoding="utf-8") if l.strip()]
    cases[0]["relevant_chunks"][0]["chunk_id"] = "chunk-missing"
    synthetic["draft"].write_text(
        "\n".join(json.dumps(c, ensure_ascii=False) for c in cases) + "\n",
        encoding="utf-8")
    with pytest.raises(ValueError, match="chunk-missing"):
        rv.build_pack(synthetic["draft"], synthetic["chunks"],
                      synthetic["manifest"], synthetic["out"])


def test_pack_fails_on_non_contiguous_snippet(synthetic):
    cases = [json.loads(l) for l in
             synthetic["draft"].open(encoding="utf-8") if l.strip()]
    cases[0]["relevant_chunks"][0]["chunk_text_snippet"] = (
        "unrelated text not in the chunk")
    synthetic["draft"].write_text(
        "\n".join(json.dumps(c, ensure_ascii=False) for c in cases) + "\n",
        encoding="utf-8")
    with pytest.raises(ValueError, match="evidence"):
        rv.build_pack(synthetic["draft"], synthetic["chunks"],
                      synthetic["manifest"], synthetic["out"])


def test_pack_fails_on_broken_multi_turn_chain(synthetic):
    cases = [json.loads(l) for l in
             synthetic["draft"].open(encoding="utf-8") if l.strip()]
    for c in cases:
        if c["id"] == "t-003":
            c["metadata"]["follow_up_to"] = "t-999"
    synthetic["draft"].write_text(
        "\n".join(json.dumps(c, ensure_ascii=False) for c in cases) + "\n",
        encoding="utf-8")
    with pytest.raises(ValueError, match="t-999"):
        rv.build_pack(synthetic["draft"], synthetic["chunks"],
                      synthetic["manifest"], synthetic["out"])


def test_pack_rejects_duplicate_case_ids(synthetic):
    cases = [json.loads(l) for l in
             synthetic["draft"].open(encoding="utf-8") if l.strip()]
    cases.append(dict(cases[0], query="duplicate"))
    synthetic["draft"].write_text(
        "\n".join(json.dumps(c, ensure_ascii=False) for c in cases) + "\n",
        encoding="utf-8")
    with pytest.raises(ValueError, match="duplicate"):
        rv.build_pack(synthetic["draft"], synthetic["chunks"],
                      synthetic["manifest"], synthetic["out"])


# ── review: mocked LLM ────────────────────────────────────────────────

def test_review_all_confirmed_writes_complete_artifacts(synthetic):
    pack, mf = _build_pack(synthetic)
    out = synthetic["out"]
    rc = rv.review(pack, mf, out_dir=out, model="deepseek-chat",
                   llm_fn=_fake_llm("confirmed"))
    assert rc == 0
    rows = [json.loads(l) for l in (out / "auto-review.jsonl").open(
        encoding="utf-8") if l.strip()]
    assert len(rows) == 4
    for r in rows:
        assert r["decision"] == "confirmed"
        assert r["reviewer_identity"] == "LLM_ASSISTED_SECOND_PASS"
        assert r["evidence_sha256"]
    report = (out / "auto-review-evidence-report.md").read_text(encoding="utf-8")
    assert "LLM-assisted candidate review complete" in report
    assert not (out / "auto-review-fixlist.jsonl").exists()


def test_review_mixed_outcomes_writes_fixlist_and_leaves_draft_untouched(
        synthetic):
    pack, mf = _build_pack(synthetic)
    draft_before = synthetic["draft"].read_bytes()
    decisions = {"t-001": "confirmed", "t-002": "reject",
                 "t-003": "confirmed", "t-004": "needs_followup"}

    def fake(call_type, messages, model=None, **kwargs):
        assert model != "gpt-5.6-sol"
        case_id = json.loads(messages[-1]["content"])["case_id"]
        payload = {"decision": decisions[case_id], "confidence": "medium",
                   "rationale": f"mock: {decisions[case_id]}",
                   "issue_categories": ["chunk_source_relevance"]}
        return (SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(
            content=json.dumps(payload, ensure_ascii=False)))]), None)

    out = synthetic["out"]
    rc = rv.review(pack, mf, out_dir=out, model="deepseek-chat", llm_fn=fake)
    assert rc == 0
    report = (out / "auto-review-evidence-report.md").read_text(encoding="utf-8")
    assert "LLM-assisted candidate review complete" not in report
    assert "t-002" in report and "t-004" in report
    fix = [json.loads(l) for l in (out / "auto-review-fixlist.jsonl").open(
        encoding="utf-8") if l.strip()]
    assert {f["case_id"] for f in fix} == {"t-002", "t-004"}
    # 原始草稿绝对不得被改写
    assert synthetic["draft"].read_bytes() == draft_before


def test_review_fails_closed_on_invalid_decision(synthetic):
    pack, mf = _build_pack(synthetic)
    out = synthetic["out"]
    with pytest.raises(rv.ReviewError, match="invalid decision"):
        rv.review(pack, mf, out_dir=out, model="deepseek-chat",
                  llm_fn=_fake_llm("maybe"))
    assert not (out / "auto-review.jsonl").exists()
    assert not (out / "auto-review-evidence-report.md").exists()


def test_review_rejects_forbidden_model(synthetic):
    pack, mf = _build_pack(synthetic)
    with pytest.raises(ValueError, match="gpt-5.6-sol"):
        rv.review(pack, mf, out_dir=synthetic["out"],
                  model="gpt-5.6-sol", llm_fn=_fake_llm("confirmed"))


def test_review_fails_on_llm_call_error(synthetic):
    pack, mf = _build_pack(synthetic)

    def boom(call_type, messages, model=None, **kwargs):
        raise rv.ReviewError("mock llm failure")

    with pytest.raises(rv.ReviewError, match="mock llm failure"):
        rv.review(pack, mf, out_dir=synthetic["out"], model="deepseek-chat",
                  llm_fn=boom)
    assert not (synthetic["out"] / "auto-review.jsonl").exists()


# ── verify: drift detection ───────────────────────────────────────────

def test_verify_detects_draft_rewrite(synthetic):
    pack, mf = _build_pack(synthetic)
    out = synthetic["out"]
    rv.review(pack, mf, out_dir=out, model="deepseek-chat",
              llm_fn=_fake_llm("confirmed"))
    # 改写草稿（模拟原始草稿被篡改）
    text = synthetic["draft"].read_text(encoding="utf-8")
    synthetic["draft"].write_text(text.replace("What is X?", "What is Z?"),
                                  encoding="utf-8")
    errors = rv.verify(pack, mf, draft_path=synthetic["draft"],
                       chunks_path=synthetic["chunks"],
                       auto_path=out / "auto-review.jsonl")
    assert any("draft" in e and "sha256" in e for e in errors)


def test_verify_detects_pack_tamper(synthetic):
    pack, mf = _build_pack(synthetic)
    out = synthetic["out"]
    rv.review(pack, mf, out_dir=out, model="deepseek-chat",
              llm_fn=_fake_llm("confirmed"))
    rows = [json.loads(l) for l in pack.open(encoding="utf-8") if l.strip()]
    rows[0]["evidence_sha256"] = "0" * 64
    pack.write_text("\n".join(json.dumps(r, ensure_ascii=False)
                              for r in rows) + "\n", encoding="utf-8")
    errors = rv.verify(pack, mf, draft_path=synthetic["draft"],
                       chunks_path=synthetic["chunks"],
                       auto_path=out / "auto-review.jsonl")
    assert any("evidence" in e for e in errors)


def test_verify_detects_reviewer_identity_spoof(synthetic):
    pack, mf = _build_pack(synthetic)
    out = synthetic["out"]
    rv.review(pack, mf, out_dir=out, model="deepseek-chat",
              llm_fn=_fake_llm("confirmed"))
    rows = [json.loads(l) for l in (out / "auto-review.jsonl").open(
        encoding="utf-8") if l.strip()]
    rows[0]["reviewer_identity"] = "HUMAN_REVIEW"
    (out / "auto-review.jsonl").write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n",
        encoding="utf-8")
    errors = rv.verify(pack, mf, draft_path=synthetic["draft"],
                       chunks_path=synthetic["chunks"],
                       auto_path=out / "auto-review.jsonl")
    assert any("identity" in e for e in errors)


# ── real corpus pack (no LLM, offline, fast) ──────────────────────────

def test_real_corpus_pack_builds_150_cases(tmp_path: Path):
    # 只写临时目录：历史 review 产物保持只读（Task 12 后草稿已变，重生成
    # 产物与历史字节不同，不得覆盖历史 evidence-review-pack）
    out = tmp_path / "out"
    pack = rv.build_pack(draft_path=rv.DEFAULT_DRAFT,
                         chunks_path=rv.DEFAULT_CHUNKS,
                         chunk_manifest_path=rv.DEFAULT_CHUNK_MANIFEST,
                         out_dir=out)
    rows = [json.loads(l) for l in pack.open(encoding="utf-8") if l.strip()]
    assert len(rows) == 150
    draft_ids = {json.loads(l)["id"] for l in
                 rv.DEFAULT_DRAFT.open(encoding="utf-8") if l.strip()}
    assert {r["case_id"] for r in rows} == draft_ids
    n_evidence = sum(len(r["evidence"]) for r in rows)
    assert n_evidence >= 146  # 与 evidence 报告一致（>=，因可能含无 snippet 引用）
