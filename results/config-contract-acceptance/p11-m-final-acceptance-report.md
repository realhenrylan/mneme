# P1.1-M 最终接线与独立验收报告

- 日期：2026-08-25
- 授权依据：Owner 批准「门控管入口」策略（manifest v5 冻结 C 线接受态；接线后行为中性偏离属 P1.1 自身范围，由 Off 零效应契约测试单独验证）
- 纪律声明：全程零 git 写操作（仅 rev-parse/status/diff/show/log 只读）；全程 fake 凭据（API_KEY=sk-fake-test，BASE_URL=https://fake.test/v1）+ sitecustomize socket 全阻断；数据目录一律指向系统 temp；未读取仓库真实 `.env`（隔离副本中的 `.env` 在任何进程运行前已删除）。
- 报告顺序披露：本报告在实现阶段（S0–S4）完成后、验收阶段（A1–A7）取证完成后撰写；写入本文件不触碰任何门控/保护资产。

## 0. 决策

```
P1_1_M_FINAL_DECISION = ACCEPT_P11M_COMPLETE
```

成立条件核验：S0–S4 全绿 ✓；A1–A7 全绿 ✓；文档与字节一致 ✓；红线零违反 ✓。

## 1. 实现阶段证据（S0–S4）

### S0 入口门控复核
- HEAD=`8e3be0c6e58bfa4c03ec15a96f9a3913f0d9285b`（与任务书基线一致）；暂存区 26 项（集合 SHA `efa7211775b57075` 前后一致）；stash 为空。
- manifest v5 复算命令：Python hashlib 逐文件复算。结果 **17/17 文件 SHA 一致**、`report_sha256` 一致、`manifest_sha256` 自哈希复算一致（算法：去除 `manifest_sha256` 键后的紧凑 JSON 序列化取 SHA256，四组候选参数全部命中同一目标值）。

### S1 重新接线（恢复前轮 MINIMAL_CAPTURE_READY 形态）
- `src/rag.py`：`answer_query`/`answer_query_stream` 显式 TraceStore 生命周期（keyword-only，无全局状态）；`_plan_query_runtime` 发射 rewrite（盐化 SHA/长度/脚本）、decompose 数量、dense/BM25 分通道候选（chunk_id/rank/score，经 `_channel_sink` 侧信道）、RRF 融合；sync/stream 分别发射 cutoff/refusal/context/generation 终态/citation 状态/长度/延迟；planning_profile 与 retrieval_k 如实记录（stream=现状 max(top_k_range)，检索宽度未改）；同步异常路径 discard 后原样重抛；流式 GeneratorExit 经 `capture_discard` 清理、终态封存不阻塞 TTFT。
- `src/cli_loop.py`：新增 `_handle_trace_command` 并接入交互循环；delete-trace 仅接受完整 32 位 hex ID，拒绝模糊/前缀/通配删除。
- `tui/screens/chat.py`：`/consent` 用户可见说明（本地、最小化、不存原文、不上传、可撤回/删除、默认关闭）+ 显式 on/off；`/delete-trace` 同样 32-hex 严格。

### S2 行为中性证明
- 新增 `tests/test_p11m_off_neutrality_contract.py`（5 用例），**RED→GREEN**（RED 计入下述 11 failed 基线）。
- Off 时 sync/stream 输出逐字节等于未接线基线字面量、traces 目录零创建、emit 平均 0.086µs（探针实测）。

### S3 回归计数（全部真实运行）
| 套件 | 结果 |
| --- | --- |
| 观测组合并（`test_production_observability*.py` 现存 7 文件 + 新增中性契约 + 新增接线契约） | **35 passed** |
| 配置契约组（contract/startup/remediation2–6/round7） | **134 passed** |
| CLI/citation 组（cli_citation_integrity/citation_integrity/citation_loop/citation_aggregation） | **87 passed** |
| G1-S capture 两组（query_plan_capture + hardening） | **108 passed** |
| planner/retrieval/refusal/Graph 组（rewriter/decomposer/retrieval×2/refusal×2/graph×3） | **135 passed, 4 skipped** |
| 全量 `python -m pytest -q`（带护栏） | **2691 passed, 8 skipped，exit 0** |
| 保护资产护栏（365 项前后 SHA 比对，全量前后各一次） | **0 漂移** |
| py_compile 全部改动文件 / `git diff --check` | 通过 / exit 0（仅既有 LF/CRLF 提示） |

- TDD RED 基线（接线前）：新两文件 + 既有观测组共 **11 failed / 3 passed**；修复过程两次根因明确（Off 路径无条件转发新 kwargs 与旧签名 fake 不兼容 → 改为仅观测激活时附加参数），单变量修复后全绿。
- 如实偏差：任务书称 `test_production_observability*.py` 为 8 个文件，磁盘现存 **7 个**；以现存文件全跑为准，特此记录。
- 修复期间一次失败定位：remediation4 `test_prepare_answer_evidence_forwards_temperature`（fake_plan 旧签名）；citation_integrity 9 例（`_fake_retrieve` 旧签名）。均属接线兼容性问题而非策略改动，修复后对应组全绿。

### S4 文档一致性
- `CHANGELOG.md` 新增 2026-08-25 条目（含「曾回退、本次重接」两段事实、额外改动披露、全部计数）。
- `plans/RAG-IMPROVEMENT-PLAN-2026-08-01.md` §十「当前下一步行动」补记回退/重接事实与本报告路径。
- 编辑事故披露：CHANGELOG 首次编辑曾误吞 `## 2026-08-17` 标题，当轮发现并恢复，最终结构经复读确认。

## 2. 验收阶段证据（A1–A7，temp 隔离副本 fresh-process）

### A1 隔离副本
- robocopy 完整复制工作树至 `%TEMP%\p11m-acceptance-20260825`；排除项（非项目字节）：`.git`（VCS 内部）、`venv`（环境）、`__pycache__/.pytest_cache`（派生缓存）。文件数核对：源 1242 − 缓存 6 − `.env` 1 = 副本 1236，精确一致。
- 副本内 `.env` 已在任何进程运行前删除（红线：不读真实凭据）；sitecustomize 部署于副本根部（socket.socket/getaddrinfo/create_connection/gethostbyname 全 fail-fast + 尝试计数）。

### A2 门控与不变式
- 副本内复算：14/17 文件 SHA 与 v5 一致；偏离集合**恰为** {src/cli_loop.py, tui/screens/chat.py, src/rag.py}（Owner 批准的预期接线偏离）；manifest 自哈希 PASS、report SHA PASS。
- 真实仓库：HEAD 未变、暂存区集合哈希与基线一致、stash 空；状态行增量恰为本任务 4 个修改文件转脏 + 2 个新测试文件。

### A3 Off 零效应探针（fresh subprocess）
- 输出：sync/stream 两路 ×（显式传 store / 默认环境解析）输出逐字节等于预期拒答文本与空 sources；traces 目录零创建；emit 平均 **0.086µs**；`network_attempts = {"count": 0}`；exit 0。

### A4 Minimal 正路径（fresh subprocess，consent On）
- begin→rewrite→decompose→dense→bm25→fusion.rrf→cutoff→context→generation.completed→trace.end 全漏斗封存成功；`verify_integrity()` 通过；流式拒绝路径封存并通过完整性校验。
- 人为篡改一行 chunk_id（`"c0"`→`"c9"`）后 `verify_integrity` **fail-closed**：`ValueError("trace integrity check failed")`。
- 删除墓碑生效（segment+manifest 移除、tombstones.json 记录）；再 replay 报 `TraceDeletedError("trace has been deleted")`——错误信息不含被删内容；重复删除幂等且不复活文件。
- `network_attempts = {"count": 0}`。

### A5 隐私审计
- 扫描 traces 下全部 4 个落盘文件（stream 段 JSONL + 其 manifest + consent.json + tombstones.json）：零命中 query 原文（3 个测试 query）、rewrite/decompose 产物原文、回答正文、凭据（sk-fake-test/fake.test/API_KEY/BASE_URL）；consent 键集合恰为 {schema_version, level, session_id, updated_at, self_sha256}（无 salt）。
- emit 对 10 个敏感键（query/history/answer/model_response/prompt/document/api_key/authorization/base_url/path）在隔离副本内全部拒绝（ValueError 含 "sensitive"）。

### A6 策略红线抽查
- 字节级：7 个策略承载文件（config/graph_rag/security/retrieval/rag_query_rewriter/rag_query_decomposer/llm_gateway）与 v5 **逐字节一致**；G1-S `CAPTURE_MODE="synthetic_only"`（query_plan_capture.py:52）且三份 G1-S 资产 mtime 均早于本会话（08-13/08-15/08-17）。
- 常量现值：`SELECTOR_MAX_PER_SOURCE` 默认 3；`DEFAULT_REFUSAL_THRESHOLD=0.03`（config.py，v5 字节）；stream `retrieval_k=max(top_k_range)` 保持现状；reranker/selector `min(k, 20)` 预算 6 处未动；Graph 默认策略承载文件未触碰。
- 审计基准诚实声明：`git diff`（vs HEAD）含大量会话前既有脏改动（C 线遗留），不作为本次审计基准；本次基准 = S0 的 v5 字节对账（14 精确一致 + 3 文档化偏离）+ 仅加法式接线编辑审查 + 全量语义锁定回归（G1-S 合同 108、citation 语义、配置契约 134 全绿）。

### A7 汇总
见 §0 决策、§3 清单、§4 边界。

## 3. 清单

### 因接线而偏离 v5 的文件清单（17 文件中恰 3 个）
| 文件 | 偏离性质 |
| --- | --- |
| `src/rag.py` | 加法式观测接线：生命周期辅助函数块、`_plan_query_runtime`/`prepare_answer_evidence` keyword-only trace 参数与事件发射、`retrieve_hybrid_with_sources` 可选 `_channel_sink` 侧信道（Off 时零附加参数）、`StreamResult` 双回调字段、`answer_query`/`answer_query_stream` 生命周期挂接；检索/生成策略代码路径零语义变更 |
| `src/cli_loop.py` | 新增 `_handle_trace_command`（32-hex 严格删除）及交互循环路由；既有问答流程未动 |
| `tui/screens/chat.py` | 新增 `/consent`、`/delete-trace` 处理器与分发分支；其余 UI 流程未动 |

### 改动/新增文件清单（本任务全部写入面）
- 修改：`src/rag.py`、`src/cli_loop.py`、`tui/screens/chat.py`、**`tui/keys.py`**（额外披露：既定三处之外的第 4 个既有文件，为满足强制 ux 契约测试所必需的两条命令注册；该文件不在 manifest v5 的 17 文件内，不构成 v5 漂移）、`CHANGELOG.md`、`plans/RAG-IMPROVEMENT-PLAN-2026-08-01.md`
- 新增：`tests/test_p11m_off_neutrality_contract.py`、`tests/test_production_observability_wiring_contract.py`、本报告
- 未触碰：`src/production_observability.py` 与既有 7 个观测测试文件（保持前轮字节原样使用）

### 环境观察（非本任务造成，如实记录）
- 验收期间检测到**另一并行会话**在同一仓库于 19:07–19:09 关闭 B0.2 子线：新建 `results/b02-lifecycle-acceptance/` 两文件并向 CHANGELOG/PLAN 追加其条目。经逐项复核：本任务的源码四文件与 A1 副本字节一致（SAME）、我的文档条目完好、v5 三组哈希与保护资产护栏终验不受影响（365/0 drift）。该会话产物属其自身工作流记录，本报告不做处置。

## 4. 未解决边界（继承前轮 + 本轮新增）

1. 跨会话聚合不可用（盐会话内随机且不落盘，按设计）。
2. 写入失败静默不向回答路径传播，无审计告警通道（与 metrics 持久化一致，fail-open 设计取舍）。
3. `test_production_observability*.py` 实际 7 个文件 vs 任务书表述 8 个，差异原因不明，按现存文件验证。
4. `delete_trace` 对同一 ID 重复删除为幂等成功（无「再删报错」路径）；墓碑防 replay 已覆盖删除后语义，「报错不含被删内容」经由 TraceDeletedError 验证。
5. 全量 pytest 曾在前轮出现资源争用型偶发失败；本轮单次全量即 2691 passed / exit 0，未见复发。
6. 并行会话共存属环境事实：若后续字节需要再冻结，应以本报告时点的 SHA 表为准另行固化为新的 manifest（本轮被禁止改写 v5，故未执行）。
