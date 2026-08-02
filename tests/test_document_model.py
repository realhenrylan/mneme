"""测试 2.1 标准文档模型：Document/Section/Chunk 数据类 + loaders + chunking。"""

import os
import pytest
from unittest.mock import patch, MagicMock

from src.domain import (
    Chunk, Document, ParseQuality, Section, SectionType,
    RetrievalCandidate, RefusalFeatures, CitationValidation, compute_context_k,
)
from src.loaders.base import BaseLoader, LoaderRegistry
from src.loaders.pdf_loader import PdfLoader, _detect_heading_level
from src.loaders.docx_loader import DocxLoader, _heading_level_from_style
from src.loaders.text_loader import TextLoader
from src.chunking import chunk_document, chunks_to_index_data, CHUNKING_CONFIG_V3


# ═══════════════════════════════════════════════════════════════
# Section / Chunk / Document 数据类测试
# ═══════════════════════════════════════════════════════════════

class TestSection:
    def test_create_heading_section(self):
        s = Section(
            section_type=SectionType.HEADING,
            text="1. Introduction",
            heading_level=1,
            heading_path="Introduction",
            page=1,
        )
        assert s.section_type == SectionType.HEADING
        assert s.heading_level == 1
        assert s.page == 1

    def test_create_paragraph_section(self):
        s = Section(
            section_type=SectionType.PARAGRAPH,
            text="Some content here.",
        )
        assert s.section_type == SectionType.PARAGRAPH
        assert s.heading_level is None

    def test_create_table_section(self):
        s = Section(
            section_type=SectionType.TABLE,
            text="A | B\n1 | 2",
            metadata={"rows": 2, "cols": 2},
        )
        assert s.section_type == SectionType.TABLE
        assert s.metadata["rows"] == 2

    def test_frozen(self):
        s = Section(section_type=SectionType.PARAGRAPH, text="test")
        with pytest.raises(AttributeError):
            s.text = "changed"


class TestChunk:
    def test_create_chunk(self):
        c = Chunk(
            text="chunk text",
            chunk_id="src_chunk_0",
            chunk_index=0,
            page=1,
            section_heading="1. Introduction",
            section_type=SectionType.PARAGRAPH,
        )
        assert c.chunk_id == "src_chunk_0"
        assert c.section_heading == "1. Introduction"

    def test_parent_chunk_id_default_none(self):
        c = Chunk(text="t", chunk_id="c0", chunk_index=0)
        assert c.parent_chunk_id is None

    def test_frozen(self):
        c = Chunk(text="t", chunk_id="c0", chunk_index=0)
        with pytest.raises(AttributeError):
            c.text = "changed"


class TestDocument:
    def _make_doc(self, **kwargs) -> Document:
        defaults = dict(
            source_id="abc123",
            source_path="/test/doc.pdf",
            source_name="doc.pdf",
            file_type="pdf",
        )
        defaults.update(kwargs)
        return Document(**defaults)

    def test_full_text(self):
        doc = self._make_doc(sections=[
            Section(section_type=SectionType.PARAGRAPH, text="Hello"),
            Section(section_type=SectionType.PARAGRAPH, text="World"),
        ])
        assert doc.full_text == "Hello\nWorld"

    def test_full_text_empty(self):
        doc = self._make_doc()
        assert doc.full_text == ""

    def test_empty_text_rate_no_pages(self):
        doc = self._make_doc()
        assert doc.empty_text_rate == 0.0

    def test_empty_text_rate_with_pages(self):
        doc = self._make_doc(total_pages=10, empty_text_pages=3)
        assert doc.empty_text_rate == pytest.approx(0.3)

    def test_is_low_quality_explicit(self):
        doc = self._make_doc(parse_quality=ParseQuality.LOW)
        assert doc.is_low_quality is True

    def test_is_low_quality_high_empty_rate(self):
        doc = self._make_doc(total_pages=10, empty_text_pages=4)
        assert doc.is_low_quality is True  # 40% > 30%

    def test_is_not_low_quality(self):
        doc = self._make_doc(total_pages=10, empty_text_pages=1)
        assert doc.is_low_quality is False  # 10% < 30%

    def test_parse_quality_enum(self):
        assert ParseQuality.NATIVE_TEXT.value == "native_text"
        assert ParseQuality.STRUCTURED.value == "structured"
        assert ParseQuality.OCR.value == "ocr"
        assert ParseQuality.LOW.value == "low"


# ═══════════════════════════════════════════════════════════════
# Loader 基类与注册表测试
# ═══════════════════════════════════════════════════════════════

class TestLoaderRegistry:
    def test_register_and_get(self):
        registry = LoaderRegistry()
        loader = TextLoader()
        registry.register(loader)
        assert registry.get_loader("test.txt") is loader
        assert registry.get_loader("test.md") is loader

    def test_unsupported_type(self):
        registry = LoaderRegistry()
        assert registry.get_loader("test.xyz") is None

    def test_load_unsupported_raises(self):
        registry = LoaderRegistry()
        with pytest.raises(ValueError, match="不支持的文件类型"):
            registry.load("test.xyz")

    def test_load_dispatches_correctly(self, tmp_path):
        f = tmp_path / "test.txt"
        f.write_text("hello", encoding="utf-8")
        registry = LoaderRegistry()
        registry.register(TextLoader())
        doc = registry.load(str(f))
        assert doc.file_type == "text"
        assert doc.source_name == "test.txt"


# ═══════════════════════════════════════════════════════════════
# PDF Loader 测试
# ═══════════════════════════════════════════════════════════════

class TestPdfLoader:
    def test_supports_pdf(self):
        loader = PdfLoader()
        assert loader.supports("test.pdf") is True
        assert loader.supports("test.txt") is False

    def test_heading_detection_numbered(self):
        assert _detect_heading_level("1. Introduction") == 1
        assert _detect_heading_level("1.1 Methods") == 2
        assert _detect_heading_level("1.1.1 Details") == 3

    def test_heading_detection_chinese(self):
        assert _detect_heading_level("一、概述") == 1
        assert _detect_heading_level("二、方法") == 1

    def test_heading_detection_parenthesized(self):
        assert _detect_heading_level("(1) First point") == 2
        assert _detect_heading_level("（2）第二点") == 2

    def test_heading_detection_markdown(self):
        assert _detect_heading_level("# Title") == 1
        assert _detect_heading_level("## Subtitle") == 2
        assert _detect_heading_level("### Sub-subtitle") == 3

    def test_heading_detection_non_heading(self):
        assert _detect_heading_level("This is a paragraph.") is None
        assert _detect_heading_level("") is None
        assert _detect_heading_level("   ") is None

    def test_assess_quality(self):
        loader = PdfLoader()
        assert loader._assess_quality(10, 0) == ParseQuality.NATIVE_TEXT
        assert loader._assess_quality(10, 2) == ParseQuality.OCR  # 20% > 10%
        assert loader._assess_quality(10, 4) == ParseQuality.LOW  # 40% > 30%
        assert loader._assess_quality(0, 0) == ParseQuality.LOW


# ═══════════════════════════════════════════════════════════════
# DOCX Loader 测试
# ═══════════════════════════════════════════════════════════════

class TestDocxLoader:
    def test_supports_docx(self):
        loader = DocxLoader()
        assert loader.supports("test.docx") is True
        assert loader.supports("test.pdf") is False

    def test_heading_level_from_style_english(self):
        assert _heading_level_from_style("Heading 1") == 1
        assert _heading_level_from_style("Heading 3") == 3
        assert _heading_level_from_style("Heading 6") == 6

    def test_heading_level_from_style_chinese(self):
        assert _heading_level_from_style("标题 1") == 1
        assert _heading_level_from_style("标题 3") == 3

    def test_heading_level_from_style_none(self):
        assert _heading_level_from_style(None) is None
        assert _heading_level_from_style("Normal") is None
        assert _heading_level_from_style("") is None

    def test_heading_level_from_style_invalid(self):
        assert _heading_level_from_style("Heading 0") is None
        assert _heading_level_from_style("Heading 7") is None

    def test_extract_table_text(self):
        loader = DocxLoader()
        mock_table = MagicMock()
        mock_table.rows = [
            MagicMock(cells=[MagicMock(text="A"), MagicMock(text="B")]),
            MagicMock(cells=[MagicMock(text="1"), MagicMock(text="2")]),
        ]
        result = loader._extract_table_text(mock_table)
        assert "A | B" in result
        assert "1 | 2" in result


# ═══════════════════════════════════════════════════════════════
# Text Loader 测试
# ═══════════════════════════════════════════════════════════════

class TestTextLoader:
    def test_supports_text(self):
        loader = TextLoader()
        assert loader.supports("test.txt") is True
        assert loader.supports("test.md") is True
        assert loader.supports("test.py") is True
        assert loader.supports("test.pdf") is False

    def test_load_text_file(self, tmp_path):
        f = tmp_path / "test.txt"
        f.write_text("Hello world\n\nSecond paragraph", encoding="utf-8")
        loader = TextLoader()
        doc = loader.load(str(f))
        assert doc.file_type == "text"
        assert doc.parse_quality == ParseQuality.NATIVE_TEXT
        assert len(doc.sections) >= 1
        assert "Hello world" in doc.full_text

    def test_load_markdown_file(self, tmp_path):
        f = tmp_path / "test.md"
        f.write_text("# Title\n\nParagraph 1\n\n## Subtitle\n\nParagraph 2", encoding="utf-8")
        loader = TextLoader()
        doc = loader.load(str(f))
        assert doc.file_type == "text"
        # Markdown 应检测到标题
        heading_sections = [s for s in doc.sections if s.section_type == SectionType.HEADING]
        assert len(heading_sections) >= 1

    def test_load_nonexistent_raises(self):
        loader = TextLoader()
        with pytest.raises(ValueError, match="无法读取"):
            loader.load("/nonexistent/file.txt")


# ═══════════════════════════════════════════════════════════════
# Chunking 测试
# ═══════════════════════════════════════════════════════════════

class TestChunking:
    def _make_doc(self, sections=None, file_type="text") -> Document:
        return Document(
            source_id="test123",
            source_path="/test/doc.txt",
            source_name="doc.txt",
            file_type=file_type,
            sections=sections if sections is not None else [
                Section(section_type=SectionType.PARAGRAPH, text="Short paragraph."),
            ],
        )

    def test_chunk_small_section(self):
        doc = self._make_doc()
        chunks = chunk_document(doc)
        assert len(chunks) == 1
        assert chunks[0].text == "Short paragraph."
        assert chunks[0].section_heading == ""

    def test_chunk_preserves_section_heading(self):
        doc = self._make_doc(sections=[
            Section(
                section_type=SectionType.HEADING,
                text="1. Introduction",
                heading_level=1,
                heading_path="Introduction",
            ),
            Section(
                section_type=SectionType.PARAGRAPH,
                text="Content here.",
                heading_path="Introduction",
            ),
        ])
        chunks = chunk_document(doc)
        assert len(chunks) == 2
        assert chunks[1].section_heading == "Introduction"

    def test_chunk_long_section_split(self):
        # PDF 类型 chunk_size=400，用 1000 字符的文本确保超过
        long_text = "Word " * 200  # ~1000 chars, exceeds pdf chunk_size=400
        doc = self._make_doc(sections=[
            Section(section_type=SectionType.PARAGRAPH, text=long_text),
        ], file_type="pdf")
        chunks = chunk_document(doc)
        # 超长 section 应被切分为多个 chunk（排除 anchor）
        content_chunks = [c for c in chunks if c.metadata.get("chunk_type") != "anchor"]
        assert len(content_chunks) > 1

    def test_chunk_pdf_adds_anchor(self):
        doc = self._make_doc(
            file_type="pdf",
            sections=[
                Section(section_type=SectionType.PARAGRAPH, text="First page content.", page=1),
            ],
        )
        chunks = chunk_document(doc)
        # 应有 1 个内容 chunk + 1 个 anchor chunk
        anchor_chunks = [c for c in chunks if c.metadata.get("chunk_type") == "anchor"]
        assert len(anchor_chunks) == 1
        assert anchor_chunks[0].chunk_index == -1

    def test_chunk_pdf_no_anchor_for_empty_first_page(self):
        doc = self._make_doc(
            file_type="pdf",
            sections=[
                Section(section_type=SectionType.PARAGRAPH, text="", page=1),
                Section(section_type=SectionType.PARAGRAPH, text="Content on page 2", page=2),
            ],
        )
        chunks = chunk_document(doc)
        anchor_chunks = [c for c in chunks if c.metadata.get("chunk_type") == "anchor"]
        assert len(anchor_chunks) == 0

    def test_chunks_to_index_data(self):
        doc = self._make_doc(
            sections=[
                Section(section_type=SectionType.PARAGRAPH, text="Hello world."),
            ],
        )
        doc.content_sha256 = "abc"
        doc.source_size = 100
        doc.source_mtime_ns = 12345
        doc.chunks = chunk_document(doc)
        texts, metadatas, ids = chunks_to_index_data(doc)
        assert len(texts) == len(metadatas) == len(ids) == 1
        assert texts[0] == "Hello world."
        assert metadatas[0]["source_id"] == "test123"
        assert metadatas[0]["section_heading"] == ""
        assert metadatas[0]["section_type"] == "paragraph"
        assert ids[0].startswith("test123_chunk_")

    def test_chunking_config_version(self):
        assert CHUNKING_CONFIG_V3["version"] == 3

    def test_empty_sections_produce_no_chunks(self):
        doc = self._make_doc(sections=[])
        chunks = chunk_document(doc)
        assert len(chunks) == 0

    def test_chunk_preserves_page(self):
        doc = self._make_doc(
            file_type="pdf",
            sections=[
                Section(section_type=SectionType.PARAGRAPH, text="Page 3 content", page=3),
            ],
        )
        chunks = chunk_document(doc)
        # 找到非 anchor 的 chunk
        content_chunks = [c for c in chunks if c.metadata.get("chunk_type") != "anchor"]
        assert content_chunks[0].page == 3


# ═══════════════════════════════════════════════════════════════
# 集成测试：loader → chunking → index_data 全链路
# ═══════════════════════════════════════════════════════════════

class TestLoaderChunkingIntegration:
    def test_text_file_full_pipeline(self, tmp_path):
        """文本文件：load → chunk → index_data 全链路。"""
        f = tmp_path / "test.txt"
        f.write_text("First paragraph.\n\nSecond paragraph.", encoding="utf-8")

        loader = TextLoader()
        doc = loader.load(str(f))
        doc.chunks = chunk_document(doc)
        texts, metadatas, ids = chunks_to_index_data(doc)

        assert len(texts) >= 1
        assert all("source_id" in m for m in metadatas)
        assert all("chunk_id" in m for m in metadatas)
        assert all("section_type" in m for m in metadatas)

    def test_markdown_file_full_pipeline(self, tmp_path):
        """Markdown 文件：标题检测 + 分块。"""
        f = tmp_path / "test.md"
        f.write_text("# Title\n\nContent under title.\n\n## Sub\n\nMore content.", encoding="utf-8")

        loader = TextLoader()
        doc = loader.load(str(f))
        doc.chunks = chunk_document(doc)
        texts, metadatas, ids = chunks_to_index_data(doc)

        # 至少有 heading section
        heading_metas = [m for m in metadatas if m.get("section_type") == "heading"]
        assert len(heading_metas) >= 1
        # section_heading 应被填充
        with_heading = [m for m in metadatas if m.get("section_heading")]
        assert len(with_heading) >= 1
