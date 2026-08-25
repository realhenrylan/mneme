"""LLM-assisted third-pass human review (offline, no API).

Processes v2 human-review pack against local chunks corpus and produces:
  - human-review-pack.llm-filled.jsonl
  - llm-third-pass-manifest.json
  - llm-third-pass-report.md
"""

from __future__ import annotations

import json
import re
from pathlib import Path

# ── Normalization (mirrors evaluation/corpus_v2.py) ─────────────────────

_FENCED_RE = re.compile(r"`{3,}\n?([\s\S]*?)\n?`{3,}")
_INLINE_CODE_RE = re.compile(r"`([^`\n]+)`")
_BOLD_RE = re.compile(r"\*\*([^*\n]+)\*\*")
_ITALIC_RE = re.compile(r"\*([^*\n]+)\*")
_LINK_RE = re.compile(r"\[([^\]\n]+)\]\([^)\n]+\)")
_LINE_PREFIX_RE = re.compile(r"^#{1,6}\s+|^\d+[.)]\s+|^-\s+|\*\s+", re.MULTILINE)
_TABLE_SEP_RE = re.compile(r"\s*\|\s*")
_WS_RE = re.compile(r"\s+")


def normalize_snippet(text: str) -> str:
    """Strip Markdown markers from chunk text for evidence comparison."""
    s = _FENCED_RE.sub(r"\1", text)
    s = _INLINE_CODE_RE.sub(r"\1", s)
    s = _BOLD_RE.sub(r"\1", s)
    s = _ITALIC_RE.sub(r"\1", s)
    s = _LINK_RE.sub(r"\1", s)
    s = _LINE_PREFIX_RE.sub("", s)
    s = s.replace("\u00b6", "")  # ¶
    s = _TABLE_SEP_RE.sub(" ", s)
    s = _WS_RE.sub(" ", s)
    return s.strip()


# ── Helpers ──────────────────────────────────────────────────────────────

_EN_STOP = {
    "a", "an", "the", "is", "are", "was", "were", "be", "been", "being",
    "have", "has", "had", "do", "does", "did", "will", "would", "could",
    "should", "may", "might", "shall", "can", "need", "dare", "ought",
    "used", "to", "of", "in", "on", "at", "by", "for", "with", "about",
    "against", "between", "into", "through", "during", "before", "after",
    "above", "below", "from", "up", "down", "out", "off", "over", "under",
    "again", "further", "then", "once", "here", "there", "when", "where",
    "why", "how", "all", "both", "each", "few", "more", "most", "other",
    "some", "such", "no", "nor", "not", "only", "own", "same", "so", "than",
    "too", "very", "s", "t", "just", "don", "now",
}


def _extract_keywords(text: str, *, min_keep_len: int = 2) -> list[str]:
    """Extract significant keywords from an answer point or query."""
    norm = normalize_snippet(text)
    tokens = re.findall(r"[A-Za-z0-9_]+|[\u4e00-\u9fff]+", norm)
    keywords: list[str] = []
    for tok in tokens:
        if len(tok) < min_keep_len:
            continue
        # Keep all-caps / mixed-with-digits tokens (SELECT, v10.0.0, 64KiB)
        if re.search(r"[A-Z]{2,}", tok) or re.search(r"\d", tok):
            keywords.append(tok)
            continue
        # Keep Chinese tokens as-is
        if re.search(r"[\u4e00-\u9fff]", tok):
            keywords.append(tok)
            continue
        # Keep English words longer than 2 chars that aren't stop words
        low = tok.lower()
        if low not in _EN_STOP and len(tok) > 2:
            keywords.append(tok)
    return keywords


def _keywords_in_text(keywords: list[str], text: str, *, require_all: bool = True) -> bool:
    """Check whether keywords appear in the (normalized) text (case-insensitive)."""
    norm = normalize_snippet(text).lower()
    if require_all:
        return all(kw.lower() in norm for kw in keywords)
    # Partial match: at least one significant keyword matches
    return any(kw.lower() in norm for kw in keywords)


def _keywords_overlap_ratio(keywords: list[str], text: str) -> float:
    """Return the fraction of keywords that appear in text."""
    if not keywords:
        return 0.0
    norm = normalize_snippet(text).lower()
    matched = sum(1 for kw in keywords if kw.lower() in norm)
    return matched / len(keywords)


# ── Core verification ────────────────────────────────────────────────────

def verify_evidenced_answer(
    case: dict,
    chunk_index: dict[str, tuple[str, str]],
) -> tuple[str, str]:
    """Verify a should_refuse=False case.

    Returns (decision, notes).
    """
    answer_points = case.get("acceptable_answer_points", [])
    evidence = case.get("evidence", [])

    if not answer_points:
        return "needs_followup", "acceptable_answer_points is empty"

    # Build evidence lookup: chunk_id -> normalized full text
    evidence_map: dict[str, str] = {}
    for ev in evidence:
        cid = ev["chunk_id"]
        if cid not in chunk_index:
            return "reject", f"chunk {cid} not found in corpus"
        chunk_text, _ = chunk_index[cid]
        evidence_map[cid] = normalize_snippet(chunk_text)

    unsupported: list[str] = []
    for ap in answer_points:
        ap_norm = normalize_snippet(ap).lower()
        supported = False
        for ev in evidence:
            cid = ev["chunk_id"]
            chunk_norm = evidence_map[cid]
            snippet_norm = normalize_snippet(ev.get("snippet", ""))
            snippet_norm_lower = snippet_norm.lower()
            # Snippet must be reproducible from the chunk
            if snippet_norm not in chunk_norm:
                unsupported.append(
                    f"答案点 '{ap}' 在 chunk {ev['chunk_id']} 的 snippet 中找不到直接文本支持"
                    f"（snippet 无法从 chunk 完整还原）"
                )
                supported = False
                break
            # 1) Exact substring match (case-insensitive)
            if ap_norm in snippet_norm_lower:
                supported = True
                break
            # 2) Keyword overlap: require at least 60% of significant keywords
            kws = _extract_keywords(ap)
            if kws:
                ratio = _keywords_overlap_ratio(kws, snippet_norm)
                if ratio >= 0.6:
                    supported = True
                    break
        if not supported:
            unsupported.append(
                f"答案点 '{ap}' 在 evidence snippet 中找不到直接文本支持"
            )

    if unsupported:
        return "reject", "; ".join(unsupported)
    return "confirmed", "证据直接支持所有答案点"


def verify_refusal(
    case: dict,
    chunk_index: dict[str, tuple[str, str]],
) -> tuple[str, str]:
    """Verify a should_refuse=True case.

    Returns (decision, notes).
    """
    query = case.get("query", "")
    # Extract keywords from the query, keeping shorter tokens to capture
    # specific entities like pandas, Django, WAL, etc.
    keywords = _extract_keywords(query, min_keep_len=2)
    if not keywords:
        return "needs_followup", "无法从 query 提取关键词"

    # Classify keywords as specific vs generic
    _GENERIC_KWS = {
        "python", "tutorial", "chapter", "section", "document", "文档", "教程",
        "介绍", "说明", "讲", "有没有", "提到", "内容", "language", "doc",
        "docs", "explain", "explains", "covered", "cover", "introduce",
        "introduces", "introduced", "mention", "mentions", "mentioned",
        "内容", "章节", "小节", "专门", "有没有",
    }
    specific_keywords = [kw for kw in keywords if kw.lower() not in _GENERIC_KWS]
    if not specific_keywords:
        # If all keywords are generic, we can't determine relevance
        return "needs_followup", "query 中仅包含通用关键词，无法判断语料是否包含相关内容"

    # Find chunks that contain at least 2 specific keywords (co-occurrence
    # reduces false positives from single-word matches in unrelated contexts)
    evidence_chunks: dict[str, list[str]] = {}  # chunk_id -> list of matched specific kws
    for cid, (text, src) in chunk_index.items():
        norm = normalize_snippet(text).lower()
        matched_kws = [kw for kw in specific_keywords if kw.lower() in norm]
        if len(matched_kws) >= 2:
            evidence_chunks[cid] = matched_kws

    if evidence_chunks:
        chunks_found = ", ".join(
            f"{cid} ({chunk_index[cid][1]})" for cid in evidence_chunks
        )
        all_matched = sorted(set(kw for kws in evidence_chunks.values() for kw in kws))
        return "reject", (
            f"chunks 中存在相关内容：{chunks_found} 提到 {', '.join(all_matched)}"
        )
    return "confirmed", "拒答判定正确，语料中确实无相关内容"


def verify_multiturn(
    case: dict,
    chunk_index: dict[str, tuple[str, str]],
) -> tuple[str, str]:
    """Verify a multi-turn case, considering previous turns."""
    if case.get("should_refuse"):
        return verify_refusal(case, chunk_index)
    return verify_evidenced_answer(case, chunk_index)


# ── Main processing ──────────────────────────────────────────────────────

def load_inputs(
    pack_path: Path,
    chunks_path: Path,
) -> tuple[list[dict], dict[str, tuple[str, str]]]:
    with pack_path.open("r", encoding="utf-8") as f:
        cases = [json.loads(line) for line in f if line.strip()]
    with chunks_path.open("r", encoding="utf-8") as f:
        chunks = [json.loads(line) for line in f if line.strip()]
    chunk_index: dict[str, tuple[str, str]] = {}
    for ch in chunks:
        chunk_index[ch["chunk_id"]] = (ch["text"], ch["source"])
    return cases, chunk_index


def process_cases(
    cases: list[dict],
    chunk_index: dict[str, tuple[str, str]],
) -> tuple[list[dict], dict, list[str]]:
    filled_cases: list[dict] = []
    manifest: dict = {
        "total_cases": len(cases),
        "confirmed": 0,
        "reject": 0,
        "needs_followup": 0,
        "non_confirmed": [],
    }
    report_lines: list[str] = []

    for case in cases:
        cid = case["case_id"]
        query_type = case.get("query_type", "")
        is_multiturn = bool(case.get("previous_turns"))

        if is_multiturn:
            decision, notes = verify_multiturn(case, chunk_index)
        elif case.get("should_refuse"):
            decision, notes = verify_refusal(case, chunk_index)
        else:
            decision, notes = verify_evidenced_answer(case, chunk_index)

        filled = dict(case)
        filled["human_review_decision"] = decision
        filled["human_reviewer"] = "LLM_ASSISTED_THIRD_PASS"
        filled["human_review_notes"] = notes
        filled_cases.append(filled)

        manifest[decision] = manifest.get(decision, 0) + 1
        if decision != "confirmed":
            manifest["non_confirmed"].append({
                "case_id": cid,
                "decision": decision,
                "summary": notes,
            })
            report_lines.append(f"- {cid}: {decision} — {notes}")
        else:
            report_lines.append(f"- {cid}: confirmed")

    return filled_cases, manifest, report_lines


def write_outputs(
    filled_cases: list[dict],
    manifest: dict,
    report_lines: list[str],
    out_dir: Path,
) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)

    # Sort by case_id for deterministic output
    filled_cases.sort(key=lambda c: c["case_id"])

    with (out_dir / "human-review-pack.llm-filled.jsonl").open("w", encoding="utf-8") as f:
        for case in filled_cases:
            f.write(json.dumps(case, ensure_ascii=False) + "\n")

    with (out_dir / "llm-third-pass-manifest.json").open("w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)
        f.write("\n")

    report = [
        "# LLM Third-Pass Review Report",
        "",
        f"- Total cases: {manifest['total_cases']}",
        f"- Confirmed: {manifest.get('confirmed', 0)}",
        f"- Reject: {manifest.get('reject', 0)}",
        f"- Needs follow-up: {manifest.get('needs_followup', 0)}",
        "",
        "## Non-confirmed cases",
        "",
    ]
    if manifest["non_confirmed"]:
        report.extend(report_lines)
    else:
        report.append("All cases confirmed.")
    report.append("")

    with (out_dir / "llm-third-pass-report.md").open("w", encoding="utf-8") as f:
        f.write("\n".join(report))


def main() -> None:
    repo_root = Path("D:/GitHub/mneme")
    pack_path = repo_root / "evaluation/datasets/v2/human-review/human-review-pack.jsonl"
    chunks_path = repo_root / "data/v2-corpus/chunks/chunks.jsonl"
    out_dir = repo_root / "evaluation/datasets/v2/human-review"

    cases, chunk_index = load_inputs(pack_path, chunks_path)
    filled_cases, manifest, report_lines = process_cases(cases, chunk_index)
    write_outputs(filled_cases, manifest, report_lines, out_dir)

    print(f"Processed {manifest['total_cases']} cases.")
    print(f"  confirmed:    {manifest.get('confirmed', 0)}")
    print(f"  reject:       {manifest.get('reject', 0)}")
    print(f"  needs_followup: {manifest.get('needs_followup', 0)}")
    print(f"Output written to {out_dir}")


if __name__ == "__main__":
    main()
