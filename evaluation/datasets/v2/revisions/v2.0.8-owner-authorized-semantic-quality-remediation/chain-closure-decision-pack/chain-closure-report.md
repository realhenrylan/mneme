# chain-closure-report.md — v2.0.8 链闭包与退役审计报告

> 只读、确定性；不修改任何 draft/evidence/chunks/review/candidate；
> 不调用 LLM/API、不联网；不自动选择任何选项。

## 门禁（fail-closed，全部通过）
- v2.0.8 candidate = 143 cases；strict raw-codepoint-v1 evidence 151/151（covered==passed）；legacy = 0；unresolved = 0
- multi-030 链关系精确：{"multi-031": ["follow_up_to"], "multi-032": ["chain_id"], "multi-033": ["chain_id"], "multi-034": ["chain_id"]}
- multi-030 自身关系：follow_up_to = None、chain_id = multi-028（multi-031 同链）
- mixed-027 隔离：{"follow_up_to": null, "chain_id": null, "doc_target": null, "previous_turns": null, "incoming_refs": [], "outgoing_refs": []}
- deferred ledger：['retirement_deferred_due_to_active_follow_up_chain_dependency']（dependent_cases 与图引用一致）
- multi-030 与 multi-031~034 在 before→after 逐字节不变：True
- 图引用完整性：全部 case-id 字段引用指向存在的 case；无多节点环；自环仅 chain root 自标号（multi-011、multi-015，良性）

## 依赖图与传递闭包（multi-030）
- 全图：143 nodes / 39 edges（follow_up_to 15、chain_id 24、doc_target 0、previous_turns 0）
- 下游（引用者方向）：direct {"multi-031": ["follow_up_to"], "multi-032": ["chain_id"], "multi-033": ["chain_id"], "multi-034": ["chain_id"]}；transitive {}
- 上游（被引用方向）：direct {"multi-028": ["chain_id"]}；transitive {"multi-015": ["chain_id"], "multi-016": ["chain_id"], "multi-018": ["chain_id"], "multi-020": ["chain_id"], "multi-022": ["chain_id"], "multi-024": ["follow_up_to"], "multi-025": ["chain_id"], "multi-027": ["follow_up_to"]}
- follow_up 父节点：None；同链成员：['multi-031']（chain multi-028）

## multi-030 退役场景核算

- `retire_only_multi_030`（❌ 不可执行（4 条悬挂引用））：cohort ['multi-030']；case 143→142、evidence 151→150、1 answer points；受影响 chain ['multi-028']
  - 悬挂引用：[{"from": "multi-031", "to": "multi-030", "relation": "follow_up_to", "field_path": "metadata.follow_up_to"}, {"from": "multi-032", "to": "multi-030", "relation": "chain_id", "field_path": "metadata.chain_id"}, {"from": "multi-033", "to": "multi-030", "relation": "chain_id", "field_path": "metadata.chain_id"}, {"from": "multi-034", "to": "multi-030", "relation": "chain_id", "field_path": "metadata.chain_id"}]
  - 链影响：{"multi-028": {"members": ["multi-030", "multi-031"], "retired_members": ["multi-030"], "remaining_members": ["multi-031"], "status": "partially_retired"}}
- `retire_multi030_to_multi034_group`（✅ 可执行（0 悬挂引用））：cohort ['multi-030', 'multi-031', 'multi-032', 'multi-033', 'multi-034']；case 143→138、evidence 151→146、5 answer points；受影响 chain ['multi-028', 'multi-030']
  - 链影响：{"multi-028": {"members": ["multi-030", "multi-031"], "retired_members": ["multi-030", "multi-031"], "remaining_members": [], "status": "fully_retired"}, "multi-030": {"members": ["multi-032", "multi-033", "multi-034"], "retired_members": ["multi-032", "multi-033", "multi-034"], "remaining_members": [], "status": "fully_retired"}}
- `retire_minimal_dependency_closed_cohort`（✅ 可执行（0 悬挂引用））：cohort ['multi-030', 'multi-031', 'multi-032', 'multi-033', 'multi-034']；case 143→138、evidence 151→146、5 answer points；受影响 chain ['multi-028', 'multi-030']
  - 链影响：{"multi-028": {"members": ["multi-030", "multi-031"], "retired_members": ["multi-030", "multi-031"], "remaining_members": [], "status": "fully_retired"}, "multi-030": {"members": ["multi-032", "multi-033", "multi-034"], "retired_members": ["multi-032", "multi-033", "multi-034"], "remaining_members": [], "status": "fully_retired"}}

## mixed-027 安全退役核验
- 依赖事实：{"follow_up_to": null, "chain_id": null, "doc_target": null, "previous_turns": null, "incoming_case_refs": [], "outgoing_case_refs": [], "chain_membership": null, "n_answer_points": 2, "n_evidence": 2}
- retire_single_case_safely = True（case 143→142、evidence 151→149、2 answer points）
- 答案点 strict 重验（判定依据，非模型输出）：
- AP0『术语表：原子化操作不可再分』：direct_strict_support=False；best evidence c9fd20815ea8_chunk_2 strict 覆盖 0.00、最长连续覆盖 0.38、仅 token 片段；源内完整 AP 命中 0 次
- AP1『SQLite 语法页仅列出 begin-stmt，未展开事务原子性说明』：direct_strict_support=False；best evidence 8b191b241b93_chunk_1 strict 覆盖 0.29、最长连续覆盖 0.31、仅 token 片段；源内完整 AP 命中 0 次

## 选项核实结果（不自动选择）

### multi-030（deferred_chain_parent）
- ✅ `keep_deferred_and_block_fresh_review`：保持 v2.0.8 现状：multi-030 延后、draft/evidence 逐字节未改；这不是 resolved / confirmed / 已接受的质量结论；fresh review 需所有者另行授权
- ✅ `retire_minimal_dependency_closed_cohort`：最小无悬挂闭包恰为 {multi-030..034}（与 5 组一致），0 悬挂引用；上游 chain multi-028 将失去全部成员（multi-030/031），chain multi-030 整链退役；143→138、evidence 151→146、5 answer points
- ❌ `retire_only_multi_030`
- recommendation：`None`（未选择）；需所有者决策

### mixed-027（retirement_safety_check）
- ✅ `retire_single_case_safely`：mixed-027 无 follow-up/chain/previous_turn/doc_target/其他 case 引用依赖，退役不造成任何链断裂；143→142、evidence 151→149、2 answer points
- ✅ `keep_deferred_and_block_fresh_review`：保持 v2.0.8 现状：mixed-027 数据未改；这不是 resolved / confirmed / 已接受的质量结论；fresh review 需所有者另行授权
- recommendation：`None`（未选择）；需所有者决策

## 链影响（最小闭包退役影响图摘要）
- 退役 cohort：['multi-030', 'multi-031', 'multi-032', 'multi-033', 'multi-034']；case 5 / evidence 5 / answer points 5；case 138、evidence 146
- 组内引用 6 条；组外引用 2 条（multi-030/031.chain_id → multi-028）；悬挂引用 0 条
- 受影响上游 chain：['multi-028', 'multi-030']（chain multi-028 失去全部成员 multi-030/031；chain multi-030 整链退役；case multi-028 本身属于 chain multi-025，不受影响）

## 数据质量（等价确定性五维检查）
- {
   "completeness": {
    "candidate_case_count": 143,
    "candidate_evidence_count": 151,
    "strict_validation": "151/151 PASS",
    "blockers": [
     "multi-030",
     "mixed-027"
    ],
    "scenarios_total": 3,
    "options_total": 5
   },
   "uniqueness": {
    "case_ids_unique": true,
    "cohort_unique": true,
    "edges_unique": true
   },
   "referential_integrity": {
    "all_edge_targets_exist": true,
    "dangling_refs_in_candidate": 0,
    "deferred_ledger_exact": true,
    "case_id_doc_target_refs": 0,
    "previous_turns_refs": 0,
    "evidence_spans_rebuildable": true,
    "mixed027_isolated": true
   },
   "continuity": {
    "chain_cases_byte_identical": true,
    "v208_manifest_self_hash_ok": true,
    "inputs_sha_unchanged": true,
    "deterministic": true
   },
   "consistency": {
    "options_not_selected": true,
    "owner_decision_required": true,
    "template_rows": 2,
    "no_model_output_as_fact": true,
    "retire_single_case_safely_consistent": true
   }
  }

## 声明
- 未调用 LLM/API、未联网；未读取历史审阅结论 / split / dev / holdout / 锁配置 / 评测结果
- 未生成 after / overlay / active / split / locked / v2.1 产物；未修改 candidate 任何既有文件
- 未 stage / commit / push
