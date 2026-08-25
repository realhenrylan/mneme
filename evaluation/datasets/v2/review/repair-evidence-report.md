# v2 修复验证与二审报告（LLM_ASSISTED_SECOND_PASS）

> 本报告记录 10 条异常草稿的证据优先修复（repair ledger）与修复后
> 的全量 150 条二审结果。修复与二审均为 LLM 辅助产物，**未经人工批准**，绝不伪称人工审核。

## 修复范围

- 目标 case（必须恰好 10 条）：en-038, en-040, en-043, en-046, en-047, mixed-025, mixed-030, mixed-032, zh-050, zh-059

- 修复动作汇总：corrected 9；retained_after_evidence_check 1；changed_to_refusal 0

## 逐条修复判定

| case_id | action | 旧值摘要 | 新值摘要 | 证据（SHA 前 12 位） | 理由 |
|---|---|---|---|---|---|
| en-038 | corrected | 答案点 Chapter 3 Advanced Features；证据仅章节标题片段（chunk_8） | 答案点不变；证据替换为目录（chunk_0：3.2 Views/3.3 Foreign Keys/3.4 Transactions）与第 3 章正文（chunk_9） | 761b22915b5e_chunk_0·b1d5e78aadae；761b22915b5e_chunk_9·0088c38169b8 | 二审指出证据仅为章节标题、不足以证明第 3 章覆盖 views/foreign keys/transactions；目录与第 3 章正文直接证实，答案点本身正确。 |
| en-040 | corrected | 答案点 2 条；SQLite snippet 截断于 commit-stmt，PG snippet 仅转账示例无 BEGIN/COMMIT/ROLLBACK | 答案点收紧为可证实表述；证据 3 条：完整语法图（begin/commit/rollback-stmt）+ Transactions 小节开头 + BEGIN/COMMIT/ROLLBACK 原文 | 8b191b241b93_chunk_1·ba50a5f9c9e7；761b22915b5e_chunk_10·5b30f85c472a；761b22915b5e_chunk_12·1e893352621f | 原 PG snippet 仅截取转账示例、未含 BEGIN/COMMIT/ROLLBACK；补齐 Transactions 小节开头与事务原文；SQLite snippet 补全至 rollback-stmt。 |
| en-043 | corrected | 答案点 2 条（SQLite 不限制类型 + PG 未讨论限制）；证据仅 SQLite 1 条 | 答案收缩为 1 条：SQLite 明确说明不限制列数据类型（含原文引句）；证据不变 | 8b191b241b93_chunk_13·e2045bd169bd | PG 否定点（"未讨论列类型限制"）无本地证据，按规则收缩为 SQLite 正面证据结论。 |
| en-046 | corrected | source-only 无证据；答案点 f.write / filehandle.write / fsPromises.writeFile | relevance_level 改 chunk；证据 4 条：f.write(string) 原文、filehandle.write、fsPromises.writeFile 签名与描述 | e564a122a7a2_chunk_87·b692ae6c9b26；b9c22720dc84_chunk_26·7ef64dd8f7f4；b9c22720dc84_chunk_47·655dccd20a2f；b9c22720dc84_chunk_48·ecf1da4777bf | source-only 且无证据；两文档均存在直接内容证据，改为 chunk 级并补齐。 |
| en-047 | corrected | 答案点 2 条（SQLite 有 JOIN + PG 无 JOIN）；证据仅 SQLite 1 条 | 答案点更正：PG 目录含 2.6 Joins Between Tables；证据 3 条：SQLite JOIN 操作符 + CROSS JOIN 特殊处理 + PG 目录 | 8b191b241b93_chunk_39·b0cc495e6a28；8b191b241b93_chunk_40·63a636a67394；761b22915b5e_chunk_0·9ed5060f5b4e | 原"PG 第 2 章未收录 JOIN"与目录（2.6 Joins Between Tables）矛盾，更正为目录证据；SQLite 补齐 LEFT/RIGHT/FULL 操作符片段。 |
| mixed-025 | corrected | source-only 无证据；答案点"文档开头列出编者（Editors）" | relevance_level 改 chunk；答案点具体化（Adam Turner 和 Thomas Wouters）；证据为头部编者栏片段 | 81544765752f_chunk_0·9336955ec57e | source-only 且无证据；头部 chunk 含编者栏（Adam Turner 和 Thomas Wouters），改为 chunk 级并补齐。 |
| mixed-030 | corrected | 答案点"Python 类可复用代码单元 + React 组件可复用 UI 单元"；证据为类定义语法与 React Intro 首页 | 答案点改为双方文档直接表述（类绑定数据与功能 / 组件可重用可嵌套）；证据为 9. 类开头与 React Intro | 32c427fb50e2_chunk_56·cab44d950446；993955159403_chunk_0·b9fdce04129f | 原"Python 类是可复用代码单元"无本地证据（教程中"复用"仅指模块）；改为 9. 类章节直接表述，React 侧用 Intro 的"可重用、可嵌套的组件"。 |
| mixed-032 | corrected | 答案点 2 条（SQLite 有 JOIN + PG 无 JOIN）；证据仅 SQLite 1 条 | 答案点更正：PG 目录列出 2.6 Joins Between Tables；证据 3 条同 en-047 | 8b191b241b93_chunk_39·b0cc495e6a28；8b191b241b93_chunk_40·63a636a67394；761b22915b5e_chunk_0·9ed5060f5b4e | 同 en-047：PG 目录含 2.6 Joins Between Tables，否定点更正为目录证据。 |
| zh-050 | corrected | 答案点"3.13 未列出 datetime 变更"；证据为构建依赖片段（sqlite3/mimalloc） | 答案点改为文档实际内容（datetime 弃用变更 + copy.replace 支持）；证据为弃用章节与 copy 章节片段 | 81544765752f_chunk_29·7211bc525645；81544765752f_chunk_9·167d14a38d9f | 原"未列出 datetime 变更"与文档实际内容矛盾（弃用章节列出 utcnow/utcfromtimestamp，copy.replace 支持 datetime 类型），答案点修正为文档实际内容并替换无关证据。 |
| zh-059 | retained_after_evidence_check | 答案点"模块（第 6 章）"；snippet 含"# 6. 模块¶"标题 | 答案点不变；snippet 扩展至含模块定义句（"这个文件就是 模块"） | 32c427fb50e2_chunk_30·24cfe23193a4 | chunk 原文含"# 6. 模块¶"标题与模块定义，答案"模块（第 6 章）"正确；二审以"snippet 未含标题"为由拒绝与事实矛盾，不改真值，仅扩展 snippet。 |

## 证据 SHA-256 明细（与草稿 chunk_text_snippet 复算一致）

```
en-038 | 761b22915b5e_chunk_0 | postgresql-tutorial.md | b1d5e78aadae4e49e0e9582fc9ad2de6a639e0ddefc9a6d693ee4a1f419b51db
en-038 | 761b22915b5e_chunk_9 | postgresql-tutorial.md | 0088c38169b848a0cb0111458e0d8b644b6fb0c84c836e199d469dfff0982391
en-040 | 8b191b241b93_chunk_1 | sqlite-lang.md | ba50a5f9c9e75eea9ae9fc42c6e8d00a0fe4b721d28e5cf3f3a5da9907e49b42
en-040 | 761b22915b5e_chunk_10 | postgresql-tutorial.md | 5b30f85c472acba3c87e02c02011f2c7686b4de811726630d39d5f8181eb12d1
en-040 | 761b22915b5e_chunk_12 | postgresql-tutorial.md | 1e893352621f8c8d9e159909f42f68649fe8e7e1ba79872b1b04bc80f2b06255
en-043 | 8b191b241b93_chunk_13 | sqlite-lang.md | e2045bd169bded44607fa9d4812f159a2da983f142cc621ab6731272d98c462f
en-046 | e564a122a7a2_chunk_87 | python-tutorial-en.md | b692ae6c9b2665b3bcad5ebd953f791300a1304d280bcecc40acef2c66cd387b
en-046 | b9c22720dc84_chunk_26 | nodejs-fs.md | 7ef64dd8f7f4ff78e2126d6bf9ff5234471a023fd2325eb48287f750f5883f0a
en-046 | b9c22720dc84_chunk_47 | nodejs-fs.md | 655dccd20a2fe4c832fe6006c061802bf12b6f4f5364e6b1e092d4665e89458d
en-046 | b9c22720dc84_chunk_48 | nodejs-fs.md | ecf1da4777bfacff3fda8244c27a70b7d362a13e376cb49728c7934c9a878b89
en-047 | 8b191b241b93_chunk_39 | sqlite-lang.md | b0cc495e6a28ca858cdc237e4a7bfc2afc5563a47b79e41693655872b90ee9b3
en-047 | 8b191b241b93_chunk_40 | sqlite-lang.md | 63a636a67394caa155baa3a57a5f078db096bab06b02a5ca73c7a9642fdd8481
en-047 | 761b22915b5e_chunk_0 | postgresql-tutorial.md | 9ed5060f5b4ed1132ecec99247c908aae3da05fcf1ed169e41d9c56436b7271a
mixed-025 | 81544765752f_chunk_0 | python-whatsnew313-zh.md | 9336955ec57e075e6841e4020ffdeff8d1dca2bcf2c682cbcbbe12e3eaa93a1d
mixed-030 | 32c427fb50e2_chunk_56 | python-tutorial-zh.md | cab44d9504461a55394b8c66614c1a990522a0d49db3b63adc84b21a304b2a1e
mixed-030 | 993955159403_chunk_0 | react-learn-zh.md | b9fdce04129f8f8fdae43a5b14e65a4024acac5b6fa1bac9d3764e2812063339
mixed-032 | 8b191b241b93_chunk_39 | sqlite-lang.md | b0cc495e6a28ca858cdc237e4a7bfc2afc5563a47b79e41693655872b90ee9b3
mixed-032 | 8b191b241b93_chunk_40 | sqlite-lang.md | 63a636a67394caa155baa3a57a5f078db096bab06b02a5ca73c7a9642fdd8481
mixed-032 | 761b22915b5e_chunk_0 | postgresql-tutorial.md | 9ed5060f5b4ed1132ecec99247c908aae3da05fcf1ed169e41d9c56436b7271a
zh-050 | 81544765752f_chunk_29 | python-whatsnew313-zh.md | 7211bc5256456fb06c99fba3aca7eb095bd0b905d92710ff9168d4a5641d1b39
zh-050 | 81544765752f_chunk_9 | python-whatsnew313-zh.md | 167d14a38d9f6fd4ba29516e7cd73d092c30adf145c2b6b48ea32509da9c69fc
zh-059 | 32c427fb50e2_chunk_30 | python-tutorial-zh.md | 24cfe23193a48b22b08647e1593b41e72763a42df8b8fb6b021434f67555dde2
```

## 全量二审汇总（不按 split 分析）

- 审阅条数：150
- confirmed：150
- reject：0
- needs_followup：0
- 草稿与二审一致率（confirmed / 总数）：150/150 = 100.0%

### 置信度分布

| 置信度 | 条数 |
|---|---|
| high | 150 |

### 问题类别分布（reject / needs_followup 提及）

| 问题类别 | 提及次数 |
|---|---|

## fail-closed 校验

- repair validator：通过（ledger 恰好 10 条、非目标行未改动、snippet 连续且 SHA 一致）
- 草稿 annotation 保持 `LLM_ASSISTED` / `pending`，无 HUMAN 声明
- 旧草稿 SHA-256：f6e2c9098031c017b99dc71573ed5bec2abb5de27a9333c7847ebd176f608055
- 新草稿 SHA-256：e289d1f0cff5daa2bed54b23a31cd72c7e40a0c46fb7f2638e5b05bfbeb2382f

## 结论

LLM-assisted candidate review complete，未经人工批准；仍不得进入 v2.1。
