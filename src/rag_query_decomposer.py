"""LLM 驱动的查询拆解。"""

import json
import re
import os
from dotenv import load_dotenv
from src.security import endpoint_validation_error, validate_endpoint

load_dotenv()

DECOMPOSE_PROMPT = """You are a query rewriter for a RAG system.
Decompose the user query into 1-3 sub-queries that, when searched
independently, will retrieve all the information needed.

Rules:
1. If the query contains both a TOPIC and a specific METADATA/ATTRIBUTE
   question, split them into separate sub-queries.
2. If the query mixes Chinese and English, split by language boundary.
   Use ONLY words that appear in the original query — do NOT add new
   keywords or topic expansions.
3. If the query is already simple, return a single sub-query (unchanged).
4. Return ONLY a JSON array of strings. No markdown, no explanation.

Examples:
  "LLMs for mobility这篇文章的作者都属于什么学校？"
  -> ["LLMs for mobility",
     "作者都属于什么学校或者科研机构？"]

  "这篇论文讲了什么？"
  -> ["这篇论文讲了什么？"]

  "DSpark 论文的主要贡献和作者分别是什么？"
  -> ["DSpark 论文的主要贡献", "DSpark 作者和机构"]"""


def should_decompose(query: str) -> bool:
    """KISS guard：简单查询不调 LLM。

    跳过条件（任一满足即跳过）：
    1. 查询 ≤4 字
    2. 单个英文单词
    3. 中文简单问题：不含多意图关键词、不含中英混合、不含复杂标点分隔
    """
    query = query.strip()
    if len(query) <= 4:
        return False
    if len(query.split()) == 1 and not re.search(r'[\u4e00-\u9fff]', query):
        return False  # single English word, no need to decompose

    # ── 中文简单问题守卫 ──
    # 含中文字符的查询，如果满足以下全部条件则跳过拆解：
    # 1. 不含多意图关键词（和、与、及、以及、分别、同时、另外、还有）
    # 2. 不含中英混合（中文+英文单词共存）
    # 3. 不含复杂分隔符（；、分号分隔的多子句）
    has_cjk = bool(re.search(r'[\u4e00-\u9fff]', query))
    if has_cjk:
        # 多意图关键词
        _MULTI_INTENT = re.compile(
            r'(?:和|与|及|以及|分别|同时|另外|还有|以及|并且|而且|或是|还是|、)',
        )
        if _MULTI_INTENT.search(query):
            return True  # 可能有多意图，需要拆解

        # 中英混合：同时含中文和英文单词（≥2字母）
        has_english_word = bool(re.search(r'[a-zA-Z]{2,}', query))
        if has_english_word:
            return True  # 中英混合，可能需要拆解

        # 复杂分隔符
        if '；' in query or ';' in query:
            return True  # 分号分隔多子句

        # 简单中文问题，不需要拆解
        return False

    return True


def decompose_query_llm(
    query: str,
    model: str = "deepseek-chat",
    temperature: float = 0.0,
    max_retries: int = 2,
) -> list[str]:
    """LLM 驱动的查询拆解。

    拆解为 1-3 个子查询。失败时重试，仍失败则返回 [query]。
    通过统一 LLM Gateway 调用，享受 timeout、retry、错误分类等能力。
    """
    if not should_decompose(query):
        return [query]

    api_key = os.getenv("API_KEY")
    base_url = os.getenv("BASE_URL")
    if not api_key or not base_url:
        return [query]
    if endpoint_validation_error(base_url):
        return [query]

    from src.llm_gateway import llm_call_safe
    content, record = llm_call_safe(
        call_type="decompose",
        messages=[
            {"role": "system", "content": DECOMPOSE_PROMPT},
            {"role": "user", "content": f"Query: {query}"},
        ],
        model=model,
        temperature=temperature,
        max_tokens=150,
        timeout=30,
        max_retries=max_retries,
    )

    if content is None:
        return [query]  # LLM 调用失败，降级

    # 清理 markdown 包裹
    content = re.sub(r'^```(?:json)?\s*', '', content)
    content = re.sub(r'\s*```$', '', content)
    try:
        sub_queries = json.loads(content)
        if isinstance(sub_queries, list) and len(sub_queries) > 0:
            return sub_queries
    except json.JSONDecodeError:
        pass
    return [query]  # fallback
