# Graph RAG 全连接子图噪音分析与修复方案

> **日期**: 2026-07-07
> **提交人**: ZCode
> **审阅人**: Henry Lan
> **类型**: 性能/正确性分析报告 + 修复计划
> **涉及文件**: `src/graph_rag.py`
> **审阅状态**: ✅ v2（B1/B2/M1/M2/M3 已修复）

---

## 1. Issue 真实性判定

### 1.1 判定结论

**真实（Valid Issue）**。当前 `KnowledgeGraph.build_from_chunks()` 对每个 chunk 的实体集合建立**完全子图**（complete subgraph），所有实体两两之间都创建边，无论它们是否真的语义相关。这带来三个核心问题：

| # | 问题 | 严重程度 |
|---|------|----------|
| 1 | **弱共现噪音** — 偶然同在一个 chunk 的两个无关实体被赋予 weight=1 的边 | **高** |
| 2 | **图密度膨胀** — 4046 实体产生 38755 条边（详见 §1.2），检索区分度下降 | **高** |
| 3 | **无法体现共现强度** — 共现 1 次与共现 10 次在 edge weight 上的差异不足以抵消大量噪音 | **中** |

### 1.2 数学验证

```
20 个实体/chunk → C(20,2) = 190 条边
4046 节点, 38755 条边
最大可能边数: 8,183,035
实际图密度: 0.47%
平均度: 19.2 (每个实体平均连接 19 个其他实体)
```

- 一个实体与 19 个其他实体有边，`get_related_entities()` 在 max_hops=1 时几乎把所有邻居都筛出来，top_k 选择失去意义
- 纯语义检索的 top-20 结果通常只覆盖少量高频实体，但 graph 扩散后引入大量弱相关实体，污染融合排序（`graph_augmented_retrieve()` 的 `merged` dict）

---

## 2. 问题定位

### 2.1 有问题的代码

`src/graph_rag.py:188-194`：

```python
for u in unique_entities:
    for v in unique_entities:
        if u < v:
            if self.entity_graph.has_edge(u, v):
                self.entity_graph[u][v]["weight"] += 1
            else:
                self.entity_graph.add_edge(u, v, weight=1)
```

### 2.2 数据流分析

```
LLM 提取 entities → unique_entities = list(set(entities))
                       ↓
              对集合求完全子图
               O(n²) 条边/每 chunk
                       ↓
              entity_graph.add_edge(u, v, weight=1)
              (或 weight += 1 如果已存在)
```

**关键观察**：edge weight 的递增（`weight += 1`）是**唯一能区分强弱关系的机制**。但问题在于：
1. 即使只共现一次，边也会被创建
2. 完全子图保证大多数实体间都有一条 weight≥1 的边
3. 弱共现边（weight=1）的累积效应远强于真实强共现边（weight=N, N≫1）的区分度

### 2.3 对下游的影响

```python
def get_related_entities(self, seed_entities, max_hops=1, top_k=10):
    # ...
    for neighbor in self.entity_graph.neighbors(node):
        weight = self.entity_graph[node][neighbor].get("weight", 1)
        related[neighbor] = related.get(neighbor, 0) + weight / (hop + 2)
```

在图密集的情况下：
- `neighbors(node)` 返回大量弱关联实体
- `weight / (hop + 2)` 的分数差距很小
- `sorted(related, reverse=True)[:top_k]` 的 top-k 几乎随机

---

## 3. 修复方案对比

### 方案 A：最小共现阈值

**思路**：边只在两个实体在**至少 N 个 chunk 中共同出现**时才创建。这要求两趟处理。

**代码变更**（仅展示建边部分的更改，实体的 entity_to_chunks 映射逻辑不变）：

```python
# 第一趟：统计所有实体对的跨 chunk 共现次数
cooccur_counts: dict[tuple[str, str], int] = {}
for chunk_entities in chunk_entity_lists:  # 已去重
    unique = chunk_entities
    for i in range(len(unique)):
        for j in range(i + 1, len(unique)):
            pair = (unique[i], unique[j]) if unique[i] < unique[j] else (unique[j], unique[i])
            cooccur_counts[pair] = cooccur_counts.get(pair, 0) + 1

# 第二趟：按阈值建边
for (u, v), count in cooccur_counts.items():
    if count >= min_cooccur:
        self.entity_graph.add_edge(u, v, weight=count)
```

**优点**：直击本质 — 滤除偶然共现噪音。
**缺点**：多一趟遍历；大 chunk 数时内存占用增加（需存 cooccur_counts dict）。

### 方案 B：限制实体数/chunk

**思路**：从每个 chunk 的实体列表中取**前 N 个**用于建边，多出的不参与建边。

```python
MAX_ENTITIES_PER_CHUNK = 20

for chunk, entities in zip(chunks, results):
    unique = list(set(entities))
    unique_for_edges = unique[:MAX_ENTITIES_PER_CHUNK]  # 仅建边使用截断
    # entity_to_chunks 仍用完整 unique
    # 建边只用 unique_for_edges
```

**优点**：修改极小，直接限制完全子图大小。
**缺点**：暴力截断可能丢弃重要实体；不解决低频共现噪音。

### 方案 C：组合方案（推荐 ✅✅）

**思路**：先限制每 chunk 建边实体数防止指数爆炸，再加最小共现阈值过滤噪音。两条路径**并行**，互不依赖。

```python
# 对每个 chunk:
unique = list(set(entities))          # 完整列表 → 用于 entity_to_chunks
capped = unique[:max_entities_per_chunk]  # 截断列表 → 仅用于建边

# 第一趟：用 capped 统计共现
for each chunk:
    for i in range(len(capped)):
        for j in range(i + 1, len(capped)):
            cooccur_counts[(capped[i], capped[j])] += 1

# 第二趟：用 cooccur_counts 和 min_cooccur 建边
for (u, v), count in cooccur_counts.items():
    if count >= min_cooccur:
        entity_graph.add_edge(u, v, weight=count)
```

**优点**：双层防护；两者互补不冲突。
**缺点**：改动稍多。

### 方案对比

| 维度 | 方案 A（阈值） | 方案 B（截断） | 方案 C（组合） |
|------|:---:|:---:|:---:|
| 噪音过滤效果 | ⭐⭐⭐ | ⭐⭐ | ⭐⭐⭐⭐⭐ |
| 实现复杂度 | 中 | 低 | 中 |
| 信息损失风险 | 低 | 中 | 中（截断建边，完整记录） |
| 向后兼容 | 是（默认值=1） | 是（大截断值） | 是（默认值兼容） |
| 图密度降低 | 显著 | 中等 | 显著 |

---

## 4. 推荐方案与实施步骤

### 4.1 推荐方案

**选方案 C（组合方案）**，参数设计如下：

| 参数名 | 类型 | 默认值 | 说明 |
|--------|------|--------|------|
| `min_cooccur` | `int` | `2` | 最小共现次数阈值。两个实体至少在 N 个 chunk 中共同出现才建边 |
| `max_entities_per_chunk` | `int` | `20` | 每 chunk 参与建边的最大实体数。超出的不参与建边（但仍记录在 entity_to_chunks 中） |

**两个参数的命名统一为 snake_case 的函数参数风格**。

> 注意：`max_entities_per_chunk` 仅影响**建边**过程。实体与 chunk 的映射（`entity_to_chunks` / `chunk_to_entities`）始终记录所有实体，不会因截断而丢失。

### 4.2 完整伪代码（组合方案）

```
def build_from_chunks(self, chunks, ..., min_cooccur=2, max_entities_per_chunk=20):
    results = extract_entities_llm_batch(chunks, ...)

    cooccur_counts: dict[tuple[str, str], int] = {}

    for chunk, entities in zip(chunks, results):
        if not entities:
            continue

        unique_all = list(set(entities))                    # 完整列表
        unique_for_edges = unique_all[:max_entities_per_chunk]  # 截断列表（仅建边用）

        # entity_to_chunks: 用完整列表 unique_all
        self.chunk_to_entities[chunk] = unique_all
        for ent in unique_all:
            self.entity_to_chunks.setdefault(ent, []).append(chunk)

        # 共现统计: 用截断列表 unique_for_edges
        for i in range(len(unique_for_edges)):
            for j in range(i + 1, len(unique_for_edges)):
                u, v = unique_for_edges[i], unique_for_edges[j]
                pair = (u, v) if u < v else (v, u)
                cooccur_counts[pair] = cooccur_counts.get(pair, 0) + 1

    # 按阈值建边
    for (u, v), count in cooccur_counts.items():
        if count >= min_cooccur:
            if self.entity_graph.has_edge(u, v):
                self.entity_graph[u][v]["weight"] += count
            else:
                self.entity_graph.add_edge(u, v, weight=count)

    # 打印统计...
```

### 4.3 流程图（修正版）

```mermaid
flowchart TD
    A[extract_entities_llm_batch] --> B[unique_all = list(set(entities))]
    B --> C_[unique_for_edges = unique_all[:max_entities_per_chunk]]
    B --> D[记录 entity_to_chunks / chunk_to_entities<br>【使用完整 unique_all】]
    C_ --> E[统计 cooccur_counts<br>【使用 unique_for_edges】]
    E --> F[建边: count >= min_cooccur]
    F --> G[打印 Graph Stats]
```

**关键修正说明**（对比 v1 审阅中的 B1）：
- 步骤 B 生成 `unique_all`（完整列表）
- 步骤 C 生成 `unique_for_edges`（截断列表，用于建边）
- 步骤 D 使用 `unique_all`，不受截断影响
- 两条分支不冲突

### 4.4 代码修改清单

**文件**: `src/graph_rag.py`

| 位置 | 变更 | 说明 |
|------|------|------|
| `KnowledgeGraph.__init__` (L125-128) | 无变化 | 无需修改 |
| `KnowledgeGraph.build_from_chunks` 签名 (L130-137) | 新增 `min_cooccur: int = 2`, `max_entities_per_chunk: int = 20` | 参数追加到签名末尾 |
| `KnowledgeGraph.build_from_chunks` 建边块 (L175-194) | 从单趟完全子图改为两趟法 | 核心变更，见 §4.2 伪代码 |
| `build_graph_index` (L354) | 无变化 | 使用默认值 `min_cooccur=2` |
| `prepare_graph_index` (L394) | 无变化 | 使用默认值 `min_cooccur=2` |
| 所有其他调用方 | 无变化 | 默认值向后兼容 |

### 4.5 调用方兼容性分析

| 调用方 | 位置 | 当前传参 | 默认值影响 | 需要修改？ |
|--------|------|----------|------------|:----------:|
| `build_graph_index()` | L354 | `kg.build_from_chunks(all_docs, verbose=True, progress_callback=...)` | 自动使用 `min_cooccur=2`, `max_entities_per_chunk=20` | 否 |
| `prepare_graph_index()` | L394 | 同上 | 同上 | 否 |
| 测试中的 `kg.build_from_chunks()` | test file | 因 mock 不存在真正建边 | 无影响 | 否（见 §7） |

**默认值 `min_cooccur=2` 的安全性**：
- 如果数据集中实体分散、很少跨 chunk 重复出现，图可能比预期稀疏。此时：
  - `get_related_entities()` 在无邻居时返回空列表，`graph_augmented_retrieve()` 退化为纯语义检索（已有空图保护逻辑 L289-290）
  - 降级路径：用户可显式传 `min_cooccur=1` 恢复原行为，或在 `.env` 中暴露（可选扩展，不在本次实施范围内）
- 在大多数文档场景中，重要实体（如论文主题、方法名、数据集）会跨多个 chunk 出现，`min_cooccur=2` 不会导致过度稀疏

### 4.6 `cooccur_counts` 内存占用估算

```
上限分析：
  假设实体总数 4046，平均每 chunk 实体数 20
  每 chunk 产生的实体对: C(20, 2) = 190
  总 chunk 数 ≈ 4046 × 平均出现次数 / 20
  平均出现次数（典型值）≈ 5
  总 chunk 数 ≈ 1011
  去重前 dict 条目上限 ≈ 190 × 1011 = 192,090
  去重后 ≈ 与原始边数同量级（~38755）

内存计算：
  key = (str, str) tuple，平均 8 字节字符串 → ~50 bytes each
  value = int → 28 bytes
  每条目 ≈ 80-100 bytes
  总内存 ≈ 38,755 × 100 ≈ 3.9 MB

结论：可安全容纳。对于 100 万条目级别的极端情况，约 100 MB，仍在合理范围内。
```

---

## 5. TDD 测试规格（修正版）

遵循 **Red → Green → Refactor** 流程。所有测试在 `tests/test_graph_rag_batch.py` 中新增一个测试类。

### 5.1 Mock 策略

- 不 mock `_get_llm_client()`，而是**绕过 LLM 直接构造 `KnowledgeGraph` 对象**
- 具体做法：先 mock `extract_entities_llm_batch` 返回预定义的实体列表，再调用 `build_from_chunks`
- 或者更简单：在 `build_from_chunks` 中，`results` 来自 mock，LLM 调用根本不会触发

实现方式：

```python
@patch("src.graph_rag.extract_entities_llm_batch")
def test_threshold_filtering(mock_extract):
    mock_extract.return_value = [
        ["实体A", "实体B", "实体C"],   # chunk 1
        ["实体A", "实体B"],            # chunk 2  — A,B 共现 2 次
        ["实体A", "实体D"],            # chunk 3  — A,D 共现 1 次
    ]
    kg = KnowledgeGraph()
    kg.build_from_chunks(["c1", "c2", "c3"], min_cooccur=2, verbose=False)
    # A-B 出现在 2 个 chunk → 应有边
    assert kg.entity_graph.has_edge("实体A", "实体B")
    # A-C 只出现在 1 个 chunk → 无
    assert not kg.entity_graph.has_edge("实体A", "实体C")
    # A-D 只出现在 1 个 chunk → 无
    assert not kg.entity_graph.has_edge("实体A", "实体D")
    assert kg.entity_graph.number_of_edges() == 1
```

### 5.2 测试清单

#### Test 1: 阈值过滤（Red → Green）

```python
def test_min_cooccur_threshold(self):
    """
    Red: 三个 chunk，A-B 共现 2 次，A-C/A-D 各 1 次
          断言: min_cooccur=2 时只有 A-B 有边
    Green: 实现两趟法 + min_cooccur 参数
    """
```

- **Red 阶段**: 先写断言，确保新测失败（原逻辑会给 A-C、A-D 也建边）
- **Green 阶段**: 实现两趟法
- **Mock**: `@patch("src.graph_rag.extract_entities_llm_batch")` 返回固定实体列表

#### Test 2: 截断边界（Red → Green）

```python
def test_max_entities_capping(self):
    """
    Red: 单 chunk 返回 25 个实体，max_entities_per_chunk=10
         断言: 建边使用 max_entities_per_chunk=10 → C(10,2)=45 条边
    Green: 实现截断
    """
```

#### Test 3: 向后兼容（Red → Green）

```python
def test_backward_compatible_defaults(self):
    """
    Red: min_cooccur=1, max_entities_per_chunk=20
         与修改前行为一致（所有共现都建边，同 chunk 完全子图）
    Green: 用等价行为验证
    """
```

- 注意：原逻辑是"每 chunk 完全子图 + weight 累加"，新逻辑是"两趟统计 + 按 count 权重"。当 `min_cooccur=1` 时边集一致，但 weight 值可能有差异：
  - 原逻辑: weight = 共现 chunk 数
  - 新逻辑: weight = count（同 chunk 共现计数，等价于共现 chunk 数）
  - 当 `min_cooccur=1` 时，两者结果一致

#### Test 4: 空 chunks 不崩溃（回归）

```python
def test_empty_chunks_no_crash(self):
    """空 chunks 不引发异常"""
```

- 现有测试可沿用，确认两趟法在空输入下不报错

#### Test 5: 单实体无完全子图（回归）

```python
def test_single_entity_no_edges(self):
    """每 chunk 只有 1 个实体 → 无完全子图 → 0 条边"""
```

#### Test 6: entity_to_chunks 完整性（集成）

```python
def test_entity_to_chunks_completeness(self):
    """
    即使实体被 max_entities_per_chunk 截断排除建边，
    仍应在 entity_to_chunks 中可查到
    """
```

### 5.3 Red/Green 阶段执行顺序

```
Step 1: 新增 TestDenseGraphFix 测试类（6 个测试）
        → 全部失败（Red ✓）
Step 2: 修改 build_from_chunks 实现两趟法 + 参数
        → 全部通过（Green ✓）
Step 3: 重构（提取辅助方法，优化注释）
        → 全部通过（Refactor ✓）
```

---

## 6. 预期效果

| 指标 | 修复前 | 修复后（估算） | 说明 |
|------|--------|----------------|------|
| 4046 实体的边数 | 38755 | ~3000-8000 | 取决于 min_cooccur=2 的过滤效果 |
| 平均度 | 19.2 | ~2-4 | 真正的强共现对数量有限 |
| 图密度 | 0.47% | ~0.05-0.1% | 稀疏图更有区分度 |
| `get_related_entities` top-10 准确率 | 低（噪音多）| 高（仅强关联）| 预期检索质量提升 |
| alpha=0.7 融合检索效果 | 图部分贡献噪音 | 图部分贡献有用信号 | 预期整体检索质量提升 |

---

## 7. 风险与回退

- **过过滤风险**：`min_cooccur=2` 导致图过于稀疏时，可降回 `min_cooccur=1`（等价于原行为）。降级路径：调用方显式传参
- **截断信息损失**：`max_entities_per_chunk=20` 不影响 entity_to_chunks 映射（始终记录所有实体），仅影响建边
- **回退方案**：`min_cooccur=1, max_entities_per_chunk=sys.maxsize` 完全恢复原行为

---

## 8. 现有测试兼容性分析

`tests/test_graph_rag_batch.py` 中现有测试的兼容性验证：

| 测试类 | 核心断言 | 兼容性 | 说明 |
|--------|----------|:------:|------|
| `TestBatchProcessing` | API 调用次数 = ceil(N/batch_size) | ✅ | mock 返回固定实体，建边逻辑变化不影响断言 |
| `TestResultOrder` | 返回实体列表顺序正确 | ✅ | 不涉及建边 |
| `TestBackwardCompatibility` | DeprecationWarning 检查 | ✅ | 不涉及建边 |
| `TestErrorHandling` | API 异常降级 | ✅ | 不涉及建边 |
| `TestProgressCallback` | 回调被调用 | ✅ | mock 返回固定实体，不影响回调 |
| `TestEntityParseWithListPrefix` | 列表前缀解析 | ✅ | extract_entities_llm_batch 层测试，不涉及建边 |

**验证步骤**（确保回归安全）：
1. 在修改代码前运行 `pytest tests/test_graph_rag_batch.py -v`，记录基线通过数
2. 实施修改后再次运行，确认基线不变
3. 新增测试在前两步通过后编写

---

## 9. 实施顺序

```
1. 运行现有测试，确认基线 (baseline)         → baseline=6 passed
2. 新增 TestDenseGraphFix（6 个 Red 测试）    → 6 failed, baseline unchanged
3. 实现 build_from_chunks 两趟法 + 参数      → 6 + 6 = 12 passed
4. 重构（清理注释、变量命名）                 → 12 passed
5. 更新 CHANGELOG                            → 文档完成
6. 最终验证：pytest tests/ -v                → 0 failures
```
