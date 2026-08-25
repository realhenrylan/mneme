# 生产基线正式候选报告（CANDIDATE）

> 目录：`results/graph-gate/production-baseline-20260804T2220/`
> 性质：**CANDIDATE（候选）** — 自动化流程 + 人工审核真值已闭环，但
> 阈值/guardrail 基线尚需人工签署确认后方可视为正式上线依据。
> 数据时间：2026-08-04；评测运行均以 `PYTHONHASHSEED=0` 固定 split。

---

## 一、评测配置（fail-closed 全链路）

| 维度 | 值 | 验证 |
|---|---|---|
| 生产基线 | `arms=[standard]`、`RAG_RERANKER=none`、`RAG_SELECTOR_MAX_PER_SOURCE=3`（`arm_selector_policy={"standard": 3}`）、Graph 禁用（无 graph-rerank 臂，kg=None）、`alpha=1.0` | `lock-production.json` + precheck PASS |
| 数据集 | `evaluation/datasets/v1.jsonl`（SHA `8ce1b46b…`，已人工补标 8 个 meta-* case chunk 真值 + 2 个 snippet 修正） | precheck / verify_truth_integrity PASS |
| 语料/索引 | `test_texts/` 6 文件（SHA `41fdb853…`）、`eval-autorun-lock` 736 chunks（index SHA `c6b54781…`，fingerprint `fefbc734…`） | 与旧锁一致 |
| 真值 overlay | dev：19/19 confirmed + 4 source-only；holdout：6/6 confirmed + 4 source-only（人工审核，`review_apply` 严格导入） | 27/27 人工决定（25 confirmed / 2 rejected → 补标） |
| split | `group_aware_split(seed=42)`，**固定 PYTHONHASHSEED=0**（dev 94 / holdout 16），rebuild↔评测严格一致 | 运行日志 Active cases 94/16 |
| 运行 | dev-full（94 例）、holdout-full（16 例），`--phase full`、seed 42、bootstrap 1000×42 | 均 exit 0、Truth gate passed |

### 真值人工审核摘要

- 27/27 overlap 条目人工决定：**confirmed 25 / rejected 2**（en-004、mixed-005）。
- **补标披露**：en-004 / mixed-005 的 `relevant_chunks` snippet 原为论文
  定义（Speculative Decoding）的**意译**，GT 匹配到错误候选 chunk_184 被
  reject；已修正为 chunk_27（2.1 节，page 3）的**逐字子串**
  （`The target model verifies all candidates in a single forward pass,
  accepting the longest prefix consistent with its own distribution`），
  语义不变、恢复 exact 可匹配。git diff 可审计。
- 4 条 source-only（cross-008 / en-013 / meta-003 / meta-008）：页面计数类
  元数据问题，无内容 chunk 真值，从 chunk/context/citation 分母排除。
- 8 个 meta-* case 补标 chunk 真值（dataset 更新，SHA 变化属预期）。
- 所有 SHA 链（overlay↔dataset↔ground-truth↔corpus↔index）与标注完整性
  校验 PASS（`verify_truth_integrity.py`、`precheck.py`）。

## 二、dev 结果（94 例，生产基线 + 人工真值）

### 检索层

| 指标 | 值 | 指标 | 值 |
|---|---|---|---|
| recall@5 | 0.5004 | source_recall@5 | 0.9826 |
| recall@10 | 0.6588 | source_recall@10 | 0.9826 |
| recall@20 | 0.7416 | context_source_recall | 0.9282 |
| context_recall | 0.5703 | context_source_coverage | 0.5903 |
| context_precision | 0.0830 | n_chunk_valid / n_source_valid | 68 / 72 |
| mrr | 0.2867 | n_source_only | 4 |
| retrieval p50/p95 | 17.0 / 161.1 ms | excluded_no_chunk_truth | 4 |

### 生成层（含 citation v2 契约）

| 指标 | 值 | 分母 |
|---|---|---|
| answer_point_coverage | 0.6574 | 72 answerable |
| **context_supported_citation_validity_micro** | **1.0000（156/156）** | total_unique_citation_ids |
| **context_supported_answer_rate** | **0.8889（64/72）** | answerable_generation_cases |
| **no_citation_answer_rate** | **0.1111（8/72）** | answerable_generation_cases |
| citation_mention_rate | 0.8889（64/72） | answerable_generation_cases |
| fabricated / retrieved_not_in_context | 0 / 0 | — |
| false_refusal_rate | 0.1389 | answerable 72 |
| error_rate | 0.0 | 94 |
| total p50/p95 | 1.68 / 3.83 s | — |

> legacy 单值（citation_id_validity=0.7340）为旧口径（全体分母均值），
> **仅兼容读取，不用于 guardrail**（契约 v2 以 citation_v2 块为准）。

## 三、holdout 独立验证（16 例）

| 指标 | 值 | 分母 |
|---|---|---|
| recall@10 / context_recall | 0.5833 / 0.5833 | 13 |
| source_recall@5 / context_source_recall | 0.9615 / 0.9231 | 13 |
| answer_point_coverage | 0.4359 | 13 |
| **context_supported_citation_validity_micro** | **1.0000（22/22）** | 22 IDs |
| **context_supported_answer_rate** | **0.8462（11/13）** | 13 |
| **no_citation_answer_rate** | **0.1538（2/13）** | 13 |
| false_refusal_rate | 0.1538 | 13 |
| error_rate | 0.0 | 16 |

> holdout answerable 仅 13 例，点估计置信区间宽（功效不足），仅作方向性验证。

## 四、citation v2 guardrail 基线建议（CANDIDATE）

基于 dev 分布 + holdout 方向性验证，建议正式 guardrail 阈值（需人工签署）：

| 指标 | 建议阈值 | dev | holdout | 依据 |
|---|---|---|---|---|
| context_supported_citation_validity_micro | **≥ 0.95** | 1.0000 | 1.0000 | 零 fabricated/not-in-context；留 5% 容差 |
| context_supported_answer_rate | **≥ 0.80** | 0.8889 | 0.8462 | 两 split 均 > 0.80 |
| no_citation_answer_rate | **≤ 0.20** | 0.1111 | 0.1538 | 两 split 均 < 0.20 |
| false_refusal_rate | **≤ 0.20** | 0.1389 | 0.1538 | 两 split 均 < 0.20 |

**guardrail 消费规则**（与契约 v2 一致）：
- 只消费 `citation_v2.metrics.*`（带显式 numerator/denominator/excluded）；
  legacy 单值键一律不作为 guardrail 输入。
- 分母为 0 → value=null（unavailable），不得伪装为 0，guardrail 应跳过该
  指标（而非判失败/成功）。
- 回归触发条件：任一指标越阈即报警；micro 越阈（出现 fabricated 或
  not-in-context 引用）为**高优先级**信号。

## 五、风险与限制

1. **语料规模**：仅 6 文档 / 736 chunks、单领域（文档问答）。阈值仅对
   当前语料 + 提示词（prompt_id 固定）+ deepseek-chat 有效；语料扩充、
   prompt 或模型变更后必须重新校准。
2. **holdout 功效不足**：answerable 13 例，置信区间宽；正式上线建议扩充
   评测语料后重跑以收紧阈值。
3. **micro=1.0 未受挑战**：当前语料无 fabricated/not-in-context 正例，
   guardrail 对引用真实性退化的**区分能力未经实证**——需要含对抗性
   case 的语料验证后才能依赖该指标拦截劣化。
4. **PYTHONHASHSEED 框架缺陷（已绕行）**：`group_aware_split` 的 chain
   分配依赖 set 迭代顺序，未固定 hash seed 时每次进程 split 可能不同；
   本报告全程 `PYTHONHASHSEED=0` 保证 rebuild↔评测一致。**历史各运行**
   （auto-run / reranker-recheck / selector-ablation）未固定 hash seed，
   其 dev/holdout 集合一致性未验证——本报告指标与历史指标**不可直接
   比较**（且真值已变更：补标 + 人工审核）。
5. **补标影响**：en-004/mixed-005 snippet 修正使这两 case 从「无可靠
   真值」变为 exact 可靠（§一）；meta-* 8 case 补标改变 chunk 分母
   （excluded_no_chunk_truth 4 = 4 条 source-only，无静默缺失）。
6. **未改动项**：未修改任何历史 results 产物与 decision-report.md；
   未 stage/commit；未自动启用 Graph/reranker。

## 六、结论

- **工程就绪**：评测全链路（真值审核 → overlay → 锁校验 → dev + 独立
  holdout）fail-closed 通过，产出 citation v2 guardrail 基线（CANDIDATE）。
- **策略保持**：生产基线维持 `reranker=none`、`cap=3`、Graph 禁用
  （alpha=1.0 仅对照口径）；本次无任何自动切换。
- **上线前置**：阈值表（§四）需人工签署；建议先扩充语料并重跑一轮
  以验证 micro 指标的区分能力与收紧 holdout 阈值。

*本报告由自动化流程生成（`production-baseline-20260804T2220/` 内脚本可复现）；人工审核决定与补标已披露，阈值签署待人工。*
