# Phase 6-B0.2.5 独立验收报告 — Snapshot Index Lifecycle Immutability 最后一轮修复

**验收日期**：2026-08-25
**验收对象**：B0.2.5（同进程顺序依赖修复）在当前工作树字节上的独立复核，通过后正式关闭 Phase 6-B 线 B0.2 子线
**验收角色**：独立验收 agent（只验收、不修码）

---

## 决策

```text
B_0_2_DECISION = ACCEPT_B02_LIFECYCLE_HARDENING_COMPLETE
```

十项验收门槛全部真实通过，无放宽、无跳步。Phase 6-B 线的 B0.2 子线（Snapshot Index Lifecycle Immutability）正式关闭。

## 基线记录

- **HEAD**：`8e3be0c6e58bfa4c03ec15a96f9a3913f0d9285b`（main），验收全程未变。
- **工作区**：起始 251 个脏条目；全程未执行 reset/clean/checkout/stash/stage/commit/push。
- **保护资产基线**：四组（`evaluation/datasets/**`、`evaluation/product-baselines/**`、`evaluation/datasets/v2/revisions/**`、`src/query_plan_capture.py` 及两份 G1-S 测试）共 **365 文件** SHA256 于验收开始时采集，结束时逐项比对 **added=0 removed=0 changed=0（零漂移）**。

## 门槛 1：b022 时序重构源码审计 — PASS

对 `scripts/evaluate_v211_frozen_contract_lifecycle_hardened.py` 源码逐点核实：

1. **① 创建即保存**：`rel_ids_before = sorted(rag._collection_data(rel)["ids"])` 位于 line 691，在 cwd_a 内创建并写入 rel collection 之后、`os.chdir(str(cwd_b))`（line 692）之前完成。
2. **② cwd_b 只做 fail-closed 检查**：切换后先断言 `b022.relative_no_residue_in_new_cwd`（line 696–698），随后仅执行 guard 在任何 collection 读取之前就拒绝的检查——四 mutation（line 699–719）、None 路径（line 720–724）、`prepare_index`（line 734–748）、`build_index`（line 749–758）。cwd_b 内没有任何对 rel 的真实 collection 读取。
3. **③ 零漂移复读时机**：`b022.relative_zero_drift` 在 `os.chdir(str(cwd_a))` 之后复读（line 760–763），真实读取、非 mock 掩盖。
4. **④ 检查级 scoped 释放**：prepare_index 检查前快照 `{id(c) for c in rag._CHROMA_CLIENTS}` 与 `SharedSystemClient._identifier_to_system.keys()`（line 730–733），finally 中立即 `_release_scoped_chroma(pre, pre)`（line 747–748）；该函数复用 `_release_owned_chroma(pre_rag_ids, pre_system_ids, set())`（line 239–245），只关闭/stop/移除边界快照之后新建的 client/system，运行前已有资源一律不动。grep 证实脚本**不调用** `rag.close_chroma_clients()` 与 `clear_system_cache()`（仅在 docstring 中作为「不调用」约定出现）。
5. **⑤ 断言未删除未放宽**：`b022.relative_prepare_parser_rebuild_rejected`（line 739/744）与 `b022.relative_build_parser_rebuild_rejected`（line 754/757）均保持「无异常 → False('no exception') / SnapshotIndexImmutableError → True」的原断言语义。

四个 B0.2.5 回归测试（`test_relative_client_collection_reads_only_in_creation_cwd`、`test_prepare_rejection_releases_same_dir_client_promptly`、`test_consecutive_verifications_with_external_client_alive`、`test_temp_chroma_cleaned_failure_sequence_regression`）均在 eval 测试文件中存在。

## 门槛 2：同目录 client 零滞留行为探针 — PASS（6/6）

独立于仓库测试代码构造 b022 关键序列（一次性系统临时目录、真实 Chroma）：

| 探针 | 结果 |
|---|---|
| 运行前外部绝对路径 client 存活 | PASS |
| prepare_index(snapshot=None) 对同目录 snapshot manifest 拒绝 | PASS |
| 拒绝后新建 system 标识零滞留（`new_ids=[]`） | PASS |
| 拒绝后新建 rag client 零滞留（`new_rag_count=0`） | PASS |
| 外部 client 结束后仍可读原记录（count/get 正常） | PASS |
| 外部 system 标识仍在缓存未被 stop | PASS |

## 门槛 3：历史绕过路径对抗性重测 — PASS（含门槛 4/5 共 23/23）

隔离临时目录 + 真实 Chroma + fixture 语料 + encode 哨兵（证明 encode 未被触达）：

| # | 攻击路径 | 结果 |
|---|---|---|
| A | EphemeralClient 四 mutation API → 全部抛 `SnapshotIndexImmutableError`（fail-closed：无法确认持久化位置） | PASS |
| B | 外部相对路径 `rel_db` + CWD a→b × 四 API → 全拒，错误目录零 sidecar | PASS |
| C1 | 错误 `chroma_path` × 四 API（marker 权威）→ 全拒 + wrong_db 零写入 + 主 collection 字节不变 | PASS |
| C2 | `chroma_path=None` × 四 API → 全拒 + 默认目录零写入 | PASS |
| D1 | `dataclasses.replace(snap, fingerprint="f"*64)` → prepare_index 拒绝且目标目录零写入 | PASS |
| D2 | 同伪造 → 直接 build_index 拒绝且零写入 | PASS |
| D3 | 内存篡改 chunk 文本（保留原指纹）→ prepare_index 拒绝且零写入 | PASS |
| D4 | 磁盘篡改 chunk 行文本（不改 chunk-manifest SHA）→ `load_chunk_snapshot` 即拒（1 drift item） | PASS |
| E | 合法 snapshot 索引 + 缺失/额外 source → ValueError(source set mismatch)，collection/manifest/BM25 字节不变 | PASS |
| F | snapshot collection 遭 `prepare_index(snapshot=None)` / `build_index(snapshot=None)` parser 重建 → 双拒且零写入 | PASS |
| 第7条 | 真实冻结语料显式重建：`test_real_lifecycle_verification_1006` + `test_real_frozen_snapshot_lifecycle_immutable` **2 passed in 76.41s**（1006 chunks / 13 sources 身份不变、manifest 闭环） | PASS |

## 门槛 4：读操作保留 — PASS

`compute_source_diff` 返回完整四段 diff（unchanged=3/3）；`sync_sources(dry_run=True)` 返回 added=0/updated=0/removed=0；两操作后主索引目录树 SHA 零漂移。

## 门槛 5：普通索引不受影响 — PASS

外部绝对路径 PersistentClient 上 parser collection 完整生命周期正常：build/add/remove/sync(dry_run=False)/add_sources 全部生效，collection 无 snapshot marker（metadata 仅 `hnsw:space`）。

## 门槛 6：顺序独立性（B0.2.4 失败场景必须消失）— PASS，全部 0 failed

| 命令 | 结果 |
|---|---|
| eval 测试文件单独跑 | **18 passed** in 68.90s |
| immutability + eval 两文件联合第 1 轮 | **43 passed** in 92.29s |
| 两文件联合第 2 轮 | **43 passed** in 92.58s |
| 两文件联合第 3 轮 | **43 passed** in 92.70s |
| 最小顺序命令（immutability::external_relative → eval::fixture_ok） | **2 passed** in 9.19s |
| 最小顺序命令反向 | **2 passed** in 9.66s |

B0.2.4 记录的两个失败场景（eval 单独 `1 failed, 13 passed`、联合 `1 failed, 38 passed`）在本环境当前字节上已不存在。

## 门槛 7：产物闭环 — PASS

`evaluation/product-baselines/v2.0.11-frozen-contract-lifecycle-hardened/`：

- **manifest self-hash 复算 MATCH**：recorded = recomputed = `62680efdbc2d0966ef19c125673acdc2637b0ef4bfa2c3d4280ffd69e53b759d`。
- **outputs**：data-quality-report.json / lifecycle-hardening-summary.json / lifecycle-immutability-report.md 三项字节 SHA 全 match。
- **inputs**：42 项（绝对 path + sha256 形态）逐项比对 **mismatch=0**。
- **质量结论引用**：data-quality-report `passed=true, error_count=0, checks 57/57 全过`；lifecycle-immutability-report.md 明示「机械检查：53/53 项通过」；summary `cleaned=True`、verification frozen/phase6a/phase6b0/phase6b01 = 61/50/64/71 项 drift=0 全 verified。
- **独立重建一致性**：以与磁盘产物相同的调用形态（不传 data_dir，脚本自管临时目录）真实重建一次（49.5s，status=ok，cleaned=True），四产物与磁盘版本**逐字节一致（diff_count=0）**。
- 说明：首次重建尝试因本验收传入了显式 `data_dir` 参数（与磁盘产物的生成形态不同），导致 `cleaned=False`、`declarations.chroma_persisted=True` 两字段及连锁哈希不同——经字段级 diff 定位为**调用参数形态差异，非脚本非确定性缺陷**；改用同形态后逐字节一致。

## 门槛 8：冻结与历史产物零漂移 — PASS

自闭环复算（self-hash + outputs/inputs 字节 SHA）：

| 资产 | 结果 |
|---|---|
| v2.0.11 revision（candidate 根 manifest） | self_hash=MATCH `066b0f7fad1f0be6…` |
| targeted-re-review manifest | self_hash=MATCH `5445379f9419850f…` |
| evaluation-freeze manifest | self_hash=MATCH `cd75d485d7463d02…` |
| 6-A baseline（v2.0.11-frozen-current） | MATCH `57388f1ceda171e9…` outputs/inputs 0 mismatch |
| B0（v2.0.11-frozen-contract） | MATCH `b3fc4b6ea575530f…` 0 mismatch |
| B0.1 hardened（frozen-contract-hardened） | MATCH `57e3ede9bbcfa2fc…` 0 mismatch |
| lifecycle-hardened（本轮对象） | MATCH `62680efdbc2d0966…` 0 mismatch |
| C1（cross-document-ablation，7 文件） | MATCH `45f40c63e5dccb18…` |
| C1.1（ablation-audit-correction，4 文件） | MATCH `99cc85476ebeba33…` |
| v2.0.10 等 9 个历史 revision | self_hash 均 MATCH |

观察记录（如实）：`revisions/v2.0.1-persistent-reject-repair/` 的 manifest 为最早期格式，按现行 self-hash 约定复算不闭环——该目录为 **untracked 历史遗留**（git 确认从未提交、本次验收未触碰），不属于 B0.2 验收门槛所列资产，非本次漂移。

**最终硬标准**：365 个保护资产文件验收前、后两次 SHA 比对 **added=0 removed=0 changed=0**。

## 门槛 9：整体回归 — PASS

- **定向回归**：index_contract + source_lifecycle + source_identity + index_lifecycle_immutability + phase_b_manifest + retrieval 共 **115 passed** in 56.25s。
- **全量 pytest（标准形态）**：**2691 passed, 8 skipped, 0 failed** in 467.95s，exit 0。
- 过程记录（如实）：首次全量以 `MNEME_OFFLINE=1` 运行得 `1 failed, 2690 passed`，失败点 `test_phase_d_p0.py::test_embedding_model_fallback_uses_requested_identifier`（`src/rag.py:182 RuntimeError: 离线模式下无法加载本地 embedding 模型: custom-model`）。单独复现证实该失败由**验收命令自带的环境变量**改变 `offline_mode` 设置所致（测试的 fake 模型加载路径按设计被离线模式拒绝），去掉该变量后同文件 **9 passed**——非产品回归、非 B0.2 缺陷。随后以标准形态重跑全量得到上述全绿结果。
- **py_compile**：验收对象脚本 + 两测试 + src/rag.py → exit 0。
- **git diff --check**：exit 0（仅 CRLF 提示，无空白错误）。

## 门槛 10：边界自证 — PASS

- v2.0.11 保持 `CANDIDATE / activation_blocked=true / human_reviewed=false`（lifecycle-hardened summary 与 revision manifest 双重确认）。
- 无 overlay/active/split/locked/v2.1 新增：`evaluation/datasets/v2/split/` 为 git tracked 历史冻结产物（case-freeze/seal-audit/split-lock）；仓库内 mtime 异动的 `None/chroma.sqlite3`（08-12）与 `data/chroma/`（08-04）均为验收开始前的历史遗留脏文件，非本次产生。
- **HEAD 全程未变**：`8e3be0c`；未 stage / commit / push。

## 并行改动观察（如实记录，不影响验收有效性）

验收进行期间（18:35–18:51）检测到另一并行进程修改了 `src/cli_loop.py`、`src/rag.py`（18:46）、`tui/keys.py`、`tui/screens/chat.py`、两个 P1.1 相关测试及若干数据文件 mtime。经复核：

- B0.2 验收对象文件未被触碰：验证脚本与两份测试文件的 mtime 仍为 2026-08-13（B0.2.5 实现当日字节），conftest 为 08-12；
- `src/rag.py` 门控区段（SNAPSHOT_INDEX_MARKER_KEY L843 / SnapshotIndexImmutableError L847 / _collection_persist_dir L870 / _assert_mutable_collection L899 / _assert_parser_rebuild_allowed L954）行号与内容特征与本验收审计时一致；
- 保护资产 365 文件字节前后零漂移（并行改动未触及受保护资产的有效字节）；
- 全量 pytest（18:52 启动）运行于包含并行改动的当前字节，仍 0 failed。

## 边界声明

本验收全程：未修改任何源码/测试/产物；未 reset/clean/checkout/stash/stage/commit/push，既有脏工作区保留；未调用真实 LLM/网络/ModelScope（对抗探针全部使用一次性系统临时目录 + 本地缓存模型/哨兵模型，结束后自行清理，含历史遗留 `%TEMP%\mneme_b02_audit_*` 探针目录）；v2.0.11 冻结语料、受保护评测资产与既有脏工作区字节零触碰（365 文件前后 SHA 一致）；未生成 overlay/active/split/locked/v2.1 或真实生产 trace。仓库内写入仅限本报告、同目录 manifest.json、计划文档状态纠正与 CHANGELOG 条目。
