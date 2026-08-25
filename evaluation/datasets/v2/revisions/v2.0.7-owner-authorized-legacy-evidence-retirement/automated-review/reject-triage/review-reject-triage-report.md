# v2.0.7 automated-review reject root-cause triage（只读分流）

> **本任务是只读分流，不是修复**：不修改 candidate draft/evidence/chunks/review，不调用 LLM/API、不联网、不生成 overlay / active metadata / split / v2.1 文件。
> 唯一事实来源：`automated-review.jsonl`（canonical，confirmed=126 / reject=22 / needs_followup=0，non-confirmed=22）。
> 模型 rationale 不作为事实：每条分类均对照 candidate raw evidence、完整 chunk 原文与答案点逐字可重建性。

## 分流总览

| 类别 | 计数 | case_id |
|---|---|---|
| exact_evidence_present_but_review_semantic_disagrees | 8 | mixed-028, mixed-029, multi-030, zh-023, zh-026, zh-029, zh-036, zh-054 |
| partial_or_paraphrase_only | 5 | en-029, en-044, en-050, multi-019, zh-052 |
| answer_point_overclaims_available_evidence | 0 | - |
| evidence_scope_insufficient_but_same_source_candidate_exists | 6 | en-042, en-049, en-051, mixed-033, zh-040, zh-042 |
| no_direct_support_in_declared_source | 2 | mixed-026, zh-045 |
| cross_source_or_cross_document_coverage_gap | 0 | - |
| refusal_label_or_schema_inconsistency | 0 | - |
| review_contract_or_model_semantics_inconsistency | 1 | mixed-027 |
| unresolved_requires_owner_judgment | 0 | - |

- 全部 22 条均需所有者决策，机械可修复：0 条
- 零答案点风险：5 条 （en-029, mixed-026, multi-019, zh-042, zh-045）
- v2.0.5/v2.0.6 曾改动（仅标记，不预设结论）：mixed-028, mixed-029, zh-023, zh-026, zh-029, zh-036, zh-054
- 未生成 overlay；gate 保持 BLOCKED；未进入 v2.1。

## 22 条逐条分流

### en-029 — partial_or_paraphrase_only（sub_type=language_mismatch）

- 模型 decision：`reject`；refusal_assessment：`not_applicable`
- 模型 rationale：The evidence only contains the section heading and introductory sentence, not the actual ownership rules. The acceptable_answer_points are not supported by the provided evidence.
- 模型 assessment：[{"answer_point_index": 0, "assessment": "unsupported", "evidence_refs": [0]}, {"answer_point_index": 1, "assessment": "unsupported", "evidence_refs": [0]}]
- query：What are the ownership rules in the Rust book?
- 答案点：["每条值有唯一所有者", "所有者离开作用域时值被丢弃"]
- 本地证据状态（in_evidence / 同源 / 跨源）：{"evidence_status_by_point": {"0": "none", "1": "none"}, "same_source_status_by_point": {"0": "none", "1": "none"}, "other_source_status_by_point": {"0": "none", "1": "none"}, "language_mismatch_by_point": {"0": true, "1": true}, "zero_answer_point_risk": true}
  - 答案点 0：in_evidence=none（覆盖 0%），in_relevant=none，same_source=none，other_source=none，language_mismatch=True
  - 答案点 1：in_evidence=none（覆盖 0%），in_relevant=none，same_source=none，other_source=none，language_mismatch=True

### en-042 — evidence_scope_insufficient_but_same_source_candidate_exists（sub_type=-）

- 模型 decision：`reject`；refusal_assessment：`not_applicable`
- 模型 rationale：Answer point 1 is unsupported: the provided evidence only defines a URI, not the generic URI syntax. Answer point 2 is unsupported: the evidence only mentions 'File URL paths' as a heading, not that Node.js fs accepts them.
- 模型 assessment：[{"answer_point_index": 0, "assessment": "unsupported", "evidence_refs": [0]}, {"answer_point_index": 1, "assessment": "unsupported", "evidence_refs": [1]}]
- query：RFC 3986 defines URI syntax — does the Node.js fs doc support file URL paths?
- 答案点：["RFC 3986 defines generic URI syntax", "Node.js fs accepts file URL paths"]
- 本地证据状态（in_evidence / 同源 / 跨源）：{"evidence_status_by_point": {"0": "none", "1": "partial"}, "same_source_status_by_point": {"0": "partial", "1": "partial"}, "other_source_status_by_point": {"0": "partial", "1": "partial"}, "language_mismatch_by_point": {"0": false, "1": false}, "zero_answer_point_risk": false}
  - 答案点 0：in_evidence=none（覆盖 0%），in_relevant=partial，same_source=partial，other_source=partial，language_mismatch=False
  - 答案点 1：in_evidence=partial（覆盖 42%），in_relevant=partial，same_source=partial，other_source=partial，language_mismatch=False
  - scope 候选（同 source，未修改 scope）：
    - 86ef1bf559c5_chunk_0 [1854:1862) `RFC 3986`
    - 86ef1bf559c5_chunk_25 [796:814) `generic URI syntax`
    - b9c22720dc84_chunk_13 [2:16) `File URL paths`
    - b9c22720dc84_chunk_6 [614:628) `File URL paths`

### en-044 — partial_or_paraphrase_only（sub_type=partial_coverage）

- 模型 decision：`reject`；refusal_assessment：`not_applicable`
- 模型 rationale：Answer point 1 ('Rust: ownership rules govern value passing') is unsupported because the evidence only mentions ownership rules without describing how data is passed between components. Answer point 2 ('Node.js: buffers passed by reference') is directly supported by evidence 1. The query is answerable, so should_refuse=false is correct.
- 模型 assessment：[{"answer_point_index": 0, "assessment": "unsupported", "evidence_refs": [0]}, {"answer_point_index": 1, "assessment": "directly_supported", "evidence_refs": [1]}]
- query：Where does each document describe how data is passed between components — Rust ownership vs Node.js fs buffers?
- 答案点：["Rust: ownership rules govern value passing", "Node.js: buffers passed by reference"]
- 本地证据状态（in_evidence / 同源 / 跨源）：{"evidence_status_by_point": {"0": "partial", "1": "partial"}, "same_source_status_by_point": {"0": "partial", "1": "partial"}, "other_source_status_by_point": {"0": "partial", "1": "partial"}, "language_mismatch_by_point": {"0": false, "1": false}, "zero_answer_point_risk": false}
  - 答案点 0：in_evidence=partial（覆盖 36%），in_relevant=partial，same_source=partial，other_source=partial，language_mismatch=False
  - 答案点 1：in_evidence=partial（覆盖 25%），in_relevant=partial，same_source=partial，other_source=partial，language_mismatch=False
  - scope 候选（同 source，未修改 scope）：
    - 4f9001ca8c15_chunk_37 [4:19) `Ownership Rules`
    - 4f9001ca8c15_chunk_32 [761:772) `: ownership`
    - b9c22720dc84_chunk_22 [57:66) `reference`
    - b9c22720dc84_chunk_20 [882:891) `reference`

### en-049 — evidence_scope_insufficient_but_same_source_candidate_exists（sub_type=-）

- 模型 decision：`reject`；refusal_assessment：`not_applicable`
- 模型 rationale：Answer point 0 ('Rust: String type owns heap memory') is not supported by the provided evidence, which only mentions the String type in the context of ownership rules without explicitly stating it owns heap memory. Answer point 1 ('SQLite: TEXT affinity for string columns') is directly supported by evidence showing TEXT affinity for 'TEXT' declared type.
- 模型 assessment：[{"answer_point_index": 0, "assessment": "unsupported", "evidence_refs": [0]}, {"answer_point_index": 1, "assessment": "directly_supported", "evidence_refs": [1]}]
- query：The Rust book introduces the String type — which SQLite type name maps to a string?
- 答案点：["Rust: String type owns heap memory", "SQLite: TEXT affinity for string columns"]
- 本地证据状态（in_evidence / 同源 / 跨源）：{"evidence_status_by_point": {"0": "none", "1": "partial"}, "same_source_status_by_point": {"0": "partial", "1": "partial"}, "other_source_status_by_point": {"0": "partial", "1": "partial"}, "language_mismatch_by_point": {"0": false, "1": false}, "zero_answer_point_risk": false}
  - 答案点 0：in_evidence=none（覆盖 0%），in_relevant=none，same_source=partial，other_source=partial，language_mismatch=False
  - 答案点 1：in_evidence=partial（覆盖 20%），in_relevant=partial，same_source=partial，other_source=partial，language_mismatch=False
  - scope 候选（同 source，未修改 scope）：
    - 4f9001ca8c15_chunk_5 [550:561) `string type`
    - 8b191b241b93_chunk_12 [11:19) `Affinity`
    - 8b191b241b93_chunk_13 [259:267) `affinity`

### en-050 — partial_or_paraphrase_only（sub_type=partial_coverage）

- 模型 decision：`reject`；refusal_assessment：`not_applicable`
- 模型 rationale：The acceptable_answer_point claims 'RFC 3986 defines URI generic syntax (file URLs follow it)', but no evidence directly states that file URLs follow RFC 3986 or that RFC 3986 defines file URL syntax. Evidence 0 only shows RFC 3986 exists and defines generic URI syntax; Evidence 1 only mentions 'File URL paths' in a Node.js context without linking to any RFC. The answer point is unsupported.
- 模型 assessment：[{"answer_point_index": 0, "assessment": "unsupported", "evidence_refs": []}]
- query：Node.js fs supports file URL paths — which RFC defines the syntax of those URLs?
- 答案点：["RFC 3986 defines URI generic syntax (file URLs follow it)"]
- 本地证据状态（in_evidence / 同源 / 跨源）：{"evidence_status_by_point": {"0": "partial"}, "same_source_status_by_point": {"0": "partial"}, "other_source_status_by_point": {"0": "partial"}, "language_mismatch_by_point": {"0": false}, "zero_answer_point_risk": false}
  - 答案点 0：in_evidence=partial（覆盖 14%），in_relevant=partial，same_source=partial，other_source=partial，language_mismatch=False
  - scope 候选（同 source，未修改 scope）：
    - 86ef1bf559c5_chunk_0 [1854:1862) `RFC 3986`
    - 86ef1bf559c5_chunk_3 [75:83) `RFC 3986`

### en-051 — evidence_scope_insufficient_but_same_source_candidate_exists（sub_type=-）

- 模型 decision：`reject`；refusal_assessment：`not_applicable`
- 模型 rationale：Answer point 0 ('Python: lists as mutable sequences') is unsupported because the provided evidence only shows list creation and mutation examples, not the explicit statement that lists are mutable sequences. Answer point 1 ('SQLite: SELECT returns rows with a fixed number of columns') is directly supported by evidence 0.
- 模型 assessment：[{"answer_point_index": 0, "assessment": "unsupported", "evidence_refs": [1]}, {"answer_point_index": 1, "assessment": "directly_supported", "evidence_refs": [0]}]
- query：Python lists are sequences; how does SQLite model rows of a table as data?
- 答案点：["Python: lists as mutable sequences", "SQLite: SELECT returns rows with a fixed number of columns"]
- 本地证据状态（in_evidence / 同源 / 跨源）：{"evidence_status_by_point": {"0": "none", "1": "partial"}, "same_source_status_by_point": {"0": "partial", "1": "partial"}, "other_source_status_by_point": {"0": "partial", "1": "partial"}, "language_mismatch_by_point": {"0": false, "1": false}, "zero_answer_point_risk": false}
  - 答案点 0：in_evidence=none（覆盖 0%），in_relevant=partial，same_source=partial，other_source=partial，language_mismatch=False
  - 答案点 1：in_evidence=partial（覆盖 43%），in_relevant=partial，same_source=partial，other_source=partial，language_mismatch=False
  - scope 候选（同 source，未修改 scope）：
    - e564a122a7a2_chunk_14 [1526:1534) `sequence`
    - e564a122a7a2_chunk_56 [1693:1704) `e sequences`
    - 8b191b241b93_chunk_24 [123:148) `a fixed number of columns`
    - 8b191b241b93_chunk_12 [1351:1368) `number of columns`

### mixed-026 — no_direct_support_in_declared_source（sub_type=-）

- 模型 decision：`reject`；refusal_assessment：`not_applicable`
- 模型 rationale：acceptable_answer_points 中的答案点“对应：同一章，标题翻译不同”未在 evidence 中得到直接支持或忠实转述。evidence 仅提供了中文标题“Python 速览”和英文标题“An Informal Introduction to Python”，但未提供任何证据表明两者是同一章或存在对应关系。
- 模型 assessment：[{"answer_point_index": 0, "assessment": "unsupported", "evidence_refs": [0, 1]}]
- query：中文教程把第 3 章叫做 Python 速览，英文教程叫 An Informal Introduction to Python，两版内容对应吗？
- 答案点：["对应：同一章，标题翻译不同"]
- 本地证据状态（in_evidence / 同源 / 跨源）：{"evidence_status_by_point": {"0": "none"}, "same_source_status_by_point": {"0": "none"}, "other_source_status_by_point": {"0": "none"}, "language_mismatch_by_point": {"0": false}, "zero_answer_point_risk": true}
  - 答案点 0：in_evidence=none（覆盖 0%），in_relevant=none，same_source=none，other_source=none，language_mismatch=False

### mixed-027 — review_contract_or_model_semantics_inconsistency（sub_type=supported_assessment_with_reject）

- 模型 decision：`reject`；refusal_assessment：`not_applicable`
- 模型 rationale：should_refuse=false 合理，因为 query 可部分回答。但 acceptable_answer_points[0] 声称“术语表：原子化操作不可再分”，该表述在 evidence[1] 中直接支持；acceptable_answer_points[1] 声称“SQLite 语法页仅列出 begin-stmt，未展开事务原子性说明”，该表述在 evidence[0] 中直接支持。然而，这两个答案点均未回答 query 的核心问题“SQLite 文档里事务的原子性体现在哪”，属于答非所问，不应作为 acceptable_answer_points。
- 模型 assessment：[{"answer_point_index": 0, "assessment": "directly_supported", "evidence_refs": [1]}, {"answer_point_index": 1, "assessment": "directly_supported", "evidence_refs": [0]}]
- query：术语表说 atomic operation 不可再分，SQLite 文档里事务的原子性体现在哪？
- 答案点：["术语表：原子化操作不可再分", "SQLite 语法页仅列出 begin-stmt，未展开事务原子性说明"]
- 本地证据状态（in_evidence / 同源 / 跨源）：{"evidence_status_by_point": {"0": "none", "1": "partial"}, "same_source_status_by_point": {"0": "none", "1": "none"}, "other_source_status_by_point": {"0": "none", "1": "none"}, "language_mismatch_by_point": {"0": false, "1": false}, "zero_answer_point_risk": false}
  - 答案点 0：in_evidence=none（覆盖 0%），in_relevant=none，same_source=none，other_source=none，language_mismatch=False
  - 答案点 1：in_evidence=partial（覆盖 29%），in_relevant=partial，same_source=none，other_source=none，language_mismatch=False
  - scope 候选（同 source，未修改 scope）：
    - 8b191b241b93_chunk_1 [185:195) `begin-stmt`

### mixed-028 — exact_evidence_present_but_review_semantic_disagrees（sub_type=-）

- 模型 decision：`reject`；refusal_assessment：`not_applicable`
- 模型 rationale：should_refuse=false 合理，因为 query 询问 Vue 响应式与 React state 的共同点，但提供的 evidence 仅包含 React state 的定义，未提及 Vue 或任何共同点，因此 acceptable_answer_points 中的 'state' 无法构成有效答案。答案点 'state' 在 evidence 中仅作为标题出现，未提供任何关于共同点的信息，属于 unsupported。
- 模型 assessment：[{"answer_point_index": 0, "assessment": "unsupported", "evidence_refs": [0]}]
- query：Vue 的响应式（reactive）和 React 的 state 在概念上有什么共同点？
- 答案点：["state"]
- 本地证据状态（in_evidence / 同源 / 跨源）：{"evidence_status_by_point": {"0": "exact"}, "same_source_status_by_point": {"0": "exact"}, "other_source_status_by_point": {"0": "exact"}, "language_mismatch_by_point": {"0": false}, "zero_answer_point_risk": false}
  - 答案点 0：in_evidence=exact（覆盖 100%），in_relevant=exact，same_source=exact，other_source=exact，language_mismatch=False
  - scope 候选（同 source，未修改 scope）：
    - 993955159403_chunk_7 [136:141) `State`
    - 993955159403_chunk_6 [540:545) `e）。你可`

### mixed-029 — exact_evidence_present_but_review_semantic_disagrees（sub_type=-）

- 模型 decision：`reject`；refusal_assessment：`not_applicable`
- 模型 rationale：acceptable_answer_points 中的“一致”在 evidence 中仅作为 raw_evidence_span 出现，但该 span 在 chunk 原文中位于“CPython 没有一致应用针对迭代器定义 __iter__() 的要求”一句，与 query 所问的 free-threaded build 和 3.13 自由线程章节的构建方式说法是否一致完全无关。该答案点无证据支持。
- 模型 assessment：[{"answer_point_index": 0, "assessment": "unsupported", "evidence_refs": [0]}]
- query：术语表里 free-threaded build 与 3.13 新特性的自由线程章节，构建方式说法是否一致？
- 答案点：["一致"]
- 本地证据状态（in_evidence / 同源 / 跨源）：{"evidence_status_by_point": {"0": "exact"}, "same_source_status_by_point": {"0": "exact"}, "other_source_status_by_point": {"0": "exact"}, "language_mismatch_by_point": {"0": false}, "zero_answer_point_risk": false}
  - 答案点 0：in_evidence=exact（覆盖 100%），in_relevant=none，same_source=exact，other_source=exact，language_mismatch=False
  - scope 候选（同 source，未修改 scope）：
    - c9fd20815ea8_chunk_10 [1381:1383) `一致`

### mixed-033 — evidence_scope_insufficient_but_same_source_candidate_exists（sub_type=-）

- 模型 decision：`reject`；refusal_assessment：`not_applicable`
- 模型 rationale：evidence 中缺少 static type checker 的定义，且两个 evidence 条目重复指向 stdlib 定义，未覆盖第一个答案点。
- 模型 assessment：[{"answer_point_index": 0, "assessment": "unsupported", "evidence_refs": []}, {"answer_point_index": 1, "assessment": "directly_supported", "evidence_refs": [0]}]
- query：术语表里 static type checker 和 stdlib 分别指什么？
- 答案点：["static type checker 是查找类型问题的外部工具", "stdlib 是标准库（standard library）的缩写"]
- 本地证据状态（in_evidence / 同源 / 跨源）：{"evidence_status_by_point": {"0": "none", "1": "partial"}, "same_source_status_by_point": {"0": "partial", "1": "partial"}, "other_source_status_by_point": {"0": "partial", "1": "partial"}, "language_mismatch_by_point": {"0": false, "1": false}, "zero_answer_point_risk": false}
  - 答案点 0：in_evidence=none（覆盖 0%），in_relevant=partial，same_source=partial，other_source=partial，language_mismatch=False
  - 答案点 1：in_evidence=partial（覆盖 50%），in_relevant=partial，same_source=partial，other_source=partial，language_mismatch=False
  - scope 候选（同 source，未修改 scope）：
    - c9fd20815ea8_chunk_18 [0:19) `static type checker`
    - c9fd20815ea8_chunk_17 [1697:1716) `static type checker`
    - c9fd20815ea8_chunk_18 [119:135) `standard library`
    - c9fd20815ea8_chunk_14 [286:302) `standard library`

### multi-019 — partial_or_paraphrase_only（sub_type=language_mismatch）

- 模型 decision：`reject`；refusal_assessment：`not_applicable`
- 模型 rationale：acceptable_answer_points 中的答案点“可以（示例演示直接写数据库文件绕过约束）”在提供的 evidence 中未得到支持。evidence 仅描述了 CHECK 约束的定义，未提及通过直接修改数据库文件绕过约束的示例或可能性。
- 模型 assessment：[{"answer_point_index": 0, "assessment": "unsupported", "evidence_refs": [0]}]
- query：Can the database file be modified externally to bypass a CHECK constraint?
- 答案点：["可以（示例演示直接写数据库文件绕过约束）"]
- 本地证据状态（in_evidence / 同源 / 跨源）：{"evidence_status_by_point": {"0": "none"}, "same_source_status_by_point": {"0": "none"}, "other_source_status_by_point": {"0": "none"}, "language_mismatch_by_point": {"0": true}, "zero_answer_point_risk": true}
  - 答案点 0：in_evidence=none（覆盖 0%），in_relevant=none，same_source=none，other_source=none，language_mismatch=True

### multi-030 — exact_evidence_present_but_review_semantic_disagrees（sub_type=-）

- 模型 decision：`reject`；refusal_assessment：`not_applicable`
- 模型 rationale：acceptable_answer_points 中的 '数字（把 Python 当作计算器）' 未在 evidence raw span 中出现，且 evidence 仅提及交互模式下的变量用法，未直接或等价表述该节内容为 '数字（把 Python 当作计算器）'。
- 模型 assessment：[{"answer_point_index": 0, "assessment": "unsupported", "evidence_refs": [0]}]
- query：中文教程 3.1.1 节讲的是什么内容？
- 答案点：["数字（把 Python 当作计算器）"]
- 本地证据状态（in_evidence / 同源 / 跨源）：{"evidence_status_by_point": {"0": "exact"}, "same_source_status_by_point": {"0": "exact"}, "other_source_status_by_point": {"0": "none"}, "language_mismatch_by_point": {"0": false}, "zero_answer_point_risk": false}
  - 答案点 0：in_evidence=exact（覆盖 78%），in_relevant=exact，same_source=exact，other_source=none，language_mismatch=False
  - scope 候选（同 source，未修改 scope）：
    - 32c427fb50e2_chunk_3 [31:45) `把 Python 当作计算器`
    - 32c427fb50e2_chunk_2 [1824:1838) `把 Python 当作计算器`

### zh-023 — exact_evidence_present_but_review_semantic_disagrees（sub_type=-）

- 模型 decision：`reject`；refusal_assessment：`not_applicable`
- 模型 rationale：证据仅包含数字'10'，无上下文表明其与range(10)生成值数量相关，答案点'10'无证据支持。
- 模型 assessment：[{"answer_point_index": 0, "assessment": "unsupported", "evidence_refs": [0]}]
- query：教程中 range(10) 会生成几个值？
- 答案点：["10"]
- 本地证据状态（in_evidence / 同源 / 跨源）：{"evidence_status_by_point": {"0": "exact"}, "same_source_status_by_point": {"0": "exact"}, "other_source_status_by_point": {"0": "exact"}, "language_mismatch_by_point": {"0": false}, "zero_answer_point_risk": false}
  - 答案点 0：in_evidence=exact（覆盖 100%），in_relevant=exact，same_source=exact，other_source=exact，language_mismatch=False
  - scope 候选（同 source，未修改 scope）：
    - 32c427fb50e2_chunk_10 [290:292) `10`
    - 32c427fb50e2_chunk_0 [1594:1596) `10`

### zh-026 — exact_evidence_present_but_review_semantic_disagrees（sub_type=-）

- 模型 decision：`reject`；refusal_assessment：`not_applicable`
- 模型 rationale：acceptable_answer_points 仅包含 'del'，但 evidence 中仅出现 'del' 字样，未提供任何关于 '从列表中删除切片' 的语义支持。query 询问删除切片，而证据仅为孤立单词，无法构成答案点。
- 模型 assessment：[{"answer_point_index": 0, "assessment": "unsupported", "evidence_refs": [0]}]
- query：教程里说，从列表中删除切片可以用什么语句？
- 答案点：["del"]
- 本地证据状态（in_evidence / 同源 / 跨源）：{"evidence_status_by_point": {"0": "exact"}, "same_source_status_by_point": {"0": "exact"}, "other_source_status_by_point": {"0": "exact"}, "language_mismatch_by_point": {"0": false}, "zero_answer_point_risk": false}
  - 答案点 0：in_evidence=exact（覆盖 100%），in_relevant=exact，same_source=exact，other_source=exact，language_mismatch=False
  - scope 候选（同 source，未修改 scope）：
    - 32c427fb50e2_chunk_25 [168:171) `del`
    - 32c427fb50e2_chunk_0 [1712:1715) `del`

### zh-029 — exact_evidence_present_but_review_semantic_disagrees（sub_type=-）

- 模型 decision：`reject`；refusal_assessment：`not_applicable`
- 模型 rationale：acceptable_answer_points 中的 'json' 过于模糊，无法构成一个完整的答案点。证据中仅出现 'json' 字样，但未明确说明是哪个标准库模块。
- 模型 assessment：[{"answer_point_index": 0, "assessment": "unsupported", "evidence_refs": [0]}]
- query：教程中提到，用哪个标准库模块可以把结构化数据保存成 JSON 格式？
- 答案点：["json"]
- 本地证据状态（in_evidence / 同源 / 跨源）：{"evidence_status_by_point": {"0": "exact"}, "same_source_status_by_point": {"0": "exact"}, "other_source_status_by_point": {"0": "exact"}, "language_mismatch_by_point": {"0": false}, "zero_answer_point_risk": false}
  - 答案点 0：in_evidence=exact（覆盖 100%），in_relevant=exact，same_source=exact，other_source=exact，language_mismatch=False
  - scope 候选（同 source，未修改 scope）：
    - 32c427fb50e2_chunk_45 [18:22) `json`
    - 32c427fb50e2_chunk_1 [341:345) `json`

### zh-036 — exact_evidence_present_but_review_semantic_disagrees（sub_type=-）

- 模型 decision：`reject`；refusal_assessment：`not_applicable`
- 模型 rationale：should_refuse应为true，因为提供的语料中未包含模块编译版本缓存目录的信息，但标注为false。acceptable_answer_points中的“目录”过于模糊，无法构成有效答案点。
- 模型 assessment：[{"answer_point_index": 0, "assessment": "unsupported", "evidence_refs": [0]}]
- query：模块的编译版本缓存在哪个目录里？
- 答案点：["目录"]
- 本地证据状态（in_evidence / 同源 / 跨源）：{"evidence_status_by_point": {"0": "exact"}, "same_source_status_by_point": {"0": "exact"}, "other_source_status_by_point": {"0": "exact"}, "language_mismatch_by_point": {"0": false}, "zero_answer_point_risk": false}
  - 答案点 0：in_evidence=exact（覆盖 100%），in_relevant=exact，same_source=exact，other_source=exact，language_mismatch=False
  - scope 候选（同 source，未修改 scope）：
    - 32c427fb50e2_chunk_32 [44:46) `目录`
    - 32c427fb50e2_chunk_0 [1984:1986) `目录`

### zh-040 — evidence_scope_insufficient_but_same_source_candidate_exists（sub_type=-）

- 模型 decision：`reject`；refusal_assessment：`not_applicable`
- 模型 rationale：evidence仅包含一个目录片段，未列出完整章节名；acceptable_answer_points中的'模块'、'输入与输出'、'错误和异常'均未在evidence raw span中直接出现或等价转述，故答案点无证据支持。
- 模型 assessment：[{"answer_point_index": 0, "assessment": "unsupported", "evidence_refs": []}, {"answer_point_index": 1, "assessment": "unsupported", "evidence_refs": []}, {"answer_point_index": 2, "assessment": "unsupported", "evidence_refs": []}]
- query：教程一共包含哪些章节？（说出至少三个章节名）
- 答案点：["模块", "输入与输出", "错误和异常"]
- 本地证据状态（in_evidence / 同源 / 跨源）：{"evidence_status_by_point": {"0": "exact", "1": "none", "2": "none"}, "same_source_status_by_point": {"0": "exact", "1": "exact", "2": "exact"}, "other_source_status_by_point": {"0": "exact", "1": "none", "2": "exact"}, "language_mismatch_by_point": {"0": false, "1": false, "2": false}, "zero_answer_point_risk": false}
  - 答案点 0：in_evidence=exact（覆盖 100%），in_relevant=exact，same_source=exact，other_source=exact，language_mismatch=False
  - 答案点 1：in_evidence=none（覆盖 0%），in_relevant=exact，same_source=exact，other_source=none，language_mismatch=False
  - 答案点 2：in_evidence=none（覆盖 0%），in_relevant=exact，same_source=exact，other_source=exact，language_mismatch=False
  - scope 候选（同 source，未修改 scope）：
    - 32c427fb50e2_chunk_1 [5:7) `模块`
    - 32c427fb50e2_chunk_0 [35:37) `模块`
    - 32c427fb50e2_chunk_1 [187:192) `输入与输出`
    - 32c427fb50e2_chunk_2 [207:212) `输入与输出`

### zh-042 — evidence_scope_insufficient_but_same_source_candidate_exists（sub_type=-）

- 模型 decision：`reject`；refusal_assessment：`not_applicable`
- 模型 rationale：acceptable_answer_points 中的答案点 'word（示例为 'Python' 的切片）' 未在提供的 evidence 中得到支持。evidence 仅包含切片索引的解释性文本，未提及示例单词 'Python'。
- 模型 assessment：[{"answer_point_index": 0, "assessment": "unsupported", "evidence_refs": [0]}]
- query：教程里演示字符串切片时，用的是什么单词作为示例？
- 答案点：["word（示例为 'Python' 的切片）"]
- 本地证据状态（in_evidence / 同源 / 跨源）：{"evidence_status_by_point": {"0": "none"}, "same_source_status_by_point": {"0": "partial"}, "other_source_status_by_point": {"0": "partial"}, "language_mismatch_by_point": {"0": false}, "zero_answer_point_risk": true}
  - 答案点 0：in_evidence=none（覆盖 0%），in_relevant=partial，same_source=partial，other_source=partial，language_mismatch=False
  - scope 候选（同 source，未修改 scope）：
    - 32c427fb50e2_chunk_5 [28:36) `'Python'`
    - 32c427fb50e2_chunk_4 [492:500) `'Python'`

### zh-045 — no_direct_support_in_declared_source（sub_type=-）

- 模型 decision：`reject`；refusal_assessment：`not_applicable`
- 模型 rationale：acceptable_answer_points 中的两个答案点均未得到 evidence 支持。evidence[0] 仅提及 Python 语言特性，未涉及 GIL；evidence[1] 仅说明 3.13 新特性文档在自由线程模式语境下提到 GIL，但未提供教程正文中 GIL 的语境信息。因此，答案点 0 和 1 均为 unsupported。
- 模型 assessment：[{"answer_point_index": 0, "assessment": "unsupported", "evidence_refs": []}, {"answer_point_index": 1, "assessment": "unsupported", "evidence_refs": []}]
- query：教程正文和 3.13 新特性文档里都出现了 GIL 这个词，它们各自在什么语境下提到它？
- 答案点：["3.13 新特性文档在自由线程模式语境下提到 GIL", "教程正文中未讨论 GIL（仅代码示例可能含英文术语）"]
- 本地证据状态（in_evidence / 同源 / 跨源）：{"evidence_status_by_point": {"0": "none", "1": "none"}, "same_source_status_by_point": {"0": "none", "1": "none"}, "other_source_status_by_point": {"0": "none", "1": "none"}, "language_mismatch_by_point": {"0": false, "1": false}, "zero_answer_point_risk": true}
  - 答案点 0：in_evidence=none（覆盖 0%），in_relevant=none，same_source=none，other_source=none，language_mismatch=False
  - 答案点 1：in_evidence=none（覆盖 0%），in_relevant=none，same_source=none，other_source=none，language_mismatch=False

### zh-052 — partial_or_paraphrase_only（sub_type=language_mismatch）

- 模型 decision：`reject`；refusal_assessment：`not_applicable`
- 模型 rationale：acceptable_answer_points 的两个答案点均未得到 evidence 支持。答案点 0 声称 SQLite 语法页仅以 begin-stmt 出现，但 evidence[1] 的 raw span 中同时包含 begin-stmt 和 commit-stmt，无法支持“仅”的断言。答案点 1 声称 PG 教程第 3 章有专门 Transactions 小节，但 evidence[0] 来自 postgresql-tutorial.md 且 raw span 仅涉及事务概念解释，未提及“第 3 章”或“专门小节”。
- 模型 assessment：[{"answer_point_index": 0, "assessment": "unsupported", "evidence_refs": [1]}, {"answer_point_index": 1, "assessment": "unsupported", "evidence_refs": [0]}]
- query：SQLite 与 PostgreSQL 文档中，对"事务"一词的出现位置有什么差异？
- 答案点：["SQLite 语法页仅以 begin-stmt 出现在语法清单", "PG 教程第 3 章有专门 Transactions 小节"]
- 本地证据状态（in_evidence / 同源 / 跨源）：{"evidence_status_by_point": {"0": "partial", "1": "none"}, "same_source_status_by_point": {"0": "none", "1": "partial"}, "other_source_status_by_point": {"0": "none", "1": "none"}, "language_mismatch_by_point": {"0": true, "1": true}, "zero_answer_point_risk": false}
  - 答案点 0：in_evidence=partial（覆盖 32%），in_relevant=partial，same_source=none，other_source=none，language_mismatch=True
  - 答案点 1：in_evidence=none（覆盖 0%），in_relevant=partial，same_source=partial，other_source=none，language_mismatch=True
  - scope 候选（同 source，未修改 scope）：
    - 8b191b241b93_chunk_1 [185:195) `begin-stmt`
    - 761b22915b5e_chunk_11 [1127:1138) `transaction`
    - 761b22915b5e_chunk_0 [1672:1684) `Transactions`

### zh-054 — exact_evidence_present_but_review_semantic_disagrees（sub_type=-）

- 模型 decision：`reject`；refusal_assessment：`not_applicable`
- 模型 rationale：query 要求比较术语表中 'free-threaded build' 条目与 3.13 新特性中 '自由线程' 章节对 '--disable-gil' 的描述是否一致，但提供的 evidence 仅包含一个 '一致' 的 raw span，且 chunks 中仅包含 'interpreted'、'interpreter shutdown'、'iterable'、'iterator'、'key' 等术语条目，完全没有 'free-threaded build'、'自由线程' 或 '--disable-gil' 的相关内容。因此，acceptable_answer_points 中的 '一致' 无法从 evidence 中得到任何支持，属于 unsupported。
- 模型 assessment：[{"answer_point_index": 0, "assessment": "unsupported", "evidence_refs": []}]
- query：术语表中 free-threaded build 条目与 3.13 新特性中的自由线程章节，对 --disable-gil 的描述是否一致？
- 答案点：["一致"]
- 本地证据状态（in_evidence / 同源 / 跨源）：{"evidence_status_by_point": {"0": "exact"}, "same_source_status_by_point": {"0": "exact"}, "other_source_status_by_point": {"0": "exact"}, "language_mismatch_by_point": {"0": false}, "zero_answer_point_risk": false}
  - 答案点 0：in_evidence=exact（覆盖 100%），in_relevant=none，same_source=exact，other_source=exact，language_mismatch=False
  - scope 候选（同 source，未修改 scope）：
    - c9fd20815ea8_chunk_10 [1381:1383) `一致`


## 数据质量（等价确定性检查）

- completeness：canonical 148 / issues 22 / evidence 161 / draft 148
- uniqueness / referential_integrity / continuity / consistency：全部通过（详见 data-quality-report.json）
- skill 说明：data-analytics:analyze-data-quality skill 在本环境中不可用（不在已安装 skills 列表内，无法加载）；已按任务约束实施等价的确定性质量检查（完整性 / 唯一性 / 引用完整性 / 连续性 / 一致性），全部为机械复算，无 LLM 参与。

## SHA 链

- canonical（automated-review.jsonl）：`cb95b7a67725e8175a4734044b41668d943998c799773e1b71a5a53bc00ed42b`
- issues（automated-review-issues.jsonl）：`ea2e6d02231f1005786f55eaae094f0f65818dcdb3dbdc0f108fe9a07ec4058f`
- review manifest.json：`c0e75274dcd83969b3505ae7095030aa46f873e5177a17cd8656f9aff99dc672`
- candidate manifest.json：`33a95a30e463296125627e03d66c33818670969c268c582c3e6e593763b7d3da`
- draft-after.jsonl：`9d56d339f47bb2aff1591973e7bcb162ff4b1a562f210e446875bfaa08a78c28`
- evidence-after.jsonl：`6f0546ba64ae9398394d97e3e58cd2fca3f56ad64164688b74345d2d41fd7b00`
- draft（v2-cases-draft.jsonl）：`3c4fd10ad581cba478266efc02a7c6e57b899254b4e2fc7912f66eb5dba4efcc`
- chunks（chunks.jsonl）：`a23d739aa9876b54cd197d32f16138e9799c74a1a1c6717bb9d232fb6a06d772`

## 声明

- 未调用任何 LLM/API，未联网；模型 rationale 仅原样记录，分类依据为本地 raw 文本事实
- 未修改任何输入数据（draft / chunks / 148 条 decision / evidence / issues / manifest / pack）
- 未生成 overlay / active metadata / split / v2.1 产物，无 draft-after.jsonl / evidence-after.jsonl / 修复文件
- 未读取历史审阅结论、split/dev/holdout、锁配置或评测结果
- 未 stage / commit / push
