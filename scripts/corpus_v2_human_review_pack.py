"""Corpus v2 human-review pack builder — blind, offline, fail-closed.

为 150 条 LLM_ASSISTED 草稿生成**人工终审包**：每条携带 query、
多轮上下文（previous_turns）、草稿标签（should_refuse /
relevance_level / acceptable_answer_points / relevant_source_ids）与
chunk 证据（source_id / chunk_id / 连续 snippet / section），另附三个
**必须留空**的人工填写字段（human_review_decision / human_reviewer /
human_review_notes）。设计原则：

1. **盲态**：包内**绝不包含**自动二审结论（decision/confidence/
   rationale）、审阅模型名、修复动作（repair action）、任何
   split/dev/holdout 身份、检索分数、候选集或历史评测结果——人工必须
   独立判断。行级键集合与证据键集合是严格白名单，多出任何键即失败。
2. **只读、不改写**：本脚本不修改草稿、chunks、语料 manifest、
   repair ledger、case-freeze、split-lock 或生产配置；manifest 只记录
   输入 SHA-256（哈希文件本身不输出任何文件内容）。
3. **确定性**：产物无时间戳、按 case_id 稳定排序；相同输入两次构建
   逐字节一致。
4. **fail-closed**：行数必须恰好 150、case_id 唯一且与草稿集合一致；
   answerable 的 chunk 证据必须存在于 chunks.jsonl 且 snippet 连续、
   source 一致；人工字段初始必须全部为空；manifest 输入 SHA 漂移、
   缺失 chunk、重复/遗漏 case、非法字段、任何 split 结构字段或出现
   ``HUMAN_APPROVED`` / ``reviewed-truth`` / "已完成人工审核" 字样
   一律失败并拒绝产出产物。

本任务**不调用任何 LLM/API**，不运行检索、生成评测、特征/阈值扫描；
禁止模型 ``gpt-5.6-sol``（本脚本根本不含任何模型调用路径）。

CLI
---
::

    python scripts/corpus_v2_human_review_pack.py build   # 生成终审包
    python scripts/corpus_v2_human_review_pack.py verify  # 重跑 fail-closed 校验

产物目录：evaluation/datasets/v2/human-review/
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))  # 允许直接以 python scripts/... 方式运行
import scripts.corpus_v2_review as rv  # noqa: E402

DEFAULT_DRAFT = rv.DEFAULT_DRAFT
DEFAULT_CHUNKS = rv.DEFAULT_CHUNKS
DEFAULT_CHUNK_MANIFEST = rv.DEFAULT_CHUNK_MANIFEST
DEFAULT_CORPUS_MANIFEST = ROOT / "evaluation" / "datasets" / "v2" / \
    "corpus-manifest.json"
DEFAULT_LEDGER = ROOT / "evaluation" / "datasets" / "v2" / "review" / \
    "repair-ledger.jsonl"
DEFAULT_OUT = ROOT / "evaluation" / "datasets" / "v2" / "human-review"

PACK_VERSION = 1
RELEVANCE_LEVELS = ("chunk", "source", "none")

# 行级严格白名单：只允许这些顶层键（含空白人工填写字段）
ALLOWED_KEYS = frozenset({
    "case_id", "query", "language", "query_type", "previous_turns",
    "should_refuse", "relevance_level", "acceptable_answer_points",
    "relevant_source_ids", "evidence",
    "human_review_decision", "human_reviewer", "human_review_notes",
})
# 证据条目白名单：source_id / chunk_id / 完整连续 snippet / section
EVIDENCE_KEYS = frozenset({"source_id", "chunk_id", "snippet", "section"})
HUMAN_FIELDS = ("human_review_decision", "human_reviewer",
                "human_review_notes")

# 输出中禁止出现的字样（终审包、manifest、报告、说明四类产物一律不出现）
FORBIDDEN_PHRASES = ("HUMAN_APPROVED", "reviewed-truth", "已完成人工审核")
# 任何自动审阅 / split / 评测结构字段名：以 JSON 键形态出现即失败
# （带引号 + 冒号，且排除转义引号，避免误伤查询文本中的普通词）
FORBIDDEN_KEYS = (
    "decision", "confidence", "rationale", "model", "action", "split",
    "holdout", "dev", "dev_set", "holdout_set", "split_id",
    "candidate_ids", "retrieval_score", "scores", "reviewed_by",
    "review_status", "evidence_sha256", "reviewer_identity", "auto_review",
    "overlay",
)
_FORBIDDEN_KEY_RE = re.compile(
    r'(?<!\\)"(' + "|".join(re.escape(k) for k in FORBIDDEN_KEYS) + r')"\s*:')


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(65536), b""):
            h.update(block)
    return h.hexdigest()


def _line(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"))


def _load_chunks(path: Path) -> tuple[dict[str, str], dict[str, str], str]:
    """chunk_id → (text, source 文件名) + 文件 SHA-256。"""
    text: dict[str, str] = {}
    source: dict[str, str] = {}
    for ln in path.open(encoding="utf-8"):
        if ln.strip():
            d = json.loads(ln)
            text[d["chunk_id"]] = d["text"]
            source[d["chunk_id"]] = d["source"]
    return text, source, _sha256_file(path)


def _scan_forbidden(text: str) -> list[str]:
    """扫描产物文本：禁止字样与禁止结构键（JSON 键形态）。"""
    errs = [p for p in FORBIDDEN_PHRASES if p in text]
    if _FORBIDDEN_KEY_RE.search(text):
        errs.append("forbidden structure key found (auto-review / split / "
                    "eval field)")
    return errs


# ── 构建 ──────────────────────────────────────────────────────────────

def build_pack(draft_path: Path, chunks_path: Path,
               chunk_manifest_path: Path, corpus_manifest_path: Path,
               ledger_path: Path, out_dir: Path,
               expected_total: int = 150) -> Path:
    """构建人工终审包（离线、确定性、fail-closed）；返回 pack 路径。"""
    cases, draft_sha = rv.load_draft(draft_path)  # 已按 id 排序、查重
    if len(cases) != expected_total:
        raise ValueError(f"draft rows {len(cases)} != expected "
                         f"{expected_total}")
    chunks, chunk_sources, chunks_sha = _load_chunks(chunks_path)
    by_id = {c["id"]: c for c in cases}

    rows: list[dict] = []
    for case in cases:
        cid = case["id"]
        errs = rv._chain_errors(case, by_id)
        if errs:
            raise ValueError("multi-turn chain broken: " + "; ".join(errs))
        for k in ("query", "language", "query_type", "metadata",
                  "should_refuse", "relevance_level",
                  "acceptable_answer_points", "relevant_source_ids",
                  "relevant_chunks", "relevant_chunk_ids"):
            if k not in case:
                raise ValueError(f"{cid}: 缺少必需字段 {k}")
        if case["relevance_level"] not in RELEVANCE_LEVELS:
            raise ValueError(f"{cid}: relevance_level 非法 "
                             f"{case['relevance_level']!r}")
        if not isinstance(case["acceptable_answer_points"], list) or \
                not isinstance(case["relevant_source_ids"], list):
            raise ValueError(f"{cid}: acceptable_answer_points / "
                             "relevant_source_ids 非列表")
        chunks_ = case["relevant_chunks"]
        chunk_ids = case["relevant_chunk_ids"]
        if not isinstance(chunks_, list) or not isinstance(chunk_ids, list):
            raise ValueError(f"{cid}: relevant_chunks / relevant_chunk_ids "
                             "非列表")
        if set(chunk_ids) != {ev.get("chunk_id") for ev in chunks_}:
            raise ValueError(f"{cid}: relevant_chunk_ids 与 relevant_chunks "
                             "不一致")

        evidence: list[dict] = []
        for rc in chunks_:
            cid2 = rc.get("chunk_id", "")
            text = chunks.get(cid2, "")
            if not text:
                raise ValueError(f"{cid}: chunk 引用不存在: {cid2}")
            snip = rc.get("chunk_text_snippet", "")
            # 缺失/非连续证据：snippet 必须是 chunk 原文的连续片段
            if not rv.snippet_is_evidence(snip, text):
                raise ValueError(f"{cid}: {cid2}: snippet 不是连续证据")
            src = rc.get("source_id", "")
            if chunk_sources.get(cid2) != src:
                raise ValueError(f"{cid}: {cid2}: source 不一致 "
                                 f"({src} vs {chunk_sources.get(cid2)})")
            evidence.append({
                "source_id": src,
                "chunk_id": cid2,
                "snippet": snip,
                "section": rc.get("section"),
            })
        if case["relevance_level"] == "chunk" and not evidence:
            raise ValueError(f"{cid}: relevance_level=chunk 但无 chunk 证据")

        row = {
            "case_id": cid,
            "query": case["query"],
            "language": case["language"],
            "query_type": case["query_type"],
            "previous_turns": rv._previous_turns(case, by_id),
            "should_refuse": bool(case["should_refuse"]),
            "relevance_level": case["relevance_level"],
            "acceptable_answer_points": case["acceptable_answer_points"],
            "relevant_source_ids": case["relevant_source_ids"],
            "evidence": evidence,
            "human_review_decision": "",
            "human_reviewer": "",
            "human_review_notes": "",
        }
        assert set(row) == ALLOWED_KEYS
        rows.append(row)

    rows.sort(key=lambda r: r["case_id"])
    pack_text = "\n".join(_line(r) for r in rows) + "\n"
    # 输出纯净性：禁止字样与禁止结构键一票否决
    markers = _scan_forbidden(pack_text)
    if markers:
        raise ValueError("forbidden marker in pack: " + "; ".join(markers))

    out_dir.mkdir(parents=True, exist_ok=True)
    pack_path = out_dir / "human-review-pack.jsonl"
    pack_path.write_text(pack_text, encoding="utf-8")

    inputs = {
        "draft": {"path": str(draft_path.resolve()), "sha256": draft_sha,
                  "rows": len(cases)},
        "chunks": {"path": str(chunks_path.resolve()),
                   "sha256": chunks_sha},
        "chunk_manifest": {"path": str(chunk_manifest_path.resolve()),
                           "sha256": _sha256_file(chunk_manifest_path)},
        "corpus_manifest": {"path": str(corpus_manifest_path.resolve()),
                            "sha256": _sha256_file(corpus_manifest_path)},
        "repair_ledger": {"path": str(ledger_path.resolve()),
                          "sha256": _sha256_file(ledger_path)},
    }
    manifest = {
        "pack_version": PACK_VERSION,
        "n_cases": len(rows),
        "inputs": inputs,
        "pack_sha256": _sha256_file(pack_path),
        "created_by": "corpus_v2_human_review_pack.py build",
    }
    (out_dir / "human-review-pack-manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=1) + "\n",
        encoding="utf-8")
    (out_dir / "HUMAN_REVIEW_INSTRUCTIONS.md").write_text(
        _instructions_text(), encoding="utf-8")
    (out_dir / "human-review-pack-report.md").write_text(
        _report_text(rows, manifest), encoding="utf-8")
    return pack_path


# ── fail-closed 校验 ──────────────────────────────────────────────────

def verify(manifest_path: Path, *, pack_path: Path | None = None,
           draft_path: Path | None = None,
           chunks_path: Path | None = None,
           chunk_manifest_path: Path | None = None,
           corpus_manifest_path: Path | None = None,
           ledger_path: Path | None = None) -> list[str]:
    """对既有终审包重跑 fail-closed 校验；返回错误列表（空 = 通过）。"""
    errors: list[str] = []
    try:
        m = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return [f"manifest 无法读取: {exc}"]

    # 输入 SHA 漂移（五类输入逐一复算）
    overrides = {
        "draft": draft_path, "chunks": chunks_path,
        "chunk_manifest": chunk_manifest_path,
        "corpus_manifest": corpus_manifest_path,
        "repair_ledger": ledger_path,
    }
    for key, override in overrides.items():
        p = override or Path(m["inputs"][key]["path"])
        if not p.exists():
            errors.append(f"{key}: 文件不存在: {p}")
            continue
        if m["inputs"][key]["sha256"] != _sha256_file(p):
            errors.append(f"{key}: SHA-256 漂移（输入被改写）")

    pack = pack_path or manifest_path.parent / "human-review-pack.jsonl"
    if not pack.exists():
        errors.append(f"pack 文件不存在: {pack}")
        return sorted(set(errors))
    if m["pack_sha256"] != _sha256_file(pack):
        errors.append("pack sha256 漂移（产物被改写）")

    pack_text = pack.read_text(encoding="utf-8")
    for marker in _scan_forbidden(pack_text):
        errors.append(marker)

    rows: list[dict] = []
    for n, ln in enumerate(pack_text.splitlines(), 1):
        if not ln.strip():
            continue
        try:
            rows.append(json.loads(ln))
        except json.JSONDecodeError as e:
            errors.append(f"pack 第 {n} 行非法 JSON: {e}")
    if len(rows) != m["n_cases"]:
        errors.append(f"pack 行数 {len(rows)} != manifest {m['n_cases']}"
                      "（case 遗漏/重复）")
    ids = [r.get("case_id", "") for r in rows]
    if len(set(ids)) != len(ids):
        dup = sorted({i for i in ids if ids.count(i) > 1})
        errors.append(f"pack 存在重复 case id: {dup}")
    if ids != sorted(ids):
        errors.append("pack 行未按 case_id 稳定排序")

    # 与草稿集合 / 证据一致性
    try:
        draft_cases, _ = rv.load_draft(draft_path or Path(
            m["inputs"]["draft"]["path"]))
    except (OSError, ValueError) as exc:
        errors.append(f"draft 无法加载: {exc}")
        draft_cases = []
    by_id = {c["id"]: c for c in draft_cases}
    if set(ids) != set(by_id):
        errors.append(f"pack case 集合与草稿不一致 "
                      f"(缺少 {sorted(set(by_id) - set(ids))} / "
                      f"多余 {sorted(set(ids) - set(by_id))})")
    try:
        chunks, chunk_sources, _ = _load_chunks(chunks_path or Path(
            m["inputs"]["chunks"]["path"]))
    except (OSError, ValueError) as exc:
        errors.append(f"chunks 无法加载: {exc}")
        chunks, chunk_sources = {}, {}

    for r in rows:
        cid = r.get("case_id", "<unknown>")
        extra = set(r) - ALLOWED_KEYS
        if extra:
            errors.append(f"{cid}: 非法字段 {sorted(extra)}")
        missing = ALLOWED_KEYS - set(r)
        if missing:
            errors.append(f"{cid}: 缺少字段 {sorted(missing)}")
        for f in HUMAN_FIELDS:
            if r.get(f, "UNSET") != "":
                errors.append(f"{cid}: 人工字段 {f} 必须为空（任务绝不自动"
                              "填值）")
        case = by_id.get(cid)
        if case is None:
            continue
        expected_prev = rv._previous_turns(case, by_id)
        if r.get("previous_turns") != expected_prev:
            errors.append(f"{cid}: previous_turns 与草稿链不一致")
        for ev in r.get("evidence", []):
            extra_ev = set(ev) - EVIDENCE_KEYS
            if extra_ev:
                errors.append(f"{cid}: 证据非法字段 {sorted(extra_ev)}")
            ck = chunks.get(ev.get("chunk_id", ""))
            if not ck:
                errors.append(f"{cid}: chunk 引用不存在 {ev.get('chunk_id')}")
                continue
            if not rv.snippet_is_evidence(ev.get("snippet", ""), ck):
                errors.append(f"{cid}: {ev.get('chunk_id')}: snippet 不是"
                              "连续证据")
            if chunk_sources.get(ev.get("chunk_id", "")) != \
                    ev.get("source_id"):
                errors.append(f"{cid}: {ev.get('chunk_id')}: source 与"
                              "chunks.jsonl 不一致")
        if r.get("relevance_level") == "chunk" and not r.get("evidence"):
            errors.append(f"{cid}: relevance_level=chunk 但无 chunk 证据")
        if r.get("should_refuse") is True and r.get("evidence"):
            errors.append(f"{cid}: 拒答行不应有证据")
    return sorted(set(errors))


# ── 报告（仅全量计数 + 字段说明 + 输入 SHA，不含 split/评测指标）──────

def _report_text(rows: list[dict], manifest: dict) -> str:
    from collections import Counter
    n = len(rows)
    rel = Counter(r["relevance_level"] for r in rows)
    ref = Counter(bool(r["should_refuse"]) for r in rows)
    lang = Counter(r["language"] for r in rows)
    qtype = Counter(r["query_type"] for r in rows)
    n_evidence = sum(len(r["evidence"]) for r in rows)
    n_with_evidence = sum(1 for r in rows if r["evidence"])
    n_multi = sum(1 for r in rows if r["previous_turns"])
    lines = [
        "# v2 人工终审包准备报告",
        "",
        "> 本报告只包含全量计数、字段说明与输入 SHA-256，不含任何划分",
        "> 身份、自动审阅结论或评测指标。终审包供真人逐条填写，"
        "**尚未进行人工终审**，绝不伪称人工审核。",
        "",
        "## 全量计数",
        "",
        f"- 条数：{n}",
        f"- relevance_level：chunk {rel.get('chunk', 0)}；"
        f"source {rel.get('source', 0)}；none {rel.get('none', 0)}",
        f"- should_refuse：true {ref.get(True, 0)}；false {ref.get(False, 0)}",
        f"- language：" + "；".join(
            f"{k} {v}" for k, v in sorted(lang.items())),
        f"- query_type：" + "；".join(
            f"{k} {v}" for k, v in sorted(qtype.items())),
        f"- 多轮行数（previous_turns 非空）：{n_multi}",
        f"- 带证据行数：{n_with_evidence}",
        f"- 证据条目总数：{n_evidence}",
        "",
        "## 字段说明",
        "",
        "| 字段 | 说明 |",
        "|---|---|",
        "| case_id | 草稿 case 标识（与 v2 草稿一致） |",
        "| query | 待审阅问题原文 |",
        "| language / query_type | 语言与问题类型 |",
        "| previous_turns | 多轮链中前序轮次（case_id + query），单轮为空 |",
        "| should_refuse | 草稿的拒答判定（true = 判定无法从语料回答） |",
        "| relevance_level | 草稿的证据层级（chunk / source / none） |",
        "| acceptable_answer_points | 草稿答案点列表（拒答行为空） |",
        "| relevant_source_ids | 草稿声明的相关源文件 |",
        "| evidence[] | 每条 chunk 证据：source_id / chunk_id / 连续 "
        "snippet / section |",
        "| human_review_decision | 人工填写：confirmed / reject / "
        "needs_followup |",
        "| human_reviewer | 人工填写：审阅人标识 |",
        "| human_review_notes | 人工填写：理由（reject / needs_followup "
        "必填） |",
        "",
        "## 输入 SHA-256",
        "",
    ]
    for key, info in manifest["inputs"].items():
        lines.append(f"- {key}：{info['sha256']}（{info['path']}）")
    lines += [
        "",
        "## fail-closed 校验",
        "",
        "- 行数 150、case_id 唯一且与草稿一致；",
        "- 证据 chunk/source 存在、snippet 连续；人工字段初始全部为空；",
        "- 行键与证据键均为严格白名单，无任何划分 / 自动审阅结构字段；",
        "- 输入 SHA 漂移、缺失 chunk、重复/遗漏 case、禁止字样出现均"
        "失败。",
        "",
        "## 结论",
        "",
        "人工终审包已准备，尚未进行人工终审；不得进入 v2.1。",
        "",
        "填写判定口径（详见 HUMAN_REVIEW_INSTRUCTIONS.md）：",
        "- confirmed：问题、答案点、拒答判定和所有证据都正确；",
        "- reject：存在事实、证据、来源或拒答错误；",
        "- needs_followup：人工无法确定，需要补充来源或证据。",
        "",
        "仅当 150 条均由真人填写后，才可另行讨论如何导入人工审阅结果；",
        "本工具绝不自动填值。",
    ]
    return "\n".join(lines) + "\n"


def _instructions_text() -> str:
    return (
        "# 人工终审填写说明（v2 标注草稿）\n"
        "\n"
        "> 本包共 150 条，由真人逐条审阅并填写。当前标注为 "
        "LLM_ASSISTED 状态，**未经人工批准**；本包是人工终审的输入，"
        "**尚未进行人工终审**，不得进入 v2.1。\n"
        "\n"
        "## 盲态声明\n"
        "\n"
        "- 本包**不含**自动二审的结论、置信度、理由或审阅模型名；\n"
        "- 本包**不含**修复动作、任何划分身份、检索分数、候选集或历史"
        "评测结果；\n"
        "- 请仅依据每条中的 query、多轮上下文、草稿标签与 chunk 证据"
        "独立判断，不要受包外信息影响。\n"
        "\n"
        "## 每行如何填写\n"
        "\n"
        "每行只允许填写以下三个字段，其余字段（case_id / query / 草稿"
        "标签 / evidence）**不得改动**：\n"
        "\n"
        "| 字段 | 填写内容 |\n"
        "|---|---|\n"
        "| human_review_decision | 三选一：`confirmed` / `reject` / "
        "`needs_followup` |\n"
        "| human_reviewer | 你的审阅人标识（姓名或工号） |\n"
        "| human_review_notes | 理由；`reject` 与 `needs_followup` "
        "必须填写 |\n"
        "\n"
        "## 判定口径\n"
        "\n"
        "- `confirmed`：问题、答案点、拒答判定和所有证据都正确；\n"
        "- `reject`：存在事实、证据、来源或拒答错误；\n"
        "- `needs_followup`：人工无法确定，需要补充来源或证据。\n"
        "\n"
        "## 核验要点\n"
        "\n"
        "1. **答案点必须有证据**：每个答案点须由证据中的连续 snippet "
        "直接支持；需要查看完整 chunk 原文时，按 chunk_id 在 "
        "`data/v2-corpus/chunks/chunks.jsonl`（source 字段与证据的 "
        "source_id 一致）中查证；\n"
        "2. **拒答行**（should_refuse=true、无证据）：判断该问题在本地"
        "语料下是否确实无法回答；\n"
        "3. **多轮行**：结合 previous_turns 上下文，判断当前问题是否"
        "合理衔接、拒答判定是否与对话链一致；\n"
        "4. **跨文档断言**：跨越多个 source 的答案点，须在各自文档中"
        "都有对应证据；\n"
        "5. **不得放宽标准**：为凑齐 150 条 confirmed 而降低证据标准"
        "是不允许的；拿不准就填 `needs_followup`。\n"
        "\n"
        "## 完成之后\n"
        "\n"
        "- 150 条全部由真人填写后，才可另行讨论如何导入人工审阅结果；\n"
        "- 本工具**绝不自动填值**，也不会在无人工确认的情况下写入任何"
        "批准标记；\n"
        "- 未完成 150 条人工填写并确认之前，不得进入 v2.1。\n"
    )


# ── CLI ───────────────────────────────────────────────────────────────

def _flag(args: list[str], name: str) -> str | None:
    for i, a in enumerate(args):
        if a == name and i + 1 < len(args):
            return args[i + 1]
    return None


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if not args:
        print("usage: corpus_v2_human_review_pack.py build|verify "
              "[--out DIR]")
        return 2
    cmd = args.pop(0)
    try:
        if cmd == "build":
            out = Path(_flag(args, "--out") or DEFAULT_OUT)
            pack = build_pack(DEFAULT_DRAFT, DEFAULT_CHUNKS,
                              DEFAULT_CHUNK_MANIFEST,
                              DEFAULT_CORPUS_MANIFEST, DEFAULT_LEDGER,
                              out)
            n = sum(1 for _ in pack.open(encoding="utf-8") if _.strip())
            print(f"wrote human-review pack: {pack} (n={n})")
            return 0
        if cmd == "verify":
            out = Path(_flag(args, "--out") or DEFAULT_OUT)
            errs = verify(out / "human-review-pack-manifest.json")
            if errs:
                for e in errs:
                    print("VERIFY FAILED:", e)
                return 1
            print("verify ok: human-review pack intact (150 rows, "
                  "no split fields, no auto-review fields)")
            return 0
    except ValueError as exc:
        print(f"FAILED: {exc}")
        return 2
    print(f"unknown command: {cmd}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
