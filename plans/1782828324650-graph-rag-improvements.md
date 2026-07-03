# Graph RAG 改进计划

## 背景

`graph_rag.py` 存在两类问题：
1. 与 `rag.py` 功能未对齐（缺少 CLI 参数、索引复用、`+add`、参考来源显示）
2. 自身逻辑 Bug、性能瓶颈、设计缺陷

---

## P0 — 必须修复

### 任务 1：索引只建一次，循环内复用

**文件：** `graph_rag.py`

**问题：** `graph_rag_pipeline` 默认 `force_rebuild=True`，且对话循环中每次提问都调用 `graph_rag_pipeline`。每问一个问题 → 重新加载文件 → 重新分块 → 重新 embedding → 重新建知识图谱 → 重新提取所有实体。

**方案：**

1. 新增 `prepare_graph_index` 函数（对标 `rag.py` 的 `prepare_index`）：
   - 检查 collection 是否已存在（`_collection_exists`）
   - 存在 → 加载已有 collection + 重建 BM25 + 重建知识图谱（KG 无持久化，必须从 collection 的 documents 重建）
   - 不存在 → 调用 `build_graph_index`

2. 修改 `__main__` 对话循环：
   - 循环外调用一次 `prepare_graph_index`，得到 `(model, collection, bm25, all_docs, all_metadatas, kg)`
   - 循环内直接调用检索 + LLM 生成，不再调用 `graph_rag_pipeline`
   - `all_metadatas` 在 `+add` 时由 `add_files_to_index` 返回值同步更新，避免每次显示来源都调 `collection.get()`

3. `graph_rag_pipeline` 中 `force_rebuild` 默认值改为 `False`

**影响：** `build_graph_index` 返回签名不变，`graph_rag_pipeline` 保留但不再在循环中使用。

---

### 任务 2：实现 `+add` 中途添加文件

**文件：** `graph_rag.py`

**问题：** 提示语写了"+add以添加新文件"但无处理逻辑，输入 `+add xxx` 会直接当查询发给 LLM。

**方案：**

1. 从 `rag.py` 导入 `add_files_to_index`
2. 在对话循环中增加 `+add` 分支：
   - 解析路径（同 `rag.py` 的解析逻辑：中文逗号分隔、空路径提示）
   - 调用 `add_files_to_index(paths, model, collection)` 更新 ChromaDB
   - `add_files_to_index` 已返回 `(bm25, all_docs, all_metadatas)`，直接解包使用（无需再手动重建 BM25）
   - 用更新后的 `all_docs` 重建知识图谱（`kg.build_from_chunks`）
   - 打印当前文档块数

**注意：** KG 重建会重新提取所有实体的 LLM 调用。对于增量场景，可以只对新 chunks 提取实体并合并到已有 KG，但为简化实现，先全量重建。

---

### 任务 3：补齐 CLI 参数

**文件：** `graph_rag.py`

**方案：** 对标 `rag.py` 的 `argparse` 配置：

```python
parser = argparse.ArgumentParser(description="Graph RAG Pipeline")
parser.add_argument("--files", nargs="+", default=None)
parser.add_argument("--collection", default=None)
parser.add_argument("--rebuild", action="store_true")
parser.add_argument("--query", default=None)
parser.add_argument("--alpha", type=float, default=0.7, help="语义检索 vs 图谱检索融合权重")
```

- `--files` 存在 → 直接使用；否则调用 `ask_for_files()`
- `--query` 存在 → 单次问答后退出；否则进入交互循环
- `--alpha` 控制融合权重，传递给 `graph_augmented_retrieve`
- `--collection` 传递给 `prepare_graph_index`

---

### 任务 4：显示参考来源

**文件：** `graph_rag.py`

**问题：** `graph_augmented_retrieve` 只返回 `(docs, scores)`，丢失索引信息，无法调用 `format_sources`。

**方案：**

1. 修改 `graph_augmented_retrieve` 返回值：增加 `indices`（原始文档索引列表）
   - 在函数内部维护 `doc → index` 映射（从 `all_docs` 构建 dict）
   - 返回 `(indices, docs, scores)`

2. 从 `rag.py` 导入 `format_sources`

3. 在对话循环中调用 `format_sources(indices, all_docs, all_metadatas)` 并打印（`all_metadatas` 由 `prepare_graph_index` 返回，`+add` 时同步更新）

---

## P1 — 逻辑修复

### 任务 5：修复 Prompt 与解析不一致

**文件：** `graph_rag.py`（`EXTRACT_PROMPT_BATCH`）

**问题：** Prompt 前半段说"用 `[ENTITY]` 标记开头"，但解析器只识别 `---段落N---`。`[ENTITY]` 指令是无效干扰。

**修改：** 删除 Prompt 第 2 行：
```
每个段落的实体用 [ENTITY] 标记开头，每行一个实体。
```

---

### 任务 6：实体提取截断从 500 提升到与 chunk_size 一致

**文件：** `graph_rag.py`（`extract_entities_llm_batch`）

**问题：** `t[:500]` 截断导致实体提取只看前 500 字符，而 `rag.py` 的 text 类型 chunk_size 已改为 2000。

**修改：** 将截断长度改为 1500（折中：覆盖大部分内容，同时控制 API token 消耗）。

```python
f"---段落{k + 1}---\n{t[:1500]}"
```

---

### 任务 7：修复融合重叠计算 O(n×m)

**文件：** `graph_rag.py`（`graph_augmented_retrieve`）

**问题：** 每个语义检索的重叠文档都遍历重建整个 `merged` 列表。

**修改：** 用 dict 替代 list 进行融合：

```python
merged: dict[str, float] = {}

# 图谱结果
for rank, doc in enumerate(graph_chunks):
    if doc not in merged:
        merged[doc] = (1 - alpha) / (rank + 1)

# 语义结果
for doc, score in zip(semantic_docs, semantic_scores):
    if doc in merged:
        merged[doc] += alpha * score
    else:
        merged[doc] = alpha * score

sorted_merged = sorted(merged.items(), key=lambda x: x[1], reverse=True)
top = sorted_merged[:k_vector]
```

---

## P2 — 设计改进

### 任务 8：修复 Collection 名称哈希碰撞

**文件：** `graph_rag.py`（`graph_rag_pipeline`）

**问题：** `"".join(sorted(file_paths))` 无分隔符，不同文件列表可能产生相同哈希。

**修改：** 改为 `"|".join(sorted(file_paths))`，与 `rag.py` 保持一致。

---

### 任务 9：`_entity_cache` 改用文本 hash 作 key

**文件：** `graph_rag.py`

**问题：** 用完整文本字符串作 dict key，内存开销大且哈希计算慢。

**修改：**

```python
import hashlib
_entity_cache: dict[str, list[str]] = {}

# 存储时
key = hashlib.md5(text.encode()).hexdigest()
_entity_cache[key] = entities

# 读取时
key = hashlib.md5(text.encode()).hexdigest()
entities = _entity_cache.get(key, [])
```

---

### 任务 10：修复 `alpha` 融合权重不一致

**文件：** `graph_rag.py`（`graph_augmented_retrieve`）

**问题：** 重叠文档只额外加 `alpha * score * 0.3`，未计入完整图谱分数。

**修改：** 已在任务 7 的 dict 方案中自然修复——重叠文档同时获得图谱分数和语义分数。

---

### 任务 11：清理 unused imports + 类名

**文件：** `graph_rag.py`

**修改：**

1. 删除未使用的 import：`load_document`, `get_splitter`（从 `rag` 的 import 列表中移除）
2. 类名 `knowledgegraph` → `KnowledgeGraph`（PEP8）

---

### 任务 12：图谱为空时给出提示

**文件：** `graph_rag.py`（`graph_augmented_retrieve`）

**问题：** 如果所有 chunk 的实体提取都失败，KG 为空，静默退化为纯语义检索。

**修改：** 在 `graph_augmented_retrieve` 中检查 `kg.entity_graph.number_of_nodes() == 0`，若为空则打印警告：

```python
if kg.entity_graph.number_of_nodes() == 0:
    print("[警告] 知识图谱为空，退化为纯语义检索")
```

---

## 实施顺序

| 步骤 | 任务 | 依赖 |
|------|------|------|
| 1 | 任务 5（Prompt 修复） | 无 |
| 2 | 任务 8（哈希碰撞） | 无 |
| 3 | 任务 9（cache key） | 无 |
| 4 | 任务 11（cleanup） | 无 |
| 5 | 任务 6（截断长度） | 无 |
| 6 | 任务 7 + 10（融合重构） | 无 |
| 7 | 任务 12（空图谱警告） | 无 |
| 8 | 任务 4（参考来源） | 任务 7 |
| 9 | 任务 1（索引复用） | 任务 8 |
| 10 | 任务 2（+add） | 任务 1 |
| 11 | 任务 3（CLI 参数） | 任务 1 |

---

## 验证清单

1. `python3 -c "import py_compile; py_compile.compile('graph_rag.py')"` — 语法检查
2. `python graph_rag.py --files CHANGELOG.md --query "有多少改动阶段"` — CLI 参数 + 单次问答
3. 交互模式：首次提问 → 第二次提问不应重新建索引（观察是否有"索引重构中..."输出）
4. `+add 2405.02357v2.pdf` → 应成功加载并重建 KG，后续查询可检索 PDF 内容
5. 参考来源应显示 `[1] filename (片段N): ...`
6. 实体提取 Prompt 不再包含 `[ENTITY]` 指令
7. 图谱为空时打印警告（可通过 mock 空 KG 测试）
