# Mneme RAG 正式上线前人工签署清单（Manual Sign-off Checklist）

> 目录：`results/graph-gate/final-readiness-20260804T204839/`
> 审计时间：2026-08-04 20:48
> 用途：正式上线（或重新讨论 Graph / unlimited selector 等策略变更）前，**人工必须完成的最小事项**。
> 自动化就绪状态不替代本清单；未完成本清单前，不得声称已获得人工审核或正式上线批准。

---

## 事项 1：审核 22 条低置信 auto-provisional 标注（阻塞性 ⛔）

**背景**：自动标注（`auto-annotation-evidence.json`，`auto-run-20260804T121410/`）共 27 条
overlap confirmed，其中 **22 条为低置信 `auto_provisional`**（基于 `chunk_text_snippet`
在 source 全 chunks 中的 substring / ≥0.15 bigram 匹配，未验证语义等价性）；另有
12 条缺失 chunk 真值（全部保守判 `relevance_level=source`，其中 5 条 medium 置信）。

**必须完成**：
1. 逐条审核 22 条 `auto_provisional` 与 12 条 missing-truth 的 snippet ↔ chunk 映射，
   标注 `confirmed` / `reject` 及 `relevance_level`；
2. 使用 `evaluation/review_apply.py` 严格导入（SHA 校验、行集/键集完整、原子输出），
   生成人工审核后的 `reviewed-truth-overlay.json`；
3. 记录审核人、日期、与自动标注的差异清单。

**影响**：三项自动评测（auto-run / reranker-recheck / selector-ablation）的所有 chunk 级
指标（context_recall 等）均基于该标注。**真值改变 → 结论可能改变 → 必须重跑受控评测。**

**现有流程**：`evaluation/REVIEW_PACK_README.md`（导出 review pack → 填写 → apply →
`compare --reviewed-truth`）。

---

## 事项 2：扩充评测语料（阻塞性 ⛔，针对规模类结论）

**背景**：当前语料仅 **6 个来源文件**（2 PDF 论文、2 PDF 产品/安全文档、1 Markdown
综述、1 DOCX 地理）、736 chunks；Graph 目标切片极小（dev 20-21 例、holdout 仅 3 例
chunk 真值），holdout 各配对检验功效不足（n=12 时 95%CI 宽度 ±0.25）。

**必须完成**：
1. 扩充到覆盖多领域、多文档类型（含高连接密度场景）的语料；
2. 增加 graph_target（cross_document / mixed_intent）与 multi_turn 盲测样例，
   使 holdout 配对具备可区分 ±5pp 级差异的功效；
3. 重新标注/审核真值（结合事项 1 的流程）；
4. 之后才可对「Graph 在更大知识库的价值」「reranker/selector 的边际收益」给出
   非诊断级结论。

**范围**：本事项只影响「规模外推」类结论；「保持现状基线」的策略决定不依赖它。

---

## 事项 3：重新讨论 Graph / unlimited selector 前的独立 holdout（条件触发 ⚠️）

**仅当**要重新讨论以下任一策略变更时触发：
- Graph 通道产品化（默认开启或条件路由）；
- 生产 selector 从 cap=3 切换为 unlimited（`RAG_SELECTOR_MAX_PER_SOURCE=none`）；
- 生产启用 reranker（`RAG_RERANKER=cross-encoder`）。

**必须完成**：
1. 先完成事项 1（人工审核真值）+ 事项 2（语料扩充，或至少明确功效限制）；
2. 在既有受控框架上重跑独立 holdout（框架已就绪：locked-config fail-closed +
   per-arm `arm_selector_policy` + citation v2 `context_supported_citation_validity` +
   QueryPlan/候选池共享）；
3. 固定指标分母口径（见 closeout §4.5：全体 vs 可答分母必须统一）并预先声明
   guardrail 阈值；
4. 以人工审核真值的结果为准，覆盖对应 AUTOMATED_DIAGNOSTIC_NO_GO 结论。

**当前不触发**：三项自动决策均为 NO_GO，维持基线无需任何动作。

---

## 完成定义

- [ ] 事项 1：22 条 auto_provisional + 12 条 missing-truth 全部人工审核，overlay 导入
      成功，差异记录归档；
- [ ] 事项 2：语料扩充完成（含 graph_target/multi_turn 覆盖），真值经人工审核；
- [ ] 事项 3：若触发——基于人工真值的独立 holdout 完成，报告可复核；
- [ ] （可选）在人工真值 + 固定分母下重跑 selector policy / reranker ablation，
      建立 citation v2 guardrail 基线阈值。

**签署**：____________________（审核人）　　日期：____________________

---

*本清单由自动化审计生成（`final-readiness-20260804T204839/`），不构成审批结论。*
