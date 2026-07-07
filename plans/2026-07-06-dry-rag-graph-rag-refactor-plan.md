# 修复计划：消除 rag.py 与 graph_rag.py 之间的代码重复（DRY）— 第三版

> **Issue**: #6a `__main__` CLI 循环重复 / #6b `prepare_index` 与 `prepare_graph_index` 高度重复
> **严重程度**: HIGH
> **日期**: 2026-07-06
> **状态**: 第三版（已处理第二轮审阅反馈）

---

## 1. 问题分析

### 1.1 重复代码清单

| 重复区域 | `src/rag.py` | `src/graph_rag.py` | 重复行数 | 其中将被提取的行数 |
|---------|-------------|-------------------|---------|------------------|
| **CLI 交互循环（可提取部分）** | `791–804`（索引准备 + 计时）、`808–847`（问答循环） | `488–497`（索引准备 + 计时）、`515–560`（问答循环） | ~75 行（含差异部分），其中 **~45 行** 为完全相同逻辑 | 先提取 ~45 行公共部分 |
| **索引准备** | `223–248`（`prepare_index`） | `361–400`（`prepare_graph_index`） | ~30 行，实际重叠约 **30-40%**（4-5 行可提取） | 4-5 行 |

**说明**：总重复范围 75 行中包含 `argparse` 定义（参数不同）、`collection_name` 生成（前缀不同）、`--query` 单次查询路径（graph_rag.py 特有），这些部分**不提取**。实际被提取的完全相同逻辑约 **45 行**（索引准备+计时 ~10 行 + 交互循环主体 ~35 行）。

### 1.2 重复逻辑对比

#### CLI 循环（#6a）— 高度重复

两个文件的 CLI 循环均包含以下**完全相同的逻辑**：
- ~~`argparse` 参数定义~~ → ❌ 不提取（参数不完全相同）
- ~~文件路径获取~~ → ❌ 不提取（完全相同但保持在各自 `__main__` 中使结构更清晰）
- ~~collection_name 生成~~ → ❌ 不提取（前缀不同）
- **索引准备 + 计时打印** → ✅ 提取（"文档库就绪（用时 X 分 Y 秒）"）
- **`+add` 命令解析与处理** → ✅ 提取（逗号/全角逗号分割、调用 `add_files_to_index`）
- **问答循环** → ✅ 提取（`input()` → 回答生成）
- **`dynamic_top_k` + `format_sources` 显示** → ✅ 提取
- **`history` 管理** → ✅ 提取（`history.append((query, answer))`）
- **计时打印** → ✅ 提取（"用时 X 分 Y 秒"）

**唯一差异**：
- `rag.py` 调用 `answer_query()`（标准 RAG，返回 `(answer, sources)`）
- `graph_rag.py` 调用 `graph_rag_pipeline()`（Graph RAG，返回单个 `answer`；`+add` 后需重建 KnowledgeGraph）
- `graph_rag.py` 额外支持 `--alpha` 参数和 `--query` 单次查询路径（`499–513` 行）

#### 索引准备（#6b）— 重叠有限

| 逻辑块 | `prepare_index` | `prepare_graph_index` | 相同？ |
|--------|----------------|----------------------|--------|
| 创建 `PersistentClient` | ✅ | ✅ | 相同 |
| `need_build` 判断 | ✅ | ✅ | 相同 |
| `kg_file` 路径 | ❌ 无 | 有 | 不同 |
| `need_build=True` 分支 | 调用 `build_index()` → `(model, collection)` | 调用 `build_graph_index()` → `(model, collection, bm25, all_docs, kg)` + `kg.save()` | **完全不同** |
| `need_build=False` 分支 | 加载 model + collection + `collection.get()` + `build_bm25_index()` | 同上 + KG 加载/重建逻辑 | ~40% 重叠 |
| 返回值 | 5-tuple | 6-tuple（多了 `kg`） | 不同 |

**结论**：两个函数实际重叠约 **30-40%**，仅 4-5 行可提取。强行提取 `_prepare_index_common` 收益有限，反而增加间接层次。

---

## 2. 修复方案

### 2.1 总体策略

| 问题 | 策略 | 理由 |
|-----|------|------|
| **#6a CLI 循环** | ✅ 提取到 `src/cli_loop.py` | 重复度高（~45 行公共逻辑），提取收益明确 |
| **#6b 索引准备** | ⚠️ 仅提取轻量 helper（`_ensure_client_and_check_rebuild`） | 实际重叠仅 30-40%，强行提取得不偿失 |

### 2.2 #6a 方案：提取公共 `cli_loop.py`

#### 核心设计：`is_graph_rag` 标志 + 辅助函数

使用 **boolean 标志** 区分两种模式，配合显式声明的辅助函数，避免抽象泄漏：

```python
# src/cli_loop.py — 核心函数
# ❌ 不使用策略回调类型（避免过度设计）
# ✅ 使用 if/else 分支 + 显式辅助函数

def run_interactive_session(
    file_paths: list[str],
    collection_name: str,
    *,
    force_rebuild: bool = False,
    alpha: float = 0.7,
    is_graph_rag: bool = False,
) -> None:
    """
    统一的交互式 CLI 会话入口。
    
    Args:
        file_paths: 初始文件路径列表
        collection_name: ChromaDB collection 名称
        force_rebuild: 是否强制重建索引
        alpha: Graph RAG 融合权重（仅 graph_rag 模式有效）
        is_graph_rag: 是否启用 Graph RAG 模式
    """
```

#### `cli_loop.py` 完整的内部结构

```python
# ── 辅助函数（cli_loop.py 内部定义）──

def _print_elapsed(label: str, t0: float, t1: float) -> None:
    """统一计时打印格式。"""
    elapsed = t1 - t0
    minutes = int(elapsed // 60)
    seconds = int(elapsed % 60)
    print(f"{label}（用时{minutes}分{seconds}秒）")


def _parse_add_paths(query: str) -> list[str]:
    """解析 +add 命令中的文件路径列表，兼容全角逗号。"""
    raw_paths = query[4:].strip()
    if not raw_paths:
        return []
    return [p.strip() for p in raw_paths.replace("，", ",").split(",") if p.strip()]


def _graph_rag_answer(
    query: str,
    model, collection, bm25,
    all_docs: list[str],
    all_metadatas: list[dict],
    kg,
    history: list[tuple[str, str]],
    alpha: float = 0.7,
) -> tuple[str, str]:
    """Graph RAG 回答生成（封装 6 步 pipeline）。
    
    此函数被 run_interactive_session 和 run_single_query 共用。
    """
    from graph_rag import graph_augmented_retrieve
    
    indices, fused_docs, fused_scores = graph_augmented_retrieve(
        query, model, collection, bm25, all_docs, kg, alpha=alpha,
    )
    k = dynamic_top_k(fused_scores, min_k=3, max_k=50)
    top_indices = indices[:k]
    enriched_docs = enrich_context(top_indices, all_docs, all_metadatas)
    context = _build_context(top_indices, enriched_docs, all_metadatas)
    answer = answer_with_llm_history(query, context, history=history, temperature=0.1)
    sources = format_sources(top_indices, enriched_docs, all_metadatas)
    return answer, sources


def run_single_query(
    query: str,
    *,    # Keyword-only: 索引准备好的对象
    model, collection, bm25, all_docs, all_metadatas,
    is_graph_rag: bool = False,
    alpha: float = 0.7,
    kg=None,
) -> tuple[str, str]:
    """单次查询，返回 (answer, sources)。供应给 --query 路径。"""
    if is_graph_rag:
        return _graph_rag_answer(
            query, model, collection, bm25,
            all_docs, all_metadatas, kg=kg, history=[], alpha=alpha,
        )
    else:
        return answer_query(
            query, model, collection, bm25,
            all_docs, all_metadatas, history=[],
        )
```

#### `run_interactive_session` 完整实现

```python
def run_interactive_session(
    file_paths: list[str],
    collection_name: str,
    *,
    force_rebuild: bool = False,
    alpha: float = 0.7,
    is_graph_rag: bool = False,
) -> None:
    t0 = time.time()
    
    if is_graph_rag:
        from graph_rag import prepare_graph_index
        model, collection, bm25, all_docs, all_metadatas, kg = prepare_graph_index(
            file_paths, collection_name, force_rebuild,
        )
        extra_state = kg
    else:
        from rag import prepare_index
        model, collection, bm25, all_docs, all_metadatas = prepare_index(
            file_paths, collection_name, force_rebuild,
        )
        extra_state = None
    
    if not all_docs:
        print("文档库为空")
        exit(1)
    
    t1 = time.time()
    _print_elapsed("文档库就绪", t0, t1)
    print("-" * 100)
    
    history: list[tuple[str, str]] = []
    while True:
        query = input("请输入问题（q以退出，+add以添加文件）：")
        if query.lower() in ("q", "quit"):
            break
        if not query:
            continue
        
        # ── +add 命令 ──
        if query.startswith("+add"):
            paths = _parse_add_paths(query)
            if not paths:
                print("用法: +add <文件路径1>[, <文件路径2>]")
                continue
            bm25, all_docs, all_metadatas = add_files_to_index(paths, model, collection)
            if is_graph_rag:
                # Graph RAG 特有：重建 KG
                from graph_rag import KnowledgeGraph
                kg = KnowledgeGraph()
                kg.build_from_chunks(all_docs, verbose=True)
                extra_state = kg
            print(f"已新增索引，当前共 {len(all_docs)} 个文档块")
            continue
        
        # ── 回答生成 ──
        tq0 = time.time()
        if is_graph_rag:
            answer, sources = _graph_rag_answer(
                query, model, collection, bm25,
                all_docs, all_metadatas, kg=extra_state,
                history=history, alpha=alpha,
            )
        else:
            answer, sources = answer_query(
                query, model, collection, bm25,
                documents=all_docs, metadatas=all_metadatas, history=history,
            )
        tq1 = time.time()
        
        _print_elapsed(f"\n{answer}", tq0, tq1)
        print(f"\n参考来源：\n{sources}\n")
        print("=" * 100)
        history.append((query, answer))
```

#### `--query` 单次查询路径处理

`graph_rag.py` 的 `main()` 有独特的 `--query` 单次查询路径（`499–513` 行），`rag.py` 没有。

**处理方式**：`run_interactive_session` 只负责**交互式循环**。`--query` 单次查询保留在 `graph_rag.py` 的 `main()` 中，使用 `run_single_query()` 辅助函数。`graph_rag.py` 的 `main()` 负责先调用 `prepare_graph_index` 准备索引，再调用 `run_single_query`。

### 2.3 #6b 方案：仅提取轻量 helper

**不提取** `_prepare_index_common`（收益不足）。

**改为提取** `_ensure_client_and_check_rebuild()` — 仅封装 client 创建 + need_build 判断（4-5 行）。

```python
# 存放位置：src/rag.py（与 _collection_exists、CHROMA_DB_PATH 紧耦合）
# graph_rag.py 通过 from rag import _ensure_client_and_check_rebuild 使用

def _ensure_client_and_check_rebuild(
    collection_name: str, 
    force_rebuild: bool
) -> tuple[chromadb.Client, bool]:
    """创建 PersistentClient 并判断是否需要重建索引。"""
    client = chromadb.PersistentClient(path=CHROMA_DB_PATH)
    need_build = force_rebuild or not _collection_exists(client, collection_name)
    return client, need_build
```

**选择放在 `rag.py` 的理由**：
- 与 `_collection_exists`、`CHROMA_DB_PATH`、`chromadb` 紧耦合
- `graph_rag.py` 已经 `from rag import ...`，无需新增导入
- 放在单独文件（如 `src/index_utils.py`）反而增加一个无谓的模块

**效益**：
- 消除 4-5 行重复
- 保持两个 `prepare_*` 函数的主体独立（各自的构建/缓存逻辑不同）
- 避免过度抽象

---

## 3. 导入依赖链分析

### 3.1 当前依赖关系

```
graph_rag.py ──► rag.py (from rag import ...)
tui/service.py ──► src.rag (from src.rag import ...)
                ──► graph_rag (from graph_rag import ...)
```

### 3.2 新增 `cli_loop.py` 后的依赖

```
cli_loop.py ──► rag.py (from rag import answer_query, add_files_to_index, dynamic_top_k,
│                        _build_context, enrich_context, format_sources, answer_with_llm_history)
│              
│              └── graph_rag.py (from graph_rag import prepare_graph_index,
│                                   graph_augmented_retrieve, KnowledgeGraph)
│
graph_rag.py ──► rag.py (from rag import ...)   # 已有，不变
rag.py ──X 不导入 cli_loop.py                    # 无反向依赖
graph_rag.py ──X 不导入 cli_loop.py              # 无反向依赖
```

### 3.3 循环依赖检查

| 导入方向 | 是否形成循环 | 说明 |
|---------|------------|------|
| `cli_loop.py` → `rag.py` | ❌ 无循环 | 单向导入 |
| `cli_loop.py` → `graph_rag.py` | ❌ 无循环 | 单向导入 |
| `graph_rag.py` → `rag.py` | ❌ 无循环 | 已有，单向 |
| `rag.py` → `cli_loop.py` | ❌ 无 | 不导入 |
| `graph_rag.py` → `cli_loop.py` | ❌ 无 | 不导入 |

**结论**：无循环依赖风险。

### 3.4 与 Issue #7（移除 `sys.path` 注入）的兼容性

现有 `graph_rag.py`、`tui/service.py` 都依赖 `sys.path` 注入来支持裸导入。本计划保持同样风格，不引入新的兼容性问题。

| 文件 | 当前导入方式 | Issue #7 后需改为 |
|------|------------|------------------|
| `graph_rag.py` | `from rag import ...` | `from src.rag import ...` |
| `cli_loop.py`（新） | `from rag import ...` / `from graph_rag import ...` | `from src.rag import ...` / `from src.graph_rag import ...` |
| `tui/service.py` | `from src.rag import ...` / `from graph_rag import ...` | 统一为 `from src.graph_rag import ...` |

---

## 4. 实施步骤

### 步骤 1：编写测试（TDD）

#### 测试文件：`tests/test_cli_loop.py`

**mock 策略**：
- `run_interactive_session`：mock `input()` 模拟用户输入序列，mock `print()` 验证输出
- `run_single_query`：mock 索引对象（`MagicMock`），不涉及真实 ChromaDB
- `_parse_add_paths`：纯函数测试，无需 mock
- `_print_elapsed`：mock `time.time()` 固定时间差，mock `print()` 验证格式

示例 mock 模式：
```python
@patch("builtins.input", side_effect=["q"])
@patch("builtins.print")
@patch("cli_loop.prepare_index")
def test_run_interactive_session_quit(mock_prepare, mock_print, mock_input):
    """输入 'q' 正常退出，不报错。"""
    run_interactive_session(["test.md"], "test_coll")
    mock_input.assert_called_once()
    mock_prepare.assert_called_once()
```

**测试用例清单**：
1. `test_run_interactive_session_quit`: 输入 'q' 正常退出
2. `test_run_interactive_session_add_files`: +add 命令正确解析路径
3. `test_run_interactive_session_add_files_with_chinese_comma`: +add 支持全角逗号
4. `test_run_interactive_session_empty_input`: 空输入被忽略
5. `test_run_interactive_session_answer_query`: 正常问答流程（mock `answer_query` 返回值）
6. `test_run_interactive_session_graph_rag_add_rebuilds_kg`: Graph RAG 模式下 +add 后重建 KG
7. `test_run_interactive_session_empty_docs`: 空文档库时 `exit(1)`
8. `test_parse_add_paths`: 路径解析函数边界条件（空格、全角逗号、空字符串）
9. `test_print_elapsed`: 计时打印格式化（0 秒、1 分 30 秒、10 分 0 秒）

#### 测试文件：`tests/test_prepare_index_helper.py`

**mock 策略**：
- mock `chromadb.PersistentClient` 和 `_collection_exists`
- 不涉及真实 ChromaDB

**测试用例清单**：
1. `test_need_build_when_force_rebuild`: `force_rebuild=True` 时返回 `need_build=True`
2. `test_need_build_when_collection_missing`: collection 不存在时返回 `need_build=True`
3. `test_no_need_build_when_collection_exists`: collection 存在且非 force_rebuild

### 步骤 2：提取 `_ensure_client_and_check_rebuild()`

1. 在 `src/rag.py` 中新增 `_ensure_client_and_check_rebuild()`（紧邻 `_collection_exists`）
2. `prepare_index()` 改为调用该 helper
3. `graph_rag.py` 的 `prepare_graph_index()` 改为：`from rag import _ensure_client_and_check_rebuild` + 调用
4. 运行测试，确保行为不变

### 步骤 3：创建 `src/cli_loop.py`

完整创建新文件，包含：
- `_print_elapsed()` — 统一计时格式
- `_parse_add_paths()` — 统一路径解析
- `_graph_rag_answer()` — Graph RAG 回答生成（6 步 pipeline 封装）
- `run_single_query()` — 单次查询
- `run_interactive_session()` — 交互式循环

**注意**：`_graph_rag_answer` 是 `cli_loop.py` 的内部辅助函数，**不**需要导出（import 时通过 `from cli_loop import run_interactive_session, run_single_query` 暴露）。

### 步骤 4：重构 `rag.py` 的 `__main__`

```python
# rag.py
if __name__ == "__main__":
    from cli_loop import run_interactive_session
    
    parser = argparse.ArgumentParser(description="RAG Pipeline")
    parser.add_argument("--files", nargs="+", default=None)
    parser.add_argument("--collection", default=None)
    parser.add_argument("--rebuild", action="store_true")
    # 注意：不再定义 --query，原 --query 是死参数从未被使用
    args = parser.parse_args()
    
    file_paths = args.files or ask_for_files()
    if not file_paths:
        print("没有有效文件")
        exit(1)
    
    collection_name = args.collection or (
        "rag_" + hashlib.md5("|".join(sorted(file_paths)).encode()).hexdigest()[:8]
    )
    
    run_interactive_session(file_paths, collection_name, force_rebuild=args.rebuild)
```

### 步骤 5：重构 `graph_rag.py` 的 `main()`

```python
# graph_rag.py
def main():
    """Graph RAG 命令行入口"""
    from cli_loop import run_interactive_session, run_single_query
    
    parser = argparse.ArgumentParser(description="Graph RAG Pipeline")
    parser.add_argument("--files", nargs="+", default=None)
    parser.add_argument("--collection", default=None)
    parser.add_argument("--rebuild", action="store_true")
    parser.add_argument("--query", default=None)
    parser.add_argument("--alpha", type=float, default=0.7)
    args = parser.parse_args()
    
    file_paths = args.files or ask_for_files()
    if not file_paths:
        print("没有文件")
        exit(1)
    
    collection_name = args.collection or (
        "graph_rag_" + hashlib.md5("|".join(sorted(file_paths)).encode()).hexdigest()[:8]
    )
    
    if args.query:
        # 单次查询路径（graph_rag.py 特有）：先准备索引，再执行单次查询
        model, collection, bm25, all_docs, all_metadatas, kg = prepare_graph_index(
            file_paths, collection_name, args.rebuild,
        )
        answer, sources = run_single_query(
            args.query,
            model=model, collection=collection, bm25=bm25,
            all_docs=all_docs, all_metadatas=all_metadatas,
            is_graph_rag=True, alpha=args.alpha, kg=kg,
        )
        print(f"\n{answer}")
        print(f"\n参考来源：\n{sources}")
        exit(0)
    
    # 交互式循环
    run_interactive_session(
        file_paths, collection_name,
        force_rebuild=args.rebuild,
        alpha=args.alpha,
        is_graph_rag=True,
    )


if __name__ == "__main__":
    main()
```

**关于 `main()` 的保留**：`graph_rag.py` 的 `main()` 被 `__main__` 块调用，且作为一个公开的 CLI 入口点（没有其他模块导入它），因此保留 `main()` 作为封装是有价值的——它允许 `graph_rag.main()` 将来被其它脚本 import 后编程式调用 CLI 流程。重构后 `main()` 体量缩小为仅做参数解析和分发。

### 步骤 6：验证与清理

1. 运行完整测试套件：`pytest tests/ -x`
2. 手动验证 CLI 交互（标准 RAG：`python src/rag.py --files ...`；Graph RAG：`python src/graph_rag.py --files ... --query ...`）
3. 手动验证 `--query` 单次查询路径（仅 Graph RAG）
4. 手动验证 `+add` 命令（两种模式）
5. 手动验证 `tui/service.py` 的 `LocalRagService` 不受影响（它直接调用 `prepare_index` / `prepare_graph_index`，不走 CLI 循环）
6. 更新 `CHANGELOG.md`

---

## 5. 风险与注意事项

| 风险 | 缓解措施 |
|-----|---------|
| CLI 循环逻辑在提取过程中遗漏分支 | 逐行对比原代码，确保 +add、空输入、q/quit 行为一致 |
| `graph_rag.py` 的 `--query` 单次查询路径被误删 | 保留在 `main()` 中，先 `prepare_graph_index` 再 `run_single_query` |
| `graph_rag.py` 的 `+add` 后 KG 重建逻辑被遗漏 | 在 `cli_loop.py` 中通过 `is_graph_rag` 条件分支内联处理 |
| 导入循环依赖 | 已分析确认无循环（见 §3） |
| 测试覆盖不足 | 新增 mock 测试，覆盖 CLI 输入分支和索引准备边界条件 |
| 过度抽象 #6b | 仅提取 4-5 行 helper，不强行提取 `_prepare_index_common` |
| `rag.py` 原有 `--query` 参数被移除 | 确认该参数是死代码（从未被检查），移除无影响 |

---

## 6. 验收标准

- [ ] `src/rag.py` 和 `src/graph_rag.py` 中不再有重复的 CLI 循环代码
- [ ] 新增 `src/cli_loop.py`，包含 `run_interactive_session()` 和 `run_single_query()`
- [ ] `cli_loop.py` 中定义 `_graph_rag_answer()` 辅助函数，被 `run_interactive_session` 和 `run_single_query` 共用，**不引用未定义的函数**
- [ ] `cli_loop.py` 中**不存在** `AnswerStrategy` / `AddFilesPostHook` 等死代码类型别名
- [ ] `src/rag.py` 包含 `_ensure_client_and_check_rebuild()`，`prepare_index()` 和 `prepare_graph_index()` 均使用它
- [ ] `graph_rag.py` 的 `--query` 单次查询路径保留且正常工作（`main()` 中先 `prepare_graph_index` 再 `run_single_query`）
- [ ] `graph_rag.py` 的 `+add` 后 KG 重建逻辑保留且正常工作
- [ ] `rag.py` 的 `--query` 死参数已被移除
- [ ] 所有现有测试通过（`pytest tests/ -x`）
- [ ] 新增测试覆盖 CLI 循环和索引准备的边界条件
- [ ] 手动验证：标准 RAG 和 Graph RAG 的 CLI 交互正常
- [ ] 手动验证：`tui/service.py` 的 `LocalRagService` 不受影响
- [ ] `CHANGELOG.md` 已更新

---

## 7. 附录：代码行号映射

| 逻辑块 | `rag.py` 行号 | `graph_rag.py` 行号 | 提取目标 | 备注 |
|--------|-------------|-------------------|---------|------|
| argparse 定义 | `771–776` | `468–474` | **不提取**，保留在各自 `__main__` | `rag.py` 移除 `--query` 死参数 |
| 文件路径获取 | `778–786` | `476–482` | **不提取**，保留在各自 `__main__` | 完全相同但仅 ~3 行，不值得提取 |
| collection_name 生成 | `788–790` | `484–486` | **不提取**，保留在各自 `__main__` | 前缀不同（`"rag_"` vs `"graph_rag_"`） |
| 索引准备 + 计时 | `791–804` | `488–497` | `cli_loop.run_interactive_session()` | 完全相同（~10 行） |
| `--query` 单次查询 | ❌ 无 | `499–513` | **不提取**，保留在 `graph_rag.py` 的 `main()` 中 | graph_rag.py 特有 |
| 问答循环（含 `+add`） | `808–847` | `515–560` | `cli_loop.run_interactive_session()` | 完全相同（~35 行），+add 后 KG 重建为差异点 |
| `prepare_index` 主体 | `223–248` | — | `_ensure_client_and_check_rebuild()` | 仅提取 client + need_build 判断（4-5 行） |
| `prepare_graph_index` 主体 | — | `361–400` | 同上 | 同上 |

---

## 8. 修订记录

| 日期 | 修订内容 |
|-----|---------|
| 2026-07-06 | 初版 |
| 2026-07-06 | **修订版**：修正 #6b 提取范围（90%→30%），改为仅提取轻量 helper；补充策略回调签名设计；补完导入依赖链分析 |
| 2026-07-06 | **第三版**：定义 `_graph_rag_answer()` 辅助函数（解决 B1'）；统一两处 Graph RAG 逻辑（解决 B2'）；删除死代码类型别名（解决 B3'）；更新 §1.1 重复行数（75→45）；修复 `--query` 路径缺少索引准备（M2'）；移除 `rag.py` 的 `--query` 死参数（M3'）；补充 mock 策略示例（M4'）；讨论 `main()` 保留和 helper 放置位置（S1'/S2'） |
