#!/usr/bin/env python3
"""Phase 1 §3.4 — audit the a' (M6a paired) baseline for replayability
(READ-ONLY, NO adjudication of C1/C2/C3).

Checks over the 150 baseline records (extracted from eval branch de8181f):
  1. context_chunk_ids_ordered resolvability against runtime-map.jsonl;
  2. whether full_sources is complete context or just record.snippet
     (compares full_sources text against the runtime chunk texts and
     against the snippet-only format_sources output);
  3. verdict: can the context be EXACTLY replayed from the record alone?

Writes baseline-audit.json into the audit output dir.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
OUT_DIR = REPO / "results" / "answer-level" / "chunk-domain-audit-2026-11-01"
BASELINE = OUT_DIR / "_tmp-baseline-outcomes.jsonl"
RUNTIME_MAP = OUT_DIR / "runtime-map.jsonl"


def main() -> int:
    rt_text: dict[str, str] = {}
    with RUNTIME_MAP.open(encoding="utf-8") as f:
        for line in f:
            row = json.loads(line)
            rt_text[row["normalized_id"]] = row["text"]

    n = 0
    ordered_total = 0
    ordered_resolved = 0
    cases_fully_resolved = 0
    full_sources_is_snippet_only = 0
    full_sources_contains_full_text = 0
    full_sources_mismatch = 0
    per_case_example = None

    with BASELINE.open(encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            row = json.loads(line)
            n += 1
            ordered = row.get("context_chunk_ids_ordered") or []
            fs = row.get("full_sources") or ""

            resolved = [c for c in ordered if c in rt_text]
            ordered_total += len(ordered)
            ordered_resolved += len(resolved)
            if ordered and len(resolved) == len(ordered):
                cases_fully_resolved += 1

            # Does full_sources contain the FULL text of every ordered chunk?
            full_present = all(
                rt_text[c] in fs for c in resolved) if resolved else False
            # Or only the 150-char snippet (snippets joined by newline)?
            snippet_only = True
            full_text_found = 0
            for c in resolved:
                text = rt_text[c]
                # exact src/citations.py:39: .replace("\n", " ")[:150]
                # ("\n" is a real newline; ops file view had escaped it)
                snippet = text.replace("\n", " ")[:150]
                # genuine full text only when chunk >150 chars AND whole
                # text present; short chunks trivially satisfy text-in-fs
                if len(text) > 150 and text in fs:
                    full_text_found += 1
                    snippet_only = False
                elif snippet not in fs:
                    snippet_only = False
            if full_text_found == len(resolved) and resolved:
                full_sources_contains_full_text += 1
            if snippet_only and resolved:
                full_sources_is_snippet_only += 1
            if not snippet_only and not full_text_found:
                full_sources_mismatch += 1

            if per_case_example is None and ordered:
                total_chunk_chars = sum(
                    len(rt_text[c]) for c in resolved)
                per_case_example = {
                    "case_id": row["case_id"],
                    "ordered_count": len(ordered),
                    "resolved_count": len(resolved),
                    "full_sources_chars": len(fs),
                    "sum_full_chunk_text_chars": total_chunk_chars,
                    "ratio": round(len(fs) / total_chunk_chars, 4)
                    if total_chunk_chars else None,
                }

    out = {
        "phase": "Phase1-3.4-baseline-audit",
        "case_count": n,
        "ordered_id_total": ordered_total,
        "ordered_id_resolved": ordered_resolved,
        "ordered_resolvable_rate": round(
            ordered_resolved / ordered_total, 6) if ordered_total else 0.0,
        "cases_fully_resolvable": cases_fully_resolved,
        "full_sources_cases_snippet_only": full_sources_is_snippet_only,
        "full_sources_cases_with_full_text": full_sources_contains_full_text,
        "full_sources_cases_mismatch": full_sources_mismatch,
        "example_case": per_case_example,
        "verdict": None,
        "note": (
            "audit only; no C1/C2/C3 adjudication. snippet format evidence: "
            "src/citations.py:39 snippet=documents[index].replace(newline,"
            " ' ')[:150]; format_sources (src/rag.py:2141-2144) renders "
            "record.snippet only."),
    }
    if (ordered_total and ordered_resolved == ordered_total
            and full_sources_is_snippet_only == n
            and full_sources_contains_full_text == 0):
        out["verdict"] = (
            "IDs fully resolvable in runtime domain, but full_sources holds "
            "only 150-char snippets -> context NOT exactly replayable from "
            "the record alone (full chunk text must come from runtime map).")
    elif ordered_total and ordered_resolved == ordered_total:
        out["verdict"] = (
            "IDs fully resolvable; full_sources completeness mixed - see "
            "per-case counts.")
    else:
        out["verdict"] = "ordered IDs not fully resolvable; replay blocked."

    (OUT_DIR / "baseline-audit.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8")
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
