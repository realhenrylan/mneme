# v2.0.6 candidate evidence-count reconciliation

只读对账：不改写任何 v2.0.6 candidate 数据、不调用 LLM/API/联网、不读取 split/dev/holdout/锁配置；不生成 overlay/active/v2.1/review/split/locked config。

- 行数复算：evidence-before=159、evidence-after=162、retired-evidence=1
- 算式：159 - 5 + 8 = 162，精确成立（数值 + 集合身份双重验证）：移除目标旧行 5 条（4 条目标 case 的旧 evidence，其中 zh-032 的 1 条进入 retired-evidence），新增 raw evidence 8 条（zh-035 六条 multi-span + mixed-022 一条 + mixed-028 一条）
- 162 与 161 差异解释：evidence-after 共 162 条 = 161 条 raw-codepoint-v1 active + 1 条 legacy coordinate（zh-037 保留的历史 legacy 行，无 coordinate_contract，按契约不在 strict validator 输入集合内）；unresolved/non-active 0 条、malformed 0 条
- strict validator：输入集合 161 条，通过 161 条，失败 0 条，未覆盖 1 条
- raw span 检查：覆盖行 161 条全部满足 chunk_text[start:end]==raw_evidence_span 及 source/chunk/SHA/range 边界校验；legacy 跳过 1 条
- 非严格合法行 1 条：zh-037（32c427fb50e2_chunk_33，legacy_coordinate，no coordinate_contract; retained historical legacy coordinate evidence outside raw-codepoint-v1 (not strict-validatable by contract)）
- 目标行覆盖：zh-035 {'rows': 6, 'covered': 6, 'passed': 6}、mixed-022 {'rows': 1, 'covered': 1, 'passed': 1}、mixed-028 {'rows': 1, 'covered': 1, 'passed': 1}（全部 covered 且 passed）
- SHA 链：v2.0.6 manifest 自哈希一致=True、输出 SHA 与磁盘一致=True；v2.0.5 manifest / 当前 draft / chunks / chunk manifest SHA 全部不变=True
- 结论：RECONCILIATION_BLOCKED（failing conditions: strict_validator_covered_count == 162, strict_validator_passed_count == 162, uncovered_count == 0, invalid_count == 0; blocker: 1 row(s) not strictly legal (zh-037 legacy_coordinate)）。对账不修改任何 candidate 数据，遗留 legacy 行的处置需所有者另行决策。
