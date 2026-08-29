# v2 人工终审问题清单报告

> 存在 reject / needs_followup：**未生成可用于评测的正式 overlay**，
> 不得进入 v2.1。以下问题需人工复核后重新填写并再次导入。

## 计数（全量，不按划分分析）

- confirmed：142
- reject：6
- needs_followup：2

## 阻断 case 清单

| case_id | decision | reviewer | notes |
|---|---|---|---|
| en-044 | reject | zcode-agent-2026-08-29 | 答案点1「Rust: ownership rules govern value passing」未被证据chunk 4f9001ca8c15_chunk_37（4.1所有权三规则）直接支持：该chunk只讲值有唯一所有者/离开作用域被丢弃，未涉及跨组件传值；传值/移动语义在语料chunk 41(Variables and Data Interacting with Move)/43但未被引用。答案点2已被b9c22720dc84_chunk_22支持。 |
| en-048 | reject | zcode-agent-2026-08-29 | query问「哪条SQLite语句使用OVER子句」，但两个答案点均未回答该问题（仅说PG由OVER决定、SQLite语法图含over-clause）；证据chunk 8b191b241b93_chunk_8的over-clause语法图未标注所属语句，无法从证据确证「SELECT使用OVER」。 |
| en-052 | reject | zcode-agent-2026-08-29 | 跨文档问题要求比较两个文档各自的保证，但答案点只有 PostgreSQL 一侧（transaction durability）；引用的 Rust chunk 4f9001ca8c15_chunk_37（所有权规则）不含任何数据一致性保证内容，Rust 侧答案点缺失且无证据支持。 |
| mixed-022 | reject | zcode-agent-2026-08-29 | 答案点2「中文仅术语名（装饰器）」与语料矛盾：chunk c9fd20815ea8_chunk_5 的 decorator 条目除英文定义外还有中文正文（「装饰器语法只是一种语法糖…」「同样的概念也适用于类…」），并非仅术语名为中文；条目实为中英混合解释。 |
| noanswer-039 | needs_followup | zcode-agent-2026-08-29 | nodejs-fs.md chunk_101 明确列出 fs.watch 在 Linux 使用 inotify(7)（并逐平台列出 kqueue/FSEvents 等机制），该事实直接对应问题主题；但文档仅点名机制、未描述 inotify 内部实现，「describe inotify internals」是否被满足取决于口径，需仲裁拒答标签是否应改为可答 |
| noanswer-040 | needs_followup | zcode-agent-2026-08-29 | rust-book-core.md chunk_46/58 对 Copy/Drop trait 有实质讲解（Copy 语义、可实现类型、与 Drop 互斥），第 4 章在语料内；但 traits 专章（第 10 章）不在语料且正文自称「we'll talk more about traits in Chapter 10」，「chapters included cover traits」按不同口径可答可拒，需仲裁 |
| noanswer-050 | reject | zcode-agent-2026-08-29 | python-tutorial-zh.md chunk_69（10.11 质量控制）明确介绍 unittest 模块并给出完整示例（import unittest / class TestStatisticalFunctions / assertEqual），en 版 chunk_136 同样存在；问题可由语料直接回答，should_refuse=true 不成立 |
| zh-057 | reject | zcode-agent-2026-08-29 | query将斐波那契while多重赋值例子归于「4.1节」，但语料中该例子位于3.2节（走向编程的第一步，证据chunk导航也显示下一主题为第4章），4.1节是if语句；证据chunk的section标签同样误标为4.1。答案点内容本身被chunk原文支持，但问题的事实前提（章节归属）错误。 |

## 结论

overlay 未生成；本报告为人工复核的问题清单；不得自动宣称任何
批准，不得进入 v2.1。

