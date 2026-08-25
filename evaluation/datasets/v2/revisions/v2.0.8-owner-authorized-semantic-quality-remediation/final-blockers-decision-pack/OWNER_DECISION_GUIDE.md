# OWNER_DECISION_GUIDE.md — v2.0.8 final blockers 所有者决策指南

> 本包**只列出并核实选项，不自动选择、不自行采纳**。所有判定基于本地
> raw 逐字重验（`raw-evidence-verification.json`），不把模型输出当作
> 已采纳事实。任何选中动作均需所有者另行授权一个确定性执行步骤。

## 两个阻断项

### 1. multi-030（deferred chain parent）

- 状态：v2.0.8 中因链依赖延后（`deferred-chain-dependent-cases.jsonl`），draft/evidence 逐字节未改；不是 resolved / confirmed / 已接受的质量结论。
- 链关系（fail-closed 核实）：`multi-031.follow_up_to == "multi-030"`，`multi-032/033/034.chain_id == "multi-030"`；无其他引用。
- 本地逐字事实：当前答案点『数字（把 Python 当作计算器）』为组合式文本，声明 source（python-tutorial-zh.md）内**无完整逐字命中**；最长连续子串『把 Python 当作计算器』出现 2 次（32c427fb50e2_chunk_2 [1824:1838) 与 chunk_3 [31:45)），**不唯一**。

选项（仅核实）：

- `repair_in_place_with_direct_exact_evidence`（❌ 条件不成立）
  - 核实依据：{
     "full_ap_verbatim_hits_in_source": 0,
     "longest_substring_text": "把 Python 当作计算器",
     "longest_substring_occurrences": 2,
     "longest_substring_unique": false,
     "in_evidence_strict_coverage": 0.7778,
     "note": "当前答案点是组合式文本（'数字（把 Python 当作计算器）'），声明 source 内无完整逐字命中；最长连续子串『把 Python 当作计算器』出现 2 次，不唯一；strict 口径下不存在可唯一、连续、直接支撑的 raw evidence"
    }

- `retire_entire_dependent_chain`（✅ 条件成立）
  - 核实依据：multi-030 与 multi-031~034 必须作为不可拆分组处理（5 case / 5 evidence / 5 answer points）；上游 multi-028 的 chain 成员将缺失，见 chain-impact-map.json

- `keep_deferred_and_block_fresh_review`（✅ 条件成立）
  - 核实依据：保持 v2.0.8 现状：multi-030 延后、draft/evidence 逐字节未改；这不是 resolved / confirmed / 已接受的质量结论；fresh review 需所有者另行授权

### 2. mixed-027（targeted re-review reject）

- 状态：v2.0.8 定向盲态复审（deepseek-v4-pro，Pro-only 契约）结果`reject`（AP0 directly_supported、AP1 unsupported）——仅事实记录。
- 本地逐字事实（判定依据）：AP0『术语表：原子化操作不可再分』在 evidence span 内无 strict 连续逐字命中（最长连续段『原子化操作』6 字符，覆盖 0.46 < 0.75；另有『不可再分』4 字符，均为 token 级片段）；AP1『SQLite 语法页仅列出 begin-stmt，未展开事务原子性说明』为负向元论述，声明 source 内仅『begin-stmt』token 命中，无完整逐字证据。

选项（仅核实）：

- `remove_unsupported_answer_point_1`（❌ 条件不成立）
  - 核实依据：{
     "ap0_strict_contiguous_support": false,
     "ap0_strict_coverage": 0.0,
     "ap0_max_contiguous_coverage": 0.3846,
     "ap0_token_level_fragments": true,
     "ap0_token_fragments_detail": [
      {
       "text": "原子化操作",
       "ap_range": [
        4,
        9
       ],
       "span_range": [
        20,
        25
       ],
       "length": 5
      },
      {
       "text": "子化操作",
       "ap_range": [
        5,
        9
       ],
       "span_range": [
        21,
        25
       ],
       "length": 4
      },
      {
       "text": "化操作",
       "ap_range": [
        6,
        9
       ],
       "span_range": [
        22,
        25
       ],
       "length": 3
      },
      {
       "text": "操作",
       "ap_range": [
        7,
        9
       ],
       "span_range": [
        23,
        25
       ],
       "length": 2
      },
      {
       "text": "不可再分",
       "ap_range": [
        9,
        13
       ],
       "span_range": [
        35,
        39
       ],
       "length": 4
      },
      {
       "text": "可再分",
       "ap_range": [
        10,
        13
       ],
       "span_range": [
        36,
        39
       ],
       "length": 3
      },
      {
       "text": "再分",
       "ap_range": [
        11,
        13
       ],
       "span_range": [
        37,
        39
       ],
       "length": 2
      }
     ],
     "non_zero_answer_points_after": true,
     "note": "删除 AP1 后 AP0 仍无 strict 连续逐字支撑（span 内最长连续段覆盖 0.38 < 0.75，仅 token 级片段）；不会形成零答案点，但 strict 条件不满足"
    }

- `repair_with_direct_exact_evidence`（❌ 条件不成立）
  - 核实依据：{
     "full_ap_verbatim_hits_in_source": 0,
     "longest_substring_text": "begin-stmt",
     "longest_substring_occurrences": 1,
     "longest_substring_unique": true,
     "note": "AP1 是对文档的负向元论述（'仅列出'/'未展开事务原子性说明'），声明 source 内仅 token『begin-stmt』逐字命中，无唯一完整逐字证据；不允许语义猜测或跨 source 扩展"
    }

- `keep_deferred_and_block_fresh_review`（✅ 条件成立）
  - 核实依据：保持 v2.0.8 现状：mixed-027 数据未改、targeted review 结果仅诊断；fresh review 需所有者另行授权

## 决策后如何执行

- 任何选中选项都**不会**在本包内执行；owner 决定后需另行授权一个确定性执行脚本（并重新走 fail-closed 门禁、split reseal、盲态复审）。
- 本包未生成 after / overlay / active / split / locked / v2.1 产物；未修改 candidate 任何既有文件；未调用 LLM/API、未联网。

授权标识：`OWNER_AUTHORIZED_FINAL_BLOCKERS_DECISION_PACK`；执行时间（确定性）：`2026-08-11T00:00:00+00:00`。
