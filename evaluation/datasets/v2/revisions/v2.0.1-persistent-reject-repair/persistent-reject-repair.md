# v2 持续 reject 最小证据修复报告（v2.0.1）

> 本报告为**机械、确定性**的证据修复（依据 persistent-reject-evidence-audit 的候选 span）；**不代表人工审核、人工批准或 v2.1 准入**。

## 一、修改的 case 与逐答案点 before/after

| case_id | 答案点 | before | after | 证据变更 |
|---|---|---|---|---|
| en-052 | 全部 | PostgreSQL: transaction durability (logged to disk)；Rust: ownership rules guarantee memory safety → PostgreSQL: transaction durability (logged to disk) | PostgreSQL: transaction durability (logged to disk) | 无 |
| en-055 | 全部 | & 运算符（借用/引用） → The `&` operator creates a reference (e.g., `&s1`) | The `&` operator creates a reference (e.g., `&s1`) | 4f9001ca8c15_chunk_49 字符 1424..1467 |
| mixed-016 | 全部 | argument 译为 参数；parameter 为另一术语表条目（形参） → argument — 参数；parameter — 形参 | argument — 参数；parameter — 形参 | c9fd20815ea8_chunk_14 字符 783..798 |
| mixed-026 | 全部 | 对应：同一章，标题翻译不同；内容均为非正式介绍（计算器、字符串、列表示例） → 对应：同一章，标题翻译不同 | 对应：同一章，标题翻译不同 | 无 |
| multi-014 | 全部 | （不变） | 尽量不要使用 from ... import *；建议使用 from package import specific_submodule | 32c427fb50e2_chunk_38 字符 321..359 |

## 二、新增证据（逐字可定位）

| case_id | chunk_id | source_id | 字符范围 | 最短必要原文 |
|---|---|---|---|---|
| multi-014 | 32c427fb50e2_chunk_38 | python-tutorial-zh.md | 321..359 | `from package import specific_submodule` |
| mixed-016 | c9fd20815ea8_chunk_14 | python-glossary-zh.md | 783..798 | `parameter -- 形参` |
| en-055 | 4f9001ca8c15_chunk_49 | rust-book-core.md | 1424..1467 | `The `&s1` syntax lets us create a reference` |

## 三、数据质量校验（五维）

- 完整性：全部答案点有证据 （True）；无证据答案点 []。
- 唯一性：重复 chunk []；重复答案点 []。
- 引用完整性：chunk 全部存在（True）；chunk_id 列表一致（True）。
- 连续性：snippet 全部连续（True）。
- 一致性：source 全部一致（True）。
  - en-052: {}
  - en-055: {"answer_point_0": {"core_has_ampersand": true, "core_has_reference": true, "core_has_create": true, "answer_point_has_ampersand": true, "answer_point_has_reference": true}}
  - mixed-016: {"answer_point_0": {"glossary_form": true, "evidence_text": "argument 参数 参数会被赋值给函数体中对应的局部变量。有关赋值规则参见 调用 一节。根据语法，任何表达式都可用来表示一个参数；最终算出的值会被赋给对应的局部变量。\n 另参见 parameter 术语表条目"}, "answer_point_1": {"glossary_form": true, "evidence_text": "parameter 形参 parameter -- 形参"}}
  - mixed-026: {}
  - multi-014: {"answer_point_1": {"core_in_answer_point": true, "coverage": 0.8974}}

## 四、派生与封印

- 空白 human-review pack 已重生成（150 行，三个人工字段仍全空）；旧 pack 字节快照见 revision 目录。
- pack fail-closed 校验：通过。
- case-freeze / split-lock：case 集合与分组不变；lock 校验 通过；未改写历史 lock（无需更新）。
- chunks.jsonl、原始第三轮填写副本、历史语义仲裁/审计产物均未修改。

## 五、限制与结论

- 本修复仅依据审计定位的本地证据，为机械修改；add_exact_evidence / remove_unsupported_answer_point / narrow_answer_point 均为审计建议，修复结果须经人工裁决。
- 5 条定点机器复审见 targeted-post-repair-machine-review/（MACHINE_REVIEWED_DIAGNOSTIC_ONLY）。
- 结论：**不构成人工终审、人工批准或 v2.1 准入。**

