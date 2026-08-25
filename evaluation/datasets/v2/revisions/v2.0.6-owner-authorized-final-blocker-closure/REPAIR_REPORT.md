# v2.0.6 owner-authorized final blocker closure（REPAIR_REPORT）

这是所有者授权的确定性数据治理修复 candidate：不是人工审核、不是 active 版本、不是 overlay、不是 v2.1 准入。未调用 LLM/API、未联网。

- case 数：149 → 148（retire zh-032，原因固定 `no_directly_supported_answer_point_after_owner_authorized_review`，退役前已 fail-closed 检查无 follow-up/chain/doc_target 依赖）
- evidence 数：159 → 162（移除 5 条目标 case 旧证据行，新增 8 条 raw evidence）
- zh-035：启用 `multi_span_exact_evidence_v1`，写入全部 6 个 verbatim duplicate span（declared source 内 3 个 + 其他 source 3 个），无任选行为；跨 source scope 扩展显式记录为 `OWNER_AUTHORIZED_MULTI_SOURCE_EXACT_EVIDENCE_SCOPE_EXPANSION`；query 与答案点文本不变
- mixed-022：答案点收窄为「A function returning another function」（c9fd20815ea8_chunk_5 [18,55)），删除未获支持的「装饰器」答案点与 orphan evidence，仅保留唯一连续可重建 raw evidence
- mixed-028：删除无直接证据的答案点 0，答案点收窄为「state」（993955159403_chunk_7 [152,157)），删除 orphan evidence
- 4 条 blocker 全部关闭：remaining_blockers=0，无坐标 unresolved 残留记录；新增 evidence 全部通过 raw-codepoint-v1 严格校验
- 非目标行逐字节不变；输入 SHA 全部不变；两次构建逐字节一致；manifest 自哈希与磁盘 SHA 一致
- 剩余门禁：见 REVIEW_AND_SPLIT_REBUILD_REQUIRED.md；activation 保持 blocked。
