# P1.1-M Minimal-only 本地观测实现报告

- 日期：2026-08-17
- 前置：`C_3_2_DECISION = ACCEPT_C32_COMPLETE`（第四轮验收，manifest self-hash 闭环一致）
- Owner 固定策略：Minimal-only；默认 Off；显式 consent；本地 `MNEME_DATA_DIR/traces`；30 天保留；单 trace 删除/撤回；Exact replay 禁止；Graph 不接入；`src/query_plan_capture.py` 保持 synthetic-only。
- 本实现未调用真实 LLM、网络或 ModelScope；未 stage/commit/push；未触碰既有脏工作区与暂存区。

## 0. 决策

`P1.1-M_DECISION = MINIMAL_CAPTURE_READY`

## 1. RED → GREEN 证据

新增 `tests/test_production_observability_contract.py`，先运行得到真实 RED（3 failed, 1 passed）：

- `test_minimal_emit_rejects_raw_sensitive_fields`：raw 敏感字段未被拒绝 → 现 emit 固定拒绝 query/history/answer/model_response/prompt/document/api_key/authorization/base_url/path 键。
- `test_verify_integrity_checks_receipts_and_manifest`：无只读完整性 API → 新增 `TraceStore.verify_integrity()`（逐行 receipt、segment SHA、manifest self-hash 校验）。
- `test_exact_replay_is_explicitly_rejected`：Exact replay 未明确拒绝 → 新增 `TraceStore.exact_replay()` 恒定 `NotImplementedError`。

GREEN：`tests/test_production_observability_contract.py tests/test_production_observability.py` → `10 passed`。

## 2. 实现内容

### `src/production_observability.py`
- 保留 `TraceStore` 为唯一 production trace 后端；未 consent 时 emit 全部 no-op，不创建目录/文件、无额外 LLM/API/网络调用。
- `emit()` 增加固定 Minimal payload 脱敏校验：禁止原文/凭据/路径/完整 prompt 与 response 键，禁止非 JSON 安全值。
- 新增只读完整性 API `verify_integrity()`：逐行 line receipt、segment SHA、manifest self-hash 全链校验，篡改抛 `ValueError`。
- 新增 `discard_trace()` 异常安全清理；新增 `exact_replay()` 恒定拒绝 Exact replay。
- 删除/清理限域保持不变：仅接受 32-hex trace id，路径 root 校验必以 `traces` 结尾且不在仓库/评测树内；单 trace 删除、30 天 prune、撤回停止新采集。

### `src/rag.py`
- Standard RAG 同步 `answer_query` 与流式 `answer_query_stream` 接入显式 trace 生命周期（keyword-only 传递，无全局请求状态）。
- `_plan_query_runtime` 内 emit：rewrite（仅长度/脚本/盐 SHA）、decompose 数量、dense/BM25 分通道候选（id/rank/score）、RRF 融合；同步/流式分别 emit：cutoff、refusal、context、generation 终态、citation 状态与结果长度/延迟字段。
- 同步异常路径 `discard_trace` 后重抛；流式 `StreamResult` 增加 `capture_discard` 在 GeneratorExit 时清理。
- 所有 payload 只含稳定 `chunk_id/source_id`、rank/score、长度/哈希；`planning_profile` 与 `retrieval_k` 如实记录（stream=20 不改变检索策略）。

### `tui/screens/chat.py`、`src/cli_loop.py`
- TUI `/consent` 增加用户可见说明（本地、最小、不保存原始问题/回答、不上传、可撤回/删除，默认关闭）。
- CLI `delete-trace` 仅接受完整 32 位 ID，拒绝模糊/宽泛删除。

## 3. 验证结果

### 默认 Off 零副作用
- `test_off_does_not_create_trace_directory`（既有）通过：OFF 时不创建 traces 目录。
- 性能基线：OFF 时 `emit` 每次约 0.24 微秒（no-op），回答字节与既有行为不变。

### 敏感字段零落盘
- 现有与新增测试扫描 JSONL/manifest/consent：不含 query 原文、salt、回答正文、凭据；`emit` 固定拒绝敏感键。

### 完整性与隔离
- 新增 `verify_integrity` 测试通过；伪钞篡改（改写 chunk_id）被拒绝。
- 删除/保留测试（既有）通过；G1-S `src/query_plan_capture.py` 与两份 G1-S 测试未修改，synthetic-only 边界保持。

### 性能
- OFF：每次 emit 约 0.24 微秒。
- ON：一次完整 trace（begin+2 emit+finish 含原子封存写盘）约 4.4 毫秒；相对真实检索数百毫秒级别开销 <5%，且流式在终态后才封存，不阻塞 TTFT。

### 回归
- 定向套件（citation、CLI citation、G1-S、production observability 合同、remediation4）：`159 passed`；Chroma/来源套件 `40 passed`。
- 全量 `python -m pytest -q`：**`2677 passed, 8 skipped`**，exit 0（首次全量在资源争用下出现 2 个失败，经单独复跑与整文件复跑全部通过，其中 1 个为集成测试对旧接口的适配更新）。
- `python -m py_compile` 全部改动文件：通过；`git diff --check`：通过。

### 保护资产
- 四组保护资产（`evaluation/datasets/**`、`evaluation/product-baselines/**`、`evaluation/datasets/v2/revisions/**`、`src/query_plan_capture.py`、两份 G1-S 测试）365 个文件，实施前后 SHA 逐项比对：0 新增、0 缺失、0 变化（全量运行后复验 diff count 0）。

## 4. 写入文件清单

- 修改：`src/rag.py`、`src/production_observability.py`、`src/cli_loop.py`、`tui/screens/chat.py`、`tests/test_production_observability_integration.py`、`plans/P1.1-PRODUCTION-OBSERVABILITY-REPLAY-CONTRACT-2026-08-13.md`、`plans/RAG-IMPROVEMENT-PLAN-2026-08-01.md`、`CHANGELOG.md`
- 新增：`tests/test_production_observability_contract.py`、`results/config-contract-acceptance/`（第四轮报告与 manifest）、`results/protected-after-v4.txt`
- 未生成 overlay/active/split/locked/v2.1 或真实生产 trace；未 stage/commit/push。

## 5. 未解决边界

- 跨会话聚合仍不可用（salt 会话内随机且不落盘，按设计）。
- 写入失败静默不向回答路径传播，因此无审计告警通道（与 metrics 持久化一致）。
- 全量二次运行在有并发/资源争用时个别 Chroma 用例曾出现环境性失败，单独与整文件复跑均通过；不属于本实现引入的逻辑缺陷。