"""Tests for the v2 corpus .gitattributes whitespace exemption.

Raw downloaded documents and license evidence files must stay
byte-identical to their upstream sources (trailing whitespace is part
of the original text), so whitespace checks are disabled for exactly
two path trees — and nothing else.  Code, JSONL, annotations and
manifests keep full whitespace checking.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# 代表性文件：raw HTML、_parts 子目录、processed 文档、许可证证据。
EXEMPT_PATHS = [
    "data/v2-corpus/documents/nodejs-fs.html",                       # raw HTML
    "data/v2-corpus/documents/_parts/pytut-appetite.html",           # _parts
    "data/v2-corpus/documents/processed/rust-book-core.md",          # processed
    "data/v2-corpus/attribution/licenses/sqlite-public-domain.txt",  # 许可证
    "data/v2-corpus/attribution/licenses/gutenberg-ebook-132-license.txt",
]

# 豁免范围之外、绝不允许放松 whitespace 检查的文件。
NON_EXEMPT_PATHS = [
    "scripts/corpus_v2_licenses.py",
    "data/v2-corpus/chunks/chunks.jsonl",
    "data/v2-corpus/chunks/chunk-manifest.json",
    "evaluation/datasets/v2/corpus-manifest.jsonl",
    "data/v2-corpus/attribution/nodejs-fs.md",
    "CHANGELOG.md",
]

EXPECTED_PATTERNS = {
    "data/v2-corpus/documents/**",
    "data/v2-corpus/attribution/licenses/**",
}


def git_check_attr(path: str) -> str:
    proc = subprocess.run(
        ["git", "check-attr", "whitespace", "--", path],
        cwd=ROOT, capture_output=True, text=True, check=True,
    )
    return proc.stdout.strip()


def test_gitattributes_covers_exactly_two_path_trees():
    attrs = (ROOT / ".gitattributes").read_text(encoding="utf-8")
    rules = [ln.strip() for ln in attrs.splitlines()
             if ln.strip() and not ln.lstrip().startswith("#")]
    assert rules, ".gitattributes 必须存在且包含豁免规则"
    patterns = {ln.split()[0] for ln in rules}
    assert patterns == EXPECTED_PATTERNS, \
        f"豁免范围必须是且仅是 documents 与 licenses 两个目录树: {patterns}"
    for ln in rules:
        # 每行只能 = 一个 pattern + 一个 -whitespace，不得附带其他属性。
        assert re.fullmatch(r"\S+ -whitespace", ln), \
            f"规则只允许关闭 whitespace: {ln!r}"


def test_representative_files_have_whitespace_unset():
    for path in EXEMPT_PATHS:
        assert (ROOT / path).is_file(), f"代表性文件缺失: {path}"
        assert git_check_attr(path).endswith(": whitespace: unset"), path


def test_outside_paths_keep_whitespace_checking():
    for path in NON_EXEMPT_PATHS:
        assert git_check_attr(path).endswith(
            ": whitespace: unspecified"), path


def test_staged_diff_check_passes():
    # Windows 可验证性契约：暂存区 diff 不得有 whitespace 错误。
    proc = subprocess.run(
        ["git", "diff", "--cached", "--check"],
        cwd=ROOT, capture_output=True, text=True,
    )
    assert proc.returncode == 0, \
        f"staged diff 存在 whitespace 错误:\n{proc.stdout[:4000]}"
