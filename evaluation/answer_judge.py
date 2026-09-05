"""M3 答案级评测线：受约束 LLM judge 的判定协议与聚合（方案 B 阶段 3）。

定位（章程 §四方案 B）
----------------------
M2 机械下界（containment）只判文本规范化包含，同义改写/中英互译/
指代变换型要点系统性漏判。M3 只对机械未命中的要点（M2 ``verdict ==
"miss"``，154 个）引入受约束 LLM judge 二次判定，并把 judge 自身的
**契约错误率**作为被测对象如实统计。

judge 只读 answer + point（判定答案覆盖）——证据覆盖由 faithfulness
承担（章程批示：judge 不读 context）。

协议（owner 批示逐条实现，禁止自由发挥）
----------------------------------------
1. 单要点一次调用：system 判定语义 + 答案全文 + 要点文本；输出要求
   ``{"verdict": "hit"|"miss"|"partial", "evidence": "<答案原文片段>"}``；
   ``max_tokens=500``。
2. 判定语义（``JUDGE_SYSTEM_PROMPT`` 逐字）：hit = 实质上完整表达
   （允许同义改写/中英互译/指代回指，不要求字面）；partial = 表达了
   主体但缺重要修饰/条件/一半内容；miss = 未表达要点实质内容，
   **答案整体为拒答或「语料没有提到 X」式语义陈述时要点一律 miss**
   （诚实不等于覆盖）。
3. 程序化校验（fail-closed，一个行为一个测试）：
   - verdict ∈ 外置词表 ``JUDGE_VERDICTS``（单一事实源，禁止字符串散落）；
   - evidence 非空，且空白归一后是答案归一文本的连续子串
     （containment 族口径，与机械指标一致）；
   - JSON 解析成功。
   任一不满足 → 重试（≤2 次，共 ≤3 次尝试；重试提示附上次失败原因）；
   仍失败 → ``contract_error=true``，**按 miss 计入**，单独披露
   ``contract_error_rate``。
4. 网关失败（超时/取消/网络）视为一次失败尝试（重试路径），不退出。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Callable

from evaluation.answer_metrics import normalize_for_containment
from src.llm_gateway import llm_call_safe

# ── 协议常量（单一事实源）─────────────────────────────────────────

# 外置词表：judge verdict 三值枚举（禁止在别处散落字符串字面量）
JUDGE_VERDICTS = ("hit", "miss", "partial")

JUDGE_MAX_TOKENS = 500
JUDGE_MAX_ATTEMPTS = 3

# 判定语义：owner 批示逐字（含「拒答/语义式陈述一律 miss」红线）
JUDGE_SYSTEM_PROMPT = """你是答案要点覆盖判定器。给定一个问答对的“答案全文”与一个“答案要点”，判定答案是否覆盖该要点。

判定语义（严格按此执行）：
- hit = 答案实质上完整表达要点（允许同义改写、中英互译、指代回指，不要求字面）；
- partial = 表达了主体但缺重要修饰/条件/一半内容；
- miss = 未表达要点实质内容。答案整体为拒答或“语料没有提到 X”式语义陈述时，要点一律 miss（诚实不等于覆盖）。

输出必须是单个 JSON 对象，且不含任何其他文本：
{"verdict": "hit"|"miss"|"partial", "evidence": "<答案原文片段>"}

要求：
- verdict 只能是 hit / miss / partial 三者之一；
- evidence 必须是非空字符串，且必须是从答案原文中逐字摘出的连续片段（允许空白规范化后匹配，即多个空格/换行折叠后仍为答案文本的连续子串）。"""


class JudgeContractError(Exception):
    """judge 输出违反协议契约（JSON/词表/evidence 校验失败）。

    这是被测对像：contract_error 率单独披露，绝不静默吞掉。
    """


@dataclass(frozen=True)
class JudgeParsedResponse:
    """校验通过的 judge 响应。"""

    verdict: str
    evidence: str


@dataclass(frozen=True)
class JudgePointResult:
    """单个要点的 judge 判定明细（逐要点一行落盘）。

    ``judge_verdict=None`` 且 ``contract_error=True`` 表示协议重试耗尽，
    该要点按 miss 计入（但不进三态分布，单独披露契约错误率）。
    """

    case_id: str
    query_type: str
    point_text: str
    mechanical_verdict: str  # 恒 "miss"（judge 面精确收窄：只判机械未命中）
    judge_verdict: str | None
    evidence: str | None
    attempts: int
    contract_error: bool
    should_refuse: bool = False


# ── 校验（纯函数，fail-closed）───────────────────────────────────

def parse_judge_response(text: str, answer: str) -> JudgeParsedResponse:
    """解析并校验 judge 输出；任一契约违反抛 JudgeContractError。

    校验链：JSON 解析成功 → verdict ∈ 外置词表 → evidence 非空 →
    evidence 为答案归一文本的连续子串（containment 族口径）。
    """
    try:
        obj = json.loads(text)
    except json.JSONDecodeError as exc:
        raise JudgeContractError(f"JSON 解析失败: {exc}") from exc
    if not isinstance(obj, dict):
        raise JudgeContractError("输出不是 JSON 对象")

    verdict = obj.get("verdict")
    if verdict not in JUDGE_VERDICTS:
        raise JudgeContractError(
            f"verdict 词表外: {verdict!r}（允许 {JUDGE_VERDICTS}）")

    evidence = obj.get("evidence")
    if not isinstance(evidence, str) or not evidence.strip():
        raise JudgeContractError("evidence 为空")

    norm_answer = normalize_for_containment(answer)
    norm_evidence = normalize_for_containment(evidence)
    if not norm_evidence:
        raise JudgeContractError("evidence 归一后为空")
    if norm_evidence not in norm_answer:
        raise JudgeContractError(
            "evidence 不是答案文本的连续子串（containment 族校验失败）")

    return JudgeParsedResponse(verdict=verdict, evidence=evidence)


# ── 调用骨架（重试协议）──────────────────────────────────────────

def build_judge_messages(
    answer: str,
    point_text: str,
    last_failure: str | None = None,
) -> list[dict[str, str]]:
    """构建 judge 调用消息：system 判定语义 + 答案全文 + 要点文本。

    重试时附上次失败原因（可审计：提示里明确告诉 judge 哪里违约）。
    """
    messages: list[dict[str, str]] = [
        {"role": "system", "content": JUDGE_SYSTEM_PROMPT},
        {"role": "user", "content":
            f"【答案全文】\n{answer}\n\n【待判定要点】\n{point_text}"},
    ]
    if last_failure:
        messages.append({"role": "user", "content":
            f"上次输出无效：{last_failure}。"
            "请重新输出单个合法 JSON 对象（verdict ∈ hit/miss/partial；"
            "evidence 非空且为答案原文连续片段）。"})
    return messages


def _default_llm_call(messages: list[dict[str, str]], max_tokens: int) -> str | None:
    """默认网关调用：call_type="judge"（登记进网关调用记录）。

    llm_call_safe 不抛异常：网关失败（超时/取消/网络）返回 (None, record)，
    由 judge 重试协议按一次失败尝试处理。
    """
    content, _record = llm_call_safe(
        "judge", messages=messages, max_tokens=max_tokens)
    return content


def judge_point_with_llm(
    answer: str,
    point_text: str,
    *,
    call_fn: Callable[[list[dict[str, str]], int], str | None] | None = None,
) -> JudgePointResult:
    """单要点 judge：≤3 次尝试（协议层重试），失败回 contract_error。

    ``call_fn`` 供测试注入（mock 网关）；None 时走 ``llm_call_safe``
    真实调用（call_type="judge"）。
    """
    if call_fn is None:
        call_fn = _default_llm_call

    attempts = 0
    last_failure: str | None = None
    for attempt in range(1, JUDGE_MAX_ATTEMPTS + 1):
        attempts = attempt
        messages = build_judge_messages(answer, point_text, last_failure)
        content = call_fn(messages, max_tokens=JUDGE_MAX_TOKENS)
        if content is None:
            # 网关失败（超时/取消/网络）——协议重试路径，不退出
            last_failure = "LLM 调用失败（超时/取消/网络错误）"
            continue
        try:
            parsed = parse_judge_response(content, answer)
        except JudgeContractError as exc:
            last_failure = str(exc)
            continue
        return JudgePointResult(
            case_id="",
            query_type="",
            point_text=point_text,
            mechanical_verdict="miss",
            judge_verdict=parsed.verdict,
            evidence=parsed.evidence,
            attempts=attempts,
            contract_error=False,
        )

    return JudgePointResult(
        case_id="",
        query_type="",
        point_text=point_text,
        mechanical_verdict="miss",
        judge_verdict=None,
        evidence=None,
        attempts=attempts,
        contract_error=True,
    )


# ── 聚合（纯函数，两个修正口径公式）─────────────────────────────

def aggregate_judge_results(
    m2_rows: list[dict[str, Any]],
    judge_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    """从 M2 机械结果 + judge 行聚合修正口径与分歧率。

    口径（owner 批示）：
    - 修正命中率(partial 计 0.5) = (mech_hit + X + 0.5*Y) / total_points；
    - 保守修正(partial 计 0) = (mech_hit + X) / total_points；
    - 分歧率 = (X + Y) / judged_count（机械下界低估量的直接度量）；
    - contract_error_rate = W / judged_count（W 按 miss 计入但不进分子）。
    X/Y/Z/W 恒满足 X + Y + Z + W == judged_count。
    """
    mech_hit = sum(
        (r.get("answer_hit") or {}).get("hit_count", 0) for r in m2_rows)
    total_points = sum(
        (r.get("answer_hit") or {}).get("effective_point_count", 0)
        for r in m2_rows)

    judged_count = len(judge_rows)
    count_hit = sum(
        1 for r in judge_rows if r["judge_verdict"] == "hit"
        and not r["contract_error"])
    count_partial = sum(
        1 for r in judge_rows if r["judge_verdict"] == "partial"
        and not r["contract_error"])
    count_contract_error = sum(
        1 for r in judge_rows if r["contract_error"])
    count_miss = sum(
        1 for r in judge_rows if r["judge_verdict"] == "miss"
        and not r["contract_error"])
    # 不变式：X + Y + Z + W == judged_count（防静默丢行）
    assert count_hit + count_partial + count_miss + count_contract_error == judged_count, \
        "judge 行聚合不变式破坏（X+Y+Z+W != judged）"

    def _safe_div(n: int, d: int) -> float | None:
        return n / d if d else None

    by_query_type: dict[str, dict[str, int]] = {}
    for r in judge_rows:
        qt = r["query_type"]
        bucket = by_query_type.setdefault(qt, {
            "hit": 0, "partial": 0, "miss": 0, "contract_error": 0})
        if r["contract_error"]:
            bucket["contract_error"] += 1
        else:
            bucket[r["judge_verdict"]] += 1

    no_answer_required = [
        {
            "case_id": r["case_id"],
            "point_text": r["point_text"],
            "judge_verdict": r["judge_verdict"],
            "contract_error": r["contract_error"],
            "evidence": r.get("evidence"),
        }
        for r in judge_rows
        if r["query_type"] == "no_answer" and not r["should_refuse"]
    ]

    return {
        "mechanical_hit_count": mech_hit,
        "total_points": total_points,
        "mechanical_rate": _safe_div(mech_hit, total_points),
        "judged_count": judged_count,
        "count_hit": count_hit,
        "count_partial": count_partial,
        "count_miss": count_miss,
        "count_contract_error": count_contract_error,
        # 修正口径两份（不作门禁/不作优劣结论）
        "corrected_rate_partial_05": _safe_div(
            mech_hit + count_hit + 0.5 * count_partial, total_points),
        "corrected_rate_partial_0": _safe_div(
            mech_hit + count_hit, total_points),
        "divergence_count": count_hit + count_partial,
        "divergence_rate": _safe_div(count_hit + count_partial, judged_count),
        "contract_error_rate": _safe_div(count_contract_error, judged_count),
        "by_query_type": by_query_type,
        "no_answer_required": no_answer_required,
    }
