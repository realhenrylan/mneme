"""Tests for evaluation.corpus_v2 — offline corpus ingestion tooling.

Covers: HTML→Markdown conversion, document assembly, production-chunker
chunking, manifest building, sensitive-content scanning, near-duplicate
detection, and chunk-quality stats.  Deterministic, zero LLM.
"""

from __future__ import annotations

import json
import re

import pytest

from evaluation.corpus_v2 import (
    assemble_document,
    build_corpus_manifest,
    chunk_stats,
    html_to_markdown,
    ingest_document,
    near_duplicate_score,
    normalize_snippet,
    scan_sensitive,
    snippet_is_evidence,
    split_corpus_document,
)

HTML_SAMPLE = """<!DOCTYPE html>
<html><head><title>T</title><style>body{}</style></head>
<body>
<nav><a href="/x">跳过</a></nav>
<h1>第一章 概述</h1>
<p>这是第一段。<b>加粗</b>与<a href="/y">链接</a>。</p>
<pre><code>print("hello")</code></pre>
<h2>1.1 小节</h2>
<ul><li>列表项一</li><li>列表项二</li></ul>
<script>var x=1;</script>
</body></html>
"""


class TestHtmlToMarkdown:
    def test_heading_levels_and_text(self):
        md = html_to_markdown(HTML_SAMPLE)
        assert "# 第一章 概述" in md
        assert "## 1.1 小节" in md
        assert "这是第一段" in md
        assert "列表项一" in md

    def test_code_block_preserved(self):
        md = html_to_markdown(HTML_SAMPLE)
        assert "print(\"hello\")" in md
        # code content must not be wrapped as markdown emphasis or links
        assert re.search(r"```", md)

    def test_nav_script_style_removed(self):
        md = html_to_markdown(HTML_SAMPLE)
        assert "跳过" not in md
        assert "var x=1" not in md
        assert "body{}" not in md

    def test_links_inline_text_only(self):
        md = html_to_markdown(HTML_SAMPLE)
        # link text survives, raw <a href> markup does not
        assert "<a" not in md
        assert "加粗" in md

    def test_deterministic(self):
        assert html_to_markdown(HTML_SAMPLE) == html_to_markdown(HTML_SAMPLE)

    def test_empty_input(self):
        assert html_to_markdown("") == ""
        assert html_to_markdown("<html></html>") == ""


class TestAssembleDocument:
    def test_parts_joined_deterministically(self):
        out = assemble_document(["AAA 内容一", "BBB 内容二"], headings=["甲", "乙"])
        assert "甲" in out and "乙" in out
        assert out.index("AAA") < out.index("BBB")
        assert assemble_document(["AAA 内容一", "BBB 内容二"], headings=["甲", "乙"]) == out

    def test_single_part_no_heading(self):
        assert assemble_document(["内容"]).strip() == "内容"

    def test_heading_parts_match_length(self):
        with pytest.raises(ValueError):
            assemble_document(["a", "b"], headings=["only-one"])


class TestIngestAndSplit:
    def test_split_produces_reconstructable_text(self, tmp_path):
        p = tmp_path / "doc.md"
        text = "# 标题\n\n" + ("这是正文内容。" * 600)  # 3600 字符 > text chunk_size 2000
        p.write_text(text, encoding="utf-8")
        chunks = split_corpus_document(str(p), "text")
        assert len(chunks) >= 2
        joined = "".join(c["text"] for c in chunks)
        # overlap makes joined text a superset; verify content conservation loosely
        assert "这是正文内容。" * 20 in joined

    def test_ingest_document_metadata(self, tmp_path):
        p = tmp_path / "doc.md"
        p.write_text("# 标题\n\n正文内容。" * 30, encoding="utf-8")
        out = ingest_document(str(p))
        assert out["path"] == str(p)
        assert out["file_type"] == "text"
        assert out["source_id"]  # sha256 hex
        assert out["content_sha256"]
        assert out["chunks"]
        assert all(re.match(r"^[0-9a-f]{12}_chunk_\d+$", c["chunk_id"]) for c in out["chunks"])
        assert all(c["source"] == p.name for c in out["chunks"])

    def test_unsupported_type_rejected(self, tmp_path):
        p = tmp_path / "doc.xyz"
        p.write_text("x")
        with pytest.raises(ValueError):
            ingest_document(str(p))


class TestSensitiveScan:
    def test_email_hit(self):
        hits = scan_sensitive("联系 contact@corp-internal.com 获取")
        assert any("email" in h for h in hits)

    def test_example_email_not_hit(self):
        assert scan_sensitive("示例 user@example.com 与 alice@example.org") == []

    def test_api_key_hit(self):
        hits = scan_sensitive("key=sk-proj-abcdef1234567890")
        assert any("key" in h.lower() for h in hits)

    def test_phone_hit(self):
        hits = scan_sensitive("电话 138-1234-5678")
        assert any("phone" in h for h in hits)

    def test_clean_text_no_hits(self):
        assert scan_sensitive("这是普通的技术文档内容。Python 3.13 发布。") == []


class TestNearDuplicate:
    def test_identical_texts(self):
        a = "同一段落内容。" * 40
        assert near_duplicate_score(a, a) == pytest.approx(1.0)

    def test_different_texts_low(self):
        a = "甲文档的主题。" * 40
        b = "乙文档的主题。" * 40
        assert near_duplicate_score(a, b) < 0.85

    def test_short_texts(self):
        assert near_duplicate_score("短", "短") == pytest.approx(1.0)
        assert near_duplicate_score("abc", "def") == pytest.approx(0.0)


class TestChunkStats:
    def test_length_distribution(self, tmp_path):
        p = tmp_path / "doc.md"
        p.write_text("段落。" * 2000, encoding="utf-8")
        doc = ingest_document(str(p))
        stats = chunk_stats([c["text"] for c in doc["chunks"]])
        assert stats["n_chunks"] == len(doc["chunks"])
        assert stats["n_total_chars"] > 0
        assert 0 <= stats["pct_lt_100"] <= 1
        assert 0 <= stats["pct_gt_1200"] <= 1

    def test_control_chars_detected(self):
        stats = chunk_stats(["正常文本", "异常\x00\x1f文本"])
        assert stats["n_with_control_chars"] == 1

    def test_encoding_invalid_detected(self):
        stats = chunk_stats(["正常", "\ud800孤立代理"])  # 孤立代理 = 非法 UTF-8 序列
        assert stats["n_encoding_errors"] == 1


class TestManifest:
    def test_manifest_deterministic(self, tmp_path):
        a, b = tmp_path / "a.md", tmp_path / "b.md"
        a.write_text("内容甲", encoding="utf-8")
        b.write_text("content b", encoding="utf-8")
        docs = [
            {"id": "d1", "path": str(a), "license": "MIT", "source_url": "u1"},
            {"id": "d2", "path": str(b), "license": "CC0", "source_url": "u2"},
        ]
        m1 = build_corpus_manifest(docs, corpus_version="v2.0.0")
        m2 = build_corpus_manifest(docs, corpus_version="v2.0.0")
        assert json.dumps(m1, ensure_ascii=False, sort_keys=True) == json.dumps(
            m2, ensure_ascii=False, sort_keys=True
        )
        assert m1["corpus_version"] == "v2.0.0"
        assert m1["manifest_sha256"]
        assert all(d["file_sha256"] for d in m1["documents"])

    def test_missing_path_rejected(self, tmp_path):
        with pytest.raises(ValueError):
            build_corpus_manifest(
                [{"id": "d1", "path": str(tmp_path / "nope.md"), "license": "MIT",
                  "source_url": "u"}],
                corpus_version="v2.0.0",
            )


class TestSnippetEvidence:
    """chunk_text_snippet 必须是指定 chunk 的可复现连续证据。

    归一化仅剥离 Markdown 标记（html_to_markdown 产物格式），不改变
    文本内容；意译、省略号拼接、跨 chunk 拼接在 fail-closed 下拒绝。
    """

    def test_inline_code_fenced_collapses(self):
        # html_to_markdown 把 inline <code> 转成独立 fenced block，
        # 且 text() 清理会吞掉代码前的空格；归一化把块边界换行折叠为
        # 单个空格（markdown 块级语义），两侧文本顺序与内容保持不变。
        chunk = "交互模式下，上次输出的表达式会赋给变量\n```\n_\n```\n。把 Python 当作计算器时"
        snippet = "交互模式下，上次输出的表达式会赋给变量 _ 。把 Python 当作计算器时"
        assert snippet_is_evidence(snippet, chunk)

    def test_raw_chunk_paste_is_evidence(self):
        # 修复协议：从 chunk 原样复制的连续片段（允许含 markdown 标记）
        # 必然通过验证——这是“从正确 chunk 复制实际证据片段”的依据。
        chunk = "交互模式下，上次输出的表达式会赋给变量\n```\n_\n```\n。把 Python 当作计算器时"
        paste = "上次输出的表达式会赋给变量\n```\n_\n```\n。把 Python 当作计算器时"
        assert snippet_is_evidence(paste, chunk)

    def test_multiline_fenced_block_whitespace_collapses(self):
        chunk = "例如：\n```\n>>> tax = 12.5 / 100\n>>> price = 100.50\n```\n\n最好只读"
        snippet = "例如：\n>>> tax = 12.5 / 100\n>>> price = 100.50\n最好只读"
        assert snippet_is_evidence(snippet, chunk)

    def test_heading_markers_stripped(self):
        chunk = "### 3.1.2. 文本¶\n 除了数字 Python 还可以操作文本"
        snippet = "3.1.2. 文本 除了数字 Python 还可以操作文本"
        assert snippet_is_evidence(snippet, chunk)

    def test_list_and_table_markers_stripped(self):
        chunk = "- 列表项一\n- 列表项二\n| 列A | 列B |\n正文"
        snippet = "列表项二 列A 列B 正文"
        assert snippet_is_evidence(snippet, chunk)

    def test_bold_italic_link_stripped(self):
        chunk = "使用 **加粗**、*斜体* 与 [链接文本](https://example.com) 示例"
        snippet = "使用 加粗、斜体 与 链接文本 示例"
        assert snippet_is_evidence(snippet, chunk)

    def test_whitespace_insensitive(self):
        chunk = "多个   空白\n\t字符折叠"
        snippet = "多个 空白 字符折叠"
        assert snippet_is_evidence(snippet, chunk)

    def test_repl_prompts_are_content(self):
        # “>>> ” 是 REPL 提示符（正文内容），不是 blockquote 标记；
        # 归一化不得删除，否则与行内出现的提示符不对称。
        chunk = "```\n>>> rgb = [\"Red\", \"Green\", \"Blue\"]\n>>> rgba = rgb\n```"
        snippet = ">>> rgb = [\"Red\", \"Green\", \"Blue\"] >>> rgba = rgb"
        assert snippet_is_evidence(snippet, chunk)

    def test_case_sensitive(self):
        # 证据比对区分大小写：大小写改写视为意译。
        chunk = "The Art of War is an ancient treatise"
        assert not snippet_is_evidence("the art of war is an ancient treatise", chunk)

    def test_contiguity_required(self):
        # 两段证据被 chunk 内其他文本隔开 → 拼接，拒绝。
        chunk = "规则一：每个值有一个所有者。\n规则二：同一时刻只能有一个所有者。"
        assert not snippet_is_evidence("规则一：每个值有一个所有者。 规则二：只能有一个所有者。", chunk)

    def test_ellipsis_concat_rejected(self):
        # “... ” 拼接不同位置文本 → 拒绝（无连续子串）。
        chunk = "### Ownership Rules\nFirst, let's look at the rules. Keep them in mind.\n"
        assert not snippet_is_evidence("### Ownership Rules ... Keep them in mind", chunk)

    def test_empty_snippet_or_chunk_rejected(self):
        assert not snippet_is_evidence("", "正文")
        assert not snippet_is_evidence("证据", "")
        assert not snippet_is_evidence("", "")

    def test_wrong_chunk_rejected(self):
        chunk = "19. Hence, when able to attack, we must seem unable"
        snippet = "Military tactics are like unto water"
        assert not snippet_is_evidence(snippet, chunk)
