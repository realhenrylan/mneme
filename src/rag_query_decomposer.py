"""LLM 驱动的查询拆解。"""

import json
import re
import os
from dotenv import load_dotenv
from openai import OpenAI

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
    """KISS guard：简单查询不调 LLM"""
    query = query.strip()
    if len(query) <= 4:
        return False
    if len(query.split()) == 1 and not re.search(r'[\u4e00-\u9fff]', query):
        return False  # single English word, no need to decompose
    return True


def decompose_query_llm(
    query: str,
    model: str = "deepseek-chat",
    temperature: float = 0.0,
    max_retries: int = 2,
) -> list[str]:
    """LLM 驱动的查询拆解。

    拆解为 1-3 个子查询。失败时重试，仍失败则返回 [query]。
    """
    if not should_decompose(query):
        return [query]

    api_key = os.getenv("API_KEY")
    base_url = os.getenv("BASE_URL")
    if not api_key or not base_url:
        return [query]

    for attempt in range(max_retries):
        try:
            client = OpenAI(api_key=api_key, base_url=base_url)
            response = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": DECOMPOSE_PROMPT},
                    {"role": "user", "content": f"Query: {query}"},
                ],
                temperature=temperature,
                max_tokens=150,
                timeout=30,
            )
            content = response.choices[0].message.content.strip()
            content = re.sub(r'^```(?:json)?\s*', '', content)
            content = re.sub(r'\s*```$', '', content)
            sub_queries = json.loads(content)
            if isinstance(sub_queries, list) and len(sub_queries) > 0:
                return sub_queries
        except (json.JSONDecodeError, Exception):
            pass
    return [query]  # fallback
