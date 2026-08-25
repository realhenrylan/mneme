# Lifecycle Immutability Report — Phase 6-B0.2

## 范围

- 只读验证：snapshot 索引可读取、可由同一有效 snapshot 显式重建，但生命周期 API 不得直接增删改。
- 不修改任何冻结 / 6-A / B0 / B0.1 / C1 / C1.1 产物；无 LLM / 生成 / 联网 / 检索策略实验；不持久化任何 Chroma 数据（临时目录，cleaned）。

## Guard 覆盖的 API

- `add_files_to_index` / `remove_file_from_index` / `sync_sources(dry_run=False)` / `add_sources`：入口 fail-closed 拒绝（先于任何解析 / model.encode / collection 读写 / commit / sidecar 写入）；`add_sources` 不能成为绕过 `add_files_to_index` 的旁路。
- `prepare_index(snapshot=None)` / `build_index(snapshot=None)` （B0.2.1）：既有 snapshot collection 拒绝默认 parser 重建（先于 model 加载 / get_or_create / parser 解析 / collection mutation）；新 collection 的普通 parser 路径不受影响。
- 只读路径保持可用：`compute_source_diff`、`sync_sources(dry_run=True)`。
- 正常重建语义不变：`prepare_index(snapshot=...)` / `build_index(snapshot=...)` 仍是唯一合法更新路径。

## 识别机制（不依赖调用方传参）

- collection 级 immutable marker：`mneme.snapshot_index=immutable`（Chroma collection metadata，sqlite 持久化；新建 build 创建时写入并保留 `hnsw:space` 与既有 metadata）。
- 旧 Phase 6-B0.1 collection（manifest `config.snapshot` 存在、尚无 marker）同样被阻断；合法 snapshot rebuild 自动迁移写入 marker。
- B0.2.1：旧 B0.1 manifest-only 判定使用 collection **自身实际**持久化目录（特征检测 `collection._client._system.settings.persist_directory`，Chroma 1.5.9 实测可用），绝不信任调用方传入 的 `chroma_path`——错误路径与 `None` 均不可绕过；无法推导真实 位置（非本地 PersistentClient）时 fail-closed 保守拒绝，绝不把「不确定」降级为「可修改」。
- B0.2.2：persist-directory 身份收紧——只接受 `is_persistent=True` 的真实持久化 client 且 persist_directory 为稳定绝对路径；EphemeralClient（is_persistent=False、残留 './chroma'）、remote、测试 double、缺失链路、仅剩未经记录的相对 persist path（创建时 CWD 已不可知）一律不可验证 → fail-closed 拒绝，绝不把「不确定」降级为「可修改」，也绝不用调用方 chroma_path 顶替真实位置；Mneme 自建 client 创建时 realpath(abspath(...)) 规范化保存绝对真实位置，CWD 切换后仍正确阻断；外部绝对路径 PersistentClient 的普通 parser / legacy 生命周期不受影响。
- marker 存在而 manifest/BM25 sidecar 缺失、损坏或与 marker 不一致时保守拒绝，绝不降级为普通 parser collection；调用方提供错误 `chroma_path` 不能绕过 marker。
- 普通 parser / legacy 索引无 marker 且无 snapshot manifest → add/remove/sync/add_sources 与默认 rebuild 行为不变。

## 实测结果（隔离临时 Chroma）

- snapshot：1006 chunks / 13 sources（真实冻结数据运行时为 1006 / 13）。
- 机械检查：53/53 项通过（明细见 summary 与 data-quality-report.json）。

## 前置复算（fail-closed，任一漂移 → 零产物）

- frozen：61 checks，0 drift，verified=True。
- phase6a：50 checks，0 drift，verified=True。
- phase6b0：64 checks，0 drift，verified=True。
- phase6b01：71 checks，0 drift，verified=True。

## Chroma 1.5.9 行为记录（实测确认）

- `collection.modify(metadata=...)` 整体替换 metadata，且 metadata 携带 `hnsw:space` 键即抛 ValueError（不支持修改距离函数）——旧 B0.1 迁移写入 marker 时显式排除 `hnsw:space` 键；实测抹除 metadata dict 中的 `hnsw:space` 不影响检索（HNSW 空间配置存于 collection 配置而非 metadata dict）。
- 新建 snapshot collection 创建时即持久化 marker，`hnsw:space` 与 既有 metadata 完整保留。

## 明确不是

- 本产物不是 active、release 或人工批准；v2.0.11 仍是只读 CANDIDATE（activation_blocked=true、human_reviewed=false）。
- 未运行 LLM / 生成模型 / LLM judge / 联网 API / query rewriting；无 overlay / active / split / locked / v2.1 产物。
- lineage 闭环：hardened manifest self-hash = `57e3ede9bbcfa2fca3bc74ed228864748ea3860ac131e29eb79eaff448990095`。
