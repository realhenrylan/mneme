"""Corpus v2 annotation merge + fail-closed validation.

Merges the deterministic skeleton (id/type/language/difficulty/band/chain
allocation) with the LLM_ASSISTED draft content (query / relevant chunks /
answer points) and validates the combined pack:

- exact 150 cases, ids exactly the skeleton set;
- every relevant_chunk_id exists in the chunk manifest and belongs to the
  referenced source;
- legal relevance_level combinations (none / chunk / source);
- source-only ratio <= 10% of new cases;
- refusal cases carry no evidence; answerable cases carry answer points;
- chain integrity (contiguous turns, follow_up_to exists).

Usage: python scripts/corpus_v2_merge.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
V2 = ROOT / "evaluation" / "datasets" / "v2"
ANNO = V2 / "annotations"

sys.path.insert(0, str(ROOT))
from evaluation.corpus_v2 import snippet_is_evidence  # noqa: E402
from scripts.corpus_v2_content_a import CASES_A  # noqa: E402
from scripts.corpus_v2_content_b import CASES_B  # noqa: E402
from scripts.corpus_v2_content_c import CASES_C  # noqa: E402
from scripts.corpus_v2_content_d import CASES_D  # noqa: E402

CONTENT = {**CASES_A, **CASES_B, **CASES_C, **CASES_D}


def load_chunk_index() -> dict[str, dict]:
    idx: dict[str, dict] = {}
    for line in (ROOT / "data" / "v2-corpus" / "chunks" / "chunks.jsonl").open(
            encoding="utf-8"):
        row = json.loads(line)
        idx[row["chunk_id"]] = row
    return idx


def merge() -> tuple[list[dict], list[str]]:
    skeleton = [json.loads(l) for l in
                (ANNO / "skeleton.jsonl").open(encoding="utf-8") if l.strip()]
    chunk_idx = load_chunk_index()
    errors: list[str] = []

    skeleton_ids = {c["id"] for c in skeleton}
    content_ids = set(CONTENT)
    if skeleton_ids != content_ids:
        missing = sorted(skeleton_ids - content_ids)
        extra = sorted(content_ids - skeleton_ids)
        if missing:
            errors.append(f"missing content for ids: {missing}")
        if extra:
            errors.append(f"content ids not in skeleton: {extra}")

    out = []
    n_source_only = 0
    for case in skeleton:
        cid = case["id"]
        if cid not in CONTENT:
            continue
        c = CONTENT[cid]
        # merge content fields
        case["query"] = c["query"]
        case["relevant_source_ids"] = c["relevant_source_ids"]
        case["relevant_chunks"] = c["relevant_chunks"]
        case["relevant_chunk_ids"] = c["relevant_chunk_ids"]
        case["acceptable_answer_points"] = c["acceptable_answer_points"]
        case["should_refuse"] = c["should_refuse"]
        case["relevance_level"] = c["relevance_level"]
        if c.get("review_notes"):
            case["annotation"]["review_notes"] = c["review_notes"]

        # ── validation ──
        level = case["relevance_level"]
        qtype = case["query_type"]
        src_ids = set(case["relevant_source_ids"])
        chunk_ids = case["relevant_chunk_ids"]
        is_refusal_turn = bool(c.get("is_refusal_turn", False))

        # legal combinations
        if level == "none":
            if not case["should_refuse"]:
                errors.append(f"{cid}: relevance_level=none but should_refuse=False")
            if src_ids or chunk_ids or case["acceptable_answer_points"]:
                errors.append(f"{cid}: none level carries evidence")
        elif level == "chunk":
            if case["should_refuse"] and not is_refusal_turn:
                errors.append(f"{cid}: chunk level but should_refuse=True")
            if not src_ids or not chunk_ids:
                errors.append(f"{cid}: chunk level missing sources/chunks")
            if not case["acceptable_answer_points"]:
                errors.append(f"{cid}: chunk level missing answer points")
        elif level == "source":
            if case["should_refuse"]:
                errors.append(f"{cid}: source level but should_refuse=True")
            if not src_ids or chunk_ids:
                errors.append(f"{cid}: source level chunk ids must be empty")
            if not case["acceptable_answer_points"]:
                errors.append(f"{cid}: source level missing answer points")
            n_source_only += 1
        else:
            errors.append(f"{cid}: unknown relevance_level {level}")

        # chunk ids exist in manifest and belong to source
        for rc in case["relevant_chunks"]:
            cid2 = rc.get("chunk_id")
            row = chunk_idx.get(cid2)
            if row is None:
                errors.append(f"{cid}: chunk {cid2} not in chunk manifest")
                continue
            if row["source"] not in src_ids:
                errors.append(f"{cid}: chunk {cid2} source {row['source']} "
                              f"not in relevant_source_ids")
            # fail-closed traceability: snippet must be reproducible
            # contiguous evidence of the chunk text (documented Markdown
            # normalization only; paraphrase/paste is rejected).
            if not snippet_is_evidence(rc.get("chunk_text_snippet", ""),
                                       row["text"]):
                errors.append(f"{cid}: chunk_text_snippet is not contiguous "
                              f"evidence of {cid2}")
        # relevant_chunks chunk_id ↔ relevant_chunk_ids consistency
        rc_ids = [rc.get("chunk_id") for rc in case["relevant_chunks"]]
        if rc_ids and set(rc_ids) != set(chunk_ids):
            errors.append(f"{cid}: relevant_chunks chunk_ids mismatch "
                          f"relevant_chunk_ids")
        # no_answer rules
        if qtype == "no_answer":
            if not case["should_refuse"]:
                errors.append(f"{cid}: no_answer but should_refuse=False")
            if case["relevant_source_ids"] or case["relevant_chunk_ids"]:
                errors.append(f"{cid}: no_answer carries evidence")
        else:
            if case["should_refuse"] and not is_refusal_turn:
                errors.append(f"{cid}: {qtype} should not refuse")
            if (not case["acceptable_answer_points"] and not is_refusal_turn
                    and qtype != "no_answer"):
                errors.append(f"{cid}: answerable case missing answer points")

        # chain integrity
        meta = case["metadata"]
        if meta.get("chain_id"):
            ft = meta.get("follow_up_to")
            if meta["turn"] > 1 and ft not in skeleton_ids:
                errors.append(f"{cid}: follow_up_to {ft} not a known case id")
            if meta["turn"] == 1 and ft is not None:
                errors.append(f"{cid}: first turn has follow_up_to")
        out.append(case)

    if n_source_only > 15:
        errors.append(f"source-only {n_source_only} > 10% of 150")
    if len(out) != 150:
        errors.append(f"merged {len(out)} != 150")
    return out, errors


def main() -> int:
    cases, errors = merge()
    if errors:
        print(f"VALIDATION FAILED ({len(errors)} errors):")
        for e in errors[:80]:
            print("  ", e)
        return 1
    dest = ANNO / "v2-cases-draft.jsonl"
    dest.write_text(
        "\n".join(json.dumps(c, ensure_ascii=False) for c in cases) + "\n",
        encoding="utf-8")
    # coverage summary
    import collections
    by_type_lang = collections.Counter(
        (c["query_type"], c["language"]) for c in cases)
    print(f"wrote {dest} ({len(cases)} cases)")
    print("type x language:")
    for qt in ["single_fact", "metadata", "cross_document", "multi_turn",
               "mixed_intent", "no_answer"]:
        row = {lang: by_type_lang.get((qt, lang), 0)
               for lang in ["zh", "en", "mixed"]}
        print(f"  {qt:14s} {row}")
    print("difficulty:", dict(collections.Counter(
        c["metadata"]["difficulty"] for c in cases)))
    print("band:", dict(collections.Counter(
        c["metadata"]["band_target"] for c in cases)))
    print("source-only:", sum(1 for c in cases if c["relevance_level"] == "source"))
    print("chains:", len({c["metadata"]["chain_id"] for c in cases
                          if c["metadata"].get("chain_id")}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
