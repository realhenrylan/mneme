#!/usr/bin/env python3
"""Phase 1 §3.2 — build store-truth → runtime-chunk bridge (READ-ONLY).

For every store chunk (data/v2-corpus/chunks/chunks.jsonl, 1006 rows) find
runtime candidates in the rebuilt runtime map by source + character-span
overlap (both sides located in the same raw source file with a
whitespace-insensitive sequential search). No ID-based mapping anywhere:
every link carries span or normalized-text evidence.

Outputs:
  - mapping.jsonl   (one row per store chunk, all candidates + ratios)
  stats are merged into metrics.json by recompute_metrics.py.
"""
from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import rebuild_runtime_map as rrm  # noqa: E402  (reuses locate_spans etc.)

OUT_DIR = REPO / "results" / "answer-level" / "chunk-domain-audit-2026-11-01"
STORE_CHUNKS = REPO / "data" / "v2-corpus" / "chunks" / "chunks.jsonl"
RUNTIME_MAP = OUT_DIR / "runtime-map.jsonl"
MAPPING_OUT = OUT_DIR / "mapping.jsonl"

CORPUS_DIR = REPO / "data" / "v2-corpus" / "documents" / "processed"


def load_runtime_by_source() -> dict[str, list[dict]]:
    by_source: dict[str, list[dict]] = defaultdict(list)
    with RUNTIME_MAP.open(encoding="utf-8") as f:
        for line in f:
            row = json.loads(line)
            by_source[row["source"]].append(row)
    return by_source


def load_store_chunks() -> list[dict]:
    rows = []
    with STORE_CHUNKS.open(encoding="utf-8") as f:
        for line in f:
            rows.append(json.loads(line))
    return rows


def resolve_source(name: str) -> Path | None:
    candidate = CORPUS_DIR / name
    if candidate.exists():
        return candidate
    lowered = {p.name.lower(): p for p in CORPUS_DIR.iterdir() if p.is_file()}
    return lowered.get(Path(name).name.lower())


def norm_ws(text: str) -> str:
    return "".join(c for c in text if not c.isspace())


def main() -> int:
    runtime = load_runtime_by_source()
    store_rows = load_store_chunks()

    # group store rows per source, preserve document order
    store_by_source: dict[str, list[dict]] = defaultdict(list)
    for row in store_rows:
        store_by_source[Path(row["source"]).name].append(row)

    stats = {
        "store_total": len(store_rows),
        "mapped_any": 0,
        "unmapped": 0,
        "one_to_many": 0,
        "ambiguous": 0,          # >=2 candidates each covering >=50% of store chunk
        "span_located": 0,
        "containment_fallback": 0,
        "failed": 0,
        "by_threshold_runtime": {"0.25": 0, "0.50": 0, "0.75": 0},
        "by_threshold_store": {"0.25": 0, "0.50": 0, "0.75": 0},
        "unmapped_examples": [],
        "ambiguous_examples": [],
        "per_source": {},
    }

    with MAPPING_OUT.open("w", encoding="utf-8", newline="\n") as out:
        for source_name in sorted(store_by_source):
            srows = store_by_source[source_name]
            rt = runtime.get(source_name, [])
            if not rt:
                for row in srows:
                    out.write(json.dumps({
                        "store_chunk_id": row["chunk_id"],
                        "source": source_name,
                        "unmapped": True,
                        "reason": "no runtime chunks for source",
                    }, ensure_ascii=False) + "\n")
                    stats["unmapped"] += 1
                continue

            path = resolve_source(source_name)
            raw = path.read_text(encoding="utf-8", errors="replace") if path else ""

            # locate store chunk texts in raw source (document order)
            store_texts = [row["text"] for row in srows]
            store_spans = rrm.locate_spans(raw, store_texts) if raw else \
                [None] * len(srows)

            rt_norms = [norm_ws(c["text"]) for c in rt]

            src_mapped = 0
            for srow, sspan in zip(srows, store_spans):
                candidates = []
                method = "span_overlap"
                if sspan is not None:
                    stats["span_located"] += 1
                    s0, s1 = sspan
                    slen = s1 - s0
                    for rrow in rt:
                        r0, rrow_end = rrow["span_start"], rrow["span_end"]
                        if r0 is None:
                            continue
                        ov = min(s1, rrow_end) - max(s0, r0)
                        if ov <= 0:
                            continue
                        candidates.append({
                            "runtime_chunk_id": rrow["chunk_id"],
                            "overlap_chars": ov,
                            "ratio_store": round(ov / slen, 4),
                            "ratio_runtime": round(
                                ov / (rrow_end - r0), 4),
                            "runtime_span": [r0, rrow_end],
                        })
                # fallback: normalized text containment (no usable span)
                if not candidates:
                    method = "text_containment"
                    sn = norm_ws(srow["text"])
                    if sn:
                        for rrow, rn in zip(rt, rt_norms):
                            if not rn:
                                continue
                            if sn in rn:
                                candidates.append({
                                    "runtime_chunk_id": rrow["chunk_id"],
                                    "overlap_chars": len(sn),
                                    "ratio_store": 1.0,
                                    "ratio_runtime": round(
                                        len(sn) / len(rn), 4),
                                    "runtime_span": [rrow["span_start"],
                                                     rrow["span_end"]],
                                })
                            elif rn in sn and len(rn) >= 0.5 * len(sn):
                                candidates.append({
                                    "runtime_chunk_id": rrow["chunk_id"],
                                    "overlap_chars": len(rn),
                                    "ratio_store": round(len(rn) / len(sn), 4),
                                    "ratio_runtime": 1.0,
                                    "runtime_span": [rrow["span_start"],
                                                     rrow["span_end"]],
                                })
                    if candidates:
                        stats["containment_fallback"] += 1

                if not candidates:
                    stats["unmapped"] += 1
                    if sspan is None:
                        stats["failed"] += 1
                    if len(stats["unmapped_examples"]) < 30:
                        stats["unmapped_examples"].append({
                            "store_chunk_id": srow["chunk_id"],
                            "source": source_name,
                            "span_located": sspan is not None,
                            "text_head": srow["text"][:80],
                        })
                else:
                    src_mapped += 1
                    stats["mapped_any"] += 1
                    if len(candidates) > 1:
                        stats["one_to_many"] += 1
                    strong = [c for c in candidates if c["ratio_store"] >= 0.5]
                    if len(strong) >= 2:
                        stats["ambiguous"] += 1
                        if len(stats["ambiguous_examples"]) < 30:
                            stats["ambiguous_examples"].append({
                                "store_chunk_id": srow["chunk_id"],
                                "source": source_name,
                                "strong_candidates": [
                                    c["runtime_chunk_id"] for c in strong],
                            })
                    for t in ("0.25", "0.50", "0.75"):
                        tf = float(t)
                        if any(c["ratio_runtime"] >= tf for c in candidates):
                            stats["by_threshold_runtime"][t] += 1
                        if any(c["ratio_store"] >= tf for c in candidates):
                            stats["by_threshold_store"][t] += 1

                out.write(json.dumps({
                    "store_chunk_id": srow["chunk_id"],
                    "source": source_name,
                    "store_span": list(sspan) if sspan else None,
                    "store_text_len": len(srow["text"]),
                    "method": method,
                    "n_candidates": len(candidates),
                    "candidates": candidates,
                    "unmapped": not candidates,
                }, ensure_ascii=False) + "\n")

            stats["per_source"][source_name] = {
                "store_chunks": len(srows),
                "mapped": src_mapped,
                "coverage": round(src_mapped / len(srows), 4) if srows else 0.0,
            }

    stats["coverage_any"] = round(stats["mapped_any"] / stats["store_total"], 6)
    stats["coverage_by_threshold_runtime"] = {
        t: round(v / stats["store_total"], 6)
        for t, v in stats["by_threshold_runtime"].items()}
    stats["coverage_by_threshold_store"] = {
        t: round(v / stats["store_total"], 6)
        for t, v in stats["by_threshold_store"].items()}
    (OUT_DIR / "bridge-stats.json").write_text(
        json.dumps(stats, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8")

    print(f"store_total={stats['store_total']} mapped_any={stats['mapped_any']} "
          f"coverage={stats['coverage_any']}")
    print(f"unmapped={stats['unmapped']} one_to_many={stats['one_to_many']} "
          f"ambiguous={stats['ambiguous']}")
    print(f"span_located={stats['span_located']} "
          f"containment_fallback={stats['containment_fallback']}")
    print(f"coverage@runtime-threshold: {stats['coverage_by_threshold_runtime']}")
    print(f"coverage@store-threshold:   {stats['coverage_by_threshold_store']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
