# v2 评测语料人工终审包 — AI 代理填写报告（2026-08-29）

## 一、身份与授权声明

- 本包 150 条审阅决策由 **AI 代理 zcode（标识 `zcode-agent-2026-08-29`）** 于 **2026-08-29** 填写，**非真人签名**。
- 填写经 owner 于 2026-08-29 明确授权委托执行；授权记录由主代理落账于最终报告与 CHANGELOG。
- 判定完全依据盲态包内信息（query / previous_turns / 草稿标签 / evidence snippet）与 `data/v2-corpus/chunks/chunks.jsonl` 的 chunk 原文独立作出；未读取任何自动审查、修复或评测结论类材料（含 `evaluation/datasets/v2/review/`、`llm-semantic-adjudication/`、`automated-review*/`、`llm-third-pass-audit/`、`targeted-post-repair-machine-review/`、`human-review/llm-review-issues*` 等）。
- 是否认可本 AI 填写结果进入 v2.1，由 owner 另行决策；本报告不构成人工批准。

## 二、总数与三值计数

| 决策 | 数量 |
|---|---|
| confirmed | 142 |
| reject | 6 |
| needs_followup | 2 |
| **合计** | **150** |

分类型分布（query_type × decision）：

| query_type | confirmed | reject | needs_followup | 小计 |
|---|---|---|---|---|
| single_fact | 34 | 0 | 0 | 34 |
| metadata | 18 | 1 | 0 | 19 |
| cross_document | 28 | 3 | 0 | 31 |
| mixed_intent | 11 | 1 | 0 | 12 |
| multi_turn | 24 | 0 | 0 | 24 |
| no_answer | 27 | 1 | 2 | 30 |

分语言：en 60（confirmed 54 / reject 4 / needs_followup 2）、zh 60（confirmed 59 / reject 1）、mixed 30（confirmed 29 / reject 1）。

## 三、分类型核验方法

1. **有证据行（relevance_level=chunk，119 条，共 161 个 snippet）**
   - 机械验证：python 脚本逐一验证每个 snippet 是否为对应 chunk 原文的连续子串（详见第四节）；
   - 逐点核验：每个 acceptable_answer_points 的答案点逐条对照 snippet 及 chunk 全文判断是否被直接支持，不凭常识脑补；
   - 来源一致性：161 个 snippet 的 chunk source 与 evidence.source_id 全部一致；relevant_source_ids 与证据 source 集合全部一致（0 例外）；
   - should_refuse=false 逐条确认语料确实可答。
   - 疑问点专项检索裁决：如 en-041 的前提句（「Simple assignment in Python never copies data」经检索确认存在于语料 chunk_13）、mixed-016 的 argument/parameter 中文标题（chunk_0/chunk_14 原文核到）、multi-027 的 BEGIN TRANSACTION 字样（chunk_0 核到）、zh-045 的「教程未讨论 GIL」负向断言（全量检索确认 GIL 仅出现于 supercalifragilisticexpialidocious 一词内）、mixed-027 的「SQLite 语法页未展开事务原子性」负向断言（sqlite-lang.md 全源检索确认）。
2. **拒答行（should_refuse=true、relevance_level=none，31 条）**
   - 用 python 对全部 1006 个 chunk 文本做每条 query 的多组关键词/同义表达检索（如 isolation level/隔离级别/REPEATABLE READ/SERIALIZABLE；journal_mode/WAL；streaming replication/流式复制；CREATE ROLE；IRI/internationalized；gunpowder/火药；scikit-learn/机器学习；Pinia/Redux；pandas/DataFrame；Django；matplotlib；inotify；crates.io/publish；quota；about:；unittest/doctest；json；Git/版本控制；cloud/deploy 等）；
   - 命中疑点（unittest、inotify、Copy trait、about:、孙武生平、JSON functions、venv Git 提及等）逐一读 chunk 全文后裁决，见第六节。
3. **多轮行（query_type=multi_turn，24 条）**
   - 其中 15 条 previous_turns 非空，逐条核对当前问题与对话链的衔接及拒答判定一致性（multi-029 为对话链上的拒答行，检索确认两篇文档均无隔离级别内容，拒答与对话链一致）；multi-016/multi-021/multi-025/multi-028 等追问的指代对象均在前轮与证据中核到；
   - 另有 9 条 query_type=multi_turn 但 previous_turns 为空（multi-011/015/018/020/022/024/027/030/032），其问题本身自足、证据与答案点核验均通过，按单条问题实质判定为 confirmed；该标签与内容的不一致建议后续修数据时留意（不影响本次三值判定）。
4. **跨文档行（query_type=cross_document，31 条）**
   - 逐条确认跨 source 的每个答案点在各自 source 的证据中均有支持；发现 3 条不满足（en-048 的答案点未回答问题、en-052 缺 Rust 侧答案点、zh-057 问题章节归属错误），均已 reject。

## 四、snippet 机械验证结果

161 个 snippet 逐条与 chunk 原文比对：

| 类别 | 数量 | 说明 |
|---|---|---|
| 字节级连续子串 | 126 | 精确匹配 |
| 空白规范化后连续匹配 | 22 | 换行/空格折叠后连续，内容零差异 |
| 行内代码/链接标记剥离后连续匹配 | 13 | chunk 内 ```code``` 反引号或 [链接]() 括号在 snippet 中被剥离，文字内容逐字一致、连续性保持 |
| **内容断裂/伪造** | **0** | 未发现任何snippet超出chunk原文范围或拼接不同位置内容的情况 |

结论：无证据伪造或断裂；35 处非字节级匹配均为空白规范化（22）与行内标记剥离（13）两类系统性轻微偏差，内容连续性均成立，不足以单独构成 reject 依据。建议后续修数据时统一 snippet 的提取口径（保留或剥离标记二选一）。

## 五、拒答行检索结论摘要

31 条拒答行中：

- **29 条确认拒答成立**：多组检索词在全语料无命中或命中均为明显误报（如 WAL 命中 walled/Wally/walrus、quota 命中 quotation、cloud 命中 clouds、publish 命中出版史叙述），或命中仅为顺带提及/链接引用（如 typescript 仅见于 Vue 文档「另参见」链接 URL、Chapter 7/Chapter 14 仅被 Rust 书前向引用、sqlite 概述页仅列「JSON functions」导航名、about: scheme 仅在 RFC 3986 附录 D 作为空路径示例一笔带过、孙武生卒年原文未载且 chunk_13 明言不足为凭、Git/版本控制仅为 venv 忽略文件与 requirements.txt 两处顺带提及）。
- **1 条拒答错误（reject）**：noanswer-050 — Python 教程 10.11 节（zh chunk_69 / en chunk_136）明确介绍 unittest 模块并给出完整示例，问题可由语料直接回答。
- **2 条转 needs_followup**：noanswer-039、noanswer-040（见下节）。

## 六、reject 与 needs_followup 清单

### reject（6 条）

| case_id | 一句话理由 |
|---|---|
| en-044 | 答案点「Rust: ownership rules govern value passing」的「传值」主张未被引用 chunk（4.1 所有权三规则）直接支持；传值/移动语义讨论在语料 chunk_41/43 但未被引用 |
| en-048 | query 问「哪条 SQLite 语句使用 OVER 子句」，两个答案点均未回答该问题，证据 chunk 的 over-clause 语法图也未标注所属语句 |
| en-052 | 跨文档问题要求比较两文档的保证，答案点只有 PostgreSQL 一侧；引用的 Rust chunk（所有权规则）不含任何数据一致性保证内容 |
| mixed-022 | 答案点「中文仅术语名（装饰器）」与语料矛盾：decorator 条目除英文定义外还有中文正文（「装饰器语法只是一种语法糖…」），实为中英混合解释 |
| zh-057 | query 将斐波那契 while 多重赋值例子归于「4.1 节」，语料中该例子在 3.2 节（4.1 节是 if 语句），证据 chunk 的 section 标签同样误标；答案点内容本身无误 |
| noanswer-050 | 拒答错误：教程 10.11 节明确介绍 unittest 模块并给出完整示例，语料可直接回答该问题 |

### needs_followup（2 条）

| case_id | 一句话理由（缺什么） |
|---|---|
| noanswer-039 | 语料 chunk_101 明确说明 fs.watch 在 Linux 使用 inotify(7)（并逐平台列出机制），该事实直接对应问题主题；但文档仅点名机制、未描述内部实现，「describe inotify internals」口径两可，需仲裁拒答标签 |
| noanswer-040 | 语料 chunk_46/58 对 Copy/Drop trait 有实质讲解（第 4 章在语料内），但 traits 专章（第 10 章）不在语料且正文自称「we'll talk more about traits in Chapter 10」，「语料包含章节是否 cover traits」按不同口径可答可拒，需仲裁 |

## 七、输出与合规声明

- 已创建文件（仅此两个）：
  1. `evaluation/datasets/v2/human-review/human-review-pack-filled.jsonl` — 150 行已填写 pack，UTF-8，每行一个 JSON，保留原始全部字段；
  2. `evaluation/datasets/v2/human-review/agent-fill-report-2026-08-29.md` — 本报告。
- 合并方式：python 脚本从原始 pack 机械合并，仅设置 `human_review_decision` / `human_reviewer` / `human_review_notes` 三个字段，其余字段一律不动。
- 自检通过：150 行、case_id 无重无漏且顺序一致、decision 均为三值之一、reject/needs_followup notes 非空且具体、confirmed notes 均不超过 40 字、每行剔除三个人工字段后与原始 pack 对应行规范化 JSON（sort_keys + 紧凑分隔符）逐字节一致。
- 未修改原始 pack、manifest、draft、chunks、split、review 等任何既有文件；未运行 `scripts/corpus_v2_human_review_apply.py`；未执行任何 git stage/commit/push。
