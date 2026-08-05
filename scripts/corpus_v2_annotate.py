"""Corpus v2 annotation scaffold: deterministic case-id allocation,
stratum-quota validation, chain structure, and case template emission.

Usage: python scripts/corpus_v2_annotate.py skeleton [--out skeleton.json]
       python scripts/corpus_v2_annotate.py validate <cases.jsonl>

Zero LLM. The scaffold assigns ids (continuing v1 per-prefix sequences),
query_type/language/difficulty/band_target/construction and chain wiring
per the quota matrix in plans/CORPUS-EXPANSION-PLAN-2026-08-05.md §3.3.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# ── 配额矩阵（类型 × 语言，合计 150）──────────────────────────────────
QUOTA = {
    "single_fact": {"zh": 17, "en": 12, "mixed": 5},
    "metadata": {"zh": 7, "en": 7, "mixed": 5},
    "cross_document": {"zh": 10, "en": 14, "mixed": 7},
    "multi_turn": {"zh": 10, "en": 9, "mixed": 5},
    "mixed_intent": {"zh": 5, "en": 4, "mixed": 3},
    "no_answer": {"zh": 11, "en": 14, "mixed": 5},
}

DIFFICULTY = {
    "single_fact": {"hard": 2, "medium": 14, "easy": 18},
    "metadata": {"hard": 1, "medium": 8, "easy": 10},
    "cross_document": {"hard": 25, "medium": 6, "easy": 0},
    "multi_turn": {"hard": 6, "medium": 12, "easy": 6},
    "mixed_intent": {"hard": 3, "medium": 7, "easy": 2},
    "no_answer": {"hard": 15, "medium": 15, "easy": 0},
}

BAND_TARGET = {
    # type -> {band_target: n}；normal 为余量
    "single_fact": {"low_answerable": 10, "near_band": 10},
    "metadata": {"near_band": 4},
    "cross_document": {"low_answerable": 10, "near_band": 5},
    "multi_turn": {},
    "mixed_intent": {},
    "no_answer": {"low_refuse": 20},
}

CONSTRUCTION_BY_TYPE = {
    "single_fact": "natural",
    "metadata": "metadata",
    "cross_document": "cross_doc",
    "multi_turn": "follow_up",
    "mixed_intent": "natural",
    "no_answer": "out_of_corpus",
}

# 链结构：9 条链 / 24 轮；跨文档链 2 条；拒答轮 1
CHAINS = [
    # (chain_id, language, [(turn, doc_target, note)])
    ("multi-011", "zh", [
        ("python-tutorial-zh", "第 1 轮：列表/数据结构"),
        ("python-tutorial-zh", "第 2 轮：函数定义"),
        ("python-tutorial-zh", "第 3 轮：模块导入"),
        ("python-tutorial-zh", "第 4 轮：异常处理"),
    ]),
    ("multi-015", "en", [
        ("python-tutorial-en", "R1: data structures"),
        ("python-tutorial-en", "R2: functions"),
        ("python-tutorial-en", "R3: modules"),
    ]),
    ("multi-016", "en", [
        ("sqlite-lang", "R1: CREATE TABLE"),
        ("sqlite-lang", "R2: INSERT"),
    ]),
    ("multi-018", "en", [
        ("postgresql-tutorial", "R1: 创建数据库"),
        ("postgresql-tutorial", "R2: psql 命令"),
    ]),
    ("multi-020", "en", [
        ("rust-book-core", "R1: 所有权"),
        ("rust-book-core", "R2: 借用"),
    ]),
    ("multi-022", "zh", [
        ("vue-guide-zh", "R1: 模板语法"),
        ("vue-guide-zh", "R2: 响应式"),
        ("vue-guide-zh", "R3: 组件"),
    ]),
    ("multi-025", "mixed", [
        ("sqlite-lang", "R1: SELECT 语法"),
        ("postgresql-tutorial", "R2: 对比事务"),
        ("", "R3: 拒答轮（语料外比较）"),
    ]),
    ("multi-028", "mixed", [
        ("python-tutorial-zh", "R1: 中文教程内容"),
        ("python-tutorial-en", "R2: 英文教程对照"),
    ]),
    ("multi-030", "zh", [
        ("react-learn-zh", "R1: 描述界面"),
        ("react-learn-zh", "R2: 添加交互"),
        ("react-learn-zh", "R3: 管理状态"),
    ]),
]

V1_BASE = {"cross": 10, "en": 20, "meta": 10, "mixed": 15, "multi": 10,
           "noanswer": 25, "zh": 20}


def _next_id(prefix: str, counter: dict[str, int]) -> str:
    counter[prefix] = counter.get(prefix, V1_BASE.get(prefix, 0)) + 1
    return f"{prefix}-{counter[prefix]:03d}"


def build_skeleton() -> list[dict]:
    counter: dict[str, int] = {}
    cases: list[dict] = []

    # 1) 链轮（multi_turn，语言按链；难度按 multi_turn 配额精确分配）
    chain_ids: dict[str, str] = {}
    diff_seq = _quota_sequence(DIFFICULTY["multi_turn"])
    di = 0
    chain_turns: list[tuple[str, int, str, dict]] = []  # (chain_id, turn, lang, case)
    for chain_id, lang, turns in CHAINS:
        for i, (_doc, note) in enumerate(turns, start=1):
            prefix = {"zh": "multi", "en": "multi", "mixed": "multi"}[lang]
            cid = _next_id(prefix, counter)
            chain_turns.append((chain_id, i, lang, {
                "id": cid,
                "query": "",
                "query_type": "multi_turn",
                "language": lang,
                "relevant_source_ids": [],
                "relevant_chunks": [],
                "relevant_chunk_ids": [],
                "acceptable_answer_points": [],
                "should_refuse": False,
                "relevance_level": "none",
                "metadata": {
                    "difficulty": diff_seq[di % len(diff_seq)],
                    "band_target": "normal",
                    "construction": "follow_up",
                    "turn": i,
                    "follow_up_to": None,
                    "chain_id": chain_id,
                },
                "annotation": {
                    "annotated_by": "zcode-draft", "reviewed_by": "",
                    "review_status": "pending",
                    "review_notes": "LLM_ASSISTED",
                    "annotation_version": "v2.0.0", "created_at": "2026-08-05",
                },
                "doc_target": _doc,
                "note": note,
                "is_refusal_turn": chain_id == "multi-025" and i == 3,
            }))
            di += 1
    # 链内 follow_up_to 指向上一轮真实 case id
    by_chain: dict[str, list[dict]] = {}
    for chain_id, turn, _lang, case in chain_turns:
        by_chain.setdefault(chain_id, []).append((turn, case))
    for members in by_chain.values():
        members.sort(key=lambda t: t[0])
        for i, (turn, case) in enumerate(members):
            if i > 0:
                case["metadata"]["follow_up_to"] = members[i - 1][1]["id"]
    cases.extend(c for _c, _t, _l, c in chain_turns)
    chain_ids = {chain_id: members[0][1]["id"]
                 for chain_id, members in by_chain.items()}

    # 2) 非链 case：按类型×语言配额 + 难度/band_target 配额
    #    doc_target 分配表（语言 → 文档池），用于后续人工填充
    doc_pool = {
        "zh": ["python-tutorial-zh", "python-whatsnew313-zh", "python-datetime-zh",
               "vue-guide-zh", "python-glossary-zh", "sqlite-lang",
               "postgresql-tutorial", "rust-book-core", "nodejs-fs"],
        "en": ["python-tutorial-en", "sqlite-lang", "postgresql-tutorial",
               "rust-book-core", "rfc3986", "nodejs-fs", "art-of-war",
               "python-glossary-zh", "python-datetime-zh"],
        "mixed": ["python-glossary-zh", "react-learn-zh", "python-tutorial-zh",
                  "python-tutorial-en", "vue-guide-zh", "sqlite-lang"],
    }
    for qtype in ("single_fact", "metadata", "cross_document", "mixed_intent",
                  "no_answer"):
        # 预生成精确配额序列（难度 + band），按 qtype 总配额
        n_qtype = sum(QUOTA[qtype].values())
        diff_seq = _quota_sequence(DIFFICULTY[qtype])
        band_seq = _quota_sequence_band(BAND_TARGET.get(qtype, {}), n_qtype)
        di = bi = 0
        for lang, n in QUOTA[qtype].items():
            band_used = {k: 0 for k in BAND_TARGET.get(qtype, {})}
            for _ in range(n):
                diff = diff_seq[di % len(diff_seq)]
                di += 1
                band_target = band_seq[bi % len(band_seq)]
                bi += 1
                prefix = {"zh": "zh", "en": "en", "mixed": "mixed"}[lang]
                if qtype == "no_answer":
                    prefix = "noanswer"
                cases.append({
                    "id": _next_id(prefix, counter),
                    "query": "",
                    "query_type": qtype,
                    "language": lang,
                    "relevant_source_ids": [],
                    "relevant_chunks": [],
                    "relevant_chunk_ids": [],
                    "acceptable_answer_points": [],
                    "should_refuse": qtype == "no_answer",
                    "relevance_level": "none",
                    "metadata": {
                        "difficulty": diff,
                        "band_target": band_target,
                        "construction": ("out_of_corpus" if qtype == "no_answer"
                                         else "fuzzy_query" if band_target == "low_answerable"
                                         else "cross_doc" if qtype == "cross_document"
                                         else "natural"),
                        "turn": 1,
                        "follow_up_to": None,
                        "chain_id": None,
                    },
                    "annotation": {
                        "annotated_by": "zcode-draft", "reviewed_by": "",
                        "review_status": "pending",
                        "review_notes": "LLM_ASSISTED",
                        "annotation_version": "v2.0.0", "created_at": "2026-08-05",
                    },
                    "doc_target": None,
                    "note": "",
                })
    return cases


def _quota_sequence(caps: dict[str, int]) -> list[str]:
    """Exact-count sequence with deterministic anti-clumping rotation."""
    seq: list[str] = []
    for k, v in caps.items():
        seq.extend([k] * v)
    n = len(seq)
    rotated = [seq[(i * 7 + 3) % n] for i in range(n)]  # coprime step 7
    return rotated


def _quota_sequence_band(band_caps: dict[str, int], total: int) -> list[str]:
    """Band sequence: explicit band caps first (rotated), then 'normal'."""
    seq = [b for b, v in band_caps.items() for _ in range(v)]
    seq.extend(["normal"] * (total - len(seq)))
    if len(seq) != total:
        raise ValueError(f"band caps exceed total: {band_caps} vs {total}")
    n = len(seq)
    return [seq[(i * 5 + 1) % n] for i in range(n)]  # coprime step 5


def validate_quotas(cases: list[dict]) -> list[str]:
    errs: list[str] = []
    by_type_lang: dict[tuple[str, str], int] = {}
    by_type_diff: dict[tuple[str, str], int] = {}
    by_type_band: dict[tuple[str, str], int] = {}
    for c in cases:
        qt, lang = c["query_type"], c["language"]
        by_type_lang[(qt, lang)] = by_type_lang.get((qt, lang), 0) + 1
        by_type_diff[(qt, c["metadata"]["difficulty"])] = \
            by_type_diff.get((qt, c["metadata"]["difficulty"]), 0) + 1
        band = c["metadata"]["band_target"]
        if band != "normal":
            by_type_band[(qt, band)] = by_type_band.get((qt, band), 0) + 1
    for qt, lang_map in QUOTA.items():
        for lang2, cap in lang_map.items():
            got = by_type_lang.get((qt, lang2), 0)
            if got != cap:
                errs.append(f"quota {qt}x{lang2}: got {got} want {cap}")
    for qt, caps in DIFFICULTY.items():
        for diff, cap in caps.items():
            got = by_type_diff.get((qt, diff), 0)
            if got != cap:
                errs.append(f"difficulty {qt}x{diff}: got {got} want {cap}")
    for qt, bands in BAND_TARGET.items():
        for band, cap in bands.items():
            got = by_type_band.get((qt, band), 0)
            if got != cap:
                errs.append(f"band {qt}x{band}: got {got} want {cap}")
    # 链完整性
    chains: dict[str, list[dict]] = {}
    for c in cases:
        if c["metadata"].get("chain_id"):
            chains.setdefault(c["metadata"]["chain_id"], []).append(c)
    for cid, members in chains.items():
        turns = sorted(int(m["metadata"]["turn"]) for m in members)
        if turns != list(range(1, len(members) + 1)):
            errs.append(f"chain {cid} turns not contiguous: {turns}")
    if len(cases) != 150:
        errs.append(f"total cases: {len(cases)} want 150")
    ids = [c["id"] for c in cases]
    if len(set(ids)) != len(ids):
        errs.append("duplicate case ids")
    return errs


def main() -> int:
    cmd = sys.argv[1] if len(sys.argv) > 1 else "skeleton"
    if cmd == "skeleton":
        cases = build_skeleton()
        errs = validate_quotas(cases)
        if errs:
            print("QUOTA ERRORS:")
            for e in errs:
                print("  ", e)
            return 1
        out = ROOT / "evaluation" / "datasets" / "v2" / "annotations"
        out.mkdir(parents=True, exist_ok=True)
        dest = out / "skeleton.jsonl"
        dest.write_text(
            "\n".join(json.dumps(c, ensure_ascii=False) for c in cases) + "\n",
            encoding="utf-8")
        print(f"wrote {dest} ({len(cases)} cases)")
        return 0
    if cmd == "validate" and len(sys.argv) >= 3:
        rows = [json.loads(l) for l in
                open(sys.argv[2], encoding="utf-8") if l.strip()]
        errs = validate_quotas(rows)
        if errs:
            for e in errs:
                print("  ", e)
            return 1
        print(f"OK: {len(rows)} cases, quotas satisfied")
        return 0
    print(__doc__)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
