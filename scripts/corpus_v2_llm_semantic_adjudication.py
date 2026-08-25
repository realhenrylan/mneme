"""Corpus v2 blind semantic adjudication of third-pass disagreements.

对 v2 第三轮机器审阅的 82 条 reject 做盲态语义仲裁：从第三轮 68 条
confirmed 中以 ``sha256("v2-semantic-adjudication-v1:" + case_id)``
确定性抽取 20 条隐藏对照，与 82 条争议合并为 102 条盲态输入；模型
（``deepseek-v4-pro``）逐条给出 semantic_verdict / 逐答案点
support_level / 拒答 refusal_assessment，全部完成后才比较。

设计原则：

1. **盲态**：模型输入仅含 query、previous_turns、should_refuse、
   acceptable_answer_points、evidence、本地 chunks 原文；不含 case_id、
   decision、reviewer、notes、repair、cohort、对照身份或任何历史结论；
   20 条对照清单只保存在审计侧 selection-manifest.json。
2. **只读**：绝不修改 draft、blank/filled pack、chunks、manifest、
   split 或生产配置；不生成 overlay；不进入 v2.1。
3. **确定性**：选择算法、盲包结构、prompt、manifest 结构可复现；
   temperature=0.0；按 case_id 升序逐条执行。
4. **fail-closed**：blank/filled 必须各 150 行、case_id 集合一致、
   除三个人工字段外逐行一致、decision 分布必须 68/82/0、证据映射
   有效；102 条覆盖、枚举合法、每条有理由；模型身份漂移、字段泄露
   或任何结构漂移立即失败且不产出比较结论。

禁止模型：``gpt-5.6-sol``、``deepseek-v4-flash``（FORBIDDEN_MODELS，
代码级守卫）；reviewer_model 固定为 ``deepseek-v4-pro``。

产物目录：evaluation/datasets/v2/llm-semantic-adjudication/
"""

from __future__ import annotations

import json
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BLANK_PACK = ROOT / "evaluation" / "datasets" / "v2" / "human-review" / \
    "human-review-pack.jsonl"
DEFAULT_FILLED_PACK = ROOT / "evaluation" / "datasets" / "v2" / "human-review" / \
    "human-review-pack.llm-filled.jsonl"
DEFAULT_CHUNKS = ROOT / "data" / "v2-corpus" / "chunks" / "chunks.jsonl"
DEFAULT_OUT = ROOT / "evaluation" / "datasets" / "v2" / \
    "llm-semantic-adjudication"

REVIEWER_MODEL = "deepseek-v4-pro"
FORBIDDEN_MODELS = ("gpt-5.6-sol", "deepseek-v4-flash")
CONTROL_SALT = "v2-semantic-adjudication-v1:"
CONTROL_COUNT = 20
TEMPERATURE = 0.0
# deepseek-v4-pro 输出前消耗约 2500-3800 tokens 做隐藏推理；
# 3000 会被推理吃光（finish_reason=length、可见输出为空/截断），
# 8000 留足推理 + 答案余量（实测 16000 与 8000 同结果）
MAX_TOKENS = 8000
EXPECTED_TOTAL = 150
EXPECTED_CONFIRMED = 68
EXPECTED_REJECT = 82
EXPECTED_FOLLOWUP = 0
REVIEWER_PREFIX = "LLM_ASSISTED_"

VERDICTS = ("confirmed", "reject", "needs_followup")
SUPPORT_LEVELS = ("direct_snippet", "within_chunk_outside_snippet",
                  "faithful_paraphrase", "unsupported")
REFUSAL_ASSESSMENTS = ("no_answer", "partial_topic_overlap_only",
                       "substantive_answer_exists", "unclear")
# 盲包每行唯一允许的字段（模型可见的全部内容）
BLIND_PACK_FIELDS = ("query", "previous_turns", "should_refuse",
                     "acceptable_answer_points", "evidence", "chunks")

# 谱系限制：与历史 deepseek-chat 同属 DeepSeek 提供方，不宣称独立性
PROVIDER_NOTE = ("本轮与此前 deepseek-chat 同属 DeepSeek 提供方；"
                 "第三轮模型身份未被历史 manifest 记录；"
                 "不宣称模型或供应商独立性")

sys.path.insert(0, str(ROOT))  # 允许直接以 python scripts/... 方式运行
import scripts.corpus_v2_human_review_apply as hra  # noqa: E402
import scripts.corpus_v2_human_review_pack as hp  # noqa: E402

_sha256_text = hra._sha256_text
_sha256_file = hra._sha256_file
_line = hra._line

ADJUDICATIONS_FILE = "deepseek-v4-pro-adjudications.jsonl"
OUTPUT_FILES = ("blind-input-pack.jsonl", ADJUDICATIONS_FILE,
                "selection-manifest.json", "comparison-report.md",
                "manifest.json")

SYSTEM_PROMPT = (
    "你是盲态机器语义审阅员，对单条评测案例做语义仲裁。\n"
    "规则：\n"
    "1. 只能依据本条消息提供的 query、previous_turns、should_refuse、"
    "acceptable_answer_points、evidence 与 chunks 原文判断；不得假设证据之外"
    "存在的语料内容。\n"
    "2. 可答题（should_refuse=false）：对 acceptable_answer_points 中每个"
    "答案点逐点给出支持级别与引用。support_level 取值：direct_snippet（答案点"
    "逐字出现在 evidence 的 snippet 内）；within_chunk_outside_snippet（答案点"
    "不在 snippet 内但逐字出现在对应 chunk 全文内）；faithful_paraphrase"
    "（chunk 原文存在忠实转述而非逐字）；unsupported（找不到支持）。每点附引用"
    "的 chunk_id（必须是本条 chunks 中的 chunk_id）与最短必要原文摘录。可答题"
    "不得输出 refusal_assessment 与 refusal_evidence 字段。\n"
    "3. 拒答题（should_refuse=true）：给出 refusal_assessment：no_answer"
    "（语料确实无相关内容）；partial_topic_overlap_only（仅有部分主题重叠，"
    "无法构成实质回答）；substantive_answer_exists（语料中存在实质答案，拒答"
    "不当）；unclear（无法确定）。附支持该判断的 chunk_id 与原文摘录。拒答题"
    "不得输出 answer_point_supports 字段。\n"
    "4. 任何不确定情况必须选择 semantic_verdict=needs_followup，不得强行确认。\n"
    "5. 只输出一个 JSON 对象，不要输出任何其他文本，字段如下：\n"
    '{"semantic_verdict": "confirmed"|"reject"|"needs_followup", '
    '"verdict_rationale": "结构化理由", '
    '"answer_point_supports": [{"answer_point_index": 0, "support_level": '
    '"direct_snippet"|"within_chunk_outside_snippet"|"faithful_paraphrase"|'
    '"unsupported", "chunk_id": "...", "excerpt": "最短必要原文摘录"}], '
    '"refusal_assessment": "no_answer"|"partial_topic_overlap_only"|'
    '"substantive_answer_exists"|"unclear", '
    '"refusal_evidence": [{"chunk_id": "...", "excerpt": "..."}]}'
)


class AdjudicationError(Exception):
    """fail-closed 仲裁失败（任何非法状态立即失败，不产出比较结论）。"""


# ── 确定性对照选择 ──────────────────────────────────────────────────

def select_controls(confirmed_ids: list[str], *,
                    salt: str = CONTROL_SALT,
                    n: int = CONTROL_COUNT) -> list[str]:
    """按 sha256(salt + case_id) 升序排序取前 n 条隐藏对照。

    排序键为十六进制摘要字符串（等长，等价于按摘要字节排序），
    输出按 case_id 升序，保证完全确定。
    """
    ids = sorted(confirmed_ids)
    return sorted(ids, key=lambda cid: _sha256_text(salt + cid))[:n]


# ── 盲态输入包 ──────────────────────────────────────────────────────

def _blind_pack_row(src: dict, chunk_texts: dict[str, str]) -> dict:
    """从 blank pack 行构建盲态行：仅 6 个字段 + 按需解析的本地 chunks。

    不含 case_id、query_type、language、relevant_source_ids、
    relevance_level 或任何 review 字段；chunk 缺失直接抛 KeyError
    （fail-closed）。
    """
    cids = sorted({ev["chunk_id"] for ev in src.get("evidence", [])})
    chunks = [{"chunk_id": c, "text": chunk_texts[c]} for c in cids]
    # previous_turns 只保留 query 文本，剥离内部 case_id（链引用不得进模型）
    turns = [{"query": t["query"]} for t in src.get("previous_turns") or []]
    return {
        "query": src["query"],
        "previous_turns": turns,
        "should_refuse": bool(src.get("should_refuse")),
        "acceptable_answer_points":
            list(src.get("acceptable_answer_points") or []),
        "evidence": [dict(ev) for ev in src.get("evidence", [])],
        "chunks": chunks,
    }


def _prompt_sha256(rows: list[dict]) -> str:
    """完整提示词（system + 102 条 user payload）的规范 JSON SHA-256。"""
    payload = {"system": SYSTEM_PROMPT, "cases": rows}
    return _sha256_text(json.dumps(payload, ensure_ascii=False, sort_keys=True,
                                   separators=(",", ":")))


# ── fail-closed 输入校验 + 队列确定 ─────────────────────────────────

def _load_blind_material(blank_path: Path, filled_path: Path,
                         chunks_path: Path, control_count: int, *,
                         expected_total: int = EXPECTED_TOTAL,
                         expected_confirmed: int = EXPECTED_CONFIRMED,
                         expected_reject: int = EXPECTED_REJECT,
                         expected_followup: int = EXPECTED_FOLLOWUP) -> dict:
    """校验输入并确定 82 争议 / 20 对照 / 102 顺序；任何漂移即抛错。

    复用 hra 共享校验：blank 结构、filled 对齐、LLM 前缀、证据映射。
    """
    errors: list[str] = []
    blank = hra._load_rows(blank_path, "blank", errors)
    filled = hra._load_rows(filled_path, "filled", errors)
    hra._blank_errors(blank, None, errors, expected_total=expected_total)
    hra._filled_errors(filled, blank, errors, expected_total=expected_total)
    hra._llm_filled_extra_errors(filled, errors, REVIEWER_PREFIX)
    hra._evidence_errors(blank, chunks_path, {}, errors)
    hra._evidence_errors(filled, chunks_path, {}, errors)

    counts = Counter(r.get("human_review_decision") for r in filled)
    expected = {"confirmed": expected_confirmed, "reject": expected_reject,
                "needs_followup": expected_followup}
    # 逐键比对：0 计数的键在 Counter 中不出现，不能做字典全等
    drift = [f"{k}={counts.get(k, 0)}"
             for k in sorted(set(counts) | set(expected))
             if counts.get(k, 0) != expected.get(k)]
    if drift:
        errors.append(f"filled decision counts drift: {', '.join(drift)} "
                      f"(expected {expected})")
    if errors:
        raise AdjudicationError("fail-closed: " + "; ".join(errors))

    blank_by_id = {r["case_id"]: r for r in blank}
    filled_by_id = {r["case_id"]: r for r in filled}
    confirmed_ids = sorted(cid for cid, r in filled_by_id.items()
                           if r["human_review_decision"] == "confirmed")
    reject_ids = sorted(cid for cid, r in filled_by_id.items()
                        if r["human_review_decision"] == "reject")
    if control_count > len(confirmed_ids):
        raise AdjudicationError(f"control_count {control_count} > confirmed "
                                f"{len(confirmed_ids)}")
    controls = select_controls(confirmed_ids, n=control_count)
    # 盲态集合 = 82 争议 + 20 对照（其余 confirmed 不进入模型输入）
    order = sorted(set(reject_ids) | set(controls))
    chunk_texts, _sources, _sha = hp._load_chunks(chunks_path)
    return {
        "blank_by_id": blank_by_id,
        "filled_by_id": filled_by_id,
        "confirmed_ids": confirmed_ids,
        "reject_ids": reject_ids,
        "controls": controls,
        "disputed": reject_ids,
        "order": order,
        "chunk_texts": chunk_texts,
        "n_confirmed": len(confirmed_ids),
        "n_reject": len(reject_ids),
    }


# ── 模型输出解析（fail-closed）─────────────────────────────────────

def _normalize_supports(raw: Any, chunk_ids: set[str],
                        n_points: int) -> list[dict] | None:
    """逐答案点支持列表：每个点至少一条、所有点全覆盖、枚举合法、
    摘录非空（unsupported 除外）。

    允许同一答案点引用多个 chunk（跨 chunk 证据），按 index 排序输出。
    unsupported 无原文可引用：chunk_id 允许为空串或 null（归一化为 ""），
    其余级别的 chunk_id 必须在本条 chunks 中。
    """
    if raw is None:
        raw = []
    if not isinstance(raw, list):
        return None
    if n_points == 0:
        return [] if raw == [] else None
    if not raw:
        return None
    covered: set[int] = set()
    out: list[dict] = []
    for s in raw:
        if not isinstance(s, dict):
            return None
        idx = s.get("answer_point_index")
        level = s.get("support_level")
        cid = s.get("chunk_id")
        excerpt = str(s.get("excerpt", "")).strip()
        if isinstance(idx, bool) or not isinstance(idx, int):
            return None
        if not (0 <= idx < n_points):
            return None
        if level not in SUPPORT_LEVELS:
            return None
        if level == "unsupported":
            cid = ""  # 无法引用原文（模型可能给空串或 null）
            excerpt = ""
        elif cid not in chunk_ids:
            return None
        elif not excerpt:
            return None
        covered.add(idx)
        out.append({"answer_point_index": idx, "support_level": level,
                    "chunk_id": cid, "excerpt": excerpt})
    if covered != set(range(n_points)):
        return None
    return sorted(out, key=lambda s: (s["answer_point_index"],
                                      s["chunk_id"]))


def _parse_adjudication(content: str, *, should_refuse: bool,
                        chunk_ids: set[str], n_points: int) -> dict | None:
    """严格解析模型输出；任何非法值返回 None（fail-closed）。

    可答题必须逐答案点输出支持级别；拒答题必须给出 refusal_assessment 与
    证据（unclear 或无 chunk 时允许空证据）。跨分支多余字段（模型噪声）先
    验证枚举/结构合法，再归一化忽略：可答题的 refusal_assessment 若存在
    必须为合法枚举，refusal_evidence 若存在必须是列表；拒答题的
    answer_point_supports 若存在必须是列表。
    """
    text = content.strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text).strip()
    try:
        d = json.loads(text)
    except json.JSONDecodeError:
        return None
    if not isinstance(d, dict):
        return None
    verdict = d.get("semantic_verdict")
    rationale = str(d.get("verdict_rationale", "")).strip()
    if verdict not in VERDICTS or not rationale:
        return None
    if should_refuse:
        ra = d.get("refusal_assessment")
        if ra not in REFUSAL_ASSESSMENTS:
            return None
        # 跨分支字段若存在必须为列表（模型噪声），归一化忽略
        raw_supports = d.get("answer_point_supports")
        if raw_supports is not None and not isinstance(raw_supports, list):
            return None
        raw_ev = d.get("refusal_evidence")
        if raw_ev is None:
            raw_ev = []
        if not isinstance(raw_ev, list):
            return None
        items: list[dict] = []
        for e in raw_ev:
            if not isinstance(e, dict):
                return None
            cid = e.get("chunk_id")
            excerpt = str(e.get("excerpt", "")).strip()
            if cid not in chunk_ids or not excerpt:
                return None
            items.append({"chunk_id": cid, "excerpt": excerpt})
        # 无 chunk 可引用（证据为空）时允许空证据；否则非 unclear 必须附证据
        if not items and ra != "unclear" and chunk_ids:
            return None
        return {"semantic_verdict": verdict, "verdict_rationale": rationale,
                "answer_point_supports": [], "refusal_assessment": ra,
                "refusal_evidence": items}
    # 可答题：跨分支字段若存在必须合法（枚举/结构），归一化忽略
    ra = d.get("refusal_assessment")
    if ra is not None and ra not in REFUSAL_ASSESSMENTS:
        return None
    raw_re = d.get("refusal_evidence")
    if raw_re is not None and not isinstance(raw_re, list):
        return None
    supports = _normalize_supports(d.get("answer_point_supports"),
                                   chunk_ids, n_points)
    if supports is None:
        return None
    return {"semantic_verdict": verdict, "verdict_rationale": rationale,
            "answer_point_supports": supports, "refusal_assessment": None,
            "refusal_evidence": []}


def _llm_content(llm_fn: Callable, messages: list[dict], model: str,
                 case_id: str) -> tuple[str, int]:
    """调用模型一次并返回 (content, transport_retries)；漂移/失败即抛错。"""
    try:
        resp, rec = llm_fn("semantic_adjudication", messages, model=model,
                           temperature=TEMPERATURE, max_tokens=MAX_TOKENS)
    except Exception as exc:
        raise AdjudicationError(f"{case_id}: llm call failed: {exc}")
    resp_model = getattr(resp, "model", None)
    if resp_model and resp_model != model:
        raise AdjudicationError(f"{case_id}: model drift: requested {model}, "
                                f"got {resp_model}")
    try:
        content = resp.choices[0].message.content
    except Exception as exc:
        raise AdjudicationError(f"{case_id}: llm response malformed: {exc}")
    retries = int(getattr(rec, "retries_used", 0) or 0)
    return content, retries


# ── 比较（仅模型输出完成后）────────────────────────────────────────

def _bucket(cids: list[str], adj_by_cid: dict[str, dict],
            verdicts: tuple[str, ...]) -> list[int]:
    return [sum(1 for c in cids if adj_by_cid[c]["semantic_verdict"] == v)
            for v in verdicts]


def _disputed_stats(cids: list[str], adj_by_cid: dict[str, dict]) -> dict:
    agree, disagree, uncertain = _bucket(
        cids, adj_by_cid, ("reject", "confirmed", "needs_followup"))
    return {"total": len(cids), "agree": agree, "disagree": disagree,
            "uncertain": uncertain}


def _controls_stats(cids: list[str], adj_by_cid: dict[str, dict]) -> dict:
    confirmed, reject, followup = _bucket(
        cids, adj_by_cid, ("confirmed", "reject", "needs_followup"))
    return {"total": len(cids), "confirmed": confirmed, "reject": reject,
            "needs_followup": followup}


def _compute_comparison(material: dict,
                        adj_by_cid: dict[str, dict]) -> dict:
    """82 争议一致/不一致/不确定 + 20 对照分布 + 三层分层 + 计数。"""
    blank_by_id = material["blank_by_id"]
    order = material["order"]
    disputed = material["disputed"]
    controls = material["controls"]

    def strata_rows(cids: list[str]) -> dict:
        return {"disputed": _disputed_stats(
                    [c for c in cids if c in disputed], adj_by_cid),
                "controls": _controls_stats(
                    [c for c in cids if c in controls], adj_by_cid)}

    strata = {
        "answerable": strata_rows(
            [c for c in order if not blank_by_id[c]["should_refuse"]]),
        "refusal": strata_rows(
            [c for c in order if blank_by_id[c]["should_refuse"]]),
        "cross_document": strata_rows(
            [c for c in order
             if blank_by_id[c].get("query_type") == "cross_document"]),
    }
    support_levels = Counter()
    refusal_assessments = Counter()
    for row in adj_by_cid.values():
        for s in row["answer_point_supports"]:
            support_levels[s["support_level"]] += 1
        if row["refusal_assessment"] is not None:
            refusal_assessments[row["refusal_assessment"]] += 1
    return {
        "disputed": _disputed_stats(disputed, adj_by_cid),
        "controls": _controls_stats(controls, adj_by_cid),
        "strata": strata,
        "support_levels": {k: support_levels.get(k, 0)
                           for k in SUPPORT_LEVELS},
        "refusal_assessments": {k: refusal_assessments.get(k, 0)
                                for k in REFUSAL_ASSESSMENTS},
    }


def _comparison_md(material: dict, adj_by_cid: dict[str, dict],
                   comparison: dict) -> str:
    """比较报告：复算 + 争议/对照/分层 + 支持级别 + 谱系限制 + 结论。"""
    d = comparison["disputed"]
    c = comparison["controls"]
    sl = comparison["support_levels"]
    ra = comparison["refusal_assessments"]
    n_sl = sum(sl.values())
    n_ra = sum(ra.values())

    def pct(a: int, b: int) -> str:
        return f"{a / b:.1%}" if b else "-"

    lines = [
        "# DeepSeek v4 Pro 盲态机器语义审阅（v2 第三轮分歧仲裁）", "",
        "> 本报告为机器语义仲裁证据，**不得视为人工终审**；不构成任何 v2.1 "
        "进入决策；不修改任何标注，不生成 overlay。", "",
        "## 一、输入与盲态构建（复算）", "",
        f"- blank pack：{material['n_confirmed'] + material['n_reject']} 行；"
        f"llm-filled：{material['n_confirmed'] + material['n_reject']} 行；"
        "case_id 集合一致；除三个人工字段外逐行一致。",
        f"- 第三轮 decision 分布（llm-filled 复算）：confirmed "
        f"{material['n_confirmed']} / reject {material['n_reject']} / "
        "needs_followup 0。",
        f"- 隐藏对照：{material['n_confirmed']} 条 confirmed 中按 "
        "sha256(\"v2-semantic-adjudication-v1:\" + case_id) 升序排序取前 "
        f"{len(material['controls'])} 条；对照清单仅在审计侧 "
        "selection-manifest.json，绝不进入模型输入。",
        f"- 盲态输入：{len(material['order'])} 条（82 争议 + 20 对照），"
        "每条仅含 query / previous_turns / should_refuse / "
        "acceptable_answer_points / evidence / chunks 原文；不含 case_id、"
        "decision、reviewer、notes、repair、cohort 或任何历史结论。", "",
        "## 二、82 条争议：与第三轮 reject 的比较", "",
        "| 结果 | 条数 | 占比 |", "|---|---|---|",
        f"| 一致（模型也判 reject） | {d['agree']} | {pct(d['agree'], d['total'])} |",
        f"| 不一致（模型判 confirmed） | {d['disagree']} | "
        f"{pct(d['disagree'], d['total'])} |",
        f"| 不确定（needs_followup） | {d['uncertain']} | "
        f"{pct(d['uncertain'], d['total'])} |", "",
        "## 三、20 条隐藏对照（第三轮 confirmed）", "",
        "| semantic_verdict | 条数 |", "|---|---|",
        f"| confirmed | {c['confirmed']} |",
        f"| reject | {c['reject']} |",
        f"| needs_followup | {c['needs_followup']} |", "",
        "## 四、分层（答案题 / 拒答题 / 跨文档题）", "",
        "| 层 | 争议总数 | 一致 | 不一致 | 不确定 | 对照 confirmed | "
        "对照 reject | 对照 needs_followup |", "|---|---|---|---|---|---|---|---|",
    ]
    for key, label in (("answerable", "答案题"), ("refusal", "拒答题"),
                       ("cross_document", "跨文档题")):
        s = comparison["strata"][key]
        dd = s["disputed"]
        cc = s["controls"]
        lines.append(
            f"| {label} | {dd['total']} | {dd['agree']} | {dd['disagree']} | "
            f"{dd['uncertain']} | {cc['confirmed']} | {cc['reject']} | "
            f"{cc['needs_followup']} |")
    lines += ["", "## 五、答案点支持级别（全部 102 条）", "",
              "| support_level | 条数 |", "|---|---|"]
    for k in SUPPORT_LEVELS:
        lines.append(f"| {k} | {sl[k]} |")
    lines.append(f"| 合计答案点 | {n_sl} |")
    lines += ["", "## 六、拒答评估（拒答题）", "",
              "| refusal_assessment | 条数 |", "|---|---|"]
    for k in REFUSAL_ASSESSMENTS:
        lines.append(f"| {k} | {ra[k]} |")
    lines.append(f"| 合计拒答评估 | {n_ra} |")
    lines += ["", "## 七、谱系限制", "",
              f"- {PROVIDER_NOTE}。", "",
              "## 八、结论与未解决风险", "",
              "- 本报告仅提供机器语义仲裁证据：82 条争议的一致/不一致/不确定、"
              "20 条隐藏对照的分布、逐答案点支持级别与拒答评估，均不构成对"
              "150 条标注的修改、采纳或覆盖。",
              "- 未解决风险：模型对 evidence snippet 截取边界的敏感度未知；"
              "逐字覆盖判定不能完全代表语义忠实度；20 条对照规模有限，统计"
              "效力有限；输出依赖 prompt 与 max_tokens 设置；本轮未做人工"
              "复核。",
              "- 结论：**不得视为人工终审、人工批准或上线批准；"
              "不构成任何 v2.1 进入决策。**", "",
              "## 附录：102 条逐条结果", "",
              "| index | case_id | 角色 | 层 | semantic_verdict | "
              "第三轮 decision |", "|---|---|---|---|---|---|",
    ]
    for i, cid in enumerate(material["order"], start=1):
        role = "对照" if cid in material["controls"] else "争议"
        row = material["blank_by_id"][cid]
        if row["should_refuse"]:
            layer = "拒答"
        elif row.get("query_type") == "cross_document":
            layer = "跨文档"
        else:
            layer = "答案"
        third = "reject" if cid in material["disputed"] else "confirmed"
        verdict = adj_by_cid[cid]["semantic_verdict"]
        lines.append(f"| {i} | {cid} | {role} | {layer} | {verdict} | "
                     f"{third} |")
    return "\n".join(lines) + "\n"


# ── 审计侧清单 / manifest ───────────────────────────────────────────

def _selection_manifest_dict(material: dict) -> dict:
    """审计侧选择清单（绝不进入模型输入）。"""
    return {
        "selection_algorithm": "sha256('v2-semantic-adjudication-v1:' + "
                               "case_id) 升序排序，取前 20 条",
        "control_salt": CONTROL_SALT,
        "control_count": len(material["controls"]),
        "disputed_count": len(material["disputed"]),
        "total_cases": len(material["order"]),
        "controls": material["controls"],
        "disputed": material["disputed"],
        "mapping": [{"index": i, "case_id": cid,
                     "role": "control" if cid in material["controls"]
                     else "disputed"}
                    for i, cid in enumerate(material["order"], start=1)],
        "note": "本清单仅保存在审计侧，绝不进入模型输入",
    }


def _manifest_dict(material: dict, blank_path: Path, filled_path: Path,
                   chunks_path: Path, prompt_sha: str, out_dir: Path,
                   comparison: dict, adjudication: dict,
                   n_chunks: int) -> dict:
    """主 manifest：模型名、prompt SHA、输入/输出 SHA、选择算法与计数。

    四个非自身输出按文件字节哈希；manifest.json 自身条目的 sha256 为其
    内容摘要（去掉 outputs 中自身条目后的规范 JSON），避免自引用环。
    """
    outputs = {name: {"sha256": _sha256_file(out_dir / name)}
               for name in OUTPUT_FILES if name != "manifest.json"}
    body = _manifest_body(material, blank_path, filled_path, chunks_path,
                          prompt_sha, out_dir, comparison, adjudication,
                          n_chunks, outputs)
    outputs["manifest.json"] = {
        "sha256": _sha256_text(json.dumps(body, ensure_ascii=False,
                                          sort_keys=True,
                                          separators=(",", ":"))),
        "note": "内容摘要（去掉 outputs 中自身条目后的规范 JSON）",
    }
    body["outputs"] = outputs
    return body


def _manifest_body(material: dict, blank_path: Path, filled_path: Path,
                   chunks_path: Path, prompt_sha: str, out_dir: Path,
                   comparison: dict, adjudication: dict, n_chunks: int,
                   outputs: dict) -> dict:
    return {
        "reviewer_model": REVIEWER_MODEL,
        "temperature": TEMPERATURE,
        "max_tokens": MAX_TOKENS,
        "prompt_sha256": prompt_sha,
        "selection": {
            "algorithm": "sha256('v2-semantic-adjudication-v1:' + case_id) "
                         "升序排序，取前 20 条",
            "control_salt": CONTROL_SALT,
            "control_count": len(material["controls"]),
            "disputed_count": len(material["disputed"]),
            "total_cases": len(material["order"]),
        },
        "inputs": {
            "blank_pack": {"path": str(Path(blank_path).resolve()),
                           "sha256": _sha256_file(blank_path),
                           "rows": len(material["blank_by_id"])},
            "filled_pack": {"path": str(Path(filled_path).resolve()),
                            "sha256": _sha256_file(filled_path),
                            "rows": len(material["filled_by_id"])},
            "chunks": {"path": str(Path(chunks_path).resolve()),
                       "sha256": _sha256_file(chunks_path),
                       "rows": n_chunks},
        },
        "outputs": outputs,
        "adjudication": {"decision_counts": adjudication["decision_counts"]},
        "retries": {"transport_retries_total":
                        adjudication["transport_retries_total"],
                    "transport_retries_max":
                        adjudication["transport_retries_max"],
                    "parse_retries_total":
                        adjudication["parse_retries_total"],
                    "parse_retries_max": adjudication["parse_retries_max"]},
        "comparison": comparison,
        "provider_note": PROVIDER_NOTE,
        "created_by": "corpus_v2_llm_semantic_adjudication.py run",
    }


# ── 主流程 ──────────────────────────────────────────────────────────

def run(blank_path: Path, filled_path: Path, chunks_path: Path,
        out_dir: Path, *, model: str = REVIEWER_MODEL,
        llm_fn: Callable | None = None,
        control_count: int = CONTROL_COUNT,
        expected_total: int = EXPECTED_TOTAL,
        expected_confirmed: int = EXPECTED_CONFIRMED,
        expected_reject: int = EXPECTED_REJECT,
        expected_followup: int = EXPECTED_FOLLOWUP) -> dict:
    """盲态仲裁全流程；任何 fail-closed 失败抛 AdjudicationError。

    先写盲包与审计侧选择清单（确定性输入），模型逐条仲裁全部合法后才写
    adjudications / manifest / comparison-report（比较结论）。
    """
    if model in FORBIDDEN_MODELS:
        raise AdjudicationError(f"forbidden model: {model}")
    if model != REVIEWER_MODEL:
        raise AdjudicationError(f"reviewer_model must be {REVIEWER_MODEL!r}, "
                                f"got {model!r}")
    material = _load_blind_material(
        blank_path, filled_path, chunks_path, control_count,
        expected_total=expected_total, expected_confirmed=expected_confirmed,
        expected_reject=expected_reject, expected_followup=expected_followup)
    order = material["order"]

    rows = [_blind_pack_row(material["blank_by_id"][cid],
                            material["chunk_texts"]) for cid in order]
    prompt_sha = _prompt_sha256(rows)

    out_dir.mkdir(parents=True, exist_ok=True)
    pack_path = out_dir / "blind-input-pack.jsonl"
    pack_path.write_text("\n".join(_line(r) for r in rows) + "\n",
                         encoding="utf-8")
    (out_dir / "selection-manifest.json").write_text(
        json.dumps(_selection_manifest_dict(material), ensure_ascii=False,
                   indent=1) + "\n", encoding="utf-8")

    if llm_fn is None:
        from src.llm_gateway import llm_call  # noqa: PLC0415
        llm_fn = llm_call

    adj_rows: list[dict] = []
    transport_total = 0
    transport_max = 0
    parse_total = 0
    for i, (cid, row) in enumerate(zip(order, rows), start=1):
        messages = [{"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": _line(row)}]
        chunk_ids = {c["chunk_id"] for c in row["chunks"]}
        n_points = len(row["acceptable_answer_points"])
        content, retries = _llm_content(llm_fn, messages, model, cid)
        parsed = _parse_adjudication(content, should_refuse=row["should_refuse"],
                                     chunk_ids=chunk_ids, n_points=n_points)
        parse_retries = 0
        # 最多两次纠正性重试（模型偶发空输出/非法结构），只要求输出合法 JSON
        while parsed is None and parse_retries < 2:
            messages = messages + [
                {"role": "assistant", "content": content},
                {"role": "user", "content": "你上一次的输出无法解析为合法 "
                                            "JSON。请只输出一个 JSON 对象，"
                                            "字段与枚举值必须与系统提示完全"
                                            "一致。"},
            ]
            content, retries2 = _llm_content(llm_fn, messages, model, cid)
            retries += retries2
            parse_retries += 1
            parsed = _parse_adjudication(
                content, should_refuse=row["should_refuse"],
                chunk_ids=chunk_ids, n_points=n_points)
        if parsed is None:
            raise AdjudicationError(
                f"{cid}: invalid decision output (unparseable or illegal "
                f"values) after {parse_retries} corrective retries; "
                f"last raw: {content[:200]!r}")
        transport_total += retries
        transport_max = max(transport_max, retries)
        parse_total += parse_retries
        adj_rows.append({
            "index": i,
            "semantic_verdict": parsed["semantic_verdict"],
            "verdict_rationale": parsed["verdict_rationale"],
            "answer_point_supports": parsed["answer_point_supports"],
            "refusal_assessment": parsed["refusal_assessment"],
            "refusal_evidence": parsed["refusal_evidence"],
            "model": model,
            "retries_used": retries,
            "parse_retries": parse_retries,
        })
        print(f"adjudicated {i}/{len(order)} {parsed['semantic_verdict']}",
              flush=True)

    if len(adj_rows) != len(order):
        raise AdjudicationError("adjudication coverage missing: "
                                f"{len(adj_rows)} != {len(order)}")

    (out_dir / ADJUDICATIONS_FILE).write_text(
        "\n".join(_line(a) for a in adj_rows) + "\n", encoding="utf-8")

    adj_by_cid = {cid: row for cid, row in zip(order, adj_rows)}
    comparison = _compute_comparison(material, adj_by_cid)
    (out_dir / "comparison-report.md").write_text(
        _comparison_md(material, adj_by_cid, comparison), encoding="utf-8")

    adjudication = {
        "decision_counts": {v: sum(1 for a in adj_rows
                                   if a["semantic_verdict"] == v)
                            for v in VERDICTS},
        "transport_retries_total": transport_total,
        "transport_retries_max": transport_max,
        "parse_retries_total": parse_total,
        "parse_retries_max": 2,
    }
    n_chunks = len(material["chunk_texts"])
    manifest = _manifest_dict(material, blank_path, filled_path, chunks_path,
                              prompt_sha, out_dir, comparison, adjudication,
                              n_chunks)
    (out_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=1) + "\n",
        encoding="utf-8")

    return {"n_cases": len(order),
            "n_disputed": len(material["disputed"]),
            "n_controls": len(material["controls"]),
            "comparison": comparison,
            "adjudication": adjudication}


# ── CLI ─────────────────────────────────────────────────────────────

def _flag(args: list[str], name: str, default: str | None) -> str | None:
    if name in args:
        return args[args.index(name) + 1]
    return default


def main(argv: list[str] | None = None) -> int:
    args = list(argv if argv is not None else sys.argv[1:])
    out = Path(_flag(args, "--out", str(DEFAULT_OUT)) or str(DEFAULT_OUT))
    try:
        summary = run(DEFAULT_BLANK_PACK, DEFAULT_FILLED_PACK,
                      DEFAULT_CHUNKS, out)
    except AdjudicationError as exc:
        print(f"FAILED: {exc}")
        return 2
    print(f"adjudicated {summary['n_cases']} cases "
          f"({summary['adjudication']['decision_counts']}) -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
