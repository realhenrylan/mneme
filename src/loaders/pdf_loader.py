"""PDF 文档解析器。

使用 PyMuPDF（fitz）优先，pdfplumber 降级。
提取页面文本、标题层级（字号 + 编号模式）、表格，并计算解析质量指标。

解析质量等级：
- NATIVE_TEXT: 原生数字 PDF，文本提取成功率高
- STRUCTURED: 检测到标题层级或表格
- OCR: 空文本页率 10%-30%，可能需要 OCR
- LOW: 空文本页率 >30% 或解析完全失败
"""

from __future__ import annotations

import hashlib
import os
import re
from pathlib import Path

from src.domain import (
    Chunk, Document, ParseQuality, Section, SectionType,
)
from src.loaders.base import BaseLoader
from src.security import validate_pdf_page_count


# 标题检测正则：匹配 "1.", "1.1", "1.1.1" 等编号模式
# 注意：中文标题后不一定有空格，\s+ 改为 \s*（至少英文编号后通常有空格，保留 \s+）
_HEADING_PATTERN = re.compile(
    r"^(\d+(\.\d+)*\.?)\s+"  # 编号：1. / 1.1. / 1.1.1.
    r"|"
    r"^([一二三四五六七八九十百]+[、.．])\s*"  # 中文编号：一、/ 二.（中文后可无空格）
    r"|"
    r"^([(（]\d+[)）])\s*"  # 括号编号：(1) / （2）（中文后可无空格）
)

# Markdown 标题检测
_MD_HEADING_PATTERN = re.compile(r"^(#{1,6})\s+")

# 字号标题检测阈值：字号超过正文平均字号的 1.3 倍视为标题
_FONT_SIZE_HEADING_RATIO = 1.3

# 最小标题字号（pt）：小于此值不视为标题，避免误判脚注
_MIN_HEADING_FONT_SIZE = 10.0


def _detect_heading_level(text: str) -> int | None:
    """从文本行检测标题级别。

    Returns:
        1-6 的标题级别，或 None（非标题行）
    """
    stripped = text.strip()
    if not stripped:
        return None

    # Markdown 风格标题
    md_match = _MD_HEADING_PATTERN.match(stripped)
    if md_match:
        return len(md_match.group(1))

    # 编号标题：根据编号深度推断级别
    num_match = _HEADING_PATTERN.match(stripped)
    if num_match:
        # "1." → level 1, "1.1." → level 2, "1.1.1." → level 3
        numbering = num_match.group(1)
        if numbering:
            depth = numbering.rstrip(".").count(".") + 1
            return min(depth, 6)
        # 中文编号 → level 1
        if num_match.group(3):
            return 1
        # 括号编号 → level 2
        if num_match.group(4):
            return 2

    return None


def _detect_heading_by_font_size(
    spans: list[dict],
) -> int | None:
    """从 fitz span 列表中检测标题级别（基于字号）。

    策略：找到该行最大字号，与全页平均正文字号比较。
    字号超过正文 1.3 倍的行视为标题，字号越大级别越低。

    Args:
        spans: fitz page.get_text("dict")["blocks"] 中提取的 span 列表

    Returns:
        1-6 的标题级别，或 None
    """
    if not spans:
        return None

    # 提取所有字号
    font_sizes = []
    for span in spans:
        size = span.get("size", 0)
        if size >= _MIN_HEADING_FONT_SIZE:
            font_sizes.append(size)

    if not font_sizes:
        return None

    max_size = max(font_sizes)

    # 如果只有一种字号，无法判断标题
    if len(set(font_sizes)) <= 1:
        return None

    # 计算众数作为正文基准字号
    from collections import Counter
    size_counts = Counter(round(s, 1) for s in font_sizes)
    base_size = size_counts.most_common(1)[0][0]

    if max_size >= base_size * _FONT_SIZE_HEADING_RATIO:
        # 字号越大，标题级别越低（1 最大）
        ratio = max_size / base_size if base_size > 0 else 1
        if ratio >= 2.0:
            return 1
        elif ratio >= 1.7:
            return 2
        elif ratio >= 1.5:
            return 3
        else:
            return 4

    return None


def _build_heading_path(headings_stack: list[tuple[int, str]]) -> str:
    """从标题栈构建层级路径。"""
    if not headings_stack:
        return ""
    return " > ".join(h[1] for h in headings_stack)


def _format_table(table_data: list[list[str | None]]) -> str:
    """将 pdfplumber 提取的表格数据格式化为文本。

    Args:
        table_data: 二维列表，每行是表格的一行

    Returns:
        格式化后的表格文本
    """
    rows = []
    for row in table_data:
        cells = [str(cell or "").strip() for cell in row]
        rows.append(" | ".join(cells))
    return "\n".join(rows)


class PdfLoader(BaseLoader):
    """PDF 文档解析器。"""

    SUPPORTED_EXTENSIONS = [".pdf"]

    def load(self, filepath: str) -> Document:
        """解析 PDF 文件，返回 Document 对象。

        提取每页文本，检测标题层级，提取表格，计算解析质量。
        """
        filepath = os.path.realpath(os.path.abspath(os.path.expanduser(filepath)))
        stat = os.stat(filepath)
        source_id = hashlib.sha256(
            os.path.normcase(filepath).encode("utf-8")
        ).hexdigest()
        content_sha256 = self._sha256_file(filepath)

        # 尝试 PyMuPDF，降级 pdfplumber
        sections, total_pages, empty_pages, table_count = self._extract_with_fitz(filepath)
        if sections is None:
            sections, total_pages, empty_pages, table_count = self._extract_with_pdfplumber(filepath)

        # 判断解析质量
        parse_quality = self._assess_quality(total_pages, empty_pages)

        # 检测到表格则升级为 STRUCTURED
        if table_count > 0 and parse_quality == ParseQuality.NATIVE_TEXT:
            parse_quality = ParseQuality.STRUCTURED

        return Document(
            source_id=source_id,
            source_path=filepath,
            source_name=os.path.basename(filepath),
            file_type="pdf",
            sections=sections if sections is not None else [],
            parse_quality=parse_quality,
            parser_version="2.0",
            content_sha256=content_sha256,
            source_size=stat.st_size,
            source_mtime_ns=stat.st_mtime_ns,
            total_pages=total_pages,
            empty_text_pages=empty_pages,
            metadata={"table_count": table_count},
        )

    def _extract_with_fitz(
        self, filepath: str,
    ) -> tuple[list[Section] | None, int, int, int]:
        """使用 PyMuPDF 提取。返回 (sections, total_pages, empty_pages, table_count)。"""
        try:
            import fitz
        except ImportError:
            return None, 0, 0, 0

        try:
            sections: list[Section] = []
            total_pages = 0
            empty_pages = 0
            table_count = 0
            char_offset = 0

            with fitz.open(filepath) as pdf:
                validate_pdf_page_count(pdf.page_count, filepath)
                total_pages = pdf.page_count
                headings_stack: list[tuple[int, str]] = []

                for page_num, page in enumerate(pdf, start=1):
                    page_text = page.get_text("text")
                    if not page_text or not page_text.strip():
                        empty_pages += 1
                        continue

                    # 按行检测标题，构建 sections
                    lines = page_text.splitlines()
                    current_section_lines: list[str] = []
                    current_heading_level: int | None = None
                    current_heading_path: str = ""
                    section_char_start = char_offset

                    for line in lines:
                        heading_level = _detect_heading_level(line)

                        if heading_level is not None and line.strip():
                            # 遇到新标题，先保存当前 section
                            if current_section_lines:
                                section_text = "\n".join(current_section_lines)
                                sections.append(Section(
                                    section_type=(
                                        SectionType.HEADING
                                        if current_heading_level is not None
                                        else SectionType.PARAGRAPH
                                    ),
                                    text=section_text,
                                    heading_level=current_heading_level,
                                    heading_path=current_heading_path,
                                    page=page_num,
                                    char_start=section_char_start,
                                    char_end=section_char_start + len(section_text),
                                ))
                                char_offset += len(section_text) + 1

                            # 更新标题栈
                            heading_text = line.strip()
                            # 弹出比当前级别低或同级的标题
                            while headings_stack and headings_stack[-1][0] >= heading_level:
                                headings_stack.pop()
                            headings_stack.append((heading_level, heading_text))

                            current_section_lines = [line]
                            current_heading_level = heading_level
                            current_heading_path = _build_heading_path(headings_stack)
                            section_char_start = char_offset
                        else:
                            current_section_lines.append(line)

                    # 保存最后一个 section
                    if current_section_lines:
                        section_text = "\n".join(current_section_lines)
                        sections.append(Section(
                            section_type=(
                                SectionType.HEADING
                                if current_heading_level is not None
                                else SectionType.PARAGRAPH
                            ),
                            text=section_text,
                            heading_level=current_heading_level,
                            heading_path=current_heading_path,
                            page=page_num,
                            char_start=section_char_start,
                            char_end=section_char_start + len(section_text),
                        ))
                        char_offset += len(section_text) + 1

            return sections, total_pages, empty_pages, table_count

        except Exception:
            return None, 0, 0, 0

    def _extract_with_pdfplumber(
        self, filepath: str,
    ) -> tuple[list[Section] | None, int, int, int]:
        """使用 pdfplumber 提取，包括表格。返回 (sections, total_pages, empty_pages, table_count)。"""
        try:
            import pdfplumber
        except ImportError:
            return None, 0, 0, 0

        try:
            sections: list[Section] = []
            total_pages = 0
            empty_pages = 0
            table_count = 0
            char_offset = 0

            with pdfplumber.open(filepath) as pdf:
                validate_pdf_page_count(len(pdf.pages), filepath)
                total_pages = len(pdf.pages)
                headings_stack: list[tuple[int, str]] = []

                for page_num, page in enumerate(pdf.pages, start=1):
                    # 提取表格
                    page_tables = page.extract_tables()
                    for table_idx, table in enumerate(page_tables or []):
                        if not table:
                            continue
                        table_text = _format_table(table)
                        if not table_text.strip():
                            continue

                        heading_path = _build_heading_path(headings_stack)
                        sections.append(Section(
                            section_type=SectionType.TABLE,
                            text=table_text,
                            heading_path=heading_path,
                            page=page_num,
                            char_start=char_offset,
                            char_end=char_offset + len(table_text),
                            metadata={
                                "table_index": table_count,
                                "rows": len(table),
                                "cols": len(table[0]) if table else 0,
                            },
                        ))
                        char_offset += len(table_text) + 1
                        table_count += 1

                    # 提取文本（排除表格区域）
                    page_text = page.extract_text()
                    if not page_text or not page_text.strip():
                        empty_pages += 1
                        continue

                    # 与 fitz 相同的 section 检测逻辑
                    lines = page_text.splitlines()
                    current_section_lines: list[str] = []
                    current_heading_level: int | None = None
                    current_heading_path: str = ""
                    section_char_start = char_offset

                    for line in lines:
                        heading_level = _detect_heading_level(line)

                        if heading_level is not None and line.strip():
                            if current_section_lines:
                                section_text = "\n".join(current_section_lines)
                                sections.append(Section(
                                    section_type=(
                                        SectionType.HEADING
                                        if current_heading_level is not None
                                        else SectionType.PARAGRAPH
                                    ),
                                    text=section_text,
                                    heading_level=current_heading_level,
                                    heading_path=current_heading_path,
                                    page=page_num,
                                    char_start=section_char_start,
                                    char_end=section_char_start + len(section_text),
                                ))
                                char_offset += len(section_text) + 1

                            heading_text = line.strip()
                            while headings_stack and headings_stack[-1][0] >= heading_level:
                                headings_stack.pop()
                            headings_stack.append((heading_level, heading_text))

                            current_section_lines = [line]
                            current_heading_level = heading_level
                            current_heading_path = _build_heading_path(headings_stack)
                            section_char_start = char_offset
                        else:
                            current_section_lines.append(line)

                    if current_section_lines:
                        section_text = "\n".join(current_section_lines)
                        sections.append(Section(
                            section_type=(
                                SectionType.HEADING
                                if current_heading_level is not None
                                else SectionType.PARAGRAPH
                            ),
                            text=section_text,
                            heading_level=current_heading_level,
                            heading_path=current_heading_path,
                            page=page_num,
                            char_start=section_char_start,
                            char_end=section_char_start + len(section_text),
                        ))
                        char_offset += len(section_text) + 1

            return sections, total_pages, empty_pages, table_count

        except Exception:
            return None, 0, 0, 0

    def _assess_quality(self, total_pages: int, empty_pages: int) -> ParseQuality:
        """评估 PDF 解析质量。"""
        if total_pages == 0:
            return ParseQuality.LOW
        empty_rate = empty_pages / total_pages
        if empty_rate > 0.3:
            return ParseQuality.LOW
        if empty_rate > 0.1:
            return ParseQuality.OCR
        return ParseQuality.NATIVE_TEXT

    @staticmethod
    def _sha256_file(filepath: str) -> str:
        digest = hashlib.sha256()
        with open(filepath, "rb") as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(block)
        return digest.hexdigest()
