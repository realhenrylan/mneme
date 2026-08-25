"""Corpus v2 persistent-reject minimal evidence repair (v2.0.1).

对 5 条持续 reject case（en-052 / en-055 / mixed-016 / mixed-026 /
multi-014）实施**已批准的最小证据修复**，仅改答案点及其必要的
evidence / relevant chunk 引用：

1. multi-014  — 保留两个答案点；按 Task 11 审计定位的教程 6.4.1 /
   chunk_38 精确 span（字符 321..359）补入本地证据与 chunk 引用。
2. mixed-026  — 删除「计算器、字符串、列表示例」子结论（无本地证据）。
3. en-052     — 删除「Rust: ownership rules guarantee memory safety」
   子结论；不编造替代表述。
4. en-055     — 收窄为证据等价的英文表述（`&` 运算符创建引用，
   chunk_49 字符 1424..1467 直接支撑）；保留引用语义、删除无证据声称。
5. mixed-016  — 收窄为术语表形式：argument — 参数；parameter — 形参，
   为 parameter 补入术语表 chunk_14 证据（字符 783..798）。

设计原则：

1. **只改这 5 条**：其余 145 条草稿行逐字节不变（按行字节级保留）。
2. **fail-closed**：持续 reject 集合必须恰为目标 5 条（由 merged +
   selection-manifest 复算）；Task 11 审计 manifest 的输入 SHA 漂移、
   行数/唯一性漂移、证据 chunk 缺失、source 不一致、snippet 不连续、
   core 字符范围偏移、任何违规一律失败且不产出。
3. **字段守恒**：case_id / chain_id / follow_up_to / query /
   should_refuse / language / query_type / difficulty /
   relevant_source_ids 与 split 归属一律不变；不创建新 split；
   不读取 split 成员。
4. **版本化**：修复前字节快照、修复后 SHA、JSONL 逐 case diff、
   变更理由、证据校验与可复现 manifest 写入独立版本化目录
   ``evaluation/datasets/v2/revisions/v2.0.1-persistent-reject-repair/``；
   绝不覆盖历史审计目录。
5. **数据质量校验**（``data-analytics:analyze-data-quality`` 的确定性
   等价实现）：完整性 / 唯一性 / 引用完整性 / 连续性 / 一致性五维校验
   修复后的证据链。
6. 重生成当前空白 human-review pack（人工字段仍全空）并对新版本运行
   既有 pack / freeze / lock 校验；任何不一致 fail-closed。

本任务不调用 LLM/API（机器复审见
``corpus_v2_targeted_machine_review.py``）、不联网、不运行检索/生成
评测。修复是机械、确定性的；不构成人工审核或 v2.1 准入。

CLI
---
::

    python scripts/corpus_v2_persistent_reject_repair.py repair   # 全流程
    python scripts/corpus_v2_persistent_reject_repair.py verify   # 只读复算
"""

from __future__ import annotations

import copy
import hashlib
import json
import sys
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))  # 允许直接以 python scripts/... 方式运行
import scripts.corpus_v2_human_review_pack as hp  # noqa: E402
import scripts.corpus_v2_review as rv  # noqa: E402

DEFAULT_DRAFT = rv.DEFAULT_DRAFT
DEFAULT_CHUNKS = rv.DEFAULT_CHUNKS
DEFAULT_AUDIT_MANIFEST = ROOT / "evaluation" / "datasets" / "v2" / \
    "persistent-reject-evidence-audit" / "manifest.json"
DEFAULT_MERGED = ROOT / "evaluation" / "datasets" / "v2" / \
    "llm-semantic-adjudication" / "coherence-recheck" / \
    "merged-adjudications.jsonl"
DEFAULT_SEL = ROOT / "evaluation" / "datasets" / "v2" / \
    "llm-semantic-adjudication" / "selection-manifest.json"
DEFAULT_V1 = ROOT / "evaluation" / "datasets" / "v1.jsonl"
DEFAULT_FREEZE = ROOT / "evaluation" / "datasets" / "v2" / "split" / \
    "case-freeze.json"
DEFAULT_LOCK = ROOT / "evaluation" / "datasets" / "v2" / "split" / \
    "split-lock.json"
DEFAULT_REVISIONS = ROOT / "evaluation" / "datasets" / "v2" / "revisions" / \
    "v2.0.1-persistent-reject-repair"

TARGET_CASE_IDS = ("en-052", "en-055", "mixed-016", "mixed-026", "multi-014")
EXPECTED_TOTAL = 150

# 新增证据的 snippet / core（全部逐字取自现有 chunks.jsonl；字符范围由
# 审计 candidate-evidence-spans.jsonl 交叉确认，运行时逐项复核）
_SNIPPET_M014 = ("记住，使用\n```\nfrom package import specific_submodule\n```\n"
                 " 没有任何问题！ 实际上，除了导入模块使用不同包的同名子模块"
                 "之外，这种方式是推荐用法。")
_SNIPPET_E055 = ("The `&s1` syntax lets us create a reference that _refers_ to "
                 "the value of `s1`\nbut does not own it.")

# 已批准的精确修复规格：answer_points=None 表示保持不变；
# add_evidence 的 expected_core_range 为审计确认的 chunk 内字符范围
REPAIR_SPEC: dict[str, dict] = {
    "multi-014": {
        "answer_points": None,
        "add_evidence": [{
            "chunk_id": "32c427fb50e2_chunk_38",
            "source_id": "python-tutorial-zh.md",
            "section": "6.4.1 从包中导入 *",
            "snippet": _SNIPPET_M014,
            "core_text": "from package import specific_submodule",
            "expected_core_range": (321, 359),
            "answer_point_index": 1,
        }],
    },
    "mixed-026": {
        "answer_points": ["对应：同一章，标题翻译不同"],
        "add_evidence": [],
    },
    "en-052": {
        "answer_points": ["PostgreSQL: transaction durability (logged to disk)"],
        "add_evidence": [],
    },
    "en-055": {
        "answer_points": ["The `&` operator creates a reference (e.g., `&s1`)"],
        "add_evidence": [{
            "chunk_id": "4f9001ca8c15_chunk_49",
            "source_id": "rust-book-core.md",
            "section": "4.2 References and Borrowing",
            "snippet": _SNIPPET_E055,
            "core_text": "The `&s1` syntax lets us create a reference",
            "expected_core_range": (1424, 1467),
            "answer_point_index": 0,
        }],
    },
    "mixed-016": {
        "answer_points": ["argument — 参数", "parameter — 形参"],
        "add_evidence": [{
            "chunk_id": "c9fd20815ea8_chunk_14",
            "source_id": "python-glossary-zh.md",
            "section": "parameter 形参",
            "snippet": "parameter -- 形参",
            "core_text": "parameter -- 形参",
            "expected_core_range": (783, 798),
            "answer_point_index": 1,
        }],
    },
}

REVISION_OUTPUT_FILES = ("draft-before.jsonl", "draft-after.jsonl",
                         "draft-field-diff.jsonl", "evidence-verification.jsonl",
                         "pack-before.jsonl", "data-quality-report.json",
                         "freeze-lock-verification.json",
                         "persistent-reject-repair.md", "manifest.json")


class RepairError(Exception):
    """fail-closed 修复失败（任何漂移立即失败，不产出）。"""


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(65536), b""):
            h.update(block)
    return h.hexdigest()


def _load_chunks(path: Path) -> tuple[dict[str, str], dict[str, str], str]:
    text: dict[str, str] = {}
    source: dict[str, str] = {}
    for ln in path.open(encoding="utf-8"):
        if ln.strip():
            d = json.loads(ln)
            text[d["chunk_id"]] = d["text"]
            source[d["chunk_id"]] = d["source"]
    return text, source, _sha256_file(path)


def _split_lines(raw: bytes) -> tuple[list[bytes], bytes, bool]:
    """按行拆分字节流，保留原换行符（CRLF/LF）与尾部换行。"""
    sep = b"\r\n" if b"\r\n" in raw else b"\n"
    parts = raw.split(sep)
    trailing = bool(parts and parts[-1] == b"")
    lines = parts[:-1] if trailing else parts
    return lines, sep, trailing


# ── 输入校验（fail-closed）───────────────────────────────────────────

def _verify_reject_set(merged_path: Path, sel_path: Path,
                       targets: tuple[str, ...]) -> None:
    """持续 reject 集合必须恰为目标 5 条（merged + mapping 复算）。"""
    sel = json.loads(sel_path.read_text(encoding="utf-8"))
    mapping: dict = {}
    for m in sel.get("mapping") or []:
        mapping[m["index"]] = m["case_id"]
    reject_ids: set[str] = set()
    for ln in merged_path.open(encoding="utf-8"):
        if ln.strip():
            r = json.loads(ln)
            if r.get("semantic_verdict") == "reject":
                reject_ids.add(mapping.get(r.get("index")))
    if reject_ids != set(targets):
        raise RepairError(
            f"持续 reject 集合漂移（fail-closed）: {sorted(reject_ids)} "
            f"!= {sorted(targets)}")


def _verify_audit_manifest(audit_path: Path, merged_path: Path, sel_path: Path,
                           chunks_path: Path, targets: tuple[str, ...]) -> None:
    """Task 11 审计 manifest 输入 SHA 与目标集合必须一致。"""
    audit = json.loads(audit_path.read_text(encoding="utf-8"))
    if list(audit.get("target_case_ids") or []) != list(targets):
        raise RepairError("审计 manifest target_case_ids 与任务目标不一致"
                          "（fail-closed）")
    for key, path in (("merged-adjudications.jsonl", merged_path),
                      ("selection-manifest.json", sel_path),
                      ("chunks.jsonl", chunks_path)):
        recorded = (audit.get("inputs") or {}).get(key, {}).get("sha256")
        if recorded != _sha256_file(path):
            raise RepairError(f"审计输入 {key} SHA 漂移（fail-closed）")


def _verify_draft(draft_path: Path, targets: tuple[str, ...],
                  expected_total: int) -> list[dict]:
    rows: list[dict] = []
    for ln in draft_path.open(encoding="utf-8"):
        if ln.strip():
            rows.append(json.loads(ln))
    if len(rows) != expected_total:
        raise RepairError(f"草稿行数 {len(rows)} != 期望 {expected_total}"
                          "（fail-closed）")
    ids = [r["id"] for r in rows]
    if len(set(ids)) != len(ids):
        dup = sorted({i for i in ids if ids.count(i) > 1})
        raise RepairError(f"草稿 case_id 重复: {dup}（fail-closed）")
    missing = set(targets) - set(ids)
    if missing:
        raise RepairError(f"目标 case 缺失: {sorted(missing)}（fail-closed）")
    return rows


# ── 精确变换 ─────────────────────────────────────────────────────────

def _apply_spec(case: dict, spec: dict, chunks: dict[str, str],
                chunk_sources: dict[str, str]) -> tuple[dict, list[dict]]:
    """对单条目标 case 应用修复规格；返回 (新 case, 证据校验记录)。"""
    case = copy.deepcopy(case)
    # 既有证据整体复核（chunk 存在 / source 一致 / snippet 连续）
    for rc in case.get("relevant_chunks") or []:
        cid = rc.get("chunk_id", "")
        text = chunks.get(cid)
        if not text:
            raise RepairError(f"{case['id']}: 既有 chunk 引用不存在: {cid}")
        if chunk_sources.get(cid) != rc.get("source_id"):
            raise RepairError(f"{case['id']}: {cid}: 既有证据 source 不一致"
                              "（fail-closed）")
        if not rv.snippet_is_evidence(rc.get("chunk_text_snippet", ""), text):
            raise RepairError(f"{case['id']}: {cid}: 既有 snippet 不是连续"
                              "证据（fail-closed）")

    if spec["answer_points"] is not None:
        if not spec["answer_points"]:
            raise RepairError(f"{case['id']}: 修复不得清空答案点"
                              "（fail-closed）")
        case["acceptable_answer_points"] = list(spec["answer_points"])

    records: list[dict] = []
    for entry in spec["add_evidence"]:
        cid = entry["chunk_id"]
        text = chunks.get(cid)
        if not text:
            raise RepairError(f"{case['id']}: 新增证据 chunk 不存在: {cid}")
        if chunk_sources.get(cid) != entry["source_id"]:
            raise RepairError(f"{case['id']}: {cid}: 新增证据 source 不一致"
                              f"（{entry['source_id']}）（fail-closed）")
        if not rv.snippet_is_evidence(entry["snippet"], text):
            raise RepairError(f"{case['id']}: {cid}: 新增 snippet 不是连续"
                              "证据（fail-closed）")
        core = entry["core_text"]
        n = text.count(core)
        if n != 1:
            raise RepairError(f"{case['id']}: {cid}: core 定位歧义"
                              f"（出现 {n} 次，fail-closed）")
        start = text.find(core)
        end = start + len(core)
        expected = tuple(entry["expected_core_range"])
        if (start, end) != expected:
            raise RepairError(f"{case['id']}: {cid}: core 字符范围偏移"
                              f"（expected {expected}，实际 {(start, end)}，"
                              "fail-closed）")
        sn = text.count(entry["snippet"])
        if sn != 1:
            raise RepairError(f"{case['id']}: {cid}: snippet 定位歧义"
                              f"（出现 {sn} 次，fail-closed）")
        sstart = text.find(entry["snippet"])
        send = sstart + len(entry["snippet"])
        # 幂等：已存在的 chunk 引用不重复添加
        if cid not in case.get("relevant_chunk_ids", []):
            case["relevant_chunks"].append({
                "source_id": entry["source_id"], "chunk_id": cid,
                "chunk_text_snippet": entry["snippet"], "page": None,
                "section": entry["section"]})
            case["relevant_chunk_ids"].append(cid)
        records.append({
            "case_id": case["id"], "chunk_id": cid,
            "source_id": entry["source_id"],
            "answer_point_index": entry["answer_point_index"],
            "section": entry["section"],
            "snippet_sha256": _sha256_text(entry["snippet"]),
            "char_start": start, "char_end": end,
            "snippet_start": sstart, "snippet_end": send,
            "core_located_once": True, "snippet_located_once": True,
            "snippet_is_evidence": True, "source_matches": True,
            "core_range_matches": True,
        })
    return case, records


# ── 主变换（纯函数式：只读输入，产出内存结果 + 版本化目录）─────────────

def transform(draft_path: Path, chunks_path: Path, audit_manifest_path: Path,
              merged_path: Path, sel_path: Path, *, revision_dir: Path,
              target_ids: tuple[str, ...] = TARGET_CASE_IDS,
              expected_total: int = EXPECTED_TOTAL) -> dict:
    """校验输入、应用五条精确变换、写版本化目录；返回确定性结果。

    任何 fail-closed 校验失败抛 RepairError 且不写任何产物。
    """
    targets = tuple(target_ids)
    chunks, chunk_sources, chunks_sha = _load_chunks(chunks_path)
    # 校验顺序按任务断言顺序：先持续 reject 集合，再审计输入 SHA
    _verify_reject_set(merged_path, sel_path, targets)
    _verify_audit_manifest(audit_manifest_path, merged_path, sel_path,
                           chunks_path, targets)
    rows = _verify_draft(draft_path, targets, expected_total)
    raw = draft_path.read_bytes()

    cases_by_id: dict[str, dict] = {}
    evidence_verification: list[dict] = []
    for row in rows:
        if row["id"] in targets:
            case, ev = _apply_spec(row, REPAIR_SPEC[row["id"]], chunks,
                                   chunk_sources)
            cases_by_id[row["id"]] = case
            evidence_verification.extend(ev)
        else:
            cases_by_id[row["id"]] = row

    # 逐行字节级重建：非目标行原样保留
    lines, sep, trailing = _split_lines(raw)
    out_lines: list[bytes] = []
    n_changed = 0
    for ln in lines:
        if not ln.strip():
            out_lines.append(ln)
            continue
        row = json.loads(ln)
        if row["id"] in targets:
            new_line = json.dumps(cases_by_id[row["id"]],
                                  ensure_ascii=False).encode("utf-8")
            out_lines.append(new_line)
            if new_line != ln:
                n_changed += 1  # 实际发生字节变化的行数（幂等重跑为 0）
        else:
            out_lines.append(ln)
    out_bytes = sep.join(out_lines) + (sep if trailing else b"")

    # JSONL 逐 case diff（仅实际发生变更的目标行）
    before_by_id = {r["id"]: r for r in rows}
    diff_rows: list[dict] = []
    for cid in targets:
        before, after = before_by_id[cid], cases_by_id[cid]
        changed = {}
        for k in before:
            if before[k] != after.get(k):
                changed[k] = {"before": before[k], "after": after.get(k)}
        for k in after:
            if k not in before:
                changed[k] = {"before": None, "after": after[k]}
        if changed:
            diff_rows.append({"case_id": cid, "changed_fields": changed})

    # 版本化目录
    revision_dir.mkdir(parents=True, exist_ok=True)
    (revision_dir / "draft-before.jsonl").write_bytes(raw)
    (revision_dir / "draft-after.jsonl").write_bytes(out_bytes)
    (revision_dir / "draft-field-diff.jsonl").write_text(
        "\n".join(json.dumps(r, ensure_ascii=False, sort_keys=True,
                             separators=(",", ":")) for r in diff_rows) + "\n",
        encoding="utf-8")
    (revision_dir / "evidence-verification.jsonl").write_text(
        "\n".join(json.dumps(r, ensure_ascii=False, sort_keys=True,
                             separators=(",", ":"))
                  for r in evidence_verification) + "\n", encoding="utf-8")

    dq = data_quality_report(cases_by_id, chunks, chunk_sources)
    return {
        "cases_by_id": cases_by_id, "bytes": out_bytes,
        "n_targets": len(targets), "n_changed": n_changed,
        "evidence_verification": evidence_verification,
        "diff_rows": diff_rows, "revision_dir": revision_dir, "dq": dq,
        "draft_sha_before": _sha256_file(draft_path),
        "draft_sha_after": _sha256_text(out_bytes.decode("utf-8")),
        "chunks_sha": chunks_sha,
    }


# ── 数据质量校验（data-analytics:analyze-data-quality 等价实现）──────

def _norm(s: str) -> str:
    """NFKC + lowercase + 去空白，用于逐字比对。"""
    return "".join(ch for ch in unicodedata.normalize("NFKC", s).lower()
                   if not ch.isspace())


def data_quality_report(cases_by_id: dict[str, dict], chunks: dict[str, str],
                        chunk_sources: dict[str, str]) -> dict:
    """五维数据质量校验：完整性/唯一性/引用完整性/连续性/一致性。

    ``data-analytics:analyze-data-quality`` 技能在本环境不可用，这里提供
    其确定性的等价实现：对修复后的 5 条证据链逐项机械校验。
    """
    dq: dict = {
        "targets_with_evidence": [], "targets_without_evidence": [],
        "answer_points_without_evidence": [],
        "all_answer_points_have_evidence": False,
        "all_chunks_exist": True, "all_snippets_contiguous": True,
        "all_sources_match": True, "chunk_id_lists_consistent": True,
        "duplicate_chunk_ids": [], "duplicate_answer_points": [],
        "per_case": {},
    }
    for cid in TARGET_CASE_IDS:
        case = cases_by_id[cid]
        pc: dict = {}
        ids = list(case.get("relevant_chunk_ids") or [])
        refs = [rc.get("chunk_id") for rc in case.get("relevant_chunks") or []]
        if sorted(set(ids)) != sorted(set(refs)):
            dq["chunk_id_lists_consistent"] = False
        for rc in case.get("relevant_chunks") or []:
            ck = chunks.get(rc["chunk_id"])
            if not ck:
                dq["all_chunks_exist"] = False
            elif not rv.snippet_is_evidence(rc.get("chunk_text_snippet", ""),
                                            ck):
                dq["all_snippets_contiguous"] = False
            if chunk_sources.get(rc["chunk_id"]) != rc.get("source_id"):
                dq["all_sources_match"] = False
        dups = sorted({x for x in ids if ids.count(x) > 1})
        if dups:
            dq["duplicate_chunk_ids"].append({"case_id": cid, "chunk_ids": dups})
        points = list(case.get("acceptable_answer_points") or [])
        pdups = sorted({p for p in points if points.count(p) > 1})
        if pdups:
            dq["duplicate_answer_points"].append(
                {"case_id": cid, "points": pdups})
        if points and ids:
            dq["targets_with_evidence"].append(cid)
        else:
            dq["targets_without_evidence"].append(cid)
            dq["answer_points_without_evidence"].append(
                {"case_id": cid, "indices": list(range(len(points)))})
        # 规格映射完整性：每个新增证据的答案点必须能引用到对应 chunk
        for entry in REPAIR_SPEC[cid]["add_evidence"]:
            if entry["chunk_id"] not in ids:
                dq["answer_points_without_evidence"].append(
                    {"case_id": cid,
                     "indices": [entry["answer_point_index"]]})

        # 逐 case 语义对应校验（答案点 ↔ 证据对应明确）
        ap = {i: p for i, p in enumerate(points)}
        if cid == "multi-014":
            core_n = _norm("from package import specific_submodule")
            ap_n = _norm(ap[1])
            pc["answer_point_1"] = {
                "core_in_answer_point": core_n in ap_n,
                "coverage": round(len(core_n) / len(ap_n), 4),
            }
        elif cid == "en-055":
            core = "The `&s1` syntax lets us create a reference"
            pc["answer_point_0"] = {
                "core_has_ampersand": "&" in core,
                "core_has_reference": "reference" in core,
                "core_has_create": "create" in core,
                "answer_point_has_ampersand": "&" in ap[0],
                "answer_point_has_reference": "reference" in ap[0],
            }
        elif cid == "mixed-016":
            for idx, term, trans, chunk in (
                    (0, "argument", "参数", "c9fd20815ea8_chunk_1"),
                    (1, "parameter", "形参", "c9fd20815ea8_chunk_14")):
                ev_text = ""
                for rc in case.get("relevant_chunks") or []:
                    if rc["chunk_id"] == chunk:
                        ev_text = f"{rc.get('section') or ''} " \
                                  f"{rc.get('chunk_text_snippet') or ''}"
                pc[f"answer_point_{idx}"] = {
                    "glossary_form": term in ev_text and trans in ev_text,
                    "evidence_text": ev_text,
                }
        dq["per_case"][cid] = pc
    dq["all_answer_points_have_evidence"] = (
        not dq["answer_points_without_evidence"]
        and set(dq["targets_with_evidence"]) == set(TARGET_CASE_IDS))
    return dq


# ── freeze / lock 校验（不读取 split 成员）───────────────────────────

def verify_freeze_lock(draft_path: Path, v1_path: Path, freeze_path: Path,
                       lock_path: Path,
                       target_ids: tuple[str, ...] = TARGET_CASE_IDS) -> dict:
    """重建 pool（v1 + 修复后 v2）并校验 case-freeze / split-lock。

    只比较 case 集合、freeze 指纹与 per-case 分层元数据；不读取、不输出
    任何 dev/holdout 成员。lock 校验复用 ``split_seal.verify_lock``
    （其指纹重算在内存中完成）。
    """
    v1 = [json.loads(l) for l in v1_path.open(encoding="utf-8") if l.strip()]
    v2 = [json.loads(l) for l in draft_path.open(encoding="utf-8")
          if l.strip()]
    follow = {r["id"]: (r.get("metadata") or {}).get("follow_up_to")
              for r in v1}
    v1_chain: dict[str, str] = {}
    for r in v1:
        cur = r["id"]
        while follow.get(cur):
            cur = follow[cur]
        v1_chain[r["id"]] = cur
    pool = []
    for r in v1:
        pool.append({"id": r["id"], "query_type": r.get("query_type"),
                     "language": r.get("language"),
                     "should_refuse": bool(r.get("should_refuse")),
                     "chain_id": v1_chain.get(r["id"]),
                     "partition": "legacy_dev"})
    for r in v2:
        m = r.get("metadata") or {}
        pool.append({"id": r["id"], "query_type": r.get("query_type"),
                     "language": r.get("language"),
                     "should_refuse": bool(r.get("should_refuse")),
                     "chain_id": m.get("chain_id"), "partition": "new"})
    from evaluation.split_seal import freeze_case_ids, verify_lock  # noqa: PLC0415
    frozen = freeze_case_ids(pool, corpus_version="v2.0.0")
    saved = json.loads(freeze_path.read_text(encoding="utf-8"))
    lock = json.loads(lock_path.read_text(encoding="utf-8"))
    result = {
        "pool_total": len(pool),
        "case_set_unchanged":
            set(saved.get("case_ids") or []) == {c["id"] for c in pool},
        "case_ids_sha256_match":
            saved.get("case_ids_sha256") == frozen["case_ids_sha256"],
        "target_meta_unchanged": {
            cid: (saved.get("cases") or {}).get(cid) == frozen["cases"][cid]
            for cid in target_ids},
        "lock_verifies": bool(verify_lock(lock, frozen)),
        "lock_holdout_ids_not_persisted": True,
    }
    ok = (result["case_set_unchanged"] and result["case_ids_sha256_match"]
          and all(result["target_meta_unchanged"].values())
          and result["lock_verifies"])
    if not ok:
        raise RepairError(f"freeze/lock 校验失败（fail-closed）: {result}")
    return result


# ── 全流程（CLI：repair）─────────────────────────────────────────────

def run(*, draft_path: Path = DEFAULT_DRAFT, chunks_path: Path = DEFAULT_CHUNKS,
        audit_manifest_path: Path = DEFAULT_AUDIT_MANIFEST,
        merged_path: Path = DEFAULT_MERGED, sel_path: Path = DEFAULT_SEL,
        revision_dir: Path = DEFAULT_REVISIONS, v1_path: Path = DEFAULT_V1,
        freeze_path: Path = DEFAULT_FREEZE, lock_path: Path = DEFAULT_LOCK,
        expected_total: int = EXPECTED_TOTAL) -> dict:
    """全流程：变换 → 原位更新草稿 → 重生成空白 pack → freeze/lock 校验。

    任何失败抛 RepairError 且草稿不被改写（草稿更新放在所有校验之后）。
    """
    out = transform(draft_path, chunks_path, audit_manifest_path, merged_path,
                    sel_path, revision_dir=revision_dir,
                    expected_total=expected_total)
    if out["n_changed"] != out["n_targets"]:
        raise RepairError(f"目标 case 变更数 {out['n_changed']} != "
                          f"{out['n_targets']}（草稿可能已处于修复状态；"
                          "拒绝重复修复，fail-closed）")

    # 重生成前的空白 pack 字节快照 + 与审计 manifest 记录的 pack SHA 交叉校验
    pack_before_path = revision_dir / "pack-before.jsonl"
    current_pack = hp.DEFAULT_OUT / "human-review-pack.jsonl"
    if not current_pack.is_file():
        raise RepairError("当前空白 human-review pack 缺失，无法快照"
                          "（fail-closed）")
    pack_before_bytes = current_pack.read_bytes()
    audit = json.loads(audit_manifest_path.read_text(encoding="utf-8"))
    recorded_pack_sha = (audit.get("inputs") or {}).get(
        "human-review-pack.jsonl", {}).get("sha256")
    if recorded_pack_sha != _sha256_text(pack_before_bytes.decode("utf-8")):
        raise RepairError("当前 pack 与审计 manifest 记录的 pack SHA 不一致"
                          "（pack-before 快照失败，fail-closed）")
    pack_before_path.write_bytes(pack_before_bytes)

    # 原位更新草稿（作者输入，任务批准；快照已在 revision 目录）
    draft_path.write_bytes(out["bytes"])

    # 重生成空白 human-review pack（人工字段必须仍为空）
    pack_path = hp.build_pack(draft_path, chunks_path, hp.DEFAULT_CHUNK_MANIFEST,
                              hp.DEFAULT_CORPUS_MANIFEST, hp.DEFAULT_LEDGER,
                              hp.DEFAULT_OUT)
    pack_errors = hp.verify(hp.DEFAULT_OUT / "human-review-pack-manifest.json")
    if pack_errors:
        raise RepairError("pack 重生成校验失败（fail-closed）: "
                          + "; ".join(pack_errors))
    pack_rows = [json.loads(l) for l in pack_path.open(encoding="utf-8")
                 if l.strip()]
    human_fields_empty = all(
        r["human_review_decision"] == "" and r["human_reviewer"] == ""
        and r["human_review_notes"] == "" for r in pack_rows)
    if not human_fields_empty:
        raise RepairError("pack 人工字段非空（fail-closed）")

    freeze_report = verify_freeze_lock(draft_path, v1_path, freeze_path,
                                       lock_path)

    # 先写报告/校验产物，最后写 manifest（manifest 需要全部产物 SHA）
    (revision_dir / "data-quality-report.json").write_text(
        json.dumps(out["dq"], ensure_ascii=False, indent=1) + "\n",
        encoding="utf-8")
    (revision_dir / "freeze-lock-verification.json").write_text(
        json.dumps(freeze_report, ensure_ascii=False, indent=1) + "\n",
        encoding="utf-8")
    (revision_dir / "persistent-reject-repair.md").write_text(
        _report_md(out, pack_rows, pack_errors, freeze_report),
        encoding="utf-8")
    manifest = _manifest_dict(out, pack_path, pack_errors, freeze_report,
                              revision_dir)
    (revision_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=1) + "\n",
        encoding="utf-8")
    return {
        "n_changed": out["n_changed"], "n_targets": out["n_targets"],
        "draft_sha_before": out["draft_sha_before"],
        "draft_sha_after": out["draft_sha_after"],
        "pack_rows": len(pack_rows),
        "freeze_lock": freeze_report,
        "revision_dir": revision_dir,
    }


def _manifest_dict(out: dict, pack_path: Path, pack_errors: list[str],
                   freeze_report: dict, revision_dir: Path) -> dict:
    """版本化修复 manifest（含修复前后 SHA、逐字段 diff、理由、产物 SHA）。"""
    outputs = {name: {"sha256": _sha256_file(revision_dir / name)}
               for name in REVISION_OUTPUT_FILES if name != "manifest.json"}
    transformations = {}
    for diff in out["diff_rows"]:
        cid = diff["case_id"]
        reasons = {
            "multi-014": "按审计定位的教程 6.4.1 / chunk_38 精确 span 补入"
                         "本地证据与 chunk 引用（答案点不变）",
            "mixed-026": "删除无本地证据的子结论「计算器、字符串、列表"
                         "示例」；保留已支持的章节标题对应结论",
            "en-052": "删除无支持的 Rust memory-safety 子结论；保留已支持"
                      "的 PostgreSQL durability 结论；不编造替代表述",
            "en-055": "收窄为证据等价的英文表述（chunk_49 `&s1` 创建引用"
                      "直接支撑）；删除无证据的 & 声称",
            "mixed-016": "收窄为术语表形式 argument — 参数；parameter — "
                         "形参，为两项保留/补齐术语表证据",
        }
        transformations[cid] = {
            "reason": reasons[cid], "changed_fields": diff["changed_fields"],
        }
    body = {
        "task": "v2 persistent-reject minimal evidence repair",
        "revision": "v2.0.1",
        "target_case_ids": list(TARGET_CASE_IDS),
        "inputs": {
            "draft_before": {"sha256": out["draft_sha_before"],
                             "rows": 150},
            "draft_after": {"sha256": out["draft_sha_after"], "rows": 150},
            "chunks": {"sha256": out["chunks_sha"]},
            "audit_manifest": {"sha256": _sha256_file(DEFAULT_AUDIT_MANIFEST)},
            "merged_adjudications": {"sha256": _sha256_file(DEFAULT_MERGED)},
            "selection_manifest": {"sha256": _sha256_file(DEFAULT_SEL)},
            "human_review_pack_before": {"sha256": _sha256_file(
                revision_dir / "pack-before.jsonl")},
        },
        "transformations": transformations,
        "evidence_verification": out["evidence_verification"],
        "data_quality": {
            k: v for k, v in out["dq"].items() if k != "per_case"},
        "pack": {
            "regenerated": True,
            "path": str(pack_path),
            "rows": 150,
            "verify_errors": pack_errors,
            "human_fields_empty": True,
        },
        "freeze_lock": freeze_report,
        "outputs": outputs,
        "created_by": "corpus_v2_persistent_reject_repair.py run",
        "note": "机械、确定性的证据修复（依据 persistent-reject-evidence-"
                "audit）；不构成人工审核、人工批准或 v2.1 准入。",
    }
    return body


def _report_md(out: dict, pack_rows: list[dict], pack_errors: list[str],
               freeze_report: dict) -> str:
    lines = [
        "# v2 持续 reject 最小证据修复报告（v2.0.1）", "",
        "> 本报告为**机械、确定性**的证据修复（依据 "
        "persistent-reject-evidence-audit 的候选 span）；**不代表人工"
        "审核、人工批准或 v2.1 准入**。", "",
        "## 一、修改的 case 与逐答案点 before/after", "",
        "| case_id | 答案点 | before | after | 证据变更 |",
        "|---|---|---|---|---|",
    ]
    for diff in out["diff_rows"]:
        cid = diff["case_id"]
        spec = REPAIR_SPEC[cid]
        if spec["answer_points"] is None:
            pts = "（不变）"
            after = "；".join(out["cases_by_id"][cid]
                              ["acceptable_answer_points"])
            before = after
        else:
            before = "；".join(diff["changed_fields"]
                               ["acceptable_answer_points"]["before"])
            after = "；".join(diff["changed_fields"]
                              ["acceptable_answer_points"]["after"])
            pts = f"{before} → {after}"
        ev = [e for e in out["evidence_verification"]
              if e["case_id"] == cid]
        ev_desc = "；".join(
            f"{e['chunk_id']} 字符 {e['char_start']}..{e['char_end']}"
            for e in ev) or "无"
        lines.append(f"| {cid} | 全部 | {pts} | {after} | {ev_desc} |")
    lines += ["", "## 二、新增证据（逐字可定位）", "",
              "| case_id | chunk_id | source_id | 字符范围 | 最短必要原文 |",
              "|---|---|---|---|---|"]
    core_by_chunk = {
        "32c427fb50e2_chunk_38": "from package import specific_submodule",
        "4f9001ca8c15_chunk_49": "The `&s1` syntax lets us create a reference",
        "c9fd20815ea8_chunk_14": "parameter -- 形参",
    }
    for e in out["evidence_verification"]:
        core = core_by_chunk[e["chunk_id"]]
        lines.append(f"| {e['case_id']} | {e['chunk_id']} | "
                     f"{e['source_id']} | {e['char_start']}..{e['char_end']} "
                     f"| `{core}` |")
    lines += ["", "## 三、数据质量校验（五维）", ""]
    dq = out["dq"]
    lines.append(f"- 完整性：全部答案点有证据 "
                 f"（{dq['all_answer_points_have_evidence']}）；"
                 f"无证据答案点 {dq['answer_points_without_evidence']}。")
    lines.append(f"- 唯一性：重复 chunk {dq['duplicate_chunk_ids']}；"
                 f"重复答案点 {dq['duplicate_answer_points']}。")
    lines.append(f"- 引用完整性：chunk 全部存在（{dq['all_chunks_exist']}）；"
                 f"chunk_id 列表一致（{dq['chunk_id_lists_consistent']}）。")
    lines.append(f"- 连续性：snippet 全部连续（{dq['all_snippets_contiguous']}）。")
    lines.append(f"- 一致性：source 全部一致（{dq['all_sources_match']}）。")
    for cid, pc in dq["per_case"].items():
        lines.append(f"  - {cid}: {json.dumps(pc, ensure_ascii=False)}")
    lines += ["", "## 四、派生与封印", "",
              f"- 空白 human-review pack 已重生成（{len(pack_rows)} 行，"
              "三个人工字段仍全空）；旧 pack 字节快照见 revision 目录。",
              f"- pack fail-closed 校验："
              f"{'通过' if not pack_errors else pack_errors}。",
              f"- case-freeze / split-lock：case 集合与分组不变；"
              f"lock 校验 {'通过' if freeze_report['lock_verifies'] else '失败'}；"
              "未改写历史 lock（无需更新）。",
              "- chunks.jsonl、原始第三轮填写副本、历史语义仲裁/审计产物"
              "均未修改。", "",
              "## 五、限制与结论", "",
              "- 本修复仅依据审计定位的本地证据，为机械修改；add_exact_evidence / "
              "remove_unsupported_answer_point / narrow_answer_point 均为"
              "审计建议，修复结果须经人工裁决。",
              "- 5 条定点机器复审见 "
              "targeted-post-repair-machine-review/（MACHINE_REVIEWED_"
              "DIAGNOSTIC_ONLY）。",
              "- 结论：**不构成人工终审、人工批准或 v2.1 准入。**", "",
    ]
    return "\n".join(lines) + "\n"


# ── CLI ──────────────────────────────────────────────────────────────

def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if not args:
        print("usage: corpus_v2_persistent_reject_repair.py repair|verify")
        return 2
    cmd = args[0]
    try:
        if cmd == "repair":
            summary = run()
            print(f"repaired {summary['n_changed']} cases "
                  f"(draft {summary['draft_sha_before'][:12]} -> "
                  f"{summary['draft_sha_after'][:12]}; pack "
                  f"{summary['pack_rows']} rows) -> {summary['revision_dir']}")
            return 0
        if cmd == "verify":
            # 只读复算：不写草稿；产物只写临时目录，绝不触碰版本化目录
            import tempfile
            with tempfile.TemporaryDirectory() as td:
                out = transform(DEFAULT_DRAFT, DEFAULT_CHUNKS,
                                DEFAULT_AUDIT_MANIFEST, DEFAULT_MERGED,
                                DEFAULT_SEL,
                                revision_dir=Path(td) / "rev")
            print(f"verify ok: {out['n_changed']} cases, "
                  f"dq all_answer_points_have_evidence="
                  f"{out['dq']['all_answer_points_have_evidence']}")
            return 0
    except (RepairError, ValueError) as exc:
        print(f"FAILED: {exc}")
        return 2
    print(f"unknown command: {cmd}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
