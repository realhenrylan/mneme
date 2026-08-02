"""History-aware standalone query rewrite — 多轮检索改写。

将省略主语的追问（如"它的作者是谁？"）改写为独立可检索问题，
同时保留原查询作为保底召回路径，防止改写漂移。

设计原则：
1. 上下文消歧：利用最近 5 轮历史，将代词/省略主语补全
2. 漂移防护：原 query 始终保留一路召回，与 rewrite 结果合并去重
3. 简单查询跳过：无历史或原查询已独立时不调 LLM
4. 记录 rewrite 文本与原查询的结果覆盖差异（通过 rewrite_log）
"""

import os
import re
from dotenv import load_dotenv
from src.security import endpoint_validation_error, validate_endpoint

load_dotenv()

# ── 改写 prompt ──
REWRITE_PROMPT = """You are a query rewriter for a RAG retrieval system.
Given the conversation history and the current follow-up question, rewrite
the follow-up into a **standalone** question that can be understood and
searched WITHOUT any prior context.

Rules:
1. Resolve pronouns and omitted subjects using the conversation history.
2. Do NOT add information that is not present in the history or the question.
3. If the question is already standalone (no pronouns, no omitted context),
   return it unchanged.
4. Return ONLY the rewritten question as a plain string. No quotes, no markdown, no explanation.

Examples:
  History: Q: "What is DSpark?" A: "DSpark is a distributed computing framework..."
  Follow-up: "它的作者是谁？"
  -> "DSpark的作者是谁？"

  History: Q: "Tell me about LLMs for mobility" A: "..."
  Follow-up: "What are the main contributions?"
  -> "What are the main contributions of LLMs for mobility?"

  History: (empty)
  Follow-up: "What is machine learning?"
  -> "What is machine learning?"
"""

# ── 不需要改写的情况 ──
# 代词/省略主语指示词（中英文）
_PRONOUN_PATTERNS = re.compile(
    r'(?:它|他|她|这个|那个|这|那|其|上面|前面|刚才|刚刚|之前|上文|前文)'
    r'|(?:it|this|that|these|those|he|she|they|the above|the previous|earlier)',
    re.IGNORECASE,
)


def should_rewrite(query: str, history: list[tuple[str, str]] | None) -> bool:
    """判断是否需要改写。

    跳过条件：
    - 无历史（第一轮对话）
    - 历史为空列表
    - 查询过短（≤2 字）
    - 查询中无代词/省略指示词且看起来已独立
    """
    if not history or len(history) == 0:
        return False
    query = query.strip()
    if len(query) <= 2:
        return False
    # 包含代词/省略指示词 → 需要改写
    if _PRONOUN_PATTERNS.search(query):
        return True
    # 以疑问词开头且无明确主语 → 可能需要改写
    # 例如"有哪些方法？"但历史讨论了特定主题
    _QUESTION_STARTERS = re.compile(
        r'^(?:怎么|如何|为什么|哪些|有什么|有哪些|能不能|可以|是否|为啥|为啥子)',
    )
    if _QUESTION_STARTERS.match(query):
        return True
    return False


def rewrite_query_llm(
    query: str,
    history: list[tuple[str, str]] | None = None,
    model: str = "deepseek-chat",
    temperature: float = 0.0,
    max_retries: int = 2,
) -> tuple[str, dict]:
    """History-aware standalone query rewrite。

    返回 (rewritten_query, rewrite_log)：
    - rewritten_query: 改写后的独立查询；不需要改写时返回原 query
    - rewrite_log: 改写日志，含 original、rewritten、changed 等字段
    """
    rewrite_log: dict = {
        "original": query,
        "rewritten": query,
        "changed": False,
        "reason": "no_rewrite_needed",
    }

    if not should_rewrite(query, history):
        return query, rewrite_log

    api_key = os.getenv("API_KEY")
    base_url = os.getenv("BASE_URL")
    if not api_key or not base_url:
        rewrite_log["reason"] = "no_api_key"
        return query, rewrite_log
    if endpoint_validation_error(base_url):
        rewrite_log["reason"] = "invalid_endpoint"
        return query, rewrite_log

    # 构建历史上下文（最近 5 轮）
    history_text = ""
    for q, a in (history or [])[-5:]:
        history_text += f"Q: {q}\nA: {a}\n"

    from src.llm_gateway import llm_call_safe
    content, record = llm_call_safe(
        call_type="rewrite",
        messages=[
            {"role": "system", "content": REWRITE_PROMPT},
            {"role": "user", "content": (
                f"History:\n{history_text}\n"
                f"Follow-up: {query}"
            )},
        ],
        model=model,
        temperature=temperature,
        max_tokens=200,
        timeout=15,
        max_retries=max_retries,
    )

    if content is None:
        rewrite_log["reason"] = "llm_failed"
        return query, rewrite_log

    # 清理 markdown 包裹
    content = re.sub(r'^["\']', '', content)
    content = re.sub(r'["\']$', '', content)
    content = re.sub(r'^```(?:json)?\s*', '', content)
    content = re.sub(r'\s*```$', '', content)

    if content and content != query:
        rewrite_log["rewritten"] = content
        rewrite_log["changed"] = True
        rewrite_log["reason"] = "llm_rewrite"
        return content, rewrite_log

    # LLM 返回原 query 或空 → 不改写
    rewrite_log["reason"] = "llm_returned_unchanged"
    return query, rewrite_log


def merge_rewrite_results(
    original_indices: list[int],
    original_scores: dict[int, float],
    rewrite_indices: list[int],
    rewrite_scores: dict[int, float],
) -> tuple[list[int], dict[int, float], dict]:
    """合并原查询与改写查询的检索结果，去重取最优分数。

    返回 (merged_indices, merged_scores, merge_log)。
    merge_log 记录覆盖差异：rewrite_only（仅改写召回）、original_only（仅原查询召回）。
    """
    merged_scores: dict[int, float] = {}
    for idx, score in original_scores.items():
        merged_scores[idx] = score
    for idx, score in rewrite_scores.items():
        if idx in merged_scores:
            merged_scores[idx] = max(merged_scores[idx], score)
        else:
            merged_scores[idx] = score

    # 按分数降序排列
    merged_indices = sorted(merged_scores, key=lambda i: merged_scores[i], reverse=True)

    # 记录覆盖差异
    original_set = set(original_indices)
    rewrite_set = set(rewrite_indices)
    merge_log: dict = {
        "original_count": len(original_set),
        "rewrite_count": len(rewrite_set),
        "merged_count": len(merged_indices),
        "rewrite_only": sorted(rewrite_set - original_set),
        "original_only": sorted(original_set - rewrite_set),
        "overlap_count": len(original_set & rewrite_set),
    }

    return merged_indices, merged_scores, merge_log
