# RAG TUI 前端现状与开发计划

> 基于当前实际代码重构的计划，后续改动均与设计沟通确认。

## 技术概览

| 项目 | 现状 |
|------|------|
| **框架** | **Rich Console**（非 Textual），同步阻塞式 CLI 风格 |
| **Python 版本** | Python 3 |
| **后端集成** | 进程内直调（`rag.py` / `graph_rag.py`） |
| **流式输出** | 同步 Generator 收集完再整段打印，非逐字实时 |
| **配色** | 深紫色 Obsidian 风格（`THEME` 常量字典） |
| **代码总量** | ~1020 行，19 个文件 |

## 文件结构（实际现状）

```
tui/
├── __init__.py
├── __main__.py             # RagApp().run()
├── app.py                  # RagApp — Rich Console 顺序应用
├── service.py              # LocalRagService — 同步 Thin Wrapper
├── theme.py                # 配色常量
├── keys.py                 # 8 个 Slash 命令
├── screens/
│   ├── home.py             # Home 页（Logo + 模式 + collection + 文件 + 命令面板）
│   ├── loading.py          # 索引构建（Rich spinner）
│   └── chat.py             # Chat 循环（Rich Prompt + 7 个命令处理 + 每次回答后命令栏）
├── components/
│   ├── message.py          # 消息气泡（user/assistant/source/thinking）
│   ├── prompt.py           # match_command() 匹配
│   ├── sidebar.py          # ⚠️ 存在但未集成到应用中
│   └── footer.py           # ⚠️ 存在但未集成到应用中
└── dialogs/
    ├── file_manager.py     # /files — 添加/删除/列出文件（Rich Prompt）
    ├── help.py             # /help — 命令列表（Panel）
    └── status.py           # /status — 系统状态（Panel）
```

## 核心流程

```
python -m tui
  └─ RagApp.run()
       ├─ render_home()
       │     ├─ 显示 Logo + 系统名
       │     ├─ 选择模式（1=Standard, 2=Graph）
       │     ├─ 输入 Collection 名（检查是否已存在）
       │     ├─ [新] 输入文件路径
       │     ├─ [已有] 提示复用索引
       │     ├─ 显示命令面板（Table + Panel，深紫风格）
       │     └─ 确认 Start building index?
       │
       ├─ render_loading()
       │     └─ console.status(spinner) → prepare_index()
       │
       └─ run_chat_loop()
             ├─ 显示 "Ready." + 命令栏
               └─ 循环：
                   ├─ Prompt.ask("> /help /files ...")
                   ├─ Ctrl+L → console.clear() + 重绘命令栏
                   ├─ [slash命令] → 对应处理（help/status/mode/alpha/settings/files/clear/quit）
                   ├─ [普通问题] → spinner + service.query() + 收集流 → 打印用户+回答+来源
                   └─ 打印命令栏（含 API 状态 ● + Mode + Chunks + Alpha）
```

## 现有的 8 个命令

| 命令 | 功能 | 实现文件 |
|------|------|---------|
| `/help` | Panel 显示全部命令及其描述 | `chat.py:_show_help()` |
| `/files` | 交互式添加/删除/列出文件 | `chat.py:_manage_files()` |
| `/mode` | 切换 standard/graph 模式 | `chat.py:_toggle_mode()` |
| `/alpha` | 调节图谱融合权重 0.0-1.0 | `chat.py:_set_alpha()` |
| `/status` | 显示 collection/chunk/实体/文件列表 | `chat.py:_show_status()` → `render_sidebar()` |
| `/settings` | 配置 API Key / Base URL | `chat.py:_configure_settings()` |
| `/clear` | 清空当前对话 history | `chat.py` 内联 |
| `/quit` | 退出程序 | `chat.py` 内联 |

## LocalRagService 接口

| 方法 | 同步/异步 | 说明 |
|------|----------|------|
| `prepare_index(files, collection, force_rebuild, mode)` | 同步 | 构建/加载索引，返回 stats dict |
| `query(query, history, temperature, top_k_range)` | 同步 | Standard RAG，返回 (generator, sources_str) |
| `graph_query(query, history, alpha, temperature, top_k_range)` | 同步 | Graph RAG，返回 (generator, sources_str) |
| `add_files(file_paths)` | 同步 | 添加文件，返回 stats dict |
| `remove_file(filename)` | 同步 | 删除文件，返回 chunk 数 |
| `get_stats()` | 同步 | 返回 stats dict |
| `get_kg()` | 同步 | 返回 KnowledgeGraph 对象 |

## 消息组件

| 函数 | 返回 | 样式 |
|------|------|------|
| `user_message(text)` | `Panel` | 紫色边框，title="You" |
| `assistant_message(text)` | `Panel(Markdown)` | 靛蓝边框，title="Assistant" |
| `source_reference(sources)` | `Panel` | 翡翠绿边框，title="Sources" |
| `thinking_message(status)` | `Panel(Spinner)` | 靛蓝边框，含 spinner |

## 近期已完成的改进

1. **命令可见性**：Home 页底部 + Chat 页每次回答后都显示命令栏
2. **Collection 已存在检测**：`_collection_exists()` 避免重复输入文件
3. **命令栏**：提取为 `_command_bar()` 函数，Home 和 Chat 复用
4. **Sidebar 集成**：`/status` 改用 `render_sidebar()` 组件
5. **Footer 信息合并到命令栏**：`●` API 状态指示 + Mode + Chunks + Alpha
6. **查询 spinner**：等待回答期间显示 `Standard RAG thinking...`
7. **Ctrl+L 清屏**：Chat 页内清屏并保留命令栏
8. **`/settings` 命令**：TUI 内交互式配置 API Key / Base URL

## 待完善功能 — 需沟通确认

以下功能目前缺失或不完整，需要与你沟通细节后逐步实现。

### 1. 模型选择
- 当前：硬编码读取 `.env` 中的模型名
- 方向：[待沟通] 是否需要 `/models` 命令切换模型

### 2. Error 组件
- 当前：错误直接 `console.print()` 散落在各处
- 方向：[待沟通] 是否需要统一的错误展示组件

### 3. Loading 进度细化
- 当前：`console.status("Building index...")` 单行 spinner，无法显示进度
- 方向：[待沟通] 是否需要显示文件级别进度（x/n files）

## 配色方案（现行）

| 元素 | 颜色 |
|------|------|
| 背景 | `#1e1a2e` |
| 面板背景 | `#2a2540` |
| 主文字 | `#d4d0e8` |
| 次要文字 | `#6b6494` |
| 强调色 | `#a78bfa` |
| 成功/在线 | `#a3e635` |
| 警告 | `#fbbf24` |
| 错误 | `#fb7185` |
| 用户消息边框 | `#c084fc` |
| LLM 回答边框 | `#818cf8` |
| 来源引用边框 | `#34d399` |

## 依赖

```
# 当前实际依赖（TUI 部分仅需 rich，已随标准库？）
rich>=13.0
# 后端依赖
chromadb, sentence-transformers, rank_bm25, openai, pdfplumber, python-docx, networkx, PyMuPDF>=1.24.0
```

## 后续开发流程

1. 每个改动先沟通设计细节，确认后再实现
2. 每次改动后提交，标注改动文件和行数
3. 保持当前 Rich Console 架构，除非你确认切换到 Textual
