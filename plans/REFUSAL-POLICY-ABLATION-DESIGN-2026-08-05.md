# 拒答策略受控 Ablation 设计：evidence_calibrated vs baseline

> 制定日期：2026-08-05
> 状态：待审批（brainstorming 设计文档）
> 关联：`plans/RAG-IMPROVEMENT-PLAN-2026-08-01.md` 阶段 1.5（拒答校准）的
> 前置受控实验；基于 `refusal-guardrail-audit-20260805T113849/` 的审计结论。

---

## 一、背景与问题

false-refusal 只读审计（`results/graph-gate/refusal-guardrail-audit-20260805T113849/`）结论：

- dev false_refusal = **14/73（0.1918）**，holdout = 1/12；
- 误拒答明显集中：**cross_document 6/11（0.5455）**、**hard 5/10（0.5000）**、en 8/29（0.2759）；
- 其中 4 例真值 chunk 已进入 context 仍被误拒（cross-007/009、mixed-008、meta-002@holdout）→
  **模型侧误判**（检索成功但 LLM 因问题复杂/跨文档/需综合而选择拒答）。

根因假设：生成阶段 LLM 的拒答倾向受 SYSTEM_PROMPT「找不到信息不能编造」影响，
对复杂/跨文档问题过度保守，即使 context 证据足以支持回答也拒答。

## 二、目标与约束

**目标**：仅改变生成阶段拒答策略，受控验证「证据校准提示」能否降低 false_refusal
且不恶化 false_answer / citation / answer 质量。

**硬约束**（不得违反）：
1. 保留默认 `RAG_REFUSAL_POLICY=baseline`（新建策略抽象，默认行为不变）；
2. 新增可锁定 candidate 策略 `evidence_calibrated`：**仅调整生成提示**——当 context
   已有可直接支持回答的证据时，即使问题复杂、跨文档或需综合也应作答并引用；
   只有 context 无法支持时才拒答；
3. **不得使用任何 GT、case_id、relevant_chunk_ids 或评测专属信息参与运行时决策**
   （策略文本为静态通用指令，不含任何真值信息）；
4. A=baseline / B=evidence_calibrated 两臂共享同一 QueryPlan、检索候选、context、
   模型、温度、预算与 split；
5. 不得改变检索、QueryPlan、reranker、Graph、selector cap、数据集、真值或现有
   生产默认；不 stage/commit；不自动切换默认策略；不批准 guardrail。

## 三、方案对比

| 方案 | 描述 | 取舍 |
|---|---|---|
| **A（采纳）** | 策略 = **静态提示词变体**：`_build_llm_messages` 按策略选择 system prompt（baseline → 原 SYSTEM_PROMPT；evidence_calibrated → 追加策略指令段）；评测按臂**临时覆盖模块属性** `RAG_REFUSAL_POLICY` 并 finally 恢复（与 RAG_RERANKER_MODE 完全同模式）；B 臂仍走完整 `answer_query()` 生产链路 | 最小侵入、生产路径一致、可单测「提示内容」；「共享检索/context」由 QueryPlan 缓存 + 检索确定性 + 共享证据链（ret_index）保证，并在 paired 分析中逐 case 断言两臂 retrieval 证据一致 |
| B | 运行时证据检测：系统按检索分数/特征判断 context 是否有证据，再决定注入哪段指令 | 引入阈值/特征判断 → 与「仅调整生成提示」冲突；拒答校准本属阶段 1.5 范围，本实验须隔离变量 |
| C | 拆分 `answer_query`，把 A 臂检索结果显式注入 B 臂生成 | 工程量大、风险高（改动生产链路）；收益（字面共享）可由 A 方案的确定性 + 断言覆盖 |

## 四、详细设计

### 4.1 策略抽象（`src/rag.py`）

```python
REFUSAL_POLICY_BASELINE = "baseline"
REFUSAL_POLICY_EVIDENCE_CALIBRATED = "evidence_calibrated"
REFUSAL_POLICIES = (REFUSAL_POLICY_BASELINE, REFUSAL_POLICY_EVIDENCE_CALIBRATED)

# 模块级（导入期读 env），评测按臂临时覆盖模块属性（RAG_RERANKER_MODE 同模式）
RAG_REFUSAL_POLICY = os.getenv("RAG_REFUSAL_POLICY", "baseline").lower().strip()
if RAG_REFUSAL_POLICY not in REFUSAL_POLICIES:   # 非法值导入期 fail-fast
    raise ValueError(...)
```

`EVIDENCE_CALIBRATED_SYSTEM_PROMPT_ADDENDUM`（静态通用指令，中英双语，**不含任何
真值/评测信息**）：

> 当提供的文档证据足以支持回答时（包括需要跨文档综合、比较或多步骤推理的问题），
> 必须基于证据作答并引用 [S1]、[S2]…；不得因问题复杂、需要综合或跨文档而拒答。
> 仅当没有任何文档片段包含回答问题所需的信息时才拒答，并明确说明缺失的信息。
>
> (English) When the provided document evidence is sufficient to answer (including
> questions requiring cross-document synthesis or multi-step reasoning), you MUST
> answer based on the evidence and cite [S1], [S2]…; never refuse because the
> question is complex, requires synthesis, or spans multiple documents. Refuse only
> when no document passage contains the information needed to answer, and state
> what is missing.

纯函数 `system_prompt_for_policy(policy) -> str`（策略 → 实际 system prompt；
`_build_llm_messages` 与 locked_config 共用同一来源，保证「策略正文」单一事实）：

```python
def system_prompt_for_policy(policy: str) -> str:
    if policy == REFUSAL_POLICY_EVIDENCE_CALIBRATED:
        return SYSTEM_PROMPT + "\n\n" + EVIDENCE_CALIBRATED_SYSTEM_PROMPT_ADDENDUM
    return SYSTEM_PROMPT   # baseline 及未知值（fail-fast 已拦）均回到基础提示
```

`_build_llm_messages` 唯一生产改动点：`system` 取
`system_prompt_for_policy(RAG_REFUSAL_POLICY)`；`PROMPT_TEMPLATE` 不变 →
来源/引用格式（`format_sources`、[S#] 语法）不变；`retrieval_refused`（检索前哨）
与策略无关，两臂一致。

### 4.2 PreparedAnswerEvidence：可复用的生成证据（生产级对象）

`src/domain.py` 新增 frozen dataclass（生产与评测共用）：

```python
@dataclass(frozen=True)
class PreparedAnswerEvidence:
    """一次检索规划产出的、可复用于多次生成的完整证据（生产与评测共用）。

    构建一次，供 baseline / evidence_calibrated 两臂分别只调用生成步骤；
    answer_query 默认生产路径同样经过本对象（prepare + generate 拆分）。
    """
    query: str
    context: str                        # 实际进入 prompt 的 context 文本
    context_sha256: str                 # sha256(context)
    context_k: int                      # 实际进入 prompt 的候选数
    top_indices: tuple[int, ...]        # 有序 chunk 索引（repair/format_sources 输入）
    citation_map: tuple[tuple[str, str], ...]  # (S#, chunk_id) 有序 —— 来源映射
    context_chunk_ids: tuple[str, ...]  # 有序去重
    context_source_ids: tuple[str, ...] # 有序去重（source_name 域）
    candidate_chunk_ids: tuple[str, ...]# 有序去重
    top_scores: tuple[float, ...]       # 检索分数（生产指标记录用）
    plan_fingerprint: str               # QueryPlan 确定性标识：sha256(rewritten_query+sub_queries)
    retrieval_fingerprint: str          # 检索证据标识：sha256(candidates+context 集)
    refused: bool = False               # 检索前哨拒答（两臂一致）
    refusal_reason: str | None = None
```

**`src/rag.py` 重构（answer_query = prepare + generate，默认行为不变）**：

```python
def prepare_answer_evidence(query, model, collection, bm25, documents, metadatas,
                            history=None, query_plan=None) -> PreparedAnswerEvidence:
    # 有 query_plan（评测路径）：复用 rewrite/decompose/base_candidates，零 LLM/检索重跑
    # 无 query_plan（生产路径）：内部全量 rewrite → decompose → 检索 → 漂移防护
    # 共同后续：dynamic_top_k → 检索拒答判定（refused）→ select_context_candidates
    #   （reranker 可选，cap=SELECTOR_MAX_PER_SOURCE）→ enrich → parent-child →
    #   adjacent → _build_context → 组装 evidence（含 citation_map/指纹）

def generate_answer(evidence, documents, metadatas, temperature=DEFAULT_TEMPERATURE,
                    history=None) -> tuple[str, str]:
    # evidence.refused → (REFUSAL_MESSAGE, "")
    # answer_with_llm_history（内部按 RAG_REFUSAL_POLICY 选 system prompt）
    # → _validate_and_repair_citations（evidence.top_indices/context_k）
    # → format_sources（同一输入）→ (answer, sources)

def answer_query(...):
    evidence = prepare_answer_evidence(...)          # 生产全量路径
    return generate_answer(evidence, documents, metadatas, temperature=temperature,
                           history=history)
```

- 流式路径 `answer_query_stream` 本批不改（内部逻辑等价，后续统一，文档声明）；
- `_record_query_metric` 由 `answer_query` 在 prepare 后按 evidence 记录（评测路径
  不触发，指标无副作用）；
- 行为不变由回归测试守护：重构后 `answer_query` 的 LLM 消息与旧实现逐字节一致。

### 4.3 锁定（`evaluation/locked_config.py`）—— effective_prompt_ids

- **新必填字段 `refusal_policy`**（per-arm 映射，值 ∈ `REFUSAL_POLICIES`，
  **键集必须与 `arms` 完全一致**，不一致 → `ValueError`）；
- **新必填字段 `effective_prompt_ids`**（per-arm 映射）：
  `effective_prompt_ids[arm] = sha256(system_prompt_for_policy(policy) + "\n" +
  PROMPT_TEMPLATE)`——即「实际 system prompt + policy addendum + PROMPT_TEMPLATE」
  的 SHA-256；build 时计算写入，**键集必须与 `arms` 完全一致**；
- `validate_locked_config`：运行时重算 effective_prompt_ids 并逐臂比对——
  **策略正文（addendum 文本）、策略名或臂映射任一漂移 → LLM 前 fail-closed 拒绝**；
  `refusal_policy` 运行时不可得/不等 → 拒绝；
- 旧锁（无两键）向后兼容放行（split_fingerprint 先例）；
- **旧 `prompt_id` 仅保留为历史兼容**（REQUIRED_LOCK_KEYS 不动），
  **不得作为新实验的唯一提示词锁**——新实验以 effective_prompt_ids 为准。

### 4.4 评测执行（`evaluation/compare.py`）

- 新臂常量：`ARM_STANDARD_CALIBRATED = "standard-calibrated"`；
  `REFUSAL_ABLATION_ARMS = (ARM_STANDARD, ARM_STANDARD_CALIBRATED)`；
  `--arms` choices 增加。
- **生成网格改为 evidence 共享**：`run_generation_grid` 增加
  `evidence_cache: dict[(alpha, case_id) → PreparedAnswerEvidence]`；
  对 `REFUSAL_ABLATION_ARMS` 的臂，第一臂调用
  `prepare_answer_evidence(..., query_plan=query_plan_cache[case.id])`
  （从共享 QueryPlan 构建，**零 rewrite/decompose/检索/select 重跑**），
  第二臂直接复用缓存对象——**只构建一次 evidence，两臂分别仅调用
  `generate_answer`**；单臂（仅 standard）与无 ablation 臂（graph/rerank）
  走原路径（answer_query），行为与历史一致。
- `_run_generation_arm`：standard 与 standard-calibrated 共用「无 reranker」
  分支（reranker/cap 覆盖逻辑不变）；standard-calibrated 额外临时覆盖
  `rag_module.RAG_REFUSAL_POLICY = "evidence_calibrated"`（同一 try/finally
  恢复原值）；standard 臂不覆盖。
- **每 generation case 写入 evidence/context 指纹**：`GenerationCaseResult`
  新增字段 `evidence_context_sha256`、`evidence_plan_fingerprint`、
  `evidence_retrieval_fingerprint`、`evidence_citation_map`（S#→chunk_id 有序），
  随 generation-cases.jsonl 落盘。
- `compute_summary`：**不改动**既有 paired C vs B 逻辑；两臂各自聚合。
- 配对分析：**独立脚本** `paired_analysis.py`，**fail-closed**：
  对任一同 case，A/B 两臂的 `evidence_context_sha256`、citation map
  （S#→chunk_id）、candidate 集任一不同 → 整体拒绝并报告 diff；
  通过后输出 W/L/T、McNemar exact、block bootstrap CI（false_refusal delta、
  coverage delta）、cross_document/hard 切片。

### 4.5 测试计划（TDD：Red → Green → Refactor）

| 文件 | RED 测试 | 断言 |
|---|---|---|
| `tests/test_compare.py` | 两臂同 case evidence 指纹一致 | 评测流程（mock）中 standard 与 standard-calibrated 的 `evidence_context_sha256`/citation map/candidate 集**完全一致**（用户指定） |
| 同上 | evidence 只构建一次 | 每 case `prepare_answer_evidence` 恰好调用 1 次（mock 计数），两臂复用 |
| 同上 | 指纹写入 JSONL | `GenerationCaseResult` 序列化含 evidence 字段 |
| 同上 | paired fail-closed | 同 case A/B `context_sha256`/citation map/candidate 任一不同 → paired 分析拒绝（用户指定） |
| 同上 | 臂切换 | standard-calibrated 覆盖 `rag_module.RAG_REFUSAL_POLICY` 并 finally 恢复（含异常路径）；standard 臂不覆盖 |
| 同上 | 臂解析 | `--arms standard standard-calibrated` 通过 choices |
| `tests/test_refusal_policy.py`（新） | 默认行为不变 | 无 env 时 `RAG_REFUSAL_POLICY == "baseline"`；baseline 下 `_build_llm_messages` system 内容 == 原 SYSTEM_PROMPT 逐字节；**重构后 `answer_query` 的 LLM 消息与旧实现一致**（用户指定） |
| 同上 | 策略切换 | evidence_calibrated 下 system = SYSTEM_PROMPT + ADDENDUM；两策略 PROMPT_TEMPLATE/user prompt 逐字节相同（来源/引用格式不变） |
| 同上 | 非法策略 | 非法值导入期 ValueError |
| 同上 | 真值不泄露 | ADDENDUM 文本不含 `ground_truth`/`relevant`/`case_id`/`GT`/`reviewer` 等模式；PreparedAnswerEvidence 指纹确定性（同输入同指纹） |
| `tests/test_locked_config.py` | 锁定 | build 缺 refusal_policy/effective_prompt_ids → ValueError；**键集 ≠ arms → ValueError**；**同名策略但 addendum 文本变化 → effective_prompt_id 不同 → validate 拒绝（LLM 前）**（用户指定）；策略名/臂映射漂移 → 拒绝；legacy 无键放行；旧 prompt_id 仍存在但新实验校验以 effective_prompt_ids 为准 |
| smoke（评测目录脚本） | 生产链路 | 15 条 false_refusal case 双臂：B 臂作答数增加、引用 [S#] 连续、来源格式不变、两臂 evidence 指纹一致 |

## 五、评测流程与预注册门槛

**新锁**（`refusal-ablation-<ts>/lock-*.json`）：复用稳定 split
（split_fingerprint=`454892e4…3690`）、双 overlay
（`stable-split-rebuild-20260804T234043/`）、相同 dataset/corpus/index SHA、
模型与预算（cap=3、reranker=none、alpha=1.0、seed 42、temperature 0.1、
refusal_threshold 0.03）；**新增**：`arms=[standard, standard-calibrated]`、
`refusal_policy={"standard": "baseline", "standard-calibrated":
"evidence_calibrated"}`、`effective_prompt_ids={...}`（逐臂实际提示 SHA-256）。
precheck 以新锁 fail-closed 校验（锁/稳定 split 指纹/双 overlay/env/immutability）。

```
1. gen_lock（新锁）→ 2. precheck（锁/split/overlay/env/immutability，fail-closed）
→ 3. smoke 15 条（双臂）→ 4. dev full（95×2）→ 门槛评估
→ 5. holdout full（15×2，仅当 dev 达标）→ 6. paired analysis + decision-report
```

**预注册成功门槛**（任一不达标 → `AUTOMATED_DIAGNOSTIC_NO_GO`，不继续）：

| # | 门槛 | 判定口径 |
|---|---|---|
| G1 | dev false_refusal 至少减少 4 例 | B 臂 ≤ 10（baseline 14） |
| G2 | false_answer 不恶化 | B 臂 false_answer_rate ≤ A 臂（分母=should_refuse 子集） |
| G3 | citation_v2 micro ≥ 0.95 且 fabricated=0、retrieved_not_in_context=0 | 从 generation JSONL 复算（numerator/denominator） |
| G4 | answer_rate 不低于 baseline | B 臂 context_supported_answer_rate ≥ A 臂 |
| G5 | answer_point_coverage 不显著下降 | paired delta（B−A）的 95% bootstrap CI 上界 < −0.05 视为显著下降 → FAIL |
| G6 | holdout 方向一致 | holdout false_refusal B ≤ A 且 G3/G4 在 holdout 成立；否则 NO_GO（如实报告） |

## 六、交付物（独立时间戳目录 `refusal-ablation-<ts>/`）

- `lock-*.json`（新锁）、`precheck.py` + 结果、`smoke.py` + smoke-results.json
- `dev-full/`（两臂 generation-cases.jsonl、summary、manifest）、`holdout-full/`
- `paired_analysis.py` + `paired-analysis.json`（W/L/T、McNemar、bootstrap CI、切片）
- `decision-report.md`（**新目录内**，明确是否值得提升为生产默认的结论；
  不自动切换默认策略、不批准 guardrail）
- `run-commands.md`、`generate_*` 脚本、manifest

## 七、验证

- 完整 pytest、py_compile、git diff --check；
- 历史产物不可变性复验（precheck-snapshot immutability 13 项 + 决策报告/旧候选/
  锁/overlay/GT map SHA）；
- CHANGELOG 更新；不 stage/commit。

## 八、不在本批范围

- 不改检索/QueryPlan/reranker/Graph/selector cap/数据集/真值/生产默认；
- 不自动切换默认策略、不批准 guardrail 阈值；
- 不修改 `compute_summary` 既有配对逻辑（历史口径不变）；
- 不重跑历史评测、不改写任何历史 results 产物。
