# P2-1 真实使用成本：可计算性审计与最小采集方案

- 日期：2026-10-31
- 状态：**AUDIT 完成；结论 NO-GO（现有数据不足）；Option A 已获 owner 2026-11-01 授权实施（进行中）**。修复方案见 §7.2；实施与测试另行提交，不 push。
- 审计对象：`src/production_observability.py`、`src/llm_gateway.py`、`src/rag.py` 的观测/生成/计量接线，以及本机 `${MNEME_DATA_DIR}/traces`（未设时 `~/.mneme/traces`）现有 trace。
- 上游：`docs/STATUS.md` §4 P2-1（WATCH，DoD 开放）；`results/cost-baseline-2026-10-31/report.md`（T6 基线）。
- 边界：审计阶段只读；未改代码/traces/consent；未调用 LLM；未安装依赖；未读取 query/history/answer/model_response 原文。2026-11-01 owner 授权 Option A 实施后，代码改动在 `feat/p2-1-usage-ledger` 分支单独进行。
- 本报告只含聚合数字，不含查询、答案、chunk id、trace id、会话标识、文件哈希或任何原文。

---

## 0. 结论（先看这里）

**不足以。现有 412 条 trace 中 0 条包含可用的 token usage；无法计算“真实每查询 token 成本”，也无法按模型或拒答分层。**

四条硬事实：

1. **唯一的 token 字段是词数，不是 token。** `generation.completed.token_count = len(answer.split())`（`src/rag.py:2422`、`src/production_observability.py:272`）。CJK 答案按空白分词几乎恒为 1；全样本 63.3% 的 trace `token_count=1`。
2. **成本所需的字段 0/412 存在。** 没有 `prompt_tokens` / `completion_tokens` / `total_tokens`，没有 `model`，没有每查询 LLM 调用次数/重试，没有 TTFT，没有事件时间戳。
3. **事后重算也不可行。** query、context、answer 原文按 Minimal 契约均不落盘（query 仅盐化哈希，盐不持久化）；依赖里没有 tokenizer（`requirements.txt` 无 `tiktoken`/`tokenizers`）。因此“拿现有 trace + 装个 tokenizer 重算”这条路不存在。
4. **现有 412 条不是可用的真实使用样本。** 单一 consent 会话；120 条参数化夹具形态；43 条统一 4,226 B 的流式形态；21 条合成 chunk 回退；9–10 月凡有检索事件的 24 条候选数全为 1（空索引/夹具）。更重要的是：**191 条 `context_k` 恰为 10、205 条候选数 ≥25 仍被截到 ≤10，全部发生在 2026-08**，说明有检索行为的样本都跑在 `RAG_CONTEXT_MAX_K=10` 的旧配置（M2 回退四 env 之一）下，**没有一条覆盖当前臂2 默认（budget 7000 / max_k 25）**。

因此 P2-1 的 DoD（“一轮真实使用样本的 token/延迟报告”）**未满足**，且按现状继续等待不会满足——必须先在采集侧补字段。

**最小可行修复（只提议）**：不动 trace、不改 consent 语义，新增本地聚合 `usage` 台账（Option A，§7.2），token 真值只取 provider `response.usage`；流式补 `stream_options.include_usage` 并守卫空 `choices`。预估 1 个新模块 + 5 处接线 + 测试，属独立实现任务，需 owner 批准（§8）。

---

## 1. 判据与审计方法

### 1.1 “能计算真实每查询 token 成本”的判据

| 编号 | 判据 |
|---|---|
| C1 | 每次查询有 provider 返回的 `prompt_tokens` / `completion_tokens` / `total_tokens`（或可证明等价的真值） |
| C2 | 有 `model` 与 `call_type`，能按模型/阶段分层 |
| C3 | 有每查询 LLM 调用次数与重试次数 |
| C4 | 能识别流量来源（真实使用 / 评测 / 测试），否则样本不可用 |
| C5 | 时间可聚合（日/周），支撑 T6 的 7 日滚动与 ≥1,000 查询/周样本量判据 |

C1–C5 全满足才给出均值/分位数；任一不满足即 NO-GO。**不使用任何代理指标替代。**

### 1.2 审计方法

- 源码：逐行核对事件生产点、gateway 记录点、metrics 记录点、评测汇总点。
- 数据：只解析 JSONL 行的白名单数字/枚举字段（`event_type`、`token_count`、`result_length`、`latency_ms`、`citation_state`、`context_k`、`candidate_count`、`refusal.reason`、`planning_profile`）；不读取/不打印 `result_sha256`、`line_sha256`、`trace_id`、`session_id`、`chunk_ids`、`source_ids` 的值；`result_script` 只做 cjk/latin 计数。
- 全程无写操作；`traces` 与 `consent` 未被修改。

---

## 2. 数据源与规模

| 项 | 值 |
|---|---|
| 根 | `~/.mneme/traces`（`MNEME_DATA_DIR` 未设时的默认；本次未设） |
| trace 文件 | 412 个 `*.jsonl` + 412 个 `*.manifest.json` |
| `.jsonl` 合计 | 10,646,444 B（均值 25,841 / 最小 1,027 / 最大 135,812） |
| 事件行 | 3,841 |
| 时间范围 | 仅文件 mtime：2026-08-27 → 2026-10-31（+08:00）；事件本身无时间戳 |
| 月分布 | 2026-08: 338；2026-09: 56；2026-10: 18 |
| consent | 全部 `minimal`；单一会话贯穿全部 412 条 |
| tombstones | 18 条 |
| 其他落盘 | `~/.mneme` 顶层仅 `chroma_db/`、`models/`、`traces/`；无 usage/metrics 文件 |

> 时间范围只能由文件 mtime 推断，粒度到文件；无法得到“每查询发生在哪一天/哪个小时”，因此 C5 不满足。

---

## 3. trace schema 逐字段审计

### 3.1 事件信封

每条事件一行 JSON（`canonical_event_bytes`，`src/production_observability.py:46-50`；封存 `:300-319`），字段为：

`schema_version`、`trace_id`、`session_id`、`turn_index`、`event_type`、`pii_level`、`line_sha256` + 事件 payload。

`schema_version = 1`、`RETENTION_DAYS = 30`；事件类型 15 种。`emit()` 明确禁止 `query/history/rewritten_query/sub_queries/answer/model_response/prompt/document/api_key/authorization/base_url/path`（`:228-232`）。这是正确的隐私设计，但也是“成本字段从未进入契约”的根因。

### 3.2 `generation.completed`：唯一疑似成本事件

| 字段 | 来源 | 语义 | 可否用于 token 成本 |
|---|---|---|---|
| `token_count` | `len(answer.split())`（`src/rag.py:2422`） | 空白分词词数 | **否**。不是 tokenizer 计数；CJK 无空格，长答案也常为 1 |
| `result_length` | `len(text)` | 答案字符数 | 否。只能做长度代理，与 token 非线性 |
| `latency_ms` | 端到端墙钟（`src/rag.py:2995`） | 检索 + 生成 + 引用校验 | 部分。非生成段；172/412 为 0 |
| `citation_state` | 枚举 | 引用状态 | 否 |
| `result_sha256` | 盐化摘要 | 完整性/去重 | 否（且不应使用） |

**缺失（数据层 0/412）**：`prompt_tokens`、`completion_tokens`、`total_tokens`、`model`、`llm_calls`、`call_type` 拆分、`retries`、`ttft_ms`、`generation_ms`、`usage_source`、`origin`、`ts`。

### 3.3 其他事件

| 事件 | 现有 payload | 成本相关缺口 |
|---|---|---|
| `trace.begin` | `schema_version/trace_id/session_id/turn_index/event_type/pii_level/planning_profile/retrieval_k/consent`（`src/production_observability.py:199-214`） | 无 `model`、无 `origin`、无时间戳、无 `app_version` |
| `context.built` | `context_k`、`chunk_ids`、`source_ids`（`src/rag.py:2812-2816`） | 无 context token 数、无正文（设计如此） |
| `cutoff.dynamic_top_k` | `k`、`candidate_count`、`planning_profile`、`retrieval_k` | 无 token |
| `refusal.decided` | `refused`、`reason`（仅 `retrieval`） | 无 `refusal_stage`、无 token（pre-LLM 本应为 0） |
| `rewrite.decided` / `decompose.decided` | 盐化 `result_sha256/length/script` | 无 token |
| `retrieve.dense/bm25`、`fusion.rrf` | `chunk_id/rank/score` 等 | 无 token |

---

## 4. 代码路径：字段为什么不在

| 环节 | 位置 | 事实 | 后果 |
|---|---|---|---|
| 同步生成调用 | `src/rag.py:2297` | `response, _ = llm_call(...)`，含 `token_usage` 的 `LLMCallRecord` 被丢弃 | 真值在进程内消失 |
| 流式生成调用 | `src/rag.py:3117` | 同上，`stream=True` | 且流式本就不取 usage |
| 网关取 usage | `src/llm_gateway.py:402-408` | `if not stream and hasattr(response,'usage') and response.usage` | 流式永不取 |
| 流式请求参数 | `src/llm_gateway.py:394-395` | 只设 `stream=True`，未设 `stream_options.include_usage` | provider 不返回 usage |
| 网关记录存储 | `src/llm_gateway.py:204-207` | `_call_records` 进程内、上限 500，无落盘 | 进程退出即失，事后不可查 |
| metrics 字段 | `src/metrics.py:47-49` | `QueryMetric` 有 `prompt_tokens/completion_tokens/total_tokens` | 字段存在，但…… |
| metrics 写入 | `src/rag.py:2169-2199` | `_record_query_metric` 只填检索/拒答字段，不填 token/`llm_ms`/`ttft_ms` | 恒为空 |
| metrics 落盘 | `src/metrics.py:186` | `GLOBAL_METRICS = MetricsRecorder()` 无 `persist_path` | 只存在于内存 |
| 评测汇总 | `evaluation/generation_runner.py:108-126` | 每 case `clear_call_records()` 后汇总 `get_call_records()` | 只有评测有数，且不写 trace |
| trace 写入 | `src/rag.py:2410-2427` | 只写 `len(text.split())` + 端到端 latency | 词数进 trace |
| 上下文 token | `src/domain.py:329-346` | `avg_chunk_tokens=200` 启发式（500 字符 ÷ ~2.5） | 不能反推 prompt token |
| tokenizer | `requirements.txt` | 无 `tiktoken`/`tokenizers` | 本地无法精确计数 |

**结论**：不是“忘了把字段聚合”，而是**生成调用点主动丢弃了 usage，且 trace 契约不允许任何成本字段**。修复必须从 gateway 的返回值开始接线，而不是在 trace 层补算。

---

## 5. 实测统计（412 条，只聚合数字）

### 5.1 形态分类

| 形态 | n | 占比 | 判别 | 特征 |
|---|---:|---:|---|---|
| full-sync | 226 | 54.9% | begin + 规划事件 + context + gen + end | 有检索行为；latency 均值 2,291 ms |
| minimal3 | 120 | 29.1% | 仅 begin + gen + end | 长度 ∈ {7,8,12,23}；token 全 1；latency 全 0 |
| refused | 23 | 5.6% | 有 `refusal.decided`、无 `context.built` | 长度全 23；latency 均值 141 ms |
| stream | 43 | 10.4% | `planning_profile=stream` | 每文件恰 4,226 B；长度全 5；latency 0–2 ms |

按月：8 月 338（220 full-sync / 70 minimal3 / 17 refused / 31 stream）；9 月 56（4 / 40 / 4 / 8）；10 月 18（2 / 10 / 2 / 4）。

minimal3 的 `result_length` 只有 4 个取值（7 / 8 / 12 / 23 字符），出现次数为 24 / 24 / 48 / 24；`citation_state` 为 24 / 24 / 72——参数化夹具特征，不是自然流量。

### 5.2 关键数字

| 指标 | n | mean | p50 | p90 | p95 | max |
|---|---:|---:|---:|---:|---:|---:|
| `token_count`（词数，全样本） | 412 | 4.66 | 1 | 13 | 20 | 97 |
| `result_length`（字符） | 412 | 107.44 | 23 | 279 | 409 | 2,925 |
| `latency_ms`（端到端） | 412 | 1,264.84 | 753 | 3,225 | 3,862 | 18,805 |
| `context_k` | 269 | 7.75 | 10 | 10 | 10 | 10 |
| `candidate_count` | 292 | 78.2 | 79 | 154 | 174 | 216 |

补充：
- `token_count = 1` 共 261 条（63.3%）；其中 27 条答案长度 ≥100 字符，42 条长度 ≥100 且 `token_count ≤2`。这直接证明词数口径在 CJK 下失效。
- `latency_ms = 0` 共 172 条（minimal3 120 + stream 24 + refused 15 + full-sync 13）。
- `context_k` 分布：`1→64`、`4→1`、`6→1`、`7→3`、`9→9`、`10→191`。
- `citation_state`：`not_required 90 / unknown 225 / unverified 25 / verified 72`。
- 拒答 23/412 = 5.58%，`reason` **全部为 `retrieval`**（pre-LLM）。没有 post-LLM 拒答记录。
- 合成 chunk 回退（形如 `chunk_<n>`）：full-sync 21/226、stream 43/43。

### 5.3 配置证据（关键）

- 191/269 的 `context_k` 恰为 10；205/269 的 `candidate_count ≥25` 却仍被截到 `≤10`。
- 当前默认是 `token_budget=7000`、`max_k=25`（`src/domain.py:329-346`），这些 trace 只可能来自 `RAG_CONTEXT_MAX_K=10`（M2 回退四 env 之一）或 2026-09-06 前的旧默认。
- **191 条全部在 2026-08**；9–10 月凡有检索事件的 24 条 `candidate_count` 全为 1（空索引/夹具形态）。
- 因此：**没有任何一条 trace 能代表当前臂2 默认配置下的每查询成本**。即使明天补上 usage 字段，用这批样本对照 T6 阈值也会错配配置。

### 5.4 样本偏差清单

1. 单一 consent 会话、单机、单用户；无 `origin`，评测流量可混入（见 §6.2）。
2. 82% 的 trace 集中在 2026-08，且该月配置为 M2 回退档。
3. 184/412（44.7%）为退化形态：120 minimal3 + 43 stream + 21 合成 chunk 回退。
4. 9–10 月 74 条中 50 条只有 3 个事件；其余 24 条检索宽度为 1。
5. 无事件时间戳，无法做日/周滚动，也无法对齐 T6 的 7 日窗口。
6. 答案偏短（p50 23 字符、mean 107 字符），与评测 mix 不可比。
7. 无查询语言分桶字段；只有盐化摘要的脚本标签可粗略区分（cjk 246 / latin 46 / 无规划事件 120），无法识别 mixed。

---

## 6. 可计算性判定

### 6.1 逐指标矩阵

| 指标 | 现有字段 | 可用 n | 判定 |
|---|---|---:|---|
| 每查询 total token | 无 | 0 | **NO** |
| prompt / completion 拆分 | 无 | 0 | **NO** |
| 每模型 token | 无 `model` | 0 | **NO** |
| 每查询 LLM 调用数 / 每阶段调用数 | 无 | 0 | **NO** |
| 重试成本 | 无 | 0 | **NO** |
| 按拒答分层的 token | 无 | 0 | **NO** |
| TTFT | 无 | 0 | **NO** |
| 生成段耗时 | 只有端到端 `latency_ms` | 412（含 172 个 0） | **NO**（不可拆） |
| 端到端延迟分布 | `latency_ms` | 412 | PARTIAL（样本非真实/非当前配置） |
| 答案长度 | `result_length` | 412 | YES（仅字符） |
| 检索上下文规模 | `context_k` | 269 | YES（启发式口径） |
| 拒答率 | `refusal.decided` | 412 | PARTIAL（仅 pre-LLM；样本不代表生产） |

### 6.2 污染路径（为什么不能把 412 当“真实”）

- `evaluation/compare.py:1581` 与 `:1598` 调用 `answer_query(...)` 时**未传 `trace_store`**。
- `src/rag.py:2353-2361 _resolve_trace_store(None)` 会回退 `TraceStore.from_environment()`；本机 consent 已是 `minimal` → **评测调用可以写入同一 traces 根**。
- trace 没有 `origin` 字段，事后无法区分真实/评测/测试。
- 这解释了为什么 9–10 月出现 `candidate_count=1` 的“full-sync”：更像夹具/空索引调用，而不是用户查询。

### 6.3 若强行用代理指标，会得到什么

| 代理 | 计算 | 结果 | 为什么错 |
|---|---|---|---|
| 词数当 token | 1,921 / 412 | 4.66 token/查询 | 对比 T6 臂2 均值 7,871.35 → 低估约 **1,688×**（0.06%） |
| 字符 ÷ 2.5 | 107.44 / 2.5 | ≈43 completion token | 只覆盖 completion（臂2 成本 98.7% 在 prompt）；CJK 字符≈1 token、英文≈0.25，统一除数必有偏 |
| `context_k × 200` | 7.75 × 200 | ≈1,550 token | 只是检索上下文粗估，不含 system/instructions/history/query；200 本身是 500 字符假设 |

**判定：三条代理都会产出“看似合理、无法校准”的数字，禁止写入 P2-1 报告或用于阈值对照。**

---

## 7. 最小修复方案（只提议，未实施）

### 7.1 设计原则

1. **不写 trace**：P1.1 已按 `NO_TRIGGER_FALLBACK` 闭环（`docs/STATUS.md:245`，§6“不重开”），不因成本观测重开 trace 线。
2. **不改 consent 语义**：沿用 `minimal` 开关；consent `off` 时立即停写。
3. **只记计数**：无 query/answer/prompt/context 原文，无 user/session/trace id，无 IP/UA。
4. **缺失记 null，绝不估算**；`usage_source` 显式标注来源。
5. 采集失败不影响问答主路径（try/except，失败仅 debug 日志）。
6. 本地、按日切分、90 天保留、可整目录删除。

### 7.2 Option A（推荐）：provider usage 聚合台账

新增 `src/usage_ledger.py`；默认路径 `${MNEME_DATA_DIR}/usage/usage-YYYY-MM.jsonl`（未设时 `~/.mneme/usage/`），一行一次**查询**（不是一次调用）。

字段（对齐 T6 §12.1 十六项，去掉不可得项，新增来源/质量字段）：

| 字段 | 类型 | 说明 |
|---|---|---|
| `schema_version` | int | 1 |
| `ts_bucket` | str | `YYYY-MM-DD`（UTC 日） |
| `origin` | str | `user` / `evaluation` / `test` |
| `route` | str | `sync` / `stream` |
| `outcome` | str | `answered` / `refused_pre_llm` / `refused_post_llm` / `error` |
| `model` | str | 实际请求模型（provider 回显优先） |
| `tokens_prompt` | int/null | provider usage |
| `tokens_completion` | int/null | provider usage |
| `tokens_total` | int/null | provider usage |
| `llm_calls` | int | 本查询调用次数（rewrite/decompose/answer） |
| `retry_count` | int | 调用级重试合计 |
| `usage_source` | str | `provider` / `partial` / `missing` / `unsupported` |
| `ttft_ms` | int/null | 流式首 token；非流式 null |
| `total_ms` | int | 端到端 |
| `retrieval_k` | int/null | 已有字段 |
| `context_chunks` | int | `context_k` |
| `refusal_stage` | str | `none` / `pre_llm` / `post_llm` |
| `cache_hit` | bool | 当前无缓存，恒 false |
| `config_fingerprint` | str | 4 个 env 的 sha256 前 12 位 |
| `language_bucket` | str | `cjk` / `latin` / `mixed` / `unknown`（只存桶，不存查询） |

**接线点（最小改动，5 个文件）**

1. `src/llm_gateway.py`：`llm_call(..., usage_sink=None)`；成功时回调
   `{"call_type","model","prompt_tokens","completion_tokens","total_tokens","latency_ms","retries_used","error_category"}`；
   `usage` 缺失时置 `usage_source="missing"`，token 记 null。
2. 流式：`kwargs["stream_options"] = {"include_usage": True}`（`:394-395` 之后）；provider 拒绝时捕获一次 → 去掉该参数重试 → `usage_source="unsupported"`。
   **必须同时改 `src/rag.py:3133`**：usage-only 尾块 `choices` 为空，`chunk.choices[0]` 会 `IndexError`；守卫后从尾块/`response.usage` 取。
3. `src/rag.py`：`answer_with_llm_history` / `_stream` 接收并转发 `usage_sink`；`generate_answer` 透传；`_plan_query_runtime` 给 rewrite/decompose 传 `_usage_sink`（两者目前只取 `retries_used`，`src/rag_query_rewriter.py:148,163`、`src/rag_query_decomposer.py:133`）。
4. `answer_query` / `answer_query_stream`：查询级 collector 汇总后 `record_query_usage(...)`；pre-LLM 拒答也记一条（0 token / 0 calls / `refused_pre_llm`），避免“免费拒答”被算成缺失。
5. `evaluation/compare.py:1581,1598`：显式传 `usage_origin="evaluation"`；`answer_query` 增加 `usage_origin="user"` 参数。**不修这条，真实台账会继续被评测污染。**

开关与读取：
- `RAG_USAGE_LEDGER`（默认 `off`）；仅当 trace consent = `minimal` 且开关 `on` 时写。
- `python -m src.usage_ledger report --days 7` 输出 n/mean/p50/p90/p95，按 `model`/`outcome`/`origin` 分层；只读。

示意（不是补丁）：

```python
# src/usage_ledger.py（示意）
def record_query_usage(**fields) -> None:
    if not _enabled():
        return
    try:
        _append(_path_for_today(), {"schema_version": 1, **fields})
    except OSError:
        log.debug("usage ledger write failed", exc_info=True)
```

### 7.3 Option B（备选，不推荐先做）：trace schema v2

- 扩 `generation.completed`：`model`、`prompt_tokens`、`completion_tokens`、`total_tokens`、`llm_calls`、`retries`、`ttft_ms`、`generation_ms`、`usage_source`、`origin`、`ts`。
- `SCHEMA_VERSION` 1→2；同步 `EVENT_TYPES` 契约、README 隐私段（`README.md:26-32`）、`patrol`、全部观测测试；旧文件兼容读取。
- 代价：需 owner 明确重开 P1.1（当前写“不重开”）；trace 文件随 per-query 元数据增长；仍需流式 usage 与 origin 接线。
- 适用：未来还要逐查询诊断/回放时；仅为 T6 成本观察则 Option A 足够。

### 7.4 两方案对比

| 维度 | Option A 台账 | Option B trace v2 |
|---|---|---|
| 触碰 P1.1 契约 | 否 | 是（需 owner 重开） |
| 原文/关联风险 | 极低（仅计数） | 低（仍不存原文） |
| 实现面 | 1 新模块 + 5 接线 | A 的全部 + schema/兼容/文档/测试 |
| 支持 T6 阈值 | 是 | 是 |
| 支持逐查询诊断 | 否（只有聚合行） | 是 |
| 推荐顺序 | **先做** | 需要时再做 |

### 7.5 测试清单（实现时）

1. 非流式 usage → 台账字段与 fake `response.usage` 一致。
2. 流式 usage-only 尾块 → 无 `IndexError`，token 入账。
3. provider 无 usage → `usage_source=missing`、token=null（不是 0）。
4. provider 拒绝 `stream_options` → 只回退一次，不重复计数。
5. 重试 → `retry_count` 正确，token 按每次成功调用累加。
6. pre-LLM 拒答 → 0 calls / 0 token / `pre_llm`。
7. consent off 或开关 off → 不落任何文件。
8. 写盘失败 → 查询仍成功。
9. 90 天清理。
10. 台账行不含 `query/answer/prompt/trace_id/session_id` 等键。
11. 聚合 p50/p90/p95 在固定夹具上正确。
12. `config_fingerprint` 稳定且为 12 位十六进制。

### 7.6 风险与边界

- **provider 差异**：OpenAI 兼容端点未必都支持 `stream_options.include_usage`；不支持时只能 `unsupported` + null，不估算。
- **重试计费**：失败调用若已产生 usage，需要计入；实现时按“每次调用一条子记录、查询级汇总”避免漏计/重计。
- **流式中断**：可能已生成 token 但无 usage 返回 → `partial`，token null，`llm_calls` 仍计。
- **并发**：多线程写同一日文件需锁或单写者队列。
- **评测污染**：必须同时修 `origin` 注入，否则台账重蹈 trace 覆辙。
- **隐私**：`model`/`token`/`route`/`language_bucket` 均非内容；`config_fingerprint` 只哈希 4 个数值型 env。

---

## 8. owner 可执行采集步骤

| 步骤 | owner/工程动作 | 验收 |
|---|---|---|
| 1. 决策 | 批准 Option A；同意新增 `src/usage_ledger.py` 与 5 处接线（另任务） | 书面批准 |
| 2. 实现 | 按 §7.2 + §7.5；`RAG_USAGE_LEDGER` 默认 off | 测试全绿；默认行为不变 |
| 3. 采集前 | `/consent` 保持 `minimal`；固定 4 个 env；固定模型；记录 `config_fingerprint` | 配置快照入档 |
| 4. 采集 | 真实使用 ≥1,000 查询/周（或先按 §12.4：107 例可检出 15%、239 例可检出 10%） | n 达标 |
| 5. 巡检 | 只读聚合；`python -m src.production_observability patrol` 确认 trace 完整性未被影响 | `failed=0` |
| 6. 对照 | 均值对照 8,658 / 9,839；p95 对照 15,618 / 18,741；拒答带 [0.20,0.40] | 7 日滚动 |
| 7. 复盘 | 若触发 T1/T2/T4 阈值，按 T6 §12.3 回退四 env 或复评 | 决策入 CHANGELOG |

命令（均为只读或本地 UI）：
- `python -m src.production_observability patrol`（只读完整性巡检）
- `mneme` → `/consent`（状态/开启/撤回）、`/status`（内存内 LLM 调用摘要，含 token 合计，仅本次进程）
- 新聚合读取器：`python -m src.usage_ledger report --days 7`（实现后）

说明：n < 1,000/周时只看均值与总量，不看 p95（T6 §12.4）；本机现有 412 条不能作为该窗口的任何一部分。

---

## 9. 隐私边界

**本次审计**
- 未读取、未打印 query/history/rewritten query/sub-query/answer/model_response 原文。
- 未打印 trace id、session id、chunk id、source id、文件哈希；仅统计其存在性与数量。
- 未修改 traces、consent、tombstones；未运行任何会产生 trace 的代码路径。
- 本报告不含任何可识别内容。

**未来采集**
- 只写计数与枚举；不写原文、不写用户/会话标识、不写精确时间戳（日桶）。
- 本地存储（`MNEME_DATA_DIR/usage`）、90 天保留、整目录可删。
- 与 P1.1 一致：默认 off、显式 consent、不跨用户关联、不接入 Graph。
- 任何对外分享只给聚合表（n/mean/分位数），不给行级台账。

---

## 10. 附录

### 10.1 复现（只读，不打印原文）

```powershell
# 仅解析白名单数字/枚举字段，不打印任何文本、id 或哈希
@'
import json, glob, collections, os
root = os.path.join(os.path.expanduser("~"), ".mneme", "traces")
rows, ev = [], collections.Counter()
for f in glob.glob(os.path.join(root, "*.jsonl")):
    for line in open(f, encoding="utf-8"):
        try:
            e = json.loads(line)
        except Exception:
            continue
        ev[e.get("event_type")] += 1
        if e.get("event_type") == "generation.completed":
            rows.append((e.get("token_count"), e.get("result_length"), e.get("latency_ms")))
print("traces", len(glob.glob(os.path.join(root, "*.jsonl"))), "events", sum(ev.values()))
print("token_count sum", sum(r[0] for r in rows), "n", len(rows))
'@ | python -
```

### 10.2 证据索引

| 主题 | 位置 |
|---|---|
| 事件信封/禁止字段 | `src/production_observability.py:221-249` |
| begin_trace 字段 | `src/production_observability.py:199-214` |
| 封存与 manifest | `src/production_observability.py:300-319` |
| `token_count = len(split())` | `src/rag.py:2422`；`src/production_observability.py:272` |
| 端到端 latency | `src/rag.py:2995` |
| 生成调用丢弃 record | `src/rag.py:2297`、`src/rag.py:3117` |
| 流式 choices 无守卫 | `src/rag.py:3133` |
| gateway 仅非流式取 usage | `src/llm_gateway.py:402-408` |
| 内存 500 条 | `src/llm_gateway.py:204-207` |
| metrics 有字段不填 | `src/metrics.py:47-49`；`src/rag.py:2169-2199` |
| GLOBAL_METRICS 无落盘 | `src/metrics.py:186` |
| 评测汇总 token | `evaluation/generation_runner.py:108-126` |
| 评测可写 trace | `evaluation/compare.py:1581,1598`；`src/rag.py:2353-2361` |
| context_k 启发式 | `src/domain.py:329-346` |
| 契约关闭 | `docs/STATUS.md:245` |
| P2-1 DoD | `docs/STATUS.md:157-168` |
| 隐私说明 | `README.md:26-32` |
| T6 基线/阈值/字段 | `results/cost-baseline-2026-10-31/report.md` §3/§4/§9/§10/§12 |

### 10.3 术语

- **Minimal**：P1.1 的本地最小观测级别；只写盐化字段与漏斗元数据，不写原文。
- **NO_TRIGGER_FALLBACK**：2026-08-27 的决策——观测线不随成本/质量需求自动重开。
- **usage**：provider 返回的 token 计量；本报告中“真值”仅指这一来源。
- **代理指标**：词数、字符数、`context_k × 200` 等非 provider 计量；本报告明确禁止用于成本结论。

---

## 11. 本文件验收

- [x] 明确回答“现有 trace 是否足以计算真实成本”：**不足以（0/412 有 usage）**。
- [x] 列出精确缺失字段、缺失位置（数据层 + 代码行）与最小修复方案（Option A/B + 测试 + owner 步骤）。
- [x] 报告不含 query/answer/chunk id/trace id/session id/哈希/原文。
- [x] 未修改代码、traces、consent；未 commit、未 push。
- [ ] 修复实施：**未做**（需 owner 批准，另任务）。
