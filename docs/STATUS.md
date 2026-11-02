# 项目状态与下一步（2026-11-02）

> **定位**：本文件是行动账本（action ledger），只回答“现在卡在哪、接下来做什么、
> 如何验收”。历史事实与证据仍以 [CHANGELOG](../CHANGELOG.md)、[plans](../plans/)、
> [`results/`](../results/) 为准；本文件不替代、不改写它们。
>
> **维护规则**：状态变化时更新 §5 汇总表；关闭项保留一行并注明日期与证据链接；
> 新增行动项必须带验收标准（DoD）。本文件不记录已完成工作的细节，细节看 CHANGELOG。

---

## 1. 快照

| 维度 | 状态 |
|---|---|
| 代码 | `main` @ `004e903`（产品源码基线 `1066d60`；T1–T8 + M6a Phase 2A 文档提交；未 push） |
| 路线图 | 23 个子项：**10 `[x]` / 10 `[~]` / 3 `[ ]`**；阶段 2 四子项全闭环；阶段 4 `NO_PROMOTION` |
| 评测 | 答案级评测线 M1–M5d 闭环并 PASS；产品默认为臂2（2026-09-09） |
| 质量门 | ✅ 默认套件 **2653 passed / 8 skipped / 318 deselected / 0 failed / 0 errors**（2026-10-31 收口）；`frozen_stage` 独立已知红 **240 failed / 78 errors / 0 passed / 2661 deselected** → P0-1 |
| 文档 | 路线图已回填至 2026-09-09（T4）；本文件为唯一行动账本；M6 决策包、M6a 预注册与 Phase 2A/2B 记录已归档 |

**总体判断**：功能与评测体系已基本建成；T1–T8 已清除“测试债 + 文档回填”两个阻断项，
并把 285 个被隔离的通过用例恢复回默认套件。P1-3 已由 owner 裁决关闭；M6a Phase 2B 于
2026-11-02 判 **FAIL / NO_GO**，已关闭、不合并，产品默认不变；P2-1 进入成本观察。
当前剩余的是 P2-1 真实使用样本，不再是工程阻断。

---

## 2. P0（阻断验收，先做）

### P0-1 全量回归红：冻结阶段测试与共享真值 SHA 耦合 — **DONE（2026-10-31；隔离 A + T1b 恢复）**

**现状**
- 2026-09-09 基线（已归档）：[2026-09-09-full-regression.log](../results/regression/2026-09-09-full-regression.log)，
  **2653 passed / 240 failed / 78 errors / 8 skipped**，282.49s。
- 2026-10-31 收口（T1/T1c + T1b）：
  - 默认套件绿：[2026-10-31-default-suite.log](../results/regression/2026-10-31-default-suite.log)，
    **2653 passed / 8 skipped / 318 deselected / 0 failed / 0 errors**，327.98s；
  - 冻结套件独立复现：[2026-10-31-frozen-stage.log](../results/regression/2026-10-31-frozen-stage.log)，
    **240 failed / 78 errors / 2661 deselected / 0 passed**，21.35s（`--tb=line`，预期 exit 1）。
- 318 个 known-red = 1 个全红测试文件保留模块级 marker（12 例）+ 30 个文件、305 个函数级
  marker（覆盖 306 个节点；一个参数化用例的两个节点共用 1 个 marker）。**285 个原本通过
  的历史用例已恢复**；默认套件 selected 2661 = 2653 passed + 8 skipped。

**根因**（未变）
1. 这些阶段门禁测试的 preflight 断言「当前输入 SHA == 该阶段 manifest `inputs`」；
2. 输入指向 live 的 [v2-cases-draft.jsonl](../evaluation/datasets/v2/annotations/v2-cases-draft.jsonl)；
3. `f28cce5`（2026-08-29，Round-2 人审修复）按 owner 仲裁**原地改写 draft 8 行**，v2.1 随后继续演进；
4. 旧阶段 preflight 全部 fail-closed。**这不是产品代码回归**，是测试与共享真值文件的耦合。

**影响**
- 默认套件已可作验收依据，通过数回到 2026-09-09 基线 **2653**；[ci.yml](../.github/workflows/ci.yml)
  的 unit-tests 已排除 `frozen_stage`，并新增 `frozen-stage-known-red` 非阻断 job（schedule/manual）。
- 318 个 known-red 只在独立 job 复现；默认套件不含这些历史门禁，不能把“绿”表述为
  “全部历史阶段门禁已通过”。
- CI 侧尚未在远端核实（本机无 GitHub 访问）；以本机 2026-10-31 两次运行为准。

**决策（2026-10-31）：采用方案 A（隔离）+ T1b（精确 marker）**

| 方案 | 做法 | 结论 |
|---|---|---|
| A 隔离 | `frozen_stage` marker + 默认套件排除 + 独立 known-red job | **已采用**；T1b 进一步把 marker 精确到失败节点，285 例恢复 |
| B 快照化 | 输入改读 `revisions/` 链上的封存快照 | 未实施；B 保留给未来 draft 再演进时彻底解耦 |
| C 重基线 | 更新旧 manifest 的 inputs SHA | **拒绝**：改写冻结证据，违反零触碰原则 |

**DoD**
- [x] 方案选定并记录（A + T1b；B 保留为未来选项）
- [x] 默认套件 0 failed / 0 errors（2026-10-31 本机复现；CI 待 push 后验证）
- [x] 318 个 known-red 精确标记；285 个原本通过用例恢复默认套件
- [x] 回归日志入库（`results/regression/`，2026-09-09 与 2026-10-31 三份）

**残余工作（不阻断，登记备查）**
- **CI 远端验证**：push 后确认 unit-tests 绿、known-red job 只报预期 240/78。
- **frozen job 仅 ubuntu-latest**：Windows 本地门禁需手动跑两条命令（见 §6）。
- **v206 全红模块**：`tests/test_corpus_v2_v206_evidence_count_reconciliation.py` 的 12 个节点
  仍为模块级 marker；若未来有节点恢复通过，再把 marker 细化到函数级。

### P0-2 回归证据未入库 — **DONE（2026-10-31）**

- [2026-09-09-full-regression.log](../results/regression/2026-09-09-full-regression.log) 已入库
  （36,802 字节，SHA-256 `2FFC1393…77C18F`）；原件 `results/full-regression-post-arm2-default.log`
  已删除，`.gitignore` 对应规则已移除。
- 2026-10-31 两份门禁日志同目录归档，SHA-256 与读数见
  [results/regression/README.md](../results/regression/README.md)。
- **DoD**：`git status` 无该日志的未跟踪/忽略残留；本文件、CHANGELOG、README 的引用均可解析。✅

---

## 3. P1（本迭代应完成）

### P1-1 路线图回填 — **DONE（2026-10-31，T4）**

[plans/RAG-IMPROVEMENT-PLAN-2026-08-01.md](../plans/RAG-IMPROVEMENT-PLAN-2026-08-01.md) 已补记：

- v2.1 数据集激活（2026-08-30，`dd66b09`）；
- 答案级评测线 M1–M5d（2026-08-30 → 2026-09-06）；
- P1 检索缺口门禁终止（M4d FAIL + owner 决策 A）；
- 产品默认切臂2（2026-09-09，`1066d60`）。

头部加 2026-10-31 注记，阶段 0/1/3 与 0.1/0.3/1.5 补记，新增 §十一“答案级评测线补记”；
**未改**阶段 0–4 的既有 `[x]/[~]/[ ]` 判定（候选升级只作建议，见 §11.4）。

**DoD**
- [x] 阶段 0/1/3 的状态注记补充 2026-09-09 前的评测结论
- [x] 新增“答案级评测线”小节，链到 M5d 报告
- [x] 全文不再出现与已闭环结论矛盾的“待批”句（§2.2 已改为“已获 owner 批准并终审”）

### P1-2 下一里程碑立项（M6 或等价） — **NO_GO（M6a Phase 2B FAIL 2026-11-02；已关闭）**

M5d 之后没有立项文档。T5 已产出
[ANSWER-LEVEL-M6-CANDIDATES-2026-10-31.md](../plans/ANSWER-LEVEL-M6-CANDIDATES-2026-10-31.md)：
四个候选放在同一把尺子下（证据强度 / 约束兼容性 / 预算 / 可机械判定性 / 前置依赖），
含预注册判据、冻结边界、风险与 owner Q1–Q4；T6 成本报告补上了“成本-质量线”的量化依据。

| 候选 | 依据 | 关键约束 |
|---|---|---|
| 引用质量线 | M5d：citation recall 仅 **0.0456**；M2：122 可答例中 99 例检索缺口 | 不碰检索排序（P1 已终止为门禁），只做引用选择/覆盖/呈现 |
| 成本-质量线 | 臂2 token **2.674×**（441,496 → 1,180,703 / 150 例）；增量 99.58% 在 prompt | 需预算上界与停损；先量化真实使用分布 |
| 1.4 reranker 净收益 | 默认关闭，从未用答案级仪器验收 | 需预注册 A/B，判据用 G1/G2′ 而非 P1 |
| 引擎侧契约修复 | en-052 / mixed-030 / mixed-033 持续 contract error，2026-08-27 登记方向 | 评测侧已在 M3 judge 预演，产品侧未实施 |

**owner 裁决（2026-10-31）**：认可 T5 §6.2 推荐——
- **M6a 引用质量线**：主选；启动前产出独立预注册（判据、预算按 §七 Q1 锁定）。
- **候选4 引擎侧契约修复**：降级为 P2 探针，与 M6a 并行；不单独占 M6 主预算。
- **候选2 成本-质量线**：排队；先补 P2-1 真实使用分布。
- **候选3 1.4 reranker**：不授权。
“方向认可”与预注册签批不等于产品默认切换；实施按预注册 §八，默认变更仍须另行批示。

**M6a 结果（2026-11-02，NO_GO）**：
原 2026-11-01 预注册（Q1-a..e）已被
[Phase 2A 预注册](../plans/ANSWER-LEVEL-M6a-PHASE2A-ORACLE-PREREGISTRATION-2026-11-01.md)
重签覆盖；原 C1≥0.10 / C3≥0.0400 不再适用。Phase 2A 冻结映射与 oracle 后，Phase 2B
离线配对重放（worktree `D:\GitHub\mneme-phase2b`，提交 `f6fb7ac`，未 push）：

- 150/150 剥离 `[S#]` 后逐字节一致；槽位 460/460；102 个被重定向。
- C1 `store_hit_recall_evi` **0.3578** < 0.4125；C3 `precision_evi` **0.2963** < 0.3060；
  两者均低于 control（0.3767 / 0.3160）。
- C2/G2′ 因 C1/C3 硬失败未执行；capture 未修复，fabricated/retrieved 未验证。

裁决 **FAIL / NO_GO**：不合并 `feat/m6a-citation-selection`，不重跑、不调阈值；如重启须另立预注册。
产品默认不变。

**建议**（T5 §6.2，已被上述 owner 裁决取代）：保留原文的候选对比与预算依据；
M6a 的预注册须独立成文，不在本账本内直接启动。

**DoD**
- [x] 四候选可比决策包产出（含预算、非目标、冻结边界、预注册判据）
- [x] owner 选定方向（2026-10-31：M6a 主选；候选4 P2 探针；候选2 排队；候选3 不授权）
- [x] 产出 M6a 的独立预注册文档并签批（2026-11-01，Q1-a..e）
- [x] M6a Phase 2B 评测完成并关闭（FAIL / NO_GO，2026-11-02；不合并、不重跑、产品默认不变）

### P1-3 陈旧开放标记裁决 — **DONE（2026-10-31，owner 裁决关闭）**

三份文档头部均已改为“2026-10-31 处置注记（owner 裁决）：`CLOSED`”，并给出
**裁决关闭**的理由与替代路径（不修改原文状态行、不删除原文）：

- [REFUSAL-POLICY-ABLATION-DESIGN-2026-08-05.md](../plans/REFUSAL-POLICY-ABLATION-DESIGN-2026-08-05.md)
  — 已执行并结案 `AUTOMATED_DIAGNOSTIC_NO_GO`；目标缺陷已由臂2 阈值/容量覆盖；**裁决：关闭**。
- [REFUSAL-THRESHOLD-CALIBRATION-DESIGN-2026-08-05.md](../plans/REFUSAL-THRESHOLD-CALIBRATION-DESIGN-2026-08-05.md)
  — 目的已由 `DEFAULT_REFUSAL_THRESHOLD` 0.03→0.015 达成并经 M4c/M5d 验收；**裁决：关闭**（含 §五 不排期）。
- [REFUSAL-SEPARABILITY-HYPOTHESIS-AUDIT-DESIGN-2026-08-05.md](../plans/REFUSAL-SEPARABILITY-HYPOTHESIS-AUDIT-DESIGN-2026-08-05.md)
  — 标签集是词表口径伪影的产物，且排序已是主导缺口；**裁决：关闭**（不排期），重开须以 al3 语义标签另立预注册。

**DoD**
- [x] 三份文档均有 2026-10-31 注记（`CLOSED`，附裁决）
- [x] owner 裁决后已把 `OPEN` 改为 `CLOSED` 并注明取代结论

---

## 4. P2（观察 / 卫生）

### P2-1 臂2 成本观察 — **WATCH（基线已建立，T6）**

- 已验证收益：修正率 **0.5575**、语义拒答 **1.0**、误拒率 **0.1393**；代价 token **+167%**。
- 完整回退通道（复现 M2 基线）：`RAG_REFUSAL_THRESHOLD=0.03`、`RAG_DYNAMIC_MIN_K=12`、
  `RAG_CONTEXT_MAX_K=10`、`RAG_CONTEXT_TOKEN_BUDGET=3000`。
- 离线基线：[results/cost-baseline-2026-10-31/report.md](../results/cost-baseline-2026-10-31/report.md)。
  观察阈值（报告 §8）：单查询 p95 **15,618** 预警 / **18,741** 复评；均值 **8,658** 预警 /
  **9,839** 复评；拒答率带 **[0.20, 0.40]**。
- **尚未采集真实用户 trace**；以上是评测 mix 的外推（每 1,000 次查询 ≈7.87M token），
  不是生产观测。
- **owner 2026-10-31 确认**按 T6 阈值继续观察（未选择“暂不监控”）；真实样本 DoD 保持开放。
- **DoD**：一轮真实使用样本的 token/延迟报告，或 owner 明确“暂不监控”的书面决定。

### P2-2 仓库卫生 — **DONE（2026-10-31）**

- `.mimosa/`：已加入 [.gitignore](../.gitignore)，不再出现在 `git status`。
- 旧回归日志：已归档到 [results/regression/](../results/regression/)，原件删除，忽略规则移除。
- `venv/` 缺 pytest：README/README.zh 与回归 README 均说明 `pip install -e ".[dev]"`；
  本轮门禁用系统 Python 3.12.10 + pytest 9.0.3，**未重建 venv**（已文档化，属可选维护）。
- **DoD**：三项均有明确归属（忽略 / 入库 / 文档化），并写入 README、`.gitignore` 或本文件。✅

---

## 5. 汇总表

| ID | 优先级 | 事项 | 状态 | 下一步 | 决策方 |
|---|---|---|---|---|---|
| P0-1 | P0 | 冻结阶段测试与共享真值 SHA 耦合 | **DONE**（隔离 A + T1b） | 观察 CI known-red；v206 全红模块保留模块 marker | 工程（已完成） |
| P0-2 | P0 | 回归日志未入库 | **DONE** | — | 工程（已完成） |
| P1-1 | P1 | 路线图回填（v2.1 / M1–M5d / 臂2） | **DONE** | — | 工程（已完成） |
| P1-2 | P1 | M6 立项 | **NO_GO**（M6a Phase 2B FAIL，2026-11-02） | 已关闭；不合并、不重跑；证据保留在 `mneme-phase2b` | owner/工程（已关闭） |
| P1-3 | P1 | 陈旧开放标记裁决 | **DONE** | — | owner（已裁决） |
| P2-1 | P2 | 臂2 成本观察 | **WATCH** | 按 T6 阈值观察真实使用；owner 已确认观察 | owner |
| P2-2 | P2 | 仓库卫生（`.mimosa/`、日志、venv） | **DONE** | — | 工程（已完成） |

---

## 6. 2026-10-31 / 11-01 执行记录（可复现）

**T1/T1c/T1b marker 收口**
- 31 个测试文件带 `frozen_stage` marker：1 个全红文件保留模块级
  `tests/test_corpus_v2_v206_evidence_count_reconciliation.py`（12 例）；其余 30 个文件用
  函数级 marker 精确覆盖 306 个节点（305 个 decorator；一个参数化用例的两个节点共用 1 个）。
- 7 个既有函数级 marker 保留：5 个 `tests/test_evaluate_v211_*.py` 的 manifest 校验 +
  `tests/test_corpus_v2_repair.py::test_real_corpus_repair_validates` +
  `tests/test_corpus_v2_persistent_reject_repair.py::TestRealCorpus::test_real_transform_idempotent_on_repaired_draft`
  （后两者是内容漂移，非 SHA 根因，已在代码注释中说明）。
- 结果：默认套件 selected **2661 = 2653 passed + 8 skipped**；318 个已知红节点
  （240 failed + 78 errors）只在 frozen job 复现；**285 个原本通过的用例已恢复**。

**门禁命令与读数**（Windows PowerShell 7，系统 Python 3.12.10 + pytest 9.0.3）

```powershell
$env:PYTHONUTF8='1'
python -m pytest -q --ignore=tests/analysis -m "not frozen_stage" -p no:cacheprovider
# 2653 passed, 8 skipped, 318 deselected — 327.98s

# 已知红，预期 exit 1；--tb=line 仅压缩日志体积
python -m pytest -q --ignore=tests/analysis -m frozen_stage -p no:cacheprovider --tb=line
# 240 failed, 78 errors, 2661 deselected, 0 passed — 21.35s
```

**环境坑（已定论）**
- 必须用 `PYTHONUTF8=1`。`PYTHONIOENCODING=utf-8` 会让子进程输出 UTF-8、父进程仍按 GBK
  解码，fresh-process 测试的 `stderr` 变 `None`；不设则 TUI 在 GBK 控制台写 `✓` 失败。
- 默认套件不要设 `MNEME_DATA_DIR` 沙箱：`tests/test_config_contract.py` 需要在真实默认目录下
  断言 `rag` 模块常量与 `Settings` 一致。

**owner 裁决**
- P1-3：三份陈旧拒答设计文档的注记由 `OPEN` 改为 `CLOSED`，原文与状态行不改。
- P1-2 / M6：方向认可 M6a 引用质量线为主选；候选4 契约修复降为 P2 探针并行；
  候选2 成本-质量线排队；候选3 reranker 不授权。M6a 预注册 2026-11-01 签批，
  Phase 2B 于 2026-11-02 判 **FAIL / NO_GO**；M6a 关闭，不合并、不重跑。
- P2-1：owner 确认按 T6 阈值继续观察，未选择“暂不监控”。

**T7/T8 文档收口**
- 本文件；`CHANGELOG.md` 追加 T1–T8 条目；README/README.zh 测试段更新；
  `results/regression/README.md` 扩为三份日志的索引；`.gitignore` 移除旧日志规则。
- 新日志：`2026-10-31-default-suite.log`（SHA-256 `C8D7CECA…56EA6E17`）、
  `2026-10-31-frozen-stage.log`（SHA-256 `B389CF36…0CE6E1`）。
- 本轮改动分两个本地 commit（测试与 CI；文档与证据），**未 push**。CI 远端验证仍待 push 后执行。

**2026-11-01 M6a 签批**
- 预注册 Q1-a..e 已签；单变量 A、C1/C2/C3、预算承诺 1,339,224 / 390 调用、U=21 冻结。
- 文件：`plans/ANSWER-LEVEL-M6a-CITATION-QUALITY-PREREGISTRATION-2026-10-31.md`；
  本次签批文档单独提交，未 push；实施未启动，产品默认不变。

**2026-11-02 M6a Phase 2B FAIL**
- 离线配对重放：150/150 剥离 `[S#]` 一致；460/460 槽位；102 个重定向。
- C1 `store_hit_recall_evi` **0.3578** < 0.4125；C3 `precision_evi` **0.2963** < 0.3060；
  两者均低于 control（0.3767 / 0.3160）。C2/G2′ 未执行（C1/C3 已硬失败）。
- 裁决 **FAIL / NO_GO**；worktree `D:\GitHub\mneme-phase2b`，提交 `f6fb7ac`，未 push；
  不合并 `feat/m6a-citation-selection`，不重跑、不调阈值；重启须另立预注册。
- 未改产品默认、未改产品 `src/`、未更新本文件之外的评测文档。

---

## 7. 明确不动作（避免重复立项）

- **M6a 引用选择线**：Phase 2B 离线配对 **FAIL / NO_GO**（C1 0.3578、C3 0.2963，双低于
  control）；不合并、不重跑、不调阈值。新假设必须另立预注册，不能复用本轮结果。
- **Graph RAG 4.1–4.3**：`NO_PROMOTION`，需新的、独立且预先注册的净收益证据才可重启
  （[路线图 §六](../plans/RAG-IMPROVEMENT-PLAN-2026-08-01.md)）。
- **P1 检索缺口率门禁**：owner 决策 A 终止为产品门禁；0.7459 归档，不再以扩大样本或压阈值方式推进。
- **P1.1 生产观测采集线**：2026-08-27 以 `NO_TRIGGER_FALLBACK` 闭环，不重开。
- **v2.1 数据集**：`ACTIVATED` 冻结真值层，任何改动须走治理流程，不在本账本内直接修改。
- **冻结资产**：v1、v2.0.x 修订树、sealed 产物零触碰。

---

## 8. 参考

- [CHANGELOG.md](../CHANGELOG.md) — 全部已落地工作的证据索引
- [RAG-IMPROVEMENT-PLAN-2026-08-01.md](../plans/RAG-IMPROVEMENT-PLAN-2026-08-01.md) — 五阶段路线图
- [ANSWER-LEVEL-EVAL-LINE-CHARTER-2026-08-30.md](../plans/ANSWER-LEVEL-EVAL-LINE-CHARTER-2026-08-30.md) — 答案级评测线章程
- [M5 预注册门禁](../plans/ANSWER-LEVEL-M5-QUALITY-GATE-PREREGISTRATION-2026-09-06.md) / [M5d 裁决报告](../results/answer-level/m5d-decision-2026-09-06/report.md) / [M4c 裁决报告](../results/answer-level/m4c-decision-2026-09-06/report.md)
- [M6 候选决策包](../plans/ANSWER-LEVEL-M6-CANDIDATES-2026-10-31.md) / [臂2 成本基线](../results/cost-baseline-2026-10-31/report.md)
- [回归证据索引](../results/regression/README.md) / [ci.yml](../.github/workflows/ci.yml) / [README 测试段](../README.zh.md#测试)
