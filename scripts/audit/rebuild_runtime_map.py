#!/usr/bin/env python3
"""Phase 1 §3.1 — rebuild runtime v3 chunk map (READ-ONLY audit).

Reuses production `src.loaders` + `src.chunking.chunk_document` verbatim
(no re-implementation of splitting logic) to rebuild the runtime index
chunks for the 13 v2 dataset source documents, records full text +
located character spans, and checks context-ID resolvability of the
M2 / M4c-arm1 / M4c-arm2 / a' baselines against the rebuilt map.

Outputs (all under results/answer-level/chunk-domain-audit-2026-11-01/):
  - runtime-map.jsonl
  - runtime-map-manifest.json  (totals, per-source counts, source SHAs,
                                script SHA, self-hash, git commit, run time)

Never writes into src/, evaluation/, tests/, config/ or data/.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from src.loaders import LoaderRegistry, PdfLoader, DocxLoader, TextLoader  # noqa: E402
from src.chunking import chunk_document  # noqa: E402

OUT_DIR = REPO / "results" / "answer-level" / "chunk-domain-audit-2026-11-01"
CORPUS_DIR = REPO / "data" / "v2-corpus" / "documents" / "processed"
DATASET = REPO / "evaluation" / "datasets" / "v2.1.jsonl"

ARMS = {
    "m2": REPO / "results" / "answer-level" / "m2-baseline-2026-08-30" / "outcomes.jsonl",
    "arm1": REPO / "results" / "answer-level" / "m4c-arm1-2026-09-06" / "outcomes.jsonl",
    "arm2": REPO / "results" / "answer-level" / "m4c-arm2-2026-09-06" / "outcomes.jsonl",
    "a_prime": OUT_DIR / "_tmp-baseline-outcomes.jsonl",
}


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def resolve_source(name: str) -> Path | None:
    """Same resolution semantics as generation_runner.build_index."""
    candidate = CORPUS_DIR / name
    if candidate.exists():
        return candidate
    lowered = {p.name.lower(): p for p in CORPUS_DIR.iterdir() if p.is_file()}
    return lowered.get(name.lower())


def build_norm_index(raw: str):
    """Whitespace-stripped view of raw text with position back-mapping."""
    norm_chars: list[str] = []
    norm_pos: list[int] = []
    for i, ch in enumerate(raw):
        if not ch.isspace():
            norm_chars.append(ch)
            norm_pos.append(i)
    return "".join(norm_chars), norm_pos


def locate_spans(raw: str, texts: list[str]) -> list[tuple[int, int] | None]:
    """Locate each chunk text inside raw text (whitespace-insensitive,
    sequential/document-order search so duplicates and overlapping
    chunks resolve to their true occurrences). Returns raw char spans
    [start, end) or None when not locatable."""
    norm_raw, norm_pos = build_norm_index(raw)
    norm_lower = norm_raw.lower()
    spans: list[tuple[int, int] | None] = []
    cursor = 0
    prev_text = None
    prev_p = -1
    for t in texts:
        nt = "".join(c for c in t if not c.isspace())
        if not nt:
            spans.append(None)
            prev_text = t
            continue
        start = cursor
        if prev_text is not None and t == prev_text:
            # identical consecutive chunk text -> next occurrence
            start = prev_p + 1
        p = norm_raw.find(nt, start)
        method = "norm"
        if p < 0:
            p = norm_lower.find(nt.lower(), start)
            method = "norm_ci"
        if p < 0 and start > 0:
            p = norm_raw.find(nt, 0)
            if p < 0:
                p = norm_lower.find(nt.lower(), 0)
            method = "norm_from0" if p >= 0 else "failed"
        if p < 0:
            spans.append(None)
        else:
            raw_start = norm_pos[p]
            raw_end = norm_pos[p + len(nt) - 1] + 1
            spans.append((raw_start, raw_end))
            cursor = p
        prev_text = t
        prev_p = p if p >= 0 else prev_p
    return spans


def normalized_id(chunk_id: str) -> str:
    """12-hex domain normalization (same rule as evaluation runner)."""
    if "_chunk_" in chunk_id:
        prefix, _, idx = chunk_id.rpartition("_chunk_")
        return f"{prefix[:12]}_chunk_{idx}"
    if chunk_id.endswith("_anchor"):
        prefix = chunk_id[: -len("_anchor")]
        return f"{prefix[:12]}_anchor"
    return chunk_id[:12]


def load_jsonl(path: Path) -> list[dict]:
    rows = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def check_resolvability(name: str, path: Path, id_set: set[str]) -> dict:
    rows = load_jsonl(path)
    field = ("context_chunk_ids_ordered"
             if name == "a_prime" else "context_chunk_ids")
    total_ids = 0
    resolved_ids = 0
    unresolved: dict[str, int] = {}
    cases_total = 0
    cases_fully_resolved = 0
    case_rates: list[float] = []
    for row in rows:
        ids = row.get(field) or []
        cases_total += 1
        ok = sum(1 for c in ids if c in id_set)
        total_ids += len(ids)
        resolved_ids += ok
        case_rates.append((ok / len(ids)) if ids else 1.0)
        if ids and ok == len(ids):
            cases_fully_resolved += 1
        for c in ids:
            if c not in id_set:
                unresolved[c] = unresolved.get(c, 0) + 1
    return {
        "arm": name,
        "field": field,
        "case_count": cases_total,
        "cases_fully_resolvable": cases_fully_resolved,
        "distinct_ids": len({c for row in rows for c in (row.get(field) or [])}),
        "total_id_refs": total_ids,
        "resolved_id_refs": resolved_ids,
        "resolvable_rate": round(resolved_ids / total_ids, 6) if total_ids else 0.0,
        "mean_case_resolvable_rate": round(sum(case_rates) / len(case_rates), 6)
        if case_rates else 0.0,
        "unresolved_distinct": len(unresolved),
        "unresolved_top": sorted(unresolved.items(), key=lambda kv: -kv[1])[:50],
    }


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    started = time.strftime("%Y-%m-%dT%H:%M:%S%z")

    # 13 dataset source files (authoritative list from the dataset)
    source_names: list[str] = []
    seen: set[str] = set()
    with DATASET.open(encoding="utf-8") as f:
        for line in f:
            row = json.loads(line)
            for s in row.get("relevant_source_ids") or []:
                if s not in seen:
                    seen.add(s)
                    source_names.append(s)
    source_names.sort()

    registry = LoaderRegistry()
    registry.register(PdfLoader())
    registry.register(DocxLoader())
    registry.register(TextLoader())

    out_path = OUT_DIR / "runtime-map.jsonl"
    per_source: dict[str, dict] = {}
    total = 0
    normalized_index: set[str] = set()
    source_shas: dict[str, str] = {}
    span_missing = 0

    with out_path.open("w", encoding="utf-8", newline="\n") as out:
        for name in source_names:
            path = resolve_source(name)
            if path is None:
                per_source[name] = {"error": "file not found", "chunks": 0}
                continue
            raw = path.read_text(encoding="utf-8", errors="replace")
            source_shas[name] = sha256_file(path)

            # Production parse+chunk path (identical to src/rag.py loader flow)
            document = registry.load(str(path))
            document.chunks = chunk_document(document)
            texts = [c.text for c in document.chunks]
            spans = locate_spans(raw, texts)

            n_ok = 0
            for chunk, span in zip(document.chunks, spans):
                if span is None:
                    span_missing += 1
                    span_start = span_end = None
                else:
                    span_start, span_end = span
                    n_ok += 1
                nid = normalized_id(chunk.chunk_id)
                normalized_index.add(nid)
                out.write(json.dumps({
                    "chunk_id": chunk.chunk_id,
                    "normalized_id": nid,
                    "source": name,
                    "source_id": document.source_id,
                    "text": chunk.text,
                    "span_start": span_start,
                    "span_end": span_end,
                    "section_char_start": chunk.char_start,
                    "section_char_end": chunk.char_end,
                    "parent_id": chunk.parent_chunk_id,
                    "section_path": chunk.section_heading,
                    "chunk_index": chunk.chunk_index,
                    "page": chunk.page,
                }, ensure_ascii=False) + "\n")
                total += 1
            per_source[name] = {
                "chunks": len(document.chunks),
                "spans_located": n_ok,
                "source_sha256": source_shas[name],
                "file": str(path.relative_to(REPO)),
            }

    # context-ID resolvability for the four baselines
    resolvability = {
        arm: check_resolvability(arm, path, normalized_index)
        for arm, path in ARMS.items() if path.exists()
    }

    git_commit = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=REPO,
        capture_output=True, text=True, check=False,
    ).stdout.strip()

    map_sha = sha256_file(out_path)
    script_sha = sha256_file(Path(__file__))
    manifest = {
        "phase": "Phase1-3.1-runtime-map",
        "started_at": started,
        "finished_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "git_commit": git_commit,
        "expected_total": 2947,
        "total_chunks": total,
        "total_matches_expected": total == 2947,
        "spans_located": total - span_missing,
        "spans_missing": span_missing,
        "distinct_normalized_ids": len(normalized_index),
        "per_source": per_source,
        "source_sha256": source_shas,
        "inputs": {
            "dataset": str(DATASET.relative_to(REPO)),
            "dataset_sha256": sha256_file(DATASET),
            "runtime_map": "runtime-map.jsonl",
            "runtime_map_sha256": map_sha,
        },
        "scripts": {"rebuild_runtime_map.py": script_sha},
        "resolvability": resolvability,
        "method": (
            "LoaderRegistry(Pdf/Docx/Text).load + src.chunking.chunk_document "
            "(production path, no re-implementation); spans located by "
            "whitespace-insensitive sequential search of chunk text in the "
            "raw source file; normalized_id = first 12 hex of source_id "
            "(same rule as evaluation/generation_runner._normalize_chunk_id)."
        ),
        "read_only_guarantees": [
            "no writes outside results/answer-level/chunk-domain-audit-2026-11-01/",
            "no LLM calls, no network",
        ],
    }
    manifest_path = OUT_DIR / "runtime-map-manifest.json"
    manifest_body = json.dumps(manifest, ensure_ascii=False, sort_keys=True)
    manifest["manifest_self_sha256"] = sha256_text(manifest_body)
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8")

    print(f"total_chunks={total} expected=2947 match={total == 2947}")
    print(f"spans_located={total - span_missing} missing={span_missing}")
    for arm, info in resolvability.items():
        print(f"{arm}: rate={info['resolvable_rate']} "
              f"cases_fully={info['cases_fully_resolvable']}/{info['case_count']} "
              f"unresolved_distinct={info['unresolved_distinct']}")
    print(f"manifest: {manifest_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
