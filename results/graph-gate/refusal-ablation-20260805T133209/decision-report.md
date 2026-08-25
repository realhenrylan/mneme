# 拒答策略受控 Ablation 决策报告（AUTOMATED_DIAGNOSTIC_NO_GO）

> 目录：`results/graph-gate/refusal-ablation-20260805T133209/`
> 性质：**受控实验报告（预注册门槛 fail-closed 判定）** — 结论为
> **NO_GO**：evidence_calibrated 不满足成功门槛，**不提升为生产默认**；
> 不自动切换默认策略、不批准任何 guardrail 阈值。
> 设计：`plans/REFUSAL-POLICY-ABLATION-DESIGN-2026-08-05.md`
> （brainstorming 审批 + 用户规格修订：PreparedAnswerEvidence 共享证据 +
> effective_prompt_ids 锁定）。

---

## 一、实验设计（受控条件）

| 维度 | 配置 | 验证 |
|---|---|---|
| 双臂 | A=`standard`（baseline）vs B=`standard-calibrated`（evidence_calibrated） | lock-refusal-ablation.json + precheck PASS |
| 策略差异 | **仅生成阶段 system prompt 追加静态指令段**（context 证据足以支持时必须作答并引用；仅当无文档片段包含所需信息时才拒答）；检索/QueryPlan/reranker/Graph/selector cap/数据集/真值**零改动** | effective_prompt_ids 逐臂锁定（standard=`d5b905dc…`、standard-calibrated=`2d602fb4…`），addendum 文本/策略名/臂映射任一漂移 → LLM 前拒绝 |
| 证据共享 | 每 case 通过 `prepare_answer_evidence`（从共享 QueryPlan 构建）只构建一次 `PreparedAnswerEvidence`，A/B 两臂仅分别调用 `generate_answer`——零 rewrite/decompose/retrieve/select 重跑 | 评测代码 evidence_cache + paired 分析 fail-closed：dev 95 例 A/B 的 context_sha256 / citation map / candidate 集**全部一致**（`evidence_consistency.ok=True`） |
| 锁定 | split_fingerprint=`454892e4…3690`（与稳定 split 锁一致）；双 overlay（dev 21 confirmed + 4 source-only / holdout 4 confirmed + 4 source-only）；dataset/corpus/index SHA 与稳定锁逐字段一致 | precheck PASS（含 refusal_policy 键集==arms、effective_prompt_ids 键集==arms） |
| 共享基线 | 同一 QueryPlan/检索候选/context/模型（deepseek-chat）/温度（0.1）/预算（cap=3、reranker=none）/seed 42/split | 结构保证 + smoke 两臂指纹一致 |

## 二、流程执行

1. TDD（RED→GREEN 三批次，新增 53 个测试）：策略抽象/PreparedAnswerEvidence/answer_query 拆分/锁定/臂切换/evidence 共享/paired fail-closed；完整 pytest **885 passed / 7 skipped**。
2. precheck PASS（锁/split/overlay/索引/env/immutability 快照）。
3. smoke 15 条 false_refusal 双臂 PASS：A 15/15 拒答、B 14/15（en-016 改善）；**5 例为检索前哨拒答**（evidence.refused，策略无法改善——audit 未区分的层）。
4. dev full（95×2 臂）EXIT=0，gate-eval fail-closed 判定 → **AUTOMATED_DIAGNOSTIC_NO_GO** → **不运行 holdout full**（预注册门槛）。

## 三、dev 结果与门槛判定（全部由 generation JSONL 独立复算）

| 门槛 | 判定 | A (standard) | B (evidence_calibrated) |
|---|---|---|---|
| G1 false_refusal 减少 ≥4 | **FAIL** | 16/73 (0.2192) | **18/73 (0.2466)**（反增 2） |
| G2 false_answer 不恶化 | PASS | 9/22 (0.4091) | 3/22 (0.1364)（改善） |
| G3 micro≥0.95 且 fab=0/nin=0 | PASS | 1.0000（142/142） | 1.0000（134/134） |
| G4 answer_rate ≥ baseline | **FAIL** | 0.8767（64/73） | 0.8219（60/73） |
| G5 coverage 无显著下降 | PASS | 0.6073 | 0.6119（delta 95% CI [−0.012, +0.021]） |
| G6 holdout 方向一致 | 未评估 | — | —（dev NO_GO，不运行） |

### 配对分析（95 例，McNemar）

- W/L/T：**wins_b=8、losses_b=4、ties=83**；McNemar p=0.388（无显著差异）；
- false_refusal delta = +2（CI [−0.074, +0.032]，含 0）；
- answer_point_coverage delta = +0.0035（CI [−0.012, +0.021]，含 0）；
- **切片（目标切片反而恶化）**：
  - **cross_document：false_refusal 6 → 9（+3，恶化）**，coverage delta −0.0455；
  - hard：5 → 6（+1，恶化）；
  - metadata：3 → 3（持平）；multi_turn：2 → 1（改善）。

## 四、诊断解释（NO_GO 根因）

1. **策略放宽的是「拒答倾向」而非「证据条件」**：B 臂 false_answer 大幅改善
   （9→3）说明模型整体更愿意作答（should_refuse case 的误答也减少——提示词
   的「必须作答」对拒答 case 同样生效？不——should_refuse case 正确拒答率
   提高说明 B 臂仍能拒答无证据问题；但 answerable 侧的 false_refusal 增加
   说明部分 case 由「作答」转为「含拒答短语的回答」或被判拒答）。
2. **cross_document 恶化最明显（6→9）**：跨文档综合问题中，B 臂提示鼓励作答，
   但模型在证据不足时产出「未找到/无法回答」式回答（仍命中拒答短语→计
   false_refusal），或强行作答导致答案要点不覆盖。提示词对「复杂问题必须
   作答」的激励未能转化为有效回答。
3. **A 臂自身波动**：本次运行 A=16 vs 历史 production baseline A=14
   （LLM 采样非确定，温度 0.1）；B=18 在噪声范围内仍明确未达标
   （需 ≤12，差距 6 例，超出单次波动解释）。
4. **5 例检索前哨拒答不可由生成策略改善**：15 条审计 case 中 5 条
   （cross-010、en-013、meta-006、meta-008、meta-002）为检索拒答
   （max score < 0.03）——false_refusal 的构成需分层（检索拒答 vs LLM
   拒答），生成策略只覆盖后者。

## 五、结论与建议

- **evidence_calibrated 不提升为生产默认**（NO_GO）；默认 `RAG_REFUSAL_POLICY`
  保持 `baseline`，未做任何自动切换。
- 不建议在当前提示词形态下继续调参上线；下一步候选方向（需人工决策）：
  1. **证据条件化提示**：把「context 有可直接支持证据」的判定从纯提示语义
     改为检索分数/覆盖率特征门控（RAG-IMPROVEMENT-PLAN 阶段 1.5 拒答校准
     特征化路径），避免无差别放宽拒答；
  2. **cross_document 专项**：针对跨文档切片的证据覆盖约束（如多来源覆盖
     检查）而非全局提示放宽；
  3. **检索拒答分层**：false_refusal 报告区分 retrieval-refusal 与
     generation-refusal（本批 evidence.refused 已可区分，后续指标分层）。
- guardrail 阈值（micro≥0.95、answer_rate≥0.80、no_citation≤0.20、
  false_refusal≤0.20）维持 CANDIDATE 状态，本实验不批准、不修改。
- **框架资产已沉淀**（无论策略结果）：PreparedAnswerEvidence 生产级证据
  对象、answer_query prepare+generate 拆分、A/B 共享证据评测、per-arm
  refusal_policy + effective_prompt_ids 锁定、paired fail-closed 分析——
  后续任何生成策略实验可复用。

## 六、风险与限制

1. 单次运行（A/B 各 95 例一次采样），LLM 非确定性下比率有 ±2 例量级波动；
2. holdout 未运行（NO_GO 预注册停止）——B 臂在 holdout 的表现未验证；
3. 提示词为静态文本，未对中文/英文分语言调优；
4. 未修改任何历史 results 产物与 decision-report.md；未 stage/commit。

*本报告由受控评测自动生成（`refusal-ablation-20260805T133209/` 内脚本可复现）；结论为 NO_GO，不构成任何生产配置变更或阈值批准。*
