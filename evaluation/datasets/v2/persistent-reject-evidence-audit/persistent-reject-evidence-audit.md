# v2 持续 reject case 本地证据可修复性审计

> 本审计为**证据可修复性分析**（确定性、离线、无 LLM/API）：逐答案点机械搜索相关 source 全文 chunks 中的逐字候选 span，评估 `repair_feasibility` 与 `proposed_action`。**不代表自动修复、人工审核或 v2.1 准入**。

- 目标 case：en-052, en-055, mixed-016, mixed-026, multi-014（合并后 102 条中唯一 5 条持续 reject：第三轮 reject 且 v4 Pro reject）
- 答案点：9 个（其中 v4 Pro 判 unsupported 5 个）
- 候选 span：432 条（范围内 82 / 范围外 out_of_scope_only 350）
- 阈值：MIN_SPAN_LEN=8、COVERAGE_EXACT=0.75

## 判定规则（机械、确定性）

- 搜索限定 `relevant_source_ids`；范围外命中标 `out_of_scope_only`，不作为修复依据
- span 覆盖答案点 ≥ 75% → `exact_local_evidence_available`；≥ 8 字符 → `only_paraphrase_or_partial_evidence`；否则 `no_local_evidence_found`
- `add_exact_evidence`：候选原文直接支撑完整答案点且不在当前 evidence；`narrow_answer_point`：至少一个完整子句逐字出现；`remove_unsupported_answer_point`：相关源内无任何逐字证据；其余改写/跨语言/仅范围外情形 → `manual_semantic_adjudication_required`
- 已被 v4 Pro 判 supported 的答案点不属于修复范围

## 逐 case 明细

### en-052（index 25，en / cross_document）

- query：Both PostgreSQL and Rust documents discuss guarantees — what does each guarantee about data consistency?
- relevant_source_ids：postgresql-tutorial.md, rust-book-core.md
- v4 Pro reject 理由：The PostgreSQL answer point is directly supported by the evidence. The Rust answer point is unsupported because the provided chunk describes ownership rules but does not explicitly state that they guarantee memory safety.
- 第三轮 reject 理由：不可用（第三轮 reject 理由位于 human-review-pack.llm-filled.jsonl 与 llm-third-pass-report.md，不在本任务允许读取范围（仅 merged-adjudications.jsonl / selection-manifest.json / human-review-pack.jsonl / chunks.jsonl）；第三轮 decision=reject 已由 selection-manifest.disputed 集合确认。）

- 当前 evidence：`761b22915b5e_chunk_12` / `postgresql-tutorial.md` / section 3.4 Transactions / snippet 「A transactional database guarantees that all the updates made by a transaction a…」
- 当前 evidence：`4f9001ca8c15_chunk_37` / `rust-book-core.md` / section 4.1 What Is Ownership / snippet 「### Ownership Rules

First, let’s take a look at the ownership rules. Keep these…」

| 答案点 | v4 Pro 支持 | 匹配 | repair_feasibility | proposed_action |
|---|---|---|---|---|
| 0 PostgreSQL: transaction durability (logg | direct_snippet | 18 / 12 | only_paraphrase_or_partial_evidence | manual_semantic_adjudication_required |
| 1 Rust: ownership rules guarantee memory s | unsupported | 34 / 14 | only_paraphrase_or_partial_evidence | manual_semantic_adjudication_required |

候选 span（chunk 内字符范围）：

| 答案点 | chunk_id | source_id | 范围 | 最短必要原文 | 类型 |
|---|---|---|---|---|---|
| 0 | `761b22915b5e_chunk_0` | `postgresql-tutorial.md` | 2-12（范围内） | `PostgreSQL` | clause |
| 0 | `761b22915b5e_chunk_0` | `postgresql-tutorial.md` | 1672-1683（范围内） | `Transaction` | partial |
| 0 | `761b22915b5e_chunk_2` | `postgresql-tutorial.md` | 50-60（范围内） | `PostgreSQL` | clause |
| 0 | `761b22915b5e_chunk_3` | `postgresql-tutorial.md` | 33-43（范围内） | `PostgreSQL` | clause |
| 0 | `761b22915b5e_chunk_4` | `postgresql-tutorial.md` | 12-22（范围内） | `PostgreSQL` | clause |
| 0 | `761b22915b5e_chunk_5` | `postgresql-tutorial.md` | 64-74（范围内） | `PostgreSQL` | clause |
| 0 | `761b22915b5e_chunk_6` | `postgresql-tutorial.md` | 959-969（范围内） | `PostgreSQL` | clause |
| 0 | `761b22915b5e_chunk_7` | `postgresql-tutorial.md` | 329-339（范围内） | `PostgreSQL` | clause |
| 0 | `761b22915b5e_chunk_9` | `postgresql-tutorial.md` | 130-140（范围内） | `PostgreSQL` | clause |
| 0 | `761b22915b5e_chunk_10` | `postgresql-tutorial.md` | 338-348（范围内） | `PostgreSQL` | clause |
| 0 | `761b22915b5e_chunk_10` | `postgresql-tutorial.md` | 1217-1228（范围内） | `Transaction` | partial |
| 0 | `761b22915b5e_chunk_11` | `postgresql-tutorial.md` | 1127-1138（范围内） | `transaction` | partial |
| 0 | `761b22915b5e_chunk_12` | `postgresql-tutorial.md` | 932-942（范围内） | `PostgreSQL` | clause |
| 0 | `761b22915b5e_chunk_12` | `postgresql-tutorial.md` | 946-957（范围内） | `transaction` | partial |
| 0 | `761b22915b5e_chunk_13` | `postgresql-tutorial.md` | 110-121（范围内） | `transaction` | partial |
| 0 | `761b22915b5e_chunk_14` | `postgresql-tutorial.md` | 265-276（范围内） | `transaction` | partial |
| 0 | `761b22915b5e_chunk_18` | `postgresql-tutorial.md` | 1160-1170（范围内） | `PostgreSQL` | clause |
| 0 | `761b22915b5e_chunk_19` | `postgresql-tutorial.md` | 93-103（范围内） | `PostgreSQL` | clause |
| 0 | `293d777c429b_chunk_11` | `art-of-war.txt` | 382-391（范围外） | `ed to dis` | partial |
| 0 | `293d777c429b_chunk_33` | `art-of-war.txt` | 933-942（范围外） | `ed to dis` | partial |
| 0 | `293d777c429b_chunk_90` | `art-of-war.txt` | 1164-1173（范围外） | `ged to di` | partial |
| 0 | `293d777c429b_chunk_94` | `art-of-war.txt` | 418-426（范围外） | `bility (` | partial |
| 0 | `293d777c429b_chunk_106` | `art-of-war.txt` | 1037-1045（范围外） | `ged to d` | partial |
| 0 | `2e79918eccf4_chunk_34` | `python-datetime-zh.md` | 870-878（范围外） | `d to dis` | partial |
| 0 | `86ef1bf559c5_chunk_8` | `rfc3986.txt` | 63-72（范围外） | `ed to dis` | partial |
| 0 | `86ef1bf559c5_chunk_22` | `rfc3986.txt` | 1487-1495（范围外） | `rability` | partial |
| 0 | `86ef1bf559c5_chunk_33` | `rfc3986.txt` | 182-190（范围外） | `rability` | partial |
| 0 | `86ef1bf559c5_chunk_51` | `rfc3986.txt` | 1012-1020（范围外） | `rability` | partial |
| 0 | `86ef1bf559c5_chunk_74` | `rfc3986.txt` | 1897-1905（范围外） | `ed to di` | partial |
| 0 | `8b191b241b93_chunk_0` | `sqlite-lang.md` | 769-780（范围外） | `TRANSACTION` | partial |
| 1 | `761b22915b5e_chunk_11` | `postgresql-tutorial.md` | 1151-1162（范围内） | `s guarantee` | partial |
| 1 | `761b22915b5e_chunk_12` | `postgresql-tutorial.md` | 27-36（范围内） | `guarantee` | partial |
| 1 | `4f9001ca8c15_chunk_1` | `rust-book-core.md` | 1611-1620（范围内） | `guarantee` | partial |
| 1 | `4f9001ca8c15_chunk_15` | `rust-book-core.md` | 1652-1660（范围内） | `e memory` | partial |
| 1 | `4f9001ca8c15_chunk_16` | `rust-book-core.md` | 350-359（范围内） | `ownership` | partial |
| 1 | `4f9001ca8c15_chunk_26` | `rust-book-core.md` | 1765-1774（范围内） | `guarantee` | partial |
| 1 | `4f9001ca8c15_chunk_32` | `rust-book-core.md` | 761-772（范围内） | `: ownership` | partial |
| 1 | `4f9001ca8c15_chunk_32` | `rust-book-core.md` | 1370-1378（范围内） | `e memory` | partial |
| 1 | `4f9001ca8c15_chunk_33` | `rust-book-core.md` | 20-29（范围内） | `ownership` | partial |
| 1 | `4f9001ca8c15_chunk_34` | `rust-book-core.md` | 313-322（范围内） | `ownership` | partial |
| 1 | `4f9001ca8c15_chunk_34` | `rust-book-core.md` | 1346-1354（范围内） | `e memory` | partial |
| 1 | `4f9001ca8c15_chunk_36` | `rust-book-core.md` | 156-165（范围内） | `ownership` | partial |
| 1 | `4f9001ca8c15_chunk_37` | `rust-book-core.md` | 4-19（范围内） | `Ownership Rules` | partial |
| 1 | `4f9001ca8c15_chunk_38` | `rust-book-core.md` | 50-59（范围内） | `ownership` | partial |
| 1 | `4f9001ca8c15_chunk_39` | `rust-book-core.md` | 557-566（范围内） | `ownership` | partial |
| 1 | `4f9001ca8c15_chunk_39` | `rust-book-core.md` | 1420-1428（范围内） | `e memory` | partial |
| 1 | `4f9001ca8c15_chunk_40` | `rust-book-core.md` | 1079-1088（范围内） | `ownership` | partial |
| 1 | `4f9001ca8c15_chunk_40` | `rust-book-core.md` | 1190-1198（范围内） | `e memory` | partial |
| 1 | `4f9001ca8c15_chunk_41` | `rust-book-core.md` | 725-734（范围内） | `ownership` | partial |
| 1 | `4f9001ca8c15_chunk_41` | `rust-book-core.md` | 1640-1648（范围内） | `e memory` | partial |
| 1 | `4f9001ca8c15_chunk_43` | `rust-book-core.md` | 998-1007（范围内） | `ownership` | partial |
| 1 | `4f9001ca8c15_chunk_44` | `rust-book-core.md` | 859-868（范围内） | `ownership` | partial |
| 1 | `4f9001ca8c15_chunk_45` | `rust-book-core.md` | 880-889（范围内） | `ownership` | partial |
| 1 | `4f9001ca8c15_chunk_47` | `rust-book-core.md` | 324-333（范围内） | `Ownership` | partial |
| 1 | `4f9001ca8c15_chunk_48` | `rust-book-core.md` | 25-34（范围内） | `ownership` | partial |
| 1 | `4f9001ca8c15_chunk_48` | `rust-book-core.md` | 1664-1675（范围内） | `s guarantee` | partial |
| 1 | `4f9001ca8c15_chunk_49` | `rust-book-core.md` | 134-143（范围内） | `ownership` | partial |
| 1 | `4f9001ca8c15_chunk_50` | `rust-book-core.md` | 334-343（范围内） | `ownership` | partial |
| 1 | `4f9001ca8c15_chunk_51` | `rust-book-core.md` | 330-339（范围内） | `ownership` | partial |
| 1 | `4f9001ca8c15_chunk_52` | `rust-book-core.md` | 58-67（范围内） | `ownership` | partial |
| 1 | `4f9001ca8c15_chunk_53` | `rust-book-core.md` | 715-724（范围内） | `ownership` | partial |
| 1 | `4f9001ca8c15_chunk_54` | `rust-book-core.md` | 204-213（范围内） | `Ownership` | partial |
| 1 | `4f9001ca8c15_chunk_61` | `rust-book-core.md` | 6-15（范围内） | `Ownership` | partial |
| 1 | `4f9001ca8c15_chunk_63` | `rust-book-core.md` | 301-310（范围内） | `ownership` | partial |
| 1 | `b9c22720dc84_chunk_16` | `nodejs-fs.md` | 506-515（范围外） | `ownership` | partial |
| 1 | `b9c22720dc84_chunk_30` | `nodejs-fs.md` | 1693-1702（范围外） | `ownership` | partial |
| 1 | `b9c22720dc84_chunk_31` | `nodejs-fs.md` | 1145-1154（范围外） | `guarantee` | partial |
| 1 | `b9c22720dc84_chunk_34` | `nodejs-fs.md` | 767-776（范围外） | `ownership` | partial |
| 1 | `b9c22720dc84_chunk_57` | `nodejs-fs.md` | 1673-1682（范围外） | `guarantee` | partial |
| 1 | `b9c22720dc84_chunk_85` | `nodejs-fs.md` | 1104-1112（范围外） | `e memory` | partial |
| 1 | `b9c22720dc84_chunk_102` | `nodejs-fs.md` | 737-748（范围外） | `s guarantee` | partial |
| 1 | `b9c22720dc84_chunk_111` | `nodejs-fs.md` | 1124-1133（范围外） | `guarantee` | partial |
| 1 | `b9c22720dc84_chunk_115` | `nodejs-fs.md` | 1301-1310（范围外） | `guarantee` | partial |
| 1 | `b9c22720dc84_chunk_151` | `nodejs-fs.md` | 1000-1009（范围外） | `guarantee` | partial |
| 1 | `2e79918eccf4_chunk_28` | `python-datetime-zh.md` | 1693-1702（范围外） | `guarantee` | partial |
| 1 | `86ef1bf559c5_chunk_13` | `rfc3986.txt` | 1547-1556（范围外） | `guarantee` | partial |
| 1 | `86ef1bf559c5_chunk_29` | `rfc3986.txt` | 816-825（范围外） | `ownership` | partial |
| 1 | `86ef1bf559c5_chunk_62` | `rfc3986.txt` | 50-59（范围外） | `guarantee` | partial |

### en-055（index 27，en / mixed_intent）

- query：The Rust book says values are moved rather than copied in some cases — what operator creates a reference instead?
- relevant_source_ids：rust-book-core.md
- v4 Pro reject 理由：答案点声称引用由 & 运算符创建，但提供的语料片段中未提及 & 运算符，仅描述了引用的概念，没有明确说明使用的运算符。
- 第三轮 reject 理由：不可用（第三轮 reject 理由位于 human-review-pack.llm-filled.jsonl 与 llm-third-pass-report.md，不在本任务允许读取范围（仅 merged-adjudications.jsonl / selection-manifest.json / human-review-pack.jsonl / chunks.jsonl）；第三轮 decision=reject 已由 selection-manifest.disputed 集合确认。）

- 当前 evidence：`4f9001ca8c15_chunk_48` / `rust-book-core.md` / section 4.2 References and Borrowing / snippet 「A reference is like a pointer in that it’s an address we can follow to access
th…」

| 答案点 | v4 Pro 支持 | 匹配 | repair_feasibility | proposed_action |
|---|---|---|---|---|
| 0 & 运算符（借用/引用） | unsupported | 0 / 0 | no_local_evidence_found | manual_semantic_adjudication_required（语言不匹配） |

### mixed-016（index 28，mixed / single_fact）

- query：术语表里，argument 和 parameter 的中文译名分别是什么？
- relevant_source_ids：python-glossary-zh.md
- v4 Pro reject 理由：答案点1（argument 译为 参数）得到证据支持（小节标题为 argument 参数），但答案点2（parameter 译为 形参）在提供的 chunks 中无任何支持，仅提及参见 parameter 术语表条目而未给出译名。因此整体答案不完整。
- 第三轮 reject 理由：不可用（第三轮 reject 理由位于 human-review-pack.llm-filled.jsonl 与 llm-third-pass-report.md，不在本任务允许读取范围（仅 merged-adjudications.jsonl / selection-manifest.json / human-review-pack.jsonl / chunks.jsonl）；第三轮 decision=reject 已由 selection-manifest.disputed 集合确认。）

- 当前 evidence：`c9fd20815ea8_chunk_1` / `python-glossary-zh.md` / section argument 参数 / snippet 「参数会被赋值给函数体中对应的局部变量。有关赋值规则参见 调用 一节。根据语法，任何表达式都可用来表示一个参数；最终算出的值会被赋给对应的局部变量。
 另参见 p…」

| 答案点 | v4 Pro 支持 | 匹配 | repair_feasibility | proposed_action |
|---|---|---|---|---|
| 0 argument 译为 参数 | direct_snippet | 7 / 124 | only_paraphrase_or_partial_evidence | manual_semantic_adjudication_required |
| 1 parameter 为另一术语表条目（形参） | unsupported | 5 / 83 | only_paraphrase_or_partial_evidence | manual_semantic_adjudication_required |

候选 span（chunk 内字符范围）：

| 答案点 | chunk_id | source_id | 范围 | 最短必要原文 | 类型 |
|---|---|---|---|---|---|
| 0 | `c9fd20815ea8_chunk_0` | `python-glossary-zh.md` | 1334-1342（范围内） | `argument` | partial |
| 0 | `c9fd20815ea8_chunk_3` | `python-glossary-zh.md` | 306-314（范围内） | `argument` | partial |
| 0 | `c9fd20815ea8_chunk_11` | `python-glossary-zh.md` | 647-655（范围内） | `argument` | partial |
| 0 | `c9fd20815ea8_chunk_12` | `python-glossary-zh.md` | 1247-1255（范围内） | `argument` | partial |
| 0 | `c9fd20815ea8_chunk_14` | `python-glossary-zh.md` | 837-845（范围内） | `argument` | partial |
| 0 | `c9fd20815ea8_chunk_15` | `python-glossary-zh.md` | 1299-1307（范围内） | `argument` | partial |
| 0 | `c9fd20815ea8_chunk_18` | `python-glossary-zh.md` | 183-191（范围内） | `argument` | partial |
| 0 | `293d777c429b_chunk_21` | `art-of-war.txt` | 1622-1630（范围外） | `argument` | partial |
| 0 | `293d777c429b_chunk_175` | `art-of-war.txt` | 1873-1881（范围外） | `gument, ` | partial |
| 0 | `b9c22720dc84_chunk_3` | `nodejs-fs.md` | 931-939（范围外） | `argument` | partial |
| 0 | `b9c22720dc84_chunk_9` | `nodejs-fs.md` | 1882-1890（范围外） | `argument` | partial |
| 0 | `b9c22720dc84_chunk_10` | `nodejs-fs.md` | 100-108（范围外） | `argument` | partial |
| 0 | `b9c22720dc84_chunk_13` | `nodejs-fs.md` | 1426-1434（范围外） | `argument` | partial |
| 0 | `b9c22720dc84_chunk_15` | `nodejs-fs.md` | 1006-1014（范围外） | `argument` | partial |
| 0 | `b9c22720dc84_chunk_20` | `nodejs-fs.md` | 925-933（范围外） | `argument` | partial |
| 0 | `b9c22720dc84_chunk_21` | `nodejs-fs.md` | 682-690（范围外） | `argument` | partial |
| 0 | `b9c22720dc84_chunk_22` | `nodejs-fs.md` | 100-108（范围外） | `argument` | partial |
| 0 | `b9c22720dc84_chunk_25` | `nodejs-fs.md` | 706-714（范围外） | `argument` | partial |
| 0 | `b9c22720dc84_chunk_26` | `nodejs-fs.md` | 484-492（范围外） | `argument` | partial |
| 0 | `b9c22720dc84_chunk_27` | `nodejs-fs.md` | 742-750（范围外） | `argument` | partial |
| 0 | `b9c22720dc84_chunk_28` | `nodejs-fs.md` | 337-345（范围外） | `argument` | partial |
| 0 | `b9c22720dc84_chunk_29` | `nodejs-fs.md` | 556-564（范围外） | `argument` | partial |
| 0 | `b9c22720dc84_chunk_30` | `nodejs-fs.md` | 1833-1841（范围外） | `argument` | partial |
| 0 | `b9c22720dc84_chunk_32` | `nodejs-fs.md` | 245-253（范围外） | `argument` | partial |
| 0 | `b9c22720dc84_chunk_35` | `nodejs-fs.md` | 1305-1313（范围外） | `argument` | partial |
| 0 | `b9c22720dc84_chunk_36` | `nodejs-fs.md` | 1610-1618（范围外） | `argument` | partial |
| 0 | `b9c22720dc84_chunk_37` | `nodejs-fs.md` | 694-702（范围外） | `argument` | partial |
| 0 | `b9c22720dc84_chunk_39` | `nodejs-fs.md` | 390-398（范围外） | `argument` | partial |
| 0 | `b9c22720dc84_chunk_41` | `nodejs-fs.md` | 912-920（范围外） | `argument` | partial |
| 0 | `b9c22720dc84_chunk_42` | `nodejs-fs.md` | 378-386（范围外） | `argument` | partial |
| 0 | `b9c22720dc84_chunk_45` | `nodejs-fs.md` | 503-511（范围外） | `argument` | partial |
| 0 | `b9c22720dc84_chunk_46` | `nodejs-fs.md` | 868-876（范围外） | `argument` | partial |
| 0 | `b9c22720dc84_chunk_47` | `nodejs-fs.md` | 1645-1653（范围外） | `argument` | partial |
| 0 | `b9c22720dc84_chunk_49` | `nodejs-fs.md` | 1650-1658（范围外） | `argument` | partial |
| 0 | `b9c22720dc84_chunk_50` | `nodejs-fs.md` | 725-733（范围外） | `argument` | partial |
| 0 | `b9c22720dc84_chunk_52` | `nodejs-fs.md` | 1192-1200（范围外） | `argument` | partial |
| 0 | `b9c22720dc84_chunk_53` | `nodejs-fs.md` | 1811-1819（范围外） | `argument` | partial |
| 0 | `b9c22720dc84_chunk_54` | `nodejs-fs.md` | 83-91（范围外） | `argument` | partial |
| 0 | `b9c22720dc84_chunk_55` | `nodejs-fs.md` | 37-45（范围外） | `argument` | partial |
| 0 | `b9c22720dc84_chunk_56` | `nodejs-fs.md` | 734-742（范围外） | `argument` | partial |
| 0 | `b9c22720dc84_chunk_57` | `nodejs-fs.md` | 484-492（范围外） | `argument` | partial |
| 0 | `b9c22720dc84_chunk_58` | `nodejs-fs.md` | 1432-1440（范围外） | `argument` | partial |
| 0 | `b9c22720dc84_chunk_60` | `nodejs-fs.md` | 410-418（范围外） | `argument` | partial |
| 0 | `b9c22720dc84_chunk_61` | `nodejs-fs.md` | 740-748（范围外） | `argument` | partial |
| 0 | `b9c22720dc84_chunk_62` | `nodejs-fs.md` | 1766-1774（范围外） | `argument` | partial |
| 0 | `b9c22720dc84_chunk_64` | `nodejs-fs.md` | 1662-1670（范围外） | `argument` | partial |
| 0 | `b9c22720dc84_chunk_65` | `nodejs-fs.md` | 135-143（范围外） | `argument` | partial |
| 0 | `b9c22720dc84_chunk_67` | `nodejs-fs.md` | 139-147（范围外） | `argument` | partial |
| 0 | `b9c22720dc84_chunk_68` | `nodejs-fs.md` | 83-91（范围外） | `argument` | partial |
| 0 | `b9c22720dc84_chunk_69` | `nodejs-fs.md` | 263-271（范围外） | `argument` | partial |
| 0 | `b9c22720dc84_chunk_70` | `nodejs-fs.md` | 190-198（范围外） | `argument` | partial |
| 0 | `b9c22720dc84_chunk_71` | `nodejs-fs.md` | 1747-1755（范围外） | `argument` | partial |
| 0 | `b9c22720dc84_chunk_72` | `nodejs-fs.md` | 625-633（范围外） | `argument` | partial |
| 0 | `b9c22720dc84_chunk_73` | `nodejs-fs.md` | 83-91（范围外） | `argument` | partial |
| 0 | `b9c22720dc84_chunk_74` | `nodejs-fs.md` | 145-153（范围外） | `argument` | partial |
| 0 | `b9c22720dc84_chunk_75` | `nodejs-fs.md` | 25-33（范围外） | `argument` | partial |
| 0 | `b9c22720dc84_chunk_76` | `nodejs-fs.md` | 761-769（范围外） | `argument` | partial |
| 0 | `b9c22720dc84_chunk_77` | `nodejs-fs.md` | 711-719（范围外） | `argument` | partial |
| 0 | `b9c22720dc84_chunk_78` | `nodejs-fs.md` | 449-457（范围外） | `argument` | partial |
| 0 | `b9c22720dc84_chunk_79` | `nodejs-fs.md` | 1245-1253（范围外） | `argument` | partial |
| 0 | `b9c22720dc84_chunk_80` | `nodejs-fs.md` | 638-646（范围外） | `argument` | partial |
| 0 | `b9c22720dc84_chunk_81` | `nodejs-fs.md` | 199-207（范围外） | `argument` | partial |
| 0 | `b9c22720dc84_chunk_82` | `nodejs-fs.md` | 1814-1822（范围外） | `argument` | partial |
| 0 | `b9c22720dc84_chunk_83` | `nodejs-fs.md` | 1078-1086（范围外） | `argument` | partial |
| 0 | `b9c22720dc84_chunk_84` | `nodejs-fs.md` | 83-91（范围外） | `argument` | partial |
| 0 | `b9c22720dc84_chunk_86` | `nodejs-fs.md` | 1265-1273（范围外） | `argument` | partial |
| 0 | `b9c22720dc84_chunk_87` | `nodejs-fs.md` | 284-292（范围外） | `argument` | partial |
| 0 | `b9c22720dc84_chunk_88` | `nodejs-fs.md` | 148-156（范围外） | `argument` | partial |
| 0 | `b9c22720dc84_chunk_89` | `nodejs-fs.md` | 193-201（范围外） | `argument` | partial |
| 0 | `b9c22720dc84_chunk_90` | `nodejs-fs.md` | 261-269（范围外） | `argument` | partial |
| 0 | `b9c22720dc84_chunk_91` | `nodejs-fs.md` | 430-438（范围外） | `argument` | partial |
| 0 | `b9c22720dc84_chunk_92` | `nodejs-fs.md` | 1461-1469（范围外） | `argument` | partial |
| 0 | `b9c22720dc84_chunk_93` | `nodejs-fs.md` | 1354-1362（范围外） | `argument` | partial |
| 0 | `b9c22720dc84_chunk_94` | `nodejs-fs.md` | 754-762（范围外） | `argument` | partial |
| 0 | `b9c22720dc84_chunk_95` | `nodejs-fs.md` | 1374-1382（范围外） | `argument` | partial |
| 0 | `b9c22720dc84_chunk_96` | `nodejs-fs.md` | 34-42（范围外） | `argument` | partial |
| 0 | `b9c22720dc84_chunk_97` | `nodejs-fs.md` | 83-91（范围外） | `argument` | partial |
| 0 | `b9c22720dc84_chunk_98` | `nodejs-fs.md` | 424-432（范围外） | `argument` | partial |
| 0 | `b9c22720dc84_chunk_99` | `nodejs-fs.md` | 83-91（范围外） | `argument` | partial |
| 0 | `b9c22720dc84_chunk_100` | `nodejs-fs.md` | 1087-1095（范围外） | `argument` | partial |
| 0 | `b9c22720dc84_chunk_102` | `nodejs-fs.md` | 561-569（范围外） | `argument` | partial |
| 0 | `b9c22720dc84_chunk_103` | `nodejs-fs.md` | 317-325（范围外） | `argument` | partial |
| 0 | `b9c22720dc84_chunk_104` | `nodejs-fs.md` | 1643-1651（范围外） | `argument` | partial |
| 0 | `b9c22720dc84_chunk_106` | `nodejs-fs.md` | 396-404（范围外） | `argument` | partial |
| 0 | `b9c22720dc84_chunk_108` | `nodejs-fs.md` | 82-90（范围外） | `argument` | partial |
| 0 | `b9c22720dc84_chunk_111` | `nodejs-fs.md` | 1326-1334（范围外） | `argument` | partial |
| 0 | `b9c22720dc84_chunk_112` | `nodejs-fs.md` | 407-415（范围外） | `argument` | partial |
| 0 | `b9c22720dc84_chunk_113` | `nodejs-fs.md` | 255-263（范围外） | `argument` | partial |
| 0 | `b9c22720dc84_chunk_115` | `nodejs-fs.md` | 810-818（范围外） | `argument` | partial |
| 0 | `b9c22720dc84_chunk_116` | `nodejs-fs.md` | 1118-1126（范围外） | `argument` | partial |
| 0 | `b9c22720dc84_chunk_121` | `nodejs-fs.md` | 1229-1237（范围外） | `argument` | partial |
| 0 | `b9c22720dc84_chunk_122` | `nodejs-fs.md` | 619-627（范围外） | `argument` | partial |
| 0 | `b9c22720dc84_chunk_123` | `nodejs-fs.md` | 49-57（范围外） | `argument` | partial |
| 0 | `b9c22720dc84_chunk_124` | `nodejs-fs.md` | 188-196（范围外） | `argument` | partial |
| 0 | `b9c22720dc84_chunk_125` | `nodejs-fs.md` | 529-537（范围外） | `argument` | partial |
| 0 | `b9c22720dc84_chunk_127` | `nodejs-fs.md` | 301-309（范围外） | `argument` | partial |
| 0 | `b9c22720dc84_chunk_130` | `nodejs-fs.md` | 1217-1225（范围外） | `argument` | partial |
| 0 | `b9c22720dc84_chunk_131` | `nodejs-fs.md` | 253-261（范围外） | `argument` | partial |
| 0 | `b9c22720dc84_chunk_134` | `nodejs-fs.md` | 1183-1191（范围外） | `argument` | partial |
| 0 | `b9c22720dc84_chunk_138` | `nodejs-fs.md` | 345-353（范围外） | `argument` | partial |
| 0 | `b9c22720dc84_chunk_140` | `nodejs-fs.md` | 630-638（范围外） | `argument` | partial |
| 0 | `b9c22720dc84_chunk_147` | `nodejs-fs.md` | 675-683（范围外） | `argument` | partial |
| 0 | `b9c22720dc84_chunk_153` | `nodejs-fs.md` | 298-306（范围外） | `argument` | partial |
| 0 | `b9c22720dc84_chunk_158` | `nodejs-fs.md` | 998-1006（范围外） | `argument` | partial |
| 0 | `2e79918eccf4_chunk_22` | `python-datetime-zh.md` | 1333-1341（范围外） | `argument` | partial |
| 0 | `2e79918eccf4_chunk_30` | `python-datetime-zh.md` | 169-177（范围外） | `argument` | partial |
| 0 | `81544765752f_chunk_2` | `python-whatsnew313-zh.md` | 1948-1956（范围外） | `argument` | partial |
| 0 | `81544765752f_chunk_6` | `python-whatsnew313-zh.md` | 1702-1710（范围外） | `argument` | partial |
| 0 | `81544765752f_chunk_21` | `python-whatsnew313-zh.md` | 762-770（范围外） | `ARGUMENT` | partial |
| 0 | `81544765752f_chunk_25` | `python-whatsnew313-zh.md` | 1189-1197（范围外） | `argument` | partial |
| 0 | `81544765752f_chunk_28` | `python-whatsnew313-zh.md` | 1206-1214（范围外） | `argument` | partial |
| 0 | `8b191b241b93_chunk_2` | `sqlite-lang.md` | 1089-1097（范围外） | `argument` | partial |
| 0 | `8b191b241b93_chunk_3` | `sqlite-lang.md` | 9-17（范围外） | `argument` | partial |
| 0 | `8b191b241b93_chunk_4` | `sqlite-lang.md` | 1119-1127（范围外） | `argument` | partial |
| 0 | `8b191b241b93_chunk_5` | `sqlite-lang.md` | 9-17（范围外） | `argument` | partial |
| 0 | `8b191b241b93_chunk_7` | `sqlite-lang.md` | 218-226（范围外） | `argument` | partial |
| 0 | `8b191b241b93_chunk_22` | `sqlite-lang.md` | 292-300（范围外） | `argument` | partial |
| 0 | `8b191b241b93_chunk_26` | `sqlite-lang.md` | 292-300（范围外） | `argument` | partial |
| 0 | `8b191b241b93_chunk_32` | `sqlite-lang.md` | 218-226（范围外） | `argument` | partial |
| 0 | `8b191b241b93_chunk_44` | `sqlite-lang.md` | 117-125（范围外） | `argument` | partial |
| 0 | `8b191b241b93_chunk_49` | `sqlite-lang.md` | 218-226（范围外） | `argument` | partial |
| 0 | `8b191b241b93_chunk_59` | `sqlite-lang.md` | 436-444（范围外） | `argument` | partial |
| 0 | `8b191b241b93_chunk_62` | `sqlite-lang.md` | 1048-1056（范围外） | `argument` | partial |
| 0 | `8b191b241b93_chunk_63` | `sqlite-lang.md` | 9-17（范围外） | `argument` | partial |
| 0 | `5927c70d0f8e_chunk_3` | `vue-guide-zh.md` | 1023-1031（范围外） | `argument` | partial |
| 0 | `5927c70d0f8e_chunk_5` | `vue-guide-zh.md` | 735-743（范围外） | `Argument` | partial |
| 0 | `5927c70d0f8e_chunk_6` | `vue-guide-zh.md` | 12-20（范围外） | `Argument` | partial |
| 0 | `5927c70d0f8e_chunk_7` | `vue-guide-zh.md` | 38-46（范围外） | `argument` | partial |
| 0 | `5927c70d0f8e_chunk_9` | `vue-guide-zh.md` | 1113-1121（范围外） | `argument` | partial |
| 0 | `5927c70d0f8e_chunk_23` | `vue-guide-zh.md` | 1231-1239（范围外） | `argument` | partial |
| 0 | `5927c70d0f8e_chunk_27` | `vue-guide-zh.md` | 1536-1544（范围外） | `argument` | partial |
| 1 | `c9fd20815ea8_chunk_0` | `python-glossary-zh.md` | 1846-1855（范围内） | `parameter` | partial |
| 1 | `c9fd20815ea8_chunk_1` | `python-glossary-zh.md` | 120-129（范围内） | `parameter` | partial |
| 1 | `c9fd20815ea8_chunk_7` | `python-glossary-zh.md` | 385-394（范围内） | `parameter` | partial |
| 1 | `c9fd20815ea8_chunk_11` | `python-glossary-zh.md` | 757-766（范围内） | `parameter` | partial |
| 1 | `c9fd20815ea8_chunk_14` | `python-glossary-zh.md` | 783-792（范围内） | `parameter` | partial |
| 1 | `b9c22720dc84_chunk_15` | `nodejs-fs.md` | 1121-1130（范围外） | `parameter` | partial |
| 1 | `b9c22720dc84_chunk_25` | `nodejs-fs.md` | 863-872（范围外） | `parameter` | partial |
| 1 | `b9c22720dc84_chunk_26` | `nodejs-fs.md` | 1278-1287（范围外） | `parameter` | partial |
| 1 | `b9c22720dc84_chunk_27` | `nodejs-fs.md` | 1041-1050（范围外） | `parameter` | partial |
| 1 | `b9c22720dc84_chunk_36` | `nodejs-fs.md` | 754-763（范围外） | `parameter` | partial |
| 1 | `b9c22720dc84_chunk_47` | `nodejs-fs.md` | 1872-1881（范围外） | `parameter` | partial |
| 1 | `b9c22720dc84_chunk_48` | `nodejs-fs.md` | 31-40（范围外） | `parameter` | partial |
| 1 | `b9c22720dc84_chunk_49` | `nodejs-fs.md` | 1774-1783（范围外） | `parameter` | partial |
| 1 | `b9c22720dc84_chunk_50` | `nodejs-fs.md` | 30-39（范围外） | `parameter` | partial |
| 1 | `b9c22720dc84_chunk_52` | `nodejs-fs.md` | 1321-1330（范围外） | `parameter` | partial |
| 1 | `b9c22720dc84_chunk_54` | `nodejs-fs.md` | 212-221（范围外） | `parameter` | partial |
| 1 | `b9c22720dc84_chunk_56` | `nodejs-fs.md` | 863-872（范围外） | `parameter` | partial |
| 1 | `b9c22720dc84_chunk_57` | `nodejs-fs.md` | 115-124（范围外） | `parameter` | partial |
| 1 | `b9c22720dc84_chunk_60` | `nodejs-fs.md` | 841-850（范围外） | `parameter` | partial |
| 1 | `b9c22720dc84_chunk_63` | `nodejs-fs.md` | 183-192（范围外） | `parameter` | partial |
| 1 | `b9c22720dc84_chunk_65` | `nodejs-fs.md` | 259-268（范围外） | `parameter` | partial |
| 1 | `b9c22720dc84_chunk_67` | `nodejs-fs.md` | 268-277（范围外） | `parameter` | partial |
| 1 | `b9c22720dc84_chunk_68` | `nodejs-fs.md` | 212-221（范围外） | `parameter` | partial |
| 1 | `b9c22720dc84_chunk_69` | `nodejs-fs.md` | 392-401（范围外） | `parameter` | partial |
| 1 | `b9c22720dc84_chunk_70` | `nodejs-fs.md` | 1414-1423（范围外） | `parameter` | partial |
| 1 | `b9c22720dc84_chunk_72` | `nodejs-fs.md` | 139-148（范围外） | `parameter` | partial |
| 1 | `b9c22720dc84_chunk_73` | `nodejs-fs.md` | 1045-1054（范围外） | `parameter` | partial |
| 1 | `b9c22720dc84_chunk_74` | `nodejs-fs.md` | 400-409（范围外） | `parameter` | partial |
| 1 | `b9c22720dc84_chunk_75` | `nodejs-fs.md` | 163-172（范围外） | `parameter` | partial |
| 1 | `b9c22720dc84_chunk_76` | `nodejs-fs.md` | 654-663（范围外） | `parameter` | partial |
| 1 | `b9c22720dc84_chunk_77` | `nodejs-fs.md` | 669-678（范围外） | `parameter` | partial |
| 1 | `b9c22720dc84_chunk_78` | `nodejs-fs.md` | 734-743（范围外） | `parameter` | partial |
| 1 | `b9c22720dc84_chunk_80` | `nodejs-fs.md` | 766-775（范围外） | `parameter` | partial |
| 1 | `b9c22720dc84_chunk_81` | `nodejs-fs.md` | 1193-1202（范围外） | `parameter` | partial |
| 1 | `b9c22720dc84_chunk_83` | `nodejs-fs.md` | 96-105（范围外） | `parameter` | partial |
| 1 | `b9c22720dc84_chunk_84` | `nodejs-fs.md` | 427-436（范围外） | `parameter` | partial |
| 1 | `b9c22720dc84_chunk_86` | `nodejs-fs.md` | 1394-1403（范围外） | `parameter` | partial |
| 1 | `b9c22720dc84_chunk_88` | `nodejs-fs.md` | 277-286（范围外） | `parameter` | partial |
| 1 | `b9c22720dc84_chunk_90` | `nodejs-fs.md` | 1142-1151（范围外） | `parameter` | partial |
| 1 | `b9c22720dc84_chunk_92` | `nodejs-fs.md` | 149-158（范围外） | `parameter` | partial |
| 1 | `b9c22720dc84_chunk_93` | `nodejs-fs.md` | 117-126（范围外） | `parameter` | partial |
| 1 | `b9c22720dc84_chunk_94` | `nodejs-fs.md` | 35-44（范围外） | `parameter` | partial |
| 1 | `b9c22720dc84_chunk_96` | `nodejs-fs.md` | 212-221（范围外） | `parameter` | partial |
| 1 | `b9c22720dc84_chunk_97` | `nodejs-fs.md` | 316-325（范围外） | `parameter` | partial |
| 1 | `b9c22720dc84_chunk_98` | `nodejs-fs.md` | 30-39（范围外） | `parameter` | partial |
| 1 | `b9c22720dc84_chunk_99` | `nodejs-fs.md` | 212-221（范围外） | `parameter` | partial |
| 1 | `b9c22720dc84_chunk_102` | `nodejs-fs.md` | 1360-1369（范围外） | `parameter` | partial |
| 1 | `b9c22720dc84_chunk_104` | `nodejs-fs.md` | 1770-1779（范围外） | `parameter` | partial |
| 1 | `b9c22720dc84_chunk_105` | `nodejs-fs.md` | 34-43（范围外） | `parameter` | partial |
| 1 | `b9c22720dc84_chunk_107` | `nodejs-fs.md` | 142-151（范围外） | `parameter` | partial |
| 1 | `b9c22720dc84_chunk_108` | `nodejs-fs.md` | 1262-1271（范围外） | `parameter` | partial |
| 1 | `b9c22720dc84_chunk_109` | `nodejs-fs.md` | 32-41（范围外） | `parameter` | partial |
| 1 | `b9c22720dc84_chunk_112` | `nodejs-fs.md` | 1290-1299（范围外） | `parameter` | partial |
| 1 | `b9c22720dc84_chunk_113` | `nodejs-fs.md` | 1269-1278（范围外） | `parameter` | partial |
| 1 | `b9c22720dc84_chunk_114` | `nodejs-fs.md` | 1346-1355（范围外） | `parameter` | partial |
| 1 | `b9c22720dc84_chunk_117` | `nodejs-fs.md` | 1257-1266（范围外） | `parameter` | partial |
| 1 | `b9c22720dc84_chunk_120` | `nodejs-fs.md` | 1207-1216（范围外） | `parameter` | partial |
| 1 | `b9c22720dc84_chunk_121` | `nodejs-fs.md` | 373-382（范围外） | `parameter` | partial |
| 1 | `b9c22720dc84_chunk_122` | `nodejs-fs.md` | 120-129（范围外） | `parameter` | partial |
| 1 | `b9c22720dc84_chunk_123` | `nodejs-fs.md` | 208-217（范围外） | `parameter` | partial |
| 1 | `b9c22720dc84_chunk_124` | `nodejs-fs.md` | 679-688（范围外） | `parameter` | partial |
| 1 | `b9c22720dc84_chunk_125` | `nodejs-fs.md` | 106-115（范围外） | `parameter` | partial |
| 1 | `b9c22720dc84_chunk_126` | `nodejs-fs.md` | 1119-1128（范围外） | `parameter` | partial |
| 1 | `b9c22720dc84_chunk_127` | `nodejs-fs.md` | 885-894（范围外） | `parameter` | partial |
| 1 | `b9c22720dc84_chunk_128` | `nodejs-fs.md` | 660-669（范围外） | `parameter` | partial |
| 1 | `b9c22720dc84_chunk_129` | `nodejs-fs.md` | 111-120（范围外） | `parameter` | partial |
| 1 | `b9c22720dc84_chunk_130` | `nodejs-fs.md` | 30-39（范围外） | `parameter` | partial |
| 1 | `b9c22720dc84_chunk_131` | `nodejs-fs.md` | 506-515（范围外） | `parameter` | partial |
| 1 | `b9c22720dc84_chunk_132` | `nodejs-fs.md` | 32-41（范围外） | `parameter` | partial |
| 1 | `b9c22720dc84_chunk_133` | `nodejs-fs.md` | 1088-1097（范围外） | `parameter` | partial |
| 1 | `b9c22720dc84_chunk_148` | `nodejs-fs.md` | 287-296（范围外） | `parameter` | partial |
| 1 | `2e79918eccf4_chunk_38` | `python-datetime-zh.md` | 1634-1643（范围外） | `parameter` | partial |
| 1 | `81544765752f_chunk_9` | `python-whatsnew313-zh.md` | 318-327（范围外） | `Parameter` | partial |
| 1 | `81544765752f_chunk_24` | `python-whatsnew313-zh.md` | 1770-1779（范围外） | `parameter` | partial |
| 1 | `86ef1bf559c5_chunk_14` | `rfc3986.txt` | 466-475（范围外） | `parameter` | partial |
| 1 | `86ef1bf559c5_chunk_36` | `rfc3986.txt` | 1017-1026（范围外） | `parameter` | partial |
| 1 | `86ef1bf559c5_chunk_63` | `rfc3986.txt` | 1037-1046（范围外） | `parameter` | partial |
| 1 | `86ef1bf559c5_chunk_66` | `rfc3986.txt` | 475-484（范围外） | `parameter` | partial |
| 1 | `8b191b241b93_chunk_2` | `sqlite-lang.md` | 912-921（范围外） | `parameter` | partial |
| 1 | `8b191b241b93_chunk_4` | `sqlite-lang.md` | 942-951（范围外） | `parameter` | partial |
| 1 | `8b191b241b93_chunk_7` | `sqlite-lang.md` | 41-50（范围外） | `parameter` | partial |
| 1 | `8b191b241b93_chunk_12` | `sqlite-lang.md` | 1429-1438（范围外） | `parameter` | partial |
| 1 | `8b191b241b93_chunk_13` | `sqlite-lang.md` | 1010-1019（范围外） | `parameter` | partial |
| 1 | `8b191b241b93_chunk_22` | `sqlite-lang.md` | 115-124（范围外） | `parameter` | partial |
| 1 | `8b191b241b93_chunk_26` | `sqlite-lang.md` | 115-124（范围外） | `parameter` | partial |
| 1 | `8b191b241b93_chunk_32` | `sqlite-lang.md` | 41-50（范围外） | `parameter` | partial |
| 1 | `8b191b241b93_chunk_49` | `sqlite-lang.md` | 41-50（范围外） | `parameter` | partial |
| 1 | `8b191b241b93_chunk_62` | `sqlite-lang.md` | 871-880（范围外） | `parameter` | partial |

### mixed-026（index 35，mixed / cross_document）

- query：中文教程把第 3 章叫做 Python 速览，英文教程叫 An Informal Introduction to Python，两版内容对应吗？
- relevant_source_ids：python-tutorial-zh.md, python-tutorial-en.md
- v4 Pro reject 理由：答案点1完全由证据直接支持：中文 chunk 显示章节标题 '3. Python 速览'，英文 chunk 显示标题 '3. An Informal Introduction to Python'，章节编号均为3，确认为同一章，标题为翻译关系。答案点2声称内容包含计算器、字符串、列表示例，但提供的 chunks 中仅有 'Python 用作计算器' 及其数字运算示例，缺少字符串和列表的示例证据，因此该点整体被评为 unsupported，导致答案不可接受。
- 第三轮 reject 理由：不可用（第三轮 reject 理由位于 human-review-pack.llm-filled.jsonl 与 llm-third-pass-report.md，不在本任务允许读取范围（仅 merged-adjudications.jsonl / selection-manifest.json / human-review-pack.jsonl / chunks.jsonl）；第三轮 decision=reject 已由 selection-manifest.disputed 集合确认。）

- 当前 evidence：`32c427fb50e2_chunk_2` / `python-tutorial-zh.md` / section 3. Python 速览 / snippet 「# 3. Python 速览¶…」
- 当前 evidence：`e564a122a7a2_chunk_5` / `python-tutorial-en.md` / section 3. An Informal Introduction to Python / snippet 「3. An Informal Introduction to Python…」

| 答案点 | v4 Pro 支持 | 匹配 | repair_feasibility | proposed_action |
|---|---|---|---|---|
| 0 对应：同一章，标题翻译不同 | direct_snippet | 0 / 0 | no_local_evidence_found | manual_semantic_adjudication_required |
| 1 内容均为非正式介绍（计算器、字符串、列表示例） | unsupported | 0 / 0 | no_local_evidence_found | remove_unsupported_answer_point |

### multi-014（index 47，zh / multi_turn）

- query：如果 from fibo import * 引入了不该引入的名字，教程建议怎么避免这种问题？
- relevant_source_ids：python-tutorial-zh.md
- v4 Pro reject 理由：第一个答案点“尽量不要使用 from ... import *”得到语料直接支持；第二个答案点“建议使用 from package import specific_submodule”在语料中未找到对应建议，语料仅展示从模块导入特定名称（如 from fibo import fib, fib2），未涉及包和子模块的特定建议。
- 第三轮 reject 理由：不可用（第三轮 reject 理由位于 human-review-pack.llm-filled.jsonl 与 llm-third-pass-report.md，不在本任务允许读取范围（仅 merged-adjudications.jsonl / selection-manifest.json / human-review-pack.jsonl / chunks.jsonl）；第三轮 decision=reject 已由 selection-manifest.disputed 集合确认。）

- 当前 evidence：`32c427fb50e2_chunk_31` / `python-tutorial-zh.md` / section 6.1.1 以脚本方式执行模块 / snippet 「这种方式会导入所有不以下划线 (
```
_
```
) 开头的名称。 大多数情况下，不要用这个功能，这种方式向解释器导入了一批未知的名称，可能会覆盖已经定义的…」

| 答案点 | v4 Pro 支持 | 匹配 | repair_feasibility | proposed_action |
|---|---|---|---|---|
| 0 尽量不要使用 from ... import * | direct_snippet | 4 / 1 | only_paraphrase_or_partial_evidence | manual_semantic_adjudication_required |
| 1 建议使用 from package import specific_submod | unsupported | 14 / 116 | exact_local_evidence_available | add_exact_evidence |

候选 span（chunk 内字符范围）：

| 答案点 | chunk_id | source_id | 范围 | 最短必要原文 | 类型 |
|---|---|---|---|---|---|
| 0 | `32c427fb50e2_chunk_31` | `python-tutorial-zh.md` | 198-206（范围内） | `import *` | partial |
| 0 | `32c427fb50e2_chunk_37` | `python-tutorial-zh.md` | 539-547（范围内） | `import *` | partial |
| 0 | `32c427fb50e2_chunk_38` | `python-tutorial-zh.md` | 774-783（范围内） | `.. import` | partial |
| 0 | `32c427fb50e2_chunk_66` | `python-tutorial-zh.md` | 1748-1756（范围内） | `import *` | partial |
| 0 | `b9c22720dc84_chunk_13` | `nodejs-fs.md` | 390-398（范围外） | `import *` | partial |
| 1 | `32c427fb50e2_chunk_31` | `python-tutorial-zh.md` | 1140-1148（范围内） | `import s` | partial |
| 1 | `32c427fb50e2_chunk_32` | `python-tutorial-zh.md` | 1523-1531（范围内） | `import s` | partial |
| 1 | `32c427fb50e2_chunk_33` | `python-tutorial-zh.md` | 8-16（范围内） | `import s` | partial |
| 1 | `32c427fb50e2_chunk_36` | `python-tutorial-zh.md` | 1372-1380（范围内） | `import s` | partial |
| 1 | `32c427fb50e2_chunk_37` | `python-tutorial-zh.md` | 210-229（范围内） | `from package import` | partial |
| 1 | `32c427fb50e2_chunk_38` | `python-tutorial-zh.md` | 321-359（范围内） | `from package import specific_submodule` | full |
| 1 | `32c427fb50e2_chunk_39` | `python-tutorial-zh.md` | 1109-1119（范围内） | `t specific` | partial |
| 1 | `32c427fb50e2_chunk_40` | `python-tutorial-zh.md` | 1849-1859（范围内） | `t specific` | partial |
| 1 | `32c427fb50e2_chunk_41` | `python-tutorial-zh.md` | 60-70（范围内） | `t specific` | partial |
| 1 | `32c427fb50e2_chunk_48` | `python-tutorial-zh.md` | 145-153（范围内） | `import s` | partial |
| 1 | `32c427fb50e2_chunk_67` | `python-tutorial-zh.md` | 150-158（范围内） | `import s` | partial |
| 1 | `32c427fb50e2_chunk_68` | `python-tutorial-zh.md` | 622-630（范围内） | `import s` | partial |
| 1 | `32c427fb50e2_chunk_71` | `python-tutorial-zh.md` | 1509-1518（范围内） | `Package I` | partial |
| 1 | `32c427fb50e2_chunk_73` | `python-tutorial-zh.md` | 607-616（范围内） | `Package I` | partial |
| 1 | `293d777c429b_chunk_3` | `art-of-war.txt` | 573-581（范围外） | `e import` | partial |
| 1 | `293d777c429b_chunk_6` | `art-of-war.txt` | 1269-1277（范围外） | `e import` | partial |
| 1 | `293d777c429b_chunk_15` | `art-of-war.txt` | 592-600（范围外） | `e import` | partial |
| 1 | `293d777c429b_chunk_59` | `art-of-war.txt` | 1139-1147（范围外） | `e import` | partial |
| 1 | `293d777c429b_chunk_62` | `art-of-war.txt` | 321-329（范围外） | `e import` | partial |
| 1 | `293d777c429b_chunk_87` | `art-of-war.txt` | 1465-1473（范围外） | `e import` | partial |
| 1 | `293d777c429b_chunk_109` | `art-of-war.txt` | 1388-1396（范围外） | `e import` | partial |
| 1 | `293d777c429b_chunk_148` | `art-of-war.txt` | 233-241（范围外） | `e import` | partial |
| 1 | `293d777c429b_chunk_199` | `art-of-war.txt` | 1609-1617（范围外） | `e
import` | partial |
| 1 | `b9c22720dc84_chunk_6` | `nodejs-fs.md` | 640-648（范围外） | `specific` | partial |
| 1 | `b9c22720dc84_chunk_12` | `nodejs-fs.md` | 1645-1653（范围外） | `specific` | partial |
| 1 | `b9c22720dc84_chunk_13` | `nodejs-fs.md` | 28-36（范围外） | `specific` | partial |
| 1 | `b9c22720dc84_chunk_23` | `nodejs-fs.md` | 495-504（范围外） | `t specifi` | partial |
| 1 | `b9c22720dc84_chunk_24` | `nodejs-fs.md` | 1388-1396（范围外） | `specific` | partial |
| 1 | `b9c22720dc84_chunk_28` | `nodejs-fs.md` | 401-410（范围外） | `t specifi` | partial |
| 1 | `b9c22720dc84_chunk_29` | `nodejs-fs.md` | 591-600（范围外） | `t specifi` | partial |
| 1 | `b9c22720dc84_chunk_30` | `nodejs-fs.md` | 926-935（范围外） | `t specifi` | partial |
| 1 | `b9c22720dc84_chunk_31` | `nodejs-fs.md` | 236-244（范围外） | `t specif` | partial |
| 1 | `b9c22720dc84_chunk_33` | `nodejs-fs.md` | 1399-1408（范围外） | `t specifi` | partial |
| 1 | `b9c22720dc84_chunk_37` | `nodejs-fs.md` | 519-527（范围外） | `specific` | partial |
| 1 | `b9c22720dc84_chunk_40` | `nodejs-fs.md` | 373-382（范围外） | `t specifi` | partial |
| 1 | `b9c22720dc84_chunk_48` | `nodejs-fs.md` | 1181-1190（范围外） | `t specifi` | partial |
| 1 | `b9c22720dc84_chunk_50` | `nodejs-fs.md` | 760-769（范围外） | `t specifi` | partial |
| 1 | `b9c22720dc84_chunk_53` | `nodejs-fs.md` | 937-946（范围外） | `t specifi` | partial |
| 1 | `b9c22720dc84_chunk_56` | `nodejs-fs.md` | 250-258（范围外） | `specific` | partial |
| 1 | `b9c22720dc84_chunk_58` | `nodejs-fs.md` | 40-49（范围外） | `t specifi` | partial |
| 1 | `b9c22720dc84_chunk_62` | `nodejs-fs.md` | 1259-1268（范围外） | `t specifi` | partial |
| 1 | `b9c22720dc84_chunk_64` | `nodejs-fs.md` | 1905-1914（范围外） | `t specifi` | partial |
| 1 | `b9c22720dc84_chunk_69` | `nodejs-fs.md` | 821-829（范围外） | `specific` | partial |
| 1 | `b9c22720dc84_chunk_77` | `nodejs-fs.md` | 1447-1455（范围外） | `specific` | partial |
| 1 | `b9c22720dc84_chunk_84` | `nodejs-fs.md` | 1861-1870（范围外） | `t specifi` | partial |
| 1 | `b9c22720dc84_chunk_85` | `nodejs-fs.md` | 206-214（范围外） | `specific` | partial |
| 1 | `b9c22720dc84_chunk_100` | `nodejs-fs.md` | 1155-1164（范围外） | `t specifi` | partial |
| 1 | `b9c22720dc84_chunk_101` | `nodejs-fs.md` | 481-489（范围外） | `specific` | partial |
| 1 | `b9c22720dc84_chunk_110` | `nodejs-fs.md` | 299-308（范围外） | `t specifi` | partial |
| 1 | `b9c22720dc84_chunk_113` | `nodejs-fs.md` | 290-299（范围外） | `t specifi` | partial |
| 1 | `b9c22720dc84_chunk_114` | `nodejs-fs.md` | 623-632（范围外） | `t specifi` | partial |
| 1 | `b9c22720dc84_chunk_115` | `nodejs-fs.md` | 1519-1528（范围外） | `t specifi` | partial |
| 1 | `b9c22720dc84_chunk_118` | `nodejs-fs.md` | 1738-1746（范围外） | `specific` | partial |
| 1 | `b9c22720dc84_chunk_124` | `nodejs-fs.md` | 1562-1570（范围外） | `specific` | partial |
| 1 | `b9c22720dc84_chunk_137` | `nodejs-fs.md` | 1905-1913（范围外） | `specific` | partial |
| 1 | `b9c22720dc84_chunk_142` | `nodejs-fs.md` | 867-875（范围外） | `specific` | partial |
| 1 | `b9c22720dc84_chunk_144` | `nodejs-fs.md` | 938-946（范围外） | `specific` | partial |
| 1 | `b9c22720dc84_chunk_147` | `nodejs-fs.md` | 1490-1498（范围外） | `specific` | partial |
| 1 | `b9c22720dc84_chunk_153` | `nodejs-fs.md` | 538-546（范围外） | `specific` | partial |
| 1 | `b9c22720dc84_chunk_155` | `nodejs-fs.md` | 824-832（范围外） | `specific` | partial |
| 1 | `b9c22720dc84_chunk_158` | `nodejs-fs.md` | 1245-1253（范围外） | `specific` | partial |
| 1 | `2e79918eccf4_chunk_2` | `python-datetime-zh.md` | 615-623（范围外） | `e import` | partial |
| 1 | `2e79918eccf4_chunk_6` | `python-datetime-zh.md` | 343-352（范围外） | `t specifi` | partial |
| 1 | `2e79918eccf4_chunk_14` | `python-datetime-zh.md` | 253-262（范围外） | `t specifi` | partial |
| 1 | `2e79918eccf4_chunk_29` | `python-datetime-zh.md` | 1089-1097（范围外） | `specific` | partial |
| 1 | `81544765752f_chunk_14` | `python-whatsnew313-zh.md` | 350-358（范围外） | `import s` | partial |
| 1 | `81544765752f_chunk_17` | `python-whatsnew313-zh.md` | 1572-1582（范围外） | `age import` | partial |
| 1 | `993955159403_chunk_0` | `react-learn-zh.md` | 1866-1874（范围外） | `e
import` | partial |
| 1 | `993955159403_chunk_1` | `react-learn-zh.md` | 158-166（范围外） | `e
import` | partial |
| 1 | `993955159403_chunk_25` | `react-learn-zh.md` | 202-210（范围外） | `import S` | partial |
| 1 | `86ef1bf559c5_chunk_0` | `rfc3986.txt` | 611-620（范围外） | `t specifi` | partial |
| 1 | `86ef1bf559c5_chunk_6` | `rfc3986.txt` | 283-291（范围外） | `specific` | partial |
| 1 | `86ef1bf559c5_chunk_7` | `rfc3986.txt` | 953-961（范围外） | `specific` | partial |
| 1 | `86ef1bf559c5_chunk_8` | `rfc3986.txt` | 1310-1318（范围外） | `specific` | partial |
| 1 | `86ef1bf559c5_chunk_9` | `rfc3986.txt` | 153-161（范围外） | `specific` | partial |
| 1 | `86ef1bf559c5_chunk_10` | `rfc3986.txt` | 5-13（范围外） | `specific` | partial |
| 1 | `86ef1bf559c5_chunk_11` | `rfc3986.txt` | 1171-1179（范围外） | `specific` | partial |
| 1 | `86ef1bf559c5_chunk_13` | `rfc3986.txt` | 482-490（范围外） | `e import` | partial |
| 1 | `86ef1bf559c5_chunk_13` | `rfc3986.txt` | 736-744（范围外） | `specific` | partial |
| 1 | `86ef1bf559c5_chunk_14` | `rfc3986.txt` | 275-283（范围外） | `specific` | partial |
| 1 | `86ef1bf559c5_chunk_15` | `rfc3986.txt` | 330-338（范围外） | `specific` | partial |
| 1 | `86ef1bf559c5_chunk_17` | `rfc3986.txt` | 1522-1532（范围外） | `t specific` | partial |
| 1 | `86ef1bf559c5_chunk_18` | `rfc3986.txt` | 259-267（范围外） | `specific` | partial |
| 1 | `86ef1bf559c5_chunk_19` | `rfc3986.txt` | 1338-1346（范围外） | `specific` | partial |
| 1 | `86ef1bf559c5_chunk_20` | `rfc3986.txt` | 1370-1378（范围外） | `specific` | partial |
| 1 | `86ef1bf559c5_chunk_21` | `rfc3986.txt` | 145-153（范围外） | `specific` | partial |
| 1 | `86ef1bf559c5_chunk_22` | `rfc3986.txt` | 1528-1536（范围外） | `specific` | partial |
| 1 | `86ef1bf559c5_chunk_26` | `rfc3986.txt` | 1178-1189（范围外） | `t
   specif` | partial |
| 1 | `86ef1bf559c5_chunk_27` | `rfc3986.txt` | 86-95（范围外） | `t specifi` | partial |
| 1 | `86ef1bf559c5_chunk_28` | `rfc3986.txt` | 742-750（范围外） | `specific` | partial |
| 1 | `86ef1bf559c5_chunk_32` | `rfc3986.txt` | 547-555（范围外） | `specific` | partial |
| 1 | `86ef1bf559c5_chunk_33` | `rfc3986.txt` | 5-13（范围外） | `specific` | partial |
| 1 | `86ef1bf559c5_chunk_36` | `rfc3986.txt` | 1475-1483（范围外） | `specific` | partial |
| 1 | `86ef1bf559c5_chunk_38` | `rfc3986.txt` | 652-660（范围外） | `specific` | partial |
| 1 | `86ef1bf559c5_chunk_39` | `rfc3986.txt` | 159-167（范围外） | `specific` | partial |
| 1 | `86ef1bf559c5_chunk_40` | `rfc3986.txt` | 430-438（范围外） | `specific` | partial |
| 1 | `86ef1bf559c5_chunk_42` | `rfc3986.txt` | 66-74（范围外） | `specific` | partial |
| 1 | `86ef1bf559c5_chunk_45` | `rfc3986.txt` | 1711-1721（范围外） | `t specific` | partial |
| 1 | `86ef1bf559c5_chunk_54` | `rfc3986.txt` | 359-367（范围外） | `specific` | partial |
| 1 | `86ef1bf559c5_chunk_57` | `rfc3986.txt` | 1506-1514（范围外） | `specific` | partial |
| 1 | `86ef1bf559c5_chunk_58` | `rfc3986.txt` | 992-1000（范围外） | `specific` | partial |
| 1 | `86ef1bf559c5_chunk_59` | `rfc3986.txt` | 878-886（范围外） | `specific` | partial |
| 1 | `86ef1bf559c5_chunk_60` | `rfc3986.txt` | 152-160（范围外） | `specific` | partial |
| 1 | `86ef1bf559c5_chunk_61` | `rfc3986.txt` | 13-21（范围外） | `specific` | partial |
| 1 | `86ef1bf559c5_chunk_62` | `rfc3986.txt` | 586-594（范围外） | `specific` | partial |
| 1 | `86ef1bf559c5_chunk_63` | `rfc3986.txt` | 52-61（范围外） | `t specifi` | partial |
| 1 | `86ef1bf559c5_chunk_64` | `rfc3986.txt` | 1184-1192（范围外） | `specific` | partial |
| 1 | `86ef1bf559c5_chunk_67` | `rfc3986.txt` | 273-281（范围外） | `specific` | partial |
| 1 | `86ef1bf559c5_chunk_68` | `rfc3986.txt` | 711-719（范围外） | `specific` | partial |
| 1 | `86ef1bf559c5_chunk_75` | `rfc3986.txt` | 936-944（范围外） | `Specific` | partial |
| 1 | `86ef1bf559c5_chunk_78` | `rfc3986.txt` | 61-69（范围外） | `specific` | partial |
| 1 | `86ef1bf559c5_chunk_80` | `rfc3986.txt` | 266-274（范围外） | `specific` | partial |
| 1 | `86ef1bf559c5_chunk_81` | `rfc3986.txt` | 757-765（范围外） | `specific` | partial |
| 1 | `86ef1bf559c5_chunk_85` | `rfc3986.txt` | 267-275（范围外） | `specific` | partial |
| 1 | `8b191b241b93_chunk_9` | `sqlite-lang.md` | 806-814（范围外） | `t specif` | partial |
| 1 | `8b191b241b93_chunk_17` | `sqlite-lang.md` | 1049-1058（范围外） | `t specifi` | partial |
| 1 | `8b191b241b93_chunk_19` | `sqlite-lang.md` | 458-466（范围外） | `specific` | partial |
| 1 | `8b191b241b93_chunk_30` | `sqlite-lang.md` | 760-768（范围外） | `specific` | partial |
| 1 | `8b191b241b93_chunk_37` | `sqlite-lang.md` | 390-398（范围外） | `specific` | partial |
| 1 | `8b191b241b93_chunk_38` | `sqlite-lang.md` | 1590-1599（范围外） | `t specifi` | partial |
| 1 | `8b191b241b93_chunk_40` | `sqlite-lang.md` | 578-586（范围外） | `specific` | partial |
| 1 | `8b191b241b93_chunk_45` | `sqlite-lang.md` | 1205-1213（范围外） | `specific` | partial |
| 1 | `8b191b241b93_chunk_60` | `sqlite-lang.md` | 557-565（范围外） | `specific` | partial |
| 1 | `5927c70d0f8e_chunk_19` | `vue-guide-zh.md` | 1818-1826（范围外） | `specific` | partial |
| 1 | `5927c70d0f8e_chunk_20` | `vue-guide-zh.md` | 112-120（范围外） | `specific` | partial |
| 1 | `5927c70d0f8e_chunk_21` | `vue-guide-zh.md` | 166-174（范围外） | `e import` | partial |
| 1 | `5927c70d0f8e_chunk_22` | `vue-guide-zh.md` | 1329-1337（范围外） | `specific` | partial |
| 1 | `5927c70d0f8e_chunk_27` | `vue-guide-zh.md` | 907-915（范围外） | `e import` | partial |
| 1 | `5927c70d0f8e_chunk_31` | `vue-guide-zh.md` | 711-719（范围外） | `specific` | partial |
| 1 | `5927c70d0f8e_chunk_32` | `vue-guide-zh.md` | 1249-1259（范围外） | `t specific` | partial |

## 汇总

| repair_feasibility | 计数 |
|---|---|
| exact_local_evidence_available | 1 |
| no_local_evidence_found | 3 |
| only_paraphrase_or_partial_evidence | 5 |

| proposed_action | 计数 |
|---|---|
| add_exact_evidence | 1 |
| manual_semantic_adjudication_required | 7 |
| remove_unsupported_answer_point | 1 |

## 限制与结论

- 第三轮 reject 理由位于 llm-filled pack / third-pass report，不在本任务允许读取范围，未输出（已如实记录）
- 候选 span 是归一化逐字匹配；改写/翻译/语义等价关系超出机械审计能力，已路由到 `manual_semantic_adjudication_required`
- `remove_unsupported_answer_point` / `narrow_answer_point` 是机械建议，采纳与否须由人工裁决
- 本审计**不是自动修复、不是人工审核、不构成 v2.1 准入决策**；未修改任何 draft / human pack / chunks / 审阅产物 / 生产配置，未生成 overlay
