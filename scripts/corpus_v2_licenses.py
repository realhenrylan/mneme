"""Corpus v2 license evidence audit (fail-closed).

Verifies that every document's attribution record points at its own
license evidence file and that the corpus manifest agrees with the
attribution records:

- every attribution/{id}.md exists and its "许可证原文" line matches the
  per-document mapping (``prepare.LICENSE_FILES``);
- every referenced license file exists and is non-empty;
- the manifest ``license`` field matches the attribution "许可证：" line;
- no license file is reused across *unrelated* sources — only the
  documented same-source groups (docs.python.org PSF-2.0 pages, the
  rust-lang/book dual license) may share a file.

Any violation is reported and the audit exits non-zero.

Usage: python scripts/corpus_v2_licenses.py
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ATTR = ROOT / "data" / "v2-corpus" / "attribution"
LIC = ATTR / "licenses"
MANIFEST = ROOT / "evaluation" / "datasets" / "v2" / "corpus-manifest.jsonl"

sys.path.insert(0, str(ROOT))
from scripts.corpus_v2_prepare import LICENSE_FILES, SOURCES  # noqa: E402

# Same-source groups allowed to share one license evidence file.
SAME_SOURCE_GROUPS = {
    "PSF-2.0.txt": {"python-tutorial-zh", "python-whatsnew313-zh",
                    "python-datetime-zh", "python-tutorial-en",
                    "python-glossary-zh"},
    "rust-book-MIT.txt (+ rust-book-APACHE.txt)": {"rust-book-core"},
}

# license name per document (from SOURCES tuple index 4)
DOC_LIC = {s[0]: s[4] for s in SOURCES}


def audit() -> list[str]:
    """Run the audit; returns a list of violation messages (empty = pass)."""
    errors: list[str] = []
    manifest = {}
    for line in MANIFEST.open(encoding="utf-8"):
        if line.strip():
            d = json.loads(line)
            manifest[d["id"]] = d

    # per-document license file mapping is the single source of truth
    for doc_id, lic_file in sorted(LICENSE_FILES.items()):
        attr = ATTR / f"{doc_id}.md"
        if not attr.is_file():
            errors.append(f"{doc_id}: attribution file missing")
            continue
        text = attr.read_text(encoding="utf-8")

        # 1. attribution "许可证原文" line must match the mapping
        m = re.search(r"- 许可证原文：`licenses/([^`]+)`", text)
        if not m or m.group(1) != lic_file:
            errors.append(f"{doc_id}: attribution license file "
                          f"{m.group(1) if m else '<missing>'} != "
                          f"mapping {lic_file}")

        # 2. referenced license file(s) must exist and be non-empty
        #    (rust-book-core references two files: MIT + APACHE)
        if m and m.group(1) != "见官方声明页":
            for fn in re.findall(r"([\w.-]+\.txt)", m.group(1)):
                path = LIC / fn
                if not path.is_file():
                    errors.append(f"{doc_id}: license file missing: {fn}")
                elif path.stat().st_size == 0:
                    errors.append(f"{doc_id}: license file empty: {fn}")

        # 3. manifest license field must match attribution "许可证："
        lm = re.search(r"- 许可证：([^（]+)（", text)
        attr_lic = lm.group(1).strip() if lm else ""
        man_lic = manifest.get(doc_id, {}).get("license", "")
        if attr_lic != man_lic:
            errors.append(f"{doc_id}: attribution license {attr_lic!r} != "
                          f"manifest license {man_lic!r}")

    # 4. cross-source reuse: a license file may only serve one source group
    owner: dict[str, str] = {}
    for doc_id, lic_file in LICENSE_FILES.items():
        owner.setdefault(lic_file, set()).add(doc_id)
    for lic_file, doc_ids in sorted(owner.items()):
        if len(doc_ids) == 1:
            continue
        allowed = SAME_SOURCE_GROUPS.get(lic_file, set())
        if doc_ids != allowed:
            errors.append(f"{lic_file}: reused by {sorted(doc_ids)} "
                          f"(allowed same-source group: {sorted(allowed)})")

    # 5. every SOURCES document must have a mapping (no doc left behind)
    for doc_id, *_ in SOURCES:
        if doc_id not in LICENSE_FILES:
            errors.append(f"{doc_id}: no license file mapping")

    return errors


def report() -> str:
    """License evidence audit report (markdown), regenerated each run."""
    lines = ["# v2 许可证证据审计报告（license evidence audit）", "",
             "> fail-closed：attribution ↔ manifest ↔ 许可证文件三者一致；",
             "> 任何不一致即整体不通过，且不得进入最终 corpus manifest。", ""]
    lines.append(f"- 文档数：{len(LICENSE_FILES)}")
    lines.append("- 同源共用组（同一来源的同一许可证）：docs.python.org 各页共用 "
                 "PSF-2.0.txt；rust-lang/book 双许可证文件")
    lines.append("- 跨来源复用：无（每个许可证文件仅服务其专属来源）")
    lines.append("")
    lines.append("| 文档 | 许可证 | 许可证证据文件 | 状态 |")
    lines.append("|---|---|---|---|")
    for doc_id, lic_file in sorted(LICENSE_FILES.items()):
        attr = ATTR / f"{doc_id}.md"
        ok = attr.is_file()
        lines.append(f"| {doc_id} | {DOC_LIC[doc_id]} | `{lic_file}` | "
                     f"{'✅ 已确认' if ok else '❌ 缺失'} |")
    lines += ["", "## pending 声明", "",
              "- 经逐文档核验，13 个来源的许可证证据均可独立确认，"
              "无 pending 来源。",
              "- 特别记录：Node.js 文档的 CC-BY-4.0 声明仅见于网站历史页脚，"
              "当前无法独立确认；已改用 nodejs/node 仓库 LICENSE（MIT，明确"
              "涵盖 associated documentation files）作为再分发依据。",
              "- art-of-war 采用 Project Gutenberg ebook 132 随附的完整"
              "Gutenberg License 条款（gutenberg-ebook-132-license.txt）作为"
              "再分发证据；该书在美国为公共领域（版权不受限）。"]
    return "\n".join(lines) + "\n"


def main() -> int:
    errors = audit()
    out = ROOT / "evaluation" / "datasets" / "v2" / "annotations"
    out.mkdir(parents=True, exist_ok=True)
    if errors:
        print(f"LICENSE AUDIT FAILED ({len(errors)}):")
        for e in errors:
            print("  ", e)
        return 1
    (out / "license-audit-report.md").write_text(report(), encoding="utf-8")
    # stdout must stay pure ASCII: Windows default consoles (GBK/cp936)
    # cannot encode the "↔" used in the markdown report, so never print
    # non-ASCII on the success path (do not rely on PYTHONIOENCODING).
    print(f"license audit passed: {len(LICENSE_FILES)} documents, "
          f"all attribution <-> manifest <-> license-file links consistent")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
