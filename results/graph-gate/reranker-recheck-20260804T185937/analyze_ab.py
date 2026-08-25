"""reranker-recheck A/B 配对分析（只读，AUTOMATED_DIAGNOSTIC）。

输入：reranker-recheck-<ts>/{dev-full,holdout-full}/ 的
retrieval-cases.jsonl 与 generation-cases.jsonl。
输出：ab-analysis.json（全部数字）+ 终端摘要。

覆盖：
- retrieval：chunk context recall、candidate recall、相关 chunk 保留率/挤出率、
  source recall@5/10、context source recall/coverage
- generation：answer_point_coverage、citation validity、无引用答案数、
  false refusal、延迟/token
- A/B 配对：win/loss/tie、paired bootstrap CI（block 重采样，seed 42）、
  McNemar exact（citation 有效性与拒答错误）
- 切片：language / query_type / multi_turn / source_only / graph_target
- 同源第 4 个相关 chunk 保留（需索引 chunk→source 映射，只读加载）
- 公平性审计：共享 QueryPlan（rewrite_ms 逐 case 一致）、A 无 rerank、
  双臂 context 长度/每 source 上限 ≤3 一致
"""
from __future__ import annotations

import json
import math
import random
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
OUT = Path(__file__).resolve().parent
GRAPH_TARGET_TYPES = {"cross_document", "mixed_intent"}


def load_records(path: Path) -> dict[str, dict[str, dict]]:
    """读取 JSONL → {case_id: {arm: record}}，集合字段还原为 set。"""
    by_case: dict[str, dict[str, dict]] = defaultdict(dict)
    for line in path.read_text(encoding="utf-8").splitlines():
        r = json.loads(line)
        r["relevant_chunk_ids"] = set(r.get("relevant_chunk_ids") or [])
        r["relevant_source_ids"] = set(r.get("relevant_source_ids") or [])
        by_case[r["case_id"]][r["arm"]] = r
    return dict(by_case)


def chunk_source_map() -> dict[str, str]:
    """从索引加载 chunk_id → source 标签（只读，与评测同口径）。"""
    import json as _json
    from evaluation.compare import _source_label_from_meta
    from src.rag import prepare_index
    _, collection, _, _, all_metadatas = prepare_index(
        [str(p) for p in (ROOT / "test_texts").glob("*") if p.is_file()],
        "eval-autorun-lock", force_rebuild=False,
    )
    data = collection.get()
    return {
        cid: _source_label_from_meta(meta)
        for cid, meta in zip(data["ids"], all_metadatas)
    }


def mcnemar_exact(binary_a: list[bool], binary_b: list[bool]) -> dict:
    """两侧 McNemar exact（与评测框架同算法）。True = 错误。"""
    n01 = sum(1 for a, b in zip(binary_a, binary_b) if (not a) and b)
    n10 = sum(1 for a, b in zip(binary_a, binary_b) if a and (not b))
    n = n01 + n10
    if n == 0:
        p = 1.0
    else:
        k_min = min(n01, n10)
        tail = sum(math.comb(n, k) * (0.5 ** n) for k in range(k_min + 1))
        p = min(1.0, 2.0 * tail)
    return {"n_pairs": len(binary_a), "n_discordant": n,
            "a_only": n10, "b_only": n01, "p_value": p}


def paired_bootstrap_ci(
    pairs: list[tuple[str, float]], chains: dict[str, list[str]],
    n_iter: int = 1000, seed: int = 42,
) -> dict:
    """Block 重采样 paired bootstrap 95% CI（与评测框架同算法）。"""
    if not pairs:
        return {"n_pairs": 0, "mean_delta": None, "ci95_low": None,
                "ci95_high": None, "n_blocks": 0}
    block_map: dict[str, list[str]] = {
        root: [c.id for c in chain] for root, chain in chains.items()
    }
    blocks: list[list[tuple[str, float]]] = []
    assigned: set[str] = set()
    for case_id, delta in pairs:
        if case_id in assigned:
            continue
        root = next((r for r, ids in block_map.items() if case_id in ids), None)
        if root:
            bp = [(cid, d) for (cid, d) in pairs if cid in block_map[root]]
            blocks.append(bp)
            assigned.update(c for c, _ in bp)
        else:
            blocks.append([(case_id, delta)])
            assigned.add(case_id)
    rng = random.Random(seed)
    means = []
    for _ in range(n_iter):
        sampled = [d for _ in range(len(blocks)) for _, d in rng.choice(blocks)]
        means.append(sum(sampled) / len(sampled))
    means.sort()
    mean_delta = sum(d for _, d in pairs) / len(pairs)
    return {
        "n_pairs": len(pairs), "n_blocks": len(blocks),
        "mean_delta": mean_delta,
        "ci95_low": means[int(0.025 * len(means))],
        "ci95_high": means[int(0.975 * len(means))],
        "bootstrap_iterations": n_iter, "bootstrap_seed": seed,
    }


def analyze_split(split_dir: Path, c2s: dict[str, str]) -> dict:
    ret = load_records(split_dir / "retrieval-cases.jsonl")
    gen = load_records(split_dir / "generation-cases.jsonl")
    case_ids = sorted(ret.keys())
    if not case_ids:
        return {"error": "no retrieval records"}
    a_arm, b_arm = "standard", "standard-rerank"
    chains = build_chains(ROOT / "evaluation/datasets/v1.jsonl", case_ids)

    # ── per-case paired rows ──
    rows = []
    for cid in case_ids:
        ra, rb = ret[cid].get(a_arm), ret[cid].get(b_arm)
        if ra is None or rb is None:
            continue
        ga, gb = (gen.get(cid, {}).get(a_arm)), (gen.get(cid, {}).get(b_arm))
        row = {"case_id": cid, "language": ra["language"],
               "query_type": ra["query_type"],
               "should_refuse": ra["should_refuse"],
               "has_chunk_truth": ra["has_chunk_truth"],
               "relevant_chunk_ids": sorted(ra["relevant_chunk_ids"]),
               "relevant_source_ids": sorted(ra["relevant_source_ids"])}
        for tag, r in (("A", ra), ("B", rb)):
            rel = r["relevant_chunk_ids"]
            cand = set(r["candidate_chunk_ids"])
            ctx = set(r["context_chunk_ids"])
            cand_rel = cand & rel
            row[f"cand_n_{tag}"] = len(r["candidate_chunk_ids"])
            row[f"ctx_n_{tag}"] = len(r["context_chunk_ids"])
            row[f"ctx_tokens_{tag}"] = r.get("context_token_count")
            row[f"candidate_recall_{tag}"] = (
                len(cand_rel) / len(rel) if rel else 0.0)
            row[f"context_recall_{tag}"] = (
                len(ctx & rel) / len(rel) if rel else 0.0)
            row[f"context_precision_{tag}"] = (
                len(ctx & rel) / len(ctx) if ctx else 0.0)
            row[f"retention_{tag}"] = (
                len(ctx & rel) / len(cand_rel) if cand_rel else None)
            row[f"squeeze_{tag}"] = (
                len(cand_rel - ctx) / len(cand_rel) if cand_rel else None)
            src_rel = r["relevant_source_ids"]
            if src_rel:
                row[f"source_recall5_{tag}"] = (
                    len(set(r["candidate_source_ids"][:5]) & src_rel)
                    / len(src_rel))
                row[f"source_recall10_{tag}"] = (
                    len(set(r["candidate_source_ids"][:10]) & src_rel)
                    / len(src_rel))
                cctx = set(r["context_source_ids"])
                row[f"ctx_source_recall_{tag}"] = (
                    len(cctx & src_rel) / len(src_rel))
                row[f"ctx_source_coverage_{tag}"] = (
                    len(cctx & src_rel) / len(cctx) if cctx else 0.0)
            row[f"rerank_ms_{tag}"] = r.get("rerank_ms", 0.0)
            row[f"rewrite_ms_{tag}"] = r.get("rewrite_ms", 0.0)
            row[f"total_retrieval_ms_{tag}"] = r.get("total_retrieval_ms", 0.0)
        # 同源相关 chunk 排名/保留（第 4 个场景）
        for tag, r in (("A", ra), ("B", rb)):
            src_rank: dict[str, int] = defaultdict(int)
            retained_4plus = []
            for rank, cid in enumerate(r["candidate_chunk_ids"], start=1):
                if cid in r["relevant_chunk_ids"]:
                    s = c2s.get(cid, "?")
                    src_rank[s] += 1
                    if src_rank[s] == 4:
                        retained_4plus.append(
                            (cid, s, cid in set(r["context_chunk_ids"])))
            row[f"fourth_chunk_retained_{tag}"] = retained_4plus
        # 每个相关 chunk：同 source 候选内排名 + 是否进 context（候选池 A/B 相同）
        row["rel_chunk_same_source"] = []
        cand_set = set(ra["candidate_chunk_ids"])
        for rc in sorted(ra["relevant_chunk_ids"]):
            if rc not in cand_set:
                continue
            src = c2s.get(rc, "?")
            rc_idx = ra["candidate_chunk_ids"].index(rc)
            rank_in_source = 1 + sum(
                1 for cid in ra["candidate_chunk_ids"][:rc_idx]
                if c2s.get(cid, "?") == src)
            row["rel_chunk_same_source"].append({
                "chunk": rc, "source": src,
                "rank_in_source": rank_in_source,
                "in_context_A": rc in set(ra["context_chunk_ids"]),
                "in_context_B": rc in set(rb["context_chunk_ids"]),
            })
        if ga and gb:
            row["answer_point_coverage_A"] = ga["answer_point_coverage"]
            row["answer_point_coverage_B"] = gb["answer_point_coverage"]
            row["citation_validity_A"] = ga["citation_id_validity"]
            row["citation_validity_B"] = gb["citation_id_validity"]
            row["citation_precision_A"] = ga["citation_precision"]
            row["citation_precision_B"] = gb["citation_precision"]
            row["citation_recall_A"] = ga["citation_recall"]
            row["citation_recall_B"] = gb["citation_recall"]
            row["correctly_refused_A"] = ga.get("correctly_refused")
            row["correctly_refused_B"] = gb.get("correctly_refused")
            row["gen_ms_A"] = ga.get("total_ms", 0.0)
            row["gen_ms_B"] = gb.get("total_ms", 0.0)
            row["tokens_A"] = ga.get("total_tokens")
            row["tokens_B"] = gb.get("total_tokens")
        rows.append(row)

    # ── 聚合 ──
    def mean(vals, key=None):
        vs = [v for v in vals if v is not None and v == v]
        return (sum(vs) / len(vs)) if vs else None

    chunk_rows = [r for r in rows if r["has_chunk_truth"]
                  and not r["should_refuse"]]
    src_rows = [r for r in rows if not r["should_refuse"]
                and r["relevant_source_ids"]]
    ans_rows = [r for r in rows if not r["should_refuse"] and
                "answer_point_coverage_A" in r]

    def col(rows_, key):
        return [r[key] for r in rows_ if key in r]

    agg = {
        "n_cases": len(rows),
        "n_chunk_truth": len(chunk_rows),
        "n_source_valid": len(src_rows),
        "n_answerable_gen": len(ans_rows),
        "retrieval": {
            "candidate_recall": {"A": mean(col(chunk_rows, "candidate_recall_A")),
                                 "B": mean(col(chunk_rows, "candidate_recall_B"))},
            "context_recall": {"A": mean(col(chunk_rows, "context_recall_A")),
                               "B": mean(col(chunk_rows, "context_recall_B"))},
            "context_precision": {"A": mean(col(chunk_rows, "context_precision_A")),
                                  "B": mean(col(chunk_rows, "context_precision_B"))},
            "retention": {"A": mean(col(chunk_rows, "retention_A")),
                          "B": mean(col(chunk_rows, "retention_B"))},
            "squeeze": {"A": mean(col(chunk_rows, "squeeze_A")),
                        "B": mean(col(chunk_rows, "squeeze_B"))},
            "source_recall@5": {"A": mean(col(src_rows, "source_recall5_A")),
                                "B": mean(col(src_rows, "source_recall5_B"))},
            "source_recall@10": {"A": mean(col(src_rows, "source_recall10_A")),
                                 "B": mean(col(src_rows, "source_recall10_B"))},
            "context_source_recall": {"A": mean(col(src_rows, "ctx_source_recall_A")),
                                      "B": mean(col(src_rows, "ctx_source_recall_B"))},
            "context_source_coverage": {"A": mean(col(src_rows, "ctx_source_coverage_A")),
                                        "B": mean(col(src_rows, "ctx_source_coverage_B"))},
        },
        "generation": {
            "answer_point_coverage": {
                "A": mean(col(ans_rows, "answer_point_coverage_A")),
                "B": mean(col(ans_rows, "answer_point_coverage_B"))},
            "citation_id_validity": {
                "A": mean(col(ans_rows, "citation_validity_A")),
                "B": mean(col(ans_rows, "citation_validity_B"))},
            "citation_precision": {
                "A": mean(col(ans_rows, "citation_precision_A")),
                "B": mean(col(ans_rows, "citation_precision_B"))},
            "citation_recall": {
                "A": mean(col(ans_rows, "citation_recall_A")),
                "B": mean(col(ans_rows, "citation_recall_B"))},
            "n_no_citation_A": sum(1 for r in ans_rows
                                   if r["citation_validity_A"] == 0.0),
            "n_no_citation_B": sum(1 for r in ans_rows
                                   if r["citation_validity_B"] == 0.0),
            "false_refusal_A": sum(1 for r in ans_rows
                                   if r["correctly_refused_A"] is False),
            "false_refusal_B": sum(1 for r in ans_rows
                                   if r["correctly_refused_B"] is False),
            "false_answer_A": sum(1 for r in rows if r["should_refuse"]
                                  and r.get("correctly_refused_A") is not True),
            "false_answer_B": sum(1 for r in rows if r["should_refuse"]
                                  and r.get("correctly_refused_B") is not True),
            "gen_ms_mean": {"A": mean(col(ans_rows, "gen_ms_A")),
                            "B": mean(col(ans_rows, "gen_ms_B"))},
            "tokens_mean": {"A": mean(col(ans_rows, "tokens_A")),
                            "B": mean(col(ans_rows, "tokens_B"))},
        },
    }

    # ── 配对检验（answer_point_coverage） ──
    cov_pairs = [(r["case_id"], r["answer_point_coverage_B"]
                  - r["answer_point_coverage_A"]) for r in ans_rows]
    agg["paired_cov"] = paired_bootstrap_ci(cov_pairs, chains)
    win = sum(1 for _, d in cov_pairs if d > 1e-9)
    loss = sum(1 for _, d in cov_pairs if d < -1e-9)
    tie = len(cov_pairs) - win - loss
    agg["cov_wlt"] = {"b_win": win, "b_loss": loss, "tie": tie,
                      "n": len(cov_pairs)}

    # context_recall 配对
    ctx_pairs = [(r["case_id"], (r["context_recall_B"] or 0.0)
                  - (r["context_recall_A"] or 0.0)) for r in chunk_rows]
    agg["paired_ctx_recall"] = paired_bootstrap_ci(ctx_pairs, chains)
    win = sum(1 for _, d in ctx_pairs if d > 1e-9)
    loss = sum(1 for _, d in ctx_pairs if d < -1e-9)
    agg["ctx_wlt"] = {"b_win": win, "b_loss": loss,
                      "tie": len(ctx_pairs) - win - loss, "n": len(ctx_pairs)}

    # McNemar：citation 有效（A/B 错误 = validity<1.0）
    cit_pairs = [(r["citation_validity_A"], r["citation_validity_B"])
                 for r in ans_rows]
    agg["mcnemar_citation"] = mcnemar_exact(
        [v < 1.0 for v, _ in cit_pairs],
        [v < 1.0 for _, v in cit_pairs])
    # McNemar：拒答错误（refusal 假答 + answerable 误拒）
    ref_pairs = [(r.get("correctly_refused_A"), r.get("correctly_refused_B"))
                 for r in rows if r.get("correctly_refused_A") is not None
                 and r.get("correctly_refused_B") is not None]
    if ref_pairs:
        agg["mcnemar_refusal"] = mcnemar_exact(
            [not a for a, _ in ref_pairs],
            [not b for _, b in ref_pairs])
    else:
        agg["mcnemar_refusal"] = {"n_pairs": 0}

    # ── 切片 ──
    def slice_stats(name, pred):
        sub = [r for r in ans_rows if pred(r)]
        ctx_sub = [r for r in chunk_rows if pred(r)]
        if not sub:
            return {"n": 0}
        w = sum(1 for r in sub
                if r["answer_point_coverage_B"]
                > r["answer_point_coverage_A"] + 1e-9)
        l = sum(1 for r in sub
                if r["answer_point_coverage_B"]
                < r["answer_point_coverage_A"] - 1e-9)
        return {
            "n": len(sub),
            "cov_A": mean([r["answer_point_coverage_A"] for r in sub]),
            "cov_B": mean([r["answer_point_coverage_B"] for r in sub]),
            "cov_delta": mean([r["answer_point_coverage_B"]
                               - r["answer_point_coverage_A"] for r in sub]),
            "b_win": w, "b_loss": l, "tie": len(sub) - w - l,
            "ctx_recall_A": mean([r["context_recall_A"] for r in ctx_sub]),
            "ctx_recall_B": mean([r["context_recall_B"] for r in ctx_sub]),
            "ctx_delta": mean([(r["context_recall_B"] or 0.0)
                               - (r["context_recall_A"] or 0.0)
                               for r in ctx_sub]),
        }

    agg["slices"] = {
        "by_language": {lang: slice_stats(f"lang_{lang}",
                                          lambda r, l=lang: r["language"] == l)
                        for lang in ("zh", "en", "mixed")},
        "by_query_type": {qt: slice_stats(f"qt_{qt}",
                                          lambda r, q=qt: r["query_type"] == q)
                          for qt in sorted({r["query_type"] for r in rows})},
        "multi_turn": slice_stats("multi_turn",
                                  lambda r: r["query_type"] == "multi_turn"),
        "source_only": slice_stats("source_only",
                                   lambda r: not r["has_chunk_truth"]
                                   and bool(r["relevant_source_ids"])),
        "graph_target": slice_stats(
            "graph_target",
            lambda r: r["query_type"] in GRAPH_TARGET_TYPES),
    }
    # source_only 无 cov 列（不在 answerable coverage 分母？仍在 gen 中）
    # → 对 source_only 单独用 ctx/source 指标
    so = [r for r in rows if not r["has_chunk_truth"]
          and r["relevant_source_ids"]]
    agg["slices"]["source_only_retrieval"] = {
        "n": len(so),
        "ctx_source_recall_A": mean(col(so, "ctx_source_recall_A")),
        "ctx_source_recall_B": mean(col(so, "ctx_source_recall_B")),
        "ctx_source_coverage_A": mean(col(so, "ctx_source_coverage_A")),
        "ctx_source_coverage_B": mean(col(so, "ctx_source_coverage_B")),
    }

    # ── 同源第 4 个相关 chunk 保留 ──
    four = {"A": {"cases_4plus": 0, "retained": 0},
            "B": {"cases_4plus": 0, "retained": 0}}
    four_detail = []
    for r in chunk_rows:
        for tag in ("A", "B"):
            lst = r.get(f"fourth_chunk_retained_{tag}") or []
            if lst:
                four[tag]["cases_4plus"] += 1
                if any(ok for _, _, ok in lst):
                    four[tag]["retained"] += 1
        if r.get("fourth_chunk_retained_A") or r.get(
                "fourth_chunk_retained_B"):
            four_detail.append({
                "case_id": r["case_id"],
                "A": [{"chunk": c, "source": s, "retained": ok}
                      for c, s, ok in (r.get("fourth_chunk_retained_A") or [])],
                "B": [{"chunk": c, "source": s, "retained": ok}
                      for c, s, ok in (r.get("fourth_chunk_retained_B") or [])],
            })
    agg["fourth_chunk_same_source"] = {"summary": four,
                                       "detail": four_detail}

    # ── 同 source 候选内排名 ≥4 的相关 chunk 保留（diversity 挤出场景） ──
    ge4 = {"chunks": 0, "cases": set(),
           "retained_A": 0, "retained_B": 0}
    lt4 = {"chunks": 0, "retained_A": 0, "retained_B": 0}
    ge4_detail = []
    for r in chunk_rows:
        for item in r.get("rel_chunk_same_source") or []:
            if item["rank_in_source"] >= 4:
                ge4["chunks"] += 1
                ge4["cases"].add(r["case_id"])
                ge4["retained_A"] += int(item["in_context_A"])
                ge4["retained_B"] += int(item["in_context_B"])
                ge4_detail.append({**item, "case_id": r["case_id"],
                                   "query_type": r["query_type"]})
            else:
                lt4["chunks"] += 1
                lt4["retained_A"] += int(item["in_context_A"])
                lt4["retained_B"] += int(item["in_context_B"])
    ge4["cases"] = sorted(ge4["cases"])
    agg["same_source_rank_ge4"] = {
        "summary": ge4, "lt4": lt4, "detail": ge4_detail}

    # ── 公平性审计 ──
    same_plan = all(
        abs((r.get("rewrite_ms_A") or 0.0) - (r.get("rewrite_ms_B") or 0.0))
        < 1.0 for r in rows)
    a_rerank = mean([r["rerank_ms_A"] for r in rows])
    b_rerank = mean([r["rerank_ms_B"] for r in rows])
    ctx_len_max = {"A": max((r["ctx_n_A"] for r in rows), default=0),
                   "B": max((r["ctx_n_B"] for r in rows), default=0)}
    cand_len = {"A": [r["cand_n_A"] for r in rows],
                "B": [r["cand_n_B"] for r in rows]}
    agg["fairness_audit"] = {
        "shared_query_plan_rewrite_equal": same_plan,
        "rerank_ms_mean": {"A": a_rerank, "B": b_rerank},
        "rerank_ms_nonzero_B": sum(1 for r in rows if r["rerank_ms_B"] > 1.0),
        "rerank_ms_zero_A": sum(1 for r in rows if r["rerank_ms_A"] < 1.0),
        "context_len_max": ctx_len_max,
        "candidate_len_mean": {"A": mean(cand_len["A"]),
                               "B": mean(cand_len["B"])},
        "context_selector": "select_context_candidates(top_k=min(k,20), "
                            "max_per_source=3) applied identically to both arms",
    }
    return agg


def build_chains(dataset_path: Path, case_ids: list[str]) -> dict[str, list]:
    """从数据集重建多轮链（root_id -> case 列表，供 block 重采样）。"""
    cases = [json.loads(l) for l in
             dataset_path.read_text(encoding="utf-8").splitlines()]
    by_id = {c["id"]: c for c in cases}
    idset = set(case_ids)
    follow = {c["id"]: c["metadata"]["follow_up_to"] for c in cases
              if c.get("metadata", {}).get("follow_up_to")}
    roots = [cid for cid in case_ids
             if not by_id.get(cid, {}).get("metadata", {}).get("follow_up_to")]
    chains: dict[str, list] = {}
    for root in roots:
        chain = [root]
        cur = root
        seen = {root}
        while cur in follow and follow[cur] in idset and follow[cur] not in seen:
            cur = follow[cur]
            seen.add(cur)
            chain.append(cur)
        if len(chain) > 1:
            chains[root] = chain
    return chains


def main() -> None:
    dev_dir = OUT / "dev-full"
    hold_dir = OUT / "holdout-full"
    c2s = chunk_source_map()
    print(f"chunk→source map: {len(c2s)} chunks")
    result = {"split": {}, }
    for name, d in (("dev", dev_dir), ("holdout", hold_dir)):
        if d.exists():
            result["split"][name] = analyze_split(d, c2s)
        else:
            result["split"][name] = {"error": "missing dir"}
    (OUT / "ab-analysis.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=1) + "\n",
        encoding="utf-8")
    for name in ("dev", "holdout"):
        s = result["split"][name]
        if "error" in s:
            print(f"[{name}] ERROR {s['error']}")
            continue
        print(f"\n=== {name} (n={s['n_cases']}, chunk={s['n_chunk_truth']}, "
              f"src={s['n_source_valid']}, gen={s['n_answerable_gen']}) ===")
        r = s["retrieval"]
        print(f"  ctx_recall   A={r['context_recall']['A']:.3f} "
              f"B={r['context_recall']['B']:.3f}  "
              f"cand_recall A={r['candidate_recall']['A']:.3f} "
              f"B={r['candidate_recall']['B']:.3f}")
        print(f"  retention    A={r['retention']['A']:.3f} "
              f"B={r['retention']['B']:.3f}  "
              f"squeeze A={r['squeeze']['A']:.3f} B={r['squeeze']['B']:.3f}")
        print(f"  src_recall@5 A={r['source_recall@5']['A']:.3f} "
              f"B={r['source_recall@5']['B']:.3f}  "
              f"ctx_src_recall A={r['context_source_recall']['A']:.3f} "
              f"B={r['context_source_recall']['B']:.3f}")
        g = s["generation"]
        print(f"  cov          A={g['answer_point_coverage']['A']:.3f} "
              f"B={g['answer_point_coverage']['B']:.3f}  "
              f"W/L/T={s['cov_wlt']['b_win']}/{s['cov_wlt']['b_loss']}"
              f"/{s['cov_wlt']['tie']}")
        pc = s["paired_cov"]
        if pc.get("mean_delta") is not None:
            print(f"  cov delta    {pc['mean_delta']:+.3f} "
                  f"95%CI [{pc['ci95_low']:+.3f}, {pc['ci95_high']:+.3f}] "
                  f"(n={pc['n_pairs']}, blocks={pc['n_blocks']})")
        m = s["mcnemar_citation"]
        print(f"  mcnemar cit  discord={m['n_discordant']} "
              f"B_only={m['b_only']} p={m['p_value']:.4f}")
        if "mcnemar_refusal" in s:
            mr = s["mcnemar_refusal"]
            print(f"  mcnemar ref  discord={mr['n_discordant']} "
                  f"p={mr['p_value']:.4f}")
        print(f"  no-citation  A={g['n_no_citation_A']} "
              f"B={g['n_no_citation_B']}  "
              f"false_refusal A={g['false_refusal_A']} "
              f"B={g['false_refusal_B']}  "
              f"false_answer A={g['false_answer_A']} B={g['false_answer_B']}")
        fa = s["fairness_audit"]
        print(f"  fairness     shared_plan={fa['shared_query_plan_rewrite_equal']} "
              f"rerank A={fa['rerank_ms_mean']['A']:.1f}ms "
              f"B={fa['rerank_ms_mean']['B']:.1f}ms "
              f"ctx_max A={fa['context_len_max']['A']} "
              f"B={fa['context_len_max']['B']}")
        f4 = s["fourth_chunk_same_source"]["summary"]
        print(f"  4th-chunk    A: {f4['A']['retained']}/"
              f"{f4['A']['cases_4plus']} retained, "
              f"B: {f4['B']['retained']}/{f4['B']['cases_4plus']} retained")
        for name2, sl in s["slices"].items():
            if isinstance(sl, dict) and "n" in sl:
                items = [(name2, sl)]
            elif isinstance(sl, dict):
                items = [(f"{name2}.{k}", v) for k, v in sl.items()
                         if isinstance(v, dict) and v.get("n")]
            else:
                items = []
            for label, sub in items:
                ca = sub.get('ctx_recall_A'); cb = sub.get('ctx_recall_B')
                ca_s = f"{ca:.3f}" if ca is not None else "  -  "
                cb_s = f"{cb:.3f}" if cb is not None else "  -  "
                cov_a = sub.get('cov_A'); cov_b = sub.get('cov_B')
                cov_a_s = f"{cov_a:.3f}" if cov_a is not None else "  -  "
                cov_b_s = f"{cov_b:.3f}" if cov_b is not None else "  -  "
                print(f"  slice {label:24s} n={sub['n']:3d} "
                      f"cov A={cov_a_s} B={cov_b_s} "
                      f"W/L/T={sub.get('b_win')}/{sub.get('b_loss')}"
                      f"/{sub.get('tie')} "
                      f"ctx A={ca_s} B={cb_s}")
        ge4 = s["same_source_rank_ge4"]["summary"]
        lt4 = s["same_source_rank_ge4"]["lt4"]
        print(f"  samesrc≥4   chunks={ge4['chunks']} cases={len(ge4['cases'])} "
              f"retained A={ge4['retained_A']}/{ge4['chunks']} "
              f"B={ge4['retained_B']}/{ge4['chunks']} | "
              f"rank<4 chunks={lt4['chunks']} retained A={lt4['retained_A']} "
              f"B={lt4['retained_B']}")


if __name__ == "__main__":
    main()
