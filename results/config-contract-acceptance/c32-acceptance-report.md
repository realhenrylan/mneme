# C 线（计划 3.2）第四轮独立验收报告

> 基于 2026-08-17 当前工作树字节独立复核；非 C 线自述。阶段 1 未修改源码/测试，不 stage/commit/push。

## 0. 决策

`C_3_2_DECISION = ACCEPT_C32_COMPLETE`

## 1. 测试隔离修复

- 两份 fixture 前后恢复 CWD、`_SCRUB_ENV` 受管环境键和 `src.config._dotenv_values`，随后调用 `reset_settings()`；未修改 `_initial_env_keys`。
- remediation2 模型切换用例接 remediation4 两个规划器用例：正向 5 次、反向 5 次，每次 `3 passed`，共 30 passed。
- remediation4 两个规划器用例单独基线：`2 passed`。
- remediation2 完整文件接 remediation4 完整文件纳入定向套件，`98 passed`。
- fresh-process 探针运行后 CWD、`LLM_MODEL`、`_dotenv_values` 与 `get_settings().llm_model` 均回到基线 `deepseek-chat`。
- 第三轮原始失败在当前字节无法稳定复现；本轮未伪造 RED，依据机制审计与重复顺序验证判定隔离修复有效。

## 2. D1 与九项门槛

- D1 专项：`17 passed`。
- 配置合同定向套件：`98 passed`。
- 全量 `python -m pytest -q`：`2656 passed, 8 skipped`，exit 0。
- `python -m py_compile`：通过。
- `git diff --check`：通过；仅有 LF/CRLF 提示，无 whitespace error。
- Settings 唯一默认源、数据目录、优先级/reset、Top-K 分离、非法配置、offline 语义、公开调用面和关键回归均通过。
- 未调用真实 LLM、网络或 ModelScope。

## 3. C 线输入当前 SHA

第三轮报告未记录逐文件 SHA，故不宣称逐项一致；以下为本轮当前字节：

- `.env.example`: `fa5b962fa908e80797724ccd7ad912859535f4bd3623f0e4895cda4a40fb0806`
- `README.md`: `e0789f7e0aaccc2555a127d5c468cb8c3324258c88772778827eea31163357dc`
- `README.zh.md`: `095d3e66dd4c11afa50803401d89afecdac6a1f982626951a43a6b31b9ae11ea`
- `src/config.py`: `0d98107cdcb0130940c8155b5d0f08285a4c98406ed6ee9959e5f3eb726bc4b1`
- `src/security.py`: `b85ce5c833901c4696ff0dc49ff5a80ae6ade7db9daef2005fdd018fafb541af`
- `tui/app.py`: `9e0a8b4e3ae4b7b8a33300c3e4a361aad1ed64aafd14f8bc94a8706910853cf0`
- `tui/service.py`: `1e71e2946c0830842b4cbfdc3be9711bae03ade4c5dac3a127806ef0a905d272`
- `tui/screens/chat.py`: `bd5ce1755b4c114c22c93f9c6dc755d0cac1a8511e0447713415a0a2e4f8b4c4`
- `src/cli_loop.py`: `54c2dda7c6960c8dcde0a63ab762b6229b37086d8044405a993eb4d2ed4803eb`
- `src/graph_rag.py`: `0c17f2f89383354156db0b32356728037f0e758536c3514407266b074c7b80d9`

## 4. 保护资产与边界

- 四组保护资产本轮未写入；仅有 pytest cache/pycache 等通常副作用。
- 既有脏工作区与暂存区保留；本轮未 reset、clean、checkout、stash、stage、commit 或 push。
- 未生成 overlay/active/split/locked/v2.1 或真实生产 trace。

## 5. 阶段 2 入口

阶段 1 已输出 `ACCEPT_C32_COMPLETE`，满足进入 P1.1-M 的第一项前置；阶段 2 尚未实施。
