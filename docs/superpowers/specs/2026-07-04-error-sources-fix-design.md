# 错误场景不显示 Sources 修复设计

> 状态：设计完成，待实施
> 日期：2026-07-04
> 作者：AI Assistant

---

## 一、问题背景

### 1.1 问题描述

用户报告：在某些错误场景下，系统既显示了错误消息，又显示了 Sources 参考来源。期望行为是：**错误场景只显示错误消息，不显示 Sources**。

### 1.2 错误场景分类

| 场景 | 当前行为 | 期望行为 |
|------|----------|----------|
| API 配置缺失（无 API_KEY/BASE_URL） | ✅ 已正确处理，不显示 Sources | 不显示 Sources |
| LLM 调用失败（RateLimitError/APIConnectionError/APIError） | ❌ 错误消息 + Sources 同时显示 | 只显示错误消息 |

### 1.3 根本原因

`answer_query_stream` 和 `graph_query_stream` 的执行流程：

```
1. 检查 API 配置 → 无配置时返回 (error_stream, "")
2. 执行检索 → 计算 sources
3. 创建 LLM stream 生成器 → 返回 (stream, sources)
4. 调用方迭代 stream → LLM 错误在此发生，但 sources 已返回
```

**关键问题**：生成器函数具有惰性求值特性。调用 `answer_with_llm_history_stream(...)` 只创建生成器对象，不执行函数体。当调用方迭代生成器时发生 LLM 错误，此时 `sources` 早已计算完成并返回给调用方。

---

## 二、设计目标

1. **统一错误处理**：所有错误场景都只返回 `(error_stream, "")`
2. **最小改动**：保持函数签名不变，改动集中在 RAG 层
3. **保持流式体验**：不预消费生成器，保持实时流式输出
4. **API 兼容**：调用方代码无需大幅修改

---

## 三、架构设计

### 3.1 核心方案：生成器包装器 + Out-of-Band 错误信号

由于生成器的惰性求值特性，无法在外层使用 try-except 捕获内部异常。采用以下方案：

1. **生成器包装器**：在 `answer_query_stream` 内部创建包装生成器，捕获 LLM 错误
2. **Out-of-Band 错误信号**：使用可变容器（list）记录错误状态，挂载到生成器对象
3. **调用方检测**：`chat.py` 迭代完成后检查错误信号，决定是否显示 Sources

### 3.2 数据流

```
answer_query_stream
    │
    ├─ 检查 API 配置 → 无配置: return (error_stream, "")
    │
    ├─ 执行检索 → 计算 sources
    │
    └─ 创建包装生成器 _safe_stream()
            │
            ├─ try: yield from answer_with_llm_history_stream(...)
            │
            └─ except LLMError/APIError:
                    error_occurred.append(True)
                    yield "[错误] ..."

    return (stream, sources)  # stream 挂载 error_occurred

chat.py
    │
    ├─ for chunk in stream: ...
    │
    └─ if sources.strip() and not stream._mneme_error:
            console.print(source_reference(sources))
```

---

## 四、改动清单

### 4.1 文件改动

| 文件 | 改动内容 | 改动量 |
|------|----------|--------|
| `src/rag.py` | 定义 `LLMError` 异常类；修改 `answer_with_llm_history_stream` 改 yield 为 raise；修改 `answer_query_stream` 添加包装器 | ~30 行 |
| `src/graph_rag.py` | 修改 `graph_query_stream` 添加包装器 | ~20 行 |
| `tui/screens/chat.py` | 修改 sources 显示逻辑，检查错误信号 | ~3 行 |

### 4.2 详细改动

#### 4.2.1 `src/rag.py` — 定义 LLMError 异常类

```python
# 在文件开头（约第 20 行）添加
class LLMError(Exception):
    """LLM 调用失败的统一异常"""
    pass
```

#### 4.2.2 `src/rag.py` — 修改 `answer_with_llm_history_stream`

**修改 1**：第 869-871 行（API 配置检查）:

**修改前**：
```python
    if not api_key or not base_url:
        yield "[错误] 请在 .env 文件中设置 API_KEY 和 BASE_URL"
        return
```

**修改后**：
```python
    if not api_key or not base_url:
        raise LLMError("请在 .env 文件中设置 API_KEY 和 BASE_URL")
```

**修改 2**：第 887-892 行（异常处理）:

**修改前**：
```python
except RateLimitError:
    yield "\n[API 请求频率超限，请稍后重试]"
except APIConnectionError:
    yield "\n[无法连接到 API 服务，请检查网络或 BASE_URL 配置]"
except APIError as e:
    yield f"\n[API 请求失败: {e}]"
```

**修改后**：
```python
except RateLimitError:
    raise LLMError("API 请求频率超限，请稍后重试")
except APIConnectionError:
    raise LLMError("无法连接到 API 服务，请检查网络或 BASE_URL 配置")
except APIError as e:
    raise LLMError(f"API 请求失败: {e}")
```

#### 4.2.3 `src/rag.py` — 修改 `answer_query_stream`

**修改前**（第 951-955 行）：
```python
sources = format_sources(top_indices, enriched_docs, metadatas)
stream = answer_with_llm_history_stream(
    query, context, history or [], model=llm_model, temperature=temperature,
)
return stream, sources
```

**修改后**：
```python
sources = format_sources(top_indices, enriched_docs, metadatas)

# 包装生成器：捕获 LLM 错误，通过 out-of-band 信号传递
error_occurred: list[bool] = []

def _safe_stream():
    try:
        yield from answer_with_llm_history_stream(
            query, context, history or [], model=llm_model, temperature=temperature,
        )
    except LLMError as e:
        error_occurred.append(True)
        yield f"[错误] {e}"
    except (RateLimitError, APIConnectionError, APIError) as e:
        # 兜底：捕获未转换的原始异常
        error_occurred.append(True)
        yield f"[错误] {e}"

stream = _safe_stream()
stream._mneme_error = error_occurred  # 挂载错误信号
return stream, sources
```

#### 4.2.4 `src/graph_rag.py` — 修改 `graph_query_stream`

**修改前**（第 587-591 行）：
```python
sources = format_sources(top_indices, all_docs, all_metadatas)
stream = answer_with_llm_history_stream(
    query, context, history or [], model=llm_model, temperature=temperature,
)
return stream, sources
```

**修改后**：
```python
from rag import LLMError  # 在文件开头添加导入

# 在函数末尾：
sources = format_sources(top_indices, all_docs, all_metadatas)

error_occurred: list[bool] = []

def _safe_stream():
    try:
        yield from answer_with_llm_history_stream(
            query, context, history or [], model=llm_model, temperature=temperature,
        )
    except LLMError as e:
        error_occurred.append(True)
        yield f"[错误] {e}"
    except (RateLimitError, APIConnectionError, APIError) as e:
        error_occurred.append(True)
        yield f"[错误] {e}"

stream = _safe_stream()
stream._mneme_error = error_occurred
return stream, sources
```

#### 4.2.5 `tui/screens/chat.py` — 修改 sources 显示逻辑

**修改前**（第 145 行）：
```python
if sources.strip():
    console.print(source_reference(sources))
```

**修改后**：
```python
# 只有在没有错误时才显示 Sources
if sources.strip() and not getattr(stream, '_mneme_error', None):
    console.print(source_reference(sources))
```

---

## 五、测试策略

### 5.1 单元测试

| 测试用例 | 验证点 |
|----------|--------|
| `test_llm_error_exception` | LLMError 异常类可正常创建和捕获 |
| `test_answer_with_llm_raises_on_api_config_missing` | `answer_with_llm_history_stream` 在 API 配置缺失时抛出 LLMError |
| `test_answer_with_llm_history_stream_raises_llm_error` | `answer_with_llm_history_stream` 在 API 错误时抛出 LLMError |
| `test_answer_query_stream_catches_llm_error` | `answer_query_stream` 包装器捕获 LLMError，设置错误信号 |
| `test_graph_query_stream_catches_llm_error` | `graph_query_stream` 包装器捕获 LLMError，设置错误信号 |

### 5.2 集成测试

| 测试用例 | 验证点 |
|----------|--------|
| `test_api_config_missing_no_sources` | API 配置缺失时，sources 为空字符串 |
| `test_llm_rate_limit_no_sources` | LLM RateLimitError 时，错误信号被设置 |
| `test_llm_connection_error_no_sources` | LLM APIConnectionError 时，错误信号被设置 |
| `test_llm_api_error_no_sources` | LLM APIError 时，错误信号被设置 |
| `test_normal_query_shows_sources` | 正常查询时，sources 正常显示 |

### 5.3 Mock 策略

使用 `unittest.mock.patch` mock LLM 调用：

```python
from unittest.mock import patch, MagicMock
from openai import RateLimitError, APIConnectionError, APIError

@patch('rag.OpenAI')
def test_llm_rate_limit_no_sources(mock_openai):
    mock_client = MagicMock()
    mock_openai.return_value = mock_client
    mock_client.chat.completions.create.side_effect = RateLimitError(...)

    stream, sources = answer_query_stream(...)
    chunks = list(stream)

    assert any("[错误]" in c for c in chunks)
    assert getattr(stream, '_mneme_error', None)  # 错误信号被设置
```

---

## 六、风险评估

| 风险 | 可能性 | 影响 | 缓解措施 |
|------|--------|------|----------|
| duck-typing 属性挂载不够优雅 | 低 | 低 | 可改用返回 tuple `(stream, sources, error)` 但改动更大 |
| 流式中途错误仍带部分 sources | 中 | 中 | 已通过 out-of-band 信号解决 |
| 遗漏某些 API 错误类型 | 低 | 低 | 添加兜底 `except Exception` |

---

## 七、实施顺序

1. **定义异常类** — `src/rag.py` 添加 `LLMError`
2. **修改生成器函数** — `answer_with_llm_history_stream` 改 yield 为 raise
3. **添加包装器** — `answer_query_stream` 和 `graph_query_stream`
4. **修改显示逻辑** — `chat.py` 检查错误信号
5. **编写测试** — 按测试策略编写单元测试和集成测试
6. **运行验证** — 确保所有测试通过

---

## 八、验收标准

- [ ] API 配置缺失时，只显示错误消息，不显示 Sources
- [ ] LLM RateLimitError 时，只显示错误消息，不显示 Sources
- [ ] LLM APIConnectionError 时，只显示错误消息，不显示 Sources
- [ ] LLM APIError 时，只显示错误消息，不显示 Sources
- [ ] 正常查询时，sources 正常显示
- [ ] 所有测试通过
