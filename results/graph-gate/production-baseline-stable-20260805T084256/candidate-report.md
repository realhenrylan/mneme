# 生产基线正式候选报告 v2（CANDIDATE — 稳定 split + LLM 辅助审阅真值）

> 目录：`results/graph-gate/production-baseline-stable-20260805T084256/`
> 性质：**CANDIDATE（候选）** — 稳定 split（split_fingerprint 锁定）+ 
> **LLM 辅助审阅真值**已闭环；**不是人工签署，不代表正式上线批准**。
> 阈值/guardrail 基线仍待人工批准后方可视为正式上线依据。
> 数据时间：2026-08-05；评测运行不依赖 PYTHONHASHSEED
> （`PYTHONHASHSEED=0` 仅作环境记录，稳定 split 结果与其无关）。

---

## 一、评测配置（fail-closed 全链路）

| 维度 | 值 | 验证 |
|---|---|---|
| 生产基线 | `arms=[standard]`、`RAG_RERANKER=none`、`RAG_SELECTOR_MAX_PER_SOURCE=3`（`arm_selector_policy={"standard": 3}`）、Graph 禁用（无 graph-rerank 臂，kg=None）、`alpha=1.0` | `lock-production-stable.json` + precheck PASS |
| 数据集 | `evaluation/datasets/v1.jsonl`（SHA `8ce1b46b…`，含补标与 snippet 修正） | precheck / phase1-verification PASS |
| 语料/索引 | `test_texts/` 6 文件（SHA `41fdb853…`）、`eval-autorun-lock` 736 chunks（index SHA `c6b54781…`） | 与锁一致 |
| **split（稳定）** | `group_aware_split(seed=42)` **修复后**：chain root 稳定排序 + 输出稳定排序，**与 PYTHONHASHSEED 无关**；dev 95 / holdout 15；split_fingerprint `454892e4…3690` 已锁定于锁配置并在评测前 fail-closed 校验 | precheck + 双环境复算（=0/=42 逐字节一致，子代理独立验证） |
| 真值 overlay | dev：21/21 confirmed + 4 source-only；holdout：4/4 confirmed + 4 source-only（按稳定键从 canonical pack 机械迁移，`review_apply` 严格导入） | verify_truth_integrity / precheck PASS |
| 运行 | dev-full（95 例）、holdout-full（15 例），`--phase full`、seed 42、bootstrap 1000×42 | 均 exit 0、Truth gate passed、overlay 全部消费 |

### 真值来源声明（事实修正，见 addendum）

- **27 条 overlap 决定（25 confirmed / 2 rejected）为 LLM 辅助审阅产生，
  不是独立人工签署**；正式 guardrail 阈值仍待人工批准。
- 4 条 source-only（cross-008 / en-013 / meta-003 / meta-008）：页面计数类
  元数据问题，从 chunk/context/citation 分母排除。
- 2 条 reject（en-004、mixed-005）保留于 canonical pack 历史记录；其标注
  已补标为 exact 匹配，不再产生 overlap 行。
- 已知机制观察（无功能影响）：holdout overlay 的 `case_relevance_levels`
  引用 dev 侧 4 个 source-only case（review_pack 对全数据集导出 missing
  行所致）；holdout gate 无 case 被跳过，指标分母不受影响。

## 二、dev 结果（95 例，生产基线 + LLM 辅助审阅真值）

### 检索层（chunk 分母 69 = 73 answerable − 4 source-only）

| 指标 | 值 | 指标 | 值 |
|---|---|---|---|
| recall@5 | 0.5004 | source_recall@5 | 0.9829 |
| recall@10 | 0.6492 | source_recall@10 | 0.9829 |
| recall@20 | 0.7453 | context_source_recall | 0.9292 |
| context_recall | 0.5403 | context_source_coverage | 0.5822 |
| context_precision | 0.0797 | n_chunk_valid / n_source_valid | 69 / 73 |
| ndcg@5 / ndcg@10 | 0.3034 / 0.3567 | n_source_only | 4 |
| mrr | 0.2869 | excluded_no_chunk_truth | 4 |
| retrieval p50/p95 | 8.3 / 96.3 ms | error_rate | 0.0 |

### 生成层（含 citation v2 契约）

| 指标 | 值 | 分母 |
|---|---|---|
| answer_point_coverage | 0.5799 | 73 answerable |
| **context_supported_citation_validity_micro** | **1.0000（153/153）** | total_unique_citation_ids = 153 |
| **context_supported_answer_rate** | **0.9041（66/73）** | answerable_generation_cases = 73 |
| **no_citation_answer_rate** | **0.0959（7/73）** | answerable_generation_cases = 73 |
| citation_mention_rate | 0.9041（66/73） | answerable_generation_cases = 73 |
| fabricated / retrieved_not_in_context / other | 0 / 0 / 0 | 153 IDs |
| n_refused / n_error / n_evidence_missing | 22 / 0 / 0 | n_all = 95 |
| false_refusal_rate | 0.1918（14/73） | answerable 73 |
| false_answer_rate | 0.3636 | 回答 case（legacy 口径） |
| total p50/p95 | 2.21 / 4.24 s | — |

> legacy 单值（citation_id_validity / context_supported_citation_validity
> = 0.7368）为旧口径（答案层均值），**仅兼容读取，不用于 guardrail**
> （契约 v2 以 `citation_v2` 块为准）。

## 三、holdout 独立验证（15 例）

| 指标 | 值 | 分母 |
|---|---|---|
| recall@5 / recall@10 | 0.5486 / 0.6319 | 12 chunk-valid |
| context_recall | 0.7569 | 12 |
| source_recall@5 / context_source_recall | 0.9583 / 0.9167 | 12 |
| answer_point_coverage | 0.6389 | 12 |
| **context_supported_citation_validity_micro** | **1.0000（22/22）** | 22 IDs |
| **context_supported_answer_rate** | **0.8333（10/12）** | 12 |
| **no_citation_answer_rate** | **0.1667（2/12）** | 12 |
| false_refusal_rate | 0.0833 | 12 |
| error_rate | 0.0 | 15 |

> holdout answerable 仅 12 例，点估计置信区间宽（功效不足），仅作方向性验证。

## 四、citation v2 guardrail 基线建议（CANDIDATE，待人工批准）

基于 dev 分布 + holdout 方向性验证，建议正式 guardrail 阈值（**需人工
签署后生效**；本报告不自动批准）：

| 指标 | 建议阈值 | dev | holdout | 依据 |
|---|---|---|---|---|
| context_supported_citation_validity_micro | **≥ 0.95** | 1.0000 | 1.0000 | 零 fabricated/not-in-context；留 5% 容差 |
| context_supported_answer_rate | **≥ 0.80** | 0.9041 | 0.8333 | 两 split 均 > 0.80 |
| no_citation_answer_rate | **≤ 0.20** | 0.0959 | 0.1667 | 两 split 均 < 0.20 |
| false_refusal_rate | **≤ 0.20** | 0.1918 | 0.0833 | 两 split 均 < 0.20（dev 贴近阈值，需关注） |

**guardrail 消费规则**（与契约 v2 一致）：只消费 `citation_v2.metrics.*`
（带显式 numerator/denominator/excluded）；分母为 0 → value=null，不得
伪装为 0；micro 越阈（fabricated 或 not-in-context）为高优先级信号。

## 五、与旧候选结果（20260804T2220）的关系：不可直接比较

| 维度 | 旧候选（已作废为正式基线） | 本报告（稳定 split） |
|---|---|---|
| split | dev 94 / holdout 16，`PYTHONHASHSEED=0` 运行绕行（框架缺陷未修复） | **dev 95 / holdout 15，框架已修复、指纹锁定** |
| holdout 链成员 | multi-007/008/009/010 | **multi-004/005/006** |
| 决定来源 | 同批 27 条（25 confirmed / 2 rejected） | 同批决定按稳定键迁移，口径一致 |

**不可比较原因**：
1. **split 成员变化**：修复后同一 seed=42 的稳定拆分与旧拆分（PYTHONHASHSEED=0
   下）成员不同 → dev/holdout case 集合不同，任何逐 case 对比均无意义；
2. **旧运行未固定 hash seed**：历史各运行（auto-run / reranker-recheck /
   selector-ablation）的 split 集合一致性未验证，本就不可与任何新运行直接比较；
3. 真值链已因补标与迁移变化（8 meta-* 补标 + 2 snippet 修正 + 稳定键迁移）。

因此本报告数字**取代**旧候选数字作为当前 CANDIDATE 基线，但仍需人工
批准阈值后才可视为正式基线。

## 六、风险与限制

1. **语料规模**：仅 6 文档 / 736 chunks、单领域；阈值仅对当前语料 + 提示词
   （prompt_id 锁定）+ deepseek-chat 有效；语料扩充、prompt 或模型变更后
   必须重新校准。
2. **holdout 功效不足**：answerable 12 例，置信区间宽；正式上线建议扩充
   评测语料后重跑以收紧阈值。
3. **micro=1.0 未受挑战**：无 fabricated/not-in-context 正例，guardrail 对
   引用真实性退化的区分能力未经实证——需含对抗性 case 的语料验证。
4. **真值为 LLM 辅助审阅**（非人工签署）：guardrail 阈值建议的置信度
   受此限制；人工批准阈值时需同步复核真值抽样。
5. **dev false_refusal_rate=0.1918 贴近建议阈值 0.20**：误拒答风险偏高，
   建议人工复核 dev 拒答 case 分布后再定阈值。
6. **未改动项**：未修改任何历史 results 产物与 decision-report.md；
   未 stage/commit；未自动启用 Graph/reranker；未修改生产默认。

## 七、结论

- **工程就绪**：稳定 split（指纹锁定、fail-closed 校验）→ LLM 辅助审阅真值
  overlay → 锁校验 → dev（95 例）+ 独立 holdout（15 例）全链路 exit 0，
  Truth gate passed，产出 citation v2 guardrail 基线（CANDIDATE v2）。
- **策略保持**：生产基线维持 `reranker=none`、`cap=3`、Graph 禁用；
  本次无任何自动切换或自动批准。
- **上线前置**：① 人工批准阈值（§四）；② 建议人工复核 dev 拒答 case 与
  真值抽样；③ 扩充语料后重跑以验证 micro 区分能力与收紧 holdout 阈值。

*本报告由自动化流程生成（`production-baseline-stable-20260805T084256/` 内
脚本可复现）；真值为 LLM 辅助审阅（非人工签署），阈值批准待人工。*
