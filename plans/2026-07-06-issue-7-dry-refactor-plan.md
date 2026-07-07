# Issue #7 — 消除重复定义与 sys.path 散落（DRY 重构）

> **严重程度**: MEDIUM  
> **标签**: `refactor`, `dry`, `code-quality`  
> **关联文件**: `src/rag.py`, `tui/screens/home.py`, `tui/screens/chat.py`, `tui/constants.py`, `tui/service.py`, `src/graph_rag.py`, `scripts/run_temperature_test.py`, `tests/` 下 10 个测试文件  
> **计划日期**: 2026-07-06（修正版 v2）

---

## 1. 问题摘要

### 1.1 重复定义清单

| 重复项 | 定义位置 | 使用位置 | 重复次数 |
|--------|---------|---------|---------|
| `TEXT_EXTENSIONS` / `_SUPPORTED_EXTENSIONS` | `src/rag.py:61-67` | `tui/constants.py:1-8`, `tui/screens/home.py:13`, `tui/file_watcher.py:9` | **3 处** |
| `_collection_exists()` | `src/rag.py:216-220` | `tui/screens/home.py:46-53` | **2 处** |
| `sys.path` 注入 | `src/rag.py:28-30`, `src/graph_rag.py:11-13`, `tui/service.py:6-9`, `tui/screens/home.py:14-17`, `scripts/run_temperature_test.py:12`, `tests/` 下 10 个测试文件 | 各文件顶部 | **15 处** |

### 1.2 影响

- **维护成本**: 扩展名列表修改需在 3 处同步，极易遗漏（如新增 `.rst` 或 `.adoc` 支持）。
- **行为不一致风险**: 两处 `_collection_exists` 若未来需要统一变更（如改为检查磁盘目录而非调用 ChromaDB API），必须同时修改两处。
- **反模式**: `sys.path` 运行时注入是 Python 包管理的反模式，导致代码无法作为正常包安装使用，IDE 静态分析失效。

---

## 2. 根因分析

1. **缺乏单一数据源 (SSOT)**: 扩展名列表没有放在公共模块中导出，各消费者各自复制粘贴。
2. **模块边界模糊**: `tui/screens/home.py` 重复实现了本应由 `src/rag.py` 提供的工具函数 `_collection_exists`。
3. **包结构未正确安装**: 项目有 `src/__init__.py` 和 `tui/__init__.py`，但没有 `setup.py`/`pyproject.toml` 配置，导致运行时只能通过 `sys.path` 注入来 import。

---

## 3. 修复方案（三阶段）

### 阶段一：统一扩展名列表 → `src/rag.py` 导出

**目标**: 让扩展名列表成为唯一权威定义，其他位置全部改为从 `src.rag` 导入。

#### 3.1.1 修改 `src/rag.py` — 新增 `SUPPORTED_EXTENSIONS`

`TEXT_EXTENSIONS` 当前定义为纯文本扩展名集合（不含 `.pdf`、`.docx`）。
`_SUPPORTED_EXTENSIONS` 在 `tui/constants.py` 中定义为包含 `.pdf`、`.docx` 的元组。

两者**语义不等价**，不能直接替换。需在 `src/rag.py` 中新增 `SUPPORTED_EXTENSIONS`：

```python
# src/rag.py
# -- 支持的文本扩展名 --
TEXT_EXTENSIONS = {
    ".txt", ".md", ".markdown", ".html", ".htm",
    ".json", ".csv", ".xml", ".yaml", ".yml",
    ".toml", ".cfg", ".ini", ".conf", ".log",
    ".py", ".js", ".ts", ".css", ".sql",
    ".sh", ".bat", ".gitignore",
}

# 所有支持的扩展名（包含 PDF/DOCX，供 TUI 文件选择器使用）
SUPPORTED_EXTENSIONS = TEXT_EXTENSIONS | {".pdf", ".docx"}
```

#### 3.1.2 修改 `tui/constants.py`

```python
# tui/constants.py
# 移除硬编码的 _SUPPORTED_EXTENSIONS，改为从 src.rag 导入
from src.rag import SUPPORTED_EXTENSIONS as _SUPPORTED_EXTENSIONS
```

#### 3.1.3 修改 `tui/screens/home.py`

```python
# tui/screens/home.py
# 移除：from tui.constants import _SUPPORTED_EXTENSIONS
# 改为：
from src.rag import SUPPORTED_EXTENSIONS as _SUPPORTED_EXTENSIONS
```

**验收标准**:  
- `grep -r "SUPPORTED_EXTENSIONS" tui/` 仅在 `constants.py` 和 `home.py` 中有 import 引用。  
- `grep -r "TEXT_EXTENSIONS" src/` 仅在 `rag.py` 中有一处定义。  
- `grep -r "_SUPPORTED_EXTENSIONS" tui/` 仅在 `constants.py`、`home.py`、`file_watcher.py` 中有引用。  

---

### 阶段二：统一 `_collection_exists` → `src/rag.py` 导出

**目标**: 删除 `tui/screens/home.py` 中的重复实现，改为从 `src.rag` 导入。

#### 3.2.1 修改 `tui/screens/home.py`

```python
# tui/screens/home.py
# 移除以下函数：
# def _collection_exists(name: str) -> bool:
#     """Check whether a ChromaDB collection already exists on disk."""
#     try:
#         client = chromadb.PersistentClient(path=CHROMA_DB_PATH)
#         client.get_collection(name)
#         return True
#     except Exception:
#         return False

# 改为从 src.rag 导入：
from src.rag import _collection_exists
```

#### 3.2.2 修改 `tui/screens/home.py` 中 `_collection_exists` 的调用点

`home.py` 版本的 `_collection_exists(name)` 在函数内部创建 `client`，而 `src/rag.py` 版本接受 `client` 参数。修改调用点：

```python
# 原代码（在 render_home 函数中）
# exists = _collection_exists(collection)

# 新代码
client = chromadb.PersistentClient(path=CHROMA_DB_PATH)
exists = _collection_exists(client, collection)
```

**验收标准**:  
- `grep -r "def _collection_exists" .` 仅在 `src/rag.py` 中有一处定义。  
- `tui/screens/home.py` 成功从 `src.rag` 导入 `_collection_exists`。  

---

### 阶段三：移除 `sys.path` 注入，改用包安装方式

**目标**: 消除 15 处 `sys.path` 运行时注入，让项目可以通过标准 Python 包方式运行。

#### 3.3.1 当前 `sys.path` 注入点

| 文件 | 注入代码 |
|------|---------|
| `src/rag.py:28-30` | `_SRC = os.path.dirname(...); sys.path.insert(0, _SRC)` |
| `src/graph_rag.py:11-13` | 同上 |
| `tui/service.py:6-9` | `_ROOT = os.path.dirname(...); sys.path.insert(0, _ROOT)` |
| `tui/screens/home.py:14-17` | 同上 |
| `scripts/run_temperature_test.py:12` | `sys.path.insert(0, "/Users/...")` |
| `tests/` 下 10 个测试文件 | `sys.path.insert(0, str(PROJECT_ROOT))` |

#### 3.3.2 方案选择

**采用方案: `pip install -e .` 可编辑安装**

在项目根目录创建/修改 `pyproject.toml`，使 `src` 和 `tui` 成为可安装的 Python 包。

```toml
# pyproject.toml（新增/修改）
# 注意：本项目依赖（chromadb, sentence-transformers, openai 等）
# 仍需通过 pip install -r requirements.txt 手动安装
[build-system]
requires = ["setuptools>=61.0", "wheel"]
build-backend = "setuptools.build_meta"

[project]
name = "mneme"
version = "0.1.0"
description = "Knowledge-Augmented Q&A System"
requires-python = ">=3.10"

[tool.setuptools.packages.find]
where = ["."]
include = ["src*", "tui*"]
```

然后执行：

```bash
pip install -e .
```

之后所有文件中的 `sys.path` 注入可以安全移除，import 路径保持不变（如 `from src.rag import ...`）。

对于不想安装的用户，提供 `PYTHONPATH` 替代方案：

```bash
export PYTHONPATH="${PYTHONPATH}:$(pwd)"
python src/rag.py
```

#### 3.3.3 各文件修改

**`src/rag.py`** — 移除 `sys.path` 注入 + 修复 `rag_query_decomposer` 导入：

```python
# 删除以下代码：
# _SRC = os.path.dirname(os.path.abspath(__file__))
# if _SRC not in sys.path:
#     sys.path.insert(0, _SRC)

# 修改两处函数内延迟导入（第 683 行和第 903 行）：
# from rag_query_decomposer import decompose_query_llm
# 改为：
from src.rag_query_decomposer import decompose_query_llm
```

> 建议：将这两处函数内延迟导入提升到文件顶部（第 18–26 行 import 块之后），避免运行时重复 import。

**`src/graph_rag.py`** — 移除 + 修复导入：

```python
# 删除以下代码：
# _SRC = os.path.dirname(os.path.abspath(__file__))
# if _SRC not in sys.path:
#     sys.path.insert(0, _SRC)

# 修改导入（第 14 行）：
# from rag import (
# 改为：
from src.rag import (
    build_bm25_index,
    build_index, ask_for_files, _collection_exists,
    add_files_to_index,
    retrieve_hybrid_with_sources, dynamic_top_k,
    answer_with_llm_history, format_sources,
    _build_context,
    enrich_context,
    SentenceTransformer, chromadb,
    EMBEDDING_MODEL_NAME, DEFAULT_COLLECTION_NAME,
    DEFAULT_TOP_K, DEFAULT_MIN_K, DEFAULT_MAX_K,
    CHROMA_DB_PATH, DEFAULT_LLM_MODEL,
)
```

**`src/graph_rag.py` 底部导入（第 567-568 行）移到文件顶部**：

```python
# 当前在文件底部（第 567-568 行）：
# from typing import Generator
# from rag import answer_with_llm_history_stream

# 应移到文件顶部（与其他 import 放在一起），并修改为：
from typing import Generator
from src.rag import answer_with_llm_history_stream
```

**`tui/service.py`** — 移除 + 修复导入：

```python
# 删除以下代码：
# _ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# if _ROOT not in sys.path:
#     sys.path.insert(0, _ROOT)

# 修改导入（第 25 行）：
# from graph_rag import (
# 改为：
from src.graph_rag import (
    prepare_graph_index,
    graph_query_stream,
    KnowledgeGraph,
)
```

**`tui/screens/home.py`** — 移除：

```python
# 删除以下代码：
# _ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
# if _ROOT not in sys.path:
#     sys.path.insert(0, _ROOT)
```

**`scripts/run_temperature_test.py`** — 移除 + 修复导入：

```python
# 删除以下代码：
# sys.path.insert(0, "/Users/deepprinciple/Desktop/henry/0")

# 修改导入（第 15 行）：
# from graph_rag import prepare_graph_index, graph_query_stream
# 改为：
from src.graph_rag import prepare_graph_index, graph_query_stream
```

**`tests/` 下 10 个测试文件** — 移除 `sys.path` 注入：

```python
# 删除以下代码（各测试文件顶部）：
# PROJECT_ROOT = Path(__file__).resolve().parent.parent
# sys.path.insert(0, str(PROJECT_ROOT))
```

受影响文件清单：
- `tests/analysis/test_anchor_chunk.py`
- `tests/analysis/test_anchor_chunk2.py`
- `tests/analysis/test_custom_bm25.py`
- `tests/analysis/test_first_principles.py`
- `tests/test_graph_rag_batch.py`
- `tests/test_graph_rag_enrich.py`
- `tests/test_hierarchical_enrich.py`
- `tests/test_llm_client_singleton.py`
- `tests/test_llm_meta_answer.py`
- `tests/test_retrieval_fix.py`

#### 3.3.4 直接运行脚本的替代方案

移除 `sys.path` 后，`python src/rag.py` 等直接运行方式会失败（因为 `src/rag.py` 中 `from src.rag_query_decomposer import ...` 等本地导入需要包安装或 `PYTHONPATH` 支持）。

**方案 A（推荐）: 包安装模式**

```bash
pip install -e .
python -m src.rag --files ... --query ...
```

**方案 B: PYTHONPATH 模式**

```bash
export PYTHONPATH="${PYTHONPATH}:$(pwd)"
python src/rag.py --files ... --query ...
```

**方案 C: 创建 `src/__main__.py`**

为支持 `python -m src.rag`，在 `src/` 下创建 `__main__.py`：

```python
# src/__main__.py
from src.rag import main
if __name__ == "__main__":
    main()
```

> 注：`src/rag.py` 当前没有 `main()` 函数（入口在 `if __name__ == "__main__":` 块中），如需支持 `python -m src.rag`，需将 CLI 逻辑提取为 `main()` 函数。

**验收标准**:  
- `grep -r "sys.path" src/ tui/ scripts/ tests/` 无匹配（或仅在真正需要动态路径的场景下保留）。  
- `python -c "from src.rag import TEXT_EXTENSIONS, SUPPORTED_EXTENSIONS, _collection_exists; print('OK')"` 执行成功。  
- `pip install -e .` 后，`python -m tui` 能正常启动。  

---

## 4. 修改文件清单

| 序号 | 文件 | 修改类型 | 修改内容 |
|------|------|---------|---------|
| 1 | `src/rag.py` | 新增 + 删除 + 修改 | 新增 `SUPPORTED_EXTENSIONS`；移除顶部 `sys.path` 注入；两处 `from rag_query_decomposer import` → `from src.rag_query_decomposer import` |
| 2 | `src/graph_rag.py` | 删除 + 修改 | 移除 `sys.path` 注入；`from rag import` → `from src.rag import`；底部 `from rag import` 移到顶部 |
| 3 | `tui/constants.py` | 修改 | 移除硬编码 `_SUPPORTED_EXTENSIONS`，改为 `from src.rag import SUPPORTED_EXTENSIONS as _SUPPORTED_EXTENSIONS` |
| 4 | `tui/screens/home.py` | 删除 + 修改 | 移除 `sys.path` 注入；移除 `_collection_exists` 定义；改为从 `src.rag` 导入 `SUPPORTED_EXTENSIONS` 和 `_collection_exists`；调整调用点 |
| 5 | `tui/service.py` | 删除 + 修改 | 移除 `sys.path` 注入；`from graph_rag import` → `from src.graph_rag import` |
| 6 | `scripts/run_temperature_test.py` | 删除 + 修改 | 移除硬编码 `sys.path.insert`；`from graph_rag import` → `from src.graph_rag import` |
| 7 | `tests/analysis/test_anchor_chunk.py` | 删除 | 移除 `sys.path` 注入 |
| 8 | `tests/analysis/test_anchor_chunk2.py` | 删除 | 移除 `sys.path` 注入 |
| 9 | `tests/analysis/test_custom_bm25.py` | 删除 | 移除 `sys.path` 注入 |
| 10 | `tests/analysis/test_first_principles.py` | 删除 | 移除 `sys.path` 注入 |
| 11 | `tests/test_graph_rag_batch.py` | 删除 | 移除 `sys.path` 注入 |
| 12 | `tests/test_graph_rag_enrich.py` | 删除 | 移除 `sys.path` 注入 |
| 13 | `tests/test_hierarchical_enrich.py` | 删除 | 移除 `sys.path` 注入 |
| 14 | `tests/test_llm_client_singleton.py` | 删除 | 移除 `sys.path` 注入 |
| 15 | `tests/test_llm_meta_answer.py` | 删除 | 移除 `sys.path` 注入 |
| 16 | `tests/test_retrieval_fix.py` | 删除 | 移除 `sys.path` 注入 |
| 17 | `pyproject.toml` | 新增 | 添加包安装配置（如不存在） |
| 18 | `README.md` | 修改 | 更新启动说明 |
| 19 | `CHANGELOG.md` | 修改 | 记录本次重构 |

---

## 5. 测试与验证计划

### 5.1 单元测试

```bash
# 1. 验证扩展名导入正确
python -c "from src.rag import TEXT_EXTENSIONS, SUPPORTED_EXTENSIONS; print('.pdf' in SUPPORTED_EXTENSIONS)"  # 期望: True
python -c "from src.rag import TEXT_EXTENSIONS, SUPPORTED_EXTENSIONS; print('.pdf' in TEXT_EXTENSIONS)"      # 期望: False

# 2. 验证 _collection_exists 可导入
python -c "from src.rag import _collection_exists; print(type(_collection_exists))"  # 期望: <class 'function'>

# 3. 验证包安装
pip install -e .
python -c "from src.rag import SUPPORTED_EXTENSIONS; from tui.constants import _SUPPORTED_EXTENSIONS; assert SUPPORTED_EXTENSIONS is _SUPPORTED_EXTENSIONS"
```

### 5.2 集成测试

```bash
# 4. 验证 TUI 能正常启动（包安装模式）
python -m tui

# 5. 验证 RAG pipeline 能正常运行（PYTHONPATH 模式）
PYTHONPATH="${PYTHONPATH}:$(pwd)" python src/rag.py --files test_texts/*.md --query "test"

# 6. 验证 Graph RAG pipeline 能正常运行
PYTHONPATH="${PYTHONPATH}:$(pwd)" python src/graph_rag.py --files test_texts/*.md --query "test"

# 7. 验证 temperature test 脚本能运行
PYTHONPATH="${PYTHONPATH}:$(pwd)" python scripts/run_temperature_test.py
```

### 5.3 回归测试

```bash
# 8. 运行现有测试套件（包安装模式下）
pip install -e .
pytest tests/ -v
```

---

## 6. 风险与回滚

| 风险 | 缓解措施 |
|------|---------|
| `pip install -e .` 后 import 路径解析失败 | 先在虚拟环境中测试，确认 `PYTHONPATH` 兜底方案可用 |
| `src/graph_rag.py` 的 `from src.rag import` 改为绝对导入后，直接 `python src/graph_rag.py` 运行失败 | 这是预期行为；应通过 `PYTHONPATH=$(pwd) python src/graph_rag.py` 或包安装后运行 |
| 移除 `sys.path` 后某些脚本在特定目录下运行失败 | 提供 `PYTHONPATH=$(pwd)` 替代文档 |
| `_collection_exists` 以下划线开头，跨模块使用可能被视为"内部 API" | 保持现状（已有 `tui/service.py` 导入），或考虑未来重命名为 `collection_exists` |
| `import sys` 在移除 `sys.path` 后可能成为孤立导入 | 实施时检查并移除不再使用的 `import sys` |

---

## 7. 验收标准（Definition of Done）

- [ ] `TEXT_EXTENSIONS` 仅在 `src/rag.py` 中定义一次；`SUPPORTED_EXTENSIONS` 包含 `.pdf` 和 `.docx`。
- [ ] `tui/constants.py` 和 `tui/screens/home.py` 正确从 `src.rag` 导入 `SUPPORTED_EXTENSIONS`。
- [ ] `_collection_exists` 仅在 `src/rag.py` 中定义一次，`tui/screens/home.py` 已删除重复实现并正确导入。
- [ ] 所有 15 处 `sys.path` 注入代码已移除（含 10 个测试文件）。
- [ ] `src/graph_rag.py` 中所有 `from rag import` 已改为 `from src.rag import`。
- [ ] `tui/service.py` 中 `from graph_rag import` 已改为 `from src.graph_rag import`。
- [ ] `scripts/run_temperature_test.py` 中 `from graph_rag import` 已改为 `from src.graph_rag import`。
- [ ] `src/graph_rag.py` 底部的 `from rag import answer_with_llm_history_stream` 已移到文件顶部并修正为 `from src.rag import`。
- [ ] `src/rag.py` 中两处 `from rag_query_decomposer import` 已改为 `from src.rag_query_decomposer import`（建议提升到文件顶部）。
- [ ] 项目根目录已配置 `pyproject.toml` 支持 `pip install -e .`。
- [ ] `README.md` 已更新启动说明（包含 `pip install -e .` 和 `PYTHONPATH` 两种方案）。
- [ ] `CHANGELOG.md` 已记录本次重构。
- [ ] 运行 `pytest tests/ -v` 全部通过。
- [ ] TUI (`python -m tui`) 能正常启动且功能无回归。
- [ ] RAG pipeline (`PYTHONPATH=$(pwd) python src/rag.py --files ... --query ...`) 能正常运行。
- [ ] Graph RAG pipeline 能正常运行。

---

## 8. 参考

- [Python Packaging User Guide — Editable installs](https://packaging.python.org/en/latest/discussions/src-layout-vs-flat-layout/)
- [PEP 518 — Specifying Minimum Build System Requirements for Python Projects](https://peps.python.org/pep-0518/)
