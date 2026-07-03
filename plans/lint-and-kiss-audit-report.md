# Lint & KISS Audit Report — SciClaw RAG System

**审计日期**: 2026-07-03
**审计范围**: `src/`, `tui/`, `scripts/` 全部 Python 文件
**审计性质**: 只检查，不修改

---

## 一、严重 Bug & 安全隐患 (P0)

---

### ISSUE #1 — `.env` 文件含真实 API Key 且自定义 `.env` 解析器脆弱

**严重程度**: CRITICAL
**文件**:
- `.env:1-2`（API Key 泄露）
- `tui/screens/chat.py:303-332`（自定义解析器）
**类别**: 安全漏洞 + 健壮性

#### #1a — API Key 明文泄露

`.env` 文件中包含明文 API Key `REVOKED` 和 Base URL。虽然仓库使用 `.gitignore`，但 `.env` 已被提交或本地可读。API Key 泄露可能导致盗刷。

#### #1b — 自定义 `.env` 解析器脆弱

`_write_env` / `_read_env` 手动解析 `.env`，假设格式精确为 `KEY=VALUE`，不支持：
- 行尾注释 `KEY=value  # comment`
- 引号包裹 `KEY="value with = sign"`
- 多行值
- 空值（`LLM_TOP_K_MIN=` 会写入空行污染）

`python-dotenv` 的 `set_key` / `get_key` 已声明在 `requirements.txt` 中，应直接使用。

**建议**: 立即轮换 API Key，确保 `.env` 未进入 git 历史（`git rm --cached`），添加 `.env.example` 模板文件；同时将自定义解析器替换为 `python-dotenv` 标准 API。

---

### ISSUE #2 — `prepare_index` 的 `force_rebuild` 删除整个 ChromaDB 目录

**严重程度**: CRITICAL
**文件**: `src/rag.py:228-229`
**类别**: 逻辑 Bug

```python
if force_rebuild and os.path.exists(CHROMA_DB_PATH):
    shutil.rmtree(CHROMA_DB_PATH)
```

`force_rebuild=True` 会删除 **整个 ChromaDB 持久化目录**，而非仅删除目标 collection。如果用户有多个 collection（如 `rag_demo` 和 `graph_rag_xxx`），重建一个会导致另一个数据全部丢失。

**KISS 违反**: 该方法职责划分不清晰——`prepare_index` 不应管理整个数据库的生命周期。

---

### ISSUE #3 — 多线程无锁写入模块级 `_entity_cache` 且批量 API 调用未被利用

**严重程度**: HIGH
**文件**: `src/graph_rag.py:29,55,71,100-102,126-130`
**类别**: 并发 Bug + 性能 & 逻辑 Bug

```python
_entity_cache: dict[str, list[str]] = {}
```

`KnowledgeGraph.build_from_chunks` 使用 `ThreadPoolExecutor` 并发调用 `extract_entities_llm_batch`：

```python
with ThreadPoolExecutor(max_workers=max_workers) as executor:
    future_to_idx = {
        executor.submit(extract_entities_llm_batch, [c]): i
        for i, c in enumerate(chunks)
    }
```

存在两个关联问题：

**#3a — 无锁并发写入 `_entity_cache`**
该函数直接写入模块级 `_entity_cache` 字典。Python GIL 在此场景下不保证 dict 写入的原子性，可能导致缓存损坏或数据丢失。

**#3b — 批量 API 调用形同虚设**
`extract_entities_llm_batch` 支持 `batch_size=5` 批量提取，但调用时每个线程只传入单个 chunk `[c]`。结果：N 个 chunk = N 次 API 调用（而非 N/5 次），线程池的 10 个 worker 实际制造了 10 倍请求压力，极易触发 rate limit。

**KISS 违反**: 完整的批量逻辑被复杂的多线程包装完全绕过。

**建议**: 将多个 chunk 拼成真正的 batch 传入 `extract_entities_llm_batch`，消除不必要的多线程层，并随之解决无锁并发写入问题；若保留多线程，则需为 `_entity_cache` 加锁。

---

### ISSUE #4 — Graph RAG 检索路径不使用 `enrich_context`

**严重程度**: HIGH
**文件**: `src/graph_rag.py:529-554`, `src/rag.py:520-547`
**类别**: 功能缺失

标准 RAG 的 `answer_query` 和 `answer_query_stream` 都调用了 `enrich_context` 将 anchor chunk 替换为 PDF 首页全文。但 Graph RAG 的 `graph_query_stream`（第 549 行）直接用 `" ".join(docs[:k])` 拼接 context，未调用 `enrich_context`。

**影响**: Graph RAG 模式下的 PDF 页面信息（作者、机构等元数据）严重缩水。

---

### ISSUE #5 — `_get_llm_client` 每次调用都创建新的 OpenAI 客户端

**严重程度**: MEDIUM
**文件**: `src/graph_rag.py:31-35`
**类别**: 资源浪费

```python
def _get_llm_client() -> OpenAI:
    return OpenAI(api_key=os.getenv("API_KEY"), base_url=os.getenv("BASE_URL"))
```

`extract_entities_llm_batch` 中每个 batch 都调用一次（第 55 行），即每次 API 调用都新建客户端。应改为模块级缓存或单例模式。

---

## 二、架构设计与 KISS 原则违规 (P1)

---

### ISSUE #6 — CLI 循环与索引准备函数在 `rag.py` 和 `graph_rag.py` 中双重重复

**严重程度**: HIGH
**文件**:
- `src/rag.py:749-825` / `src/graph_rag.py:431-523`（CLI 循环）
- `src/rag.py:222-250` / `src/graph_rag.py:327-366`（索引准备）
**类别**: KISS 违规 — DRY

#### #6a — `__main__` CLI 循环重复

两个文件各有一份约 75 行的 CLI 交互循环，包含完全相同的：
- `+add` 命令逻辑
- 问答循环 `while True: input("请输入问题...")`
- 计时打印 `(用时X分Y秒)`
- `history` 管理
- `dynamic_top_k` 调用
- `format_sources` 显示

#### #6b — `prepare_index` 与 `prepare_graph_index` 高度重复

两个函数的前 90% 逻辑相同（检测索引存在、加载 model、加载 collection、构建 BM25）。`prepare_graph_index` 仅在末尾多了一段 KnowledgeGraph 的加载/构建逻辑。

**建议**: 提取公共 `cli_loop.py`（`run_interactive_session()`）和公共索引准备函数 `_prepare_index_common()`，消除两个文件中各自维护的重复逻辑。

---

### ISSUE #7 — `TEXT_EXTENSIONS` / `_SUPPORTED_EXTENSIONS` 三处重复 + `_collection_exists` 两处重复 + `sys.path` 散落 5 处

**严重程度**: MEDIUM
**文件**:
- `src/rag.py:61-67`（`TEXT_EXTENSIONS`）
- `tui/screens/home.py:30-37`（`_SUPPORTED_EXTENSIONS`）
- `tui/screens/chat.py:15-22`（`_SUPPORTED_EXTENSIONS`）
- `src/rag.py:215-220` / `tui/screens/home.py:64-71`（`_collection_exists`）
- `src/rag.py:29-31` / `src/graph_rag.py:11-13` / `tui/service.py:4-7` / `tui/screens/home.py:12-15` / `scripts/run_temperature_test.py:12`（`sys.path`）

**类别**: KISS 违规 — DRY + 工程规范

三个关联问题同属"跨文件共享代码缺失"：

**#7a — 扩展名列表三处重复定义**
同一份扩展名列表在三个文件中各维护一份，修改时极易遗漏。

**#7b — `_collection_exists` 两处重复实现**
两个完全相同的函数用于检查 ChromaDB collection 是否存在，TUI 版本应直接导入 `src.rag._collection_exists`。

**#7c — `sys.path` 散落 5 处**
每个文件都自行操作 `sys.path` 以确保 import 正常工作。这是典型的「能用但脆弱」模式，应通过 `pip install -e .` 或 `PYTHONPATH` 统一解决。

**建议**: 将扩展名列表和 `_collection_exists` 统一定义在 `src/rag.py`，TUI 和脚本层直接导入；同时移除各处的 `sys.path` 注入，改用包安装方式统一管理。解决 #7c（统一 import 路径）是 #7a 和 #7b 重构的前置条件。

---

### ISSUE #8 — 两个评分系统各自实现且逻辑不一致

**严重程度**: MEDIUM
**文件**:
- `scripts/run_temperature_test.py`（`compute_A_B_C_D`, `compute_E`, `check_refuse`）
- `scripts/fix_scoring.py`（`score_single`, `score_consistency`, `is_refusal_answer`）

**类别**: 可维护性

两套评分函数计算方式不同（如 `fix_scoring.py` 引入了 `count_fabricated_numbers`，而 `run_temperature_test.py` 用 `fact_hits`）。同一个测试流程使用两套评分标准，结果不可比，且难以维护。应合并为单一评分模块供两个脚本共同引用。

---

### ISSUE #9 — `KnowledgeGraph.build_from_chunks` 的 O(n×m²) 边构建无剪枝

**严重程度**: MEDIUM
**文件**: `src/graph_rag.py:155-161`
**类别**: 性能 / KISS

```python
for u in unique_entities:
    for v in unique_entities:
        if u < v:
            self.entity_graph.add_edge(u, v, weight=1)
```

一个 chunk 若提取出 20 个实体，产生 190 条边；测试报告显示 4046 个实体产生 38755 条边。所有两两组合都创建边，大量「弱共现」噪音污染图谱。应加阈值过滤低频共现，或限制每个 chunk 的实体上限。

---

### ISSUE #10 — `graph_rag.py:75` LLM model 硬编码为 `deepseek-chat`

**严重程度**: LOW
**文件**: `src/graph_rag.py:75`
**类别**: KISS — 硬编码

```python
model="deepseek-chat",
```

实体提取的模型名硬编码，不尊重 `DEFAULT_LLM_MODEL` 或环境变量 `LLM_MODEL`。用户在 TUI `/settings` 中切换模型不会影响 Graph RAG 的实体提取。

---

### ISSUE #11 — `build_graph_index` 函数几乎未被使用（死代码）

**严重程度**: LOW
**文件**: `src/graph_rag.py:299-324`
**类别**: 死代码

`build_graph_index` 是公开函数，但所有调用路径都经过 `prepare_graph_index`（后者只在 `need_build` 时内部调用 `build_graph_index`）。该函数要么改为私有（`_build_graph_index`），要么合并入调用者。

---

## 三、代码风格与健壮性问题 (P2)

---

### ISSUE #12 — 全局使用 `print()` 替代日志系统

**严重程度**: LOW
**文件**: 几乎所有源文件

系统依赖 `print()` 进行所有输出，无日志级别（debug/info/warning/error），无日志文件写入。生产环境中无法控制输出粒度，也无法聚合错误信息。

---

### ISSUE #13 — 文件路径安全过滤 `".." in fp` 存在误杀和漏杀

**严重程度**: MEDIUM
**文件**: `src/rag.py:286-288`, `src/rag.py:376-378`
**类别**: 安全 / 健壮性

```python
if ".." in fp:
    print(f"  [跳过] 路径包含目录遍历: {fp}")
    continue
```

这个过滤：
- **误杀**: 合法路径 `/foo/bar..2026/data.pdf` 会被阻止
- **漏杀**: 符号链接 `/tmp/foo -> /etc/` 可以绕过
- **KISS 违规**: 不应自行实现路径安全，应使用 `os.path.realpath()` 规范化后判断是否在允许目录内

---

### ISSUE #14 — 中文实体提取 prompt 对分隔符解析有 bug

**严重程度**: LOW
**文件**: `src/graph_rag.py:85-98`
**类别**: 鲁棒性

```python
if line.startswith("---段落"):
    if current: parsed.append(current)
elif line and not line.startswith(("-", "*", "·")):
    current.append(line)
```

如果 LLM 返回的实体行恰好以 `-` 或 `*` 开头（如 `- 某概念`），该行会被静默丢弃。且分隔符 `---段落` 的格式与 LLM 的 `---段落1---` 不匹配（少了一端的 `---`）。

---

### ISSUE #15 — `extract_entities_llm_batch` 文本截断丢失尾部实体

**严重程度**: LOW
**文件**: `src/graph_rag.py:71`
**类别**: 数据丢失

```python
f"---段落{k + 1}---\n{t[:1500]}" for k, t in enumerate(uncached_texts)
```

长文本被硬截断到 1500 字符，末尾的实体信息直接丢失。对于长 PDF chunk（2000+ 字符），截断意味着丢失 25%+ 的内容。可使用更智能的截断（按句子边界）或分批次处理。

---

## 四、数据统计

| 类别 | 数量 |
|------|------|
| 严重安全/逻辑 Bug (P0) | 5 |
| 架构/KISS 违规 (P1) | 7 |
| 风格/健壮性 (P2) | 4 |
| **合并后总计** | **16** |

| 文件 | 问题数 |
|------|--------|
| `src/rag.py` | 4 |
| `src/graph_rag.py` | 7 |
| `tui/screens/chat.py` | 2 |
| `tui/screens/home.py` | 2 |
| `tui/service.py` | 1 |
| `scripts/run_temperature_test.py` | 1 |
| `scripts/fix_scoring.py` | 1 |
| `.env` | 1 |

---

## 附：Issue 合并说明

| 原始 Issue | 合并后 Issue | 合并原因 |
|------------|-------------|---------|
| **#1** `.env` 泄露 + **#12** 自定义 `.env` 解析脆弱 | **#1** | 同属 `.env` 处理流程，一损俱损，应一并审视与修复 |
| **#3** 无锁写 `_entity_cache` + **#4** 批量调用未利用 | **#3** | 两者同根：都源于 `ThreadPoolExecutor` 包装 batch 函数却只传单个 chunk。修复 #4 后 #3 的并发压力自然消失，建议合并为一个并发批处理重构 |
| **#9** 扩展名三处重复 + **#10** `_collection_exists` 两处重复 + **#11** `sys.path` 散落 | **#7** | 三者同属"跨文件共享代码缺失"，统一 `sys.path`（#11）是提取公共模块（#9/#10）的前置条件，合并处理更连贯 |
| **#7** CLI 循环重复 + **#8** `prepare_index` 重复 | **#6** | 同属 `rag.py` / `graph_rag.py` 双文件间的 DRY 问题，合并规划可一次性梳理两文件间的公共抽象 |

---

*报告由人工代码审计生成，未使用外部 lint 工具（venv 中无 ruff/pylint）。数据基准时间：2026-07-03。*
