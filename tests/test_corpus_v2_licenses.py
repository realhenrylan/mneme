"""Tests for scripts.corpus_v2_licenses — license evidence audit.

Covers the fail-closed contract: attribution ↔ manifest ↔ license-file
consistency, per-source license file ownership (no cross-source reuse),
and the pending-source rule.
"""

from __future__ import annotations

import pytest

from scripts.corpus_v2_licenses import LICENSE_FILES, SAME_SOURCE_GROUPS, audit
from scripts.corpus_v2_prepare import SOURCES


def test_audit_passes_on_real_corpus():
    # 真实语料必须通过：任何失败说明许可证据被破坏。
    assert audit() == []


def test_every_source_has_license_mapping():
    doc_ids = {s[0] for s in SOURCES}
    assert doc_ids == set(LICENSE_FILES)


def test_no_cross_source_license_reuse():
    # 同一许可证文件只能服务一个来源组（同源共用白名单除外）。
    owner: dict[str, set[str]] = {}
    for doc_id, lic_file in LICENSE_FILES.items():
        owner.setdefault(lic_file, set()).add(doc_id)
    for lic_file, doc_ids in owner.items():
        if len(doc_ids) > 1:
            assert doc_ids == SAME_SOURCE_GROUPS.get(lic_file, set()), \
                f"{lic_file} 被跨来源复用: {sorted(doc_ids)}"


def test_license_file_evidence_exists():
    from pathlib import Path
    lic_dir = Path("data/v2-corpus/attribution/licenses")
    for lic_file in LICENSE_FILES.values():
        for fn in __import__("re").findall(r"([\w.-]+\.txt)", lic_file):
            p = lic_dir / fn
            assert p.is_file(), f"许可证证据缺失: {fn}"
            assert p.stat().st_size > 0, f"许可证证据为空: {fn}"


def test_art_of_war_has_gutenberg_evidence():
    # art-of-war 必须引用 Project Gutenberg 专属再分发证据，
    # 不得再指向 sqlite 的公共领域声明。
    assert LICENSE_FILES["art-of-war"] == "gutenberg-ebook-132-license.txt"
    assert "sqlite-public-domain.txt" not in LICENSE_FILES["art-of-war"]


def test_nodejs_uses_repo_mit_evidence():
    # Node.js 文档的 CC-BY-4.0 网站声明无法独立确认，改用仓库 MIT。
    assert LICENSE_FILES["nodejs-fs"] == "MIT-nodejs.txt"


def test_vue_license_is_cc_by_40_not_mit():
    # vuejs/docs 仓库 LICENSE 文件实际声明 CC BY 4.0。
    sources = {s[0]: s for s in SOURCES}
    assert sources["vue-guide-zh"][4] == "CC-BY-4.0"
    assert "MIT" not in LICENSE_FILES["vue-guide-zh"]


def test_audit_detects_broken_mapping(monkeypatch):
    broken = dict(LICENSE_FILES)
    broken["art-of-war"] = "sqlite-public-domain.txt"
    monkeypatch.setattr("scripts.corpus_v2_licenses.LICENSE_FILES", broken)
    errors = audit()
    assert any("art-of-war" in e for e in errors)


def test_cli_exit0_under_gbk_stdout_encoding():
    """Windows 默认 GBK 控制台必须 exit 0：成功输出必须是纯 ASCII，
    不得依赖用户设置 PYTHONIOENCODING（回归：↔ 曾触发 UnicodeEncodeError）。"""
    import os
    import subprocess
    import sys
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "gbk"  # 模拟 Windows 默认控制台代码页
    proc = subprocess.run(
        [sys.executable, "scripts/corpus_v2_licenses.py"],
        cwd=root, env=env, capture_output=True,
    )
    assert proc.returncode == 0, \
        proc.stderr.decode("utf-8", "replace")
    assert b"UnicodeEncodeError" not in proc.stderr
    out = proc.stdout.decode("ascii")  # 成功输出必须可被 ASCII 严格解码
    assert "license audit passed" in out
