# v2.0.5 remaining-four blocker 所有者决策指南

本包是只读、确定性、离线的所有者决策包：不调用 LLM/API、不联网、不修改任何 draft/evidence/chunks/revision，不生成 overlay/active 指针，不重封 split，不进入 v2.1。包内任何动作都不会被自动采用；所有动作均需所有者显式选择，并填写 candidate-patch-template.jsonl 中的 owner_decision / owner_reviewer / owner_notes 字段。

动作含义：
- keep_unresolved：保持现状（case 继续 unresolved），不修改任何数据。
- retire_case：整体退役该 case；case 退出语料，不产生零答案点 case。
- remove_unsupported_answer_point：删除无 exact 证据支持的答案点（unsupported 标记见 remaining-blockers-decision-pack.jsonl）；若删除后剩余 0 个答案点，则标记 zero_answer_point_risk=true。
- narrow_answer_point_to_exact_raw_text：把指定答案点收窄为 narrow_candidates 中的 exact raw 原文（均满足 chunk_text[start:end]==raw_span），不改变其余答案点。仅当存在完整、唯一、连续的 exact raw clause 时才提供该动作。
- retain_all_exact_duplicate_spans_with_explicit_multi_span_policy：把全部完全相同的 verbatim duplicate span 一并保留为证据，并采用显式 multi-span evidence policy。这是需所有者批准的新 evidence policy，不能自动采用；未获批前不得把任一 span 单独当作唯一证据。

各 case 特别说明：
- zh-035：答案点 fibo.py 在语料中 verbatim 出现 6 次（declared source 内 3 次），全部可重建；不允许任选一个；仅允许 keep_unresolved / retain_all_exact_duplicate_spans_with_explicit_multi_span_policy / retire_case 三个动作。
- zh-032：复核确认无 full/clause 级 exact 证据（仅碎片级原文，见 fragment_matches，按 fail-closed 规则不得当作 exact 证据）；仅允许 remove_unsupported_answer_point / retire_case / keep_unresolved。
- mixed-022 / mixed-028：存在完整、唯一、连续的 exact raw clause 的答案点才提供 narrow 动作；其余答案点不得把 paraphrase 当作 exact evidence，仅提供 remove_unsupported_answer_point / retire_case / keep_unresolved。
