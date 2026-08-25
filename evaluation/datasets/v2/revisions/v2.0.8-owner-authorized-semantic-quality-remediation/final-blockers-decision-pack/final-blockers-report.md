# final-blockers-report.md — v2.0.8 final blockers 决策包报告

> 只读、确定性；不修改任何 draft/evidence/chunks/review/candidate；
> 不调用 LLM/API、不联网；不自动选择任何选项。

## 门禁（fail-closed，全部通过）
- v2.0.8 candidate = 143 cases；strict raw-codepoint-v1 evidence 151/151（covered==passed）；legacy = 0；unresolved = 0
- multi-030 链关系精确：{"multi-031": ["follow_up_to"], "multi-032": ["chain_id"], "multi-033": ["chain_id"], "multi-034": ["chain_id"]}
- deferred ledger：['retirement_deferred_due_to_active_follow_up_chain_dependency']
- multi-030 与 multi-031~034 在 before→after 逐字节不变：True
- mixed-027 targeted re-review 事实：{"status": "TARGETED_REVIEW_OK", "decision": "reject", "ap0_assessment": "directly_supported", "ap1_assessment": "unsupported", "model": "deepseek-v4-pro"}

## 本地逐字重验（判定依据，非模型输出）

### multi-030
- `32c427fb50e2_chunk_3` / `python-tutorial-zh.md` / raw [0,65) / 重建 True；strict 命中 1 段（覆盖 0.78）；token 片段 13 段（最长连续 14 字符，覆盖 0.78）
- 源内完整 AP 命中 0 次（唯一 False）；最长连续子串『把 Python 当作计算器』出现 2 次

### mixed-027
- `8b191b241b93_chunk_1` / `sqlite-lang.md` / raw [75,213) / 重建 True；strict 命中 0 段（覆盖 0.00）；token 片段 0 段（最长连续 0 字符，覆盖 0.00）
- `c9fd20815ea8_chunk_2` / `python-glossary-zh.md` / raw [0,47) / 重建 True；strict 命中 0 段（覆盖 0.00）；token 片段 7 段（最长连续 5 字符，覆盖 0.38）
- 源内完整 AP 命中 0 次（唯一 False）；最长连续子串『』出现 0 次
- `8b191b241b93_chunk_1` / `sqlite-lang.md` / raw [75,213) / 重建 True；strict 命中 1 段（覆盖 0.29）；token 片段 14 段（最长连续 11 字符，覆盖 0.31）
- `c9fd20815ea8_chunk_2` / `python-glossary-zh.md` / raw [0,47) / 重建 True；strict 命中 0 段（覆盖 0.00）；token 片段 1 段（最长连续 2 字符，覆盖 0.06）
- 源内完整 AP 命中 0 次（唯一 False）；最长连续子串『begin-stmt』出现 1 次

## 选项核实结果（不自动选择）

### multi-030（deferred_chain_parent）
- ❌ `repair_in_place_with_direct_exact_evidence`
- ✅ `retire_entire_dependent_chain`：multi-030 与 multi-031~034 必须作为不可拆分组处理（5 case / 5 evidence / 5 answer points）；上游 multi-028 的 chain 成员将缺失，见 chain-impact-map.json
- ✅ `keep_deferred_and_block_fresh_review`：保持 v2.0.8 现状：multi-030 延后、draft/evidence 逐字节未改；这不是 resolved / confirmed / 已接受的质量结论；fresh review 需所有者另行授权
- recommendation：`None`（未选择）；需所有者决策

### mixed-027（targeted_re_review_reject）
- ❌ `remove_unsupported_answer_point_1`
- ❌ `repair_with_direct_exact_evidence`
- ✅ `keep_deferred_and_block_fresh_review`：保持 v2.0.8 现状：mixed-027 数据未改、targeted review 结果仅诊断；fresh review 需所有者另行授权
- recommendation：`None`（未选择）；需所有者决策

## 链影响（retire_entire_dependent_chain 影响图摘要）
- 不可拆分组：['multi-030', 'multi-031', 'multi-032', 'multi-033', 'multi-034']；case 5 / evidence 5 / answer points 5
- 组内引用 6 条；组外引用 0 条；受影响上游 chain：['multi-028']（成员缺失影响见 chain-impact-map.json）

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
    "options_total": 6
   },
   "uniqueness": {
    "case_ids_unique": true,
    "chain_case_ids_unique": true,
    "full_ap_hits_unique": true
   },
   "referential_integrity": {
    "chain_deps_exact": true,
    "deferred_ledger_exact": true,
    "evidence_spans_rebuildable": true,
    "evidence_sources_match_chunk": true,
    "upstream_impact_listed": true
   },
   "continuity": {
    "chain_cases_byte_identical": true,
    "v208_manifest_self_hash_ok": true,
    "inputs_sha_unchanged": true
   },
   "consistency": {
    "options_not_selected": true,
    "owner_decision_required": true,
    "decision_pack_rows": true,
    "no_model_output_as_fact": true
   }
  }

## 声明
- 未调用 LLM/API、未联网；未读取历史审阅结论 / split / dev / holdout / 锁配置 / 评测结果
- 未生成 after / overlay / active / split / locked / v2.1 产物；未修改 candidate 任何既有文件
- 未 stage / commit / push
