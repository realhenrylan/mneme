"""PDF 文档解析器。

使用 PyMuPDF（fitz）优先，pdfplumber 降级。
提取页面文本、标题层级、表格，并计算解析质量指标。
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


def _build_heading_path(headings_stack: list[tuple[int, str]]) -> str:
    """从标题栈构建层级路径。"""
    if not headings_stack:
        return ""
    return " > ".join(h[1] for h in headings_stack)


class PdfLoader(BaseLoader):
    """PDF 文档解析器。"""

    SUPPORTED_EXTENSIONS = [".pdf"]

    def load(self, filepath: str) -> Document:
        """解析 PDF 文件，返回 Document 对象。

        提取每页文本，检测标题层级，计算解析质量。
        """
        filepath = os.path.realpath(os.path.abspath(os.path.expanduser(filepath)))
        stat = os.stat(filepath)
        source_id = hashlib.sha256(
            os.path.normcase(filepath).encode("utf-8")
        ).hexdigest()
        content_sha256 = self._sha256_file(filepath)

        # 尝试 PyMuPDF，降级 pdfplumber
        sections, total_pages, empty_pages = self._extract_with_fitz(filepath)
        if sections is None:
            sections, total_pages, empty_pages = self._extract_with_pdfplumber(filepath)

        # 判断解析质量
        parse_quality = self._assess_quality(total_pages, empty_pages)

        return Document(
            source_id=source_id,
            source_path=filepath,
            source_name=os.path.basename(filepath),
            file_type="pdf",
            sections=sections,
            parse_quality=parse_quality,
            parser_version="1.0",
            content_sha256=content_sha256,
            source_size=stat.st_size,
            source_mtime_ns=stat.st_mtime_ns,
            total_pages=total_pages,
            empty_text_pages=empty_pages,
        )

    def _extract_with_fitz(
        self, filepath: str,
    ) -> tuple[list[Section] | None, int, int]:
        """使用 PyMuPDF 提取。返回 (sections, total_pages, empty_pages)。"""
        try:
            import fitz
        except ImportError:
            return None, 0, 0

        try:
            sections: list[Section] = []
            total_pages = 0
            empty_pages = 0
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

            return sections, total_pages, empty_pages

        except Exception:
            return None, 0, 0

    def _extract_with_pdfplumber(
        self, filepath: str,
    ) -> tuple[list[Section] | None, int, int]:
        """使用 pdfplumber 提取。返回 (sections, total_pages, empty_pages)。"""
        try:
            import pdfplumber
        except ImportError:
            return None, 0, 0

        try:
            sections: list[Section] = []
            total_pages = 0
            empty_pages = 0
            char_offset = 0

            with pdfplumber.open(filepath) as pdf:
                validate_pdf_page_count(len(pdf.pages), filepath)
                total_pages = len(pdf.pages)
                headings_stack: list[tuple[int, str]] = []

                for page_num, page in enumerate(pdf.pages, start=1):
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

            return sections, total_pages, empty_pages

        except Exception:
            return None, 0, 0

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
