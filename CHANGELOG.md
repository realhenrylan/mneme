# Mneme Changelog

All notable changes to the Mneme project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [1.0.3] - 2026-07-04

### Fixed

**错误场景不再显示 Sources**

- 修复 LLM 调用失败（RateLimitError/APIConnectionError/APIError）时同时显示错误消息和 Sources 的问题
- 新增 `LLMError` 自定义异常类，统一 LLM 错误处理
- `answer_with_llm_history_stream` 从 `yield` 错误消息改为 `raise LLMError`
- `answer_query_stream` 和 `graph_query_stream` 添加生成器包装器，捕获异常并通过 `_mneme_error` 信号传递
- `chat.py` 根据 `_mneme_error` 信号决定是否显示 Sources
- 新增 13 个 TDD 测试覆盖错误场景

---

## [1.0.2] - 2026-07-04

### Fixed

- 修复 `/settings` 中 **Temperature、Alpha、Top-K Min/Max** 四个设置项在重启后丢失的问题：
  - `RagApp.__init__()` 新增从 `.env` 读取 `LLM_TEMPERATURE`、`ALPHA`、`LLM_TOP_K_MIN`、`LLM_TOP_K_MAX`
  - `/settings` 修改设置写入 `.env` 后，重启应用将自动恢复上次保存的值

---

## [1.0.1] - 2026-07-03

### Fixed

**Issue #3: 多线程无锁写入 `_entity_cache` + 批量 API 调用形同虚设**

- 移除 `build_from_chunks` 中的 `ThreadPoolExecutor`，消除无锁并发写入 `_entity_cache` 的数据竞争风险
- 修复批量处理被错误调用的问题：之前每个 chunk 单独调用一次 API，现在正确批量处理（减少 80% API 调用）
- 新增 `batch_size` 参数控制批量大小，默认为 5
- `max_workers` 参数标记为废弃，传入非默认值时发出 `DeprecationWarning`
- 新增 `progress_callback` 参数支持增量进度回调

### Added

- 新增 `tests/test_graph_rag_batch.py` 测试文件，覆盖批量处理、向后兼容性、异常处理等场景

---

## [1.0.0] - 2026-07-03

### Added

- Initial release of Mneme (née RAG system) with TUI
- Core RAG pipeline with hybrid retrieval (BM25 + ChromaDB vector search)
- Graph RAG mode with knowledge graph construction
- Query decomposition for complex questions
- Hierarchical document enrichment (anchor chunk strategy)
- Rich-based terminal UI with interactive settings
- PDF, DOCX, Markdown, and text file support
- Temperature testing framework for model evaluation
- Comprehensive test suite with unit and integration tests

### KISS 原则重构 (2026-07-01)

#### `rag.py`

**文件类型检测简化**
- 删除 `MAGIC_SIGNATURES`、`read_magic_bytes()`、`check_magic_bytes()`、`is_text_content()`、`detect_office_type()` (~70 行死码)
- `detect_file_type()` 重写为纯扩展名判断

**rag_pipeline 索引入口合并**
- `rag_pipeline` 改为调用 `prepare_index()`，与 CLI 走同一条路径
- 消除了重复调用时产生重复向量条目的隐式 bug

**rag_pipeline 消除与 answer_query 的重复**
- 检索→dynamic_top_k→构建 context→LLM 生成的 16 行代码替换为单行 `answer_query(...)` 调用
- 消除 `" ".join` vs `"\n\n".join` 的不一致问题

**清理**
- 修复过时注释（魔数检测相关）
- 删除 `build_index` 中未使用的 `doc_id` 变量
- 修复 `prepare_index` 返回值注解
- `get_splitter` 嵌套字典展开为平铺 if/elif

**安全修复**
- `TEXT_EXTENSIONS` 中删除 `".env"`，阻止 API Key 文件被纳入检索池
- `build_index` 增加两重过滤：拒绝含 `..` 的路径，拒绝 `.env` 文件
- 新增 `SYSTEM_PROMPT` 常量，指令放入 `{"role": "system"}` 消息，与文档内容隔离
- 移除 `RAG_PROMPT_TEMPLATE` 和 `prompt_template` 参数

#### `graph_rag.py`

**真实分数替代伪造分数送 dynamic_top_k**
- `graph_augmented_retrieve` 返回类型由 `list[str]` 变为 `tuple[list[str], list[float]]`
- `graph_rag_pipeline` 移除 `scores = [1.0/(i+1) ...]` 伪造逻辑

**代码清理**
- 删除 `zip()` 教学注释 (12 行)
- 简化 `extract_entities_llm_batch` 缓存逻辑，删除辅助结构 (~20 行)
- 删除未使用的 `verbose = True`
- 删除未使用的 import (`re`, `json`, `asyncio`)
- 删除未使用的 `method` 参数（`extract_entities_from_query`）
- 删除 `collection.get()` 教学注释
- 删除未使用的 `rebuild_graph` 参数（`graph_rag_pipeline`）
- 恢复异常处理，删除空循环
- 删除 `all_results` 未使用变量
- 删除 `cooccur_window` 死参数
- 删除三引号悬空字符串
- 更新 docstring 返回值描述

**安全修复**
- 移除模块级 `_llm_client: Optional[OpenAI] = None` 全局变量及缓存逻辑
- `_get_llm_client()` 每次新建 client，key 随局部变量 GC 回收

### Graph RAG 改进 (2026-07-01)

- **索引只建一次，循环内复用**: 新增 `prepare_graph_index()` 函数，检查 collection 是否已存在；`graph_rag_pipeline` 中 `force_rebuild` 默认值从 `True` 改为 `False`
- **实现 `+add` 中途添加文件**: 导入 `add_files_to_index`，对话循环中增加 `+add` 分支
- **补齐 CLI 参数**: 新增 `--files`, `--collection`, `--rebuild`, `--query`, `--alpha`
- **显示参考来源**: `graph_augmented_retrieve` 返回值扩展为 `(indices, docs, scores)`
- **修复 Prompt 与解析不一致**: 删除无效指令行
- **实体提取截断从 500 提升到 1500**
- **融合重构 + alpha 权重修复**: `merged` 从 `list` 改为 `dict[str, float]`
- **修复 Collection 名称哈希碰撞**: `"".join` → `"|".join`
- **`_entity_cache` 改用文本 hash 作 key**
- **清理 unused imports + 类名**: `knowledgegraph` → `KnowledgeGraph`（PEP8）
- **图谱为空时给出提示**: 退化为纯语义检索时打印警告
- **修复 `get_related_entities` 大小写敏感匹配**: `seed_nodes` 查找改为大小写不敏感

### RAG TUI 前端 (2026-07-01)

基于 Python Textual 框架构建类 opencode 风格的 TUI 前端，支持 Standard RAG 和 Graph RAG 两种模式。

**新增文件:**

```
tui/
├── __init__.py
├── __main__.py
├── app.py                  # RagApp 主类 + 路由 + 全局 reactive 状态
├── service.py              # LocalRagService Thin Wrapper
├── theme.py                # Obsidian 深紫配色常量
├── theme.tcss              # Textual CSS 样式
├── keys.py                 # 快捷键 + Slash 命令定义
├── routes/
│   ├── home.py             # Home 页
│   ├── chat.py             # Chat 页
│   └── settings.py         # Settings 页
├── components/
│   ├── message.py          # UserMessage / AssistantMessage / ThinkingMessage
│   ├── prompt.py           # PromptInput
│   ├── sidebar.py          # 侧边栏
│   ├── footer.py           # 底部状态栏
│   ├── loading.py          # LoadingScreen
│   └── error.py            # ErrorWidget
└── dialogs/
    ├── command_palette.py  # Ctrl+P 命令面板
    ├── file_manager.py     # /files 文件管理
    ├── model_select.py     # /models 模型选择
    ├── status.py           # /status 系统状态
    └── help.py             # /help 帮助
```

**后端修改:**
- `rag.py`: `answer_with_llm_history_stream()`, `answer_query_stream()`, `remove_file_from_index()`
- `graph_rag.py`: `graph_query_stream()`, `KnowledgeGraph.build_from_chunks()` 新增 `progress_callback`

**Service 层**: `LocalRagService` — 进程内直调 Thin Wrapper，缓存 SentenceTransformer，阻塞操作通过 `asyncio.to_thread()` 包装

**TUI 功能:**
- Home 页: ASCII Logo + Standard/Graph 模式单选 + 文件路径输入 + Collection 名称
- Chat 页: 流式 LLM 回答 + 嵌入式来源引用 + 侧边栏 + 命令分发
- 快捷键: Ctrl+P 命令面板、Ctrl+L 侧边栏、Ctrl+N 新建、Ctrl+K 清空、Ctrl+C 退出
- Slash 命令: /files /models /settings /mode /alpha /rebuild /status /clear /export /help /quit
- 配色: Obsidian 深紫（#1e1a2e 背景 + #a78bfa 强调色）

**审计修复:**
- 第一轮 (5 P0 + 4 P1): `reactive(list)` 崩溃、对话框无法打开、CommandPalette 不执行、Graph add 后 KG 未更新、Standard→Graph 切换崩溃、FileAction 无 handler、/rebuild /export 无处理、settings.py 缺失
- 第二轮: SettingsScreen `.env` 路径修复

### 检索修复 + 查询拆解 + 分层 Enrich (2026-07-02)

#### `rag.py`

**PyMuPDF 优先策略**
- `load_pdf()` / `load_pdf_pages()` 先试 `fitz`，失败降级 `pdfplumber`
- PyMuPDF `page.get_text("text")` 保留 word 空格，修复 `UniversityofPennsylvania` 拼接问题

**Tokenize 重构**
- 新增 `_STRIP_PUNCT` + `_tokenize()`：支持双语/大小写/标点
- `build_bm25_index` 和 `retrieve_hybrid_with_sources` 改用 `_tokenize`

**Anchor chunk 生成**
- `build_index` / `add_files_to_index`：取 PDF 首页 `splitlines()[:5]` 作为 anchor chunk
- `rrf_merge` 增加 `documents`/`metadatas` 参数，anchor chunk RRF score ×2 提升

**Default 参数调整**
- `DEFAULT_TOP_K`: 20 → 70
- `DEFAULT_MIN_K`: 3 → 12
- `DEFAULT_MAX_K`: 20 → 70
- `DEFAULT_TEMPERATURE`: 0.1 → 0.2

**`prepare_index` 重构**
- 接受 `progress_callback` 参数
- `force_rebuild` 逻辑移到 `prepare_index` 层

**查询拆解 + 并发检索**
- 调用 `decompose_query_llm()` 拆解查询，`ThreadPoolExecutor` 并发执行子查询
- `best_score` dict 按 chunk 去重
- `enrich_context()`：anchor 命中时用首页全文替换 snippet

**流式接口**
- `answer_with_llm_history_stream()` / `answer_query_stream()`
- 错误处理：`RateLimitError` / `APIConnectionError` / `APIError`

#### `graph_rag.py`

- `KnowledgeGraph` 持久化：`save()` / `load()` — pickle 序列化
- `build_graph_index` / `build_from_chunks` / `prepare_graph_index` 传播 `progress_callback`
- CLI 对齐：暴露 `temperature` 参数

#### 测试与工具

| 文件 | 说明 |
|------|------|
| `test_retrieval_fix.py` | 8 项回归测试 |
| `test_query_decomposer.py` | 5 mock + 2 集成 + 2 回归 (9 项) |
| `test_hierarchical_enrich.py` | 4 单元 + 2 端到端 (6 项) |
| `fix_scoring.py` | 评分分析工具 |
| `generate_report.py` | 报告生成工具 |
| `run_temperature_test.py` | temperature 对比测试 |

#### 项目文件重组

- `rag.py` / `graph_rag.py` / `rag_query_decomposer.py` → `src/`
- 测试文件 → `tests/`
- 分析工具 → `scripts/`
- 废弃文件 → `archive/`
- `test_report/` → `reports/`

#### 计划文档

| 文件 | 摘要 |
|------|------|
| `plans/1782828324650-retrieval-fix-plan.md` | 检索修复计划 |
| `plans/1782828324650-query-decomposer-plan.md` | 查询拆解计划 |
| `plans/1782828324650-hierarchical-enrich-plan.md` | 分层 enrich 计划 |
| `plans/1782828324650-tui-rewrite-rich.md` | TUI 重写计划 |
| `plans/1782828324650-add-files-mid-session.md` | 会话中添加文件计划 |
| `plans/1782828324650-graph-rag-improvements.md` | Graph RAG 改进计划 |
| `plans/1782828324650-p0p1-security-fix-plan.md` | 安全修复计划 |
| `plans/1782828324650-review-verification.md` | 代码审阅验证 |
| `plans/1782828324650-retrieval-failure-report.md` | 检索失败分析 |
| `plans/rag-tui-frontend.md` | TUI 前端计划 |
| `plans/rag-first-principles-analysis-report.md` | 第一性原理分析 |
| `plans/SciClaw RAG技术总结.md` | 技术调研 |
| `plans/temperature-test-questions.md` | 测试问题集 |

### Security

#### [#1] - API Key Protection & .env Parser Fix (2026-07-03)

**#1a: API Key Exposure Prevention**
- Added `_mask_api_key()` to mask API keys in TUI (displays `sk-...xxxx` format)
- API keys no longer displayed in plaintext in settings interface
- `.env` file protected by `.gitignore` (not tracked in git history)

**#1b: .env Parser Hardening**
- Replaced fragile custom `_read_env`/`_write_env` with `python-dotenv` standard API
- Fixed handling of values containing `=`, `#`, quotes, and newlines
- Automatic quoting via `set_key()` prevents malformed `.env` entries
- Added 21 unit tests covering all edge cases

**Files Changed:**
- `tui/screens/chat.py`: Refactored env parsing, added masking
- `tests/test_env_security.py`: 21 new tests (all passing)
- `.env.example`: Added template file

### Changed

- `_toggle_mode()` in TUI now shows progress bar during knowledge graph construction
- Graph RAG knowledge graph files saved to `chroma_db/` directory

### Fixed

- [#1] Custom `.env` parser failed on values with `=`, `#`, quotes, or newlines
- [#1] `_mask_api_key` prefix calculation corrected (`key[:3]` = `"sk-"`)
- `build_bm25_index([])` 在空文档列表时触发 `ZeroDivisionError`（已知问题，CLI 主流程 `if not all_docs: exit(1)` 可正常退出）

### Format Sources & Cleanup

- `format_sources` docstring 精简：9 行示例输出替换为 1 行简洁描述
- `graph_rag.py` 删除未使用的导入（`detect_file_type`, `RAG_PROMPT_TEMPLATE`）
- 删除误导性注释（`EXTRACT_PROMPT_BATCH` 后）
- 删除 `entity_method` 死参数链（`build_from_chunks`, `graph_augmented_retrieve`, `build_graph_index`, `graph_rag_pipeline`）
- 修复 `graph_augmented_retrieve` 返回值注解

---

## [Unreleased]

### Added

- **自动目录监控 (File Watcher)** — 用 `watchdog` 替换 `/files → add` 交互流程
  - `tui/file_watcher.py`: `FileWatcher` 类，监听 `created`/`moved`/`deleted` 事件，2 秒防抖，dotfile/temp 文件过滤
  - `tui/constants.py`: 共享 `_SUPPORTED_EXTENSIONS` 常量，消除 `chat.py` 和 `home.py` 的重复定义
  - `LocalRagService.set_watch_dir()` / `start_watching()` / `stop_watching()` / `get_watch_dir()` 生命周期方法
  - `LocalRagService._on_new_file()` / `_on_removed_file()` 回调，删除后自动刷新 `_docs`/`_metadatas`/`_bm25`
  - 线程安全：`threading.Lock` 保护 `add_files()` / `remove_file()` 写操作
  - `.env` 持久化 `RAG_WATCH_DIR`，重启后自动恢复监控
  - TUI 命令：`/files watch <dir>`、`/files stop`、`/files list`、`/files remove <file>`、`/files add <path>`
- `tui/app.py`: 索引就绪后自动启动 watcher，退出时 `finally` 中停止
- **#16: LLM 元问题回答** — 在 context 中标注来源文件名，使 LLM 能回答文件数量、文件名等元问题

#### `src/rag.py`

- 新增 `_build_context(top_indices, docs, metadatas)` 函数：遍历 `top_indices`，从 `metadatas[i]["source"]` 获取文件名，为每个 chunk 添加 `[Source: filename]` 前缀
- 更新 `SYSTEM_PROMPT`：添加"每个文档片段前标注了[Source: 文件名]，你可以通过统计不同的[Source: 文件名]来回答关于文件数量、文件名等元问题"指令
- `answer_query` (line 710)：`"\n\n".join([enriched_docs[i] for i in top_indices])` → `_build_context(top_indices, enriched_docs, metadatas)`
- `answer_query_stream` (line 937)：同上替换

#### `src/graph_rag.py`

- import 新增 `_build_context`
- `graph_rag_pipeline` (line 418)：`" ".join(top_docs)` → `_build_context(top_indices, all_docs, all_metadatas)`
- CLI 首次查询 (line 472)：同上替换
- CLI 对话循环 (line 510)：同上替换
- `graph_query_stream` (line 550)：`" ".join(docs[:k])` → `_build_context(top_indices, all_docs, all_metadatas)`
- **关键**：graph_rag 中传 `all_docs`（全量列表）而非 `top_docs`/`docs[:k]`（截断列表），因为 `top_indices` 是全局索引

#### `tests/test_llm_meta_answer.py` (新建 10 个测试)

| 测试类 | 数量 | 说明 |
|--------|------|------|
| `TestBuildContextFunction` | 7 | 函数存在性、单/多文件标注、重复来源、分隔符、缺 source 兜底、非连续索引 |
| `TestContextInRagPipeline` | 2 | metadata 含 source、RAG 流程中 source 可访问 |
| `TestLlmCanAnswerMetaQuestion` | 1 | 端到端集成（需 API key）|

### Changed

- `tui/screens/chat.py`: `_manage_files()` 替换为 `_handle_files()`，支持子命令路由
- `tui/screens/chat.py`: `_toggle_mode()` 重写，支持 Standard→Graph 自动构建（Confirm → 进度条 → 成功/错误提示），Graph→Standard 直接切换
- `tui/service.py`: 新增 `set_mode()` 和 `build_kg_from_chromadb()` 方法，供新版 `_toggle_mode` 调用

### Fixed

- `/mode` 命令报 `NameError: name 'add_files_to_index' is not defined` — 在 `tui/service.py` 的 `from src.rag import` 中添加缺失的 `add_files_to_index`
- `/mode` 显示旧警告 `"Build with graph mode first to use /mode."` — 重写 `_toggle_mode()`，改为带确认提示、进度条、异常处理的自动构建流程
- 知识图谱构建进度条初始即显示 100% — `add_task(total=1)` 改为 `total=None`，回调中同步传入 `total=total`，使百分比 = `done/total` 正常递增

### Fixed

- **无 API 配置时错误显示 Sources** — 当 `.env` 未配置 `API_KEY`/`BASE_URL` 时，错误消息与 Sources 同时显示
  - `answer_query_stream` / `graph_query_stream` 在调用 LLM 前先检查 API 配置，配置无效时直接返回空 sources 和错误 stream
  - 避免无效的检索计算和 sources 格式化

- `build_index(force_rebuild=True)` 改为原子删除并重建 collection，避免逐条删除文档的低效操作，同路径下其他 collection 不再被连带删除

### Changed

- **README Logo** — 将 SVG（内嵌 base64 PNG）替换为直接引用原始 PNG 文件，更简单可靠
  - 删除 `.github/images/logo-light.svg` 和 `.github/images/logo-dark.svg`
  - 新增 `.github/images/mneme-logo.png`（原始 1053×208 PNG）
  - README.md / README.zh.md 中的 `<picture>`（暗黑/亮色切换）替换为简单 `<img>` 标签
  - 参考 `obsidian-with-kilocode` 项目的 logo 展示方式

### Planned

- Cross-encoder reranking for improved retrieval quality
- Query intent routing for complex multi-part questions
- Multi-language query expansion
- Persistent configuration with validation
