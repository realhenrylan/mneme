"""LLM 驱动的查询拆解。

统一配置契约：本模块不自行加载 `.env`（`.env` 仅由 `src.config` 在进程
启动时统一加载）；受管默认值 `model`/`temperature` 在调用期从
`src.config.Settings` 解析（显式参数仍优先）。API_KEY/BASE_URL 属于
LLM gateway 边界，本模块只做读取预检（无 key/非法端点时走本地降级，
不发起调用）。
"""

import json
import re
import os
from src.security import endpoint_validation_error, validate_endpoint

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


def _decompose_query_provenanced(
    query: str,
    model: str | None = None,
    temperature: float | None = None,
    max_retries: int = 2,
) -> tuple[list[str], "StageProvenance"]:
    """拆解单一实现：返回 (sub_queries, stage provenance)。

    ``decompose_query_llm`` 是其薄包装（保持公开 API 与既有测试兼容）。
    outcome 枚举与现有 fallback 路径逐一对齐（guard 跳过 / 无 key /
    非法端点 / LLM 失败 / invalid JSON / 拆解成功）；禁止捕获原始
    LLM response 或其 SHA。served version 当前无可靠来源，固定 "unknown"。

    统一配置契约：model/temperature 未显式传入时在调用期从 Settings 解析
    （不再冻结 "deepseek-chat"/0.0 静态默认）；provenance 记录的是解析后
    的生效值。
    """
    from src.config import get_settings
    from src.domain import StageProvenance

    if model is None:
        model = get_settings().llm_model
    if temperature is None:
        temperature = get_settings().llm_temperature

    def _stage(outcome: str, guard_result: bool,
               retries_used: int = 0) -> StageProvenance:
        return StageProvenance(
            guard_result=guard_result,
            outcome=outcome,
            requested_model=model,
            temperature=temperature,
            max_tokens=150,
            timeout=30,
            max_retries=max_retries,
            retries_used=retries_used,
        )

    guard_result = should_decompose(query)
    if not guard_result:
        return [query], _stage("guard_skipped", False)

    api_key = os.getenv("API_KEY")
    base_url = os.getenv("BASE_URL")
    if not api_key or not base_url:
        return [query], _stage("no_api_key", True)
    if endpoint_validation_error(base_url):
        return [query], _stage("invalid_endpoint", True)

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
    retries_used = int(getattr(record, "retries_used", 0) or 0)

    if content is None:
        return [query], _stage("llm_failed", True, retries_used)

    # 清理 markdown 包裹
    content = re.sub(r'^```(?:json)?\s*', '', content)
    content = re.sub(r'\s*```$', '', content)
    try:
        sub_queries = json.loads(content)
        if isinstance(sub_queries, list) and len(sub_queries) > 0:
            return sub_queries, _stage("llm_decomposed", True, retries_used)
    except json.JSONDecodeError:
        pass
    # 非法 JSON / 非 list / 空 list → 降级
    return [query], _stage("invalid_json", True, retries_used)


def decompose_query_llm(
    query: str,
    model: str | None = None,
    temperature: float | None = None,
    max_retries: int = 2,
    *,
    _provenance_sink: list | None = None,
) -> list[str]:
    """LLM 驱动的查询拆解（公开 API，薄包装）。

    拆解为 1-3 个子查询。失败时重试，仍失败则返回 [query]。
    通过统一 LLM Gateway 调用，享受 timeout、retry、错误分类等能力。
    model/temperature 未显式传入时从统一配置 Settings 调用期解析
    （显式参数优先）。``_provenance_sink`` 为 G1-S 内部侧信道
    （同 rewrite_query_llm）。
    """
    sub_queries, stage = _decompose_query_provenanced(
        query, model, temperature, max_retries,
    )
    if _provenance_sink is not None:
        _provenance_sink.append(stage)
    return sub_queries
