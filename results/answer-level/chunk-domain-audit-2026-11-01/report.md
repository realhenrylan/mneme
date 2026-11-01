# Mneme Phase 1：citation chunk 域只读审计报告

- 日期：2026-11-01
- 基线：main @ `c70cda2e496c8e9d6e2cd5eea8062b0647e8a263`（已含 docs/AUDIT-CHUNK-DOMAIN-2026-11-01.md）
- 性质：只读审计（非评测、非产品修改、非阈值标定）
- 产物目录：`results/answer-level/chunk-domain-audit-2026-11-01/`
- 审计脚本：`scripts/audit/rebuild_runtime_map.py`、`scripts/audit/build_store_bridge.py`、`scripts/audit/recompute_metrics.py`、`scripts/audit/audit_baseline.py`、`scripts/audit/finalize_audit.py`

---

## 0. 结论摘要：C1/C3 是否还能在 runtime 域定义？

**能定义（附带 Phase 2 重签条件）：**

1. 映射覆盖率 1.00（1006/1006 store chunks 至少有 1 个 runtime 候选）≥ 95% 门槛，**允许宣称信号存在**。
2. 桥接后三臂信号存在且排序在全部阈值下稳定：**arm2 > arm1 > m2**（例：t=0.50/ratio_runtime 下 citation recall 0.2510 > 0.2267 > 0.1928；context recall 0.4008 > 0.3489 > 0.2955），方向与两臂设计意图一致 → **C1（recall）/C3（precision）有可用信号**。
3. 但旧预注册全部数字（控制臂 0.0456、C1≥0.10、C3≥0.0400、上界 0.2067、U=21）属于 ID 碰撞域，**不可平移**：桥接后旧控制臂 arm2 自身即达 recall 0.2510 / precision 0.3494（t=0.50/runtime），旧阈值会被控制臂直接"通过"而失去区分力 → Phase 2 必须基于桥接后基线**重新签定** C1/C3 阈值与上界。
4. a′ baseline：ordered context ID 在 runtime 域 **100% 可解析**，但 `full_sources` 仅含 150 字符 snippet（150/150 例），**单凭记录无法精确重放 context** → Phase 2 任何依赖 context 文本的裁决前，须先实施 §6 的 eval-only capture 修复（本轮不实施）。

**一句话**：C1/C3 在 runtime 域**可定义、有信号**，但必须换用本报告的桥接口径重签阈值，并先补 capture；旧 M6a 预注册数字全部作废。

---

## 1. 停止条件检查

| # | 停止条件 | 结果 | 证据 |
|---|---------|------|------|
| 1 | 重建 runtime chunk 数 ≠ 2,947 且无法解释 | **未触发** | 重建 = 2,947（预期命中） |
| 2 | context ID 可解析率 < 95% | **未触发** | M2/arm1/arm2/a′ 四臂全部 1.00 |
| 3 | store→runtime 映射覆盖率 < 95% | **未触发** | 1.00（1006/1006） |
| 4 | 必须修改 src/ 才能重建 | **未触发** | 复用 LoaderRegistry + chunk_document 生产路径 |
| 5 | 任一步需 LLM 或网络 | **未触发** | 全程离线，未调用任何模型 |

**结论：无停止条件触发，审计完成。**

---

## 2. §3.1 runtime v3 chunk 重建（预期 2,947）

**方法**：`LoaderRegistry(Pdf/Docx/Text).load` + `src.chunking.chunk_document`（与 `src/rag.py` 单文件加载路径一致，**未复制/改写切分逻辑**）；对 13 个数据集源文件重建。span 由 chunk 文本在原始文件中的**空白不敏感顺序搜索**定位（记录 char span、parent_id、section_path）。`normalized_id` = 源哈希前 12 位 + `_chunk_N`（与 `evaluation/generation_runner._normalize_chunk_id` 同规则）。

### 2.1 逐源重建数（合计 2,947 ✓）

| 源文件 | chunks | 源文件 | chunks |
|---|---:|---|---:|
| art-of-war.txt | 1,195 | python-whatsnew313-zh.md | 132 |
| rfc3986.txt | 554 | sqlite-lang.md | 83 |
| python-tutorial-en.md | 258 | python-datetime-zh.md | 72 |
| python-tutorial-zh.md | 212 | vue-guide-zh.md | 61 |
| nodejs-fs.md | 190 | react-learn-zh.md | 44 |
| rust-book-core.md | 98 | python-glossary-zh.md | 26 |
| postgresql-tutorial.md | 22 | | |
| **合计** | | | **2,947** |

span 定位：2,947/2,947 全部定位（missing=0）。distinct normalized_id = 2,947。

### 2.2 现有 runtime context ID 可解析率

| 臂 | 字段 | distinct ID | 可解析率 | 逐例全解析 | 说明 |
|---|---|---:|---:|---:|---|
| M2 | context_chunk_ids | — | **1.00** | 107/150 | 43 例 context 为空列表（无可解析对象，按口径通过） |
| arm1 | context_chunk_ids | — | **1.00** | 150/150 | unresolved distinct = 0 |
| arm2 | context_chunk_ids | — | **1.00** | 150/150 | unresolved distinct = 0 |
| a′ | context_chunk_ids_ordered | 920 | **1.00** | 150/150 | ordered 共 3,108 个 ID 全部可解析 |

四臂均 ≥95%，停止条件 #2 未触发。

---

## 3. §3.2 store truth → runtime chunk 桥

**映射规则（全程禁止 ID 映射，每条映射均有 source+span 或文本证据）：**

1. **优先 source + 字符 span 重叠**：store chunk 文本（chunks.jsonl，无 span 字段）与 runtime chunk 文本分别在**同一原始源文件**中以空白不敏感顺序搜索定位 span，取交集得 `overlap_chars`，比值 `ratio_runtime = overlap / runtime_span_len`、`ratio_store = overlap / store_span_len`。
2. **无 span 时回退**：归一化文本包含/高重叠（本轮 fallback 使用 0 次）。
3. 一对多允许；候选中若 ≥2 个各覆盖 ≥50% 记为 ambiguous（歧义）。

### 3.1 覆盖率与结构

| 指标 | 值 |
|---|---:|
| store chunks 总数 | 1,006 |
| 至少 1 个 runtime 候选（**映射覆盖率**） | **1.00**（1,006/1,006） |
| 未映射 | 0 |
| span 定位成功 | 1,006（回退包含法 0） |
| 一对多 | 930 |
| 歧义（≥2 候选各 ≥50%） | 16 |

### 3.2 阈值条件覆盖率（≥1 候选且比值 ≥ t）

| 阈值 t | ratio_runtime | ratio_store |
|---:|---:|---:|
| 0.25 | 0.9960 | 0.9513 |
| 0.50 | 0.9851 | 0.7465 |
| 0.75 | 0.8877 | 0.4463 |

**读法**：整体覆盖率 1.00（停止条件 #3 未触发）；但**阈值条件覆盖率**在 ratio_store≥0.50（74.7%/44.6%）与 ratio_runtime≥0.75（88.8%）时 <95%，这些组合**不得单独作为 C1/C3 结论**（metrics.json `c1_c3_assessment.threshold_coverage_flags` 已逐行标记）。

---

## 4. §3.3 用桥复算 M2 / M4c arm1 / arm2

**口径**：与现指标完全一致——逐例 precision/recall 后对**全部 150 例**求均值、round 4；retrieved 为空 → precision 0.0，truth 为空 → recall 0.0（同 `evaluation/citation_metrics.py:206-218` + `_aggregate`）。truth 与 `evaluation/datasets/v2.1.jsonl` 逐例零 mismatch（三臂均 0）。检索侧两种口径：`ctx_based`（retrieved = context_chunk_ids）、`evi_based`（retrieved = citation supported chunks）。

### 4.1 新旧对照 + ID 碰撞复现校验（match 校验）

| 臂 | 旧 manifest recall | 旧 manifest precision | 本复算（ID 域原样）recall | precision | case any-overlap | 与旧 manifest 吻合 |
|---|---:|---:|---:|---:|---:|---|
| M2 | 0.0322 | 0.0300 | 0.0322 | 0.0300 | 0.1533 | **✓ match** |
| arm1 | 0.0322 | 0.0333 | 0.0322 | 0.0333 | 0.1667 | **✓ match** |
| arm2 | 0.0456 | 0.0400 | 0.0456 | 0.0400 | 0.2067 | **✓ match** |

→ 复算口径与旧实现逐位一致，确认旧值即 ID 碰撞伪值（与 AUDIT 文档 §2.2 一致）。

### 4.2 桥接后主结果（t = 0.50，ratio_runtime，覆盖率 98.5%）

| 臂 | recall (ctx) | precision (ctx) | recall (evi) | precision (evi) | case any-overlap | store-hit recall (ctx) |
|---|---:|---:|---:|---:|---:|---:|
| M2 | 0.2955 | 0.0710 | 0.1928 | 0.2940 | 0.4133 | 0.3567 |
| arm1 | 0.3489 | 0.0792 | 0.2267 | 0.3336 | 0.4667 | 0.4167 |
| arm2 | 0.4008 | 0.0521 | 0.2510 | 0.3494 | 0.5333 | 0.4694 |

三臂 fabricated 合计 = 0、retrieved_not_in_context 合计 = 0（按 metrics.json 记录；两者在旧 capture 域内计算，Phase 2 重签时须在修复 capture 后重测）。

### 4.3 敏感性表 A：ratio_runtime 阈值（覆盖率 99.6%/98.5%/88.8%）

| 臂 | t | rec (ctx) | prec (ctx) | rec (evi) | prec (evi) | any-overlap | store-hit (ctx) | truth 未映射率 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| M2 | 0.25 | 0.2919 | 0.0758 | 0.1824 | 0.3018 | 0.4267 | 0.3700 | 0.0000 |
| M2 | 0.50 | 0.2955 | 0.0710 | 0.1928 | 0.2940 | 0.4133 | 0.3567 | 0.0067 |
| M2 | 0.75 | 0.2856 | 0.0626 | 0.1828 | 0.2507 | 0.3867 | 0.3333 | 0.0667 |
| arm1 | 0.25 | 0.3458 | 0.0846 | 0.2180 | 0.3458 | 0.4867 | 0.4333 | 0.0000 |
| arm1 | 0.50 | 0.3489 | 0.0792 | 0.2267 | 0.3336 | 0.4667 | 0.4167 | 0.0067 |
| arm1 | 0.75 | 0.3336 | 0.0702 | 0.2168 | 0.2913 | 0.4400 | 0.3900 | 0.0667 |
| arm2 | 0.25 | 0.4081 | 0.0564 | 0.2494 | 0.3722 | 0.5533 | 0.4894 | 0.0000 |
| arm2 | 0.50 | 0.4008 | 0.0521 | 0.2510 | 0.3494 | 0.5333 | 0.4694 | 0.0067 |
| arm2 | 0.75 | 0.3879 | 0.0465 | 0.2422 | 0.3039 | 0.5067 | 0.4478 | 0.0667 |

t=0.75（runtime）条件覆盖率 88.8% <95% → 该行**仅作敏感性参考，不得单独作结论**。

### 4.4 敏感性表 B：ratio_store 阈值（覆盖率 95.1%/74.7%/44.6%）

| 臂 | t | rec (ctx) | prec (ctx) | rec (evi) | prec (evi) | any-overlap | truth 未映射率 |
|---|---:|---:|---:|---:|---:|---:|---:|
| M2 | 0.25 | 0.3163 | 0.0577 | 0.1974 | 0.2484 | 0.3933 | 0.0067 |
| M2 | 0.50 | 0.2811 | 0.0365 | 0.1911 | 0.1888 | 0.3200 | 0.1800 |
| M2 | 0.75 | 0.2044 | 0.0249 | 0.1244 | 0.1154 | 0.2267 | 0.4667 |
| arm1 | 0.25 | 0.3797 | 0.0643 | 0.2480 | 0.2898 | 0.4533 | 0.0067 |
| arm1 | 0.50 | 0.3411 | 0.0418 | 0.2411 | 0.2244 | 0.3733 | 0.1800 |
| arm1 | 0.75 | 0.2444 | 0.0290 | 0.1644 | 0.1411 | 0.2667 | 0.4667 |
| arm2 | 0.25 | 0.4412 | 0.0423 | 0.2791 | 0.3148 | 0.5267 | 0.0067 |
| arm2 | 0.50 | 0.3894 | 0.0270 | 0.2678 | 0.2352 | 0.4333 | 0.1800 |
| arm2 | 0.75 | 0.2728 | 0.0174 | 0.1811 | 0.1490 | 0.3000 | 0.4667 |

ratio_store ≥0.50 两档条件覆盖率 <95%（74.7%/44.6%），**不得作为主口径**。

### 4.5 一对多免疫指标：store-hit recall（ctx，ratio_runtime）

| 臂 | t=0.25 | t=0.50 | t=0.75 |
|---|---:|---:|---:|
| M2 | 0.3700 | 0.3567 | 0.3333 |
| arm1 | 0.4333 | 0.4167 | 0.3900 |
| arm2 | 0.4894 | 0.4694 | 0.4478 |

（store-hit = 每个 store truth chunk 只要任一映射 runtime 候选被命中即记 hit，不受一对多膨胀分母影响；930/1006 为一对多，故此列建议与 recall 并列报告。）

### 4.6 明确回答：桥接后是否还有可用 C1/C3 信号？

**有。** 覆盖率 1.00 ≥95%（允许宣称）；三臂在全部阈值/两种比值/两种检索口径下排序稳定（arm2 > arm1 > m2），且幅度显著高于 ID 碰撞值（evi-recall 从 0.0456 量级升至 0.19–0.27 量级）。**但**：(a) 旧 C1≥0.10 / C3≥0.0400 阈值在新口径下会被旧控制臂直接通过（arm2 t=0.50：recall 0.2510、precision 0.3494），失去区分力，必须重签；(b) 阈值选择必须附带 §4.3/4.4 敏感性与条件覆盖率标记，不得只挑一档作结论；(c) fabricated/retrieved_not_in_context 须在 capture 修复后重测方可入 C3。

---

## 5. §3.4 a′ baseline 审计（只报"能否精确重放"，不裁决 C1/C2/C3）

数据来源：`git show de8181f:results/answer-level/m6a-paired-2026-11-01/baseline-outcomes.jsonl`（分支 eval/m6a-paired-2026-11-01，head=8ffa3e0，抽至本目录 `_tmp-baseline-outcomes.jsonl`，150 行）。

| 指标 | 值 |
|---|---:|
| 例数 | 150 |
| context_chunk_ids_ordered 总数 | 3,108 |
| 可被 §2 runtime map 解析 | 3,108（**1.00**） |
| 逐例全解析 | 150/150 |
| full_sources = 纯 snippet 的例数 | **150/150** |
| full_sources 含完整 chunk 全文的例数 | 0 |
| snippet/全文判据不一致例数 | 0 |
| 例：case multi-011 | 25 chunk，full_sources 6,066 字符 vs 全文合计 22,267 字符（ratio 0.2724） |

chunk 级证据：2,238 个 >150 字符的长 chunk 均"snippet 在 full_sources 中、全文不在"；870 个 ≤150 字符短 chunk 被 snippet 平凡覆盖（150/150 例全部 snippet 齐备）。

**结论（仅重放性，不裁决指标）**：ordered ID 100% 可解析 → **可精确恢复 context 的"ID 序列"**；但 `full_sources` 只有每 chunk 前 150 字符的 snippet → **不能单凭 a′ 记录精确重放 context 文本**，全文必须取自 runtime map（或待修复后的 capture）。

---

## 6. §3.5 capture 缺口报告（只提方案，本轮不实施）

### 6.1 为什么 full_sources 不是完整 context

1. **渲染层截断**：`format_sources`（`src/rag.py:2141-2144`）每 chunk 只输出 `record.snippet`；而 snippet 构造于 `src/citations.py:39`：`snippet = documents[index].replace("\n", " ")[:150]` —— **仅前 150 字符且换行被替换**。
2. **字段层截断**：`evaluation/generation_runner.py:320` `context = sources[:500]` —— context 字段只存前 500 字符。
3. **full_sources 未修复**：`full_sources = _normalize_source_chunk_ids(sources)`（a′ runner L284/298）只归一了 chunk_id，底文仍是 snippet 拼接。
4. **实测**（§5）：150/150 例 full_sources 均为 snippet-only；首例全文覆盖率仅 27.2%。

因此 capture 里既没有完整 chunk 文本，也没有富化文档结构，context 无法精确重放。

### 6.2 eval-only 修复方案（建议，待 owner 授权后另行实施）

- **方案 A（推荐）**：在 evaluation 侧 `run_case` capture 时，用 `build_index` 已持有的 `self._all_docs`（`chunks_to_index_data` 的 texts）按 `context_chunk_ids` 顺序取出完整 chunk 文本，新增字段 `context_chunks_full: [{chunk_id, text}]`（ordered），与现有字段并存；只改 evaluation 序列化，**不改 `src/rag.py` 生产路径**。
- **方案 B**：把全量 enriched_docs/ordered chunk_texts 写入 sidecar 文件，outcomes 只存 sidecar SHA（避免 outcomes 膨胀）。
- 两者均为 eval-only、不触产品默认、不改冻结资产；实施前需 owner 明确授权，本轮**未实施**。

---

## 7. 建议的 Phase 2 口径

1. **域与桥**：C1/C3 定义在 runtime 域；truth 经 §3 桥映射（source+span，禁止 ID 映射），主口径 **t=0.50 / ratio_runtime**（条件覆盖率 98.5% ≥95%）；t=0.25 与 t=0.75（runtime）、ratio_store 三档一律附敏感性表与覆盖率标记（<95% 的行不得单独作结论）。
2. **指标列**：同时报告 ctx-based 与 evi-based 两口径，并**并列 store-hit recall**（一对多免疫）；分母仍冻结 150 例、逐例均值 round 4。
3. **阈值重签**：以本报告 §4 桥接后三臂数值为新基线重签 C1/C3 阈值与上界（旧 0.0456/0.10/0.0400/0.2067/U=21 全部作废——新口径下控制臂自身即 recall 0.2510、precision 0.3494，旧阈值无区分力）。
4. **前置条件**：任何依赖 context 文本/`retrieved_not_in_context`/fabricated 的裁决，必须先实施 §6 capture 修复并重跑 a′/新臂；a′ 现记录仅可作 ID 序列回放，不可作文本裁决。
5. **顺序**：Phase 2（口径重签 + capture 修复授权）→ 之后才谈 M6a 重启；**不得沿用旧预注册直接继续 M6a**。

---

## 8. 声明

- **未修改产品代码**：`src/`、`evaluation/`、`tests/`、`config`、`data/`、产品默认与冻结资产均未改动；本轮新增仅 `scripts/audit/*.py`（5 个审计脚本）与 `results/answer-level/chunk-domain-audit-2026-11-01/` 下产物。
- **未跑模型**：未调用 LLM、未联网、未跑 judge/al3、未重跑 M2/M4c/M6a；三臂数值均为旧 outcomes 的**离线复算**。
- **未 push、未 commit**；未更新 `docs/STATUS.md` 与 `CHANGELOG`。
- 真值（store chunks、v2.1 relevant_chunk_ids）仅在离线映射/复算脚本中读取，未写回产品、未用于调规则或阈值。
- 所有映射均以 source+字符 span 重叠或文本包含为证据，**未使用 ID 直接映射**。
