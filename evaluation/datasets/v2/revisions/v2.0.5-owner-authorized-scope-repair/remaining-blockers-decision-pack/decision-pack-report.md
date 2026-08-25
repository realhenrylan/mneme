# v2.0.5 remaining-four blocker 决策包报告
这是只读、确定性、离线决策包：不是修复、不是人工审核、不是 active 版本、不是 overlay、不是 v2.1 准入；不生成 after 文件、不重封 split、不调用 LLM/API。
- 目标：4 条（zh-035 / zh-032 / mixed-022 / mixed-028）
- exact raw 证据发现：3 条 case
  - zh-035：fibo.py 语料级 verbatim 6 个 duplicate span（declared source 内 3 个），全部可重建，multi-span policy 需所有者批准。
  - mixed-022：答案点 0 存在唯一 exact clause「A function returning another function」（c9fd20815ea8_chunk_5 [18,55)）。
  - mixed-028：答案点 1 存在唯一 exact clause「state」（993955159403_chunk_7 [152,157)，位于该 case 已有证据 scope）。
  - zh-032：复核确认无 full/clause 级 exact 证据；仅碎片级原文「异常实例」「一起被引发」（fragment_matches），按 fail-closed 规则不得标为 exact。
- 零答案点风险：1 条 case 存在风险动作（zh-032 的 remove_unsupported_answer_point 为 True；其余为 False）。
- narrow 候选 case：2 条（mixed-022、mixed-028），候选 span 见 remaining-blockers-decision-pack.jsonl。
- 输入/输出 SHA：见 manifest.json（自哈希与磁盘文件 SHA 一致）。
