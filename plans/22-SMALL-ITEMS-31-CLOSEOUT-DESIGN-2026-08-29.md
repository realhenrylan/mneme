# 设计提案：2.2 附带小项 + 3.1 收尾（2026-08-29）

> 状态：~~**待 owner 审批**~~ **已批准并实施（2026-08-29 owner 指示
> 「按照这个开工」）**——实施记录：Part 1（A 守卫 A1 冻结 20 / B1 孤例
> 不修 / run-4 ACCEPTED 保持）→ Part 2（D1–D3、D5）全部落地，见
> CHANGELOG 2026-08-29 条目与 `results/` 对应报告/审计。
> 上游：路线图 §四 2.2 附带登记两项（run-2/run-3 报告）+ §五 3.1 回填
> 范式：沿用 Stage 2 验收纪律——TDD 全程、沙箱实验零 trace 写入、
> 冻结资产（v1 数据集行 / v2.0.11 / v2 sealed 语料）零改写、每次修改更新 CHANGELOG。

---

## Part 1 · 2.2 附带小项（先做）

### A. 邻接扩展最小块长守卫

**现状（证据）**：run-2 实测 chunk_12（4 字符，"1. 2"，heading 残片）经
`expand_with_adjacent`（`src/chunking.py:223`）进入 ON context——该函数对
prev/next 邻居候选**无任何长度检查**（chunking.py:273-287）。

**设计**：

- `src/chunking.py` 新增模块常量 `MIN_ADJACENT_CHUNK_CHARS`（**初值 20，
  最终值待 A1 审计证据冻结**；注释说明 magic number 依据）；
- `expand_with_adjacent` 新增 keyword-only `texts: list[str] | None = None`：
  非 None 时，prev/next 候选若 `len(texts[candidate].strip()) < 阈值` →
  跳过该候选（不计入 `added`，同一召回块的另一侧邻居仍可扩展）；
  None 时行为逐字节不变（向后兼容）；
- 两处扩展调用点（`src/rag.py` sync ~2665 / stream ~3252）传入 documents；
- **守卫只过滤邻接候选**：select 代表块路径（`expand_with_parent`、
  `reconcile_expansion_budget`）零改动——召回证据不可被守卫误伤。

**A1 审计（先于阈值冻结）**：脚本统计 v1 test_texts 索引与 v2 sealed
`chunks.jsonl`（只读）的 chunk 长度分布：<阈值块的数量、形态（标题残片 /
列表碎片 / 正文短节）、按 chunk_type 分布；据此冻结阈值并留档。

**TDD**：短邻居被排除且另一侧仍扩展 / select 块永不被过滤 / 阈值边界值 /
`texts=None` 行为不变；既有 E1 与预算调和测试适配（夹具文本加长到阈值之上，
另补守卫边界用例）。

**验收回归（行为改动的代价，如实付）**：扩展行为变更后复跑
`evaluation/parentchild_ab.py`（run-4，同一沙箱索引、同一
containment-aware 口径）→ `STAGE2_22_ACCEPTED` **必须保持**；若翻转 →
回滚守卫或带证据重议（不静默改判）。

### B. parent 划分质量专项

**现状（证据）**：chunk_12 是 4 字符 child 且 parent 指向 chunk_6——
`chunk_document`（`src/chunking.py:121`）对超长 Section 二次切分后
**无碎块合并**，`RecursiveCharacterTextSplitter` 会产出微小 child。

**B1 审计（只读，先做）**：脚本扫 v1 索引 + v2 sealed chunks：每 source 的
tiny child（< 30 字符）数量与形态、parent 尺寸分布、child ⊆ parent 包含
健全性、tiny child 是否 heading 残片。

**B2 条件修复（仅当审计证实系统性问题）**：`chunk_document` 增加切分后
合并 pass（tiny child 并入相邻 child，parent 划分不变）；只对新增索引生效；
**sealed v2 语料资产零触碰**。若审计显示仅孤例 → 登记为已知限制，不修。

**回归**：B2 若实施，并入 run-4 同一轮复跑（A + B 单次回归，成本一次）。

---

## Part 2 · 3.1 收尾（后做）

### 现状对齐审计（开工第一步，落档到回填）

**回填声明滞后于代码**——以下已实现（须在路线图回填中更正）：

| 计划要求 | 代码现状 |
| --- | --- |
| 进程级模型缓存 | ✅ `llm_gateway.get_or_load_model` 双检锁缓存 |
| timeout / 有限重试 / 退避 | ✅ 60s + 2 次 + 指数退避（`llm_gateway.py:151-153,317-363`） |
| 并发上限 | ✅ 模块级 `Semaphore(4)`（`llm_gateway.py:161`）——但**不可配置** |
| token 使用统计 | ✅ `TokenUsage` 采集 + `get_call_summary()` 汇总 |
| 错误分类 | ✅ 9 类含 `CANCELLED`（`classify_error`） |
| 步骤 3 拆解守卫增强 | ✅ `should_decompose` 已含多意图/中英混合/复杂分隔规则并接线（`rag_query_decomposer.py:40,121`） |

**真缺口（本轮范围）**：

1. **取消机制**：`llm_call` 无 cancel 入口（`CANCELLED` 分类存在但无路径
   触发）；TUI（`tui/screens/chat.py` 同步 `console.status` 循环）生成期间
   无法中断，Ctrl+C 会逸出主循环终止会话——「网络异常时不停留 thinking」
   的完成标准未满足（timeout 上界 ~3 分钟且不可逃逸）。
2. **并发上限不可配置**：`DEFAULT_MAX_CONCURRENT=4` 硬编码模块常量。
3. **错误分类可见未接线**：`get_call_summary()` 无任何 UI 出口。
4. **拆解收益计量（计划步骤 4）未做**：无 decompose 开关、无数据。

### D1 取消机制（TDD）

- `llm_gateway`：新增 `LLMCancelledError`；`llm_call` 新增 keyword-only
  `cancel_event: threading.Event | None = None`——每个 attempt 前检查置位、
  退避等待改为 `cancel_event.wait(backoff)`（取消即时唤醒）；置位 → 抛
  `LLMCancelledError`（分类 `CANCELLED`、不可重试）。
- `answer_with_llm_history_stream`：透传 `cancel_event`；流消费循环逐 chunk
  检查，置位 → `response.close()` + 抛 `LLMCancelledError`。
- TUI（`tui/screens/chat.py`）：生成块捕获 `KeyboardInterrupt` → 置位事件 →
  打印「已取消当前回答」→ 回到输入提示；半截答案不入 history（回滚）。
- 测试：调用前取消 = 零网络零 client；退避中取消即时返回；流中取消 close
  被调用；KeyboardInterrupt 恢复路径受测试保护。

### D2 并发上限可配置（TDD）

`RAG_LLM_MAX_CONCURRENCY`（1–32，导入期 fail-fast 校验，沿用
`RAG_CONTEXT_EXPANSION` 同模式）；默认 4 行为不变。

### D3 错误分类可见（TDD）

`service.get_stats()` 附 gateway 调用摘要（调用数 / 错误率 / 分类分布 /
token 合计）；TUI `/status` 渲染一行；无调用记录时零噪音。

### D5 拆解收益计量（计划步骤 4）

- 新增 `RAG_QUERY_DECOMPOSE`（on 默认 / off，导入期 fail-fast）门控
  `src/rag.py` 共享规划 helper 的 `decompose_query_llm` 调用（off =
  单查询直通）；默认行为零变化。
- `evaluation/decompose_ab.py`：复用 parentchild_ab 范式——单因子 =
  decompose 开关（模块属性按臂临时覆盖 + finally 恢复），两臂共享同一
  rewrite；指标 = **containment-aware context recall（run-3 仪器）** +
  规划墙钟延迟；v1 目标集同 2.2（n=71）；**诊断性计量：报告 deltas 与 n，
  不设 accept/reject 门禁**；沙箱运行零 trace 写入。
- 报告 `results/stage3-decompose/report-2026-08-29.md`。

### 3.1 完成标准逐条对照（[~]→[x] 依据）

| 完成标准 | 证据 |
| --- | --- |
| 无重复加载 | 既有模型缓存 + 既有测试 |
| 错误分类可见 | D3 接线 + 测试 |
| 网络异常不停留 thinking | D1 取消 + 既有 timeout 上界 |
| 步骤 3 守卫 | 已实现（本轮回填更正 + 测试覆盖确认） |
| 步骤 4 计量 | D5 报告 |

---

## 执行顺序与成本

1. **Part 1**：A1 审计 → 阈值冻结 → A TDD → B1 审计 →（条件 B2）→
   run-4 复跑（一次回归覆盖 A/B）→ 报告 + CHANGELOG + 提交；
2. **Part 2**：现状对齐落档 → D1 → D2 → D3 → D5 → 3.1 落账 →
   报告 + CHANGELOG + 提交。

LLM 成本：run-4 ≈ 71×2 规划调用（零生成）；D5 ≈ 71×2 规划调用（零生成）。
红线不变：TDD 全程、沙箱零 trace、冻结资产零改写、不 stage/commit/push
trace 与 consent 数据。
