#!/usr/bin/env python3
"""Phase 1 §3.3 — recompute M2 / M4c-arm1 / M4c-arm2 citation metrics in
the runtime chunk domain via the store→runtime bridge (READ-ONLY).

Metric口径 (identical to evaluation/citation_metrics.py:206-218 and
evaluation/generation_runner.py:_aggregate):
  per-case precision / recall, then MEAN over all 150 cases, round 4;
  empty supported set -> precision 0.0; empty truth -> recall 0.0.

Two "retrieved" sides are reported:
  ctx_based : retrieved = context_chunk_ids          (spec-literal)
  evi_based : retrieved = citation-supported chunks  (old-manifest口径)
Both are crossed with bridge thresholds {0.25, 0.50, 0.75} on both overlap
ratios (ratio_runtime = overlap/runtime_len, ratio_store = overlap/store_len).
Store-domain hit recall (one-to-many immune) is also reported.

Outputs: metrics.json in the audit output dir.
"""
from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))
from rebuild_runtime_map import normalized_id  # noqa: E402

OUT_DIR = REPO / "results" / "answer-level" / "chunk-domain-audit-2026-11-01"

ARMS = {
    "m2": REPO / "results" / "answer-level" / "m2-baseline-2026-08-30",
    "arm1": REPO / "results" / "answer-level" / "m4c-arm1-2026-09-06",
    "arm2": REPO / "results" / "answer-level" / "m4c-arm2-2026-09-06",
}
THRESHOLDS = ("0.25", "0.50", "0.75")
RATIO_KINDS = ("runtime", "store")
SUPPORTED_STATUS = ("supported_chunk", "supported_source")


def load_jsonl(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def r4(x: float) -> float:
    return round(x, 4)


def main() -> int:
    mapping = load_jsonl(OUT_DIR / "mapping.jsonl")
    bridge: dict[str, list[dict]] = {
        row["store_chunk_id"]: [
            {**c, "runtime_chunk_id": normalized_id(c["runtime_chunk_id"])}
            for c in row.get("candidates", [])
        ] for row in mapping
    }
    bridge_stats = json.loads(
        (OUT_DIR / "bridge-stats.json").read_text(encoding="utf-8"))

    out: dict = {
        "phase": "Phase1-3.3-recompute",
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "git_commit": subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=REPO,
            capture_output=True, text=True, check=False).stdout.strip(),
        "metric_口径": (
            "per-case precision/recall then mean over all 150 cases, round 4; "
            "precision=0.0 when retrieved set empty; recall=0.0 when truth "
            "empty (identical to citation_metrics.py:206-218 + _aggregate)"),
        "bridge_coverage": {
            "coverage_any": bridge_stats["coverage_any"],
            "coverage_by_threshold_runtime":
                bridge_stats["coverage_by_threshold_runtime"],
            "coverage_by_threshold_store":
                bridge_stats["coverage_by_threshold_store"],
            "one_to_many": bridge_stats["one_to_many"],
            "ambiguous": bridge_stats["ambiguous"],
        },
        "per_arm": {},
        "id_collision_reproduction": {},
        "truth_domain": {},
    }

    # ---- dataset truth (only used to verify outcomes carry identical truth)
    ds_truth: dict[str, set] = {}
    with (REPO / "evaluation" / "datasets" / "v2.1.jsonl").open(
            encoding="utf-8") as f:
        for line in f:
            row = json.loads(line)
            ds_truth[row["id"]] = set(row.get("relevant_chunk_ids") or [])

    for arm, root in ARMS.items():
        rows = load_jsonl(root / "outcomes.jsonl")
        manifest = json.loads((root / "manifest.json").read_text(
            encoding="utf-8"))
        agg = manifest.get("aggregates") or {}
        old_recall = agg.get("citation_recall_avg")
        old_precision = agg.get("citation_precision_avg")

        truth_mismatch = 0
        n_truth_cases = 0
        # accumulators: [ratio_kind][threshold] -> lists
        acc = {k: {t: {
            "rec_ctx": [], "prec_ctx": [], "rec_evi": [], "prec_evi": [],
            "any_ctx": [], "rec_store_ctx": [], "rec_store_evi": [],
            "rel_runtime_sizes": [], "unmapped_truth": [],
        } for t in THRESHOLDS} for k in RATIO_KINDS}
        id_rec_ctx, id_prec_ctx, id_any = [], [], []   # ID-collision baseline
        evi_totals = {"fabricated": 0, "retrieved_not_in_context": 0}

        for row in rows:
            case_id = row["case_id"]
            rel_store = set(row.get("relevant_chunk_ids") or [])
            if ds_truth.get(case_id, rel_store) != rel_store:
                truth_mismatch += 1
            if rel_store:
                n_truth_cases += 1
            cm = row.get("citation_metrics") or {}
            evi_totals["fabricated"] += cm.get("fabricated_citation_count", 0)
            evi_totals["retrieved_not_in_context"] += \
                cm.get("retrieved_not_in_context_count", 0)
            supp = {e["chunk_id"] for e in (cm.get("evidence") or [])
                    if e.get("status") in SUPPORTED_STATUS and e.get("chunk_id")}
            ctx = set(row.get("context_chunk_ids") or [])

            # ID-collision baseline (old broken domain): raw string compare
            if supp:
                id_prec_ctx.append(len(supp & rel_store) / len(supp))
            else:
                id_prec_ctx.append(0.0)
            id_rec_ctx.append(
                len(supp & rel_store) / len(rel_store) if rel_store else 0.0)
            id_any.append(1.0 if (ctx & rel_store) else 0.0)

            for kind in RATIO_KINDS:
                key = "ratio_runtime" if kind == "runtime" else "ratio_store"
                for t in THRESHOLDS:
                    tf = float(t)
                    rel_rt: set[str] = set()
                    unmapped = 0
                    hit_ctx: set[str] = set()   # store chunks hit (any cand)
                    hit_evi: set[str] = set()
                    for sid in rel_store:
                        cands = [c for c in bridge.get(sid, [])
                                 if c.get(key, 0) >= tf]
                        if not cands:
                            unmapped += 1
                            continue
                        ids = {c["runtime_chunk_id"] for c in cands}
                        rel_rt |= ids
                        if ids & ctx:
                            hit_ctx.add(sid)
                        if ids & supp:
                            hit_evi.add(sid)

                    a = acc[kind][t]
                    a["rel_runtime_sizes"].append(len(rel_rt))
                    a["unmapped_truth"].append(unmapped)
                    # ctx-based (spec literal)
                    if ctx:
                        a["prec_ctx"].append(len(ctx & rel_rt) / len(ctx))
                    else:
                        a["prec_ctx"].append(0.0)
                    a["rec_ctx"].append(
                        len(ctx & rel_rt) / len(rel_rt) if rel_rt else 0.0)
                    a["any_ctx"].append(1.0 if (ctx & rel_rt) else 0.0)
                    # evidence-based (old manifest口径)
                    if supp:
                        a["prec_evi"].append(len(supp & rel_rt) / len(supp))
                    else:
                        a["prec_evi"].append(0.0)
                    a["rec_evi"].append(
                        len(supp & rel_rt) / len(rel_rt) if rel_rt else 0.0)
                    # store-domain hit recall (one-to-many immune)
                    a["rec_store_ctx"].append(
                        len(hit_ctx) / len(rel_store) if rel_store else 0.0)
                    a["rec_store_evi"].append(
                        len(hit_evi) / len(rel_store) if rel_store else 0.0)

        arm_out: dict = {
            "case_count": len(rows),
            "truth_cases": n_truth_cases,
            "truth_mismatch_vs_dataset": truth_mismatch,
            "old_manifest": {"citation_recall_avg": old_recall,
                             "citation_precision_avg": old_precision},
            "fabricated_total": evi_totals["fabricated"],
            "retrieved_not_in_context_total":
                evi_totals["retrieved_not_in_context"],
            "thresholds": {},
        }
        for kind in RATIO_KINDS:
            for t in THRESHOLDS:
                a = acc[kind][t]
                arm_out["thresholds"].setdefault(t, {})[kind] = {
                    "recall_ctx_based": r4(sum(a["rec_ctx"]) / len(a["rec_ctx"])),
                    "precision_ctx_based": r4(
                        sum(a["prec_ctx"]) / len(a["prec_ctx"])),
                    "recall_evi_based": r4(sum(a["rec_evi"]) / len(a["rec_evi"])),
                    "precision_evi_based": r4(
                        sum(a["prec_evi"]) / len(a["prec_evi"])),
                    "case_any_overlap_ctx": r4(
                        sum(a["any_ctx"]) / len(a["any_ctx"])),
                    "store_hit_recall_ctx": r4(
                        sum(a["rec_store_ctx"]) / len(a["rec_store_ctx"])),
                    "store_hit_recall_evi": r4(
                        sum(a["rec_store_evi"]) / len(a["rec_store_evi"])),
                    "mean_rel_runtime_size": r4(
                        sum(a["rel_runtime_sizes"]) / len(a["rel_runtime_sizes"])),
                    "mean_unmapped_truth_chunks": r4(
                        sum(a["unmapped_truth"]) / len(a["unmapped_truth"])),
                    "truth_chunks_unmapped_rate": r4(
                        sum(1 for u in a["unmapped_truth"] if u > 0)
                        / len(a["unmapped_truth"])),
                }
        out["per_arm"][arm] = arm_out
        out["id_collision_reproduction"][arm] = {
            "recall": r4(sum(id_rec_ctx) / len(id_rec_ctx)),
            "precision": r4(sum(id_prec_ctx) / len(id_prec_ctx)),
            "case_any_overlap": r4(sum(id_any) / len(id_any)),
            "matches_old_manifest":
                abs(sum(id_rec_ctx) / len(id_rec_ctx)
                    - (old_recall or 0)) < 5e-5
                and abs(sum(id_prec_ctx) / len(id_prec_ctx)
                        - (old_precision or 0)) < 5e-5,
        }

    out["truth_domain"]["dataset_vs_outcomes_mismatch"] = sum(
        a["truth_mismatch_vs_dataset"] for a in out["per_arm"].values())

    # ---- C1/C3 signal assessment (coverage gate per spec: <95% -> no claim)
    cov = out["bridge_coverage"]["coverage_any"]
    out["c1_c3_assessment"] = {
        "mapping_coverage_any": cov,
        "coverage_gate_pass": cov >= 0.95,
        "note": (
            "C1/C3 may only be discussed if overall mapping coverage >=95%. "
            "Threshold-conditional coverage below 95% is flagged per row."),
        "threshold_coverage_flags": {
            t: {
                "runtime": out["bridge_coverage"]
                    ["coverage_by_threshold_runtime"][t],
                "store": out["bridge_coverage"]
                    ["coverage_by_threshold_store"][t],
            } for t in THRESHOLDS},
    }

    (OUT_DIR / "metrics.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8")

    print(f"truth mismatch vs dataset: "
          f"{out['truth_domain']['dataset_vs_outcomes_mismatch']}")
    for arm, a in out["per_arm"].items():
        rep = out["id_collision_reproduction"][arm]
        print(f"[{arm}] old(manifest) R={a['old_manifest']['citation_recall_avg']} "
              f"P={a['old_manifest']['citation_precision_avg']} | "
              f"id-repro R={rep['recall']} P={rep['precision']} "
              f"match={rep['matches_old_manifest']}")
        for t in THRESHOLDS:
            for kind in RATIO_KINDS:
                s = a["thresholds"][t][kind]
                print(f"  t={t} {kind}: rec_ctx={s['recall_ctx_based']} "
                      f"prec_ctx={s['precision_ctx_based']} | "
                      f"rec_evi={s['recall_evi_based']} "
                      f"prec_evi={s['precision_evi_based']} | "
                      f"any={s['case_any_overlap_ctx']} "
                      f"storehit={s['store_hit_recall_ctx']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
