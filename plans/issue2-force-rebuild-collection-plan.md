# Issue #2 — `force_rebuild` 删除整个 ChromaDB 目录 → 改为仅删除目标 collection

## 背景

`src/rag.py` 中 `build_index()` 的 `force_rebuild=True` 路径在过去使用
`shutil.rmtree(CHROMA_DB_PATH)` 清空全部数据，导致同路径下的其他 collection 被连带删除。
该行代码目前已不在源码中，但当前的替代方案（逐条 `collection.get()` + `collection.delete(ids=...)`）
仍有以下问题：

- 必须将所有 ID 加载到内存再逐个删除，大 collection 下效率低
- 仅删除文档而非整个 collection 结构，留下空的 collection metadata
- 意义不清晰——调用者预期的是"重建索引"，而非"清空文档再追加"

## 影响范围

**仅修改 `src/rag.py:build_index()` 内部**（lines 262-274）。
调用方无需任何改动：

| 调用方 | 关系 |
|--------|------|
| `prepare_index()` (rag.py:223) | 将 `client` + `force_rebuild` 传入 `build_index` |
| `build_graph_index()` (graph_rag.py:300) | 直接调用 `build_index()`，不涉及 client 管理 |
| `prepare_graph_index()` (graph_rag.py:328) | 将 `client` + `force_rebuild` 传入 `build_graph_index` |
| `tui/service.py` IndexService | 调用 `prepare_index` / `prepare_graph_index`，调用链不变 |

## 方案

### 替换目标

**当前代码**（`src/rag.py:262-274`）：

```python
collection = client.get_or_create_collection(
    name=collection_name,
    metadata={"hnsw:space": "cosine"},
)

if force_rebuild:
    existing_count = collection.count()
    if existing_count > 0:
        print(f"检测到已有 {existing_count} 条索引，清除后重建")
        existing_ids = collection.get()["ids"]
        if existing_ids:
            collection.delete(ids=existing_ids)
```

**修改为**：

```python
if force_rebuild:
    try:
        client.delete_collection(collection_name)
    except Exception:
        pass
    collection = client.create_collection(
        name=collection_name,
        metadata={"hnsw:space": "cosine"},
    )
else:
    collection = client.get_or_create_collection(
        name=collection_name,
        metadata={"hnsw:space": "cosine"},
    )
```

### 变更说明

- `client.delete_collection(name)` 原子性地从 ChromaDB 持久化存储中移除该 collection
- `client.create_collection(name, metadata)` 创建一个全新的空 collection
- 裸 `except Exception: pass` 用于 handle collection 不存在的情况（`delete_collection` 在不存在的 collection 上会抛异常）
- `force_rebuild=False` 时行为完全不变，走 `get_or_create_collection`

### 异常处理说明

当前代码风格中已有类似宽捕获模式（如 `_collection_exists` 的 `try/except Exception`），
因此本计划也使用 `except Exception` 以保持一致。

严格来说在此处加一条日志会更利于排查（如 `print("旧 collection 不存在，直接创建新 collection")`），
但这不是必须的，可在实现时作为可选项。

## 边界情况

| 场景 | 预期行为 |
|------|----------|
| Collection 不存在 | `delete_collection` 抛异常 → 被捕获 → 直接 `create_collection` |
| Collection 存在但空 | 被删除 → 重新创建 → 后续 upsert 正常写入 |
| 多个 collection 同路径 | 仅目标 collection 被删除，其他完全不受影响 |
| `force_rebuild=False` | 行为不变，走 `get_or_create_collection` |

## 验证

1. 确认无未使用的 import（`shutil` 应已不在此文件的 import 中）
2. 运行含 `force_rebuild=True` 的测试：
   - `tests/test_llm_meta_answer.py` — `setup_class` 中调用 `prepare_index(force_rebuild=True)`，
     `teardown_class` 中手动 `client.delete_collection()`，与修改后的 API 一致
3. 手动测试：用不同 collection_name 调用两次 `rag_pipeline(force_rebuild=True)`，
   验证第一次的 collection 在第二次重建后仍可正常查询
