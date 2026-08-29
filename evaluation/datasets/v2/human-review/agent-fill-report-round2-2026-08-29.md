# v2 人工终审 Round-2 报告：owner 仲裁 → 修复 → 复核 → overlay 生成

> 日期：2026-08-29。Round-1（同日）代理终审 142 confirmed / 6 reject /
> 2 needs_followup，8 条阻断；owner 对 8 条作出仲裁批示后，本轮按批示
> 修复草稿、重建 pack、转移决策并再次导入——**150/150 confirmed，
> `HUMAN_REVIEWED` overlay 已生成**（verify 复检通过）。

## owner 仲裁批示（2026-08-29，逐字）

- 「同意六条reject」——en-044 / en-048 / en-052 / mixed-022 / zh-057 /
  noanswer-050 的草稿错误成立；
- noanswer-039「算可答」——机制点名即答；
- noanswer-040「实质讲解在就按照讲解回答，然后如实陈述 traits 专章不在」。

## 8 条修复（证据优先最小修复，ledger 已追加 8 条记录）

| case | 修复内容 | 证据变化 |
| --- | --- | --- |
| en-044 | Rust 侧答案点改「传值即 move 所有权并使源变量失效」 | chunk_37 → chunk_43（move 后 s1 失效） |
| en-048 | 问题对齐证据：改问「SQLite 语言文档定义了什么 OVER 子句语法」 | 不变（PG chunk_16 + SQLite 语法图 chunk_8） |
| en-052 | 问题改「各自保证什么」；Rust 侧答案点=内存安全保证 | chunk_37 → chunk_53（引用永不悬垂）+ chunk_43（杜绝 double-free） |
| mixed-022 | 答案点 2 改「条目为中英混合：英文定义 + 中文正文解释」 | 不变（chunk_5） |
| zh-057 | query 与证据 section 章节归属 4.1 → 3.2 | chunk 不变（chunk_7 内目录可证） |
| noanswer-039 | 翻可答（chunk 级）：按平台点名机制 | 新增 chunk_101（Linux inotify(7) 等） |
| noanswer-040 | 翻可答（chunk 级）：Copy/Drop 实质讲解 + 如实说明 traits 专章不在 | 新增 chunk_46（Copy 语义 + Copy/Drop 互斥 + 自身指向 Chapter 10） |
| noanswer-050 | 翻可答（chunk 级）：unittest 有完整讲解与示例 | 新增 chunk_69（zh）+ chunk_136（en），10.11 节 |

三条拒答探针翻可答的行：`metadata.band_target` 同步
`low_refuse → low_answerable`（construction/query_type 等构建元数据保持
历史原样）；`annotation.review_notes` 记录仲裁落地。

## 机械过程与校验

1. **修复脚本**：仅 8 行改动（改动行集断言 = 目标集）；全部新 snippet
   `snippet_is_evidence` 连续性校验通过（含一次围栏代码块未闭合导致的
   fail-closed 拦截，修正切点后通过）；ledger 既有 10 条逐字节不动；
2. **pack 重建**：`build_pack` 全量校验（链完整性、必需字段、证据连续、
   source 一致）通过；manifest 五类输入 SHA 更新为新链；
3. **142 条决策机械转移**：pack 级新旧行剔除人工字段逐字节一致（round-1
   空白包自 git dba4c81 恢复比对）+ round-1 filled 行一致才照搬人工字段，
   转移计数 142 断言通过；
4. **8 条 round-2 复核填写**：修复后逐条对照 chunk 原文确认证据支撑，
   全部 confirmed（审阅人 `zcode-agent-2026-08-29`，notes 注明 round-2
   复核依据）；
5. **apply**：status=**overlay**，counts 150/0/0，零阻断；
   `human-reviewed-truth-overlay.json` + manifest 落盘；
6. **verify**：`overlay + manifest chain intact (HUMAN_REVIEWED)`。

## 身份与授权声明

Round-1 填写与 Round-2 复核均由 AI 代理（zcode-agent-2026-08-29）在
owner 明确授权下执行；owner 对 8 条阻断 case 作出了真人仲裁批示。
overlay 的 reviewer 字段如实记录代理标识——**是否据此启用 v2.1 属于
owner 的另行人工决策**，本流水线不自动宣称任何「上线批准」。

## 数据卫生

草稿/ledger 追加以外零改动；chunks、corpus-manifest、case-freeze、
split-lock、sealed 产物零触碰；中间脚本均在系统临时目录；无 LLM/API
调用路径（纯本地文本操作）。
