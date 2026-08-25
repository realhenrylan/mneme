"""selector-ablation S0/S3 配对分析（只读，AUTOMATED_DIAGNOSTIC）。

输入：selector-ablation-<ts>/{dev-full,holdout-full}/ 的
retrieval-cases.jsonl 与 generation-cases.jsonl。
输出：s0s3-analysis.json（全部数字）+ 终端摘要 + failures.csv（S0/S3 对齐）。

双臂定义（唯一实验变量 = context selector 同源上限）：
- S0 = selector-unlimited：max_per_source=None，不限同源（仅 top_k 截断）
- S3 = selector-cap3：max_per_source=3，每源最多 3 chunk（生产默认）

覆盖：
- retrieval：chunk context recall / candidate recall / retention / squeeze、
  source recall@5/10、context source recall/coverage（source-only 单列）
- context shape：context chunk 数、source 数、单源 context 占比、
  单源最多 chunk 数（S0 可 >3、S3 ≤3 → diversity 挤出的可观察差异）
- generation：answer_point_coverage、citation v2
  （context_supported_citation_validity 为正式 guardrail 口径）、
  citation_id_validity、fabricated/retrieved_not_in_context 计数、
  false refusal、无引用答案数、延迟/token
- S0/S3 配对：win/loss/tie、paired bootstrap CI（block 重采样，seed 42）、
  McNemar exact（citation v2 有效性与拒答错误）
- 切片：language / query_type / multi_turn / source_only / graph_target
- 同源相关 chunk 保留/挤出（rank≥4 场景，S0 vs S3）
- 公平性审计：共享 QueryPlan（rewrite_ms 逐 case 一致）、双臂均无 rerank、
  候选池逐 case 相同、S3 全 case 每源 ≤3、S0 允许同源 >3
"""
from __future__ import annotations

import csv
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

S0_ARM = "selector-unlimited"
S3_ARM = "selector-cap3"


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
            "s0_only": n10, "s3_only": n01, "p_value": p}


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


def _max_same_source_in_context(r: dict, c2s: dict[str, str]) -> int:
    """context 内同一 source 的最大 chunk 数（diversity 可观察差异）。"""
    counts: dict[str, int] = defaultdict(int)
    for cid in r["context_chunk_ids"]:
        counts[c2s.get(cid, "?")] += 1
    return max(counts.values(), default=0)


def analyze_split(split_dir: Path, c2s: dict[str, str]) -> dict:
    ret = load_records(split_dir / "retrieval-cases.jsonl")
    gen = load_records(split_dir / "generation-cases.jsonl")
    case_ids = sorted(ret.keys())
    if not case_ids:
        return {"error": "no retrieval records"}
    chains = build_chains(ROOT / "evaluation/datasets/v1.jsonl", case_ids)

    # ── per-case paired rows ──
    rows = []
    for cid in case_ids:
        r0, r3 = ret[cid].get(S0_ARM), ret[cid].get(S3_ARM)
        if r0 is None or r3 is None:
            continue
        g0, g3 = (gen.get(cid, {}).get(S0_ARM)), (gen.get(cid, {}).get(S3_ARM))
        row = {"case_id": cid, "language": r0["language"],
               "query_type": r0["query_type"],
               "should_refuse": r0["should_refuse"],
               "has_chunk_truth": r0["has_chunk_truth"],
               "relevant_chunk_ids": sorted(r0["relevant_chunk_ids"]),
               "relevant_source_ids": sorted(r0["relevant_source_ids"])}
        for tag, r in (("S0", r0), ("S3", r3)):
            rel = r["relevant_chunk_ids"]
            cand = set(r["candidate_chunk_ids"])
            ctx = set(r["context_chunk_ids"])
            cand_rel = cand & rel
            row[f"cand_n_{tag}"] = len(r["candidate_chunk_ids"])
            row[f"ctx_n_{tag}"] = len(r["context_chunk_ids"])
            row[f"ctx_tokens_{tag}"] = r.get("context_token_count")
            row[f"ctx_sources_n_{tag}"] = len(r["context_source_ids"])
            row[f"ctx_max_same_source_{tag}"] = _max_same_source_in_context(r, c2s)
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
        # 每个相关 chunk：同 source 候选内排名 + 是否进 context（候选池 S0/S3 相同）
        row["rel_chunk_same_source"] = []
        cand_set = set(r0["candidate_chunk_ids"])
        for rc in sorted(r0["relevant_chunk_ids"]):
            if rc not in cand_set:
                continue
            src = c2s.get(rc, "?")
            rc_idx = r0["candidate_chunk_ids"].index(rc)
            rank_in_source = 1 + sum(
                1 for cid in r0["candidate_chunk_ids"][:rc_idx]
                if c2s.get(cid, "?") == src)
            row["rel_chunk_same_source"].append({
                "chunk": rc, "source": src,
                "rank_in_source": rank_in_source,
                "in_context_S0": rc in set(r0["context_chunk_ids"]),
                "in_context_S3": rc in set(r3["context_chunk_ids"]),
            })
        if g0 and g3:
            row["answer_point_coverage_S0"] = g0["answer_point_coverage"]
            row["answer_point_coverage_S3"] = g3["answer_point_coverage"]
            row["citation_id_validity_S0"] = g0["citation_id_validity"]
            row["citation_id_validity_S3"] = g3["citation_id_validity"]
            # 契约 v2：context-supported 引用有效性（正式 guardrail 口径）
            row["ctx_supported_validity_S0"] = g0.get(
                "context_supported_citation_validity", 0.0)
            row["ctx_supported_validity_S3"] = g3.get(
                "context_supported_citation_validity", 0.0)
            row["fabricated_S0"] = g0.get("fabricated_citation_count", 0)
            row["fabricated_S3"] = g3.get("fabricated_citation_count", 0)
            row["not_in_context_S0"] = g0.get(
                "retrieved_not_in_context_count", 0)
            row["not_in_context_S3"] = g3.get(
                "retrieved_not_in_context_count", 0)
            row["correctly_refused_S0"] = g0.get("correctly_refused")
            row["correctly_refused_S3"] = g3.get("correctly_refused")
            row["gen_ms_S0"] = g0.get("total_ms", 0.0)
            row["gen_ms_S3"] = g3.get("total_ms", 0.0)
            row["tokens_S0"] = g0.get("total_tokens")
            row["tokens_S3"] = g3.get("total_tokens")
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
                "answer_point_coverage_S0" in r]

    def col(rows_, key):
        return [r[key] for r in rows_ if key in r]

    def both(tag_key, default=0.0):
        return {"S0": mean(col(ans_rows, tag_key + "_S0")) if ans_rows else None,
                "S3": mean(col(ans_rows, tag_key + "_S3")) if ans_rows else None}

    agg = {
        "n_cases": len(rows),
        "n_chunk_truth": len(chunk_rows),
        "n_source_valid": len(src_rows),
        "n_answerable_gen": len(ans_rows),
        "retrieval": {
            "candidate_recall": {"S0": mean(col(chunk_rows, "candidate_recall_S0")),
                                 "S3": mean(col(chunk_rows, "candidate_recall_S3"))},
            "context_recall": {"S0": mean(col(chunk_rows, "context_recall_S0")),
                               "S3": mean(col(chunk_rows, "context_recall_S3"))},
            "context_precision": {"S0": mean(col(chunk_rows, "context_precision_S0")),
                                  "S3": mean(col(chunk_rows, "context_precision_S3"))},
            "retention": {"S0": mean(col(chunk_rows, "retention_S0")),
                          "S3": mean(col(chunk_rows, "retention_S3"))},
            "squeeze": {"S0": mean(col(chunk_rows, "squeeze_S0")),
                        "S3": mean(col(chunk_rows, "squeeze_S3"))},
            "source_recall@5": {"S0": mean(col(src_rows, "source_recall5_S0")),
                                "S3": mean(col(src_rows, "source_recall5_S3"))},
            "source_recall@10": {"S0": mean(col(src_rows, "source_recall10_S0")),
                                 "S3": mean(col(src_rows, "source_recall10_S3"))},
            "context_source_recall": {"S0": mean(col(src_rows, "ctx_source_recall_S0")),
                                      "S3": mean(col(src_rows, "ctx_source_recall_S3"))},
            "context_source_coverage": {"S0": mean(col(src_rows, "ctx_source_coverage_S0")),
                                        "S3": mean(col(src_rows, "ctx_source_coverage_S3"))},
        },
        # context shape：diversity 策略的可观察差异
        "context_shape": {
            "ctx_n_mean": {"S0": mean(col(rows, "ctx_n_S0")),
                           "S3": mean(col(rows, "ctx_n_S3"))},
            "ctx_n_max": {"S0": max(col(rows, "ctx_n_S0"), default=0),
                          "S3": max(col(rows, "ctx_n_S3"), default=0)},
            "ctx_tokens_mean": {"S0": mean(col(rows, "ctx_tokens_S0")),
                                "S3": mean(col(rows, "ctx_tokens_S3"))},
            "ctx_sources_n_mean": {"S0": mean(col(rows, "ctx_sources_n_S0")),
                                   "S3": mean(col(rows, "ctx_sources_n_S3"))},
            "single_source_ratio": {
                "S0": sum(1 for r in rows if r["ctx_sources_n_S0"] <= 1) / len(rows),
                "S3": sum(1 for r in rows if r["ctx_sources_n_S3"] <= 1) / len(rows),
            },
            "ctx_max_same_source_mean": {
                "S0": mean(col(rows, "ctx_max_same_source_S0")),
                "S3": mean(col(rows, "ctx_max_same_source_S3")),
            },
            "ctx_max_same_source_max": {
                "S0": max(col(rows, "ctx_max_same_source_S0"), default=0),
                "S3": max(col(rows, "ctx_max_same_source_S3"), default=0),
            },
            "cases_with_same_source_gt3": {
                "S0": sum(1 for r in rows
                          if r["ctx_max_same_source_S0"] > 3),
                "S3": sum(1 for r in rows
                          if r["ctx_max_same_source_S3"] > 3),
            },
        },
        "generation": {
            "answer_point_coverage": both("answer_point_coverage"),
            "citation_id_validity": both("citation_id_validity"),
            "context_supported_citation_validity": both("ctx_supported_validity"),
            "fabricated_avg": both("fabricated"),
            "not_in_context_avg": both("not_in_context"),
            "n_no_citation": {"S0": sum(1 for r in ans_rows
                                        if r["citation_id_validity_S0"] == 0.0),
                              "S3": sum(1 for r in ans_rows
                                        if r["citation_id_validity_S3"] == 0.0)},
            "n_no_context_supported": {
                "S0": sum(1 for r in ans_rows
                          if r["ctx_supported_validity_S0"] == 0.0),
                "S3": sum(1 for r in ans_rows
                          if r["ctx_supported_validity_S3"] == 0.0)},
            "false_refusal": {"S0": sum(1 for r in ans_rows
                                        if r["correctly_refused_S0"] is False),
                              "S3": sum(1 for r in ans_rows
                                        if r["correctly_refused_S3"] is False)},
            "false_answer": {"S0": sum(1 for r in rows if r["should_refuse"]
                                       and r.get("correctly_refused_S0") is not True),
                             "S3": sum(1 for r in rows if r["should_refuse"]
                                       and r.get("correctly_refused_S3") is not True)},
            "gen_ms_mean": {"S0": mean(col(ans_rows, "gen_ms_S0")),
                            "S3": mean(col(ans_rows, "gen_ms_S3"))},
            "tokens_mean": {"S0": mean(col(ans_rows, "tokens_S0")),
                            "S3": mean(col(ans_rows, "tokens_S3"))},
        },
    }

    # ── 配对检验 ──
    def paired_stats(key_delta_fn, rows_):
        pairs = [(r["case_id"], key_delta_fn(r)) for r in rows_]
        ci = paired_bootstrap_ci(pairs, chains)
        win = sum(1 for _, d in pairs if d > 1e-9)
        loss = sum(1 for _, d in pairs if d < -1e-9)
        return ci, {"s3_win": win, "s3_loss": loss,
                    "tie": len(pairs) - win - loss, "n": len(pairs)}

    agg["paired_cov"] = paired_stats(
        lambda r: r["answer_point_coverage_S3"] - r["answer_point_coverage_S0"],
        ans_rows)
    agg["paired_ctx_supported"] = paired_stats(
        lambda r: r["ctx_supported_validity_S3"] - r["ctx_supported_validity_S0"],
        ans_rows)
    agg["paired_ctx_recall"] = paired_stats(
        lambda r: (r["context_recall_S3"] or 0.0) - (r["context_recall_S0"] or 0.0),
        chunk_rows)

    # McNemar：citation v2 有效（S0/S3 错误 = validity<1.0）
    agg["mcnemar_citation_v2"] = mcnemar_exact(
        [r["ctx_supported_validity_S0"] < 1.0 for r in ans_rows],
        [r["ctx_supported_validity_S3"] < 1.0 for r in ans_rows])
    agg["mcnemar_citation_id"] = mcnemar_exact(
        [r["citation_id_validity_S0"] < 1.0 for r in ans_rows],
        [r["citation_id_validity_S3"] < 1.0 for r in ans_rows])
    # McNemar：拒答错误（refusal 假答 + answerable 误拒）
    ref_pairs = [(r.get("correctly_refused_S0"), r.get("correctly_refused_S3"))
                 for r in rows if r.get("correctly_refused_S0") is not None
                 and r.get("correctly_refused_S3") is not None]
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
                if r["answer_point_coverage_S3"]
                > r["answer_point_coverage_S0"] + 1e-9)
        l = sum(1 for r in sub
                if r["answer_point_coverage_S3"]
                < r["answer_point_coverage_S0"] - 1e-9)
        cs_w = sum(1 for r in sub
                   if r["ctx_supported_validity_S3"]
                   > r["ctx_supported_validity_S0"] + 1e-9)
        cs_l = sum(1 for r in sub
                   if r["ctx_supported_validity_S3"]
                   < r["ctx_supported_validity_S0"] - 1e-9)
        return {
            "n": len(sub),
            "cov_S0": mean([r["answer_point_coverage_S0"] for r in sub]),
            "cov_S3": mean([r["answer_point_coverage_S3"] for r in sub]),
            "cov_delta": mean([r["answer_point_coverage_S3"]
                               - r["answer_point_coverage_S0"] for r in sub]),
            "s3_win": w, "s3_loss": l, "tie": len(sub) - w - l,
            "ctx_supported_S0": mean([r["ctx_supported_validity_S0"]
                                      for r in sub]),
            "ctx_supported_S3": mean([r["ctx_supported_validity_S3"]
                                      for r in sub]),
            "cs_delta": mean([r["ctx_supported_validity_S3"]
                              - r["ctx_supported_validity_S0"] for r in sub]),
            "cs_s3_win": cs_w, "cs_s3_loss": cs_l,
            "cs_tie": len(sub) - cs_w - cs_l,
            "ctx_recall_S0": mean([r["context_recall_S0"] for r in ctx_sub]),
            "ctx_recall_S3": mean([r["context_recall_S3"] for r in ctx_sub]),
            "ctx_delta": mean([(r["context_recall_S3"] or 0.0)
                               - (r["context_recall_S0"] or 0.0)
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
    so = [r for r in rows if not r["has_chunk_truth"]
          and r["relevant_source_ids"]]
    agg["slices"]["source_only_retrieval"] = {
        "n": len(so),
        "ctx_source_recall_S0": mean(col(so, "ctx_source_recall_S0")),
        "ctx_source_recall_S3": mean(col(so, "ctx_source_recall_S3")),
        "ctx_source_coverage_S0": mean(col(so, "ctx_source_coverage_S0")),
        "ctx_source_coverage_S3": mean(col(so, "ctx_source_coverage_S3")),
    }

    # ── 同 source 候选内排名 ≥4 的相关 chunk 保留（diversity 挤出场景） ──
    ge4 = {"chunks": 0, "cases": set(),
           "retained_S0": 0, "retained_S3": 0}
    lt4 = {"chunks": 0, "retained_S0": 0, "retained_S3": 0}
    ge4_detail = []
    for r in chunk_rows:
        for item in r.get("rel_chunk_same_source") or []:
            if item["rank_in_source"] >= 4:
                ge4["chunks"] += 1
                ge4["cases"].add(r["case_id"])
                ge4["retained_S0"] += int(item["in_context_S0"])
                ge4["retained_S3"] += int(item["in_context_S3"])
                ge4_detail.append({**item, "case_id": r["case_id"],
                                   "query_type": r["query_type"]})
            else:
                lt4["chunks"] += 1
                lt4["retained_S0"] += int(item["in_context_S0"])
                lt4["retained_S3"] += int(item["in_context_S3"])
    ge4["cases"] = sorted(ge4["cases"])
    agg["same_source_rank_ge4"] = {
        "summary": ge4, "lt4": lt4, "detail": ge4_detail}

    # ── 公平性审计 ──
    same_plan = all(
        abs((r.get("rewrite_ms_S0") or 0.0) - (r.get("rewrite_ms_S3") or 0.0))
        < 1.0 for r in rows)
    cand_identical = all(
        r["cand_n_S0"] == r["cand_n_S3"] for r in rows)
    s0_rerank = mean([r["rerank_ms_S0"] for r in rows])
    s3_rerank = mean([r["rerank_ms_S3"] for r in rows])
    # cap 是「选择层」约束：select_context_candidates(max_per_source=3) 在
    # 候选→context 选择时每源最多 3；最终 context 还会被 parent/adjacent
    # 扩展追加同源 chunk（生产既有行为，双臂一致，不是 policy 失效）。
    ge4 = agg["same_source_rank_ge4"]["summary"]
    agg["fairness_audit"] = {
        "shared_query_plan_rewrite_equal": same_plan,
        "candidate_pool_n_identical": cand_identical,
        "rerank_ms_mean": {"S0": s0_rerank, "S3": s3_rerank},
        "rerank_ms_nonzero_S0": sum(1 for r in rows if r["rerank_ms_S0"] > 1.0),
        "rerank_ms_nonzero_S3": sum(1 for r in rows if r["rerank_ms_S3"] > 1.0),
        # 选择层 cap 生效证据：同源 rank≥4 相关 chunk 保留数（cap3 应 ≤ unlimited）
        "selection_cap_evidence_rank4_retained": {
            "S0": ge4["retained_S0"], "S3": ge4["retained_S3"],
            "note": "rank>=4 same-source relevant chunks retained in context",
        },
        # 最终 context 观察（含扩展）：单源 >3 的 case 数，双臂均有
        "final_context_same_source_gt3": {
            "S0": sum(1 for r in rows if r["ctx_max_same_source_S0"] > 3),
            "S3": sum(1 for r in rows if r["ctx_max_same_source_S3"] > 3),
            "note": "post-expansion observation (parent/adjacent), both arms",
        },
        "selector_policy": {
            S0_ARM: None, S3_ARM: 3,
            "note": "select_context_candidates(top_k=min(k,20), "
                    "max_per_source=per-arm policy); only difference between arms",
        },
    }
    return agg


def write_failures_csv(split_dir: Path, result: dict) -> None:
    """S0/S3 对齐 failures.csv（chunk 真值 win/loss/equal；source-only 语义化）。

    与评测框架 build_failures_csv_rows 同口径：
    - 无可靠 chunk 真值：notes=source_level_only（有 relevant_source_ids）或
      no_reliable_chunk_truth（无任何真值），outcome="" 不伪造 chunk 结论。
    - flip 列保留（无 graph 臂 → 恒 False，语义为"无图污染/lift"）。
    """
    rows = result.get("rows", [])
    out_path = split_dir / "failures.csv"
    with open(out_path, "w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["case_id", "query_type", "s0_context_recall",
                         "s3_context_recall", "outcome", "flip",
                         "has_chunk_truth", "notes"])
        for r in sorted(rows, key=lambda x: x["case_id"]):
            if r["should_refuse"]:
                writer.writerow([r["case_id"], r["query_type"], "", "", "",
                                 "False", r["has_chunk_truth"], "refusal_case"])
                continue
            if not r["has_chunk_truth"]:
                notes = ("source_level_only" if r["relevant_source_ids"]
                         else "no_reliable_chunk_truth")
                writer.writerow([r["case_id"], r["query_type"], "", "", "",
                                 "False", r["has_chunk_truth"], notes])
                continue
            c0 = r["context_recall_S0"] or 0.0
            c3 = r["context_recall_S3"] or 0.0
            if c3 > c0 + 1e-9:
                outcome = "win"      # S3 优于 S0
            elif c3 < c0 - 1e-9:
                outcome = "loss"
            else:
                outcome = "equal"
            writer.writerow([r["case_id"], r["query_type"],
                             f"{c0:.4f}", f"{c3:.4f}", outcome,
                             "False", "True", ""])
    print(f"  ✓ failures.csv: {len(rows)} rows → {out_path.name}")


def main() -> None:
    dev_dir = OUT / "dev-full"
    hold_dir = OUT / "holdout-full"
    c2s = chunk_source_map()
    print(f"chunk→source map: {len(c2s)} chunks")
    result = {"split": {}}
    for name, d in (("dev", dev_dir), ("holdout", hold_dir)):
        if d.exists():
            s = analyze_split(d, c2s)
            result["split"][name] = s
            # failures.csv 需要逐 case 行：analyze_split 已计算，这里通过
            # 重新加载记录生成对齐行（轻量，只读）
            if "error" not in s:
                _emit_failures(d, c2s)
        else:
            result["split"][name] = {"error": "missing dir"}
    (OUT / "s0s3-analysis.json").write_text(
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
        print(f"  ctx_recall   S0={r['context_recall']['S0']:.3f} "
              f"S3={r['context_recall']['S3']:.3f}  "
              f"cand_recall S0={r['candidate_recall']['S0']:.3f} "
              f"S3={r['candidate_recall']['S3']:.3f}")
        print(f"  retention    S0={r['retention']['S0']:.3f} "
              f"S3={r['retention']['S3']:.3f}  "
              f"squeeze S0={r['squeeze']['S0']:.3f} S3={r['squeeze']['S3']:.3f}")
        print(f"  src_recall@5 S0={r['source_recall@5']['S0']:.3f} "
              f"S3={r['source_recall@5']['S3']:.3f}  "
              f"ctx_src_recall S0={r['context_source_recall']['S0']:.3f} "
              f"S3={r['context_source_recall']['S3']:.3f}")
        cs = s["context_shape"]
        print(f"  ctx shape    n_mean S0={cs['ctx_n_mean']['S0']:.2f} "
              f"S3={cs['ctx_n_mean']['S3']:.2f} | "
              f"srcs_mean S0={cs['ctx_sources_n_mean']['S0']:.2f} "
              f"S3={cs['ctx_sources_n_mean']['S3']:.2f} | "
              f"single_src S0={cs['single_source_ratio']['S0']:.2f} "
              f"S3={cs['single_source_ratio']['S3']:.2f} | "
              f"max_same_src S0={cs['ctx_max_same_source_max']['S0']} "
              f"S3={cs['ctx_max_same_source_max']['S3']} "
              f"(>3 cases S0={cs['cases_with_same_source_gt3']['S0']} "
              f"S3={cs['cases_with_same_source_gt3']['S3']})")
        g = s["generation"]
        print(f"  cov          S0={g['answer_point_coverage']['S0']:.3f} "
              f"S3={g['answer_point_coverage']['S3']:.3f}  "
              f"W/L/T={s['paired_cov'][1]['s3_win']}/"
              f"{s['paired_cov'][1]['s3_loss']}/{s['paired_cov'][1]['tie']}")
        print(f"  cit v2       S0={g['context_supported_citation_validity']['S0']:.3f} "
              f"S3={g['context_supported_citation_validity']['S3']:.3f}  "
              f"W/L/T={s['paired_ctx_supported'][1]['s3_win']}/"
              f"{s['paired_ctx_supported'][1]['s3_loss']}/"
              f"{s['paired_ctx_supported'][1]['tie']}")
        pc = s["paired_cov"][0]
        if pc.get("mean_delta") is not None:
            print(f"  cov delta    {pc['mean_delta']:+.3f} "
                  f"95%CI [{pc['ci95_low']:+.3f}, {pc['ci95_high']:+.3f}] "
                  f"(n={pc['n_pairs']}, blocks={pc['n_blocks']})")
        m = s["mcnemar_citation_v2"]
        print(f"  mcnemar v2   discord={m['n_discordant']} "
              f"S3_only={m['s3_only']} p={m['p_value']:.4f}")
        print(f"  no-citation  S0={g['n_no_citation']['S0']} "
              f"S3={g['n_no_citation']['S3']}  "
              f"no-ctx-supported S0={g['n_no_context_supported']['S0']} "
              f"S3={g['n_no_context_supported']['S3']}  "
              f"fabricated S0={g['fabricated_avg']['S0']:.2f} "
              f"S3={g['fabricated_avg']['S3']:.2f}  "
              f"false_refusal S0={g['false_refusal']['S0']} "
              f"S3={g['false_refusal']['S3']}")
        fa = s["fairness_audit"]
        r4 = fa["selection_cap_evidence_rank4_retained"]
        print(f"  fairness     shared_plan={fa['shared_query_plan_rewrite_equal']} "
              f"cand_identical={fa['candidate_pool_n_identical']} "
              f"rerank S0={fa['rerank_ms_mean']['S0']:.1f}ms "
              f"S3={fa['rerank_ms_mean']['S3']:.1f}ms "
              f"rank>=4 retained S0={r4['S0']} S3={r4['S3']}")
        ge4 = s["same_source_rank_ge4"]["summary"]
        lt4 = s["same_source_rank_ge4"]["lt4"]
        print(f"  samesrc≥4   chunks={ge4['chunks']} cases={len(ge4['cases'])} "
              f"retained S0={ge4['retained_S0']}/{ge4['chunks']} "
              f"S3={ge4['retained_S3']}/{ge4['chunks']} | "
              f"rank<4 chunks={lt4['chunks']} retained S0={lt4['retained_S0']} "
              f"S3={lt4['retained_S3']}")
        for name2, sl in s["slices"].items():
            if isinstance(sl, dict) and "n" in sl:
                items = [(name2, sl)]
            elif isinstance(sl, dict):
                items = [(f"{name2}.{k}", v) for k, v in sl.items()
                         if isinstance(v, dict) and v.get("n")]
            else:
                items = []
            for label, sub in items:
                ca = sub.get('ctx_recall_S0'); cb = sub.get('ctx_recall_S3')
                ca_s = f"{ca:.3f}" if ca is not None else "  -  "
                cb_s = f"{cb:.3f}" if cb is not None else "  -  "
                cov_a = sub.get('cov_S0'); cov_b = sub.get('cov_S3')
                cov_a_s = f"{cov_a:.3f}" if cov_a is not None else "  -  "
                cov_b_s = f"{cov_b:.3f}" if cov_b is not None else "  -  "
                cs_a = sub.get('ctx_supported_S0'); cs_b = sub.get('ctx_supported_S3')
                cs_a_s = f"{cs_a:.3f}" if cs_a is not None else "  -  "
                cs_b_s = f"{cs_b:.3f}" if cs_b is not None else "  -  "
                print(f"  slice {label:24s} n={sub['n']:3d} "
                      f"cov S0={cov_a_s} S3={cov_b_s} "
                      f"W/L/T={sub.get('s3_win')}/{sub.get('s3_loss')}"
                      f"/{sub.get('tie')} "
                      f"citv2 S0={cs_a_s} S3={cs_b_s} "
                      f"ctx S0={ca_s} S3={cb_s}")


def _emit_failures(split_dir: Path, c2s: dict[str, str]) -> None:
    """为 dev/holdout 目录生成 S0/S3 对齐 failures.csv（复用 analyze 逻辑）。"""
    ret = load_records(split_dir / "retrieval-cases.jsonl")
    case_ids = sorted(ret.keys())
    rows = []
    for cid in case_ids:
        r0, r3 = ret[cid].get(S0_ARM), ret[cid].get(S3_ARM)
        if r0 is None or r3 is None:
            continue
        rows.append({
            "case_id": cid,
            "query_type": r0["query_type"],
            "should_refuse": r0["should_refuse"],
            "has_chunk_truth": r0["has_chunk_truth"],
            "relevant_source_ids": r0["relevant_source_ids"],
            "context_recall_S0": (len(set(r0["context_chunk_ids"])
                                       & r0["relevant_chunk_ids"])
                                  / len(r0["relevant_chunk_ids"])
                                  if r0["relevant_chunk_ids"] else 0.0),
            "context_recall_S3": (len(set(r3["context_chunk_ids"])
                                       & r3["relevant_chunk_ids"])
                                  / len(r3["relevant_chunk_ids"])
                                  if r3["relevant_chunk_ids"] else 0.0),
        })
    write_failures_csv(split_dir, {"rows": rows})


if __name__ == "__main__":
    main()
