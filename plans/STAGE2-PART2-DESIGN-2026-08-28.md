# Stage 2 收尾设计：2.2 parent-child 效果验收 + 2.3 解析失败可见性验收

> 日期：2026-08-28
> 状态：owner 已指示「先完成 2.2 和 2.3」＝授权实施；本文档冻结预注册判据，
> 阈值可被 owner 事后推翻（推翻则修订本文档并重跑实验）。
> 上游：`plans/RAG-IMPROVEMENT-PLAN-2026-08-01.md` §四；沿用 2.4 已验证的
> 验收范式（预注册门禁三态 + 密封产物 + 数据卫生声明）。

---

## Part 1 · 2.2 Parent-Child/邻接扩展效果验收

### 现状

- 扩展（`expand_with_parent` → `expand_with_adjacent`）在 `src/rag.py` sync/stream
  两路径**无条件执行**，无开关；
- chunk 级真值基建现成：`compare.build_ground_truth_map`（snippet→chunk 匹配）；
- v1 有 chunk 真值的 case 81 条，剔除 multi_turn 10 条（其检索行为已由 2.4
  实验度量，且 canonical history 需要答案回放，与本实验正交）→ **有效样本 71**；
- 完成标准（路线图）：「跨边界问答的 context recall 提升（在评测集 v1 上验证）」。

### 设计

**E1 扩展开关（TDD）**：Settings 新增 `RAG_CONTEXT_EXPANSION`（环境变量同名，
取值 `on`/`off`，默认 `on`，非法值导入期 fail-fast——沿用 RAG_REFUSAL_POLICY
范式）；rag.py 两处扩展调用点改为调用期读取开关。默认行为零变化。

**E2 实验执行器** `evaluation/parentchild_ab.py`（TDD）：

- 每 case 只构建**一次** `QueryPlan`（compare.prepare_query_plan，含
  rewrite+decompose+检索），随后 `prepare_answer_evidence(query_plan=plan)`
  跑 ON/OFF 两遍——两臂规划与检索**由构造保证逐字节相同**，唯一差异是
  select 之后的扩展阶段（真正的单因子隔离）；
- 指标：chunk 级 context recall（`context_chunk_ids ∩ 该 case 真值 chunk 集` /
  真值数；真值来自 build_ground_truth_map）；零 LLM 生成调用；
- 语料：test_texts 全部 6 文件（v1 各 case relevant_source_ids 的并集域）；
- 密封产物 `results/stage2-parentchild/run-*/`（逐例 JSONL + 自哈希 manifest，
  沿用 2.4 约定）。

**预注册门禁（n=71）**：

| 判定 | 条件 | 门禁名 |
| --- | --- | --- |
| 通过 | mean(ON) ≥ mean(OFF) + 0.05 且无单例恶化 > 0.05 | `STAGE2_22_ACCEPTED` |
| 未证明 | ON ≥ OFF 但未达阈值 | `STAGE2_22_NOT_PROVEN` |
| 回归 | mean(ON) < mean(OFF) | `STAGE2_22_REGRESSION`（扩展挤占 context 预算，转修复项） |

机制说明：扩展**可能**造成回退——parent/邻接块更大，在 context_k 预算内
挤出其他相关块。这正是实验要回答的问题。阈值冻结后不得回调。

---

## Part 2 · 2.3 解析失败可见性验收

### 现状缺口

- CLI 侧可见已完成（2026-08-28 降级路径显式化：结构化警告 + manifest
  `parse_degraded`）；
- **TUI 不可见**：loader 的 print 警告直达裸 stdout，rich TUI 不渲染；
- 零块文件（如纯扫描 PDF）仅靠 is_low_quality 打印，无结构化"该文件产出 0 块"
  信号；
- 现有 `test_pdf_docx_parsing.py` 是单元级质量评级测试，无端到端可见性/回退验收。

### 设计

**F1 诊断通道（TDD）**：`_load_index_chunks` / `prepare_index` /
`add_files_to_index` 增 keyword-only `diagnostics_sink: list | None = None`；
非 None 时按文件收集结构化诊断：`{source_name, file_type, parse_quality,
is_low_quality, chunk_count, parse_degraded, error}`。默认 None → 行为逐字节
不变。零块文件（chunk_count=0）必产出诊断条目。

**F2 TUI 呈现（TDD）**：`tui/service.py` 索引时传入 sink，索引完成后把
低质量/降级/零块条目以 warning_panel 渲染（复用现有 `warning_panel` 组件）。

**F3 端到端验收套件** `tests/test_stage2_parsing_acceptance.py`（fitz 程序化
构造 PDF 夹具，不引入二进制 fixture）：

| 夹具 | 断言 |
| --- | --- |
| 原生文本 PDF（fitz 生成含文本页） | 质量评级 ≥ structured/native，无低质量警告 |
| 纯图/空页 PDF（fitz 生成无文本页） | is_low_quality=True + 警告可见 + 诊断条目 |
| 空文本 txt（0 块） | chunk_count=0 诊断 + 不静默 |
| loader 异常文件 | 降级可见（M3 语义）+ parse_degraded 标记 |
| 正常 docx/txt | 正常路径零诊断噪音 |

**F4 验收报告** `results/stage2-parsing-acceptance/report-2026-08-28.md`：
矩阵结果 + 门禁结论（`STAGE2_23_ACCEPTED` = 全矩阵通过且 TUI 呈现受测试证明；
任一缺口 → 列缺口与修复项）。

---

## 执行顺序与边界

1. E1 → E2 → 跑 2.2 实验 → 门禁判定；2. F1 → F2 → F3 → 2.3 报告；
3. 全量回归 0 failed；4. 路线图 2.2/2.3 状态更新 + CHANGELOG + 提交。

红线不变：v1 数据集与 v2.0.11 冻结树零改写；实验/验收在沙箱数据目录跑，
零 trace 写入；不 stage/commit/push 任何 trace 与 consent 数据。
LLM 成本：2.2 约 71×(1 rewrite + 1 decompose)，零生成调用。
