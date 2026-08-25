# v2.0.7 owner-authorized redundant legacy evidence retirement（REPAIR_REPORT）

这是所有者授权的确定性数据治理 candidate：不是人工审核、不是 active 版本、不是 overlay、不是 v2.1 准入。未调用 LLM/API、未联网。

- evidence 数：162 → 161，仅移除 1 条冗余 legacy coordinate evidence：`zh-037::32c427fb50e2_chunk_33::legacy`（历史展示文本「内置函数 dir() 用于查找模块定义的名称。返回结果是经过排序的字符串列表」，无 coordinate_contract，无法按 raw-codepoint-v1 严格校验）
- 退役原因（固定）：`redundant_legacy_coordinate_superseded_by_raw_codepoint_v1_evidence`
- 授权标识：`OWNER_AUTHORIZED_REDUNDANT_LEGACY_EVIDENCE_RETIREMENT`
- successor 证明：zh-037 保留同一答案点「经过排序的字符串列表」，由 `32c427fb50e2_chunk_32` `[1921,1931)` 的 strict raw-codepoint-v1 evidence （raw span == 答案点）覆盖；该 successor 自 v2.0.5 起逐字节存在
- 退役行承载的 legacy `char_range` 逐字保留于 retired-legacy-evidence.jsonl，不做任何 raw 坐标猜测/转换/重新解释
- draft 与 v2.0.6 draft-after 逐字节一致（148 case，case_id 唯一）；除该 legacy 行外，其余 161 行 evidence 逐字节不变
- 严格校验：raw-codepoint active evidence == 161，strict validator covered == 161、passed == 161、uncovered == 0、invalid == 0，legacy coordinate evidence == 0、unresolved == 0
- 输入 SHA 全部不变；两次构建逐字节一致；manifest 自哈希与磁盘 SHA 一致
- 剩余门禁：见 REVIEW_AND_SPLIT_REBUILD_REQUIRED.md；activation 保持 blocked。
