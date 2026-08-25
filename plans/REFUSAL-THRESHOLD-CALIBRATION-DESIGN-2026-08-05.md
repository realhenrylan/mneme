# 检索拒答阈值校准（Refusal Threshold Calibration）设计文档

> 日期：2026-08-05
> 状态：**已批准**（用户修订：G2 主口径分母改为该 split 全部 `should_refuse` case）
> 关联：plans/RAG-IMPROVEMENT-PLAN-2026-08-01.md（阶段 1.5 拒答校准）、
> REFUSAL-POLICY-ABLATION-DESIGN-2026-08-05.md（生成策略消融，NO_GO）、
> results/graph-gate/refusal-guardrail-audit-20260805T113849/（只读审计）

---

## 一、背景与目标

拒答策略消融（refusal-policy ablation）发现：dev baseline 的 16 条
false_refusal 中，有 5 条由**检索前哨拒答**（`evidence.refused`，max score
< 0.03）直接产生，生成阶段策略无法改善。本实验研究唯一可调参数
`DEFAULT_REFUSAL_THRESHOLD`（0.03）的候选值（0.00 / 0.01 / 0.02 / 0.03），
验证更低的检索拒答阈值能否**只**释放这些前哨 false_refusal，而不把
`should_refuse` case（应拒答、无相关 chunk）放行给 LLM。

约束（用户规格，逐字保留）：

- 保持 `RAG_REFUSAL_POLICY=baseline`；**禁止**复用或启用
  `evidence_calibrated`；
- 不改 QueryPlan / reranker / Graph / selector / 数据集 / 真值 / 生产默认；
- 不调用 LLM/API（本批为纯离线只读分析）；
- 不 stage/commit；不改写任何历史 results 产物与 decision-report.md；
- 不自动切换生产默认、不批准 guardrail。

## 二、决定性与探索结论（已核实的数据事实）

检索是确定性的（同一 split + 索引 + 配置 → 同一 `candidate_scores`）；
跨运行微差（6 例 float 差异）不跨越任何拒答边界（0.03），拒答分类跨运行
一致。

**dev（95 例）**：`should_refuse` = 22；baseline（0.03）检索拒答 = 10：

| 分组 | case_id（max score） |
|---|---|
| 前哨 FR（answerable，max<0.03） | cross-010 (0.02988)、en-013 (0.02837)、meta-006 (0.02830)、meta-008 (0.02601) |
| 正确拒答（should_refuse，max<0.03） | noanswer-006 (0.02649)、noanswer-008 (0.02490)、noanswer-012 (0.02938)、noanswer-020 (0.02353)、noanswer-022 (0.02210)、noanswer-024 (0.02649) |

**holdout（15 例）**：`should_refuse` = 3；baseline 检索拒答 = 2：
前哨 FR = meta-002 (0.02857)；正确拒答 = noanswer-010。

任务口径中"5 条前哨 false_refusal" = dev 4 条 + holdout meta-002 1 条
（与 refusal-policy ablation smoke 的 `evidence_refused` 清单一致）。

**关键事实**：全部拒答 case 的 max score 位于 [0.0221, 0.03)，
**不存在低于 0.02 的 case** → 候选阈值 0.00 / 0.01 / 0.02 的放行集合
完全相同：10 = 4 FR + 6 should_refuse（dev）；2 = 1 FR + 1 should_refuse
（holdout）。

## 三、预注册门槛（正式定义）

对每个候选阈值 t（放行 = `max(scores) ≥ t` 且 baseline 拒答）：

- **G1**：放行的前哨 false_refusal ≥ 4/5（dev 4 条 + holdout 1 条；
  按 split 报告，合并判定）。
- **G2（主口径，用户修订）**：新放行 `should_refuse` case 数 ≤
  **该 split 全部 `should_refuse` case 数**的 10%。
  - dev：6 新放行 vs 10% × 22 = 2.2 → FAIL；
  - holdout：1 新放行 vs 10% × 3 = 0.3 → FAIL。
  - **敏感性表**（保留三种基数）：基线检索拒答总数（dev 10 / holdout 2）、
    其中 should_refuse 数（6 / 1）、全部 should_refuse（22 / 3）；
    10% 容许量分别为 1.0 / 0.6 / 2.2 与 0.2 / 0.1 / 0.3——三种口径结论
    一致 FAIL。
- 任一候选阈值不满足双门槛 → **AUTOMATED_DIAGNOSTIC_NO_GO**，不进入
  LLM 评测、不生成锁、不实施第二阶段。

补充诊断（不参与门槛）：分数带交织分析——前哨 FR 带 [0.0260, 0.0299] 与
正确拒答带 [0.0221, 0.0294] 完全交织；任何放行全部 4 条 dev FR 的阈值
（t ≤ 0.026）必然同时放行 ≥3 条正确拒答 → **不存在任何阈值值（不限于
候选集）能同时满足双门槛**。

## 四、扫描模块设计（TDD，唯一无条件交付）

新增 `evaluation/threshold_scan.py`（纯函数 + CLI，零 LLM 调用）：

| 函数 | 职责 |
|---|---|
| `refused_at(scores, threshold)` | `not scores or max(scores) < threshold`（空分数在 t=0.00 仍拒答） |
| `scan_thresholds(rows, baseline, thresholds)` | 逐阈值输出新放行 answerable / should_refuse id 列表与计数 |
| `evaluate_gates(scan, sentinel_fr_ids, should_refuse_total, ...)` | G1 / G2（主口径）+ 敏感性表 |
| `band_diagnostic(...)` | 分数带与交织诊断（放行全部 FR 时最少放行的正确拒答数） |
| `check_generation_consistency(...)` | fail-closed：score 判定（max<0.03）与 generation JSONL 的 `evidence_context_sha256==""` 逐 case 一致，不符抛 ValueError |
| `check_cross_source_agreement(...)` | fail-closed：跨运行（production-baseline vs ablation）拒答分类一致，不符抛 ValueError |
| `render_markdown(...)` | 报告渲染（确定性） |
| `main()` | CLI：输入 JSONL → 校验 → 扫描 → 写 threshold-scan.json / threshold-scan.md / gate-pre-registration.json |

输入数据源（fail-closed）：

- dev 扫描主源：`refusal-ablation-20260805T133209/dev-full/retrieval-cases.jsonl`
  （standard 臂，与"16 条 FR / 5 条前哨"同一运行）；
- dev 交叉校验源：`production-baseline-stable-20260805T084256/dev-full/retrieval-cases.jsonl`；
- dev 生成一致性校验：`refusal-ablation-20260805T133209/dev-full/generation-cases.jsonl`
  （含 evidence 字段；production run 无 evidence 字段，故该校验仅 dev）；
- holdout 主源：`production-baseline-stable-20260805T084256/holdout-full/retrieval-cases.jsonl`。

测试计划（tests/test_threshold_scan.py，纯 mock fixture）：空分数 t=0.00
仍拒答；边界语义（max==t 放行）；逐阈值放行集；G1 通过/失败；G2 主口径
通过/失败（边界 2 ≤ 2.2）；敏感性三基数；交织诊断；fail-closed 两个
校验（不符抛 ValueError）；输出确定性（同输入同字节）。

## 五、第二阶段（条件化，本批不实施）

仅当出现合格候选阈值（未来语料扩充后重扫）才实施，路径预定义：

1. `src/rag.py` 新增模块级 `RAG_REFUSAL_THRESHOLD: float | None = None`
   （与 `RAG_REFUSAL_POLICY` 同模式）；`retrieval_refused` 解析顺序：
   显式参数 → 模块属性 → 环境变量 → `DEFAULT_REFUSAL_THRESHOLD`；
   生产默认与 env 行为不变。
2. `build_locked_config` 新增必填 per-arm `refusal_threshold`（键集==arms、
   值 float≥0、fail-closed；load/validate 旧锁向后兼容）。
3. `_run_generation_arm` 按臂 try/finally 覆盖模块属性；evidence 缓存键
   含 threshold（不同阈值不共享 evidence，QueryPlan/检索候选仍共享）。
4. smoke（5 前哨 FR + 新放行 should_refuse）→ dev full → 门槛
   （false_refusal 减 ≥4、false_answer 不恶化、citation v2 micro≥0.95 /
   fabricated=0 / not_in_context=0、answer_rate 与 coverage 不显著下降）
   → holdout 方向一致，否则 NO_GO。
5. 阈值感知 paired analysis：非放行 case 的 A/B 证据指纹（context_sha256 /
   citation map / candidates / plan）必须一致（fail-closed）；放行 case 允许
   A 拒 B 答，但 B 的 plan/candidates 指纹必须与 A 一致且 B 有完整 context。

## 六、交付物（本批）

时间戳目录 `results/graph-gate/refusal-threshold-scan-20260805T<time>/`：

- `threshold-scan.py`（模块副本，可复现）
- `threshold-scan.json`（机器可读：逐阈值放行表 + 门槛 + 诊断）
- `threshold-scan.md`（报告）
- `gate-pre-registration.json`（G1/G2 判定 + 敏感性 + 结论）
- `decision-report.md`（NO_GO 结论：`DEFAULT_REFUSAL_THRESHOLD=0.03`
  保持不变，不切换生产默认、不批准 guardrail）
- `manifest.json`（输入 SHA-256、case 数、不可变性说明）
- `run-commands.md`

另更新 CHANGELOG.md（本批改动条目）。

## 七、验证

- 相关测试：`pytest tests/test_threshold_scan.py -q`；全套件回归；
- `python -m py_compile evaluation/threshold_scan.py tests/test_threshold_scan.py`；
- `git diff --check`；
- 历史产物不可变性复核（decision-report.md 等未改动）。

## 八、不在本批范围

- 不实施 §五 的任何代码（per-arm threshold 覆盖 / 锁字段 / paired
  analysis 扩展）；
- 不调用 LLM/API；不跑评测；不改生产默认；
- 不 stage/commit。
