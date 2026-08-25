# v2.0.7 盲态自动审阅门禁报告

> **状态**：AUTOMATED_REVIEW_GATE_BLOCKED — 22 条未通过
> **结论**：未生成 automated overlay。
> **声明**：本报告是用户授权的 LLM 自动审阅结果，不是人工审核。

## 决策统计

- confirmed：126
- reject：22
- needs_followup：0
- 确认率：126/148

## 未通过 case 清单

| case_id | decision | 理由 |
|---|---|---|
| en-029 | reject | The evidence only contains the section heading and introductory sentence, not the actual ownership rules. The acceptable_answer_points are not supported by the  |
| en-042 | reject | Answer point 1 is unsupported: the provided evidence only defines a URI, not the generic URI syntax. Answer point 2 is unsupported: the evidence only mentions ' |
| en-044 | reject | Answer point 1 ('Rust: ownership rules govern value passing') is unsupported because the evidence only mentions ownership rules without describing how data is p |
| en-049 | reject | Answer point 0 ('Rust: String type owns heap memory') is not supported by the provided evidence, which only mentions the String type in the context of ownership |
| en-050 | reject | The acceptable_answer_point claims 'RFC 3986 defines URI generic syntax (file URLs follow it)', but no evidence directly states that file URLs follow RFC 3986 o |
| en-051 | reject | Answer point 0 ('Python: lists as mutable sequences') is unsupported because the provided evidence only shows list creation and mutation examples, not the expli |
| mixed-026 | reject | acceptable_answer_points 中的答案点“对应：同一章，标题翻译不同”未在 evidence 中得到直接支持或忠实转述。evidence 仅提供了中文标题“Python 速览”和英文标题“An Informal Introduction to Python”，但未提供任何证据表明两者是同一章或存在对 |
| mixed-027 | reject | should_refuse=false 合理，因为 query 可部分回答。但 acceptable_answer_points[0] 声称“术语表：原子化操作不可再分”，该表述在 evidence[1] 中直接支持；acceptable_answer_points[1] 声称“SQLite 语法页仅列出 begin- |
| mixed-028 | reject | should_refuse=false 合理，因为 query 询问 Vue 响应式与 React state 的共同点，但提供的 evidence 仅包含 React state 的定义，未提及 Vue 或任何共同点，因此 acceptable_answer_points 中的 'state' 无法构成有效答案。答案 |
| mixed-029 | reject | acceptable_answer_points 中的“一致”在 evidence 中仅作为 raw_evidence_span 出现，但该 span 在 chunk 原文中位于“CPython 没有一致应用针对迭代器定义 __iter__() 的要求”一句，与 query 所问的 free-threaded buil |
| mixed-033 | reject | evidence 中缺少 static type checker 的定义，且两个 evidence 条目重复指向 stdlib 定义，未覆盖第一个答案点。 |
| multi-019 | reject | acceptable_answer_points 中的答案点“可以（示例演示直接写数据库文件绕过约束）”在提供的 evidence 中未得到支持。evidence 仅描述了 CHECK 约束的定义，未提及通过直接修改数据库文件绕过约束的示例或可能性。 |
| multi-030 | reject | acceptable_answer_points 中的 '数字（把 Python 当作计算器）' 未在 evidence raw span 中出现，且 evidence 仅提及交互模式下的变量用法，未直接或等价表述该节内容为 '数字（把 Python 当作计算器）'。 |
| zh-023 | reject | 证据仅包含数字'10'，无上下文表明其与range(10)生成值数量相关，答案点'10'无证据支持。 |
| zh-026 | reject | acceptable_answer_points 仅包含 'del'，但 evidence 中仅出现 'del' 字样，未提供任何关于 '从列表中删除切片' 的语义支持。query 询问删除切片，而证据仅为孤立单词，无法构成答案点。 |
| zh-029 | reject | acceptable_answer_points 中的 'json' 过于模糊，无法构成一个完整的答案点。证据中仅出现 'json' 字样，但未明确说明是哪个标准库模块。 |
| zh-036 | reject | should_refuse应为true，因为提供的语料中未包含模块编译版本缓存目录的信息，但标注为false。acceptable_answer_points中的“目录”过于模糊，无法构成有效答案点。 |
| zh-040 | reject | evidence仅包含一个目录片段，未列出完整章节名；acceptable_answer_points中的'模块'、'输入与输出'、'错误和异常'均未在evidence raw span中直接出现或等价转述，故答案点无证据支持。 |
| zh-042 | reject | acceptable_answer_points 中的答案点 'word（示例为 'Python' 的切片）' 未在提供的 evidence 中得到支持。evidence 仅包含切片索引的解释性文本，未提及示例单词 'Python'。 |
| zh-045 | reject | acceptable_answer_points 中的两个答案点均未得到 evidence 支持。evidence[0] 仅提及 Python 语言特性，未涉及 GIL；evidence[1] 仅说明 3.13 新特性文档在自由线程模式语境下提到 GIL，但未提供教程正文中 GIL 的语境信息。因此，答案点 0 和 1 |
| zh-052 | reject | acceptable_answer_points 的两个答案点均未得到 evidence 支持。答案点 0 声称 SQLite 语法页仅以 begin-stmt 出现，但 evidence[1] 的 raw span 中同时包含 begin-stmt 和 commit-stmt，无法支持“仅”的断言。答案点 1 声称  |
| zh-054 | reject | query 要求比较术语表中 'free-threaded build' 条目与 3.13 新特性中 '自由线程' 章节对 '--disable-gil' 的描述是否一致，但提供的 evidence 仅包含一个 '一致' 的 raw span，且 chunks 中仅包含 'interpreted'、'interpret |

## 结论

存在 22 条 reject / needs_followup，不得生成 automated overlay；修复后须重新运行本脚本。
