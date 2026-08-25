# OWNER_DECISION_GUIDE.md — v2.0.8 传递链闭包与退役决策指南

> 本包**只列出并核实选项，不自动选择、不自行采纳**。所有判定基于本地
> 机械复算（依赖图 / 传递闭包 / strict raw 逐字重验），不把模型输出
> 当作已采纳事实。任何选中动作均需所有者另行授权一个确定性执行步骤。

## 1. multi-030（deferred chain parent）传递链闭包

- 状态：v2.0.8 中因链依赖延后（`deferred-chain-dependent-cases.jsonl`），draft/evidence 逐字节未改；不是 resolved / confirmed / 已接受的质量结论。
- 直接下游（引用者）：`multi-031.follow_up_to -> multi-030`；`multi-032/033/034.chain_id -> multi-030`；下游传递闭包 = ['multi-031', 'multi-032', 'multi-033', 'multi-034']（无纯传递下游）。
- 上游可达（被引用方向）：['multi-015', 'multi-016', 'multi-018', 'multi-020', 'multi-022', 'multi-024', 'multi-025', 'multi-027', 'multi-028']；follow_up 父节点 = 无；同链成员（chain multi-028）= ['multi-031']；multi-030/031 自身是 chain multi-028 的成员。
- 最小无悬挂闭包 = ['multi-030', 'multi-031', 'multi-032', 'multi-033', 'multi-034']（multi-031.follow_up_to 与 multi-032/033/034.chain_id 强制其入组；multi-028 不引用组内 case，无需入组）。

退役场景（逐一核算）：

- `retire_only_multi_030`（❌ 不可执行（4 条悬挂引用））：cohort ['multi-030']；case 143→142、evidence 151→150、1 answer points；受影响 chain ['multi-028']
- `retire_multi030_to_multi034_group`（✅ 可执行（0 悬挂引用））：cohort ['multi-030', 'multi-031', 'multi-032', 'multi-033', 'multi-034']；case 143→138、evidence 151→146、5 answer points；受影响 chain ['multi-028', 'multi-030']
- `retire_minimal_dependency_closed_cohort`（✅ 可执行（0 悬挂引用））：cohort ['multi-030', 'multi-031', 'multi-032', 'multi-033', 'multi-034']；case 143→138、evidence 151→146、5 answer points；受影响 chain ['multi-028', 'multi-030']

选项（仅核实）：

- `keep_deferred_and_block_fresh_review`（✅ 条件成立）
  - 核实依据：保持 v2.0.8 现状：multi-030 延后、draft/evidence 逐字节未改；这不是 resolved / confirmed / 已接受的质量结论；fresh review 需所有者另行授权

- `retire_minimal_dependency_closed_cohort`（✅ 条件成立）
  - 核实依据：最小无悬挂闭包恰为 {multi-030..034}（与 5 组一致），0 悬挂引用；上游 chain multi-028 将失去全部成员（multi-030/031），chain multi-030 整链退役；143→138、evidence 151→146、5 answer points

- `retire_only_multi_030`（❌ 条件不成立）
  - 核实依据：{
     "dangling_ref_count": 4,
     "dangling_refs": [
      {
       "from": "multi-031",
       "to": "multi-030",
       "relation": "follow_up_to",
       "field_path": "metadata.follow_up_to"
      },
      {
       "from": "multi-032",
       "to": "multi-030",
       "relation": "chain_id",
       "field_path": "metadata.chain_id"
      },
      {
       "from": "multi-033",
       "to": "multi-030",
       "relation": "chain_id",
       "field_path": "metadata.chain_id"
      },
      {
       "from": "multi-034",
       "to": "multi-030",
       "relation": "chain_id",
       "field_path": "metadata.chain_id"
      }
     ],
     "case_count_after": 142,
     "note": "仅 retire multi-030 会留下 4 条悬挂引用（multi-031.follow_up_to 与 multi-032/033/034.chain_id 指向已退役 case），不可执行"
    }

## 2. mixed-027 安全退役核验

- 依赖事实：`follow_up_to` / `chain_id` / `doc_target` / `previous_turns` 均为空；无任何 case 引用它，它也不引用任何 case；非任何 chain 成员。
- 本地逐字事实（strict 口径，判定依据）：AP0『术语表：原子化操作不可再分』无完整连续逐字命中（仅 token 片段『原子化操作』/『不可再分』，最长连续覆盖 0.38 < 0.75）；AP1『SQLite 语法页仅列出 begin-stmt，未展开事务原子性说明』为负向元论述，仅『begin-stmt』token 命中，无完整逐字证据。两个答案点均无完整、唯一、连续、同 source 直接支持。

选项（仅核实）：

- `retire_single_case_safely`（✅ 条件成立）
  - 核实依据：mixed-027 无 follow-up/chain/previous_turn/doc_target/其他 case 引用依赖，退役不造成任何链断裂；143→142、evidence 151→149、2 answer points

- `keep_deferred_and_block_fresh_review`（✅ 条件成立）
  - 核实依据：保持 v2.0.8 现状：mixed-027 数据未改；这不是 resolved / confirmed / 已接受的质量结论；fresh review 需所有者另行授权

## 未来可授权选项（本包不自动采纳）

- 保持 `multi-030` deferred（现状）；
- retire 经证明的最小依赖闭包 `retire_minimal_dependency_closed_cohort`（{multi-030..034}，0 悬挂引用；上游 chain multi-028 失去全部成员）；
- 仅在安全时 retire `mixed-027`（`retire_single_case_safely=true`，143→142）；
- 保持 `mixed-027` deferred（现状）。

## 决策后如何执行

- 任何选中选项都**不会**在本包内执行；owner 决定后需另行授权一个确定性执行脚本（并重新走 fail-closed 门禁、split reseal、盲态复审）。
- 本包未生成 after / overlay / active / split / locked / v2.1 产物；未修改 candidate 任何既有文件；未调用 LLM/API、未联网。

授权标识：`OWNER_AUTHORIZED_CHAIN_CLOSURE_DECISION_AUDIT`；执行时间（确定性）：`2026-08-11T00:00:00+00:00`。
