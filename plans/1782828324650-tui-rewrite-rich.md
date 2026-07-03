# TUI 重写计划：Textual → Rich

## 决策汇总

| 决策 | 结论 |
|------|------|
| 框架 | 抛弃 Textual → Python Rich |
| 配色 | **保留**当前 Obsidian 深紫（`#1e1a2e`, `#a78bfa` 等） |
| 交互 | 分页面：Home → Loading → Chat |
| Stats | 保留右侧栏（Rich `Layout` 实现） |
| 范围 | 重写整个 `tui/` 目录 |
| 后端 | `rag.py` / `graph_rag.py` 不动 |
| 异步 | 抛弃 asyncio，改用同步代码（Rich 不支持 async） |

---

## 第 1 步：删除旧 tui/，安装 Rich

**操作：**
1. 删除 `tui/` 下所有现有文件
2. `pip install rich`

**验证：** `python -c "from rich.console import Console; Console().print('OK')"`

---

## 第 2 步：theme.py — 保留配色，适配 Rich

**文件：** `tui/theme.py`

当前 Obsidian 配色保留，转换为 Rich Style 格式：

```python
THEME = {
    "bg": "#1e1a2e",
    "surface": "#2a2540",
    "text": "#d4d0e8",
    "text_dim": "#6b6494",
    "accent": "#a78bfa",
    "success": "#a3e635",
    "warning": "#fbbf24",
    "error": "#fb7185",
    "user_border": "#c084fc",
    "assistant_border": "#818cf8",
    "source_border": "#34d399",
}
```

**行数：** ~13 行

---

## 第 3 步：app.py — 主应用 + 布局管理

**文件：** `tui/app.py`

```python
class RagApp:
    def __init__(self):
        self.console = Console()
        self.service = LocalRagService()
        self.mode = "standard"       # "standard" | "graph"
        self.history = []
        self.alpha = 0.7
        self.temperature = 0.1
        self.top_k_range = (3, 20)

    def run(self):
        """入口：Home → Loading → Chat → 循环"""
```

使用 Rich `Layout` 实现右侧栏布局：

```python
layout = Layout()
layout.split_column(
    Layout(name="header", size=3),
    Layout(name="body"),
)
layout["body"].split_row(
    Layout(name="main"),
    Layout(name="sidebar", size=42),
)
```

用 `Live(layout, screen=True, refresh_per_second=10)` 实现全屏刷新（代替 Textual 的 reactive）。

**关键原则：**
- 每个 "页面" 是 `render_xxx(layout, state)` 函数
- `Live` context 负责持续刷新
- 输入用 `rich.prompt` 或 `Prompt.ask()`

**行数：** ~80 行

---

## 第 4 步：screens/home.py — Home 页

**文件：** `tui/screens/home.py`

```python
def render_home(console: Console, app: "RagApp") -> dict:
    """渲染 Home 页，返回用户选择 {files, mode, collection}"""
```

**布局（`Layout`）：**
```
┌──────────────────────────────┐
│         RAG System           │
│    ── 知识库问答系统 ──       │
│                              │
│  Mode:  [Standard] [Graph]   │
│  Files: [______________]     │
│  Coll:  [auto_________]      │
│                              │
│        [ 开始对话 ]           │
└──────────────────────────────┘
```

- 上方：ASCII Logo（保持现有设计，紫色 accent）
- 中部：表单（RadioButton 用 Rich `Prompt` 单选 → 键盘上下键选择）
- 按钮：`Prompt.ask()` 选择

**注意：** Async 全部移除。`prepare_index` 同步调用，`console.status()` 显示 loading（自带 spinner）。

**行数：** ~60 行

---

## 第 5 步：screens/loading.py — Loading 页

**文件：** `tui/screens/loading.py`

```python
def render_loading(console: Console, app: "RagApp", files: list[str], mode: str) -> bool:
    """构建索引，返回 True 成功 / False 失败"""
```

使用 Rich `console.status()` 或 `Progress` 显示：

```
⏳ 正在构建索引...  [10/237 chunks]
   → 加载: CHANGELOG.md (5 切片)
   → 加载: paper.pdf (234 切片)
   → 提取实体: 150/234

Graph RAG 时额外：
   → 构建知识图谱: 1641 实体, 13316 关系
```

- `console.status()` 自动显示 spinner + 动态更新文字
- 后端调用 `app.service.prepare_index()`（去掉 `async`）

**行数：** ~50 行

---

## 第 6 步：screens/chat.py — Chat 页

**文件：** `tui/screens/chat.py`

核心渲染函数：

```python
def run_chat_loop(console: Console, app: "RagApp"):
    """Chat 主循环：渲染布局 + 处理输入"""
```

**布局（`Layout`）：**
```
┌──────────────────────────────┬─────────┐
│ Messages                     │ Session │
│                              │ Mode:   │
│ [User] 第一轮问答...          │ Graph   │
│                              │         │
│ [Asst] 根据文档，changelog   │ Stats   │
│ 中共有 6 个改动阶段...        │ Chunks  │
│                              │ 239     │
│ [来源] [1] CHANGELOG.md...   │ Files   │
│                              │ · CH..  │
│                              │ · pa..  │
│                              │         │
│                              │ Params  │
│                              │ α: 0.7  │
│                              │ T: 0.1   │
├──────────────────────────────┤         │
│ > changelog有多少个改动阶段   │ API ●   │
└──────────────────────────────┴─────────┘
```

**消息渲染**（用 `rich.panel.Panel` 替代 Textual Widget）：
```python
def render_user_msg(text: str) -> Panel:
    return Panel(text, border_style=THEME["user_border"], title="You")

def render_assistant_msg(text: str) -> Panel:
    return Panel(Markdown(text), border_style=THEME["assistant_border"], title="Assistant")

def render_sources(sources: str) -> Panel:
    return Panel(sources, border_style=THEME["source_border"], title="来源")
```

**流式输出**：
```python
with Live(layout, screen=True, refresh_per_second=10) as live:
    for chunk in stream:  # 同步 generator，不需要 Queue！
        full_text += chunk
        panel = render_assistant_msg(full_text)
        layout["main"].update(panel)
```

**输入**：用 `Prompt.ask(">")` 或手动 `console.input()`，`/` 命令过滤。

**行数：** ~120 行

---

## 第 7 步：components/sidebar.py — 侧边栏

**文件：** `tui/components/sidebar.py`

```python
def render_sidebar(stats: dict, app: "RagApp") -> Panel:
    """返回一个 Panel，内含 stats 信息"""
```

用 `rich.table.Table` 或 `rich.text.Text` 组装，title 为紫色 accent。

```
Session
  Mode:       Graph RAG
  Collection: graph_rag_9eb
Index Stats
  Chunks:     239
  Entities:   1641
  Relations:  13316
  Files:
    • CHANGELOG.md
    • paper.pdf
Parameters
  Alpha:    0.7
  Top-K:    (3, 50)
  Temp:     0.1
```
API 在线状态：`●` 绿色 / `●` 红色

**行数：** ~50 行

---

## 第 8 步：components/prompt.py — 输入区

**文件：** `tui/components/prompt.py`

```python
def ask_input(console: Console, app: "RagApp") -> tuple[str, bool]:
    """获取用户输入，返回 (text, is_command)"""
```

- 用 `Prompt.ask(">")` 获取输入
- 以 `/` 开头 → 命令，调用对应函数
- 普通文本 → 发送消息
- 空输入 → 忽略
- `Ctrl+C` → 退出

Slash 命令：`/help` `/files` `/mode` `/alpha` `/status` `/clear` `/quit`

**行数：** ~50 行

---

## 第 9 步：components/footer.py — 状态栏

**文件：** `tui/components/footer.py`

```python
def render_footer(stats: dict, app: "RagApp") -> Text:
    """一行状态栏，左/中/右三段式"""
```

用 `rich.text.Text` 组装：
```
/path/to/cwd    Ctrl+P cmd    API ●  graph_rag 239 chunks
```

**行数：** ~30 行

---

## 第 10 步：components/message.py — 消息渲染

**文件：** `tui/components/message.py`

```python
def user_message(text: str) -> Panel:
    """紫色左边框 + 面板背景"""

def assistant_message(text: str) -> Panel:
    """靛蓝左边框 + Markdown 渲染 + 流式更新"""

def source_reference(sources: str) -> Panel:
    """翡翠绿左边框 + 来源引用"""

def thinking_message(status: str = "检索中...") -> Panel:
    """Spinner + 状态文字"""
```

Rich 的 `Panel` 天然支持边框颜色、标题、padding，相当于 Textual 的 Widget。Markdown 用 `rich.markdown.Markdown` 自动渲染（粗体、列表、代码块等）。

**行数：** ~40 行

---

## 第 11 步：service.py — 精简

**文件：** `tui/service.py`

**改动：** 移除所有 async/await/asyncio.Queue/daemon 线程/回调函数，改为同步：

```python
class LocalRagService:
    def __init__(self):
        self._model = SentenceTransformer(EMBEDDING_MODEL_NAME)

    def prepare_index(self, files, collection, rebuild=False) -> dict:
        """同步调用 rag.prepare_index()"""
    
    def query(self, query, history, temperature=0.1) -> tuple[Generator, str]:
        """返回 (chunk_generator, sources_str) — 同步 generator"""
    
    def graph_query(self, query, history, alpha=0.7, temperature=0.1) -> tuple[Generator, str]:
        """同上，Graph RAG 版本"""
    
    def add_files(self, paths) -> dict:
        """同步调用 rag.add_files_to_index()"""
    
    def get_stats(self) -> dict:
        """同步返回 stats dict"""
```

**移除项：**
- `_get_loop()` 方法
- `asyncio.Queue` 流式桥接
- `daemon` 线程
- `asyncio.to_thread()` 包装

**行数：** ~100 行（删减至原 ~50%）

---

## 第 12 步：keys.py — 快捷键

**文件：** `tui/keys.py`

简化。Rich 不提供全局快捷键绑定，改为：
- 在 chat 循环中监听 `Prompt.ask()` 返回的文本
- `/` 命令处理
- `Ctrl+C` → `sys.exit(0)`

```python
COMMANDS = {
    "/help": "显示帮助",
    "/files": "文件管理",
    "/mode": "切换 RAG 模式",
    "/alpha": "调节融合权重",
    "/status": "系统状态",
    "/clear": "清空对话",
    "/quit": "退出",
}
```

**行数：** ~20 行

---

## 第 13 步：__main__.py + __init__.py

**文件：** `tui/__main__.py`

```python
from tui.app import RagApp
RagApp().run()
```

`__init__.py` 保持空文件。

---

## 文件结构（最终）

```
tui/
├── __init__.py
├── __main__.py
├── app.py                  # RagApp 类 + Layout 管理
├── service.py              # 同步 Service 层
├── theme.py                # Obsidian 配色
├── keys.py                 # Slash 命令表
├── screens/
│   ├── __init__.py
│   ├── home.py             # Home 页
│   ├── loading.py          # Loading 过渡
│   └── chat.py             # Chat 主循环
├── components/
│   ├── __init__.py
│   ├── message.py          # 消息 Panel（user/assistant/sources/thinking）
│   ├── sidebar.py          # 侧边栏 Panel
│   ├── prompt.py           # 输入处理
│   └── footer.py           # 底部状态栏
└── dialogs/
    ├── __init__.py
    ├── help.py
    ├── file_manager.py
    └── status.py
```

## 依赖变化

**移除：** `textual`, `textual-autocomplete`

**新增：** `rich`（`pip install rich`）

---

## 验证方式

1. `python -m tui` 启动 → Home 页渲染正常（Logo + 表单）
2. 选择文件 → 选择模式 → 点击开始 → Loading 页显示进度
3. 索引完成 → 进入 Chat → 侧边栏显示 stats
4. 输入问题 → 流式输出 LLM 回答 → Markdown 正确渲染
5. `/help` → 帮助信息显示
6. `/files` → 文件管理对话框
7. `/status` → 系统状态
8. `Ctrl+C` → 优雅退出
9. `pip list | grep textual` → 无 textual（已卸载）
