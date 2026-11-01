# 答案级 citation 指标 chunk 域错位审计

- 日期：2026-11-01
- 状态：**只读审计完成；Phase 1 只读原型完成（2026-11-01）；未改代码、数据、配置；M6a 评测暂停**
- 范围：M2、M4c arm1/arm2、M6a a′ baseline；`evaluation/citation_metrics.py`、`src/chunking.py`、`src/rag.py`、`data/v2-corpus/chunks/`
- 结论一句话：**M4c/M2 的 citation recall/precision 不是有效指标；0.0456 不是 recall，而是 runtime/store 两个 chunk 域的 ID 碰撞与 context 扩容共同产生的伪值。M6a 的 C1/C3 基线、U 例集与上界全部失效，评测必须暂停。Phase 1 证明 C1/C3 在 runtime 域仍有信号，但 0.2510/0.3494 是新口径（按映射后的 runtime truth 计，平均 2.58 个 runtime chunk / store chunk），不能与旧 0.0456 同比；必须先冻结映射、算 oracle 上界，再重签阈值。**

---

## 1. 结论摘要

1. **两个 chunk 域**：评测真值 `relevant_chunk_ids` 来自 `data/v2-corpus/chunks/`（corpus v2.0.0，1,006 chunks，Recursive 2000/200）；运行时 context 来自 `prepare_index` 的 `src.chunking` v3 section/child（2,947 chunks）。两者 ID 都写成 `{source_sha256_prefix12}_chunk_{n}`，但 `_chunk_{n}` 是各自序号空间，**同 ID 不同文**。
2. **指标直接做 ID 交集**：`evaluation/citation_metrics.py:206-218` 的 precision/recall 用 `supported_chunks & relevant_chunk_ids`，没有文本或 span 映射；因此它测到的是“序号碰撞”，不是“引用命中真值”。
3. **M4c arm2 的 0.0456**：3,065 个 context ID 中 1,184 个（38.6%）不在 store；122 个可答例中只有 31 例在 context 里出现至少一个真值 ID；33 个“命中”全部未经文本核验。0.0456 不能作为 C1 基线。
4. **a′ baseline 在 store 域不能配对，但在 runtime 域可重放**：按 store 域解析仅 12/150 例，138 例含 store 中不存在的 `context_chunk_ids_ordered`；同 ID 文本 `snippet ⊆ store` 校验 0/1877 吻合。`full_sources` 只保存 `record.snippet`（首例 25 chunk 共 6,066 字符），记录本身不能恢复全文。Phase 1 重建 runtime map 后，a′ 的 3,108/3,108 个 ordered ID **全部可解析**，因此可用 runtime map 的全文做离线精确重放；a′ 的 INVALID 裁决仍正确（其原定 capture 假设不成立）。
5. **影响边界**：M5d 的 G1=0.5575 / G2′=1.0 不依赖 chunk ID，门禁结论不受直接影响；但 M5d 报告中“citation recall 0.0456”一类叙述需要标注失效。M6a 实现本身不被否定，被否定的是评测数据契约与预注册基线。
6. **修复顺序**：先做 Phase 1 只读映射原型（runtime 全文/span + store truth→runtime 桥 + 复算 M2/M4c + 修 capture），再决定是否重签 M6a 预注册。Phase 1 前不跑模型、不改产品代码。

---

## 2. 证据

### 2.1 首例（M4c arm2，`multi-021`）

- `context_chunk_ids_ordered` 有 25 个 ID，其中 9 个在 store 中不存在。
- `relevant_chunk_ids` 有 1 个 ID，该 ID 在 store 中存在。
- 两者交集为 0；即按 ID 交集计，该例 recall=0。
- 即使某个 ID 同时在两边，也不能说明文本相同：本次 a′ 的 0/1877 文本吻合率说明“同 ID 异文”是常态，不是边角。

### 2.2 全量 ID 交集复算（只读；未做文本映射）

| 臂 | context IDs | 缺 store | 缺失率 | 有真值 ID 的可答例 | ID 命中数 | manifest recall | manifest precision |
|---|---:|---:|---:|---:|---:|---:|---:|
| M2 | 1,028 | 354 | 34.4% | 23 / 122 | 23 | 0.032222 | 0.030000 |
| M4c arm1 | 1,452 | 561 | 38.6% | 25 / 122 | 25 | 0.032222 | 0.033333 |
| M4c arm2 | 3,065 | 1,184 | 38.6% | 31 / 122 | 33 | 0.045556 | 0.040000 |

读法：

- “有真值 ID 的可答例”只表示 **ID 出现在 context**，不表示该 ID 对应的 runtime 文本与 store 真值文本一致；因此这 23/25/31 例也不能直接当作有效命中。
- “ID 命中数”是 truth ID 在 context 中出现的次数；manifest 的 recall 是逐例 recall 的均值，不是 33/总数。
- 0.0456 恰好在 ID 碰撞与 context 扩到 25 块后变大；把 context 扩得更大，碰撞概率更高，指标会“变好”，这与引用质量无关。

### 2.3 chunk 域对照

| 维度 | store（真值） | runtime（context） |
|---|---|---|
| 构造 | `src.rag.get_splitter` Recursive，size=2000，overlap=200 | `src.chunking` v3 section/child，text 2000，default 500，parent/child |
| 数量 | 1,006 | 2,947 |
| manifest | `data/v2-corpus/chunks/chunk-manifest.json`，corpus v2.0.0 | `prepare_index`（`generation_runner.build_index` 调用，`force_rebuild=True`） |
| ID 形式 | `{source_sha256_prefix12}_chunk_{n}` | 同左 |
| 序号空间 | store 自己的 `n` | runtime 自己的 `n` |

结论：ID 形式相同是**命名巧合**，不是同一实体。任何跨域 ID 集合运算都必须先做 source+span/文本映射。

### 2.4 a′ baseline（`eval/m6a-paired-2026-11-01`，`de8181f`）

- 基线：150/150，cases_failed=0，**1,177,717 token / 150 调用**；预算未超。
- 重放：仅 **12/150** 例可解析；**138 例**含 store 中不存在的 `context_chunk_ids_ordered`；distinct 缺失 420 / 920 ID。
- 文本核验：同 ID 的 `snippet ⊆ store` **0/1877** 吻合。
- `full_sources`：`src/rag.py:2141-2144` 使用 `record.snippet`；首例 25 chunk 只有 6,066 字符。它不是完整 context，无法用于精确重放 `retarget_citations` 的 chunk 文本打分。
- 最终裁决：`INVALID`（一致性前置失败）；C1/C2/C3 未裁决；judge/al3 未运行。
- 产物：`results/answer-level/m6a-paired-2026-11-01/report.md`；decision `INVALID`；预算 1,177,717/150。
- 说明：这 1,177,717 token 已密封，可作为“runtime 基线”留档；但在 truth 桥与完整 context capture 修好前，不能用于 M6a 的 C1/C3 裁决。

---

## 3. 影响

### 3.1 M4c / M2

- `citation_recall` 与 `citation_precision` 的当前数值（M2 0.0322/0.0300；arm1 0.0322/0.0333；arm2 0.0456/0.0400）**不能作为引用质量结论**。
- `citation_id_validity`（0.8733）与 context-supported citation validity 不依赖 truth ID，仍可用；它们回答的是“引用格式/上下文支持”，不是“引用命中真值”。
- M4c 的 token/成本、拒答、修正率等不依赖 chunk ID 的指标不受影响；但任何“citation recall +0.013”的叙述应撤回或标注无效。

### 3.2 M6a

- 预注册的 **0.0456 基线、C1=0.10、C3=0.0400、U=21、0.2067 上界** 全部建立在跨域 ID 交集上，必须重算。
- 不能把 a′ 的 baseline 直接接到 M6a；`full_sources` snippet 也不足以复现 chunk 文本打分。
- M6a 的 **实现分支 `614e260` 不被否定**：47 tests 通过、只改 `[S#]`、不新增/删除槽位；被否定的是评测配对与基线。产品默认未切换。

### 3.3 M5d

- G1=0.5575（修正率，partial=0.5）与 G2′=1.0（al3 语义拒答）不依赖 chunk ID；M5d 的 PASS 结论不受直接影响。
- M5d 报告中引用 0.0456 的段落需标注“chunk 域错位，失效”；不能把该数字继续当作引用质量证据。

---

## 4. 根因

1. **历史构造分叉**：v2 corpus 的 chunk store 用 Recursive splitter（1,006 chunks）；运行时索引后来切到 section/child（2,947 chunks），但没有迁移 truth ID。
2. **指标假设了同域**：`evaluation/citation_metrics.py` 把 `relevant_chunk_ids` 与 `supported_chunks` 都当作同一 ID 空间的实体，直接做集合交集。
3. **capture 只存 snippet**：`format_sources` 为展示而截断（`record.snippet`），评测 runner 又只存 `context=sources[:500]`；即使 ID 域修好，也无法从旧产物恢复完整 chunk 文本。
4. **a′ 的 fallback 假设不成立**：addendum 允许“从完整 sources 解析”，但 `full_sources` 并非完整文本；因此 0/1877 与 138/150 缺失不是脚本 bug，是数据契约不足。

---

## 5. 修复计划

### Phase 1（只读原型；不跑 LLM、不改产品代码）

1. **重建 runtime v3 chunk 全文/span 映射**：用 `src.chunking` 对 v2 源文档确定性重建 2,947 个 chunk，记录 `chunk_id`、`source`、`text`、`span`、`parent_id`、`section_path`；核对数量与现有 runtime `context_chunk_ids` 的可解析率。
2. **建立 store truth → runtime chunk 的桥**：以 source+字符 span 为主、文本归一化为辅；允许一对多；记录覆盖率和歧义；不得再用 ID 直接映射。
3. **复算 M2/M4c 的 C1/C3**：用桥接后的 truth 重算 recall/precision，输出新旧对照；判断是否存在可用的引用质量信号，还是需要重新定义 C1/C3。
4. **修 evaluation capture**：在 `evaluation/generation_runner.py` 保存完整 `enriched_docs`（或 ordered `chunk_texts`）与 `context_chunk_ids_ordered`；这是 eval-only 变更，不改 `src/`。
5. **产出审计原型报告**：`results/answer-level/chunk-domain-audit-2026-11-01/`，含映射覆盖率、歧义样例、复算表、失败关闭条件。

### Phase 2（治理与重签）

- 按 Phase 1 结果重算 M6a 的 baseline、U 集、0.2067 上界、C1/C3。
- 若 C1/C3 仍有意义，另立预注册附录；owner 签批后再跑 M6a。
- 若 C1/C3 无法在 runtime 域稳定定义，M6a 不应继续；需要先决定“引用质量”的产品口径。

---

## 5A. Phase 1 执行结果（2026-11-01，只读）

Phase 1 已完成，5 个停止条件均未触发：重建 runtime chunk 2,947、四臂 context ID 可解析率 1.00、store→runtime 映射覆盖率 1.00、未改 `src/`、全程无 LLM/网络。完整报告见 [`results/answer-level/chunk-domain-audit-2026-11-01/report.md`](../results/answer-level/chunk-domain-audit-2026-11-01/report.md)，指标见同目录 `metrics.json`，manifest 自哈希 `c23c1f3f…e36cfc3`。

### 5A.1 重建与桥

| 项 | 结果 |
|---|---:|
| 重建 runtime chunks | 2,947（与现有索引一致） |
| span 定位 | 2,947/2,947 |
| store chunks | 1,006 |
| 映射覆盖率（至少 1 个 runtime 候选） | 1.00（1,006/1,006） |
| 一对多 | 930 |
| 歧义（≥2 候选各 ≥50%） | 16 |
| 主口径条件覆盖率（t=0.50，ratio_runtime） | 98.5% |
| ratio_store t=0.50 条件覆盖率 | 74.7%（truth 未映射 18.0%，不能作主口径） |

### 5A.2 桥接后指标（t=0.50，ratio_runtime）

| 臂 | 旧 recall | 旧 precision | 新 recall (evi) | 新 precision (evi) | 新 recall (ctx) | 新 precision (ctx) | store-hit recall (evi) |
|---|---:|---:|---:|---:|---:|---:|---:|
| M2 | 0.0322 | 0.0300 | 0.1928 | 0.2940 | 0.2955 | 0.0710 | 0.3033 |
| arm1 | 0.0322 | 0.0333 | 0.2267 | 0.3336 | 0.3489 | 0.0792 | 0.3578 |
| arm2 | 0.0456 | 0.0400 | 0.2510 | 0.3494 | 0.4008 | 0.0521 | 0.3878 |

**读法（关键）**：

- `新 recall (evi)` 的分母是**映射后的 runtime truth 集合**，不是旧口径的 store truth 数。`mean_rel_runtime_size=2.58`，即一个 store chunk 平均映射 2.58 个 runtime chunk；因此 0.2510 与旧 0.0456 **不是同一把尺子**，不能直接说“提升 5.5 倍”。
- 更接近旧分母的是 `store-hit recall (evi)`（arm2 0.3878）：按 store truth 计，任一映射 runtime chunk 被引用即命中；它仍因“任一子 chunk”而偏宽松。
- 三臂 recall 的排序（arm2 > arm1 > M2）部分来自 context 扩容（arm2 25 块 vs arm1/M2 更少）；同表 arm2 的 ctx precision 0.0521 低于 arm1 0.0792，不能把排序当作纯引用质量结论。M6a 的同 context 配对不受此混杂影响。
- 主口径 `ratio_runtime` 是单边宽松映射：短 runtime chunk 完全落在长 store chunk 内即 ratio=1.0，precision 0.3494 是**区域级**精度。`ratio_store` 口径的 precision 更低（arm2 0.2352），但 18% truth 未映射，不能单独作主口径。
- 旧阈值 0.0456/0.10/0.0400/0.2067 全部作废；新阈值必须在冻结映射策略、算出 oracle 上界后重签。

### 5A.3 a′ baseline

- ordered context IDs：**3,108/3,108 可解析**（150/150 例）；说明 runtime map 足以恢复 context 的 **ID 序列与全文**。
- `full_sources`：150/150 例均为 150 字符 snippet；首例 25 chunk 全文 22,267 字符，`full_sources` 仅 6,066 字符（27.2%）。
- 结论：a′ **可以用 runtime map 离线精确重放**；capture 修复不是 C1/C3 重放的前置条件，而是“单凭 outcomes 记录可复现”和 `retrieved_not_in_context` / fabricated 文本裁决的前置条件。后续 capture 修复仍应做，但不应阻塞配对重放。

### 5A.4 仍未解决

1. **映射策略未冻结**：单边 `ratio_runtime`、双边覆盖、`ratio_store` 三者给出的绝对数值不同；Phase 2 必须先由 owner 选定并写入预注册。
2. **缺 oracle 上界**：旧 0.2067 已作废；需要用 a′ baseline 在“只重定向既有槽位”的约束下计算每例最大可达 recall，聚合为 M6a 的天花板；没有上界就无法合理设定 C1。
3. **C3 的 fabricated/retrieved_not_in_context**：旧 capture 只有 snippet，需在 capture 修复后重测；在此之前 C3 只能使用可离线验证的部分。

---

## 6. 决策与边界

- **M6a 评测暂停**：Phase 1 已完成，但 Phase 2A（映射策略 + oracle + 阈值重签）未完成前，不跑 150 例、不跑 judge/al3、不产出 PASS/FAIL。
- **不 push**：本审计、Phase 1 证据与 Phase 2A 草案均本地保留；提交仅本地 commit，除非 owner 明确要求 push。
- **不改产品默认**：`src/`、配置默认、检索/rerank/Graph RAG 均不动。
- **不改数据**：不修 store、不重新切 chunk、不改 dataset；Phase 1 只读/原型。
- **不把 ID 交集当 truth**：任何后续指标必须使用 source+span/文本映射，并在报告中披露覆盖率与歧义。

---

## 7. 未决问题

1. **桥接粒度与方向**：单边 `ratio_runtime`、双边覆盖、`ratio_store` 三种策略的绝对数值不同；Phase 2 必须选定一种并冻结。一对多时是按映射后的 runtime truth 计（`recall_evi`），还是按 store truth “任一子 chunk 命中”计（`store_hit_recall_evi`），也必须二选一，不能混报。
2. **C1/C3 的产品口径**：是“引用指向的 runtime chunk 与 truth span 有重叠”，还是“必须完全覆盖 truth span”？两者对阈值影响很大。
3. **oracle 上界**：旧 0.2067 已作废；需在 a′ baseline 上按“只重定向既有槽位”计算每例最大可达 recall，聚合为 M6a 天花板；C1 必须落在 control 与 oracle 之间，否则无区分力。
4. **历史产物**：M4c/M5d/M6a 报告中引用 0.0456 的段落，是逐条加勘误，还是统一在 STATUS 标注失效？
5. **a′ baseline 的处置**：保留为 runtime 基线证据，还是删除以节省仓库体积？当前建议保留（已密封、可审计）。

---

## 8. 参考

- `evaluation/citation_metrics.py`（precision/recall 的 ID 交集实现）
- `evaluation/generation_runner.py`（`build_index`、capture、`context=sources[:500]`）
- `src/chunking.py`（runtime v3 section/child）
- `src/rag.py:2141-2144`（`format_sources` 使用 `record.snippet`）、`src/rag.py:2202`（`_validate_and_repair_citations`）、`src/rag.py:2898`（`generate_answer`）
- `data/v2-corpus/chunks/chunk-manifest.json`（store v2.0.0，1,006 chunks）
- `results/answer-level/m4c-arm2-2026-09-06/manifest.json`（0.0456/0.04 的原始 manifest）
- `results/answer-level/m6a-paired-2026-11-01/report.md`（a′ INVALID）
- `results/answer-level/chunk-domain-audit-2026-11-01/report.md`（Phase 1 完整结果）
- `results/answer-level/chunk-domain-audit-2026-11-01/metrics.json`（Phase 1 指标与阈值敏感性）
- `plans/ANSWER-LEVEL-M6a-CITATION-QUALITY-PREREGISTRATION-2026-10-31.md`（失效的基线/C1/C3）
- `plans/ANSWER-LEVEL-M6a-PAIRED-REPLAY-ADDENDUM-2026-11-01.md`（a′ 方法与其 capture 假设）
