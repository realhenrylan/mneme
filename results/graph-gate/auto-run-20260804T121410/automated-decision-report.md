# Automated Diagnostic Decision Report — Graph RAG Phase-4 Gating Evaluation

> **⚠️ 本报告为「自动化诊断」结论，非正式 GO/NO-GO 上线批准。**
> 真值由结构化文本匹配规则自动标注（`rule_based_ds_snippet_first`），
> **未经任何人工审核**；不得作为正式上线批准依据。正式结论必须以
> 人工审核后的 ground truth 与人工盲评为准。

- 报告生成时间：2026-08-04（会话内）
- 评测计划：`plans/GRAPH-RAG-EVALUATION-PLAN-2026-08-02.md`
- 自动化运行目录：`results/graph-gate/auto-run-20260804T121410/`
- 评测框架版本：`compare_version=1`（含本会话 4 处缺陷修复，见 §8）

---

## 1. 结论

# **AUTOMATED_DIAGNOSTIC_NO_GO**

在受控对比实验中，**Graph 通道（C 组）未带来可测量的检索或生成增益**；
按计划 §4.4 自动锁定规则选出的最优 alpha 为 **1.0**——即"无 Graph 的同路径
对照"本身胜出。开发集与 holdout 均未发现 Graph 相对 Standard+Reranker 的
统计显著改善，Graph 候选在 alpha<1 时反而**降低** graph_target context recall。

- 该结论基于**自动化标注**（27 overlap confirmed + 12 source-only），
  标注置信度分布见 §6；低置信度条目已标 `auto_provisional`。
- 若人工审核后真值改变，本结论可能改变；正式流程必须重跑。

---

## 2. 实验组与配置

| 组 | 配置 |
|----|------|
| A | Standard（无 reranker） |
| B | Standard + CrossEncoder reranker（`cross-encoder/ms-marco-MiniLM-L-6-v2`） |
| C | Standard + reranker + Graph 通道（`alpha` 扫描后锁定） |

- 锁定 alpha：**1.0**（§4.4 自动选择，开发集，不回调 holdout）
- 锁定依据：graph_target context_recall 最高（0.3898，alpha=1.0/0.9 并列），
  差距 <1pp → 取更高 alpha=1.0；无候选因 context_precision 下降 >2pp 被淘汰。
- embedding：`all-MiniLM-L6-v2`（384 维）；LLM：`deepseek-chat`
- reranker_mode：`cross-encoder`；seed=42；bootstrap=1000 次
- 语料：`test_texts/` 6 文件（2 PDF 论文、2 PDF 产品/安全文档、1 Markdown
  综述、1 DOCX 地理）；索引 736 chunks；KG 1290 entities / 5124 edges
- 自动 overlay：27 条 overlap confirmed + 12 条 relevance_level=source
  （详见 §6）

---

## 3. 核心指标（锁定 alpha=1.0）

### 3.1 开发集（development，95 cases）

**生成层（answer point coverage / citation validity / false refusal / p95）**

| 指标 | A (standard) | B (standard-rerank) | C (graph-rerank) |
|------|-------------|---------------------|------------------|
| answer_point_coverage (overall) | **0.646** | 0.575 | 0.591 |
| answer_point_coverage (graph_target) | 0.500 | **0.611** | 0.508 |
| citation_id_validity (overall) | **0.726** | 0.632 | 0.653 |
| error_rate | 0.000 | 0.0105 | 0.000 |
| false_refusal_rate | **0.137** | 0.219 | 0.233 |
| total_ms_p95 | **3.6s** | 28.3s | 5.2s |

**检索层（overall）**

| 指标 | A | B | C |
|------|---|---|---|
| context_recall | **0.655** | 0.497 | 0.497 |
| context_precision | **0.087** | 0.078 | 0.078 |
| recall@5 | 0.508 | 0.508 | 0.508 |
| source_recall@5 | **0.983** | 0.983 | 0.983 |

> 注：alpha=1.0 时 C 不经过 Graph 通道，故 C 与 B 检索层完全等价（符合
> 计划 §4.4 "1.0 是无 Graph 的同路径控制"）。

### 3.2 Holdout（16 cases）

| 指标 | A | B | C |
|------|---|---|---|
| answer_point_coverage (overall) | **0.474** | 0.372 | 0.372 |
| answer_point_coverage (graph_target) | **0.556** | 0.444 | 0.444 |
| citation_id_validity | **0.688** | 0.500 | 0.625 |
| false_refusal_rate | **0.077** | 0.308 | 0.308 |
| context_recall (retrieval) | **0.841** | 0.614 | 0.614 |
| source_recall@5 | 0.962 | 0.962 | 0.962 |

---

## 4. 统计检验

### 4.1 配对 bootstrap（C−B context_recall delta，95% CI）

| 切片 | dev mean_delta | dev CI95 | n_pairs |
|------|---------------|----------|---------|
| overall | 0.0000 | [0.0000, 0.0000] | 63 |
| graph_target | 0.0000 | [0.0000, 0.0000] | 20 |

> alpha=1.0 时 C=B 检索层 → delta 恒 0。alpha<1 扫描中 C 的 recall
> 更低（见 §5），因此 Graph 通道在任何锁定候选下均未带来 recall 增益。

### 4.2 McNemar exact（生成二元错误，C vs B）

| 集 | p_value | n_discordant | B-only | C-only | n_pairs |
|----|---------|--------------|--------|--------|---------|
| dev | 0.3877 | 12 | 4 | 8 | 94 |
| holdout | 1.0000 | 1 | 0 | 1 | 16 |

无统计显著差异（p>0.05）。

---

## 5. Alpha 敏感性扫描（dev retrieval，graph_target 切片）

| alpha | C context_recall | C context_precision | B context_precision |
|-------|------------------|---------------------|---------------------|
| 0.50 | 0.352 | 0.0706 | 0.0756 |
| 0.60 | 0.340 | 0.0656 | 0.0756 |
| 0.70 | 0.340 | 0.0656 | 0.0756 |
| 0.80 | 0.352 | 0.0656 | 0.0756 |
| 0.90 | 0.390 | 0.0756 | 0.0756 |
| **1.00（选中）** | **0.390** | **0.0756** | 0.0756 |

- Graph 权重越强（alpha 越小），graph_target context_recall **越低**
  （0.340-0.352 vs 0.390 无图路径）。
- 决策证据文件：`alpha-selection.json`；锁定配置：`lock-generation/locked-config.json`。

---

## 6. 自动标注覆盖率与置信度

- **27 条 overlap**：confirmed=27（reject=0）
  - 高置信（substring/强 bigram 精确命中）：5
  - 低置信（`auto_provisional`，弱-中匹配或仅 source 真值）：22
- **12 条缺失 chunk 真值**：relevance_level=source=12（chunk=0）
  - 理由：答案点多为元数据/数量类（页数、文件名、文档数），在内容 chunk
    中无可靠文本证据；保守判 source 避免伪造 chunk 真值。
- 派生数据集（supplemental chunk 标注）：0（无 chunk 判定的 case）
- 证据文件：`auto-annotation-evidence.json`（逐条记录 snippet、匹配 chunk、
  bigram 重叠、判定、置信度、理由）

**⚠️ 关键限制**：22/27 的 confirmed 标注为低置信 `auto_provisional`——
它们基于 dataset 的 `chunk_text_snippet` 在 source 全 chunks 中的匹配
（substring 或 ≥0.15 bigram 重叠），但未经验证 snippets 的语义等价性。
这使 chunk 真值存在噪声风险，chunk 级指标（context recall 等）应视为
**自动化诊断参考值**。

---

## 7. Graph lift / pollution（failures.csv）

| 指标 | dev | holdout |
|------|-----|---------|
| graph_lift cases | 0 | 0 |
| graph_pollution cases | 0 | 0 |
| flip cases | 0 | 0 |
| source_level_only rows | 10 | 3 |
| refusal_case rows | 22 | 0 |

> alpha=1.0 时 C 不经过 Graph 通道，lift/pollution 恒为 False，符合设计。
> alpha<1 扫描的 failures 未单列（检索层指标已覆盖）。

---

## 8. 流程中发现并修复的缺陷（自动化诊断前）

1. **`compute_summary` paired bootstrap 类型缺陷**：对 `GenerationCaseResult`
   调用 `paired_bootstrap_ci_cb`（访问 retrieval-only 字段）→
   `AttributeError`，导致 full 阶段保存生成 summary 前崩溃。已加
   `isinstance` 守卫，生成结果走 McNemar 分支。回归测试 2 个。
2. **source 指标域不一致**：`candidate_source_ids` 取自 chunk metadata 的
   `source_id`（SHA-256 路径哈希），而 `relevant_source_ids` 是文件名 → 
   `source_recall@5` 恒为 0。提取 `_source_label_from_meta` 优先
   `source_name`，修复后 source_recall@5=0.983。回归测试 5 个。
3. **KG 缓存缺失**：评测进程每次独立构建 KG（LLM 非确定抽取）→
   locked-config 的 kg_sha256 后验跨进程恒失败。已加磁盘缓存
   （`{collection}_kg.json`，以 `index_fingerprint` 判据）并复用 collection。
4. **KG 指纹口径不一致**：`_kg_snapshot_sha256` 用 `get_edge_data` 全属性
   （load 后丢失非 weight 属性）且对不可比较的实体名（dict 类型）抛
   TypeError → 指纹不稳/None。已改为与 `KnowledgeGraph.save` payload
   一致的 (source,target,weight) 三元组口径 + 全 str 化排序。

全部修复后：261→266 个单元测试通过；locked-config 后验指纹 MATCH。

---

## 9. 数据缺口与限制

- **自动标注未经人工审核**（最重要限制）：22/27 confirmed 低置信；12 条
  missing-truth 全判 source（可能漏标 chunk 真值）。
- graph_target 切片小（dev 20 chunk_valid / holdout 3），统计功效不足。
- 语料仅 6 个来源，Graph 连接密度/噪音在真实大知识库中未验证。
- `citation_id_validity` 依赖 LLM 引用生成质量，未人工校准。
- holdout 仅 16 cases，p95 延迟受个别长调用影响（B 的 28s p95）。
- LLM judge/答案要点覆盖率由规则匹配计算，未人工盲评。
- reranker 每条调用重新加载权重（日志可见 "Loading weights"），
  拖慢 B/C 生成；这是评测基础设施问题，不影响指标正确性。

---

## 10. 建议

- **正式流程**：人工审核 review pack（27 overlap + 12 missing-truth），
  再重跑 `review_apply` + 本评测流程；本自动化结论不得替代。
- **工程建议**（若正式评测确认）：Graph 通道在 6 文档小语料中未显价值，
  默认关闭或条件路由（仅当 KG 规模/密度达标时启用）更经济。
- 下一个阶段 4 实现项（若入场）：`evaluation/compare.py` 的 alpha
  适配器（§4.4 价值验证轨）已就绪；正式入场需先扩充 graph_target 盲测集。

---

*本报告由自动化诊断流程生成：阶段1 预检 → 阶段2 自动标注 → 阶段3 严格导入
→ 阶段4 smoke → 阶段5 alpha 扫描/锁定 → 阶段6 dev+holdout 全量评测。
所有中间产物位于 `results/graph-gate/auto-run-20260804T121410/`。*
