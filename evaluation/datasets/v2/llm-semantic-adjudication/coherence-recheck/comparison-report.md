# DeepSeek v4 Pro 盲态机器语义审阅（v2 第三轮分歧仲裁）

> 本报告为**一致性重审后合并结果**的重算版本（原始 102 条仲裁见父目录 comparison-report.md，
> 重审记录见 rechecks.jsonl）。
>
> 本报告为机器语义仲裁证据，**不得视为人工终审**；不构成任何 v2.1 进入决策；不修改任何标注，不生成 overlay。

## 一、输入与盲态构建（复算）

- blank pack：150 行；llm-filled：150 行；case_id 集合一致；除三个人工字段外逐行一致。
- 第三轮 decision 分布（llm-filled 复算）：confirmed 68 / reject 82 / needs_followup 0。
- 隐藏对照：68 条 confirmed 中按 sha256("v2-semantic-adjudication-v1:" + case_id) 升序排序取前 20 条；对照清单仅在审计侧 selection-manifest.json，绝不进入模型输入。
- 盲态输入：102 条（82 争议 + 20 对照），每条仅含 query / previous_turns / should_refuse / acceptable_answer_points / evidence / chunks 原文；不含 case_id、decision、reviewer、notes、repair、cohort 或任何历史结论。

## 二、82 条争议：与第三轮 reject 的比较

| 结果 | 条数 | 占比 |
|---|---|---|
| 一致（模型也判 reject） | 5 | 6.1% |
| 不一致（模型判 confirmed） | 77 | 93.9% |
| 不确定（needs_followup） | 0 | 0.0% |

## 三、20 条隐藏对照（第三轮 confirmed）

| semantic_verdict | 条数 |
|---|---|
| confirmed | 20 |
| reject | 0 |
| needs_followup | 0 |

## 四、分层（答案题 / 拒答题 / 跨文档题）

| 层 | 争议总数 | 一致 | 不一致 | 不确定 | 对照 confirmed | 对照 reject | 对照 needs_followup |
|---|---|---|---|---|---|---|---|
| 答案题 | 67 | 5 | 62 | 0 | 16 | 0 | 0 |
| 拒答题 | 15 | 0 | 15 | 0 | 4 | 0 | 0 |
| 跨文档题 | 28 | 2 | 26 | 0 | 2 | 0 | 0 |

## 五、答案点支持级别（全部 102 条）

| support_level | 条数 |
|---|---|
| direct_snippet | 77 |
| within_chunk_outside_snippet | 6 |
| faithful_paraphrase | 39 |
| unsupported | 5 |
| 合计答案点 | 127 |

## 六、拒答评估（拒答题）

| refusal_assessment | 条数 |
|---|---|
| no_answer | 19 |
| partial_topic_overlap_only | 0 |
| substantive_answer_exists | 0 |
| unclear | 0 |
| 合计拒答评估 | 19 |

## 七、谱系限制

- 本轮与此前 deepseek-chat 同属 DeepSeek 提供方；第三轮模型身份未被历史 manifest 记录；不宣称模型或供应商独立性。

## 八、结论与未解决风险

- 本报告仅提供机器语义仲裁证据：82 条争议的一致/不一致/不确定、20 条隐藏对照的分布、逐答案点支持级别与拒答评估，均不构成对150 条标注的修改、采纳或覆盖。
- 未解决风险：模型对 evidence snippet 截取边界的敏感度未知；逐字覆盖判定不能完全代表语义忠实度；20 条对照规模有限，统计效力有限；输出依赖 prompt 与 max_tokens 设置；本轮未做人工复核。
- 结论：**不得视为人工终审、人工批准或上线批准；不构成任何 v2.1 进入决策。**

## 附录：102 条逐条结果

| index | case_id | 角色 | 层 | semantic_verdict | 第三轮 decision |
|---|---|---|---|---|---|
| 1 | en-022 | 对照 | 答案 | confirmed | confirmed |
| 2 | en-024 | 争议 | 答案 | confirmed | reject |
| 3 | en-025 | 对照 | 答案 | confirmed | confirmed |
| 4 | en-026 | 对照 | 答案 | confirmed | confirmed |
| 5 | en-028 | 对照 | 答案 | confirmed | confirmed |
| 6 | en-029 | 争议 | 答案 | confirmed | reject |
| 7 | en-030 | 争议 | 答案 | confirmed | reject |
| 8 | en-031 | 争议 | 答案 | confirmed | reject |
| 9 | en-032 | 对照 | 答案 | confirmed | confirmed |
| 10 | en-033 | 对照 | 答案 | confirmed | confirmed |
| 11 | en-037 | 对照 | 答案 | confirmed | confirmed |
| 12 | en-038 | 对照 | 答案 | confirmed | confirmed |
| 13 | en-040 | 争议 | 跨文档 | confirmed | reject |
| 14 | en-041 | 争议 | 跨文档 | confirmed | reject |
| 15 | en-042 | 争议 | 跨文档 | confirmed | reject |
| 16 | en-043 | 对照 | 跨文档 | confirmed | confirmed |
| 17 | en-044 | 争议 | 跨文档 | confirmed | reject |
| 18 | en-045 | 争议 | 跨文档 | confirmed | reject |
| 19 | en-046 | 争议 | 跨文档 | confirmed | reject |
| 20 | en-047 | 争议 | 跨文档 | confirmed | reject |
| 21 | en-048 | 争议 | 跨文档 | confirmed | reject |
| 22 | en-049 | 争议 | 跨文档 | confirmed | reject |
| 23 | en-050 | 争议 | 跨文档 | confirmed | reject |
| 24 | en-051 | 争议 | 跨文档 | confirmed | reject |
| 25 | en-052 | 争议 | 跨文档 | reject | reject |
| 26 | en-053 | 争议 | 跨文档 | confirmed | reject |
| 27 | en-055 | 争议 | 答案 | reject | reject |
| 28 | mixed-016 | 争议 | 答案 | reject | reject |
| 29 | mixed-017 | 对照 | 答案 | confirmed | confirmed |
| 30 | mixed-018 | 争议 | 答案 | confirmed | reject |
| 31 | mixed-019 | 争议 | 答案 | confirmed | reject |
| 32 | mixed-020 | 争议 | 答案 | confirmed | reject |
| 33 | mixed-022 | 争议 | 答案 | confirmed | reject |
| 34 | mixed-025 | 争议 | 答案 | confirmed | reject |
| 35 | mixed-026 | 争议 | 跨文档 | reject | reject |
| 36 | mixed-027 | 争议 | 跨文档 | confirmed | reject |
| 37 | mixed-028 | 争议 | 跨文档 | confirmed | reject |
| 38 | mixed-029 | 争议 | 跨文档 | confirmed | reject |
| 39 | mixed-030 | 争议 | 跨文档 | confirmed | reject |
| 40 | mixed-031 | 争议 | 跨文档 | confirmed | reject |
| 41 | mixed-032 | 争议 | 跨文档 | confirmed | reject |
| 42 | mixed-034 | 争议 | 答案 | confirmed | reject |
| 43 | mixed-035 | 对照 | 答案 | confirmed | confirmed |
| 44 | multi-011 | 争议 | 答案 | confirmed | reject |
| 45 | multi-012 | 对照 | 答案 | confirmed | confirmed |
| 46 | multi-013 | 争议 | 答案 | confirmed | reject |
| 47 | multi-014 | 争议 | 答案 | reject | reject |
| 48 | multi-015 | 争议 | 答案 | confirmed | reject |
| 49 | multi-016 | 争议 | 答案 | confirmed | reject |
| 50 | multi-018 | 争议 | 答案 | confirmed | reject |
| 51 | multi-019 | 争议 | 答案 | confirmed | reject |
| 52 | multi-020 | 争议 | 答案 | confirmed | reject |
| 53 | multi-022 | 争议 | 答案 | confirmed | reject |
| 54 | multi-023 | 争议 | 答案 | confirmed | reject |
| 55 | multi-025 | 争议 | 答案 | confirmed | reject |
| 56 | multi-026 | 争议 | 答案 | confirmed | reject |
| 57 | multi-028 | 争议 | 答案 | confirmed | reject |
| 58 | multi-029 | 对照 | 拒答 | confirmed | confirmed |
| 59 | multi-030 | 对照 | 答案 | confirmed | confirmed |
| 60 | noanswer-030 | 对照 | 拒答 | confirmed | confirmed |
| 61 | noanswer-031 | 争议 | 拒答 | confirmed | reject |
| 62 | noanswer-032 | 争议 | 拒答 | confirmed | reject |
| 63 | noanswer-034 | 对照 | 拒答 | confirmed | confirmed |
| 64 | noanswer-037 | 争议 | 拒答 | confirmed | reject |
| 65 | noanswer-038 | 争议 | 拒答 | confirmed | reject |
| 66 | noanswer-039 | 争议 | 拒答 | confirmed | reject |
| 67 | noanswer-040 | 争议 | 拒答 | confirmed | reject |
| 68 | noanswer-042 | 争议 | 拒答 | confirmed | reject |
| 69 | noanswer-043 | 争议 | 拒答 | confirmed | reject |
| 70 | noanswer-044 | 争议 | 拒答 | confirmed | reject |
| 71 | noanswer-045 | 对照 | 拒答 | confirmed | confirmed |
| 72 | noanswer-046 | 争议 | 拒答 | confirmed | reject |
| 73 | noanswer-047 | 争议 | 拒答 | confirmed | reject |
| 74 | noanswer-048 | 争议 | 拒答 | confirmed | reject |
| 75 | noanswer-049 | 争议 | 拒答 | confirmed | reject |
| 76 | noanswer-052 | 争议 | 拒答 | confirmed | reject |
| 77 | noanswer-053 | 争议 | 拒答 | confirmed | reject |
| 78 | zh-021 | 争议 | 答案 | confirmed | reject |
| 79 | zh-024 | 争议 | 答案 | confirmed | reject |
| 80 | zh-025 | 争议 | 答案 | confirmed | reject |
| 81 | zh-026 | 对照 | 答案 | confirmed | confirmed |
| 82 | zh-031 | 争议 | 答案 | confirmed | reject |
| 83 | zh-032 | 争议 | 答案 | confirmed | reject |
| 84 | zh-033 | 争议 | 答案 | confirmed | reject |
| 85 | zh-036 | 对照 | 答案 | confirmed | confirmed |
| 86 | zh-038 | 争议 | 答案 | confirmed | reject |
| 87 | zh-040 | 争议 | 答案 | confirmed | reject |
| 88 | zh-042 | 争议 | 答案 | confirmed | reject |
| 89 | zh-044 | 争议 | 答案 | confirmed | reject |
| 90 | zh-045 | 争议 | 跨文档 | confirmed | reject |
| 91 | zh-046 | 争议 | 跨文档 | confirmed | reject |
| 92 | zh-047 | 争议 | 跨文档 | confirmed | reject |
| 93 | zh-048 | 争议 | 跨文档 | confirmed | reject |
| 94 | zh-049 | 争议 | 跨文档 | confirmed | reject |
| 95 | zh-050 | 对照 | 跨文档 | confirmed | confirmed |
| 96 | zh-052 | 争议 | 跨文档 | confirmed | reject |
| 97 | zh-053 | 争议 | 跨文档 | confirmed | reject |
| 98 | zh-054 | 争议 | 跨文档 | confirmed | reject |
| 99 | zh-055 | 争议 | 答案 | confirmed | reject |
| 100 | zh-056 | 争议 | 答案 | confirmed | reject |
| 101 | zh-057 | 争议 | 答案 | confirmed | reject |
| 102 | zh-058 | 争议 | 答案 | confirmed | reject |
