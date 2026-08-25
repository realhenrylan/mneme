"""只读诊断：A/B/C 按 case 对齐分析 reranker 回归。

读取 auto-run-20260804T121410/ 的 dev-full / holdout-full 产物，
不修改任何文件。输出：
1. A vs B 胜负数量（answer_point_coverage）
2. 切片分布：query_type / language / graph_target / source-only / multi_turn
3. reranker 前后相关 chunk/source 是否被挤出 context
4. context token / source 多样性 / citation / 拒答 / coverage 变化
5. 典型失败 case 清单
"""
from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

RUN = Path("results/graph-gate/auto-run-20260804T121410")
EPS = 1e-6


def load_jsonl(path):
    return [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]


def load_dev():
    gen = load_jsonl(RUN / "dev-full" / "generation-cases.jsonl")
    ret = load_jsonl(RUN / "dev-full" / "retrieval-cases.jsonl")
    return gen, ret


def align(gen, ret):
    """按 case_id + arm 对齐。返回 dict[case_id] = {arm: gen_record} 与 ret 同构。"""
    g_by = defaultdict(dict)
    for r in gen:
        g_by[r["case_id"]][r["arm"]] = r
    r_by = defaultdict(dict)
    for r in ret:
        r_by[r["case_id"]][r["arm"]] = r
    return g_by, r_by


def main():
    gen, ret = load_dev()
    g_by, r_by = align(gen, ret)
    case_ids = sorted(g_by.keys())
    print(f"cases: {len(case_ids)}")

    # 1. A vs B 胜负（answer_point_coverage）
    wins = Counter()  # a_win / b_win / tie
    wins_source = defaultdict(Counter)  # 切片 -> counter
    typical_loss = []  # (case, a_apc, b_apc, c_apc, query)
    details = []
    for cid in case_ids:
        ga = g_by[cid].get("standard")
        gb = g_by[cid].get("standard-rerank")
        gc = g_by[cid].get("graph-rerank")
        if not (ga and gb):
            continue
        a_apc = ga.get("answer_point_coverage", 0) or 0
        b_apc = gb.get("answer_point_coverage", 0) or 0
        c_apc = gc.get("answer_point_coverage", 0) if gc else None
        if a_apc > b_apc + EPS:
            outcome = "A_win"
        elif b_apc > a_apc + EPS:
            outcome = "B_win"
        else:
            outcome = "tie"
        wins[outcome] += 1

        # 切片
        qtype = ga.get("query_type")
        lang = ga.get("language")
        should_refuse = bool(ga.get("should_refuse"))
        ret_a = r_by[cid].get("standard", {})
        has_truth = ret_a.get("has_chunk_truth", True)
        is_source_only = (not has_truth) and bool(ret_a.get("relevant_source_ids"))
        is_multi = qtype == "multi_turn"
        is_gt = qtype in ("cross_document", "mixed_intent")

        slices = []
        slices.append(f"qtype:{qtype}")
        slices.append(f"lang:{lang}")
        if is_gt:
            slices.append("graph_target")
        if is_source_only:
            slices.append("source_only")
        if is_multi:
            slices.append("multi_turn")
        if should_refuse:
            slices.append("refusal")
        for s in slices:
            wins_source[s][outcome] += 1

        details.append({
            "case_id": cid, "query": ga.get("query", "")[:60],
            "qtype": qtype, "lang": lang,
            "should_refuse": should_refuse, "is_source_only": is_source_only,
            "A": a_apc, "B": b_apc, "C": c_apc, "outcome": outcome,
        })
        if outcome == "A_win" and not should_refuse and len(typical_loss) < 30:
            typical_loss.append(details[-1])

    print(f"\n=== A vs B 胜负（answer_point_coverage, dev {len(case_ids)} cases）===")
    print(f"  A_win={wins['A_win']}  B_win={wins['B_win']}  tie={wins['tie']}")

    print(f"\n=== 切片胜负分布 ===")
    for s in sorted(wins_source.keys()):
        c = wins_source[s]
        print(f"  {s:22s} A_win={c['A_win']:3d}  B_win={c['B_win']:3d}  tie={c['tie']:3d}")

    # 2. reranker 前后相关 chunk 是否被挤出 context
    print(f"\n=== reranker 前后 context 相关 chunk 保留（chunk truth cases）===")
    ctx_keep = Counter()  # A_keeps / B_keeps / both / neither
    squeeze_examples = []
    for cid in case_ids:
        ra = r_by[cid].get("standard")
        rb = r_by[cid].get("standard-rerank")
        if not (ra and rb):
            continue
        rel = set(ra.get("relevant_chunk_ids") or [])
        if not rel:
            continue
        ctx_a = set(ra.get("context_chunk_ids") or [])
        ctx_b = set(rb.get("context_chunk_ids") or [])
        a_keeps = bool(ctx_a & rel)
        b_keeps = bool(ctx_b & rel)
        if a_keeps and b_keeps:
            key = "both"
        elif a_keeps and not b_keeps:
            key = "A_only"
        elif not a_keeps and b_keeps:
            key = "B_only"
        else:
            key = "neither"
        ctx_keep[key] += 1
        if key == "A_only" and len(squeeze_examples) < 20:
            squeeze_examples.append((cid, sorted(ctx_a & rel)[:2], sorted(ctx_b & rel)[:2],
                                     ra.get("query", "")[:50]))
    print(f"  {dict(ctx_keep)}")
    print(f"\n  A 保留但 B 挤出的 case（{len(squeeze_examples)} 个示例）:")
    for cid, rel_in_a, rel_in_b, q in squeeze_examples[:10]:
        print(f"    {cid:14s} A_ctx_rels={rel_in_a}  B_ctx_rels={rel_in_b}  q={q!r}")

    # 3. context token / source 多样性 / citation / 拒答
    print(f"\n=== context token / source 多样性 / citation 数量 ===")
    ctx_tok = {"A": [], "B": []}
    src_cnt = {"A": [], "B": []}
    cit_cnt = {"A": [], "B": []}
    refusal = {"A": 0, "B": 0}
    for cid in case_ids:
        for arm_key, arm in (("A", "standard"), ("B", "standard-rerank")):
            ra = r_by[cid].get(arm)
            ga = g_by[cid].get(arm)
            if not (ra and ga):
                continue
            ctx_tok[arm_key].append(ra.get("context_token_count") or 0)
            src_cnt[arm_key].append(len(ra.get("context_source_ids") or []))
            cit_cnt[arm_key].append(len(ra.get("context_chunk_ids") or []))
            if ga.get("correctly_refused") is False:
                refusal[arm_key] += 1
    for arm_key in ("A", "B"):
        n = len(ctx_tok[arm_key])
        print(f"  {arm_key}: ctx_tokens avg={sum(ctx_tok[arm_key])/n:.0f}  "
              f"ctx_sources avg={sum(src_cnt[arm_key])/n:.2f}  "
              f"ctx_chunks avg={sum(cit_cnt[arm_key])/n:.2f}  "
              f"false_refusals={refusal[arm_key]}/{n}")

    # 4. 典型失败 case（A 胜 B 且差 > 0.2，非拒答）
    print(f"\n=== 典型失败 case（A - B > 0.2, answerable）===")
    big = [d for d in details if d["outcome"] == "A_win" and not d["should_refuse"]
           and d["A"] - d["B"] > 0.2]
    big.sort(key=lambda d: -(d["A"] - d["B"]))
    for d in big[:15]:
        print(f"  {d['case_id']:14s} {d['qtype']:14s} {d['lang']:6s} "
              f"A={d['A']:.3f} B={d['B']:.3f} C={d['C'] if d['C'] is not None else 0:.3f} "
              f"q={d['query']!r}")

    # 5. B 胜 A 的 case（reranker 可能有效的场景）
    print(f"\n=== B 胜 A 的 case ===")
    b_wins = [d for d in details if d["outcome"] == "B_win"]
    b_wins.sort(key=lambda d: -(d["B"] - d["A"]))
    print(f"  共 {len(b_wins)} 个")
    for d in b_wins[:10]:
        print(f"  {d['case_id']:14s} {d['qtype']:14s} {d['lang']:6s} "
              f"A={d['A']:.3f} B={d['B']:.3f} C={d['C'] if d['C'] is not None else 0:.3f} "
              f"q={d['query']!r}")

    # 6. holdout 快速统计
    print(f"\n=== holdout A vs B ===")
    gen_h = load_jsonl(RUN / "holdout-full" / "generation-cases.jsonl")
    ret_h = load_jsonl(RUN / "holdout-full" / "retrieval-cases.jsonl")
    g_h, r_h = align(gen_h, ret_h)
    hw = Counter()
    for cid, arms in g_h.items():
        ga, gb = arms.get("standard"), arms.get("standard-rerank")
        if not (ga and gb):
            continue
        a, b = ga.get("answer_point_coverage", 0) or 0, gb.get("answer_point_coverage", 0) or 0
        if a > b + EPS:
            hw["A_win"] += 1
        elif b > a + EPS:
            hw["B_win"] += 1
        else:
            hw["tie"] += 1
    print(f"  {dict(hw)}")


if __name__ == "__main__":
    main()
