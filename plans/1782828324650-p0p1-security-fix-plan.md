# P0/P1 安全修复计划

决策记录：
- Graph RAG 实体提取数据外泄 → **不处理**（用户确认）
- 路径限制 → **轻量**（仅拒绝 `.env` + `..` 遍历）
- 提示注入防护 → **基础**（仅 system role 隔离）

---

## 任务 1：移除 `.env` 文件可索引风险（P0）

**文件：** `rag.py`

**修改：** 从 `TEXT_EXTENSIONS` 删除 `".env"`

**当前：**
```python
TEXT_EXTENSIONS = {
    ".txt", ".md", ".markdown", ".html", ".htm",
    ".json", ".csv", ".xml", ".yaml", ".yml",
    ".toml", ".cfg", ".ini", ".conf", ".log",
    ".py", ".js", ".ts", ".css", ".sql",
    ".sh", ".bat", ".env", ".gitignore",
}
```

**改为：** 删除 `".env",`

**效果：** `detect_file_type(".env")` → 不匹配任何分支 → 抛 `ValueError("不支持的文件类型")`，`load_document` 不会打开 `.env` 文件。

**副作用：** 无。`load_dotenv()` 在模块加载时（第 27 行）独立读取 `.env`，不受此变更影响。

**行数：** 1 行删除

---

## 任务 2：删除 `_llm_client` 全局缓存（P0）

**文件：** `graph_rag.py`

**理由：** API key 在 `_llm_client` 对象中以字符串形式存在于全局作用域，进程存活期间不可回收。每次调用时新建 client 可让 key 随局部变量一起 GC。

**修改点：**

| # | 当前代码 | 改为 |
|---|---------|------|
| L21 | `_llm_client: Optional[OpenAI] = None` | 删除此行 |
| L24-33 | `def _get_llm_client(): global _llm_client; if _llm_client is None: ... return _llm_client` | `def _get_llm_client(): from dotenv import load_dotenv; load_dotenv(); return OpenAI(api_key=os.getenv("API_KEY"), base_url=os.getenv("BASE_URL"))` |

**改后代码：**
```python
def _get_llm_client() -> OpenAI:
    return OpenAI(
        api_key = os.getenv("API_KEY"),
        base_url = os.getenv("BASE_URL"),
    )
```

**副作用：** 每个 chunk 单独调用 `_get_llm_client()`（`build_from_chunks` 逐个传入 `[c]`），200 个 chunk → 200 次 client 创建。OpenAI client 创建轻量，demo 项目可忽略。

**行数：** -7 行

---

## 任务 3：路径限制 — 轻量级别（P1）

**文件：** `rag.py`（`build_index` 函数）

**理由：** `--files` 参数绕过 `ask_for_files`，在 `build_index` 中过滤能覆盖所有入口。

**修改：** 在 `build_index` 的 `for fp in file_paths:` 循环中，在 `os.path.exists()` 检查之后增加两个过滤条件：

```python
for fp in file_paths:
    if not os.path.exists(fp):
        print(f"  [跳过] 文件不存在: {fp}")
        continue
    if ".." in fp:
        print(f"  [跳过] 路径包含目录遍历: {fp}")
        continue
    if os.path.basename(fp) == ".env":
        print(f"  [跳过] 不支持对环境变量文件建立索引: {fp}")
        continue```

**注意：** 对原始字符串 `fp` 检查 `".."`，而非 `os.path.normpath(fp)`，否则 `/Users/../etc/passwd` 被 normpath 解析为 `/etc/passwd` 后绕过检查。`.env` 检查作为**第二层防御**（defense in depth），给出用户友好的中文错误信息而不是 Python traceback。

**行数：** +6 行

---  


## 任务 4：System role 隔离指令（P1）

**文件：** `rag.py`（`answer_with_llm_history`）

**理由：** 指令在 user message 中，文档 chunk 被检索后拼入同一 message，内容可覆盖指令。将指令放入 system message 后，LLM 将其视为不可变约束，降低注入风险。

**修改点：**

| 位置 | 当前 | 改为 |
|------|------|------|
| L46-51 | `RAG_PROMPT_TEMPLATE` 包含指令 | 新建 `PROMPT_TEMPLATE` 仅含格式 |
| L399-407 | 无 system message | 前置 `{"role": "system"}` |
| L406 | 使用 `prompt_template` 参数 | 使用 `PROMPT_TEMPLATE`（保留参数用于向后兼容） |

**改后代码：**
```python
SYSTEM_PROMPT = (
    "你是一个基于文档内容的问答助手。根据提供的文档回答问题。"
    "如果文档中找不到相关信息，绝对不能私自编造。"
)
PROMPT_TEMPLATE = "文档：\n{context}\n\n问题：{question}\n答案："

def answer_with_llm_history(
    question: str,
    context: str,
    history: list[tuple[str, str]],
    model: str = DEFAULT_LLM_MODEL,
    temperature: float = DEFAULT_TEMPERATURE,
) -> str:
    api_key = os.getenv("API_KEY")
    base_url = os.getenv("BASE_URL")
    if not api_key or not base_url:
        raise ValueError("请在 .env 文件中设置 API_KEY 和 BASE_URL")

    client = OpenAI(api_key=api_key, base_url=base_url)
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    for q, a in history[-5:]:
        messages.append({"role": "user", "content": q})
        messages.append({"role": "assistant", "content": a})
    prompt = PROMPT_TEMPLATE.format(context=context, question=question)
    messages.append({"role": "user", "content": prompt})
    try:
        response = client.chat.completions.create(
            model=model, messages=messages, temperature=temperature,
        )
    except RateLimitError:
        return "API 请求频率超限，请稍后重试。"
    except APIConnectionError:
        return "无法连接到 API 服务，请检查网络或 BASE_URL 配置。"
    except APIError as e:
        return f"API 请求失败: {e}"
    return response.choices[0].message.content
```

**注意：** `prompt_template` 参数被移除（不再需要），因为指令固定为 `SYSTEM_PROMPT`，格式固定为 `PROMPT_TEMPLATE`。检查调用方 `answer_query` 和 `graph_rag_pipeline` 是否传了该参数。

**调用方检查：**

| 调用处 | 是否传 `prompt_template` | 结论 |
|--------|------------------------|------|
| `answer_query` (rag.py:441-443) | 否 | ✅ 不传，使用默认值 |
| `graph_rag_pipeline` (graph_rag.py:411) | 否 | ✅ 不传，使用默认值 |

**行数：** +5 行

---

## 影响范围

| 任务 | 文件 | 变更类型 | 行数变化 | 测试验证 |
|------|------|---------|---------|---------|
| 1 | rag.py | TEXT_EXTENSIONS 删元素 | -1 | `python rag.py --files .env` → 应报错跳过 |
| 2 | graph_rag.py | 删全局变量 + 简化函数 | -7 | 实体提取仍正常 |
| 3 | rag.py | build_index 加过滤 | +6 | `python rag.py --files ../x.txt` → 应提示跳过 |
| 4 | rag.py | 新增 SYSTEM_PROMPT + PROMPT_TEMPLATE | +5 | 回答格式不变，指令不丢失 |

**合计：** 2 文件，净变 +3 行

---

## 验证清单

1. 语法检查：`python3 -c "import py_compile; py_compile.compile('rag.py'); py_compile.compile('graph_rag.py')"`
2. `python rag.py --files .env` → 打印跳过信息，不读入
3. `python rag.py --files ../some_file.txt` → 打印"路径包含目录遍历"
4. 正常提问：回答质量不受影响，指令仍被遵守
5. `python graph_rag.py` → 实体提取正常工作
6. `python rag.py --files DSpark_paper.pdf --query "什么是DSpark"` → 正常回答
