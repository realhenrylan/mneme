"""Tests for the targeted post-repair machine review of the five
persistent-reject cases (Task 12).

Covers: blind input construction (no case id / history / cohort / split
leakage), determinism, strict JSON contract + coherence validation,
fail-closed behaviour (any reject / needs_followup / invalid JSON /
coherence violation stops without any overlay), model guard and the
MACHINE_REVIEWED_DIAGNOSTIC_ONLY reporting.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

import scripts.corpus_v2_targeted_machine_review as tmr

TARGETS = list(tmr.TARGET_CASE_IDS)

# ── synthetic world (mirrors the repaired draft shapes) ───────────────

SNIPPET_M014 = ("记住，使用\n```\nfrom package import specific_submodule\n```\n"
                " 没有任何问题！ 实际上，除了导入模块使用不同包的同名子模块"
                "之外，这种方式是推荐用法。")
SNIPPET_E055 = ("The `&s1` syntax lets us create a reference that _refers_ to "
                "the value of `s1`\nbut does not own it.")

CHUNK_FIXTURES: dict[str, tuple[str, str]] = {
    "gen_0": ("python-tutorial-zh.md", "generic evidence text one."),
    "32c427fb50e2_chunk_31": (
        "python-tutorial-zh.md",
        "大多数情况下，不要用这个功能，这种方式向解释器导入了一批未知的名称。"),
    "32c427fb50e2_chunk_38": (
        "python-tutorial-zh.md",
        "记住，使用\n```\nfrom package import specific_submodule\n```\n 没有"
        "任何问题！ 实际上，除了导入模块使用不同包的同名子模块之外，这种方式"
        "是推荐用法。" + "填充" * 300),
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
        "rules."),
    "4f9001ca8c15_chunk_48": (
        "rust-book-core.md",
        "A reference is like a pointer in that it's an address we can follow "
        "to access the data stored at that address; that data is owned by "
        "some other variable."),
    "4f9001ca8c15_chunk_49": (
        "rust-book-core.md",
        "The `&s1` syntax lets us create a reference that _refers_ to the "
        "value of `s1`\nbut does not own it." + "padding " * 200),
    "c9fd20815ea8_chunk_1": (
        "python-glossary-zh.md",
        "参数会被赋值给函数体中对应的局部变量。 另参见 parameter 术语表条目"),
    "c9fd20815ea8_chunk_14": (
        "python-glossary-zh.md",
        "填充" * 300 + "parameter -- 形参¶ 词条正文。"),
}


def _chunk_ref(cid: str, snippet: str, section: str | None = None):
    source, _ = CHUNK_FIXTURES[cid]
    return {"source_id": source, "chunk_id": cid,
            "chunk_text_snippet": snippet, "page": None, "section": section}


def _case(cid: str, i: int) -> dict:
    """Repaired post-transform draft row for each target."""
    if cid == "multi-014":
        return {"id": cid, "query": "如果 from fibo import * 引入了不该引入"
                                    "的名字，教程建议怎么避免这种问题？",
                "query_type": "multi_turn", "language": "zh",
                "relevant_source_ids": ["python-tutorial-zh.md"],
                "relevant_chunks": [
                    _chunk_ref("32c427fb50e2_chunk_31",
                               "大多数情况下，不要用这个功能",
                               "6.1.1 以脚本方式执行模块"),
                    _chunk_ref("32c427fb50e2_chunk_38", SNIPPET_M014,
                               "6.4.1 从包中导入 *")],
                "relevant_chunk_ids": ["32c427fb50e2_chunk_31",
                                       "32c427fb50e2_chunk_38"],
                "acceptable_answer_points": [
                    "尽量不要使用 from ... import *",
                    "建议使用 from package import specific_submodule"],
                "should_refuse": False, "relevance_level": "chunk",
                "metadata": {"turn": 1, "follow_up_to": None,
                             "chain_id": None, "difficulty": "hard"}}
    if cid == "mixed-026":
        return {"id": cid, "query": "中文教程把第 3 章叫做 Python 速览，英文教程"
                                    "叫 An Informal Introduction to Python，两"
                                    "版内容对应吗？",
                "query_type": "cross_document", "language": "mixed",
                "relevant_source_ids": ["python-tutorial-zh.md",
                                        "python-tutorial-en.md"],
                "relevant_chunks": [
                    _chunk_ref("32c427fb50e2_chunk_2", "# 3. Python 速览¶",
                               "3. Python 速览"),
                    _chunk_ref("e564a122a7a2_chunk_5",
                               "3. An Informal Introduction to Python",
                               "3. An Informal Introduction to Python")],
                "relevant_chunk_ids": ["32c427fb50e2_chunk_2",
                                       "e564a122a7a2_chunk_5"],
                "acceptable_answer_points": ["对应：同一章，标题翻译不同"],
                "should_refuse": False, "relevance_level": "chunk",
                "metadata": {"turn": 1, "follow_up_to": None,
                             "chain_id": None, "difficulty": "hard"}}
    if cid == "en-052":
        return {"id": cid, "query": "Both PostgreSQL and Rust documents discuss"
                                    " guarantees — what does each guarantee "
                                    "about data consistency?",
                "query_type": "cross_document", "language": "en",
                "relevant_source_ids": ["postgresql-tutorial.md",
                                        "rust-book-core.md"],
                "relevant_chunks": [
                    _chunk_ref("761b22915b5e_chunk_12",
                               "A transactional database guarantees that all "
                               "the updates made by a transaction are logged "
                               "in permanent storage", "3.4 Transactions"),
                    _chunk_ref("4f9001ca8c15_chunk_37",
                               "### Ownership Rules\n\nFirst, let's take a "
                               "look at the ownership rules.",
                               "4.1 What Is Ownership")],
                "relevant_chunk_ids": ["761b22915b5e_chunk_12",
                                       "4f9001ca8c15_chunk_37"],
                "acceptable_answer_points": [
                    "PostgreSQL: transaction durability (logged to disk)"],
                "should_refuse": False, "relevance_level": "chunk",
                "metadata": {"turn": 1, "follow_up_to": None,
                             "chain_id": None, "difficulty": "hard"}}
    if cid == "en-055":
        return {"id": cid, "query": "The Rust book says values are moved rather"
                                    " than copied in some cases — what operator"
                                    " creates a reference instead?",
                "query_type": "mixed_intent", "language": "en",
                "relevant_source_ids": ["rust-book-core.md"],
                "relevant_chunks": [
                    _chunk_ref("4f9001ca8c15_chunk_48",
                               "A reference is like a pointer in that it's an "
                               "address we can follow to access the data "
                               "stored at that address; that data is owned by "
                               "some other variable.",
                               "4.2 References and Borrowing"),
                    _chunk_ref("4f9001ca8c15_chunk_49", SNIPPET_E055,
                               "4.2 References and Borrowing")],
                "relevant_chunk_ids": ["4f9001ca8c15_chunk_48",
                                       "4f9001ca8c15_chunk_49"],
                "acceptable_answer_points": [
                    "The `&` operator creates a reference (e.g., `&s1`)"],
                "should_refuse": False, "relevance_level": "chunk",
                "metadata": {"turn": 1, "follow_up_to": None,
                             "chain_id": None, "difficulty": "medium"}}
    if cid == "mixed-016":
        return {"id": cid, "query": "术语表里，argument 和 parameter 的中文译"
                                    "名分别是什么？",
                "query_type": "single_fact", "language": "mixed",
                "relevant_source_ids": ["python-glossary-zh.md"],
                "relevant_chunks": [
                    _chunk_ref("c9fd20815ea8_chunk_1",
                               "参数会被赋值给函数体中对应的局部变量。",
                               "argument 参数"),
                    _chunk_ref("c9fd20815ea8_chunk_14", "parameter -- 形参",
                               "parameter 形参")],
                "relevant_chunk_ids": ["c9fd20815ea8_chunk_1",
                                       "c9fd20815ea8_chunk_14"],
                "acceptable_answer_points": ["argument — 参数",
                                             "parameter — 形参"],
                "should_refuse": False, "relevance_level": "chunk",
                "metadata": {"turn": 1, "follow_up_to": None,
                             "chain_id": None, "difficulty": "medium"}}
    raise AssertionError(cid)


def _all_ids() -> list[str]:
    ids: list[str] = []
    for prefix, n in (("en", 60), ("mixed", 40), ("zh", 30), ("multi", 20)):
        ids += [f"{prefix}-{i:03d}" for i in range(1, n + 1)]
    return ids


def _generic_case(cid: str) -> dict:
    """非目标行：仅用于凑足 150 行（target 行才被读取校验）。"""
    return {"id": cid, "query": f"query {cid}?", "query_type": "single_fact",
            "language": "en", "should_refuse": False,
            "relevance_level": "chunk",
            "relevant_source_ids": ["python-tutorial-zh.md"],
            "relevant_chunks": [{"source_id": "python-tutorial-zh.md",
                                 "chunk_id": "gen_0",
                                 "chunk_text_snippet":
                                 "generic evidence text one.",
                                 "page": None, "section": None}],
            "relevant_chunk_ids": ["gen_0"],
            "acceptable_answer_points": ["point a", "point b"],
            "metadata": {"turn": 1, "follow_up_to": None, "chain_id": None,
                         "difficulty": "medium"}}


def _write_draft(tmp_path: Path) -> Path:
    p = tmp_path / "draft.jsonl"
    rows = []
    for i, cid in enumerate(_all_ids(), start=1):
        rows.append(_case(cid, i) if cid in TARGETS else _generic_case(cid))
    assert len(rows) == 150
    p.write_text("\n".join(json.dumps(r, ensure_ascii=False)
                           for r in rows) + "\n", encoding="utf-8")
    return p


def _write_chunks(tmp_path: Path) -> Path:
    p = tmp_path / "chunks.jsonl"
    lines = [json.dumps({"chunk_id": cid, "index": n, "source": src,
                         "text": text}, ensure_ascii=False)
             for n, (cid, (src, text)) in enumerate(CHUNK_FIXTURES.items())]
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return p


@pytest.fixture
def world(tmp_path: Path):
    draft_p = _write_draft(tmp_path)
    chunks_p = _write_chunks(tmp_path)
    return {"tmp": tmp_path, "draft": draft_p, "chunks": chunks_p}


def _build(world: dict, out: Path | None = None) -> dict:
    return tmr.build_targeted_input(world["draft"], world["chunks"], out)


# ── 盲态输入构建 ─────────────────────────────────────────────────────

class TestBlindInput:
    def test_rows_are_blind_no_case_id(self, world):
        b = _build(world)
        for cid, row in zip(TARGETS, b["rows"]):
            text = json.dumps(row, ensure_ascii=False)
            assert cid not in text
            assert "multi-014" not in text
        assert set(b["rows"][0]) == {"query", "previous_turns", "should_refuse",
                                     "acceptable_answer_points", "evidence",
                                     "chunks"}

    def test_no_history_or_split_fields(self, world):
        b = _build(world)
        forbidden = ("decision", "verdict", "cohort", "split", "holdout",
                     "dev_set", "reviewer", "notes", "persistent", "third",
                     "rationale", "case_id")
        for row in b["rows"]:
            text = json.dumps(row, ensure_ascii=False)
            for key in forbidden:
                assert f'"{key}"' not in text

    def test_rows_include_repaired_points_and_scoped_chunks(self, world):
        b = _build(world)
        by_q = {row["query"]: row for row in b["rows"]}
        en055 = by_q["The Rust book says values are moved rather than copied "
                     "in some cases — what operator creates a reference "
                     "instead?"]
        assert en055["acceptable_answer_points"] == [
            "The `&` operator creates a reference (e.g., `&s1`)"]
        chunk_ids = {c["chunk_id"] for c in en055["chunks"]}
        assert chunk_ids == {"4f9001ca8c15_chunk_48", "4f9001ca8c15_chunk_49"}
        assert all(c["text"] for c in en055["chunks"])
        m016 = by_q["术语表里，argument 和 parameter 的中文译名分别是什么？"]
        assert m016["acceptable_answer_points"] == ["argument — 参数",
                                                    "parameter — 形参"]

    def test_previous_turns_only_queries(self, world):
        b = _build(world)
        for row in b["rows"]:
            for t in row["previous_turns"]:
                assert set(t) == {"query"}

    def test_deterministic_input_pack(self, world):
        b1 = _build(world)
        b2 = _build(world)
        assert b1["pack_bytes"] == b2["pack_bytes"]

    def test_input_pack_written_with_shas(self, world):
        out = world["tmp"] / "review-out"
        b = _build(world, out)
        pack = out / "targeted-input-pack.jsonl"
        assert pack.read_bytes() == b["pack_bytes"]
        rows = [json.loads(l) for l in
                pack.read_text(encoding="utf-8").splitlines() if l.strip()]
        assert len(rows) == 5

    def test_missing_chunk_fails(self, world):
        chunks_p = world["chunks"]
        chunks_p.write_text(
            "\n".join(l for l in chunks_p.read_text(encoding="utf-8")
                      .splitlines() if '"4f9001ca8c15_chunk_49"' not in l)
            + "\n", encoding="utf-8")
        with pytest.raises(tmr.MachineReviewError, match="chunk"):
            _build(world)

    def test_snippet_not_contiguous_fails(self, world):
        draft_p = world["draft"]
        lines = [l for l in draft_p.read_text(encoding="utf-8").splitlines()
                 if l.strip()]
        for i, l in enumerate(lines):
            if '"multi-014"' in l:
                row = json.loads(l)
                row["relevant_chunks"][1]["chunk_text_snippet"] = "拼接的"
                lines[i] = json.dumps(row, ensure_ascii=False)
                break
        draft_p.write_text("\n".join(lines) + "\n", encoding="utf-8")
        with pytest.raises(tmr.MachineReviewError, match="snippet|证据"):
            _build(world)


# ── 复审流程（fake llm）──────────────────────────────────────────────

def _resp(content: str, model: str = "deepseek-v4-pro", retries: int = 0):
    msg = SimpleNamespace(content=content)
    choice = SimpleNamespace(message=msg)
    resp = SimpleNamespace(choices=[choice], model=model)
    rec = SimpleNamespace(retries_used=retries)
    return resp, rec


def _fake_llm_map(mapping: dict[str, str], model: str = "deepseek-v4-pro"):
    """Return an llm_fn whose content depends on the user payload query."""
    def fn(call_type, messages, model=model, temperature=0.0, max_tokens=8000):
        payload = json.loads(messages[-1]["content"])
        q = payload["query"]
        for cid, content in mapping.items():
            if cid in q or q in cid:
                return _resp(content, model=model)
        raise AssertionError(f"no fake mapping for query: {q}")
    return fn


CONFIRMED = (
    '{"semantic_verdict": "confirmed", "verdict_rationale": "所有答案点均'
    '由证据直接支持", "answer_point_supports": [{"answer_point_index": 0, '
    '"support_level": "direct_snippet", "chunk_id": "32c427fb50e2_chunk_31", '
    '"excerpt": "大多数情况下，不要用这个功能"}, {"answer_point_index": 1, '
    '"support_level": "faithful_paraphrase", "chunk_id": '
    '"32c427fb50e2_chunk_38", "excerpt": "from package import '
    'specific_submodule"}]}'
)


def _confirmed_for(n_points: int, chunk_ids: list[str]) -> str:
    supports = [{"answer_point_index": i,
                 "support_level": "direct_snippet",
                 "chunk_id": chunk_ids[i % len(chunk_ids)],
                 "excerpt": "支持摘录"} for i in range(n_points)]
    return json.dumps({"semantic_verdict": "confirmed",
                       "verdict_rationale": "所有答案点均由证据直接支持",
                       "answer_point_supports": supports},
                      ensure_ascii=False)


class TestReviewFlow:
    def _run(self, world: dict, llm_fn) -> dict:
        return tmr.run(world["draft"], world["chunks"],
                       world["tmp"] / "review-out", llm_fn=llm_fn)

    def test_confirmed_flow_writes_diagnostic_only_report(self, world):
        def llm_fn(call_type, messages, model="deepseek-v4-pro",
                   temperature=0.0, max_tokens=8000):
            payload = json.loads(messages[-1]["content"])
            n = len(payload["acceptable_answer_points"])
            cids = [c["chunk_id"] for c in payload["chunks"]]
            return _resp(_confirmed_for(n, cids), model=model)

        out = self._run(world, llm_fn)
        assert out["status"] == "all_confirmed"
        assert out["fail_closed"] is False
        rev_dir = world["tmp"] / "review-out"
        reviews = [json.loads(l) for l in
                   (rev_dir / "post-repair-reviews.jsonl")
                   .read_text(encoding="utf-8").splitlines() if l.strip()]
        assert len(reviews) == 5
        assert [r["semantic_verdict"] for r in reviews] == ["confirmed"] * 5
        assert [r["model"] for r in reviews] == ["deepseek-v4-pro"] * 5
        assert [r["index"] for r in reviews] == list(range(1, 6))
        report = (rev_dir / "MACHINE_REVIEWED_DIAGNOSTIC_ONLY.md").read_text(
            encoding="utf-8")
        assert "MACHINE_REVIEWED_DIAGNOSTIC_ONLY" in report
        assert "人工终审" not in report.replace("不是人工终审", "")

    def test_any_reject_stops_fail_closed(self, world):
        def llm_fn(call_type, messages, model="deepseek-v4-pro",
                   temperature=0.0, max_tokens=8000):
            payload = json.loads(messages[-1]["content"])
            n = len(payload["acceptable_answer_points"])
            cids = [c["chunk_id"] for c in payload["chunks"]]
            if "术语表" in payload["query"]:
                content = json.dumps(
                    {"semantic_verdict": "reject",
                     "verdict_rationale": "证据不足",
                     "answer_point_supports": [
                         {"answer_point_index": i,
                          "support_level": "unsupported",
                          "chunk_id": "", "excerpt": ""}
                         for i in range(n)]}, ensure_ascii=False)
            else:
                content = _confirmed_for(n, cids)
            return _resp(content, model=model)

        with pytest.raises(tmr.MachineReviewError, match="reject"):
            self._run(world, llm_fn)
        rev_dir = world["tmp"] / "review-out"
        assert not (rev_dir / "post-repair-reviews.jsonl").exists()
        diag = (rev_dir / "diagnostic-report.md").read_text(encoding="utf-8")
        assert "FAIL_CLOSED" in diag

    def test_needs_followup_stops(self, world):
        def llm_fn(call_type, messages, model="deepseek-v4-pro",
                   temperature=0.0, max_tokens=8000):
            payload = json.loads(messages[-1]["content"])
            n = len(payload["acceptable_answer_points"])
            cids = [c["chunk_id"] for c in payload["chunks"]]
            if "argument" in payload["query"]:
                content = json.dumps(
                    {"semantic_verdict": "needs_followup",
                     "verdict_rationale": "无法确认参数译名是否准确",
                     "answer_point_supports": [
                         {"answer_point_index": i,
                          "support_level": "faithful_paraphrase",
                          "chunk_id": cids[0], "excerpt": "摘录"}
                         for i in range(n)]}, ensure_ascii=False)
            else:
                content = _confirmed_for(n, cids)
            return _resp(content, model=model)

        with pytest.raises(tmr.MachineReviewError, match="needs_followup"):
            self._run(world, llm_fn)

    def test_invalid_json_after_retries_stops(self, world):
        calls = {"n": 0}

        def llm_fn(call_type, messages, model="deepseek-v4-pro",
                   temperature=0.0, max_tokens=8000):
            if len(messages) > 2:  # 纠正性重试消息（非 JSON 载荷）
                calls["n"] += 1
                return _resp("仍然不是 JSON", model=model)
            payload = json.loads(messages[1]["content"])
            if "术语表" in payload["query"]:
                calls["n"] += 1
                return _resp("不是 JSON", model=model)
            n = len(payload["acceptable_answer_points"])
            cids = [c["chunk_id"] for c in payload["chunks"]]
            return _resp(_confirmed_for(n, cids), model=model)

        with pytest.raises(tmr.MachineReviewError, match="解析|unparseable"):
            self._run(world, llm_fn)
        assert calls["n"] == 3  # 首次 + 2 次纠正重试
        rev_dir = world["tmp"] / "review-out"
        assert not (rev_dir / "post-repair-reviews.jsonl").exists()

    def test_coherence_violation_stops(self, world):
        def llm_fn(call_type, messages, model="deepseek-v4-pro",
                   temperature=0.0, max_tokens=8000):
            payload = json.loads(messages[-1]["content"])
            n = len(payload["acceptable_answer_points"])
            cids = [c["chunk_id"] for c in payload["chunks"]]
            if "术语表" in payload["query"]:
                # confirmed 但存在 unsupported 答案点 → coherence 违规
                content = json.dumps(
                    {"semantic_verdict": "confirmed",
                     "verdict_rationale": "全部支持",
                     "answer_point_supports": [
                         {"answer_point_index": i,
                          "support_level": "unsupported",
                          "chunk_id": "", "excerpt": ""}
                         for i in range(n)]}, ensure_ascii=False)
            else:
                content = _confirmed_for(n, cids)
            return _resp(content, model=model)

        with pytest.raises(tmr.MachineReviewError, match="coherence|一致性"):
            self._run(world, llm_fn)
        rev_dir = world["tmp"] / "review-out"
        assert not (rev_dir / "post-repair-reviews.jsonl").exists()

    def test_manifest_records_prompt_and_response_shas(self, world):
        def llm_fn(call_type, messages, model="deepseek-v4-pro",
                   temperature=0.0, max_tokens=8000):
            payload = json.loads(messages[-1]["content"])
            n = len(payload["acceptable_answer_points"])
            cids = [c["chunk_id"] for c in payload["chunks"]]
            return _resp(_confirmed_for(n, cids), model=model)

        self._run(world, llm_fn)
        rev_dir = world["tmp"] / "review-out"
        m = json.loads((rev_dir / "manifest.json").read_text(encoding="utf-8"))
        assert len(m["cases"]) == 5
        for entry in m["cases"]:
            assert len(entry["prompt_sha256"]) == 64
            assert len(entry["response_sha256"]) == 64
            assert entry["parse_retries"] == 0
            assert entry["retries_used"] == 0
        raw = [json.loads(l) for l in
               (rev_dir / "raw-responses.jsonl")
               .read_text(encoding="utf-8").splitlines() if l.strip()]
        assert len(raw) == 5
        for r in raw:
            h = hashlib.sha256(r["raw_content"].encode("utf-8")).hexdigest()
            assert h == r["response_sha256"]

    def test_deterministic_with_fake_llm(self, world):
        def llm_fn(call_type, messages, model="deepseek-v4-pro",
                   temperature=0.0, max_tokens=8000):
            payload = json.loads(messages[-1]["content"])
            n = len(payload["acceptable_answer_points"])
            cids = [c["chunk_id"] for c in payload["chunks"]]
            return _resp(_confirmed_for(n, cids), model=model)

        out1 = tmr.run(world["draft"], world["chunks"],
                       world["tmp"] / "o1", llm_fn=llm_fn)
        out2 = tmr.run(world["draft"], world["chunks"],
                       world["tmp"] / "o2", llm_fn=llm_fn)
        for name in ("targeted-input-pack.jsonl", "post-repair-reviews.jsonl",
                     "raw-responses.jsonl", "MACHINE_REVIEWED_DIAGNOSTIC_ONLY.md",
                     "manifest.json"):
            assert (world["tmp"] / "o1" / name).read_bytes() == \
                (world["tmp"] / "o2" / name).read_bytes()

    def test_model_guard_forbidden(self, world):
        def llm_fn(call_type, messages, model="deepseek-v4-pro",
                   temperature=0.0, max_tokens=8000):
            payload = json.loads(messages[-1]["content"])
            n = len(payload["acceptable_answer_points"])
            cids = [c["chunk_id"] for c in payload["chunks"]]
            return _resp(_confirmed_for(n, cids), model=model)

        with pytest.raises(tmr.MachineReviewError, match="forbidden|禁止"):
            tmr.run(world["draft"], world["chunks"], world["tmp"] / "x",
                    model="deepseek-v4-flash", llm_fn=llm_fn)
        with pytest.raises(tmr.MachineReviewError, match="forbidden|禁止"):
            tmr.run(world["draft"], world["chunks"], world["tmp"] / "x",
                    model="gpt-5.6-sol", llm_fn=llm_fn)

    def test_wrong_model_identity_stops(self, world):
        def llm_fn(call_type, messages, model="deepseek-v4-pro",
                   temperature=0.0, max_tokens=8000):
            payload = json.loads(messages[-1]["content"])
            n = len(payload["acceptable_answer_points"])
            cids = [c["chunk_id"] for c in payload["chunks"]]
            return _resp(_confirmed_for(n, cids), model="wrong-model")

        with pytest.raises(tmr.MachineReviewError, match="drift|模型"):
            self._run(world, llm_fn)

    def test_no_overlay_ever_written(self, world):
        def llm_fn(call_type, messages, model="deepseek-v4-pro",
                   temperature=0.0, max_tokens=8000):
            payload = json.loads(messages[-1]["content"])
            n = len(payload["acceptable_answer_points"])
            cids = [c["chunk_id"] for c in payload["chunks"]]
            return _resp(_confirmed_for(n, cids), model=model)

        self._run(world, llm_fn)
        rev_dir = world["tmp"] / "review-out"
        names = [p.name for p in rev_dir.iterdir()]
        assert "truth-overlay.jsonl" not in names
        assert "overlay.jsonl" not in names


# ── 真实语料（文件缺失时跳过）────────────────────────────────────────

def _real_paths() -> dict:
    root = Path(__file__).resolve().parents[1]
    return {
        "draft": root / "evaluation" / "datasets" / "v2" / "annotations" /
                 "v2-cases-draft.jsonl",
        "chunks": root / "data" / "v2-corpus" / "chunks" / "chunks.jsonl",
    }


@pytest.mark.skipif(not all(p.is_file() for p in _real_paths().values()),
                    reason="real corpus files missing")
class TestRealCorpus:
    def test_real_input_pack_deterministic_and_blind(self, tmp_path):
        import shutil
        p = _real_paths()
        draft_copy = tmp_path / "draft.jsonl"
        shutil.copy2(p["draft"], draft_copy)
        b1 = tmr.build_targeted_input(draft_copy, p["chunks"], tmp_path / "o1")
        b2 = tmr.build_targeted_input(draft_copy, p["chunks"], tmp_path / "o2")
        assert b1["pack_bytes"] == b2["pack_bytes"]
        for cid, row in zip(tmr.TARGET_CASE_IDS, b1["rows"]):
            text = json.dumps(row, ensure_ascii=False)
            assert cid not in text
            for key in ("decision", "verdict", "cohort", "split", "holdout",
                        "persistent"):
                assert f'"{key}"' not in text
        assert len(b1["rows"]) == 5
