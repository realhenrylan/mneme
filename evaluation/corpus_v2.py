"""Corpus v2 offline ingestion tooling.

Deterministic, zero-LLM helpers for the v2 evaluation corpus:
HTML→Markdown conversion, document assembly, production-chunker chunking,
corpus manifest building, sensitive-content scanning, near-duplicate
detection and chunk-quality statistics.

Contract (see plans/CORPUS-EXPANSION-PLAN-2026-08-05.md §2, §6):
- chunk ids follow the runtime format ``{source_sha256_prefix}_chunk_{n}``
  and are produced by the *production* chunker (``src.rag.get_splitter``)
  so annotations stay valid when the evaluation runner rebuilds the index;
- all outputs are deterministic (sorted, stable) and free of secrets.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from html.parser import HTMLParser
from pathlib import Path

# ── HTML → Markdown ────────────────────────────────────────────────────


class _HtmlToMarkdown(HTMLParser):
    """Extract headings, paragraphs, lists, definitions and code blocks.

    Navigation (nav), scripts, styles and head content are dropped so the
    converted text stays clean for chunking and annotation.
    """

    _HEADING = {"h1": 1, "h2": 2, "h3": 3, "h4": 4, "h5": 5, "h6": 6}
    _SKIP = {"nav", "script", "style", "head", "noscript", "iframe", "footer"}
    _BLOCK = {"p", "li", "dt", "dd", "tr", "div", "br", "section", "article"}
    _PRE = {"pre", "code", "tt", "samp", "kbd", "var"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._out: list[str] = []
        self._skip_depth = 0
        self._pre_depth = 0
        self._pending_newline = False
        self._list_stack: list[str] = []

    def _newline(self) -> None:
        if self._out and not self._out[-1].endswith("\n"):
            self._out.append("\n")

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in self._SKIP:
            self._skip_depth += 1
            return
        if self._skip_depth:
            return
        if tag in self._PRE:
            if self._pre_depth == 0:
                self._newline()
                self._out.append("```\n")
            self._pre_depth += 1
            return
        if tag in self._HEADING:
            self._newline()
            self._out.append("#" * self._HEADING[tag] + " ")
            return
        if tag == "li":
            self._newline()
            marker = self._list_stack[-1] if self._list_stack else "- "
            self._out.append(marker)
            return
        if tag in ("ul", "ol"):
            self._list_stack.append("- " if tag == "ul" else "1. ")
            return
        if tag == "tr":
            self._newline()
            return
        if tag == "td":
            self._out.append(" | ")
            return
        if tag == "table":
            self._newline()
            return

    def handle_endtag(self, tag: str) -> None:
        if tag in self._SKIP:
            if self._skip_depth:
                self._skip_depth -= 1
            return
        if self._skip_depth:
            return
        if tag in self._PRE:
            self._pre_depth = max(0, self._pre_depth - 1)
            if self._pre_depth == 0:
                self._newline()
                self._out.append("```\n")
            return
        if tag in self._HEADING:
            self._newline()
            return
        if tag in ("ul", "ol"):
            if self._list_stack:
                self._list_stack.pop()
            self._newline()
            return
        if tag in self._BLOCK:
            self._newline()
            return

    def handle_data(self, data: str) -> None:
        if self._skip_depth or self._pre_depth:
            if self._pre_depth:
                self._out.append(data)
            return
        text = re.sub(r"\s+", " ", data)
        if text:
            self._out.append(text)

    def text(self) -> str:
        out = "".join(self._out)
        out = re.sub(r"[ \t]+\n", "\n", out)
        out = re.sub(r"\n{3,}", "\n\n", out)
        return out.strip() + ("\n" if out.strip() else "")


def html_to_markdown(html_text: str) -> str:
    """Convert an HTML document to clean Markdown (deterministic)."""
    if not html_text:
        return ""
    parser = _HtmlToMarkdown()
    parser.feed(html_text)
    parser.close()
    return parser.text()


# ── Snippet evidence (annotation traceability) ────────────────────────

_FENCED_RE = re.compile(r"`{3,}\n?([\s\S]*?)\n?`{3,}")
_INLINE_CODE_RE = re.compile(r"`([^`\n]+)`")
_BOLD_RE = re.compile(r"\*\*([^*\n]+)\*\*")
_ITALIC_RE = re.compile(r"\*([^*\n]+)\*")
_LINK_RE = re.compile(r"\[([^\]\n]+)\]\([^)\n]+\)")
_LINE_PREFIX_RE = re.compile(r"^#{1,6}\s+|^\d+[.)]\s+|^-\s+|\*\s+", re.MULTILINE)
_TABLE_SEP_RE = re.compile(r"\s*\|\s*")
_WS_RE = re.compile(r"\s+")


def normalize_snippet(text: str) -> str:
    """Strip Markdown markers from chunk text for evidence comparison.

    Only *format* normalization is applied — the text content is never
    rephrased, reordered or truncated.  The rules mirror the markers that
    ``html_to_markdown`` can emit (fenced code blocks, headings, lists,
    table separators) plus inline code/emphasis/link syntax:

    1. fenced code blocks (````` … `````) → block content;
    2. inline code ``x`` → x; bold ``**x**`` / italic ``*x*`` → x;
    3. links ``[t](u)`` → t;
    4. line-prefix markers (``#``, ``-``, ``1.``, ``*``) → removed;
       ``>>>`` REPL prompts are *content*, not blockquote markers;
    5. table separators (`` | ``) → single space;
    6. all whitespace runs → single space (so block-boundary newlines
       introduced by the converter collapse like rendered HTML does).

    Case is preserved: changing case counts as paraphrase, not format.
    """
    s = _FENCED_RE.sub(r"\1", text)
    s = _INLINE_CODE_RE.sub(r"\1", s)
    s = _BOLD_RE.sub(r"\1", s)
    s = _ITALIC_RE.sub(r"\1", s)
    s = _LINK_RE.sub(r"\1", s)
    s = _LINE_PREFIX_RE.sub("", s)
    s = s.replace("¶", "")  # Python 文档标题锚点字符（格式标记，非正文）
    s = _TABLE_SEP_RE.sub(" ", s)
    s = _WS_RE.sub(" ", s)
    return s.strip()


def snippet_is_evidence(snippet: str, chunk_text: str) -> bool:
    """Fail-closed: is ``snippet`` reproducible contiguous evidence of
    ``chunk_text``?

    True only when the normalized snippet is a contiguous substring of the
    normalized chunk text.  Paraphrase, ellipsis-joined fragments and
    cross-chunk pastes all fail, as does any empty input.
    """
    if not snippet or not chunk_text:
        return False
    return normalize_snippet(snippet) in normalize_snippet(chunk_text)


# ── Document assembly ──────────────────────────────────────────────────


def assemble_document(parts: list[str], headings: list[str] | None = None) -> str:
    """Join document parts into one corpus document.

    Args:
        parts: Content chunks (e.g. one per source page/chapter).
        headings: Optional per-part headings; must match ``parts`` length.

    Returns:
        Deterministically joined Markdown text.
    """
    if headings is not None and len(headings) != len(parts):
        raise ValueError(
            f"headings ({len(headings)}) must match parts ({len(parts)})"
        )
    blocks: list[str] = []
    for i, part in enumerate(parts):
        text = part.strip()
        if not text:
            continue
        if headings is not None:
            blocks.append(f"# {headings[i].strip()}\n\n{text}")
        else:
            blocks.append(text)
    return "\n\n".join(blocks) + "\n"


# ── Chunking via production pipeline ───────────────────────────────────


def _source_id_for_path(filepath: str) -> str:
    import src.rag as rag

    return rag.source_id_for_path(filepath)


def split_corpus_document(filepath: str, file_type: str) -> list[dict]:
    """Chunk a document with the production chunker.

    Returns list of ``{"chunk_id", "text", "source", "index"}`` where
    ``chunk_id`` follows ``{source_sha256_prefix}_chunk_{n}``.
    """
    import src.rag as rag

    text, detected = rag.load_document(filepath)
    if detected != file_type:
        raise ValueError(f"type mismatch: {filepath} detected={detected} want={file_type}")
    splitter = rag.get_splitter(detected)
    pieces = splitter.split_text(text)
    if not pieces:
        raise ValueError(f"no chunks produced for {filepath}")
    source_id = _source_id_for_path(filepath)
    source_name = os.path.basename(filepath)
    return [
        {
            "chunk_id": f"{source_id[:12]}_chunk_{i}",
            "text": piece,
            "source": source_name,
            "index": i,
        }
        for i, piece in enumerate(pieces)
    ]


def ingest_document(filepath: str) -> dict:
    """Parse + chunk one corpus document (production loaders/chunker)."""
    import src.rag as rag

    suffix = os.path.splitext(filepath)[1].lower()
    file_type = rag.detect_file_type(filepath)
    content_sha256 = hashlib.sha256(Path(filepath).read_bytes()).hexdigest()
    return {
        "path": os.path.realpath(filepath),
        "file_type": file_type,
        "source_id": _source_id_for_path(filepath),
        "source_name": os.path.basename(filepath),
        "size": os.path.getsize(filepath),
        "content_sha256": content_sha256,
        "chunks": split_corpus_document(filepath, file_type),
    }


# ── Sensitive-content scanning ─────────────────────────────────────────


_SENSITIVE_PATTERNS: list[tuple[str, str]] = [
    ("email", r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"),
    ("api_key", r"\b(sk-[A-Za-z0-9_-]{8,}|AKIA[0-9A-Z]{16}|ghp_[A-Za-z0-9]{20,}|xox[baprs]-[A-Za-z0-9-]{10,})\b"),
    ("phone", r"(?<!\d)(1[3-9]\d[\s-]?\d{4}[\s-]?\d{4})(?!\d)"),
    ("id_card", r"(?<!\d)\d{17}[\dXx](?!\d)"),
    ("private_key", r"-----BEGIN (RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    ("password_field", r"(password|passwd|pwd)\s*[=:]\s*['\"][^'\"]{4,}['\"]"),
]

# RFC 2606 保留域名（example.*）与文档惯用示例名邮箱不算敏感
_EXAMPLE_DOMAINS = ("example.com", "example.org", "example.net", "example.edu")
_EXAMPLE_LOCALPARTS = ("alice", "bob", "taylor", "charlie", "someone", "user")


def _is_example_email(email: str) -> bool:
    local, _, domain = email.partition("@")
    return domain.lower() in _EXAMPLE_DOMAINS or local.lower() in _EXAMPLE_LOCALPARTS


def scan_sensitive(text: str) -> list[str]:
    """Return matched sensitive-content categories (empty = clean).

    Emails on RFC 2606 reserved domains and common doc-placeholder names
    are treated as safe (documentation examples).
    """
    hits: list[str] = []
    for label, pattern in _SENSITIVE_PATTERNS:
        if label == "email":
            if any(not _is_example_email(m) for m in re.findall(pattern, text)):
                hits.append(label)
            continue
        if re.search(pattern, text):
            hits.append(label)
    return hits


# ── Near-duplicate detection ───────────────────────────────────────────


def _normalize(text: str) -> str:
    return re.sub(r"[\s\W_]+", "", text.lower())


def _ngrams(text: str, k: int = 5) -> set[str]:
    if len(text) < k:
        return {text} if text else set()
    return {text[i : i + k] for i in range(len(text) - k + 1)}


def near_duplicate_score(a: str, b: str, k: int = 5) -> float:
    """Character k-gram Jaccard similarity in [0, 1] (deterministic)."""
    na, nb = _normalize(a), _normalize(b)
    ga, gb = _ngrams(na, k), _ngrams(nb, k)
    if not ga and not gb:
        return 1.0
    if not ga or not gb:
        return 0.0
    union = ga | gb
    if not union:
        return 1.0
    return len(ga & gb) / len(union)


# ── Chunk quality statistics ───────────────────────────────────────────


def chunk_stats(chunks: list[str]) -> dict:
    """Summary statistics for chunk-quality acceptance.

    Reports: counts, total chars, length-band percentages, control
    characters and encoding errors (lone surrogates = invalid UTF-8).
    """
    n = len(chunks)
    total = sum(len(c) for c in chunks)
    lt100 = sum(1 for c in chunks if len(c) < 100)
    gt1200 = sum(1 for c in chunks if len(c) > 1200)
    ctrl = sum(1 for c in chunks if any(
        ch in c and ord(ch) < 32 and ch not in "\n\t\r" for ch in c
    ))
    enc = sum(1 for c in chunks if any(0xD800 <= ord(ch) <= 0xDFFF for ch in c))
    return {
        "n_chunks": n,
        "n_total_chars": total,
        "pct_lt_100": lt100 / n if n else 0.0,
        "pct_gt_1200": gt1200 / n if n else 0.0,
        "n_with_control_chars": ctrl,
        "n_encoding_errors": enc,
    }


# ── Corpus manifest ────────────────────────────────────────────────────


def _safe_relpath(path: str) -> str:
    """Return path relative to CWD, falling back to basename cross-drive."""
    try:
        return os.path.relpath(path)
    except ValueError:
        return os.path.basename(path)


def build_corpus_manifest(entries: list[dict], corpus_version: str) -> dict:
    """Build the versioned corpus manifest with content SHA-256 per document.

    Each ``entries`` item requires: id, path, source_url, license (others
    optional, e.g. license_url, author, language, doc_type, obtained_date,
    pub_date, notes, processed_file).  The manifest SHA-256 is computed
    over the canonical JSON of version + documents (self-referential key
    excluded) so the manifest is deterministic.
    """
    docs: list[dict] = []
    for e in entries:
        required = ("id", "path", "source_url", "license")
        missing = [k for k in required if not e.get(k)]
        if missing:
            raise ValueError(f"manifest entry missing {missing}: {e.get('id')}")
        path = Path(e["path"])
        if not path.is_file():
            raise ValueError(f"manifest path not found: {e['path']}")
        payload = {
            "id": e["id"],
            "path": _safe_relpath(str(path)),
            "source_url": e["source_url"],
            "license": e["license"],
        }
        for key in (
            "license_url", "author", "language", "doc_type", "version",
            "obtained_date", "pub_date", "notes", "processed_file",
        ):
            if e.get(key) is not None:
                payload[key] = e[key]
        payload["file_sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
        payload["size"] = path.stat().st_size
        docs.append(payload)
    docs_sorted = sorted(docs, key=lambda d: d["id"])
    canonical = json.dumps(
        {"corpus_version": corpus_version, "documents": docs_sorted},
        ensure_ascii=False, sort_keys=True,
    )
    return {
        "corpus_version": corpus_version,
        "documents": docs_sorted,
        "manifest_sha256": hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
    }


# ── CLI ────────────────────────────────────────────────────────────────


def main(argv: list[str] | None = None) -> int:
    """CLI: ``python -m evaluation.corpus_v2 <command> <path>``.

    Commands:
      convert <src.html> <dst.md>     HTML → Markdown
      ingest <file> [--json]          parse+chunk one document (JSON out)
      stats <file>                    chunk statistics for a document
    """
    import sys

    args = list(argv if argv is not None else sys.argv[1:])
    if not args:
        print(__doc__)
        return 0
    cmd = args[0]
    if cmd == "convert" and len(args) == 3:
        src, dst = args[1], args[2]
        html = Path(src).read_text(encoding="utf-8")
        md = html_to_markdown(html)
        Path(dst).write_text(md, encoding="utf-8")
        print(f"{src} -> {dst} ({len(md)} chars)")
        return 0
    if cmd == "ingest" and len(args) >= 2:
        doc = ingest_document(args[1])
        print(json.dumps(doc, ensure_ascii=False, indent=1 if "--json" in args else None))
        return 0
    if cmd == "stats" and len(args) == 2:
        doc = ingest_document(args[1])
        stats = chunk_stats([c["text"] for c in doc["chunks"]])
        print(json.dumps(stats, ensure_ascii=False, indent=1))
        return 0
    print(f"unknown command: {cmd}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
