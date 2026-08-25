# v2.0.4 所有者决策指南

本包不修改任何 v2 数据，不生成 after/overlay/active 文件，不进入 v2.1。
可行动作含义：
- remove_answer_point：删除无 scoped 原文证据的答案点及其关联证据；若可答 case 为零答案点则标记 zero_answer_point_risk。
- replace_answer_point_with_exact_raw_text：用选定 anchor 的原始连续文本完整替换答案点，不改写其他字段。
- narrow_answer_point_to_exact_raw_text：把答案点收窄为选定 anchor 的原文，不改变其余答案点。
- add_new_document_then_reannotate：在新增文档并建立 chunk 后再重新标注，不改变当前 scope。
- expand_evidence_scope_with_explicit_approval：把同 source 其他 chunk 作为未来证据范围，仍需显式授权。
- retire_case：整体退役该 case，不影响其他 case。

所有动作均不修改 draft/evidence/chunks/revision，不创建 refusal 建议（除非 case 原本就是 refusal）。
