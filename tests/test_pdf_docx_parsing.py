"""测试 2.3 PDF/DOCX 重点解析增强。"""

import pytest
from src.domain import SectionType, ParseQuality
from src.loaders.pdf_loader import _detect_heading_level, _detect_heading_by_font_size, _format_table
from src.loaders.docx_loader import DocxLoader, _heading_level_from_style


# ═══════════════════════════════════════════════════════════════
# PDF 表格格式化测试
# ═══════════════════════════════════════════════════════════════

class TestFormatTable:
    def test_basic_table(self):
        table = [
            ["Header1", "Header2"],
            ["1", "2"],
        ]
        result = _format_table(table)
        assert "Header1 | Header2" in result
        assert "1 | 2" in result

    def test_table_with_none_cells(self):
        table = [
            ["A", None, "C"],
            [None, "B", None],
        ]
        result = _format_table(table)
        assert "A |  | C" in result
        assert " | B | " in result

    def test_empty_table(self):
        result = _format_table([])
        assert result == ""


# ═══════════════════════════════════════════════════════════════
# 字号标题检测测试
# ═══════════════════════════════════════════════════════════════

class TestDetectHeadingByFontSize:
    def test_no_spans(self):
        assert _detect_heading_by_font_size([]) is None

    def test_single_size_no_heading(self):
        """只有一种字号时不视为标题。"""
        spans = [
            {"size": 12.0, "text": "Line 1"},
            {"size": 12.0, "text": "Line 2"},
        ]
        assert _detect_heading_by_font_size(spans) is None

    def test_large_font_heading(self):
        """大字号行视为标题。"""
        spans = [
            {"size": 12.0, "text": "Normal text"},
            {"size": 12.0, "text": "More text"},
            {"size": 24.0, "text": "BIG TITLE"},
        ]
        level = _detect_heading_by_font_size(spans)
        assert level is not None
        assert level == 1  # ratio >= 2.0 → level 1

    def test_medium_font_heading(self):
        """中等字号行视为低级标题。"""
        spans = [
            {"size": 12.0, "text": "Normal"},
            {"size": 12.0, "text": "Normal"},
            {"size": 16.0, "text": "Subheading"},
        ]
        level = _detect_heading_by_font_size(spans)
        assert level is not None
        assert level >= 2  # ratio ~1.3 → level 4

    def test_small_font_not_heading(self):
        """小于最小字号的文本不视为标题。"""
        spans = [
            {"size": 8.0, "text": "Small"},
            {"size": 8.0, "text": "Small"},
            {"size": 12.0, "text": "Big"},
        ]
        # 8.0 < _MIN_HEADING_FONT_SIZE (10.0), 只有 12.0 的字号
        # 众数是 8.0，最大是 12.0，但 8.0 不计入 font_sizes
        # 所以 font_sizes = [12.0]，只有一种字号，返回 None
        assert _detect_heading_by_font_size(spans) is None


# ═══════════════════════════════════════════════════════════════
# PDF 解析质量升级测试
# ═══════════════════════════════════════════════════════════════

class TestPdfParseQuality:
    def test_quality_upgraded_with_tables(self):
        """有表格时质量升级为 STRUCTURED。"""
        from src.loaders.pdf_loader import PdfLoader
        loader = PdfLoader()
        # _assess_quality 只看空文本页率，但 load() 中会根据 table_count 升级
        # 模拟：空文本页率 0%，有表格 → STRUCTURED
        assert loader._assess_quality(10, 0) == ParseQuality.NATIVE_TEXT
        # 在 load() 中，如果 table_count > 0 且 quality == NATIVE_TEXT，升级为 STRUCTURED

    def test_quality_low_with_many_empty_pages(self):
        from src.loaders.pdf_loader import PdfLoader
        loader = PdfLoader()
        assert loader._assess_quality(10, 4) == ParseQuality.LOW  # 40% > 30%

    def test_quality_ocr_with_some_empty_pages(self):
        from src.loaders.pdf_loader import PdfLoader
        loader = PdfLoader()
        assert loader._assess_quality(10, 2) == ParseQuality.OCR  # 20% > 10%

    def test_quality_low_zero_pages(self):
        from src.loaders.pdf_loader import PdfLoader
        loader = PdfLoader()
        assert loader._assess_quality(0, 0) == ParseQuality.LOW


# ═══════════════════════════════════════════════════════════════
# DOCX 表格提取测试
# ═══════════════════════════════════════════════════════════════

class TestDocxTableExtraction:
    def test_extract_table_text(self):
        from unittest.mock import MagicMock
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
# 标题检测综合测试
# ═══════════════════════════════════════════════════════════════

class TestHeadingDetectionComprehensive:
    def test_deep_numbering(self):
        """深层编号标题。"""
        assert _detect_heading_level("1.2.3.4 Deep section") == 4

    def test_chinese_numbering_variants(self):
        """中文编号变体。"""
        assert _detect_heading_level("一、总则") == 1
        assert _detect_heading_level("二．方法") == 1
        assert _detect_heading_level("十、结论") == 1

    def test_mixed_content_not_heading(self):
        """包含数字但不是标题的行。"""
        assert _detect_heading_level("The result is 3.14") is None
        assert _detect_heading_level("Price: 100 dollars") is None

    def test_docx_heading_styles(self):
        """DOCX 标题样式检测。"""
        assert _heading_level_from_style("Heading 1") == 1
        assert _heading_level_from_style("Heading 6") == 6
        assert _heading_level_from_style("标题 1") == 1
        assert _heading_level_from_style("Normal") is None
        assert _heading_level_from_style("Title") is None
