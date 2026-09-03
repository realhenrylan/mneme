"""M2 答案级基线报告：拒答三形态分类器与报告生成辅助。

三形态拒答操作化定义（M2 批示口径）
-----------------------------------
对 should_refuse 真值例（28 探针）按生成输出形态分列：

1. ``sentinel_refusal``（前哨拒答）：context 零证据（``len(context)==0``，
   生产检索零证据快速路径，未进 context 即被拒绝）且输出拒答消息形态；
2. ``post_generation_refusal``（生成后拒答）：context 非空（证据进场），
   输出为拒答消息形态（``REFUSAL_INDICATORS`` 词表命中）；
3. ``semantic_statement``（语义式陈述）：输出实质表示「语料未覆盖/
   没有介绍 X」的中性陈述，词表未命中——不是拒答消息形态，但语义上
   未回答问题（M1 探针 0/2 为此形态）。

其余（should_refuse=False 且词表未命中）归 ``not_refusal``。

口径注明：形态判定建立在 refusal 词表命中 + context 长度上，非 LLM
裁定；词表外语义等价输出会被归入 semantic_statement（如实披露，不作
优劣裁决）。
"""

from __future__ import annotations

from evaluation.citation_metrics import REFUSAL_INDICATORS


def _refusal_message_hit(answer: str) -> bool:
    """拒答消息形态判定：词表任一指示语出现在答案小写文本中。"""
    answer_lower = answer.lower()
    return any(ind in answer_lower for ind in REFUSAL_INDICATORS)


def classify_refusal_form(
    *,
    should_refuse: bool,
    answer: str,
    context: str,
) -> str:
    """按操作化定义归一类生成输出的拒答形态（见模块 docstring）。"""
    if not should_refuse:
        return "not_refusal"

    if _refusal_message_hit(answer):
        if not context:
            return "sentinel_refusal"
        return "post_generation_refusal"
    return "semantic_statement"
