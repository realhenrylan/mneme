# Mneme 评测语料 v2 验收 checklist

> 配合 `plans/CORPUS-EXPANSION-PLAN-2026-08-05.md`（主方案）与
> `plans/CORPUS-V2-ANNOTATION-TEMPLATE.md`（标注模板）使用。
> 逐阶段验收：**任一检查项失败 → 该阶段不通过，不进入下一阶段**；
> 失败动作须记录在案（证据文件 + 修复 + 复检）。
> 本文件为只读设计，实施时逐项执行。

---

## 阶段 1：文档准入

| # | 检查项 | 通过标准 | 失败动作 | 证据 |
|---|---|---|---|---|
| 1.1 | 来源与许可证 | 每篇文档有 source_url（或授权说明）+ license（SPDX 或 URL）+ obtained_date；无抓取/无许可证/付费/机密内容 | 剔除该文档；补充授权后复检 | corpus-manifest.json |
| 1.2 | 内容指纹 | 每篇 file_sha256 已计算并与 manifest 一致（复算比对） | 重新计算；不一致则拒绝 | corpus-manifest.json |
| 1.3 | 敏感信息 | 凭据类 0 命中；个人数据已脱敏或排除（用户决定记录） | 拒绝入库 / 脱敏后复检 | 扫描报告（记录于 manifest） |
| 1.4 | 精确去重 | 无重复 SHA-256 文档（alias 已记录） | 保留一份，记录 alias | manifest dup 记录 |
| 1.5 | 近重复 | 文档级 5-gram Jaccard ≥0.85 对已人工判定（合并/剔除/记录） | 人工裁决 | 近重复报告 |
| 1.6 | 最小正文质量 | 有效文本 ≥800 字符；无乱码/控制字符；结构信号达标；语言与申报一致 | 剔除或修复后复检 | 质量扫描记录 |
| 1.7 | 解析成功率 | 逐文档判定通过（PDF 无文本页 ≤10%；DOCX/MD/HTML 结构完整） | 修复解析后随下一小版本 | 解析报告（含 parser 版本） |
| 1.8 | 数量与构成 | 新增 8–16 篇；zh 3–4 / en 5–7 / mixed 1–2；≥1 个同主题新集群；≥1 篇含版本/日期信息 | 补齐构成 | corpus-manifest.json |

**阶段产出**：`evaluation/datasets/v2/corpus-manifest.json`（v2.0.0）

## 阶段 2：索引与分块

| # | 检查项 | 通过标准 | 失败动作 | 证据 |
|---|---|---|---|---|
| 2.1 | chunk 长度 | ≥90% 在 200–600 字符；<100 或 >1200 ≤5%（豁免注明） | 调整分块参数后重分 | chunk-manifest.json |
| 2.2 | chunk 完整性 | 无截断句子/表格；不跨标题边界；标题归属唯一 | 修复后重分 | 分块报告 |
| 2.3 | chunk 溯源 | 每 chunk 有 source、标题路径、序号、页码（PDF） | 补全元数据 | chunk-manifest.json |
| 2.4 | chunk 编码 | UTF-8 合法、无控制字符 | 修复后重分 | 扫描记录 |
| 2.5 | 人工抽检 | 每文档 ≥20 chunk（不足全检）可读性 100% | 修复问题 chunk 后复检 | 抽检记录 |
| 2.6 | chunk 指纹 | chunks.jsonl + chunk-manifest.json 生成，SHA-256 校验通过 | 重新生成 | chunk-manifest.json |

**阶段产出**：`data/v2-corpus/chunks/chunks.jsonl` + `chunk-manifest.json`

## 阶段 3：用例构造与标注

| # | 检查项 | 通过标准 | 失败动作 | 证据 |
|---|---|---|---|---|
| 3.1 | 规模与分层 | 新 150 ±10%；zh/en/mixed = 60/60/30；六类分布符合 §3.3；每有效层 ≥5 | 补足缺口层 | 分布统计 |
| 3.2 | band_target 构成 | low_answerable 18–22 / low_refuse 18–22 / near_band 15–20 | 调整构造 | 分布统计 |
| 3.3 | 多轮链 | ≥8 条链（≥24 轮，链长 2–5）；跨文档链 ≥2；含拒答轮链 ≥1；链完整 | 补建/修复链 | 链统计 |
| 3.4 | 难度分布 | 全池 hard ≥25%（新 hard ≥52）；easy/medium/hard ≈ 40/35/25 | 补充 hard 构造 | 分布统计 |
| 3.5 | schema 合法组合 | §3 组合表全成立；chunk_id ⊆ manifest；no_answer 全空规则成立 | 逐条修复（fail-closed） | 校验器输出 |
| 3.6 | source-only | ≤10% 新增；每条 review_notes 有理由；能定位的未降级为 source | 补标 chunk 或剔除 | 校验器输出 |
| 3.7 | id 冻结登记 | id 唯一、已登记 case-freeze 清单、prefix 序号连续 | 修正后重新冻结 | case-freeze.json |

**阶段产出**：`evaluation/datasets/v2/annotations/annotation-pack-*.jsonl`

## 阶段 4：审核与 ground truth 锁定

| # | 检查项 | 通过标准 | 失败动作 | 证据 |
|---|---|---|---|---|
| 4.1 | 终审 | 100% review_status=approved；revise/reject 均有意见且已闭环 | 继续修正循环 | annotation packs |
| 4.2 | IAA（双人模式） | should_refuse κ ≥0.85；source 一致率 ≥90%；chunk 一致率 ≥80%；分歧 100% 裁决 | 复核分歧后复评 | IAA 报告 |
| 4.3 | 链审核 | 链内全部 approved 才允许锁定 | 继续修正 | annotation packs |
| 4.4 | GT 指纹 | gt-v2.jsonl + gt-manifest.json（SHA-256、审核统计、变更历史）生成并通过复算 | 重新生成 | gt-manifest.json |
| 4.5 | GT 不可变 | 锁定后修改走 change request（diff + 理由 + 新指纹） | 恢复锁定版本，走变更流程 | gt-manifest.json 变更历史 |

**阶段产出**：`evaluation/datasets/v2/gt-v2.jsonl` + `gt-manifest.json`

## 阶段 5：划分冻结（holdout 封印）

| # | 检查项 | 通过标准 | 失败动作 | 证据 |
|---|---|---|---|---|
| 5.1 | 冻结输入 | case-freeze.json：全池 id 有序列表 + SHA-256；旧 110 标记 legacy_dev/explored | 修正后重新冻结 | case-freeze.json |
| 5.2 | 分组 | 链闭包正确、链不跨 split；单例组 1 例 | 修正分组 | 分组表（含于冻结） |
| 5.3 | 分层采样 | 每层（18 层）holdout ≥1 组（n_groups≥2 时）；占比 ∈[0.22, 0.30]；holdout ∩ 旧 110 = ∅ | 换 seed 重划并记录 | 每层计数表 |
| 5.4 | 指纹锁定 | split_fingerprint 已计算；split-lock.json 不含 holdout id 列表 | 重新生成 | split-lock.json |
| 5.5 | 复现性 | 同一输入 + seed + splitter_version 重算指纹一致（跨进程） | 修复 splitter | verify_lock 输出 |
| 5.6 | holdout 纯净 | 阶段 A 起无任何 v2 case 的检索分数/特征被查看（记录审计日志） | 中止，重新设计 | 审计日志 |

**阶段产出**：`evaluation/datasets/v2/split/case-freeze.json` + `split-lock.json`

## 阶段 6：规则选择与 holdout 确认（未来，属 §5.4 协议）

| # | 检查项 | 通过标准 | 失败动作 | 证据 |
|---|---|---|---|---|
| 6.1 | 分析守卫 | 全部分析产物（features.jsonl 等）无 holdout id；写入前 fail-closed 校验 | 修正流水线后重跑 | check_artifact_ids 输出 |
| 6.2 | 嵌套 GroupKFold | 5 折、按链分组；每折训练折选规则 → 验证折评估；方向一致 | 报告折内方差，不进入确认 | CV 报告 |
| 6.3 | dev 低分带校准 | 仅 dev 侧扫描；落带情况记录；构造调整走变更流程 | 不触碰 holdout | v2.1 扫描轮记录 |
| 6.4 | 一次性确认 | 重算 holdout ids → 指纹一致 → 锁定规则评估一次 | 指纹不一致 → 中止；评估后不得再调规则 | holdout-confirmation.json + 报告 |

**阶段产出**：`results/graph-gate/corpus-v2-<ts>/` 下确认报告

---

## 数值门槛汇总（速查）

| 指标 | 门槛 |
|---|---|
| 新增文档 | 8–16 篇（zh 3–4 / en 5–7 / mixed 1–2） |
| 新增用例 | 150 ±10%（全池 ≈260） |
| 语言 | zh/en/mixed = 60/60/30 |
| should_refuse | 全池 55（21%）；dev 40–42（含旧 22）；holdout 10–12 |
| 前哨 FR | dev ≥12–15；holdout ≥5 |
| 交织带样本 | dev ≥30（可回答 ≥15 / 应拒答 ≥15）；近带 ≥15 |
| 多轮链 | ≥8 条新链（≥24 轮）；跨文档链 ≥2；拒答轮链 ≥1 |
| hard | 全池 ≥25%（新 ≥52） |
| source-only | ≤10% 新增，每条有理由 |
| chunk 长度 | ≥90% ∈ [200, 600] 字符；异常 ≤5% |
| 近重复 | 文档级 Jaccard ≥0.85 → 人工裁决 |
| holdout 占比 | 新池的 25–30%（38–45 例） |
| G2（未来） | 新放行 SR ≤ 10% × 该 split 全部 SR |
