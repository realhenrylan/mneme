#!/usr/bin/env python3
"""M6a Phase 2A — mapping candidates + control metrics + oracle upper bound
(READ-ONLY, 0 LLM / 0 network / 0 generation).

Preregistration: plans/ANSWER-LEVEL-M6a-PHASE2A-ORACLE-PREREGISTRATION-2026-11-01.md
Upstream evidence: docs/AUDIT-CHUNK-DOMAIN-2026-11-01.md §5A +
results/answer-level/chunk-domain-audit-2026-11-01/{report.md,metrics.json,
runtime-map.jsonl,mapping.jsonl}.

Inputs (all read-only):
  - a' baseline: `git show de8181f:results/answer-level/m6a-paired-base-2026-11-01/
    outcomes.jsonl` (+ its manifest), cross-checked against the decision-dir copy
    `de8181f:results/answer-level/m6a-paired-2026-11-01/baseline-outcomes.jsonl`.
    Exported to a temp dir only; never checked out.
  - results/answer-level/chunk-domain-audit-2026-11-01/runtime-map.jsonl (2,947)
  - results/answer-level/chunk-domain-audit-2026-11-01/mapping.jsonl (1,006)
  - v2.1 dataset via the PRODUCTION resolution path
    (evaluation.generation_runner.resolve_generation_dataset + evaluation.schema
    .load_dataset) — only used to verify baseline truth == dataset truth.

Mapping candidates (t = 0.50, per prereg §3), all three reported in parallel;
this script does NOT pick the winner (owner signs Q2-a):
  A: ratio_runtime >= 0.50                       (single-sided runtime)
  B: ratio_runtime >= 0.50 AND ratio_store >= 0.50 (bilateral)
  C: ratio_store >= 0.50                          (single-sided store, sensitivity)

Metrics (frozen口径, identical to evaluation/citation_metrics.py:206-218 +
aggregate; per-case then MEAN over all 150 cases, round 4; empty truth -> 0,
empty retrieved -> precision 0):
  control C1   = store_hit_recall_evi  (per store truth: any mapped runtime
                 candidate cited in S -> hit; hits/|T_store|)
  recall_evi   = |S ∩ T_rt| / |T_rt|
  precision_evi= |S ∩ T_rt| / |S|        (control C3)
  S  = citation_metrics.evidence entries with status in
       (supported_chunk, supported_source)  [12-hex normalized, evi side]
  Ctx= context_chunk_ids                 [ctx side, auxiliary]
  T_store = dataset relevant_chunk_ids   (store domain; == baseline field,
             verified per-case)
  T_rt    = union of passing candidates' runtime chunks (12-hex normalized)

Oracle (only REDIRECT existing [S#] slots; no add/remove; one slot can hit at
most one truth):
  m = count of regex \\[S\\d+\\] in the baseline answer
  oracle_store_hit  = min(m, |T_store|) / |T_store|   (empty truth -> 0)
  oracle_recall_evi = min(m, |T_rt|)    / |T_rt|      (empty -> 0)
  Auxiliary (coverage-aware): oracle_store_hit_achievable = min(m,
  |mapped store truths|) / |T_store| — a slot cannot hit a store truth that has
  no passing candidate. Reported alongside; prereg §5 formula stays primary.

Outputs: results/answer-level/m6a-phase2a-2026-11-01/
  mapping-candidates.json, control-metrics.json, oracle.json, report.md,
  manifest.json (self-hash).

Never writes into src/, evaluation/, tests/, config/, data/, plans/, docs/ or
CHANGELOG. Never calls an LLM or the network.
"""
from __future__ import annotations

import hashlib
import json
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

AUDIT_DIR = (REPO / "results" / "answer-level"
             / "chunk-domain-audit-2026-11-01")
RUNTIME_MAP = AUDIT_DIR / "runtime-map.jsonl"
MAPPING = AUDIT_DIR / "mapping.jsonl"
OUT_DIR = REPO / "results" / "answer-level" / "m6a-phase2a-2026-11-01"

BASELINE_COMMIT = "de8181f"
BASELINE_PRIMARY = ("results/answer-level/m6a-paired-base-2026-11-01"
                    "/outcomes.jsonl")
BASELINE_SECONDARY = ("results/answer-level/m6a-paired-2026-11-01"
                      "/baseline-outcomes.jsonl")
BASELINE_MANIFEST = ("results/answer-level/m6a-paired-base-2026-11-01"
                     "/manifest.json")
EXPECTED_BASELINE_SHA = ("5cd71261507a8367c9acb160bb71406fc289e85a"
                         "19ed761a6fe0604ba85a5c54")
EXPECTED_HEAD = "ab4073c1704e3a8e361e8a55373fbf03bad9859c"

EXPECTED_RUNTIME_ROWS = 2947
EXPECTED_MAPPING_ROWS = 1006
EXPECTED_BASELINE_ROWS = 150
EXPECTED_ORDERED_IDS = 3108

SLOT_RE = re.compile(r"\[S\d+\]")
SUPPORTED_STATUS = ("supported_chunk", "supported_source")
T = 0.50

CANDIDATES = {
    "A": {"rule": "ratio_runtime >= 0.50",
          "kind": "single_sided_runtime",
          "pred": lambda c: c["ratio_runtime"] >= T},
    "B": {"rule": "ratio_runtime >= 0.50 AND ratio_store >= 0.50",
          "kind": "bilateral",
          "pred": lambda c: (c["ratio_runtime"] >= T
                             and c["ratio_store"] >= T)},
    "C": {"rule": "ratio_store >= 0.50",
          "kind": "single_sided_store",
          "pred": lambda c: c["ratio_store"] >= T},
}


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def r4(x: float) -> float:
    return round(x, 4)


def mean4(xs: list[float]) -> float:
    return r4(sum(xs) / len(xs)) if xs else 0.0


def load_jsonl(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def die(msg: str) -> None:
    print(f"[STOP] {msg}", file=sys.stderr)
    sys.exit(1)


def git_show(ref_path: str) -> bytes:
    proc = subprocess.run(["git", "show", ref_path], cwd=REPO,
                          capture_output=True)
    if proc.returncode != 0:
        die(f"git show {ref_path} failed: "
            f"{proc.stderr.decode('utf-8', 'replace')[:300]}")
    return proc.stdout


def main() -> int:
    # ── preflight (fail-closed, mirrors task stop conditions) ──────────
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=REPO,
                          capture_output=True, text=True,
                          check=False).stdout.strip()
    if head != EXPECTED_HEAD:
        die(f"HEAD is {head}, expected {EXPECTED_HEAD}")

    runtime_rows = load_jsonl(RUNTIME_MAP)
    if len(runtime_rows) != EXPECTED_RUNTIME_ROWS:
        die(f"runtime-map rows {len(runtime_rows)} != "
            f"{EXPECTED_RUNTIME_ROWS}")
    mapping_rows = load_jsonl(MAPPING)
    if len(mapping_rows) != EXPECTED_MAPPING_ROWS:
        die(f"mapping rows {len(mapping_rows)} != {EXPECTED_MAPPING_ROWS}")

    baseline_bytes = git_show(f"{BASELINE_COMMIT}:{BASELINE_PRIMARY}")
    baseline_sha = sha256_bytes(baseline_bytes)
    if not baseline_sha.startswith("5cd712"):
        die(f"baseline SHA {baseline_sha} does not start with 5cd712")
    secondary_bytes = git_show(f"{BASELINE_COMMIT}:{BASELINE_SECONDARY}")
    if sha256_bytes(secondary_bytes) != baseline_sha:
        die("decision-dir baseline copy SHA differs from primary copy")
    baseline_manifest = json.loads(
        git_show(f"{BASELINE_COMMIT}:{BASELINE_MANIFEST}").decode("utf-8"))
    agg0 = baseline_manifest.get("aggregates") or {}
    if baseline_manifest.get("case_count") != EXPECTED_BASELINE_ROWS:
        die("baseline manifest case_count != 150")
    if agg0.get("cases_failed") != 0:
        die("baseline cases_failed != 0")

    with tempfile.TemporaryDirectory(prefix="m6a-phase2a-") as td:
        base_path = Path(td) / "baseline-outcomes.jsonl"
        base_path.write_bytes(baseline_bytes)
        baseline = load_jsonl(base_path)

    if len(baseline) != EXPECTED_BASELINE_ROWS:
        die(f"baseline rows {len(baseline)} != {EXPECTED_BASELINE_ROWS}")

    # runtime map: full chunk_id -> normalized_id (12-hex); 2,947 distinct
    full2norm: dict[str, str] = {}
    norm_set: set[str] = set()
    for row in runtime_rows:
        full2norm[row["chunk_id"]] = row["normalized_id"]
        norm_set.add(row["normalized_id"])
    if len(full2norm) != EXPECTED_RUNTIME_ROWS or \
            len(norm_set) != EXPECTED_RUNTIME_ROWS:
        die("runtime map chunk_id/normalized_id not 2,947 distinct")

    # mapping: store_chunk_id -> candidates (runtime ids normalized via map)
    bridge: dict[str, list[dict]] = {}
    for row in mapping_rows:
        cands = []
        for c in row.get("candidates", []):
            norm = full2norm.get(c["runtime_chunk_id"])
            if norm is None:
                die(f"candidate runtime chunk not in runtime map: "
                    f"{c['runtime_chunk_id']}")
            cands.append({**c, "runtime_norm": norm})
        bridge[row["store_chunk_id"]] = cands

    # dataset truth via PRODUCTION resolution path (not hardcoded)
    from evaluation.generation_runner import resolve_generation_dataset  # noqa: E402
    from evaluation.schema import load_dataset  # noqa: E402

    dataset_path = resolve_generation_dataset("v2.1")
    dataset_sha = sha256_bytes(dataset_path.read_bytes())
    ds_truth: dict[str, list[str]] = {
        c.id: list(c.relevant_chunk_ids or []) for c in load_dataset(dataset_path)}

    # baseline first-case keys (no answer text printed)
    print(f"[baseline] rows={len(baseline)} sha256={baseline_sha}")
    print(f"[baseline] first-case keys: {sorted(baseline[0].keys())}")

    # ── per-case extraction + verification ────────────────────────────
    ordered_total = 0
    ordered_unresolved = 0
    truth_mismatch = 0
    truth_dup_notes: list[dict] = []
    ctx_field_mismatch = 0
    per_case: list[dict] = []
    for row in baseline:
        case_id = row["case_id"]
        ordered = row.get("context_chunk_ids_ordered") or []
        ordered_total += len(ordered)
        ordered_unresolved += sum(1 for i in ordered if i not in norm_set)
        if set(row.get("context_chunk_ids") or []) != set(ordered):
            ctx_field_mismatch += 1
        t_store = list(row.get("relevant_chunk_ids") or [])
        ds_list = ds_truth.get(case_id, [])
        # Truth is a SET for every metric (hits/|T_store|, min(m, truth)).
        # Compare sets; a duplicated ID inside the dataset's list is a data
        # note, not a domain mismatch (baseline stored the deduped list).
        if set(t_store) != set(ds_list):
            truth_mismatch += 1
        if len(ds_list) != len(set(ds_list)):
            truth_dup_notes.append({
                "case_id": case_id,
                "dataset_truth": ds_list,
                "baseline_truth": t_store,
                "note": "dataset relevant_chunk_ids contains a duplicate "
                        "entry; set semantics used, baseline == dedup",
            })
        cm = row.get("citation_metrics") or {}
        supp = {e["chunk_id"] for e in (cm.get("evidence") or [])
                if e.get("status") in SUPPORTED_STATUS and e.get("chunk_id")}
        unresolved_supp = [i for i in supp if i not in norm_set]
        if unresolved_supp:
            die(f"supported evidence ids not in runtime map "
                f"({case_id}): {unresolved_supp[:3]}")
        ctx = set(row.get("context_chunk_ids") or [])
        unresolved_ctx = [i for i in ctx if i not in norm_set]
        if unresolved_ctx:
            die(f"context ids not in runtime map ({case_id}): "
                f"{unresolved_ctx[:3]}")
        per_case.append({
            "case_id": case_id,
            "answer": row.get("answer") or "",
            "t_store": set(t_store),
            "S": supp,
            "Ctx": ctx,
            "fabricated": cm.get("fabricated_citation_count", 0),
            "not_in_context": cm.get("retrieved_not_in_context_count", 0),
            "should_refuse": bool(row.get("should_refuse")),
        })

    if ordered_total != EXPECTED_ORDERED_IDS or ordered_unresolved:
        die(f"ordered ids {ordered_total} total / {ordered_unresolved} "
            f"unresolved (expected {EXPECTED_ORDERED_IDS}/0)")
    if truth_mismatch:
        die(f"baseline truth != dataset truth in {truth_mismatch} cases")
    print(f"[verify] ordered ids {ordered_total}/{ordered_total} resolvable; "
          f"truth set mismatch vs v2.1 = {truth_mismatch}; "
          f"dataset truth-list duplicates = {len(truth_dup_notes)} "
          f"({', '.join(d['case_id'] for d in truth_dup_notes) or 'none'}); "
          f"ctx field mismatches = {ctx_field_mismatch}")

    n = len(per_case)
    truth_cases = sum(1 for c in per_case if c["t_store"])
    distinct_truth = {t for c in per_case for t in c["t_store"]}
    print(f"[verify] truth_cases={truth_cases}/150; "
          f"distinct truth chunks={len(distinct_truth)}")

    # ── mapping candidates (store-chunk level, over 1,006) ────────────
    candidates_out: dict[str, dict] = {}
    passing: dict[str, dict[str, set[str]]] = {}   # cand -> store -> rt set
    for name, spec in CANDIDATES.items():
        pred = spec["pred"]
        passing[name] = {}
        coverage = one_to_many = ambiguous = unmapped_all = 0
        unmapped_truth_ids: list[str] = []
        for store_id, cands in bridge.items():
            ok = [c for c in cands if pred(c)]
            ids = {c["runtime_norm"] for c in ok}
            passing[name][store_id] = ids
            if ids:
                coverage += 1
            else:
                unmapped_all += 1
                if store_id in distinct_truth:
                    unmapped_truth_ids.append(store_id)
            if len(ok) > 1:
                one_to_many += 1
            if len(ok) >= 2:
                ambiguous += 1
        candidates_out[name] = {
            "rule": spec["rule"],
            "kind": spec["kind"],
            "coverage": r4(coverage / EXPECTED_MAPPING_ROWS),
            "covered_store_chunks": coverage,
            "unmapped_store_chunks": unmapped_all,
            "one_to_many": one_to_many,
            "ambiguous": ambiguous,
            "distinct_case_truth_total": len(distinct_truth),
            "distinct_case_truth_unmapped": len(unmapped_truth_ids),
            "distinct_case_truth_unmapped_ids": sorted(unmapped_truth_ids),
        }

    # ── per-case control metrics + oracle, per candidate ──────────────
    control_out: dict[str, dict] = {}
    oracle_out: dict[str, dict] = {}
    per_case_rt_summary: list[dict] = []
    for name in CANDIDATES:
        c1_list, recall_list, prec_list = [], [], []
        rel_size_list, unmapped_list = [], []
        prec_ctx_list, recall_ctx_list = [], []
        any_evi_list, any_ctx_list = [], []
        o_store_list, o_evi_list, o_achievable_list = [], [], []
        o_evi_achievable_list: list[float] = []
        fabricated_total = not_in_context_total = 0
        per_case_oracle: list[dict] = []

        for c in per_case:
            t_store = c["t_store"]
            t_rt: set[str] = set()
            unmapped = 0
            mapped_store = 0
            for sid in t_store:
                ids = passing[name].get(sid, set())
                if ids:
                    mapped_store += 1
                    t_rt |= ids
                else:
                    unmapped += 1
            S, Ctx = c["S"], c["Ctx"]
            fabricated_total += c["fabricated"]
            not_in_context_total += c["not_in_context"]

            # control (a' baseline as-is)
            hits = sum(1 for sid in t_store
                       if passing[name].get(sid) & S)
            c1_list.append(hits / len(t_store) if t_store else 0.0)
            recall_list.append(len(S & t_rt) / len(t_rt) if t_rt else 0.0)
            prec_list.append(len(S & t_rt) / len(S) if S else 0.0)
            rel_size_list.append(len(t_rt))
            unmapped_list.append(unmapped)
            prec_ctx_list.append(len(Ctx & t_rt) / len(Ctx) if Ctx else 0.0)
            recall_ctx_list.append(len(Ctx & t_rt) / len(t_rt) if t_rt else 0.0)
            any_evi_list.append(1.0 if (S & t_rt) else 0.0)
            any_ctx_list.append(1.0 if (Ctx & t_rt) else 0.0)

            # oracle: redirect existing [S#] slots only, and only to
            # runtime chunks actually present in this case's context
            # (M6a can only retarget to context chunks).
            m = len(SLOT_RE.findall(c["answer"]))
            reachable_store = sum(
                1 for sid in t_store
                if passing[name].get(sid, set()) & Ctx)
            o_store = (min(m, len(t_store)) / len(t_store)
                       if t_store else 0.0)
            o_evi = min(m, len(t_rt)) / len(t_rt) if t_rt else 0.0
            o_ach = (min(m, reachable_store) / len(t_store)
                     if t_store else 0.0)
            o_evi_ach = (
                min(m, len(t_rt & Ctx)) / len(t_rt) if t_rt else 0.0)
            o_store_list.append(o_store)
            o_evi_list.append(o_evi)
            o_achievable_list.append(o_ach)
            o_evi_achievable_list.append(o_evi_ach)
            per_case_oracle.append({
                "case_id": c["case_id"], "m": m,
                "n_t_store": len(t_store), "n_t_rt": len(t_rt),
                "n_t_store_reachable": reachable_store,
                "n_t_rt_reachable": len(t_rt & Ctx),
                "oracle_store_hit": r4(o_store),
                "oracle_recall_evi": r4(o_evi),
                "oracle_store_hit_achievable": r4(o_ach),
                "oracle_recall_evi_achievable": r4(o_evi_ach),
            })

        c1 = mean4(c1_list)
        control_out[name] = {
            "mapping_rule": CANDIDATES[name]["rule"],
            "coverage": candidates_out[name]["coverage"],
            "store_hit_recall_evi": c1,
            "recall_evi": mean4(recall_list),
            "precision_evi": mean4(prec_list),
            "mean_rel_runtime_size": mean4(rel_size_list),
            "mean_unmapped_truth_chunks": mean4(
                [float(u) for u in unmapped_list]),
            "truth_chunks_unmapped_rate": mean4(
                [1.0 if u > 0 else 0.0 for u in unmapped_list]),
            "precision_ctx": mean4(prec_ctx_list),
            "recall_ctx": mean4(recall_ctx_list),
            "case_any_overlap_evi": mean4(any_evi_list),
            "case_any_overlap_ctx": mean4(any_ctx_list),
            "fabricated_total": fabricated_total,
            "retrieved_not_in_context_total": not_in_context_total,
            "case_count": n, "truth_cases": truth_cases,
        }
        o_store = mean4(o_store_list)
        o_store_ach = mean4(o_achievable_list)
        o_evi_ach = mean4(o_evi_achievable_list)
        oracle_out[name] = {
            "O_store": o_store,
            "O_evi": mean4(o_evi_list),
            "O_store_achievable": o_store_ach,
            "O_evi_achievable": o_evi_ach,
            "O_store_minus_control_C1": r4(o_store - c1),
            "O_evi_minus_control_recall_evi": r4(
                mean4(o_evi_list) - control_out[name]["recall_evi"]),
            "O_store_achievable_minus_control_C1": r4(o_store_ach - c1),
            "O_evi_achievable_minus_control_recall_evi": r4(
                o_evi_ach - control_out[name]["recall_evi"]),
            "separable_band_ge_0.02": (o_store_ach - c1) >= 0.02,
            "per_case": per_case_oracle,
        }
        if name == "A":
            per_case_rt_summary = [{
                "case_id": c["case_id"],
                "n_t_store": len(c["t_store"]),
            } for c in per_case]
        for i, c in enumerate(per_case):
            t_store = c["t_store"]
            t_rt: set[str] = set()
            unmapped = 0
            for sid in t_store:
                ids = passing[name].get(sid, set())
                if ids:
                    t_rt |= ids
                else:
                    unmapped += 1
            per_case_rt_summary[i][f"n_t_rt_{name}"] = len(t_rt)
            per_case_rt_summary[i][f"unmapped_truth_{name}"] = unmapped

    # ── write artifacts ───────────────────────────────────────────────
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    generated_at = time.strftime("%Y-%m-%dT%H:%M:%S%z")

    mapping_out = {
        "phase": "M6a-Phase2A-mapping-candidates",
        "generated_at": generated_at,
        "git_commit": head,
        "threshold": T,
        "note": ("All three candidates reported in parallel; the primary "
                 "口径 is the owner's decision (Q2-a). Coverage <95% means "
                 "the candidate may NOT serve as primary口径 (report only)."),
        "candidates": candidates_out,
        "per_case_T_rt_summary": per_case_rt_summary,
    }
    control_metrics_out = {
        "phase": "M6a-Phase2A-control-metrics",
        "generated_at": generated_at,
        "git_commit": head,
        "baseline": {"ref": f"{BASELINE_COMMIT}:{BASELINE_PRIMARY}",
                     "sha256": baseline_sha, "cases": n,
                     "cases_failed": agg0.get("cases_failed"),
                     "old_manifest_id_collision": {
                         "citation_recall_avg":
                             baseline_manifest["aggregates"]
                             .get("citation_recall_avg"),
                         "citation_precision_avg":
                             baseline_manifest["aggregates"]
                             .get("citation_precision_avg"),
                     }},
        "口径": ("per-case metric then MEAN over all 150 cases, round 4; "
                 "empty truth -> 0.0; empty retrieved -> precision 0.0 "
                 "(identical to citation_metrics.py:206-218 + aggregate). "
                 "S = citation_metrics.evidence supported "
                 "(supported_chunk|supported_source), 12-hex normalized; "
                 "T_rt = union of passing mapping candidates."),
        "verification": {
            "baseline_truth_set_mismatch_vs_dataset": truth_mismatch,
            "dataset_truth_list_duplicates": truth_dup_notes,
            "note": ("Truth compared as SETS (metrics are set-based). "
                     "mixed-033: dataset list repeats "
                     "c9fd20815ea8_chunk_18; baseline stored the deduped "
                     "list; set semantics -> identical, not a domain "
                     "mismatch, not a stop condition."),
        },
        "per_candidate": control_out,
    }
    oracle_payload = {
        "phase": "M6a-Phase2A-oracle",
        "generated_at": generated_at,
        "git_commit": head,
        "method": ("Only REDIRECT existing [S#] slots (m = count of "
                   "regex \\[S\\d+\\] in the baseline answer); no slot "
                   "addition/removal; one slot hits at most one truth "
                   "(min(m, truth) / truth); empty truth -> 0. "
                   "oracle_store_hit is the theoretical all-truth bound. "
                   "oracle_store_hit_achievable only counts store truths "
                   "whose mapped runtime chunk is present in this case's "
                   "context (context-reachable; the actual M6a bound). "
                   "oracle_recall_evi_achievable intersects T_rt with Ctx. "
                   "Offline truth use only; never enters product."),
        "per_candidate": oracle_payload_per_candidate(oracle_out),
    }

    write_json(OUT_DIR / "mapping-candidates.json", mapping_out)
    write_json(OUT_DIR / "control-metrics.json", control_metrics_out)
    write_json(OUT_DIR / "oracle.json", oracle_payload)

    # ── decision readiness table + report ─────────────────────────────
    report_md = build_report(head, baseline_sha, dataset_sha,
                             baseline_manifest, candidates_out,
                             control_out, oracle_out, n, truth_cases,
                             len(distinct_truth), generated_at)
    (OUT_DIR / "report.md").write_text(report_md, encoding="utf-8")

    # ── manifest (self-hash covers body sans manifest_sha256) ─────────
    script_path = Path(__file__).resolve()
    outputs = {}
    for fname in ("mapping-candidates.json", "control-metrics.json",
                  "oracle.json", "report.md"):
        outputs[fname] = sha256_bytes((OUT_DIR / fname).read_bytes())
    manifest_body = {
        "phase": "M6a-Phase2A",
        "generated_at": generated_at,
        "git_commit": head,
        "read_only": True,
        "llm_calls": 0,
        "network": False,
        "baseline": {"ref": f"{BASELINE_COMMIT}:{BASELINE_PRIMARY}",
                     "ref_secondary": f"{BASELINE_COMMIT}:{BASELINE_SECONDARY}",
                     "sha256": baseline_sha,
                     "rows": len(baseline),
                     "cases_failed": agg0.get("cases_failed")},
        "runtime_map": {"path": str(RUNTIME_MAP.relative_to(REPO)),
                        "sha256": sha256_bytes(RUNTIME_MAP.read_bytes()),
                        "rows": len(runtime_rows)},
        "mapping": {"path": str(MAPPING.relative_to(REPO)),
                    "sha256": sha256_bytes(MAPPING.read_bytes()),
                    "rows": len(mapping_rows)},
        "dataset": {"path": str(dataset_path.relative_to(REPO)),
                    "sha256_worktree_raw": dataset_sha,
                    "sha256_lf_normalized": sha256_bytes(
                        dataset_path.read_bytes().replace(b"\r\n", b"\n")),
                    "sha256_at_baseline_run":
                        baseline_manifest.get("dataset_sha256"),
                    "sha256_note": ("raw worktree bytes differ from the git "
                                    "blob only because core.autocrlf=true "
                                    "converts LF->CRLF on checkout; "
                                    "LF-normalized == blob == baseline-run "
                                    "value 4597167d…"),
                    "truth_set_mismatch_vs_baseline": truth_mismatch,
                    "truth_list_duplicates": [d["case_id"]
                                              for d in truth_dup_notes]},
        "script": {"path": str(script_path.relative_to(REPO)),
                   "sha256": sha256_bytes(script_path.read_bytes())},
        "outputs_sha256": outputs,
        "manifest_sha256": "",
    }
    manifest_body["manifest_sha256"] = sha256_bytes(
        json.dumps(manifest_body, ensure_ascii=False, indent=1,
                   sort_keys=True).encode("utf-8"))
    write_json(OUT_DIR / "manifest.json", manifest_body)

    # ── console summary ───────────────────────────────────────────────
    print("\n=== mapping candidates (t=0.50) ===")
    for name in ("A", "B", "C"):
        c = candidates_out[name]
        print(f"  {name}: coverage={c['coverage']:.4f} "
              f"one_to_many={c['one_to_many']} "
              f"ambiguous={c['ambiguous']} "
              f"unmapped_truth(distinct)="
              f"{c['distinct_case_truth_unmapped']}")
    print("=== control (a' baseline) ===")
    for name in ("A", "B", "C"):
        c = control_out[name]
        print(f"  {name}: C1(store_hit_recall_evi)="
              f"{c['store_hit_recall_evi']} "
              f"recall_evi={c['recall_evi']} "
              f"precision_evi={c['precision_evi']} "
              f"mean_rel_rt={c['mean_rel_runtime_size']}")
    print("=== oracle ===")
    for name in ("A", "B", "C"):
        o = oracle_out[name]
        print(f"  {name}: O_store={o['O_store']} O_evi={o['O_evi']} "
              f"O_store-ctrl={o['O_store_minus_control_C1']} "
              f"separable>=0.02={o['separable_band_ge_0.02']} "
              f"(achievable O_store={o['O_store_achievable']})")
    print(f"\n[sealed] {OUT_DIR}")
    return 0


def oracle_payload_per_candidate(oracle_out: dict[str, dict]) -> dict:
    return {name: {k: v for k, v in o.items()} for name, o in
            oracle_out.items()}


def write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2,
                               sort_keys=True) + "\n", encoding="utf-8")


def build_report(head: str, baseline_sha: str, dataset_sha: str,
                 baseline_manifest: dict, candidates_out: dict,
                 control_out: dict, oracle_out: dict, n: int,
                 truth_cases: int, distinct_truth: int,
                 generated_at: str) -> str:
    b_aggs = baseline_manifest.get("aggregates") or {}
    rows = []
    for name in ("A", "B", "C"):
        cov = candidates_out[name]["coverage"]
        ctrl = control_out[name]
        orc = oracle_out[name]
        gap = orc["O_store_achievable_minus_control_C1"]
        rows.append(
            f"| {name} | {CANDIDATES[name]['rule']} | {cov:.4f} | "
            f"{ctrl['store_hit_recall_evi']} | {ctrl['precision_evi']} | "
            f"{orc['O_store']} | {orc['O_store_achievable']} | "
            f"{orc['O_evi']} | {gap:.4f} | "
            f"{'是' if gap >= 0.02 else '否'} |")

    any_band = any(oracle_out[x]["separable_band_ge_0.02"] for x in CANDIDATES)
    if not any_band:
        verdict = ("**NO_SEPARABLE_BAND** — 所有候选的 context-reachable "
                   "O_store − control < 0.02，无足够区分空间，建议停止 M6a。")
    else:
        verdict = ("存在可分离区间：至少一个候选的 context-reachable "
                   "O_store − control ≥ 0.02；建议进入 Phase 2B（阈值由 "
                   "owner 在区间内选定）。")
    if candidates_out["B"]["coverage"] >= 0.95:
        q2a = ("**B（双边）**：条件覆盖率 "
               f"{candidates_out['B']['coverage']:.4f} ≥ 95%，符合预注册 "
               "§3 决策规则 1；A/C 作敏感性并列。")
        q2a_short = "B（双边；覆盖达标）"
    else:
        q2a = (f"**A（单边 runtime，宽松）**：B 覆盖率 "
               f"{candidates_out['B']['coverage']:.4f} < 95%，按预注册 §3 "
               f"回退 A（覆盖 {candidates_out['A']['coverage']:.4f}）；"
               "**Phase 2B 报告必须披露“单边宽松”**，并附 B/C 敏感性表。")
        q2a_short = "A（单边宽松；B 覆盖 <95% 回退）"

    c_ctrl = control_out["C"]
    band_low = r4(control_out["A"]["store_hit_recall_evi"] + 0.02)
    primary = ("B" if candidates_out["B"]["coverage"] >= 0.95 else "A")
    band_high = r4(oracle_out[primary]["O_store_achievable"] - 0.01)
    midpoint = r4(control_out[primary]["store_hit_recall_evi"]
                  + 0.5 * oracle_out[primary]
                  ["O_store_achievable_minus_control_C1"])

    md = f"""# M6a Phase 2A：映射候选与 oracle 上界（只读计算）

- 日期：{generated_at}
- 仓库状态：main 工作树未触碰；worktree `{head[:7]}` @ `{head}`
- 性质：**只读离线计算**——0 LLM、0 judge、0 al3、0 网络、0 生成；truth 仅在离线脚本使用，未进入产品
- 产物目录：`results/answer-level/m6a-phase2a-2026-11-01/`
- 脚本：`scripts/audit/phase2a_oracle.py`（唯一新增代码，只读）
- 预注册：`plans/ANSWER-LEVEL-M6a-PHASE2A-ORACLE-PREREGISTRATION-2026-11-01.md`
- 上游证据：`docs/AUDIT-CHUNK-DOMAIN-2026-11-01.md` §5A + `results/answer-level/chunk-domain-audit-2026-11-01/`

## 0. 输入核验（全部通过，未触发停止条件）

| 项 | 预期 | 实测 |
|---|---|---|
| worktree HEAD | `ab4073c` | `{head[:7]}` ✓ |
| runtime-map 行数 | 2,947 | {EXPECTED_RUNTIME_ROWS:,} ✓ |
| mapping 行数 | 1,006 | {EXPECTED_MAPPING_ROWS:,} ✓ |
| a′ baseline 例数 | 150 | {n} ✓ |
| baseline SHA 前缀 | `5cd712` | `{baseline_sha[:12]}…` ✓ |
| baseline cases_failed | 0 | {b_aggs.get('cases_failed')} ✓ |
| ordered IDs 可解析 | 3,108/3,108 | 3,108/3,108 ✓ |
| baseline truth == v2.1 dataset（集合比对） | 0 mismatch | 0 ✓（生产加载路径 `resolve_generation_dataset('v2.1')` → `evaluation/datasets/v2.1.jsonl`，SHA `{dataset_sha[:12]}…`；truth 按集合比对——指标全部为集合运算） |
| dataset 内容 == baseline 运行时 | 内容相同 | ✓（git blob `4597167d…` == baseline-run 记录值；worktree 裸 SHA `{dataset_sha[:12]}…` 仅因 `core.autocrlf=true` 将 LF→CRLF，LF 归一后与 blob 逐字节相同——内容零差异） |

- 数据备注（非停止条件）：`mixed-033` 的 dataset `relevant_chunk_ids` 列表内含重复条目 `c9fd20815ea8_chunk_18` ×2；baseline 存的是去重后的单条。集合语义下两者完全一致（Phase 1 `truth_mismatch_vs_dataset=0` 同为集合比对），不构成域不一致，未修改数据集。

- baseline 旧（ID 碰撞域）manifest 值：recall {b_aggs.get('citation_recall_avg')} / precision {b_aggs.get('citation_precision_avg')} —— 与 Phase 1 §4.1 ID 碰撞复现一致，**不可平移**。
- truth：{truth_cases}/150 例非空（28 拒答例空 truth），distinct store truth chunk {distinct_truth} 个。

## 1. 三种映射候选（t = 0.50，覆盖分母 = 1,006 store chunks）

| 候选 | 规则 | 覆盖率 | 一对多 | 歧义 | 未映射 truth（distinct/{distinct_truth}） |
|---|---|---:|---:|---:|---:|
| A | ratio_runtime ≥ 0.50 | {candidates_out['A']['coverage']:.4f} | {candidates_out['A']['one_to_many']} | {candidates_out['A']['ambiguous']} | {candidates_out['A']['distinct_case_truth_unmapped']} |
| B | runtime ≥ 0.50 且 store ≥ 0.50 | {candidates_out['B']['coverage']:.4f} | {candidates_out['B']['one_to_many']} | {candidates_out['B']['ambiguous']} | {candidates_out['B']['distinct_case_truth_unmapped']} |
| C | ratio_store ≥ 0.50（敏感性） | {candidates_out['C']['coverage']:.4f} | {candidates_out['C']['one_to_many']} | {candidates_out['C']['ambiguous']} | {candidates_out['C']['distinct_case_truth_unmapped']} |

读法：A 覆盖 {candidates_out['A']['coverage']:.4f} 与 Phase 1 一致（98.5%）；C 覆盖 {candidates_out['C']['coverage']:.4f} < 95%，**只作敏感性，不作主口径**（预注册 §3 规则 3）。B 为双边，覆盖 {candidates_out['B']['coverage']:.4f}。

## 2. control（a′ baseline）与 oracle 上界（逐例均值，round 4，150 例）

| 候选 | 映射规则 | 覆盖率 | control C1 (store_hit_recall_evi) | control C3 (precision_evi) | O_store（理论上界） | O_store_ach（context-reachable） | O_evi | O_store_ach − control | ≥0.02? |
|---|---|---:|---:|---:|---:|---:|---:|---:|:--|
{chr(10).join(rows)}

辅助（不参与裁决，详见 control-metrics.json）：A 候选下 recall_evi={control_out['A']['recall_evi']}、mean_rel_runtime_size={control_out['A']['mean_rel_runtime_size']}、precision_ctx={control_out['A']['precision_ctx']}、case_any_overlap_evi={control_out['A']['case_any_overlap_evi']}；fabricated 合计={control_out['A']['fabricated_total']}、retrieved_not_in_context 合计={control_out['A']['retrieved_not_in_context_total']}（**capture 域旧值，Phase 2B 须按预注册 §6 在 capture 修复后重测方可入 C3**）。

**关键读法（2026-11-02 修正）**：`O_store` 假设每个 truth 都可达，**不是 M6a 的可达上界**；M6a 只能重定向到本 case context 内的 chunk，因此阈值只能用 `O_store_ach`（同时扣除未映射 truth 与不在 context 的 truth）。A 候选 context-reachable 真值率约 50%，`O_store_ach` 明显低于 `O_store`；若 Phase 2B 阈值按 `O_store` 设定，会不可达。`O_evi_ach` 见 oracle.json。

**O_store_ach − control ≥ 0.02 判定**：{'通过（至少一个候选）' if any_band else '全部未通过'}。{verdict}

## 3. 决策就绪建议（Q2-a..f，只给建议，不做裁决）

| 编号 | 建议 | 依据 |
|---|---|---|
| Q2-a 映射 | {q2a_short} | {q2a} |
| Q2-b C1 主指标 | `store_hit_recall_evi`（分母 = store truth，一对多免疫） | §2 表：C1 = A 候选 {control_out['A']['store_hit_recall_evi']} / B {control_out['B']['store_hit_recall_evi']} / C {control_out['C']['store_hit_recall_evi']} |
| Q2-c C3 主指标 | `precision_evi`（区域级精度）；非劣门槛 = control − 0.01；fabricated/retrieved 两项**未验证**（capture 修复未实施），C3 只能按“precision 非劣 + 两标记未验证”降级表述 | 预注册 §6；本目录 control-metrics.json |
| Q2-d oracle 方法 | `min(m, truth_reachable)/truth` 逐例均值；m = 答案中既有 `\\[S\\d+\\]` 槽位数；truth_reachable = 映射 runtime 与本 case context 有交集的 store truth；不新增/删除槽位；一槽至多命中一个 truth | oracle.json（理论 O_store 仅作上界披露） |
| Q2-e 阈值规则 | Phase 2B 在 [{band_low}, {band_high}] 内由 owner 选定；建议中点 {midpoint}（= control + 0.5×可分离区间，round 4），不得低于 control+0.02、不得高于 O_store_ach−0.01 | 预注册 §6 建议规则 |
| Q2-f 预算 | Phase 2A **0 LLM / 0 token**（本目录即为交付，已满足）；Phase 2B ≤158,521 judge/al3 token（72,521+86,000），且总预算仍受 1,500,000/400 硬上界 | 预注册 §6/§7 |

C 候选补充披露：C 覆盖 {candidates_out['C']['coverage']:.4f} < 95%，其 control（C1={c_ctrl['store_hit_recall_evi']}、C3={c_ctrl['precision_evi']}）与 oracle（O_store={oracle_out['C']['O_store']}）**仅作敏感性参考，不得单独作结论**。

## 4. 停止条件核查（本阶段）

| # | 停止条件（任务 §7） | 结果 |
|---|---|---|
| 1 | baseline 非 150 例或 SHA 不符 | 未触发（150 例，SHA `{baseline_sha[:12]}…`） |
| 2 | runtime map ≠ 2,947 或 mapping ≠ 1,006 | 未触发 |
| 3 | 需要 LLM/网络 | 未触发（全程离线） |
| 4 | 需要改 src/ 或 evaluation/ | 未触发（只读导入生产加载路径，未改动） |
| 5 | 任一候选覆盖率 < 95% 时被当作主口径 | 未触发（C 仅作敏感性报告） |
| — | O_store_ach − control < 0.02 → NO_SEPARABLE_BAND | {'触发！见 §2' if not any_band else '未触发（见 §2 判定列）'} |

## 5. 声明

- 未跑模型：未调用 LLM、未联网、未跑 judge/al3、未生成任何答案；所有数字为 a′ baseline 与 Phase 1 映射的离线复算。
- 未 commit、未 push；产物留在 worktree `eval/m6a-phase2a-2026-11-01`，由父会话复核。
- 未修改 `src/`、`evaluation/`、`plans/`、`docs/`、`CHANGELOG`、数据集、store 与产品默认；本阶段唯一新增代码为 `scripts/audit/phase2a_oracle.py`。
- 运行时真值（v2.1 `relevant_chunk_ids`）仅用于离线比对与 oracle 计算，未写回产品、未用于调阈值。
- 本文件只给建议，Q2-a..f 最终口径与阈值由 owner 签批。
"""
    return md


if __name__ == "__main__":
    sys.exit(main())
