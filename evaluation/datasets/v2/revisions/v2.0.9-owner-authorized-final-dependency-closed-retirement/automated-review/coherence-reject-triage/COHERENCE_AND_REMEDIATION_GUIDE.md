# Coherence & Remediation Guide — v2.0.9 automated review

## 范围与边界

本目录由 `corpus_v2_v209_coherence_reject_triage.py` 确定性生成（只读、无 LLM、无联网）。
它是对 v2.0.9 fresh full blind automated review（gate=AUTOMATED_REVIEW_GATE_BLOCKED，
111 confirmed / 22 reject / 0 needs_followup / 4 errors）的**本地根因分流**，不是人工审核、
不是人工批准、不是 active 版本、不是 v2.1 准入。本目录不修改 candidate draft/evidence/
chunks/review，不生成 overlay。

## 一、分流一：model-output coherence errors（4 条）

目标：`en-052`、`mixed-030`、`mixed-033`、`multi-011`。

- 判定依据（契约层）：issue 记录为 `kind=error`、`attempts=4`、detail 为
  `reject/needs_followup without any disagreement`。该语义 = 本地校验器在 4 次重试中
  均未发现任何分歧（全部答案点 supported、refusal 一致），而统一 decision 契约要求
  此时 decision=confirmed；模型却输出 reject/needs_followup → 模型输出自相矛盾。
- 归类：一律 `model_output_contract_inconsistency`。
- 红线：**不得**把 error 改写为 confirmed/reject；**不得**重跑模型；**不得**写回 review。
  本任务只生成诊断与后续可选 recheck 规格（见 `owner-decision-template.jsonl`）。
- expected decision 的推导：契约层为 `confirmed`；证据层（本地 raw evidence 对答案点
  的确定性关系）作为辅助核验记录在 `answer_point_relations`。

## 二、分流二：substantive rejects（22 条）的分类定义

对每个 reject 的每个答案点，只基于 candidate 当前 raw evidence 与同 source chunk
原文做确定性分类：

| 分类 | 含义 | 机械判定信号 |
|---|---|---|
| `exact_evidence_present_but_review_semantic_disagrees` | 证据直接支撑答案点，分歧在 review 语义判断 | 规范化后答案点 ⊆ 证据 span（verbatim/containment） |
| `partial_or_paraphrase_only` | 证据仅部分支撑或为改写 | 最长公共连续子串 ≥ max(3, 0.10×较短文本长度)；或跨语言但答案点全部 ASCII 内容已被证据覆盖 |
| `same_source_scope_candidate_exists` | 当前证据未覆盖，但同 source 存在可证明候选 evidence | 原文/剥代码围栏/（跨语言时）最长未覆盖 ASCII token 命中同 source chunk 且不重叠现有 span |
| `translation_equivalence_requires_owner_policy` | 翻译等价性需 owner 政策裁定 | 答案点与证据跨语言、无原文候选（有 token 或共享数字） |
| `no_direct_support_in_declared_source` | 声明 source 中无直接支撑 | 无 containment、无同源候选、无有效共享 |
| `refusal_label_or_schema_inconsistency` | refusal 标签/schema 不一致 | 仅 refusal case 可能出现（本次 22 条全为 answerable，不出现） |
| `other_unresolved` | 其他未决 | 兜底 |

case 级分类 = 答案点分类中**证据最弱**者（severity：exact < partial < same-source <
translation < no-direct）。

**边界红线**：token 片段、跨 source 文本、模型解释或语义猜测一律不得标为 direct
evidence；候选 evidence 必须给出 chunk、Unicode `[start,end)`、raw span 与唯一性。

## 三、只读建议动作

| 动作 | 触发 | 含义 |
|---|---|---|
| `targeted_recheck_required` | case 级 exact / partial | 证据存在或部分存在，建议对模型判定做定向复审（不得自动确认） |
| `repair_candidate` | case 级 same-source | 存在可证明候选 evidence，建议 owner 授权后修复 evidence 分配 |
| `remove_answer_point` | no-direct 且非全部答案点无支撑 | 建议移除该无支撑答案点（需 owner 授权） |
| `retire_case` | 全部答案点 no-direct | 建议退役该 case（需 owner 授权） |
| `keep_unresolved` | translation / other / refusal | 保持未决，等待 owner 政策或人工判定 |

## 四、mixed-033 重复 evidence

两条 evidence 行字节级完全一致（同 chunk / 同 raw range / 同 raw span / 同 snippet
SHA / 同 source），均支撑同一保留答案点。删除任意一条在语义、答案点、source/chunk
关系上均可安全进行（144 → 143），但必须由 owner 明确授权并同步更新 manifest 计数
与 outputs SHA 后重跑 strict 校验。本任务只写建议，不修改数据。

## 五、owner 决策流程

1. 审阅 `reject-root-cause-triage.jsonl`（逐答案点明细）与 `review-coherence-errors.jsonl`。
2. 在 `owner-decision-template.jsonl` 每行的 `owner_decision` / `owner_reviewer` /
   `owner_notes` 填值（当前为空）。
3. 对 repair/remove/retire 动作：授权后在**新 revision** 中执行确定性修改并重跑
   strict 校验；对 recheck 动作：可发起一次全新盲态复审。
4. 任何动作完成前，v2.0.9 保持 CANDIDATE / activation_blocked / split_reseal_required。

## 六、统计守恒（预检 fail-closed）

- candidate：137 cases / 144 strict evidence（covered == passed == 144，legacy=0）。
- review canonical：111 confirmed + 22 reject + 0 needs_followup + 4 errors = 137；
  26 条 issue 的 case_id 无重复、无遗漏；无 overlay。
- candidate/review manifest 自哈希与输入输出 SHA 均一致；本任务前后输入 SHA 不变。
- 五维确定性检查（data-analytics skill 不可用，已记录）：完整性 / 唯一性 / 引用
  完整性 / 连续性 / 一致性全部通过。
