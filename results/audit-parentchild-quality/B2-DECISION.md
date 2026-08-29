# B2 决策：不实施（登记为已知限制）

- 日期：2026-08-29
- 依据：`results/audit-parentchild-quality/`（B1 审计，只读）
- 决策出处：`plans/22-SMALL-ITEMS-31-CLOSEOUT-DESIGN-2026-08-29.md` Part 1-B
  「B2 条件修复（仅当审计证实系统性问题）……若审计显示仅孤例 → 登记为
  已知限制，不修」

## 审计证据

| 维度 | 结果 |
| --- | --- |
| tiny child（<30 字符）数量 | 3 块 / 609 child（0.5%） |
| tiny child 形态 | 页码残片 1（"4"）、标题残片 1（"1.\n2"）、正文残片 1（25 字符 "losslessness argument.\n33"） |
| parent 尺寸 | 55 块，min=412 median=1141 max=1982 —— 健康 |
| child ⊆ parent 包含健全性 | 201/201 零违规（无缺 parent、无非子串） |
| v2 sealed | min=22 字符，无关系字段，无可处理问题 |

## 结论

- 系统性问题不成立：二次切分碎块仅 0.5% 覆盖，且 2/3 已由 A1 邻接守卫
  （MIN_ADJACENT_CHUNK_CHARS=20）直接拦截（1 与 4 字符块）；
- 剩余 1 块（25 字符正文残片）含真实语义内容，属正常切分产物；
- 合并 pass 将引入「切分-合并」二次变换复杂度，对 0.5% 覆盖率的收益
  不成立 → 不实施；后续如 v2 corpus 出现系统性 tiny child 再议。
