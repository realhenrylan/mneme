# v2.0.1 自动审阅 37 条阻断项：确定性根因分流与修复计划

> 只读分析任务：不修改 draft / chunks / 自动审阅 decision / pack / 任何 overlay 或历史产物；不进入 v2.1。

> 唯一事实来源：`automated-review.jsonl`（canonical，confirmed=113 / reject=20 / needs_followup=17，non-confirmed=37）。

## 分流总览

| 类别 | 计数 | 说明 |
|---|---|---|
| exact_local_evidence_available | 3 | 机械可修复：补/扩 evidence 表示（逐字 span） |
| partial_or_paraphrase_evidence_only | 18 | 需所有者裁决：收窄或核验改写/翻译 |
| no_local_evidence_found | 2 | 范围内无逐字证据：删除/建模/补文档需裁决 |
| refusal_label_or_schema_inconsistency | 13 | 字段级确定性矛盾：不改标签，需所有者批准 |
| semantic_judgment_unresolved | 1 | 证据已足，阻断为语义判断 |

- 机械可修复：3 条 （en-031, multi-020, zh-040）
- 需所有者裁决：34 条
- 未生成 overlay；gate 保持 BLOCKED；未进入 v2.1。

## 37 条逐条分流

| case_id | decision | 类别 | 子类 | 建议动作 |
|---|---|---|---|---|
| en-029 | needs_followup | partial_or_paraphrase_evidence_only | - | narrow_answer_point_or_verify_paraphrase |
| en-031 | reject | exact_local_evidence_available | evidence_gap | add_or_expand_evidence |
| en-034 | reject | semantic_judgment_unresolved | - | semantic_adjudication_required |
| en-041 | reject | partial_or_paraphrase_evidence_only | - | narrow_answer_point_or_verify_paraphrase |
| en-042 | reject | partial_or_paraphrase_evidence_only | - | narrow_answer_point_or_verify_paraphrase |
| en-044 | needs_followup | partial_or_paraphrase_evidence_only | - | narrow_answer_point_or_verify_paraphrase |
| en-048 | reject | partial_or_paraphrase_evidence_only | - | narrow_answer_point_or_verify_paraphrase |
| en-049 | needs_followup | partial_or_paraphrase_evidence_only | - | narrow_answer_point_or_verify_paraphrase |
| en-051 | needs_followup | partial_or_paraphrase_evidence_only | - | narrow_answer_point_or_verify_paraphrase |
| en-052 | reject | refusal_label_or_schema_inconsistency | refusal_assessment_conflict | fix_refusal_label_or_resolve_assessment |
| mixed-016 | reject | partial_or_paraphrase_evidence_only | - | narrow_answer_point_or_verify_paraphrase |
| mixed-027 | reject | refusal_label_or_schema_inconsistency | refusal_assessment_conflict | fix_refusal_label_or_resolve_assessment |
| mixed-029 | reject | partial_or_paraphrase_evidence_only | - | narrow_answer_point_or_verify_paraphrase |
| multi-018 | reject | partial_or_paraphrase_evidence_only | - | narrow_answer_point_or_verify_paraphrase |
| multi-019 | needs_followup | partial_or_paraphrase_evidence_only | - | narrow_answer_point_or_verify_paraphrase |
| multi-020 | reject | exact_local_evidence_available | evidence_gap | add_or_expand_evidence |
| multi-028 | reject | partial_or_paraphrase_evidence_only | - | narrow_answer_point_or_verify_paraphrase |
| noanswer-026 | reject | refusal_label_or_schema_inconsistency | missing_refusal_turn_label | fix_refusal_label_or_resolve_assessment |
| noanswer-029 | needs_followup | refusal_label_or_schema_inconsistency | missing_refusal_turn_label | fix_refusal_label_or_resolve_assessment |
| noanswer-030 | needs_followup | refusal_label_or_schema_inconsistency | missing_refusal_turn_label | fix_refusal_label_or_resolve_assessment |
| noanswer-031 | needs_followup | refusal_label_or_schema_inconsistency | missing_refusal_turn_label | fix_refusal_label_or_resolve_assessment |
| noanswer-032 | needs_followup | refusal_label_or_schema_inconsistency | missing_refusal_turn_label | fix_refusal_label_or_resolve_assessment |
| noanswer-037 | needs_followup | refusal_label_or_schema_inconsistency | missing_refusal_turn_label | fix_refusal_label_or_resolve_assessment |
| noanswer-040 | needs_followup | refusal_label_or_schema_inconsistency | missing_refusal_turn_label | fix_refusal_label_or_resolve_assessment |
| noanswer-044 | needs_followup | refusal_label_or_schema_inconsistency | missing_refusal_turn_label | fix_refusal_label_or_resolve_assessment |
| noanswer-045 | needs_followup | refusal_label_or_schema_inconsistency | missing_refusal_turn_label | fix_refusal_label_or_resolve_assessment |
| noanswer-052 | reject | refusal_label_or_schema_inconsistency | missing_refusal_turn_label | fix_refusal_label_or_resolve_assessment |
| noanswer-054 | needs_followup | refusal_label_or_schema_inconsistency | missing_refusal_turn_label | fix_refusal_label_or_resolve_assessment |
| zh-040 | reject | exact_local_evidence_available | evidence_gap | add_or_expand_evidence |
| zh-042 | needs_followup | partial_or_paraphrase_evidence_only | - | narrow_answer_point_or_verify_paraphrase |
| zh-045 | reject | no_local_evidence_found | zero_answer_points_modeling | remove_unsupported_point_or_rework_modeling |
| zh-046 | needs_followup | partial_or_paraphrase_evidence_only | - | narrow_answer_point_or_verify_paraphrase |
| zh-048 | reject | partial_or_paraphrase_evidence_only | - | narrow_answer_point_or_verify_paraphrase |
| zh-050 | reject | partial_or_paraphrase_evidence_only | - | narrow_answer_point_or_verify_paraphrase |
| zh-052 | reject | partial_or_paraphrase_evidence_only | - | narrow_answer_point_or_verify_paraphrase |
| zh-053 | needs_followup | partial_or_paraphrase_evidence_only | - | narrow_answer_point_or_verify_paraphrase |
| zh-056 | reject | no_local_evidence_found | zero_answer_points_modeling | remove_unsupported_point_or_rework_modeling |

## 机械可修复（补/扩 evidence）

| case_id | 答案点 | chunk_id | 字符范围 | 最短 span | 覆盖 | 动作 |
|---|---|---|---|---|---|---|
| en-031 | RFC 3986 | 86ef1bf559c5_chunk_6 | [75:83] | RFC 3986 | 100% | expand_snippet |
| multi-020 | createdb | 761b22915b5e_chunk_6 | [312:320] | createdb | 100% | expand_snippet |
| zh-040 | 输入与输出 | 32c427fb50e2_chunk_1 | [187:192] | 输入与输出 | 100% | expand_snippet |
| zh-040 | 错误和异常 | 32c427fb50e2_chunk_1 | [365:370] | 错误和异常 | 100% | expand_snippet |

## 需所有者裁决

- **partial_or_paraphrase_evidence_only**（18）：en-029, en-041, en-042, en-044, en-048, en-049, en-051, mixed-016, mixed-029, multi-018, multi-019, multi-028, zh-042, zh-046, zh-048, zh-050, zh-052, zh-053
- **no_local_evidence_found**（2）：zh-045, zh-056
- **refusal_label_or_schema_inconsistency**（13）：en-052, mixed-027, noanswer-026, noanswer-029, noanswer-030, noanswer-031, noanswer-032, noanswer-037, noanswer-040, noanswer-044, noanswer-045, noanswer-052, noanswer-054
- **semantic_judgment_unresolved**（1）：en-034


## 数据质量（等价确定性检查）

- completeness：canonical 150 / issues 37 / evidence 161 / draft 150 / chunks 1006；issues 集合 == non-confirmed 集合；canonical↔issues evidence_summary 0 差异
- uniqueness：case_id / chunk_id / evidence 行均唯一
- snippet 连续性：snippet/chunk SHA 全部自洽 （161/161）；char_range 切片与 snippet 文本完全一致 12/161 行
- source 一致性：evidence chunk↔source 一致、均在相关源/相关 chunk 内（{'evidence_source_matches_chunk': True, 'evidence_source_in_relevant_sources': True, 'evidence_chunk_in_relevant_chunks': True, 'relevant_chunk_ids_resolve': True, 'relevant_source_ids_resolve': True}）
- 答案点证据覆盖（37 条全部答案点）：{"exact": 7, "language_mismatch": 8, "none": 5, "partial": 26}
- skill 说明：data-analytics:analyze-data-quality skill 在本环境中不可用（不在已安装 skills 列表内），无法加载；已按任务约束实施等价的确定性质量检查（完整性 / 唯一性 / snippet 连续性 / source 一致性 / 答案点证据覆盖），全部为机械复算，无 LLM 参与。


## SHA 链

- canonical（automated-review.jsonl）：`ea2af431d7391bb8335086c673a7d4a4fea10b25601e9331a490f58a17af8224`
- evidence（automated-review-evidence.jsonl）：`af54ff88bd9384832593fd46301ef02bfd3408ed708508eec68dd5c7d8d1cbb9`
- issues（automated-review-issues.jsonl）：`f23a422effe8b53e57f2e0cd638c9ae76298efac0479f701fa4502ceb5cf55a7`
- manifest.json：`4e5d4079fff5c33a6819a70a191226e42781a559eaaee10a8743a2b38cfba123`
- draft（v2-cases-draft.jsonl）：`3c4fd10ad581cba478266efc02a7c6e57b899254b4e2fc7912f66eb5dba4efcc`
- chunks（chunks.jsonl）：`a23d739aa9876b54cd197d32f16138e9799c74a1a1c6717bb9d232fb6a06d772`

## 声明

- 未调用任何 LLM/API，未联网，未运行检索/生成/alpha/阈值评测
- 未修改任何输入数据（draft / chunks / 150 条 decision / evidence / issues / manifest）
- 未生成 overlay；gate 保持 BLOCKED；未进入 v2.1
- 未读取历史审阅结论；分流仅基于允许读取的 6 个输入文件
- 未 stage / commit / push
