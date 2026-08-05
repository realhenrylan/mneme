# v2 标注完整性报告（annotation integrity）

> LLM_ASSISTED 草稿状态；全部自动标注，无人工 confirmed。

- 总用例：150（配额校验通过：类型×语言、难度 52/62/36、band 20/20/19/91、9 条链）
- chunk 引用数：146（全部存在于 chunk manifest：True）
- 证据可追溯性（fail-closed）：146/146 个 snippet 为指定 chunk 的连续证据（文档化 Markdown 归一化后；意译/拼接/错误 chunk_id 拒绝）
- source-only：2（≤10% 上限 15）
- LLM_ASSISTED 标记：150/150
- 合法组合校验：通过（none/chunk/source fail-closed 检查）
- 链完整性：9 条链轮次连续、follow_up_to 引用存在
- 键集：每行含 15 个必需键 + metadata + annotation

## 逐例状态

| case_id | 类型 | 语言 | level | chunks | 状态 |
|---|---|---|---|---|---|
| en-021 | single_fact | en | chunk | 1 | LLM_ASSISTED (pending review) |
| en-022 | single_fact | en | chunk | 1 | LLM_ASSISTED (pending review) |
| en-023 | single_fact | en | chunk | 1 | LLM_ASSISTED (pending review) |
| en-024 | single_fact | en | chunk | 1 | LLM_ASSISTED (pending review) |
| en-025 | single_fact | en | chunk | 1 | LLM_ASSISTED (pending review) |
| en-026 | single_fact | en | chunk | 1 | LLM_ASSISTED (pending review) |
| en-027 | single_fact | en | chunk | 1 | LLM_ASSISTED (pending review) |
| en-028 | single_fact | en | chunk | 1 | LLM_ASSISTED (pending review) |
| en-029 | single_fact | en | chunk | 1 | LLM_ASSISTED (pending review) |
| en-030 | single_fact | en | chunk | 1 | LLM_ASSISTED (pending review) |
| en-031 | single_fact | en | chunk | 1 | LLM_ASSISTED (pending review) |
| en-032 | single_fact | en | chunk | 1 | LLM_ASSISTED (pending review) |
| en-033 | metadata | en | chunk | 1 | LLM_ASSISTED (pending review) |
| en-034 | metadata | en | chunk | 1 | LLM_ASSISTED (pending review) |
| en-035 | metadata | en | chunk | 1 | LLM_ASSISTED (pending review) |
| en-036 | metadata | en | chunk | 1 | LLM_ASSISTED (pending review) |
| en-037 | metadata | en | chunk | 1 | LLM_ASSISTED (pending review) |
| en-038 | metadata | en | chunk | 1 | LLM_ASSISTED (pending review) |
| en-039 | metadata | en | chunk | 1 | LLM_ASSISTED (pending review) |
| en-040 | cross_document | en | chunk | 2 | LLM_ASSISTED (pending review) |
| en-041 | cross_document | en | chunk | 2 | LLM_ASSISTED (pending review) |
| en-042 | cross_document | en | chunk | 2 | LLM_ASSISTED (pending review) |
| en-043 | cross_document | en | chunk | 1 | LLM_ASSISTED (pending review) |
| en-044 | cross_document | en | chunk | 2 | LLM_ASSISTED (pending review) |
| en-045 | cross_document | en | chunk | 2 | LLM_ASSISTED (pending review) |
| en-046 | cross_document | en | source | 0 | LLM_ASSISTED (pending review) |
| en-047 | cross_document | en | chunk | 1 | LLM_ASSISTED (pending review) |
| en-048 | cross_document | en | chunk | 2 | LLM_ASSISTED (pending review) |
| en-049 | cross_document | en | chunk | 2 | LLM_ASSISTED (pending review) |
| en-050 | cross_document | en | chunk | 2 | LLM_ASSISTED (pending review) |
| en-051 | cross_document | en | chunk | 2 | LLM_ASSISTED (pending review) |
| en-052 | cross_document | en | chunk | 2 | LLM_ASSISTED (pending review) |
| en-053 | cross_document | en | chunk | 2 | LLM_ASSISTED (pending review) |
| en-054 | mixed_intent | en | chunk | 1 | LLM_ASSISTED (pending review) |
| en-055 | mixed_intent | en | chunk | 1 | LLM_ASSISTED (pending review) |
| en-056 | mixed_intent | en | chunk | 1 | LLM_ASSISTED (pending review) |
| en-057 | mixed_intent | en | chunk | 1 | LLM_ASSISTED (pending review) |
| mixed-016 | single_fact | mixed | chunk | 1 | LLM_ASSISTED (pending review) |
| mixed-017 | single_fact | mixed | chunk | 1 | LLM_ASSISTED (pending review) |
| mixed-018 | single_fact | mixed | chunk | 1 | LLM_ASSISTED (pending review) |
| mixed-019 | single_fact | mixed | chunk | 1 | LLM_ASSISTED (pending review) |
| mixed-020 | single_fact | mixed | chunk | 1 | LLM_ASSISTED (pending review) |
| mixed-021 | metadata | mixed | chunk | 1 | LLM_ASSISTED (pending review) |
| mixed-022 | metadata | mixed | chunk | 1 | LLM_ASSISTED (pending review) |
| mixed-023 | metadata | mixed | chunk | 1 | LLM_ASSISTED (pending review) |
| mixed-024 | metadata | mixed | chunk | 1 | LLM_ASSISTED (pending review) |
| mixed-025 | metadata | mixed | source | 0 | LLM_ASSISTED (pending review) |
| mixed-026 | cross_document | mixed | chunk | 2 | LLM_ASSISTED (pending review) |
| mixed-027 | cross_document | mixed | chunk | 2 | LLM_ASSISTED (pending review) |
| mixed-028 | cross_document | mixed | chunk | 2 | LLM_ASSISTED (pending review) |
| mixed-029 | cross_document | mixed | chunk | 2 | LLM_ASSISTED (pending review) |
| mixed-030 | cross_document | mixed | chunk | 2 | LLM_ASSISTED (pending review) |
| mixed-031 | cross_document | mixed | chunk | 2 | LLM_ASSISTED (pending review) |
| mixed-032 | cross_document | mixed | chunk | 1 | LLM_ASSISTED (pending review) |
| mixed-033 | mixed_intent | mixed | chunk | 2 | LLM_ASSISTED (pending review) |
| mixed-034 | mixed_intent | mixed | chunk | 2 | LLM_ASSISTED (pending review) |
| mixed-035 | mixed_intent | mixed | chunk | 2 | LLM_ASSISTED (pending review) |
| multi-011 | multi_turn | zh | chunk | 1 | LLM_ASSISTED (pending review) |
| multi-012 | multi_turn | zh | chunk | 1 | LLM_ASSISTED (pending review) |
| multi-013 | multi_turn | zh | chunk | 1 | LLM_ASSISTED (pending review) |
| multi-014 | multi_turn | zh | chunk | 1 | LLM_ASSISTED (pending review) |
| multi-015 | multi_turn | en | chunk | 1 | LLM_ASSISTED (pending review) |
| multi-016 | multi_turn | en | chunk | 1 | LLM_ASSISTED (pending review) |
| multi-017 | multi_turn | en | chunk | 1 | LLM_ASSISTED (pending review) |
| multi-018 | multi_turn | en | chunk | 1 | LLM_ASSISTED (pending review) |
| multi-019 | multi_turn | en | chunk | 1 | LLM_ASSISTED (pending review) |
| multi-020 | multi_turn | en | chunk | 1 | LLM_ASSISTED (pending review) |
| multi-021 | multi_turn | en | chunk | 1 | LLM_ASSISTED (pending review) |
| multi-022 | multi_turn | en | chunk | 1 | LLM_ASSISTED (pending review) |
| multi-023 | multi_turn | en | chunk | 1 | LLM_ASSISTED (pending review) |
| multi-024 | multi_turn | zh | chunk | 1 | LLM_ASSISTED (pending review) |
| multi-025 | multi_turn | zh | chunk | 1 | LLM_ASSISTED (pending review) |
| multi-026 | multi_turn | zh | chunk | 1 | LLM_ASSISTED (pending review) |
| multi-027 | multi_turn | mixed | chunk | 1 | LLM_ASSISTED (pending review) |
| multi-028 | multi_turn | mixed | chunk | 1 | LLM_ASSISTED (pending review) |
| multi-029 | multi_turn | mixed | none | 0 | LLM_ASSISTED (pending review) |
| multi-030 | multi_turn | mixed | chunk | 1 | LLM_ASSISTED (pending review) |
| multi-031 | multi_turn | mixed | chunk | 1 | LLM_ASSISTED (pending review) |
| multi-032 | multi_turn | zh | chunk | 1 | LLM_ASSISTED (pending review) |
| multi-033 | multi_turn | zh | chunk | 1 | LLM_ASSISTED (pending review) |
| multi-034 | multi_turn | zh | chunk | 1 | LLM_ASSISTED (pending review) |
| noanswer-026 | no_answer | zh | none | 0 | LLM_ASSISTED (pending review) |
| noanswer-027 | no_answer | zh | none | 0 | LLM_ASSISTED (pending review) |
| noanswer-028 | no_answer | zh | none | 0 | LLM_ASSISTED (pending review) |
| noanswer-029 | no_answer | zh | none | 0 | LLM_ASSISTED (pending review) |
| noanswer-030 | no_answer | zh | none | 0 | LLM_ASSISTED (pending review) |
| noanswer-031 | no_answer | zh | none | 0 | LLM_ASSISTED (pending review) |
| noanswer-032 | no_answer | zh | none | 0 | LLM_ASSISTED (pending review) |
| noanswer-033 | no_answer | zh | none | 0 | LLM_ASSISTED (pending review) |
| noanswer-034 | no_answer | zh | none | 0 | LLM_ASSISTED (pending review) |
| noanswer-035 | no_answer | zh | none | 0 | LLM_ASSISTED (pending review) |
| noanswer-036 | no_answer | zh | none | 0 | LLM_ASSISTED (pending review) |
| noanswer-037 | no_answer | en | none | 0 | LLM_ASSISTED (pending review) |
| noanswer-038 | no_answer | en | none | 0 | LLM_ASSISTED (pending review) |
| noanswer-039 | no_answer | en | none | 0 | LLM_ASSISTED (pending review) |
| noanswer-040 | no_answer | en | none | 0 | LLM_ASSISTED (pending review) |
| noanswer-041 | no_answer | en | none | 0 | LLM_ASSISTED (pending review) |
| noanswer-042 | no_answer | en | none | 0 | LLM_ASSISTED (pending review) |
| noanswer-043 | no_answer | en | none | 0 | LLM_ASSISTED (pending review) |
| noanswer-044 | no_answer | en | none | 0 | LLM_ASSISTED (pending review) |
| noanswer-045 | no_answer | en | none | 0 | LLM_ASSISTED (pending review) |
| noanswer-046 | no_answer | en | none | 0 | LLM_ASSISTED (pending review) |
| noanswer-047 | no_answer | en | none | 0 | LLM_ASSISTED (pending review) |
| noanswer-048 | no_answer | en | none | 0 | LLM_ASSISTED (pending review) |
| noanswer-049 | no_answer | en | none | 0 | LLM_ASSISTED (pending review) |
| noanswer-050 | no_answer | en | none | 0 | LLM_ASSISTED (pending review) |
| noanswer-051 | no_answer | mixed | none | 0 | LLM_ASSISTED (pending review) |
| noanswer-052 | no_answer | mixed | none | 0 | LLM_ASSISTED (pending review) |
| noanswer-053 | no_answer | mixed | none | 0 | LLM_ASSISTED (pending review) |
| noanswer-054 | no_answer | mixed | none | 0 | LLM_ASSISTED (pending review) |
| noanswer-055 | no_answer | mixed | none | 0 | LLM_ASSISTED (pending review) |
| zh-021 | single_fact | zh | chunk | 1 | LLM_ASSISTED (pending review) |
| zh-022 | single_fact | zh | chunk | 1 | LLM_ASSISTED (pending review) |
| zh-023 | single_fact | zh | chunk | 1 | LLM_ASSISTED (pending review) |
| zh-024 | single_fact | zh | chunk | 1 | LLM_ASSISTED (pending review) |
| zh-025 | single_fact | zh | chunk | 1 | LLM_ASSISTED (pending review) |
| zh-026 | single_fact | zh | chunk | 1 | LLM_ASSISTED (pending review) |
| zh-027 | single_fact | zh | chunk | 1 | LLM_ASSISTED (pending review) |
| zh-028 | single_fact | zh | chunk | 1 | LLM_ASSISTED (pending review) |
| zh-029 | single_fact | zh | chunk | 1 | LLM_ASSISTED (pending review) |
| zh-030 | single_fact | zh | chunk | 1 | LLM_ASSISTED (pending review) |
| zh-031 | single_fact | zh | chunk | 1 | LLM_ASSISTED (pending review) |
| zh-032 | single_fact | zh | chunk | 1 | LLM_ASSISTED (pending review) |
| zh-033 | single_fact | zh | chunk | 1 | LLM_ASSISTED (pending review) |
| zh-034 | single_fact | zh | chunk | 1 | LLM_ASSISTED (pending review) |
| zh-035 | single_fact | zh | chunk | 1 | LLM_ASSISTED (pending review) |
| zh-036 | single_fact | zh | chunk | 1 | LLM_ASSISTED (pending review) |
| zh-037 | single_fact | zh | chunk | 1 | LLM_ASSISTED (pending review) |
| zh-038 | metadata | zh | chunk | 1 | LLM_ASSISTED (pending review) |
| zh-039 | metadata | zh | chunk | 1 | LLM_ASSISTED (pending review) |
| zh-040 | metadata | zh | chunk | 1 | LLM_ASSISTED (pending review) |
| zh-041 | metadata | zh | chunk | 1 | LLM_ASSISTED (pending review) |
| zh-042 | metadata | zh | chunk | 1 | LLM_ASSISTED (pending review) |
| zh-043 | metadata | zh | chunk | 1 | LLM_ASSISTED (pending review) |
| zh-044 | metadata | zh | chunk | 1 | LLM_ASSISTED (pending review) |
| zh-045 | cross_document | zh | chunk | 2 | LLM_ASSISTED (pending review) |
| zh-046 | cross_document | zh | chunk | 2 | LLM_ASSISTED (pending review) |
| zh-047 | cross_document | zh | chunk | 2 | LLM_ASSISTED (pending review) |
| zh-048 | cross_document | zh | chunk | 2 | LLM_ASSISTED (pending review) |
| zh-049 | cross_document | zh | chunk | 2 | LLM_ASSISTED (pending review) |
| zh-050 | cross_document | zh | chunk | 1 | LLM_ASSISTED (pending review) |
| zh-051 | cross_document | zh | chunk | 2 | LLM_ASSISTED (pending review) |
| zh-052 | cross_document | zh | chunk | 2 | LLM_ASSISTED (pending review) |
| zh-053 | cross_document | zh | chunk | 2 | LLM_ASSISTED (pending review) |
| zh-054 | cross_document | zh | chunk | 2 | LLM_ASSISTED (pending review) |
| zh-055 | mixed_intent | zh | chunk | 1 | LLM_ASSISTED (pending review) |
| zh-056 | mixed_intent | zh | chunk | 1 | LLM_ASSISTED (pending review) |
| zh-057 | mixed_intent | zh | chunk | 1 | LLM_ASSISTED (pending review) |
| zh-058 | mixed_intent | zh | chunk | 1 | LLM_ASSISTED (pending review) |
| zh-059 | mixed_intent | zh | chunk | 1 | LLM_ASSISTED (pending review) |
