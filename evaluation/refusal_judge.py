"""M5b 答案级评测线：拒答判定的语义测量协议（al3-refusal-judge-v1.1）。

定位
----
`compute_refusal_accuracy`（词表口径）只做 12 个固定短语的子串匹配——
M5b 侦查证实：臂2 的 28 探针答案**语义 28/28 正确拒答**（人工逐条核验），
但词表仅命中 5 例（「没有/未提及/并未定义/无法确认/无法找到」不在词表）。
本模块提供语义口径的重测量协议，把「拒答正确性」的判定从短语匹配升级为
受约束的 LLM 判定，并沿用 al2 的 fail-closed 契约模式。

版本历史（如实披露）
--------------------
- **v1**：首版。三基线读数（M2=1.0 / 臂1=0.8929 / 臂2=0.9286）后人工核查发现
  **2/28 系统性误判**：对「否定 + 解释/引证该否定」型答案（noanswer-038/042）
  误判为 answered。产物保留于 `m5b-{m2,arm1,arm2}-refusal-judge-2026-09-06`。
- **v1.1**：判定语义增补「否定 + 解释该否定 = refused」条款（见
  ``REFUSAL_JUDGE_SYSTEM_PROMPT`` 关键区分第 4 条）；协议逻辑与校验链不变。

协议（al3-refusal-judge-v1.1，与 al2 同族）
-------------------------------------------
1. 单探针一次调用：system 判定语义 + 查询 + 答案全文；输出
   ``{"verdict": "refused"|"answered", "evidence": "<答案原文片段>"}``；
   ``max_tokens=500``。
2. 判定语义：refused = 答案以任何措辞表达了「语料/文档中没有该信息、
   无法确认、未定义、未提供」等拒答语义（含否定式陈述，不要求出现固定
   拒答短语）；answered = 答案对该问题给出了实质性的肯定/否定事实回答。
3. 程序化校验（fail-closed）：verdict ∈ 外置词表；evidence 非空且为答案
   文本的标点/空白不敏感连续子串；JSON 解析成功。任一违反 → 重试 ≤2
   （共 ≤3）→ 仍失败 ``contract_error=true``，**按「未正确拒答」计入**
   （保守），单独披露契约错误率。
4. 网关失败（超时/取消/网络）计一次失败尝试，不退出。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Callable

from evaluation.answer_metrics import normalize_for_containment
from src.llm_gateway import llm_call_safe

# ── 协议常量（单一事实源）─────────────────────────────────────────

REFUSAL_JUDGE_PROTOCOL_VERSION = "al3-refusal-judge-v1.1"

# 外置词表：拒答语义判定二值（禁止在别处散落字符串字面量）
REFUSAL_VERDICTS = ("refused", "answered")

JUDGE_MAX_TOKENS = 500
JUDGE_MAX_ATTEMPTS = 3

REFUSAL_JUDGE_SYSTEM_PROMPT = """你是拒答语义判定器。给定一个“用户查询”与系统的“答案全文”，判定该答案是否属于拒答。

判定语义（严格按此执行）：
- refused = 答案以任何措辞表达了「语料/文档中没有该信息、无法确认、未定义、未提供、未提及」等拒答语义（允许否定式陈述，例如「文档中没有 X」「并未定义 Y」「无法确认是否存在 Z」「术语表中没有 W 的条目」，不要求出现固定拒答短语）；
- answered = 答案对该问题给出了实质性的肯定或否定事实回答（例如「是的，文档提到 X」「不是，文档说的是 Y」），即使该事实可能错误，只要不是「无法从语料确认」的拒答语义即算 answered。

关键区分：
- 「文档中没有提到 X」= refused（拒绝提供 X 的答案）；
- 「文档中没有提到 X，但是……（给出 X 相关的实质内容）」= answered（提供了实质内容）；
- 纯列举文档内容后说「因此无法回答」= refused；
- **「否定 + 解释/引证该否定本身」= refused**：例如「RFC 3986 没有定义 about: scheme。
  文档指出 Individual schemes are not specified by this document……因此 RFC 3986
  只定义通用语法，不涉及特定方案」——后续内容是**对「没有」的论证**，不是该问题的
  实质答案，仍判 refused；判定 answered 要求答案提供了问题所问对象的实质内容
  （如「是的，文档提到 X 的用法是……」「不是，文档说的是 Y」）。

输出必须是单个 JSON 对象，且不含任何其他文本：
{"verdict": "refused"|"answered", "evidence": "<答案原文片段>"}

要求：
- verdict 只能是 refused / answered 二者之一；
- evidence 必须是非空字符串，且必须是从答案原文中逐字摘出的连续片段（允许空白规范化后匹配）。"""


class RefusalJudgeContractError(Exception):
    """al3 judge 输出违反协议契约（JSON/词表/evidence 校验失败）。"""


@dataclass(frozen=True)
class RefusalParsedResponse:
    """校验通过的 al3 judge 响应。"""

    verdict: str
    evidence: str


@dataclass(frozen=True)
class RefusalJudgeResult:
    """单个探针的拒答语义判定明细（逐探针一行落盘）。

    ``semantic_verdict=None`` 且 ``contract_error=True`` 表示协议重试耗尽，
    该探针按「未正确拒答」计入（保守），单独披露契约错误率。
    """

    case_id: str
    query: str
    semantic_verdict: str | None
    evidence: str | None
    attempts: int
    contract_error: bool
    should_refuse: bool = True
    # 词表口径对照（同探针，来自既有密封产物）
    lexical_verdict: bool | None = None


# ── 校验（纯函数，fail-closed）───────────────────────────────────

def _alnum_only(text: str) -> str:
    """归一化后仅保留字母/数字/CJK（al3 evidence 匹配口径）。

    ``normalize_for_containment`` 只做小写化 + 空白折叠，不剥离标点与
    markdown 标记；judge 摘录时自然省略这些字符，逐字匹配会系统性误报
    契约错误（M5b 冒烟 RED 证据：noanswer-026 三次尝试全失败）。
    """
    return "".join(ch for ch in normalize_for_containment(text) if ch.isalnum())


def evidence_in_answer(evidence: str, answer: str) -> bool:
    """al3 evidence 校验：标点/空白不敏感的 containment。

    判定目的：确认「证据确实摘录自答案原文」。空白、标点、markdown 标记
    （``**``、`` ` ``）与大小写差异不改变这一事实，故比对在「仅保留字母
    数字/CJK」的域内进行。仍拒绝凭空编造的 evidence（其字符序列不在答案中）。
    """
    norm_evidence = _alnum_only(evidence)
    return bool(norm_evidence) and norm_evidence in _alnum_only(answer)


def parse_refusal_response(text: str, answer: str) -> RefusalParsedResponse:
    """解析并校验 al3 judge 输出；任一契约违反抛 RefusalJudgeContractError。"""
    try:
        obj = json.loads(text)
    except json.JSONDecodeError as exc:
        raise RefusalJudgeContractError(f"JSON 解析失败: {exc}") from exc
    if not isinstance(obj, dict):
        raise RefusalJudgeContractError("输出不是 JSON 对象")

    verdict = obj.get("verdict")
    if verdict not in REFUSAL_VERDICTS:
        raise RefusalJudgeContractError(
            f"verdict 词表外: {verdict!r}（允许 {REFUSAL_VERDICTS}）")

    evidence = obj.get("evidence")
    if not isinstance(evidence, str) or not evidence.strip():
        raise RefusalJudgeContractError("evidence 为空")

    if not evidence_in_answer(evidence, answer):
        raise RefusalJudgeContractError(
            "evidence 不是答案文本的连续子串（空白不敏感 containment 校验失败）")

    return RefusalParsedResponse(verdict=verdict, evidence=evidence)


# ── 调用骨架（重试协议）──────────────────────────────────────────

def build_refusal_messages(
    query: str,
    answer: str,
    last_failure: str | None = None,
) -> list[dict[str, str]]:
    """构建 al3 调用消息：system 判定语义 + 查询 + 答案全文。"""
    messages: list[dict[str, str]] = [
        {"role": "system", "content": REFUSAL_JUDGE_SYSTEM_PROMPT},
        {"role": "user", "content":
            f"【用户查询】\n{query}\n\n【答案全文】\n{answer}"},
    ]
    if last_failure:
        messages.append({"role": "user", "content":
            f"上次输出无效：{last_failure}。"
            "请重新输出单个合法 JSON 对象（verdict ∈ refused/answered；"
            "evidence 非空且为答案原文连续片段）。"})
    return messages


def _default_llm_call(messages: list[dict[str, str]], max_tokens: int) -> str | None:
    """默认网关调用：call_type="refusal_judge"（与 al2 的 "judge" 分开登记）。"""
    content, _record = llm_call_safe(
        "refusal_judge", messages=messages, max_tokens=max_tokens)
    return content


def judge_refusal_with_llm(
    query: str,
    answer: str,
    *,
    call_fn: Callable[[list[dict[str, str]], int], str | None] | None = None,
) -> tuple[str | None, str | None, int, bool]:
    """单探针拒答语义判定：≤3 次尝试，失败回 contract_error。

    Returns:
        (semantic_verdict, evidence, attempts, contract_error)
    """
    if call_fn is None:
        call_fn = _default_llm_call

    attempts = 0
    last_failure: str | None = None
    for attempt in range(1, JUDGE_MAX_ATTEMPTS + 1):
        attempts = attempt
        messages = build_refusal_messages(query, answer, last_failure)
        content = call_fn(messages, max_tokens=JUDGE_MAX_TOKENS)
        if content is None:
            last_failure = "LLM 调用失败（超时/取消/网络错误）"
            continue
        try:
            parsed = parse_refusal_response(content, answer)
        except RefusalJudgeContractError as exc:
            last_failure = str(exc)
            continue
        return parsed.verdict, parsed.evidence, attempts, False

    return None, None, attempts, True


# ── 聚合 ─────────────────────────────────────────────────────────

def aggregate_refusal_results(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """聚合 al3 判定：语义拒答正确率 + 词表口径对照 + 契约错误率。

    契约错误行按「未正确拒答」计入语义正确数（保守）。
    """
    n = len(rows)
    if n == 0:
        return {
            "probe_count": 0,
            "semantic_correct": 0,
            "semantic_refusal_accuracy": None,
            "lexical_correct": 0,
            "lexical_refusal_accuracy": None,
            "contract_error_count": 0,
            "contract_error_rate": None,
            "disagreement_count": 0,
        }

    semantic_correct = sum(
        1 for r in rows if r.get("semantic_verdict") == "refused")
    contract_errors = sum(1 for r in rows if r.get("contract_error"))
    lexical_correct = sum(1 for r in rows if r.get("lexical_verdict") is True)
    disagreement = sum(
        1 for r in rows
        if (r.get("semantic_verdict") == "refused") != (r.get("lexical_verdict") is True)
    )
    return {
        "probe_count": n,
        "semantic_correct": semantic_correct,
        "semantic_refusal_accuracy": round(semantic_correct / n, 4),
        "lexical_correct": lexical_correct,
        "lexical_refusal_accuracy": round(lexical_correct / n, 4),
        "contract_error_count": contract_errors,
        "contract_error_rate": round(contract_errors / n, 4),
        "disagreement_count": disagreement,
    }
