"""Tests for the v2 persistent-reject minimal evidence repair (Task 12).

Covers the five approved precise transformations, fail-closed input
validation, byte-preservation of the other 145 draft rows, evidence
verification, versioned revision artifacts, determinism, data-quality
checks and (on real corpora) blank-pack regeneration + freeze/lock
stability.  No LLM/API, no network, no split identity.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import scripts.corpus_v2_persistent_reject_repair as rp

# ── synthetic world ────────────────────────────────────────────────────

# The three new-evidence chunks are built by padding so the spec's expected
# char ranges are exact (unit-testing the range verification logic); the
# real-corpus tests re-verify against the real chunks.jsonl.
SNIPPET_M014 = ("记住，使用\n```\nfrom package import specific_submodule\n```\n"
                " 没有任何问题！ 实际上，除了导入模块使用不同包的同名子模块"
                "之外，这种方式是推荐用法。")
SNIPPET_E055 = ("The `&s1` syntax lets us create a reference that _refers_ to "
                "the value of `s1`\nbut does not own it.")
CORE_M014 = "from package import specific_submodule"
CORE_E055 = "The `&s1` syntax lets us create a reference"
CORE_M016 = "parameter -- 形参"

PAD_M014 = "甲" * 311          # snippet starts at 311, core at 321..359
PAD_E055 = "a" * 1424          # snippet starts at 1424, core at 1424..1467
PAD_M016 = "b" * 783           # core at 783..798

CHUNK_38_TEXT = PAD_M014 + SNIPPET_M014 + "后缀文本。"
CHUNK_49_TEXT = PAD_E055 + SNIPPET_E055 + " suffix."
CHUNK_14_TEXT = PAD_M016 + CORE_M016 + "¶ 词条正文。"

CHUNK_FIXTURES: dict[str, tuple[str, str]] = {
    "gen_0": ("python-tutorial-zh.md", "generic evidence text one."),
    "32c427fb50e2_chunk_31": (
        "python-tutorial-zh.md",
        "大多数情况下，不要用这个功能，这种方式向解释器导入了一批未知的名称。"),
    "32c427fb50e2_chunk_2": ("python-tutorial-zh.md", "# 3. Python 速览¶"),
    "e564a122a7a2_chunk_5": ("python-tutorial-en.md",
                             "3. An Informal Introduction to Python"),
    "761b22915b5e_chunk_12": (
        "postgresql-tutorial.md",
        "A transactional database guarantees that all the updates made by a "
        "transaction are logged in permanent storage"),
    "4f9001ca8c15_chunk_37": (
        "rust-book-core.md",
        "### Ownership Rules\n\nFirst, let's take a look at the ownership "
        "rules. Keep these rules in mind as we work through the examples "
        "that illustrate them:"),
    "4f9001ca8c15_chunk_48": (
        "rust-book-core.md",
        "A reference is like a pointer in that it's an address we can follow "
        "to access the data stored at that address; that data is owned by "
        "some other variable."),
    "c9fd20815ea8_chunk_1": (
        "python-glossary-zh.md",
        "参数会被赋值给函数体中对应的局部变量。 另参见 parameter 术语表条目"),
    "32c427fb50e2_chunk_38": ("python-tutorial-zh.md", CHUNK_38_TEXT),
    "4f9001ca8c15_chunk_49": ("rust-book-core.md", CHUNK_49_TEXT),
    "c9fd20815ea8_chunk_14": ("python-glossary-zh.md", CHUNK_14_TEXT),
}

TARGETS = list(rp.TARGET_CASE_IDS)

# 150 synthetic ids: en-001..060, mixed-001..040, zh-001..030, multi-001..020
def _all_ids() -> list[str]:
    ids: list[str] = []
    for prefix, n in (("en", 60), ("mixed", 40), ("zh", 30), ("multi", 20)):
        ids += [f"{prefix}-{i:03d}" for i in range(1, n + 1)]
    return ids


def _chunk_ref(cid: str, snippet: str, section: str | None = None):
    source, _ = CHUNK_FIXTURES[cid]
    return {"source_id": source, "chunk_id": cid,
            "chunk_text_snippet": snippet, "page": None, "section": section}


def _make_case(cid: str, i: int, *, points: list[str] | None = None,
               chunks: list[dict] | None = None,
               language: str = "en", qtype: str = "single_fact") -> dict:
    chunks = chunks or [_chunk_ref("gen_0", "generic evidence text one.")]
    return {
        "id": cid,
        "query": f"query number {i}?",
        "query_type": qtype,
        "language": language,
        "relevant_source_ids": sorted({c["source_id"] for c in chunks}),
        "relevant_chunks": chunks,
        "relevant_chunk_ids": [c["chunk_id"] for c in chunks],
        "acceptable_answer_points": points or [f"point {i} a", f"point {i} b"],
        "should_refuse": False,
        "relevance_level": "chunk",
        "metadata": {
            "difficulty": "medium", "band_target": "normal",
            "construction": "natural", "turn": 1, "follow_up_to": None,
            "chain_id": None,
        },
        "annotation": {
            "annotated_by": "zcode-draft", "reviewed_by": "",
            "review_status": "pending", "review_notes": "LLM_ASSISTED",
            "annotation_version": "v2.0.0", "created_at": "2026-08-05",
        },
        "doc_target": None, "note": "", "is_refusal_turn": False,
    }


def _target_case(cid: str, i: int) -> dict:
    """Draft rows for the five targets (structure mirrors the real draft)."""
    if cid == "multi-014":
        return _make_case(cid, i, language="zh", qtype="multi_turn",
                          points=["尽量不要使用 from ... import *",
                                  "建议使用 from package import specific_submodule"],
                          chunks=[_chunk_ref(
                              "32c427fb50e2_chunk_31",
                              "大多数情况下，不要用这个功能",
                              "6.1.1 以脚本方式执行模块")])
    if cid == "mixed-026":
        return _make_case(cid, i, language="mixed", qtype="cross_document",
                          points=["对应：同一章，标题翻译不同",
                                  "内容均为非正式介绍（计算器、字符串、列表示例）"],
                          chunks=[_chunk_ref("32c427fb50e2_chunk_2",
                                             "# 3. Python 速览¶", "3. Python 速览"),
                                  _chunk_ref("e564a122a7a2_chunk_5",
                                             "3. An Informal Introduction to Python",
                                             "3. An Informal Introduction to Python")])
    if cid == "en-052":
        return _make_case(cid, i, qtype="cross_document",
                          points=["PostgreSQL: transaction durability (logged to disk)",
                                  "Rust: ownership rules guarantee memory safety"],
                          chunks=[_chunk_ref(
                              "761b22915b5e_chunk_12",
                              "A transactional database guarantees that all the "
                              "updates made by a transaction are logged in "
                              "permanent storage", "3.4 Transactions"),
                              _chunk_ref("4f9001ca8c15_chunk_37",
                                         "### Ownership Rules\n\nFirst, let's "
                                         "take a look at the ownership rules.",
                                         "4.1 What Is Ownership")])
    if cid == "en-055":
        return _make_case(cid, i, qtype="mixed_intent",
                          points=["& 运算符（借用/引用）"],
                          chunks=[_chunk_ref(
                              "4f9001ca8c15_chunk_48",
                              "A reference is like a pointer in that it's an "
                              "address we can follow to access the data stored "
                              "at that address; that data is owned by some "
                              "other variable.", "4.2 References and Borrowing")])
    if cid == "mixed-016":
        return _make_case(cid, i, language="mixed",
                          points=["argument 译为 参数",
                                  "parameter 为另一术语表条目（形参）"],
                          chunks=[_chunk_ref(
                              "c9fd20815ea8_chunk_1",
                              "参数会被赋值给函数体中对应的局部变量。",
                              "argument 参数")])
    raise AssertionError(cid)


def _write_chunks(tmp_path: Path) -> Path:
    p = tmp_path / "chunks.jsonl"
    lines = [json.dumps({"chunk_id": cid, "index": n, "source": src,
                         "text": text}, ensure_ascii=False)
             for n, (cid, (src, text)) in enumerate(CHUNK_FIXTURES.items())]
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return p


def _write_draft(tmp_path: Path) -> Path:
    rows = []
    for n, cid in enumerate(_all_ids(), start=1):
        if cid in TARGETS:
            rows.append(_target_case(cid, n))
        else:
            rows.append(_make_case(cid, n))
    p = tmp_path / "v2-cases-draft.jsonl"
    p.write_text("\n".join(json.dumps(r, ensure_ascii=False)
                           for r in rows) + "\n", encoding="utf-8")
    return p


def _write_merged_sel(tmp_path: Path) -> tuple[Path, Path]:
    """merged reject set == the five targets; others confirmed."""
    mapping = [{"index": i, "case_id": cid}
               for i, cid in enumerate(_all_ids(), start=1)]
    sel = {"total_cases": len(mapping), "mapping": mapping}
    sel_p = tmp_path / "selection-manifest.json"
    sel_p.write_text(json.dumps(sel, ensure_ascii=False) + "\n",
                     encoding="utf-8")
    by_index = {m["index"]: m["case_id"] for m in mapping}
    rows = []
    for i, cid in by_index.items():
        verdict = "reject" if cid in TARGETS else "confirmed"
        rows.append({"index": i, "semantic_verdict": verdict,
                     "verdict_rationale": "r", "answer_point_supports": []})
    merged_p = tmp_path / "merged-adjudications.jsonl"
    merged_p.write_text("\n".join(json.dumps(r) for r in rows) + "\n",
                        encoding="utf-8")
    return merged_p, sel_p


def _write_audit_manifest(tmp_path: Path, chunks_p: Path, merged_p: Path,
                          sel_p: Path) -> Path:
    def sha(p: Path) -> str:
        import hashlib
        return hashlib.sha256(p.read_bytes()).hexdigest()
    m = {
        "task": "persistent-reject-evidence-audit",
        "target_case_ids": TARGETS,
        "inputs": {
            "merged-adjudications.jsonl": {"sha256": sha(merged_p)},
            "selection-manifest.json": {"sha256": sha(sel_p)},
            "chunks.jsonl": {"sha256": sha(chunks_p)},
        },
        "validation": {"reject_set_matches_target": True},
    }
    p = tmp_path / "audit-manifest.json"
    p.write_text(json.dumps(m, ensure_ascii=False) + "\n", encoding="utf-8")
    return p


@pytest.fixture
def world(tmp_path: Path):
    chunks_p = _write_chunks(tmp_path)
    draft_p = _write_draft(tmp_path)
    merged_p, sel_p = _write_merged_sel(tmp_path)
    audit_p = _write_audit_manifest(tmp_path, chunks_p, merged_p, sel_p)
    return {"tmp": tmp_path, "chunks": chunks_p, "draft": draft_p,
            "merged": merged_p, "sel": sel_p, "audit": audit_p}


def _fixture_chunks():
    """Fixture chunks/sources maps（合成世界）。"""
    return ({cid: text for cid, (src, text) in CHUNK_FIXTURES.items()},
            {cid: src for cid, (src, text) in CHUNK_FIXTURES.items()})


def _refresh_audit_chunks_sha(world: dict) -> None:
    """篡改 chunks 后同步审计 manifest 的 chunks SHA（保持其他校验独立）。"""
    import hashlib
    m = json.loads(world["audit"].read_text(encoding="utf-8"))
    m["inputs"]["chunks.jsonl"]["sha256"] = hashlib.sha256(
        world["chunks"].read_bytes()).hexdigest()
    world["audit"].write_text(json.dumps(m, ensure_ascii=False) + "\n",
                              encoding="utf-8")


def _transform(world: dict) -> dict:
    return rp.transform(world["draft"], world["chunks"], world["audit"],
                        world["merged"], world["sel"],
                        revision_dir=world["tmp"] / "rev")


# ── 五条精确变换 ──────────────────────────────────────────────────────

class TestTransform:
    def test_multi_014_keeps_answer_points_and_adds_evidence(self, world):
        out = _transform(world)
        case = out["cases_by_id"]["multi-014"]
        assert case["acceptable_answer_points"] == [
            "尽量不要使用 from ... import *",
            "建议使用 from package import specific_submodule"]
        assert "32c427fb50e2_chunk_38" in case["relevant_chunk_ids"]
        assert case["relevant_chunk_ids"] == [
            "32c427fb50e2_chunk_31", "32c427fb50e2_chunk_38"]
        added = case["relevant_chunks"][-1]
        assert added["chunk_id"] == "32c427fb50e2_chunk_38"
        assert added["source_id"] == "python-tutorial-zh.md"
        assert added["section"] == "6.4.1 从包中导入 *"
        assert added["chunk_text_snippet"] == SNIPPET_M014

    def test_mixed_026_removes_unsupported_point(self, world):
        out = _transform(world)
        case = out["cases_by_id"]["mixed-026"]
        assert case["acceptable_answer_points"] == ["对应：同一章，标题翻译不同"]
        assert case["relevant_chunk_ids"] == [
            "32c427fb50e2_chunk_2", "e564a122a7a2_chunk_5"]

    def test_en_052_removes_unsupported_point(self, world):
        out = _transform(world)
        case = out["cases_by_id"]["en-052"]
        assert case["acceptable_answer_points"] == [
            "PostgreSQL: transaction durability (logged to disk)"]

    def test_en_055_narrowed_with_operator_evidence(self, world):
        out = _transform(world)
        case = out["cases_by_id"]["en-055"]
        assert case["acceptable_answer_points"] == [
            "The `&` operator creates a reference (e.g., `&s1`)"]
        assert "4f9001ca8c15_chunk_49" in case["relevant_chunk_ids"]
        added = case["relevant_chunks"][-1]
        assert added["source_id"] == "rust-book-core.md"
        assert added["chunk_text_snippet"] == SNIPPET_E055

    def test_mixed_016_glossary_form_both_terms(self, world):
        out = _transform(world)
        case = out["cases_by_id"]["mixed-016"]
        assert case["acceptable_answer_points"] == ["argument — 参数",
                                                    "parameter — 形参"]
        assert "c9fd20815ea8_chunk_1" in case["relevant_chunk_ids"]
        assert "c9fd20815ea8_chunk_14" in case["relevant_chunk_ids"]
        added = case["relevant_chunks"][-1]
        assert added["chunk_id"] == "c9fd20815ea8_chunk_14"
        assert added["chunk_text_snippet"] == "parameter -- 形参"
        assert added["section"] == "parameter 形参"

    def test_non_target_rows_byte_identical(self, world):
        out = _transform(world)
        orig_lines = [l for l in world["draft"].read_bytes().split(b"\r\n")
                      if l.strip()]
        new_lines = [l for l in out["bytes"].split(b"\r\n") if l.strip()]
        assert len(orig_lines) == len(new_lines) == 150
        for old, new in zip(orig_lines, new_lines):
            cid = json.loads(old)["id"]
            if cid not in TARGETS:
                assert old == new, f"non-target row changed: {cid}"

    def test_preserved_fields_unchanged(self, world):
        old_rows = {r["id"]: r for r in
                    [json.loads(l) for l in
                     world["draft"].read_text(encoding="utf-8").splitlines()
                     if l.strip()]}
        out = _transform(world)
        for cid in TARGETS:
            before, after = old_rows[cid], out["cases_by_id"][cid]
            assert after["id"] == before["id"]
            assert after["query"] == before["query"]
            assert after["language"] == before["language"]
            assert after["query_type"] == before["query_type"]
            assert after["should_refuse"] == before["should_refuse"]
            assert after["relevant_source_ids"] == before["relevant_source_ids"]
            assert after["metadata"]["difficulty"] == \
                before["metadata"]["difficulty"]
            assert after["metadata"]["chain_id"] == \
                before["metadata"]["chain_id"]
            assert after["metadata"]["follow_up_to"] == \
                before["metadata"]["follow_up_to"]

    def test_evidence_verification_records_ranges(self, world):
        out = _transform(world)
        ev = out["evidence_verification"]
        by_chunk = {e["chunk_id"]: e for e in ev}
        assert by_chunk["32c427fb50e2_chunk_38"]["char_start"] == 321
        assert by_chunk["32c427fb50e2_chunk_38"]["char_end"] == 359
        assert by_chunk["4f9001ca8c15_chunk_49"]["char_start"] == 1424
        assert by_chunk["4f9001ca8c15_chunk_49"]["char_end"] == 1467
        assert by_chunk["c9fd20815ea8_chunk_14"]["char_start"] == 783
        assert by_chunk["c9fd20815ea8_chunk_14"]["char_end"] == 798
        for e in ev:
            assert e["snippet_is_evidence"] is True
            assert e["core_located_once"] is True
            assert e["source_matches"] is True

    def test_multi_014_evidence_maps_to_second_answer_point(self, world):
        out = _transform(world)
        ev = out["evidence_verification"]
        m014 = [e for e in ev if e["case_id"] == "multi-014"][0]
        assert m014["answer_point_index"] == 1

    def test_chunk_missing_fails(self, world):
        chunks_p = world["chunks"]
        text = chunks_p.read_text(encoding="utf-8")
        text = "\n".join(l for l in text.splitlines()
                         if '"32c427fb50e2_chunk_38"' not in l) + "\n"
        chunks_p.write_text(text, encoding="utf-8")
        with pytest.raises(rp.RepairError, match="chunk"):
            _transform(world)

    def test_source_mismatch_fails(self, world):
        chunks_p = world["chunks"]
        # 只改新增证据 chunk_38 所在行的 source（其余行不动）
        lines = [l for l in chunks_p.read_text(encoding="utf-8").splitlines()
                 if l.strip()]
        for i, l in enumerate(lines):
            if '"32c427fb50e2_chunk_38"' in l:
                lines[i] = l.replace('"source": "python-tutorial-zh.md"',
                                     '"source": "wrong-source.md"')
                break
        chunks_p.write_text("\n".join(lines) + "\n", encoding="utf-8")
        _refresh_audit_chunks_sha(world)
        with pytest.raises(rp.RepairError, match="source"):
            _transform(world)

    def test_core_range_mismatch_fails(self, world):
        chunks_p = world["chunks"]
        text = chunks_p.read_text(encoding="utf-8")
        # 破坏 chunk_38 的文本，使 core 位置偏移
        text = text.replace(PAD_M014, "甲" * 312, 1)
        chunks_p.write_text(text, encoding="utf-8")
        _refresh_audit_chunks_sha(world)
        with pytest.raises(rp.RepairError, match="范围|range|偏移"):
            _transform(world)


# ── fail-closed 输入校验 ──────────────────────────────────────────────

class TestFailClosed:
    def test_reject_set_mismatch_fails(self, world):
        merged_p = world["merged"]
        rows = [json.loads(l) for l in
                merged_p.read_text(encoding="utf-8").splitlines() if l.strip()]
        rows[0]["semantic_verdict"] = "reject"  # 加入非目标 reject
        merged_p.write_text("\n".join(json.dumps(r) for r in rows) + "\n",
                            encoding="utf-8")
        with pytest.raises(rp.RepairError, match="reject"):
            _transform(world)

    def test_audit_manifest_sha_drift_fails(self, world):
        chunks_p = world["chunks"]
        # 合法 JSON 但内容变化（避免解析错误）：改一个 chunk 的文本
        lines = [l for l in chunks_p.read_text(encoding="utf-8").splitlines()
                 if l.strip()]
        lines[0] = lines[0].replace("generic evidence text one.",
                                    "generic evidence text changed.")
        chunks_p.write_text("\n".join(lines) + "\n", encoding="utf-8")
        with pytest.raises(rp.RepairError, match="SHA|sha|漂移"):
            _transform(world)

    def test_draft_row_count_mismatch_fails(self, world):
        draft_p = world["draft"]
        first = draft_p.read_text(encoding="utf-8").splitlines()[0]
        draft_p.write_text(draft_p.read_text(encoding="utf-8") + first + "\n",
                           encoding="utf-8")
        with pytest.raises(rp.RepairError, match="行数"):
            _transform(world)

    def test_duplicate_ids_fail(self, world):
        draft_p = world["draft"]
        lines = [l for l in draft_p.read_text(encoding="utf-8").splitlines()
                 if l.strip()]
        # 用 en-001 的副本替换 en-002 的行：150 行但 id 重复
        for i, l in enumerate(lines):
            if json.loads(l)["id"] == "en-002":
                lines[i] = lines[0]
                break
        draft_p.write_text("\n".join(lines) + "\n", encoding="utf-8")
        with pytest.raises(rp.RepairError, match="重复|duplicate"):
            _transform(world)

    def test_target_missing_from_draft_fails(self, world):
        draft_p = world["draft"]
        lines = [l for l in draft_p.read_text(encoding="utf-8").splitlines()
                 if l.strip()]
        lines = [l for l in lines
                 if json.loads(l)["id"] != "multi-014"]
        draft_p.write_text("\n".join(lines) + "\n", encoding="utf-8")
        with pytest.raises(rp.RepairError):
            _transform(world)

    def test_audit_target_set_mismatch_fails(self, world):
        audit_p = world["audit"]
        m = json.loads(audit_p.read_text(encoding="utf-8"))
        m["target_case_ids"] = ["en-001"]
        audit_p.write_text(json.dumps(m, ensure_ascii=False) + "\n",
                           encoding="utf-8")
        with pytest.raises(rp.RepairError):
            _transform(world)

    def test_fail_closed_produces_no_draft_change(self, world):
        before = world["draft"].read_bytes()
        try:
            _transform(world)
        except rp.RepairError:
            pass
        assert world["draft"].read_bytes() == before


# ── 版本化修复目录与确定性 ───────────────────────────────────────────

class TestRevisionArtifacts:
    def test_revision_dir_snapshots(self, world):
        out = _transform(world)
        rev_dir = out["revision_dir"]
        assert (rev_dir / "draft-before.jsonl").read_bytes() == \
            world["draft"].read_bytes()
        assert (rev_dir / "draft-after.jsonl").read_bytes() == out["bytes"]
        diff_rows = [json.loads(l) for l in
                     (rev_dir / "draft-field-diff.jsonl")
                     .read_text(encoding="utf-8").splitlines() if l.strip()]
        assert len(diff_rows) == 5
        assert {r["case_id"] for r in diff_rows} == set(TARGETS)
        m014 = next(r for r in diff_rows if r["case_id"] == "multi-014")
        assert "relevant_chunk_ids" in m014["changed_fields"]
        assert "acceptable_answer_points" not in m014["changed_fields"]
        ev = [json.loads(l) for l in
              (rev_dir / "evidence-verification.jsonl")
              .read_text(encoding="utf-8").splitlines() if l.strip()]
        assert len(ev) == 3

    def test_deterministic_rebuild(self, world):
        out1 = _transform(world)
        out2 = _transform(world)
        assert out1["bytes"] == out2["bytes"]
        for name in ("draft-before.jsonl", "draft-after.jsonl",
                     "draft-field-diff.jsonl", "evidence-verification.jsonl"):
            assert (out1["revision_dir"] / name).read_bytes() == \
                (out2["revision_dir"] / name).read_bytes()

    def test_field_diff_lists_before_after(self, world):
        out = _transform(world)
        diff_rows = [json.loads(l) for l in
                     (out["revision_dir"] / "draft-field-diff.jsonl")
                     .read_text(encoding="utf-8").splitlines() if l.strip()]
        en055 = next(r for r in diff_rows if r["case_id"] == "en-055")
        ap = en055["changed_fields"]["acceptable_answer_points"]
        assert ap["before"] == ["& 运算符（借用/引用）"]
        assert ap["after"] == ["The `&` operator creates a reference (e.g., `&s1`)"]
        en052 = next(r for r in diff_rows if r["case_id"] == "en-052")
        assert en052["changed_fields"]["acceptable_answer_points"]["after"] == [
            "PostgreSQL: transaction durability (logged to disk)"]


# ── 数据质量校验（data-analytics 等价实现）───────────────────────────

class TestDataQuality:
    def test_all_answer_points_have_evidence(self, world):
        out = _transform(world)
        dq = rp.data_quality_report(
            out["cases_by_id"], *_fixture_chunks())
        assert dq["all_answer_points_have_evidence"] is True
        assert dq["answer_points_without_evidence"] == []

    def test_evidence_referential_integrity(self, world):
        out = _transform(world)
        dq = rp.data_quality_report(
            out["cases_by_id"], *_fixture_chunks())
        assert dq["all_chunks_exist"] is True
        assert dq["all_snippets_contiguous"] is True
        assert dq["all_sources_match"] is True
        assert dq["chunk_id_lists_consistent"] is True

    def test_no_duplicate_evidence_or_points(self, world):
        out = _transform(world)
        dq = rp.data_quality_report(
            out["cases_by_id"], *_fixture_chunks())
        assert dq["duplicate_chunk_ids"] == []
        assert dq["duplicate_answer_points"] == []

    def test_multi_014_core_verbatim_in_answer_point(self, world):
        out = _transform(world)
        dq = rp.data_quality_report(
            out["cases_by_id"], *_fixture_chunks())
        check = dq["per_case"]["multi-014"]["answer_point_1"]
        assert check["core_in_answer_point"] is True
        assert check["coverage"] >= 0.75

    def test_en_055_semantic_tokens_present(self, world):
        out = _transform(world)
        dq = rp.data_quality_report(
            out["cases_by_id"], *_fixture_chunks())
        check = dq["per_case"]["en-055"]["answer_point_0"]
        assert check["core_has_ampersand"] is True
        assert check["core_has_reference"] is True
        assert check["core_has_create"] is True
        assert check["answer_point_has_ampersand"] is True
        assert check["answer_point_has_reference"] is True

    def test_mixed_016_terms_present(self, world):
        out = _transform(world)
        dq = rp.data_quality_report(
            out["cases_by_id"], *_fixture_chunks())
        check = dq["per_case"]["mixed-016"]
        assert check["answer_point_0"]["glossary_form"] is True
        assert check["answer_point_1"]["glossary_form"] is True
        assert "parameter" in check["answer_point_1"]["evidence_text"]
        assert "形参" in check["answer_point_1"]["evidence_text"]

    def test_target_cases_have_evidence(self, world):
        out = _transform(world)
        dq = rp.data_quality_report(
            out["cases_by_id"], *_fixture_chunks())
        assert dq["targets_with_evidence"] == sorted(TARGETS)
        assert dq["targets_without_evidence"] == []


# ── 真实语料（文件缺失时跳过）────────────────────────────────────────

def _real_paths() -> dict:
    root = Path(__file__).resolve().parents[1]
    return {
        "draft": root / "evaluation" / "datasets" / "v2" / "annotations" /
                 "v2-cases-draft.jsonl",
        "chunks": root / "data" / "v2-corpus" / "chunks" / "chunks.jsonl",
        "audit": root / "evaluation" / "datasets" / "v2" /
                 "persistent-reject-evidence-audit" / "manifest.json",
        "merged": root / "evaluation" / "datasets" / "v2" /
                  "llm-semantic-adjudication" / "coherence-recheck" /
                  "merged-adjudications.jsonl",
        "sel": root / "evaluation" / "datasets" / "v2" /
               "llm-semantic-adjudication" / "selection-manifest.json",
    }


def _real_available() -> bool:
    paths = _real_paths()
    return all(p.is_file() for p in paths.values())


def _pre_repair_draft_copy(tmp_path: Path) -> Path:
    """修复前草稿副本：优先版本化快照（draft-before），缺失回退当前文件。"""
    import shutil
    import v2_repair_snapshot_util as snap
    draft_copy = tmp_path / "draft.jsonl"
    shutil.copy2(snap.pre_repair_draft(tmp_path), draft_copy)
    return draft_copy


@pytest.mark.skipif(not _real_available(), reason="real corpus files missing")
class TestRealCorpus:
    def test_real_transform_validates_and_verifies_ranges(self, tmp_path):
        p = _real_paths()
        # 使用临时副本：测试绝不修改真实草稿
        draft_copy = _pre_repair_draft_copy(tmp_path)
        out = rp.transform(draft_copy, p["chunks"], p["audit"], p["merged"],
                           p["sel"], revision_dir=tmp_path / "rev")
        assert set(out["cases_by_id"]) >= set(TARGETS)
        assert out["n_targets"] == 5
        assert out["n_changed"] == 5
        ev = out["evidence_verification"]
        assert len(ev) == 3
        by_chunk = {e["chunk_id"]: e for e in ev}
        assert by_chunk["32c427fb50e2_chunk_38"]["char_start"] == 321
        assert by_chunk["32c427fb50e2_chunk_38"]["char_end"] == 359
        assert by_chunk["4f9001ca8c15_chunk_49"]["char_start"] == 1424
        assert by_chunk["4f9001ca8c15_chunk_49"]["char_end"] == 1467
        assert by_chunk["c9fd20815ea8_chunk_14"]["char_start"] == 783
        assert by_chunk["c9fd20815ea8_chunk_14"]["char_end"] == 798
        assert all(e["snippet_is_evidence"] and e["core_located_once"]
                   and e["source_matches"] for e in ev)

    def test_real_145_rows_byte_identical(self, tmp_path):
        p = _real_paths()
        draft_copy = _pre_repair_draft_copy(tmp_path)
        orig = [l for l in draft_copy.read_bytes().split(b"\r\n") if l.strip()]
        out = rp.transform(draft_copy, p["chunks"], p["audit"], p["merged"],
                           p["sel"], revision_dir=tmp_path / "rev")
        new = [l for l in out["bytes"].split(b"\r\n") if l.strip()]
        changed = 0
        for old, newline in zip(orig, new):
            if json.loads(old)["id"] in TARGETS:
                assert old != newline
                changed += 1
            else:
                assert old == newline
        assert changed == 5

    def test_real_determinism(self, tmp_path):
        p = _real_paths()
        draft_copy = _pre_repair_draft_copy(tmp_path)
        out1 = rp.transform(draft_copy, p["chunks"], p["audit"], p["merged"],
                            p["sel"], revision_dir=tmp_path / "r1")
        out2 = rp.transform(draft_copy, p["chunks"], p["audit"], p["merged"],
                            p["sel"], revision_dir=tmp_path / "r2")
        assert out1["bytes"] == out2["bytes"]
        assert (out1["revision_dir"] / "draft-after.jsonl").read_bytes() == \
            (out2["revision_dir"] / "draft-after.jsonl").read_bytes()

    def test_real_pack_regeneration_145_rows_identical(self, tmp_path):
        """空白 pack 重生成：145 行逐字节一致、5 行变化、人工字段全空。"""
        import shutil
        import scripts.corpus_v2_human_review_pack as hp
        p = _real_paths()
        old_draft = tmp_path / "old-draft.jsonl"
        new_draft = tmp_path / "new-draft.jsonl"
        shutil.copy2(_pre_repair_draft_copy(tmp_path), old_draft)
        out = rp.transform(old_draft, p["chunks"], p["audit"], p["merged"],
                           p["sel"], revision_dir=tmp_path / "rev")
        new_draft.write_bytes(out["bytes"])

        out_old = tmp_path / "pack-old"
        out_new = tmp_path / "pack-new"
        hp.build_pack(old_draft, p["chunks"], hp.DEFAULT_CHUNK_MANIFEST,
                      hp.DEFAULT_CORPUS_MANIFEST, hp.DEFAULT_LEDGER, out_old)
        hp.build_pack(new_draft, p["chunks"], hp.DEFAULT_CHUNK_MANIFEST,
                      hp.DEFAULT_CORPUS_MANIFEST, hp.DEFAULT_LEDGER, out_new)

        old_rows = [json.loads(l) for l in
                    (out_old / "human-review-pack.jsonl")
                    .read_text(encoding="utf-8").splitlines() if l.strip()]
        new_rows = [json.loads(l) for l in
                    (out_new / "human-review-pack.jsonl")
                    .read_text(encoding="utf-8").splitlines() if l.strip()]
        assert len(old_rows) == len(new_rows) == 150
        changed = 0
        for a, b in zip(old_rows, new_rows):
            if a["case_id"] in TARGETS:
                assert a != b
                changed += 1
            else:
                assert a == b
        assert changed == 5
        # 三个手工字段必须仍为空
        for row in new_rows:
            assert row["human_review_decision"] == ""
            assert row["human_reviewer"] == ""
            assert row["human_review_notes"] == ""
        # 新包 fail-closed 校验通过
        errs = hp.verify(out_new / "human-review-pack-manifest.json")
        assert errs == []

    def test_real_freeze_lock_stable(self, tmp_path):
        """case 集合与分组稳定：freeze 指纹不变、lock 校验通过。"""
        import shutil
        import scripts.corpus_v2_seal as seal
        from evaluation.split_seal import verify_lock
        p = _real_paths()
        draft_copy = _pre_repair_draft_copy(tmp_path)
        out = rp.transform(draft_copy, p["chunks"], p["audit"], p["merged"],
                           p["sel"], revision_dir=tmp_path / "rev")
        draft_copy.write_bytes(out["bytes"])

        root = Path(__file__).resolve().parents[1]
        freeze_path = root / "evaluation" / "datasets" / "v2" / "split" / \
            "case-freeze.json"
        lock_path = root / "evaluation" / "datasets" / "v2" / "split" / \
            "split-lock.json"
        if not (freeze_path.is_file() and lock_path.is_file()):
            pytest.skip("freeze/lock files missing")
        seal.V2 = draft_copy  # 用修复后副本重建 pool（v1 不变）
        frozen = seal.freeze_case_ids(seal.build_pool(), seal.CORPUS_VERSION)
        saved = json.loads(freeze_path.read_text(encoding="utf-8"))
        assert saved["case_ids_sha256"] == frozen["case_ids_sha256"]
        # 5 条目标的 freeze 元数据（stratum 字段）不变
        for cid in TARGETS:
            assert saved["cases"][cid] == frozen["cases"][cid]
        lock = json.loads(lock_path.read_text(encoding="utf-8"))
        assert verify_lock(lock, frozen) is True

    def test_real_transform_idempotent_on_repaired_draft(self, tmp_path):
        """已修复草稿上重跑 transform：0 变更、字节一致（安全重跑）。"""
        p = _real_paths()
        import shutil
        draft_copy = tmp_path / "draft.jsonl"
        shutil.copy2(p["draft"], draft_copy)  # 当前真实草稿 = 修复后
        out = rp.transform(draft_copy, p["chunks"], p["audit"], p["merged"],
                           p["sel"], revision_dir=tmp_path / "rev")
        assert out["n_changed"] == 0
        assert out["bytes"] == draft_copy.read_bytes()
        assert out["diff_rows"] == []
