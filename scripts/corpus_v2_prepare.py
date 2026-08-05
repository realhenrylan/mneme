"""Corpus v2 one-shot preparation: convert HTML sources, assemble
multi-chapter documents, run admission checks (parse, sensitive scan,
near-duplicate), and emit corpus manifest + attribution records.

Usage (from repo root):
    python scripts/corpus_v2_prepare.py prepare
    python scripts/corpus_v2_prepare.py validate
    python scripts/corpus_v2_prepare.py manifest
    python scripts/corpus_v2_prepare.py all          # prepare+validate+manifest

All outputs are deterministic. Zero LLM.  Reads only data/v2-corpus/.
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from evaluation.corpus_v2 import (  # noqa: E402
    assemble_document,
    build_corpus_manifest,
    html_to_markdown,
    ingest_document,
    near_duplicate_score,
    scan_sensitive,
    chunk_stats,
)

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "data" / "v2-corpus" / "documents"
RAW = DOCS
PROCESSED = DOCS / "processed"
PARTS = RAW / "_parts"
ATTR = ROOT / "data" / "v2-corpus" / "attribution"
CHUNKS_DIR = ROOT / "data" / "v2-corpus" / "chunks"

# 语言申报（人工确认；语言检测仅作参考）
LANG = {
    "python-tutorial-zh.md": "zh",
    "python-whatsnew313-zh.md": "zh",
    "python-datetime-zh.md": "zh",
    "vue-guide-zh.md": "zh",
    "sqlite-lang.md": "en",
    "postgresql-tutorial.md": "en",
    "rust-book-core.md": "en",
    "rfc3986.txt": "en",
    "art-of-war.txt": "en",
    "nodejs-fs.md": "en",
    "python-tutorial-en.md": "en",
    "python-glossary-zh.md": "mixed",
    "react-learn-zh.md": "mixed",
}

SOURCES = [
    # id, raw_file(s), processed_file, source_url, license, license_url, author, doc_type, notes
    ("python-tutorial-zh",
     ["python-tutorial-zh.html"] + [f"_parts/pytut-{p}.html" for p in
        ("introduction", "appetite", "controlflow", "datastructures", "modules",
         "inputoutput", "errors", "classes", "stdlib", "venv")],
     "python-tutorial-zh.md",
     "https://docs.python.org/zh-cn/3/tutorial/index.html",
     "PSF-2.0", "https://docs.python.org/3/license.html",
     "Python Software Foundation", "html", "Python 官方教程中文版（合并 11 页）"),
    ("python-whatsnew313-zh",
     ["python-whatsnew313-zh.html"],
     "python-whatsnew313-zh.md",
     "https://docs.python.org/zh-cn/3/whatsnew/3.13.html",
     "PSF-2.0", "https://docs.python.org/3/license.html",
     "Python Software Foundation", "html", "Python 3.13 新特性（版本说明，zh-cn）"),
    ("python-datetime-zh",
     ["python-datetime-zh.html"],
     "python-datetime-zh.md",
     "https://docs.python.org/zh-cn/3/library/datetime.html",
     "PSF-2.0", "https://docs.python.org/3/license.html",
     "Python Software Foundation", "html", "Python 标准库 datetime 模块参考（zh-cn）"),
    ("vue-guide-zh",
     [f"_parts/vue-{p}.md" for p in ("template-syntax", "reactivity-fundamentals",
                                     "component-basics", "lifecycle")],
     "vue-guide-zh.md",
     "https://github.com/vuejs/docs/tree/main/src/guide/essentials",
     "CC-BY-4.0", "https://github.com/vuejs/docs/blob/main/LICENSE",
     "Vue.js 社区（vuejs/docs 仓库）", "md", "Vue 3 指南（合并 4 章）"),
    ("sqlite-lang",
     ["sqlite-lang.html", "_parts/sqlite-lang_createtable.html",
      "_parts/sqlite-lang_select.html", "_parts/sqlite-lang_insert.html"],
     "sqlite-lang.md",
     "https://www.sqlite.org/lang.html",
     "Public-Domain", "https://www.sqlite.org/copyright.html",
     "SQLite 项目（D. Richard Hipp）", "html", "SQLite SQL 语言参考（合并 4 页）"),
    ("postgresql-tutorial",
     ["postgresql-tutorial.html", "_parts/pg-start.sgml", "_parts/pg-advanced.sgml"],
     "postgresql-tutorial.md",
     "https://www.postgresql.org/docs/current/tutorial.html",
     "PostgreSQL", "https://www.postgresql.org/about/licence/",
     "PostgreSQL Global Development Group", "html", "PostgreSQL 教程（引言 + start/advanced 章节；正文取自 REL_16_STABLE sgml 源，第 2 章未收录）"),
    ("rust-book-core",
     ["rust-book-core.md", "_parts/rust-ch04.md", "_parts/rust-ch04b.md",
      "_parts/rust-ch05.md", "_parts/rust-ch06.md"],
     "rust-book-core.md",
     "https://github.com/rust-lang/book",
     "MIT/Apache-2.0", "https://github.com/rust-lang/book/blob/main/LICENSE-MIT",
     "The Rust Programming Language（rust-lang/book）", "md", "The Rust Book 第 3–6 章"),
    ("rfc3986",
     ["rfc3986.txt"],
     "rfc3986.txt",
     "https://www.rfc-editor.org/rfc/rfc3986.txt",
     "IETF-Trust", "https://www.rfc-editor.org/rfc/rfc5378.txt",
     "IETF（RFC 3986，T. Berners-Lee 等）", "txt", "RFC 3986 URI 语法规范"),
    ("art-of-war",
     ["art-of-war.txt"],
     "art-of-war.txt",
     "https://www.gutenberg.org/ebooks/132",
     "Public-Domain", "https://www.gutenberg.org/ebooks/132",
     "Sun Tzu；Lionel Giles 英译", "txt", "孙子兵法英译（Gutenberg 公共领域）"),
    ("nodejs-fs",
     ["nodejs-fs.html"],
     "nodejs-fs.md",
     "https://nodejs.org/dist/latest-v22.x/docs/api/fs.html",
     "MIT", "https://github.com/nodejs/node/blob/main/LICENSE",
     "OpenJS Foundation", "html",
     "Node.js fs 模块 API 参考（随仓库 MIT 许可分发，涵盖文档；"
     "网站页脚历史 CC-BY-4.0 声明当前无法独立确认，不采用）"),
    ("python-tutorial-en",
     ["python-tutorial-zh.html"] + [f"_parts/pytut-en-{p}.html" for p in
        ("index", "introduction", "appetite", "controlflow", "datastructures",
         "modules", "inputoutput", "errors", "classes", "stdlib", "venv")],
     "python-tutorial-en.md",
     "https://docs.python.org/3/tutorial/",
     "PSF-2.0", "https://docs.python.org/3/license.html",
     "Python Software Foundation", "html", "Python 官方教程英文版（合并 11 页）"),
    ("python-glossary-zh",
     ["python-glossary-zh.html"],
     "python-glossary-zh.md",
     "https://docs.python.org/zh-cn/3/glossary.html",
     "PSF-2.0", "https://docs.python.org/3/license.html",
     "Python Software Foundation", "html", "Python 术语表（zh-cn，中英对照）"),
    ("react-learn-zh",
     [f"_parts/react-{p}.md" for p in ("describing-the-ui", "adding-interactivity",
                                      "managing-state")],
     "react-learn-zh.md",
     "https://github.com/reactjs/zh-hans.react.dev",
     "CC-BY-4.0", "https://github.com/reactjs/zh-hans.react.dev/blob/main/LICENSE",
     "React 中文文档翻译组（reactjs/zh-hans.react.dev）", "md", "React 中文教程（合并 3 章）"),
]

# Python 教程子页标题（组装 heading，与子页顺序一致）
TUTORIAL_HEADINGS = ["Python 教程（引言）", "1. 课前甜点", "2. 使用 Python 解释器",
                     "3. 流程控制", "4. 数据结构", "5. 模块", "6. 输入输出",
                     "7. 错误和异常", "8. 类", "9. 标准库概览", "10. 虚拟环境和包"]
RUST_HEADINGS = ["3. 通用编程概念", "4.1 什么是所有权", "4.2 引用与借用",
                 "5. 使用结构体", "6. 枚举与模式匹配"]
VUE_HEADINGS = ["模板语法", "响应式基础", "组件基础", "生命周期"]
REACT_HEADINGS = ["描述界面", "添加交互", "管理状态"]
SQLITE_HEADINGS = ["SQLite SQL 语言概述", "CREATE TABLE", "SELECT", "INSERT"]
PG_HEADINGS = ["PostgreSQL 教程（引言）", "1. Getting Started", "3. Advanced Features"]


def _convert_html(raw: Path, dst: Path) -> None:
    text = html_to_markdown(raw.read_text(encoding="utf-8"))
    dst.write_text(text, encoding="utf-8")


def prepare() -> None:
    """Convert HTML sources and assemble multi-chapter documents."""
    PROCESSED.mkdir(parents=True, exist_ok=True)
    # 1) convert every raw HTML to md (parts + single pages)
    for html in RAW.glob("*.html"):
        dst = PROCESSED / (html.stem + ".md")
        _convert_html(html, dst)
        print(f"converted {html.name} -> {dst.name}")
    for html in PARTS.glob("*.html"):
        dst = PROCESSED / ("_part-" + html.stem + ".md")
        _convert_html(html, dst)
    for sgml in PARTS.glob("*.sgml"):
        dst = PROCESSED / ("_part-" + sgml.stem + ".md")
        dst.write_text(html_to_markdown(sgml.read_text(encoding="utf-8")), encoding="utf-8")
        print(f"converted {sgml.name} -> {dst.name}")
    # 1b) plain-text sources are used as-is
    for name in ("rfc3986.txt", "art-of-war.txt"):
        src, dst = RAW / name, PROCESSED / name
        if src.exists() and not dst.exists():
            dst.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
            print(f"copied {name}")
    # 2) assemble multi-part documents
    def part_md(name: str) -> str:
        return (PROCESSED / f"_part-{name}.md").read_text(encoding="utf-8")

    def raw_md(name: str) -> str:
        p = RAW / name
        if not p.exists():
            p = PARTS / name
        return p.read_text(encoding="utf-8")

    # Python tutorial: 首页 md（PROCESSED 已转换）+ 10 个子页 md
    index_md = (PROCESSED / "python-tutorial-zh.md").read_text(encoding="utf-8")
    parts = [index_md] + [part_md(f"pytut-{p}") for p in
                          ("introduction", "appetite", "controlflow",
                           "datastructures", "modules", "inputoutput",
                           "errors", "classes", "stdlib", "venv")]
    (PROCESSED / "python-tutorial-zh.md").write_text(
        assemble_document(parts, TUTORIAL_HEADINGS), encoding="utf-8")
    # English tutorial: 下载自 docs.python.org/3/tutorial（英文子页）
    en_parts = [part_md(f"pytut-en-{p}") for p in
                ("index", "introduction", "appetite", "controlflow",
                 "datastructures", "modules", "inputoutput", "errors",
                 "classes", "stdlib", "venv")]
    (PROCESSED / "python-tutorial-en.md").write_text(
        assemble_document(en_parts, TUTORIAL_HEADINGS), encoding="utf-8")
    # Rust book core: ch03（6 个子文件）+ ch04/04b/05/06
    rust_ch3 = "\n\n".join(raw_md(f"rust-ch03-0{i}.md") for i in range(6))
    rust_parts = [rust_ch3, raw_md("rust-ch04.md"),
                  raw_md("rust-ch04b.md"), raw_md("rust-ch05.md"),
                  raw_md("rust-ch06.md")]
    (PROCESSED / "rust-book-core.md").write_text(
        assemble_document(rust_parts, RUST_HEADINGS), encoding="utf-8")
    # Vue guide
    vue_parts = [raw_md(f"vue-{p}.md") for p in
                 ("template-syntax", "reactivity-fundamentals",
                  "component-basics", "lifecycle")]
    (PROCESSED / "vue-guide-zh.md").write_text(
        assemble_document(vue_parts, VUE_HEADINGS), encoding="utf-8")
    # React learn
    react_parts = [raw_md(f"react-{p}.md") for p in
                   ("describing-the-ui", "adding-interactivity", "managing-state")]
    (PROCESSED / "react-learn-zh.md").write_text(
        assemble_document(react_parts, REACT_HEADINGS), encoding="utf-8")
    # SQLite syntax: 引言（RAW 根 html）+ CREATE TABLE + SELECT + INSERT
    sqlite_parts = [(PROCESSED / "sqlite-lang.md").read_text(encoding="utf-8"),
                    part_md("sqlite-lang_createtable"),
                    part_md("sqlite-lang_select"), part_md("sqlite-lang_insert")]
    (PROCESSED / "sqlite-lang.md").write_text(
        assemble_document(sqlite_parts, SQLITE_HEADINGS), encoding="utf-8")
    # PostgreSQL tutorial: 引言（RAW 根 html）+ start.sgml + advanced.sgml
    # （官方 HTML 正文为 JS 渲染，改用 postgres/postgres REL_16_STABLE 的
    #   doc/src/sgml 源；教程第 2 章 SQL 语言未收录——SQL 主题由 sqlite-lang 覆盖）
    pg_parts = [(PROCESSED / "postgresql-tutorial.md").read_text(encoding="utf-8"),
                part_md("pg-start"), part_md("pg-advanced")]
    (PROCESSED / "postgresql-tutorial.md").write_text(
        assemble_document(pg_parts, PG_HEADINGS), encoding="utf-8")
    # 3) sizes
    for f in sorted(PROCESSED.iterdir()):
        if f.suffix in (".md", ".txt"):
            print(f"  {f.name}: {f.stat().st_size} bytes")


def validate() -> None:
    """Admission checks: parse, sensitive scan, near-dup, chunk stats."""
    print("== parse / chunk / sensitive / stats per document ==")
    processed = [s[2] for s in SOURCES]
    stats_rows: list[dict] = []
    for name in processed:
        p = PROCESSED / name
        if not p.exists():
            print(f"  MISSING {name}")
            continue
        try:
            doc = ingest_document(str(p))
        except Exception as exc:  # noqa: BLE001
            print(f"  FAIL {name}: {exc}")
            continue
        hits = scan_sensitive(p.read_text(encoding="utf-8"))
        st = chunk_stats([c["text"] for c in doc["chunks"]])
        stats_rows.append({
            "doc": name, "chunks": st["n_chunks"], "chars": st["n_total_chars"],
            "sensitive": hits, "type": doc["file_type"],
        })
        flag = "SENSITIVE!" if hits else "ok"
        print(f"  {name}: chunks={st['n_chunks']} chars={st['n_total_chars']} {flag}")
    # near-dup across v2 docs (pairwise, k=5 normalized)
    print("== near-duplicate pairs (Jaccard >= 0.6) ==")
    texts = {}
    for name in processed:
        p = PROCESSED / name
        if p.exists():
            texts[name] = p.read_text(encoding="utf-8")
    names = sorted(texts)
    found = 0
    for i in range(len(names)):
        for j in range(i + 1, len(names)):
            s = near_duplicate_score(texts[names[i]], texts[names[j]])
            if s >= 0.6:
                print(f"  {names[i]} vs {names[j]}: {s:.3f}")
                found += 1
    if found == 0:
        print("  (no near-duplicate pairs >= 0.6)")
    print("== summary ==")
    total_chunks = sum(r["chunks"] for r in stats_rows)
    print(f"  documents={len(stats_rows)} chunks={total_chunks}")


def manifest() -> None:
    """Write corpus-manifest.jsonl (per-doc) + corpus-manifest.json (versioned)."""
    entries = []
    for doc_id, raw_names, processed, url, lic, lic_url, author, dtype, notes in SOURCES:
        p = PROCESSED / processed
        if not p.exists():
            raise SystemExit(f"missing processed doc: {processed}")
        entries.append({
            "id": doc_id,
            "path": str(p),
            "source_url": url,
            "license": lic,
            "license_url": lic_url,
            "author": author,
            "language": LANG[processed],
            "doc_type": dtype,
            "obtained_date": "2026-08-05",
            "pub_date": None,
            "notes": notes,
            "raw_files": [os.path.basename(r) for r in raw_names],
        })
    # per-doc JSONL (each line one document record, sha256/size appended)
    lines = []
    for e in entries:
        rec = dict(e)
        fname = Path(e["path"]).name
        rec["file_sha256"] = hashlib.sha256((PROCESSED / fname).read_bytes()).hexdigest()
        rec["size"] = (PROCESSED / fname).stat().st_size
        rec["path"] = "data/v2-corpus/documents/processed/" + fname
        lines.append(json.dumps(rec, ensure_ascii=False, sort_keys=True))
    (ROOT / "evaluation" / "datasets" / "v2").mkdir(parents=True, exist_ok=True)
    out_jsonl = ROOT / "evaluation" / "datasets" / "v2" / "corpus-manifest.jsonl"
    out_json = ROOT / "evaluation" / "datasets" / "v2" / "corpus-manifest.json"
    out_jsonl.write_text("\n".join(lines) + "\n", encoding="utf-8")
    m = build_corpus_manifest(entries, corpus_version="v2.0.0")
    out_json.write_text(json.dumps(m, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"wrote {out_jsonl} ({len(lines)} docs) and {out_json}")
    print(f"manifest_sha256={m['manifest_sha256']}")


def chunks() -> None:
    """Ingest processed documents -> chunks.jsonl + chunk-manifest.json."""
    import src.rag  # noqa: F401  (production chunker)

    rows: list[dict] = []
    per_source: dict[str, int] = {}
    for doc_id, _raw, processed, _url, _lic, _lurl, _author, _dtype, _notes in SOURCES:
        doc = ingest_document(str(PROCESSED / processed))
        per_source[processed] = len(doc["chunks"])
        rows.extend(doc["chunks"])
    rows_sorted = sorted(rows, key=lambda c: (c["source"], c["index"]))
    canonical = "\n".join(
        json.dumps(r, ensure_ascii=False, sort_keys=True) for r in rows_sorted
    )
    chunks_sha256 = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    out = CHUNKS_DIR / "chunks.jsonl"
    out.write_text(canonical + "\n", encoding="utf-8")
    manifest = {
        "corpus_version": "v2.0.0",
        "n_documents": len(per_source),
        "n_chunks": len(rows_sorted),
        "chunker": "src.rag.get_splitter (RecursiveCharacterTextSplitter, "
                   "text size=2000 overlap=200 separators=\\n\\n,\\n,。！？；., )",
        "chunks_sha256": chunks_sha256,
        "per_source": per_source,
        "chunk_id_format": "{source_sha256_prefix12}_chunk_{n}",
    }
    (CHUNKS_DIR / "chunk-manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"wrote {out} ({len(rows_sorted)} chunks, sha256={chunks_sha256[:16]}...)")
    for src, n in sorted(per_source.items()):
        print(f"  {n:4d}  {src}")


LICENSE_FILES = {
    # 按文档 id 映射专属许可证证据文件：同一来源的同一许可证可共用
    # （如 docs.python.org 各页均为 PSF-2.0），禁止跨来源复用。
    "python-tutorial-zh": "PSF-2.0.txt",
    "python-whatsnew313-zh": "PSF-2.0.txt",
    "python-datetime-zh": "PSF-2.0.txt",
    "python-tutorial-en": "PSF-2.0.txt",
    "python-glossary-zh": "PSF-2.0.txt",
    "vue-guide-zh": "CC-BY-4.0-vuejs.txt",
    "react-learn-zh": "CC-BY-4.0-react.txt",
    "nodejs-fs": "MIT-nodejs.txt",
    "postgresql-tutorial": "PostgreSQL-Copyright.txt",
    "rust-book-core": "rust-book-MIT.txt (+ rust-book-APACHE.txt)",
    "rfc3986": "IETF-Trust-rfc5378.txt",
    "sqlite-lang": "sqlite-public-domain.txt",
    "art-of-war": "gutenberg-ebook-132-license.txt",
}


def attribution() -> None:
    """Write per-document attribution records into data/v2-corpus/attribution/."""
    ATTR.mkdir(parents=True, exist_ok=True)
    for doc_id, raw_names, processed, url, lic, lic_url, author, dtype, notes in SOURCES:
        lic_file = LICENSE_FILES.get(doc_id, "")
        lines = [
            f"# {doc_id}",
            "",
            f"- 文档：`{processed}`（源文件：{', '.join(os.path.basename(r) for r in raw_names)}）",
            f"- 来源 URL：{url}",
            f"- 作者/机构：{author}",
            f"- 许可证：{lic}（{lic_url}）",
            f"- 许可证原文：`licenses/{lic_file}`" if lic_file else "- 许可证原文：见官方声明页",
            f"- 语言：{LANG[processed]}",
            f"- 类型：{dtype}",
            "- 获取日期：2026-08-05",
            f"- 处理说明：{notes}",
            "- 再分发合规：本文件按上述许可证允许复制与衍生标注。",
        ]
        (ATTR / f"{doc_id}.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"wrote {len(SOURCES)} attribution files to {ATTR}")


def main() -> int:
    cmd = sys.argv[1] if len(sys.argv) > 1 else "all"
    if cmd in ("prepare", "all"):
        prepare()
    if cmd in ("validate", "all"):
        validate()
    if cmd in ("chunks", "all"):
        chunks()
    if cmd in ("manifest", "all"):
        manifest()
    if cmd in ("attribution", "all"):
        attribution()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
