# Mneme 答案级评测线 M2 诊断基线报告

- 数据集：`v2.1`（150 例基准，本次 `150` 例全量）
- 指标口径：`al1-containment-v1`（answer-hit containment 族，机械下界）
- chunk_id 域：`12hex-normalized`（M1.1 归一修复后；产品侧 ID 形态未改，仅评测侧比对归一）
- 密封：`outcomes_sha256=6e4d59e1c7a6…`，`manifest_sha256=0055cfa413b1…`（自哈希 MATCH；本报告只读不写回）
- 运行时粒度：`retrieval_ms=0.0`（生成路径未拆分检索/生成计时，M1 起已知粒度；总耗时 `total_ms` 有效）

## 1. answer_hit（有效要点机械命中）

- 可判定例：122（拒答/无要点例 28，计入 `cases_without_effective_points`；其中 28 例为拒答探针）
- 要点级命中率：**20/174 = 0.1149**（含义：真值要点被答案文本规范化包含，机械下界）
- 例级宏平均：**0.1380**（122 例宏平均）
- 逐例分布：全中 15 / 部分 4 / 全零 103
- 按 query_type `cross_document`：n=31 平均=0.0000
- 按 query_type `metadata`：n=19 平均=0.2018
- 按 query_type `mixed_intent`：n=12 平均=0.2917
- 按 query_type `multi_turn`：n=23 平均=0.0870
- 按 query_type `no_answer`：n=3 平均=0.0000
- 按 query_type `single_fact`：n=34 平均=0.2206
- 按 language `en`：n=49 平均=0.1939
- 按 language `mixed`：n=24 平均=0.0625
- 按 language `zh`：n=49 平均=0.1190
- 结构性局限（如实披露）：containment 只识别文本规范化包含；同义改写/中英互译/指代变换型要点系统性漏判，此值为**下界**）

## 2. token 实耗

- 合计：**441,496**（prompt 429,709 + completion 11,787；completion 占比 2.7%）
- 全量 150 例：平均 2,943，中位 3,485，min 0 / max 9,263
- 拒答探针 28 例：合计 83,000，平均 2,964
- 可答例 122：合计 358,496，平均 2,938
- 零 token 例 11 个（`multi-029, multi-030, multi-031, multi-033, zh-021, zh-022` 等）：纯本地快速拒答路径——检索零证据未触发 LLM，无 gateway 记录，答案文本为固定拒绝消息（非 LLM 生成），token 记录真实为 0

## 3. refusal（28 拒答探针 + 122 可答误拒率）

- 28 探针正确拒答：**11/28** = 0.3929
- 122 可答例误拒答：**48/122** = 0.3934
- 语义式陈述占探针 **17/28**（非拒答消息形态，词表未命中；indicator 词典外语义等价输出归此类——如实披露，不作优劣裁决）
- `sentinel_refusal`（6 例）：multi-029, noanswer-029, noanswer-032, noanswer-042, noanswer-048, noanswer-054
- `post_generation_refusal`（5 例）：noanswer-027, noanswer-034, noanswer-036, noanswer-043, noanswer-052
- `semantic_statement`（17 例）：noanswer-026, noanswer-028, noanswer-030, noanswer-031, noanswer-033, noanswer-035, noanswer-037, noanswer-038…

## 4. citation 契约 v2 联合分布（12-hex 归一口径）

- `citation_id_validity`：mean=0.6067，非零例 91/150
- `context_supported_citation_validity`：mean=0.6067，非零例 91/150
- `citation_precision`：mean=0.0300，非零例 7/150
- `citation_recall`：mean=0.0322，非零例 7/150
- `faithfulness`：mean=0.5411，非零例 89/150
- 有引用例 91/150；真值非空的引用例中：检索缺口（context∩truth=∅）57，引用未覆盖（context 含真值但答案未引用）15，命中真值引用 7；拒答探针（无真值块）12
- 122 可答例中检索缺口（context∩truth=∅）：**99/122**——答案引用质量的主要制约是检索未召回真值块，而非引用错位
- 说明：`faithfulness` 为证据覆盖启发式（要点术语 vs context ≥50% 命中），非答案级指标，引用契约带内汇报；`context_supported_citation_validity` 为契约 v2 正式 guardrail 口径（引用 chunk 真正进入 context）

## 5. 逐例遗漏清单（诊断，无门禁判定）

- 要点 miss 共 154 条（覆盖 107 例；截样本 24 条）：
  - `multi-011` `[multi_turn]` 都支持索引和切片操作
  - `multi-011` `[multi_turn]` 两者都是序列类型
  - `multi-012` `[multi_turn]` 数量应相等
  - `multi-013` `[multi_turn]` 使用 import fibo as fib
  - `multi-013` `[multi_turn]` 用 as 后的名称绑定导入模块
  - `multi-014` `[multi_turn]` 尽量不要使用 from ... import *
  - `multi-014` `[multi_turn]` 建议使用 from package import specific_submodule
  - `multi-015` `[multi_turn]` simple assignment never copies data
  - `multi-015` `[multi_turn]` both names reference the same object
  - `multi-016` `[multi_turn]` rgb also changes because it is the same list object
  - `multi-017` `[multi_turn]` freely available
  - `multi-017` `[multi_turn]` from the Python web site https://www.python.org/
  - `multi-018` `[multi_turn]` 可附加到列定义或表约束
  - `multi-018` `[multi_turn]` 用于约束列值（如 x>3）
  - `multi-019` `[multi_turn]` 可以（示例演示直接写数据库文件绕过约束）
  - `multi-022` `[multi_turn]` 值被丢弃（drop）
  - `multi-023` `[multi_turn]` 请求（分配）它需要的内存
  - `multi-024` `[multi_turn]` 文本插值（text interpolation）{{ }}
  - `multi-025` `[multi_turn]` 冒号简写 :id（即 : 前缀）
  - `multi-026` `[multi_turn]` JavaScript Proxies（Proxy 代理）
  - `multi-027` `[multi_turn]` BEGIN TRANSACTION（begin-stmt）
  - `multi-028` `[multi_turn]` BEGIN / COMMIT（以及 ROLLBACK）
  - `multi-030` `[multi_turn]` 数字（把 Python 当作计算器）
  - `multi-031` `[multi_turn]` Numbers
- context 含真值但引用 precision=0 的例（15 个）：`multi-021, en-027, en-028, en-038, mixed-024, mixed-025, zh-054, en-043, en-047, en-048`…

---
本报告为纯诊断基线（owner Q3 批示：首轮无任何产品门禁）；所有数字为事实陈述，不含合格/不合格判定。
