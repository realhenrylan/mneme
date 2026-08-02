"""纯文本文档解析器。

支持 .txt, .md, .json, .csv, .py 等纯文本格式。
Markdown 文件会检测标题层级。
"""

from __future__ import annotations

import hashlib
import os
import re
from pathlib import Path

from src.domain import (
    Document, ParseQuality, Section, SectionType,
)
from src.loaders.base import BaseLoader

# Markdown 标题检测
_MD_HEADING = re.compile(r"^(#{1,6})\s+(.+)$")


class TextLoader(BaseLoader):
    """纯文本文档解析器。

    Markdown 文件会检测 # 标题层级，其他格式按段落分 section。
    """

    SUPPORTED_EXTENSIONS = [
        ".txt", ".md", ".markdown", ".html", ".htm",
        ".json", ".csv", ".xml", ".yaml", ".yml",
        ".toml", ".cfg", ".ini", ".conf", ".log",
        ".py", ".js", ".ts", ".css", ".sql",
        ".sh", ".bat", ".gitignore",
    ]

    def load(self, filepath: str) -> Document:
        """解析文本文件，返回 Document 对象。"""
        filepath = os.path.realpath(os.path.abspath(os.path.expanduser(filepath)))
        try:
            stat = os.stat(filepath)
        except FileNotFoundError as e:
            raise ValueError(f"无法读取文本文件 {filepath}: {e}") from e
        source_id = hashlib.sha256(
            os.path.normcase(filepath).encode("utf-8")
        ).hexdigest()
        content_sha256 = self._sha256_file(filepath)

        try:
            with open(filepath, "r", encoding="utf-8", errors="replace") as f:
                text = f.read()
        except FileNotFoundError as e:
            raise ValueError(f"无法读取文本文件 {filepath}: {e}") from e
        except Exception as e:
            raise ValueError(f"无法读取文本文件 {filepath}: {e}") from e

        suffix = Path(filepath).suffix.lower()
        sections = self._parse_sections(text, suffix)

        return Document(
            source_id=source_id,
            source_path=filepath,
            source_name=os.path.basename(filepath),
            file_type="text",
            sections=sections,
            parse_quality=ParseQuality.NATIVE_TEXT,
            parser_version="1.0",
            content_sha256=content_sha256,
            source_size=stat.st_size,
            source_mtime_ns=stat.st_mtime_ns,
        )

    def _parse_sections(self, text: str, suffix: str) -> list[Section]:
        """按文件类型解析 section。

        Markdown 文件检测 # 标题，其他格式按空行分段。
        """
        if suffix in (".md", ".markdown"):
            return self._parse_markdown(text)
        return self._parse_plain(text)

    def _parse_markdown(self, text: str) -> list[Section]:
        """解析 Markdown，检测 # 标题层级。"""
        sections: list[Section] = []
        char_offset = 0
        headings_stack: list[tuple[int, str]] = []
        current_lines: list[str] = []
        current_heading_level: int | None = None
        current_heading_path: str = ""
        section_char_start = 0

        for line in text.splitlines():
            md_match = _MD_HEADING.match(line)
            if md_match:
                # 保存当前 section
                if current_lines:
                    section_text = "\n".join(current_lines)
                    sections.append(Section(
                        section_type=(
                            SectionType.HEADING
                            if current_heading_level is not None
                            else SectionType.PARAGRAPH
                        ),
                        text=section_text,
                        heading_level=current_heading_level,
                        heading_path=current_heading_path,
                        char_start=section_char_start,
                        char_end=section_char_start + len(section_text),
                    ))

                # 新标题
                heading_level = len(md_match.group(1))
                heading_text = md_match.group(2).strip()

                while headings_stack and headings_stack[-1][0] >= heading_level:
                    headings_stack.pop()
                headings_stack.append((heading_level, heading_text))

                current_lines = [line]
                current_heading_level = heading_level
                current_heading_path = " > ".join(h[1] for h in headings_stack)
                section_char_start = char_offset
            else:
                current_lines.append(line)

            char_offset += len(line) + 1

        # 保存最后一个 section
        if current_lines:
            section_text = "\n".join(current_lines)
            sections.append(Section(
                section_type=(
                    SectionType.HEADING
                    if current_heading_level is not None
                    else SectionType.PARAGRAPH
                ),
                text=section_text,
                heading_level=current_heading_level,
                heading_path=current_heading_path,
                char_start=section_char_start,
                char_end=section_char_start + len(section_text),
            ))

        return sections

    def _parse_plain(self, text: str) -> list[Section]:
        """纯文本按空行分段。"""
        sections: list[Section] = []
        char_offset = 0

        # 按双换行分段
        paragraphs = re.split(r"\n\n+", text)
        for para in paragraphs:
            para = para.strip()
            if not para:
                char_offset += len(para) + 2
                continue
            sections.append(Section(
                section_type=SectionType.PARAGRAPH,
                text=para,
                char_start=char_offset,
                char_end=char_offset + len(para),
            ))
            char_offset += len(para) + 2

        return sections

    @staticmethod
    def _sha256_file(filepath: str) -> str:
        digest = hashlib.sha256()
        with open(filepath, "rb") as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(block)
        return digest.hexdigest()
