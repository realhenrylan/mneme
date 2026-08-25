"""Phase 6-B0.2 / B0.2.1 / B0.2.2 — frozen contract lifecycle hardening.

补上 Phase 6-B0.1 已确认的最后一个产品安全缺口：由受验证 snapshot 建出的
索引可读取、可由同一有效 snapshot 显式重建，但不得被生命周期 API 直接
增删改（add_files_to_index / remove_file_from_index / sync_sources /
add_sources 一律 fail-closed 拒绝；compute_source_diff 与
sync_sources(dry_run=True) 保持只读）。

Phase 6-B0.2.1 修复两个验收缺陷：
1. 旧 B0.1 manifest-only snapshot collection 可被错误 / None chroma_path
   绕过 —— manifest-only 判定改用 collection **自身实际持久化目录**
   （特征检测 ``collection._client._system.settings.persist_directory``），
   绝不信任调用方传参；位置不可推导时 fail-closed 拒绝；
2. snapshot collection 被默认 parser 重建（prepare_index / build_index 的
   snapshot=None）会残留 marker 造成状态不一致 —— 对既有 snapshot
   collection（marker 或 manifest config.snapshot）的默认 parser 重建
   在 model 加载 / get_or_create / parser 之前拒绝，snapshot=... 显式
   rebuild 是唯一合法更新路径。

Phase 6-B0.2.2 关闭 B0.2.1 审计发现的 persist-directory 身份绕过：
1. EphemeralClient（is_persistent=False、残留 persist_directory
   './chroma'）被当作真实位置 —— persist 身份只接受 is_persistent=True
   的真实持久化 client；
2. 外部以相对路径创建的 PersistentClient（persist_directory 保留相对串）
   在 CWD 切换后按新 CWD 解析错误目录 —— persist_directory 必须是稳定
   绝对路径，Mneme 自建 client 创建时 realpath(abspath(...)) 规范化。
   非持久化 / remote / 测试 double / 缺失链路 / 仅剩相对 persist path
   一律不可验证：公开 mutation 与默认 parser rebuild 一律 fail-closed
   拒绝，绝不把「不确定」降级为「可修改」，也绝不用调用方 chroma_path
   顶替；外部绝对路径 PersistentClient 的普通 parser / legacy 生命周期
   不受影响。

本脚本是**只读验证**：不修改任何冻结 revision / chunks / draft / evidence /
6-A / B0 / B0.1 / C1 / C1.1 产物；不运行 LLM / 生成 / 联网 / 检索策略实验；
不持久化任何 Chroma 数据（临时目录 + cleaned）。

fail-closed 顺序（任一漂移 → BaselineDrift，零产物）：
1. 冻结输入复算（bl6a.verify_frozen_inputs，61 项）；
2. Phase 6-A manifest 复算（cbl.verify_phase6a_manifest，50 项）；
3. 旧 Phase 6-B0 manifest 复算（hbl.verify_b0_manifest，64 项）；
4. Phase 6-B0.1 hardened manifest 复算（hbl.verify_b0_manifest，71 项）
   —— lineage 闭环到 hardened manifest 与其已验证 lineage。

随后在隔离临时 Chroma 中用真实冻结 snapshot 实测：四类生命周期 mutation
拒绝（拒绝前后 collection count/ids 与 manifest/BM25/graph sidecar 字节
零漂移，model.encode 未调用）、只读 diff/dry-run、fail-closed 矩阵
（marker-only / malformed manifest / marker-manifest mismatch / 错误
chroma_path）、旧 B0.1 manifest-only 形态阻断与合法 rebuild 迁移写入
marker、B0.2.1 矩阵（manifest-only + 错误 / None chroma_path、snapshot
collection 拒绝默认 parser 重建、parser collection 默认 rebuild 不变、
错误路径 rebuild 只作用于错误目录）、B0.2.2 矩阵（EphemeralClient 四类
mutation 与 parser rebuild 拒绝、外部相对路径 PersistentClient + CWD
切换 fail-closed、Mneme 自建相对 client 绝对化、外部绝对路径 client
生命周期正常）、普通 parser 索引生命周期语义不变。

产物（4 个）：lifecycle-hardening-summary.json / lifecycle-immutability-
report.md / data-quality-report.json / manifest.json（自哈希约定 +
inputs/outputs SHA 闭环）。
"""

from __future__ import annotations

import io
import json
import os
import shutil
import sys
import tempfile
import time
from contextlib import redirect_stdout
from pathlib import Path

# 强制离线（在导入任何模型库之前无条件设置，与 Phase 6-A/B0/B0.1 一致）
os.environ["HF_HUB_OFFLINE"] = "1"
os.environ["TRANSFORMERS_OFFLINE"] = "1"

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import scripts.evaluate_v211_frozen_product_baseline as bl6a  # noqa: E402
import scripts.evaluate_v211_frozen_product_contract as cbl  # noqa: E402
import scripts.evaluate_v211_frozen_product_contract_hardened as hbl  # noqa: E402

# ── 目录常量 ──────────────────────────────────────────────────────────
PHASE6A_DIR = cbl.PHASE6A_DIR
PHASE6B0_DIR = cbl.OUTPUT_DIR
HARDENED_DIR = hbl.HARDENED_DIR
LIFECYCLE_DIR = REPO_ROOT / (
    "evaluation/product-baselines/v2.0.11-frozen-contract-lifecycle-hardened")
COLLECTION_NAME = "v211_lifecycle_hardening_probe"

LIFECYCLE_OUTPUT_FILES = (
    "lifecycle-hardening-summary.json",
    "lifecycle-immutability-report.md",
    "data-quality-report.json",
)

BaselineDrift = cbl.BaselineDrift

_SKILL_NOTE = (
    "data-analytics:analyze-data-quality 实际检查：zcode 运行环境不可用"
    "（本次会话可用技能列表、~/.zcode/skills、~/.agents/skills、插件目录均无"
    " data-analytics）——不能声称所有环境均不可用；实施等价的确定性机械检查"
)


def verify_hardened_manifest(hardened_dir: Path) -> dict:
    """复算 Phase 6-B0.1 hardened manifest（与 C1 runner 口径一致，71 项）：
    self-hash + inputs / frozen_outputs / outputs（hbl.verify_b0_manifest）
    + hardened 特有段 phase6a_outputs（6A 产物引用，base=Phase 6-A 目录）。
    纯只读。"""
    report = hbl.verify_b0_manifest(hardened_dir)
    manifest_path = Path(hardened_dir) / "manifest.json"
    if not manifest_path.is_file():
        return report
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    for name, rec in sorted(manifest.get("phase6a_outputs", {}).items()):
        path = Path(cbl.PHASE6A_DIR) / name
        expected = rec if isinstance(rec, str) else rec.get("sha256")
        actual_sha = bl6a.sha256_bytes(path) if path.is_file() else None
        status = ("ok" if actual_sha == expected
                  else ("missing" if actual_sha is None else "mismatch"))
        check = {
            "name": f"phase6b01 phase6a_outputs/{name}",
            "kind": "phase6a_outputs", "status": status,
            "expected": expected, "actual": actual_sha, "path": str(path),
        }
        report["checks"].append(check)
        if status != "ok":
            report["drift"].append(
                {k: check[k] for k in
                 ("name", "kind", "status", "expected", "actual", "path")})
    report["verified"] = not report["drift"]
    return report


class _EncodeForbidden:
    """encode() 一旦被调用即抛错——证明拒绝路径从未触及模型编码。"""

    def encode(self, *args, **kwargs):
        raise AssertionError("model.encode called during a rejected mutation")

    def get_embedding_dimension(self):
        return 384


def _sha256_bytes(path: Path) -> str:
    return bl6a.sha256_bytes(path)


def _collection_state(collection, collection_name: str, chroma_dir: Path) -> dict:
    """collection 内容 + 全部 sidecar 的字节状态（零漂移证明）。"""
    import src.rag as rag
    manifest_path = chroma_dir / f"{collection_name}.manifest.json"
    bm25_path = chroma_dir / f"{collection_name}.bm25.json"
    kg_path = chroma_dir / f"{collection_name}_kg.json"
    return {
        "count": collection.count(),
        "ids": sorted(rag._collection_data(collection)["ids"]),
        "manifest_sha256": _sha256_bytes(manifest_path)
        if manifest_path.exists() else None,
        "bm25_sha256": _sha256_bytes(bm25_path)
        if bm25_path.exists() else None,
        "kg_sha256": _sha256_bytes(kg_path) if kg_path.exists() else None,
    }


# B0.2.4：只清理「有所有权」的 Chroma 资源。Chroma 1.5.9 的
# SharedSystemClient 按 persist 标识全局缓存 system——相对标识
# （'rel_db' / 'ephemeral'）会跨测试/调用复用错位（复用旧测试目录），
# 必须回收；但绝对路径 external client 的标识全局唯一，运行前已存在的
# 必须保持可用，绝不停 stop / 清空。以下 helper 明确记录该所有权边界。
_RELATIVE_ALIAS_IDS = ("rel_db", "ephemeral")


def _reclaim_relative_chroma_aliases() -> set[str]:
    """B0.2.4：入口只回收已知会错位复用的相对别名 system。

    只 pop + stop ``_RELATIVE_ALIAS_IDS`` 中的相对标识（存在时才处理），
    绝不动任何绝对路径 external client 的 system。返回被回收的标识集合
    （结束时这些标识若被本次验证重建，也要释放）。
    """
    import chromadb

    cache = chromadb.api.client.SharedSystemClient
    reclaimed: set[str] = set()
    for ident in _RELATIVE_ALIAS_IDS:
        system = cache._identifier_to_system.pop(ident, None)
        cache._identifier_to_refcount.pop(ident, None)
        if system is not None:
            try:
                system.stop()
            except Exception:
                pass  # 已停止 / 部分初始化的 system：忽略
            reclaimed.add(ident)
    return reclaimed


def _release_owned_chroma(pre_rag_ids: set[int], pre_system_ids: set[str],
                          reclaimed: set[str]) -> None:
    """B0.2.4：只关闭 / stop / 移除「本次验证新建或明确归属本次验证」的
    client / system（所有权边界 = 运行前快照）。

    - 运行前已存在的 ``rag._CHROMA_CLIENTS`` client 一律不 close、不移除；
    - 运行前已存在的 system 标识（绝对路径 external client）一律不 stop、
      不清空——只有本次新建的标识（cur - pre）与入口回收后重建的相对
      别名（cur ∩ reclaimed）被 pop + stop；
    - 不调用 ``rag.close_chroma_clients()``（其关闭列表中全部 client，含
      非本次验证所有）；不调用 ``SharedSystemClient.clear_system_cache()``
      （其清空全部缓存）。
    """
    import chromadb

    import src.rag as rag

    for client in list(rag._CHROMA_CLIENTS):
        if id(client) in pre_rag_ids:
            continue  # 运行前已有：保持不动
        close = getattr(client, "close", None)
        if close is not None:
            close()
        if client in rag._CHROMA_CLIENTS:
            rag._CHROMA_CLIENTS.remove(client)

    cache = chromadb.api.client.SharedSystemClient
    cur_ids = set(cache._identifier_to_system.keys())
    owned_ids = (cur_ids - pre_system_ids) | (cur_ids & reclaimed)
    for ident in owned_ids:
        system = cache._identifier_to_system.pop(ident, None)
        cache._identifier_to_refcount.pop(ident, None)
        if system is not None:
            try:
                system.stop()
            except Exception:
                pass  # 已停止的 system：忽略


def _release_scoped_chroma(pre_rag_ids: set[int],
                           pre_system_ids: set[str]) -> None:
    """B0.2.5：检查级 scoped 释放——只关闭 / stop / 移除「边界快照之后
    新建」的 client / system（供单个检查立即释放其副作用，如
    prepare_index 拒绝路径新建的同目录 Rag client）；运行前已有资源
    （含外部绝对路径 client）一律不动。"""
    _release_owned_chroma(pre_rag_ids, pre_system_ids, set())


def _stable_json(obj) -> str:
    """B0.2.4：确定性 JSON 序列化——进入持久化产物（check detail / 报告）
    的 dict 序列化必须经此函数。

    ``ensure_ascii=False + sort_keys=True``：dict 键顺序（如 collection
    .metadata 的键序，跨构建不确定）不得影响产物字节——两次独立构建的
    data-quality-report.json / lifecycle-hardening-summary.json / Markdown
    报告 / manifest.json 必须逐字节一致。
    """
    return json.dumps(obj, ensure_ascii=False, sort_keys=True)


def _verify_lifecycle(
    snapshot,
    data_dir: Path,
    collection_name: str,
) -> dict:
    """隔离临时 Chroma 中的真实生命周期实测。

    Returns:
        {"checks", "count", "source_count", "build_log_len",
         "migration_count", "parser_added", "parser_removed"}
    """
    import src.rag as rag

    chroma_dir = data_dir / "chroma_db"
    buf = io.StringIO()
    with redirect_stdout(buf):
        model, collection, bm25, docs, metas = rag.prepare_index(
            file_paths=snapshot.source_paths(),
            collection_name=collection_name,
            force_rebuild=True,
            snapshot=snapshot,
            chroma_path=str(chroma_dir),
        )

    checks: list[dict] = []

    def _check(name: str, ok: bool, detail: str = "") -> None:
        checks.append({"name": name, "ok": bool(ok), "detail": detail})
        if not ok:
            raise AssertionError(f"{name}: {detail}")

    # marker 已持久化（新建 collection 创建时写入，保留 hnsw:space）
    marker = collection.metadata.get(rag.SNAPSHOT_INDEX_MARKER_KEY)
    _check("immutability.marker_persisted",
           marker == rag.SNAPSHOT_INDEX_MARKER_VALUE,
           _stable_json(dict(collection.metadata)))
    _check("immutability.hnsw_space_preserved",
           collection.metadata.get("hnsw:space") == "cosine",
           _stable_json(dict(collection.metadata)))

    manifest_path = chroma_dir / f"{collection_name}.manifest.json"
    kg_path = chroma_dir / f"{collection_name}_kg.json"
    # 模拟既有 graph cache：先于 before 采集写入，拒绝前后字节必须不变
    kg_path.write_bytes(b"cached-graph-probe")

    before = _collection_state(collection, collection_name, chroma_dir)
    _check("conservation.chunk_count", before["count"] == len(snapshot.chunks),
           f"count={before['count']} expected={len(snapshot.chunks)}")
    _check("conservation.source_count",
           len(snapshot.sources) == len(set(snapshot.source_paths())),
           f"sources={len(snapshot.sources)}")

    first_source = snapshot.source_paths()[0]

    # 1. 四类生命周期 mutation 拒绝（encode 未调用、commit 未调用）
    try:
        rag.add_files_to_index(
            [first_source], _EncodeForbidden(), collection,
            chroma_path=str(chroma_dir))
        _check("immutability.add_files_rejected", False, "no exception")
    except rag.SnapshotIndexImmutableError as exc:
        _check("immutability.add_files_rejected", True, str(exc)[:160])

    try:
        rag.remove_file_from_index(
            first_source, collection, chroma_path=str(chroma_dir))
        _check("immutability.remove_file_rejected", False, "no exception")
    except rag.SnapshotIndexImmutableError as exc:
        _check("immutability.remove_file_rejected", True, str(exc)[:160])

    try:
        rag.sync_sources(
            snapshot.source_paths(), _EncodeForbidden(), collection,
            dry_run=False, chroma_path=str(chroma_dir))
        _check("immutability.sync_sources_rejected", False, "no exception")
    except rag.SnapshotIndexImmutableError as exc:
        _check("immutability.sync_sources_rejected", True, str(exc)[:160])

    try:
        rag.add_sources(
            [first_source], _EncodeForbidden(), collection,
            chroma_path=str(chroma_dir))
        _check("immutability.add_sources_rejected", False, "no exception")
    except rag.SnapshotIndexImmutableError as exc:
        _check("immutability.add_sources_rejected", True, str(exc)[:160])

    # 2. 只读路径保持可用且零写入
    diff = rag.compute_source_diff(
        snapshot.source_paths(), collection, chroma_path=str(chroma_dir))
    _check("readonly.compute_source_diff",
           diff["to_add"] == [] and diff["to_remove"] == []
           and len(diff["unchanged"]) == len(snapshot.sources),
           _stable_json({k: len(v) for k, v in diff.items()}))
    preview = rag.sync_sources(
        snapshot.source_paths(), _EncodeForbidden(), collection,
        dry_run=True, chroma_path=str(chroma_dir))
    _check("readonly.sync_sources_dry_run",
           preview["added"] == 0 and preview["removed"] == 0,
           _stable_json(preview))

    # 3. 错误 chroma_path 不能绕过 collection marker
    try:
        rag.remove_file_from_index(
            first_source, collection,
            chroma_path=str(data_dir / "wrong_chroma"))
        _check("fail_closed.wrong_chroma_path", False, "no exception")
    except rag.SnapshotIndexImmutableError:
        _check("fail_closed.wrong_chroma_path", True,
               "blocked via collection marker (manifest unreachable)")

    # 4. 攻击矩阵（marker 权威）：删 manifest / 坏 manifest / mismatch
    manifest_bytes = manifest_path.read_bytes()
    try:
        manifest_path.unlink()
        try:
            rag.add_files_to_index([], _EncodeForbidden(), collection,
                                   chroma_path=str(chroma_dir))
            _check("fail_closed.marker_only_no_manifest", False, "no exception")
        except rag.SnapshotIndexImmutableError:
            _check("fail_closed.marker_only_no_manifest", True,
                   "marker 存在而 manifest 缺失 → 拒绝")

        manifest_path.write_text("{not-json", encoding="utf-8")
        try:
            rag.add_files_to_index([], _EncodeForbidden(), collection,
                                   chroma_path=str(chroma_dir))
            _check("fail_closed.malformed_manifest", False, "no exception")
        except rag.SnapshotIndexImmutableError:
            _check("fail_closed.malformed_manifest", True,
                   "marker 存在而 manifest 损坏 → 拒绝")

        plain = {
            "schema_version": 1, "manifest_version": 2,
            "collection_name": collection_name,
            "config": {"embedding_model": "plain"},
            "sources": [], "indexed_chunk_ids": [],
        }
        manifest_path.write_text(
            json.dumps(plain, ensure_ascii=False), encoding="utf-8")
        try:
            rag.add_files_to_index([], _EncodeForbidden(), collection,
                                   chroma_path=str(chroma_dir))
            _check("fail_closed.marker_manifest_mismatch", False, "no exception")
        except rag.SnapshotIndexImmutableError:
            _check("fail_closed.marker_manifest_mismatch", True,
                   "marker 与 manifest 不一致 → 拒绝（不降级 parser）")
    finally:
        manifest_path.write_bytes(manifest_bytes)

    # 5. 旧 B0.1 manifest-only 形态：阻断 + 合法 rebuild 迁移 marker
    b01_name = f"{collection_name}_b01legacy"
    client = rag._new_persistent_client(str(chroma_dir))
    b01 = client.get_or_create_collection(
        name=b01_name, metadata={"hnsw:space": "cosine"})
    b01_manifest = {
        "schema_version": 1, "manifest_version": 1,
        "collection_name": b01_name,
        "config": {
            "embedding_model": rag.EMBEDDING_MODEL_NAME,
            "normalize": False,
            "chunking": rag.CHUNKING_CONFIG,
            "snapshot": snapshot.config(),
        },
        "sources": [], "indexed_chunk_ids": [],
    }
    (chroma_dir / f"{b01_name}.manifest.json").write_text(
        json.dumps(b01_manifest, ensure_ascii=False, indent=2, sort_keys=True)
        + "\n", encoding="utf-8")
    try:
        rag.add_files_to_index([], _EncodeForbidden(), b01,
                               chroma_path=str(chroma_dir))
        _check("migration.b01_manifest_only_blocked", False, "no exception")
    except rag.SnapshotIndexImmutableError:
        _check("migration.b01_manifest_only_blocked", True,
               "无 marker、manifest config.snapshot 存在 → 拒绝")

    # B0.2.1：旧 B0.1 manifest-only collection 不能被错误 / None chroma_path
    # 绕过（guard 使用 collection 自身实际持久化目录，绝不信任调用方路径）
    try:
        rag.remove_file_from_index(
            first_source, b01, chroma_path=str(data_dir / "wrong_chroma_b01"))
        _check("b021.b01_wrong_chroma_path_blocked", False, "no exception")
    except rag.SnapshotIndexImmutableError:
        _check("b021.b01_wrong_chroma_path_blocked", True,
               "guard 使用 collection 实际持久化目录（错误路径不可绕过）")
    old_default = rag.CHROMA_DB_PATH
    rag.CHROMA_DB_PATH = str(data_dir / "default_db_b01")
    try:
        try:
            rag.remove_file_from_index(first_source, b01)
            _check("b021.b01_none_chroma_path_blocked", False, "no exception")
        except rag.SnapshotIndexImmutableError:
            _check("b021.b01_none_chroma_path_blocked", True,
                   "chroma_path=None（默认目录）同样不能绕过")
    finally:
        rag.CHROMA_DB_PATH = old_default
    _check("b021.b01_none_path_left_no_residue",
           not (data_dir / "default_db_b01").exists()
           or list((data_dir / "default_db_b01").iterdir()) == [],
           "None 路径拒绝后默认目录零文件")

    # B0.2.1：默认 parser 重建（snapshot=None）不得覆盖 snapshot collection
    try:
        with redirect_stdout(io.StringIO()):
            rag.prepare_index(
                file_paths=snapshot.source_paths(),
                collection_name=collection_name,
                force_rebuild=True,
                chroma_path=str(chroma_dir))
        _check("b021.parser_rebuild_marker_collection_rejected", False,
               "no exception")
    except rag.SnapshotIndexImmutableError:
        _check("b021.parser_rebuild_marker_collection_rejected", True,
               "marker collection 拒绝默认 parser 重建（零写入）")
    try:
        with redirect_stdout(io.StringIO()):
            rag.prepare_index(
                file_paths=snapshot.source_paths(),
                collection_name=b01_name,
                force_rebuild=True,
                chroma_path=str(chroma_dir))
        _check("b021.parser_rebuild_b01_manifest_only_rejected", False,
               "no exception")
    except rag.SnapshotIndexImmutableError:
        _check("b021.parser_rebuild_b01_manifest_only_rejected", True,
               "旧 B0.1 manifest-only collection 拒绝默认 parser 重建")
    try:
        with redirect_stdout(io.StringIO()):
            rag.build_index(
                snapshot.source_paths(), collection_name, force_rebuild=True,
                chroma_path=str(chroma_dir))
        _check("b021.build_index_parser_rebuild_rejected", False,
               "no exception")
    except rag.SnapshotIndexImmutableError:
        _check("b021.build_index_parser_rebuild_rejected", True,
               "直接 build_index(snapshot=None) 同样拒绝")

    # 合法显式 rebuild → 迁移写入 marker，内容精确重建，检索仍可用
    with redirect_stdout(io.StringIO()):
        _, b01_rebuilt, _, _, _ = rag.prepare_index(
            file_paths=snapshot.source_paths(),
            collection_name=b01_name,
            force_rebuild=True,
            snapshot=snapshot,
            chroma_path=str(chroma_dir),
        )
    _check("migration.marker_written_by_rebuild",
           b01_rebuilt.metadata.get(rag.SNAPSHOT_INDEX_MARKER_KEY)
           == rag.SNAPSHOT_INDEX_MARKER_VALUE,
           _stable_json(dict(b01_rebuilt.metadata)))
    _check("migration.rebuilt_content_exact",
           b01_rebuilt.count() == len(snapshot.chunks),
           f"count={b01_rebuilt.count()} expected={len(snapshot.chunks)}")
    _check("migration.retrieval_still_works",
           len(b01_rebuilt.query(
               query_embeddings=[[0.0] * 384], n_results=1)["ids"][0]) == 1,
           "cosine 检索在迁移后仍可用")
    try:
        rag.remove_file_from_index(
            first_source, b01_rebuilt, chroma_path=str(chroma_dir))
        _check("migration.blocked_via_marker_after_rebuild", False,
               "no exception")
    except rag.SnapshotIndexImmutableError:
        _check("migration.blocked_via_marker_after_rebuild", True,
               "rebuild 后经 marker 路径拒绝")

    # 6. 普通 parser 索引生命周期语义不变
    parser_name = f"{collection_name}_parser"
    probe_a = data_dir / "probe-a.md"
    probe_b = data_dir / "probe-b.md"
    probe_a.write_text("Probe A: lifecycle regression source one.",
                       encoding="utf-8")
    probe_b.write_text("Probe B: lifecycle regression source two.",
                       encoding="utf-8")
    with redirect_stdout(io.StringIO()):
        _, parser_collection, _, _, _ = rag.prepare_index(
            file_paths=[str(probe_a)],
            collection_name=parser_name,
            force_rebuild=True,
            chroma_path=str(chroma_dir),
        )
    _check("legacy.parser_no_marker",
           parser_collection.metadata.get(rag.SNAPSHOT_INDEX_MARKER_KEY)
           is None, "parser collection 无 marker")
    parser_count0 = parser_collection.count()
    with redirect_stdout(io.StringIO()):
        rag.add_files_to_index(
            [str(probe_b)], model, parser_collection,
            chroma_path=str(chroma_dir))
    _check("legacy.parser_add_works",
           parser_collection.count() > parser_count0,
           f"{parser_count0} -> {parser_collection.count()}")
    with redirect_stdout(io.StringIO()):
        removed = rag.remove_file_from_index(
            str(probe_b), parser_collection, chroma_path=str(chroma_dir))
    _check("legacy.parser_remove_works",
           removed > 0 and parser_collection.count() == parser_count0,
           f"removed={removed}")

    # B0.2.1：普通 parser collection 的默认 rebuild 不受影响（复用正常）；
    # 错误 chroma_path 的 parser rebuild 只作用于错误目录（真实目录零漂移）
    parser_before = _collection_state(parser_collection, parser_name,
                                      chroma_dir)
    with redirect_stdout(io.StringIO()):
        _, parser_reused, _, _, _ = rag.prepare_index(
            file_paths=[str(probe_a)],
            collection_name=parser_name,
            force_rebuild=False,
            chroma_path=str(chroma_dir),
        )
    _check("b021.parser_reuse_still_works",
           parser_reused.metadata.get(rag.SNAPSHOT_INDEX_MARKER_KEY) is None,
           "普通 parser collection 的 prepare_index(snapshot=None) 复用正常")
    wrong_build_dir = data_dir / "wrong_rebuild_chroma"
    with redirect_stdout(io.StringIO()):
        rag.build_index(
            [str(probe_a)], parser_name, force_rebuild=True,
            chroma_path=str(wrong_build_dir))
    wrong_client = rag._new_persistent_client(str(wrong_build_dir))
    wrong_col = wrong_client.get_collection(parser_name)
    _check("b021.wrong_path_rebuild_touches_only_wrong_dir",
           wrong_col.metadata.get(rag.SNAPSHOT_INDEX_MARKER_KEY) is None,
           "错误目录产出的是普通 parser collection（无 marker）")
    _check("b021.wrong_path_rebuild_preserves_real_collection",
           _collection_state(parser_collection, parser_name, chroma_dir)
           == parser_before,
           "错误路径 rebuild 不触碰真实目录 collection/sidecar")

    # B0.2.2：persist-directory 身份绕过关闭（审计缺陷 1/2 的修复实测）
    import chromadb as _chromadb

    def _close_client(client) -> None:
        """关闭本段直接创建的外部 Chroma client（不注册进 rag 的
        _CHROMA_CLIENTS，必须显式关闭以释放 sqlite 文件锁，保证临时目录
        cleaned）。"""
        close = getattr(client, "close", None)
        if close is not None:
            close()

    # (a) EphemeralClient：is_persistent=False、persist_directory='./chroma'
    #     残留串——四类 mutation + build_index 默认 parser 重建 fail-closed
    ep_client = _chromadb.EphemeralClient()
    ep = ep_client.get_or_create_collection(
        name=f"{collection_name}_ephemeral",
        metadata={"hnsw:space": "cosine"})
    ep.add(ids=[f"{ep.name}-0"], documents=["ephemeral probe"],
           metadatas=[{"source_id": "ep-probe",
                       "source_path": first_source}],
           embeddings=[[0.1] * 384])
    ep_sidecar = data_dir / "ephemeral_sidecar"
    ep_sidecar.mkdir(parents=True, exist_ok=True)
    (ep_sidecar / f"{ep.name}.manifest.json").write_text(
        json.dumps({
            "schema_version": 1, "manifest_version": 1,
            "collection_name": ep.name,
            "config": {"embedding_model": rag.EMBEDDING_MODEL_NAME,
                       "chunking": rag.CHUNKING_CONFIG,
                       "snapshot": snapshot.config()},
            "sources": [], "indexed_chunk_ids": [],
        }, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8")
    _check("b022.ephemeral_settings_observed",
           ep._client._system.settings.is_persistent is False
           and ep._client._system.settings.persist_directory == "./chroma",
           "EphemeralClient 实测特征：非持久化 + 残留相对串")
    ep_ids_before = sorted(rag._collection_data(ep)["ids"])
    for api in ("add", "remove", "sync", "add_sources"):
        try:
            if api == "add":
                rag.add_files_to_index([first_source], _EncodeForbidden(), ep,
                                       chroma_path=str(ep_sidecar))
            elif api == "remove":
                rag.remove_file_from_index(first_source, ep,
                                           chroma_path=str(ep_sidecar))
            elif api == "sync":
                rag.sync_sources([], _EncodeForbidden(), ep, dry_run=False,
                                 chroma_path=str(ep_sidecar))
            else:
                rag.add_sources([], _EncodeForbidden(), ep,
                                chroma_path=str(ep_sidecar))
            _check(f"b022.ephemeral_{api}_rejected", False, "no exception")
        except rag.SnapshotIndexImmutableError as exc:
            _check(f"b022.ephemeral_{api}_rejected", True, str(exc)[:140])
    try:
        with redirect_stdout(io.StringIO()):
            rag.build_index(snapshot.source_paths(), ep.name,
                            force_rebuild=True, client=ep_client,
                            chroma_path=str(ep_sidecar))
        _check("b022.ephemeral_parser_rebuild_rejected", False, "no exception")
    except rag.SnapshotIndexImmutableError as exc:
        _check("b022.ephemeral_parser_rebuild_rejected", True, str(exc)[:140])
    _check("b022.ephemeral_zero_drift",
           sorted(rag._collection_data(ep)["ids"]) == ep_ids_before,
           "EphemeralClient collection 零漂移")
    _close_client(ep_client)

    # (b) 外部相对路径 PersistentClient + CWD 切换：fail-closed，零残留；
    # (c) Mneme 自建相对 client：创建时绝对化，CWD 切换后仍正确阻断
    old_cwd = os.getcwd()
    cwd_a = data_dir / "cwd_a"
    cwd_b = data_dir / "cwd_b"
    cwd_a.mkdir(parents=True, exist_ok=True)
    cwd_b.mkdir(parents=True, exist_ok=True)
    b022_rel_clients: list = []
    try:
        os.chdir(str(cwd_a))
        rel_client = _chromadb.PersistentClient(path="rel_db")
        b022_rel_clients.append(rel_client)
        rel = rel_client.get_or_create_collection(
            name=f"{collection_name}_rel", metadata={"hnsw:space": "cosine"})
        rel.add(ids=[f"{rel.name}-0"], documents=["relative probe"],
                metadatas=[{"source_id": "rel-probe",
                            "source_path": first_source}],
                embeddings=[[0.1] * 384])
        (cwd_a / "rel_db").mkdir(parents=True, exist_ok=True)
        (cwd_a / "rel_db" / f"{rel.name}.manifest.json").write_text(
            json.dumps({
                "schema_version": 1, "manifest_version": 1,
                "collection_name": rel.name,
                "config": {"embedding_model": rag.EMBEDDING_MODEL_NAME,
                           "chunking": rag.CHUNKING_CONFIG,
                           "snapshot": snapshot.config()},
                "sources": [], "indexed_chunk_ids": [],
            }, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8")
        # B0.2.5：rel 的 system 只记录相对 persist 路径（sqlite URL 是
        # 相对串，连接一旦重开即按当前 CWD 解析，跨进程顺序下曾在 cwd_b
        # 读 rel 时抛 InternalError: unable to open database file）——
        # 真实 collection 的读取（before 与零漂移复读）只在 cwd_a 完成；
        # cwd_b 内只做 guard 在任何 collection 读取之前就拒绝的
        # fail-closed 检查（mutation / prepare_index / build_index）。
        rel_ids_before = sorted(rag._collection_data(rel)["ids"])
        os.chdir(str(cwd_b))
        _check("b022.external_relative_stays_relative",
               rel._client._system.settings.persist_directory == "rel_db",
               "外部相对 client 只记录相对串（创建时 CWD 已不可知）")
        _check("b022.relative_no_residue_in_new_cwd",
               not (cwd_b / "rel_db").exists(),
               "新 CWD 不产生任何残留")
        for api in ("add", "remove", "sync", "add_sources"):
            try:
                if api == "add":
                    rag.add_files_to_index(
                        [first_source], _EncodeForbidden(), rel,
                        chroma_path=str(cwd_a / "rel_db"))
                elif api == "remove":
                    rag.remove_file_from_index(
                        first_source, rel, chroma_path=str(cwd_a / "rel_db"))
                elif api == "sync":
                    rag.sync_sources([], _EncodeForbidden(), rel,
                                     dry_run=False,
                                     chroma_path=str(cwd_a / "rel_db"))
                else:
                    rag.add_sources([], _EncodeForbidden(), rel,
                                    chroma_path=str(cwd_a / "rel_db"))
                _check(f"b022.relative_{api}_fail_closed", False,
                       "no exception")
            except rag.SnapshotIndexImmutableError as exc:
                _check(f"b022.relative_{api}_fail_closed", True,
                       str(exc)[:140])
        try:
            rag.remove_file_from_index(first_source, rel)
            _check("b022.relative_none_path_fail_closed", False, "no exception")
        except rag.SnapshotIndexImmutableError as exc:
            _check("b022.relative_none_path_fail_closed", True, str(exc)[:140])
        # B0.2.5：prepare_index 拒绝路径仍会新建/注册同物理目录
        # （<cwd_a>/rel_db）的绝对路径 Rag client（src/rag.py 保持不动）——
        # 检查前记录所有权边界，检查后立即只释放本检查新建的
        # client/system，不让两个 system 同时持有同一 sqlite 文件直至
        # 验证结束；rel_client 与运行前已有资源一律不动。
        pre_check_rag_ids = {id(c) for c in rag._CHROMA_CLIENTS}
        pre_check_system_ids = set(
            _chromadb.api.client.SharedSystemClient
            ._identifier_to_system.keys())
        try:
            with redirect_stdout(io.StringIO()):
                rag.prepare_index(snapshot.source_paths(), rel.name,
                                  force_rebuild=True,
                                  chroma_path=str(cwd_a / "rel_db"))
            _check("b022.relative_prepare_parser_rebuild_rejected", False,
                   "no exception")
        except rag.SnapshotIndexImmutableError:
            # detail 不含路径（异常消息嵌入真实持久化目录，两次构建必须
            # 逐字节一致）
            _check("b022.relative_prepare_parser_rebuild_rejected", True,
                   "prepare_index(snapshot=None) 拒绝（真实目录 manifest "
                   "config.snapshot）")
        finally:
            _release_scoped_chroma(pre_check_rag_ids, pre_check_system_ids)
        try:
            with redirect_stdout(io.StringIO()):
                rag.build_index(snapshot.source_paths(), rel.name,
                                force_rebuild=True, client=rel_client,
                                chroma_path=str(cwd_a / "rel_db"))
            _check("b022.relative_build_parser_rebuild_rejected", False,
                   "no exception")
        except rag.SnapshotIndexImmutableError as exc:
            _check("b022.relative_build_parser_rebuild_rejected", True,
                   str(exc)[:140])
        # B0.2.5：真实 collection 零漂移只在临时切回 cwd_a 后复读
        os.chdir(str(cwd_a))
        _check("b022.relative_zero_drift",
               sorted(rag._collection_data(rel)["ids"]) == rel_ids_before,
               "相对 client collection 零漂移")
        mn_client = rag._new_persistent_client("rel_mneme_db")
        b022_rel_clients.append(mn_client)
        mn = mn_client.get_or_create_collection(
            name=f"{collection_name}_relmneme",
            metadata={"hnsw:space": "cosine"})
        stored = mn._client._system.settings.persist_directory
        _check("b022.mneme_relative_stores_absolute",
               isinstance(stored, str) and os.path.isabs(stored)
               and os.path.realpath(stored)
               == os.path.realpath(str(cwd_a / "rel_mneme_db")),
               f"isabs={os.path.isabs(stored)}")
        mn.add(ids=[f"{mn.name}-0"], documents=["mneme relative probe"],
               metadatas=[{"source_id": "mn-rel-probe",
                           "source_path": first_source}],
               embeddings=[[0.1] * 384])
        (cwd_a / "rel_mneme_db" / f"{mn.name}.manifest.json").write_text(
            json.dumps({
                "schema_version": 1, "manifest_version": 1,
                "collection_name": mn.name,
                "config": {"embedding_model": rag.EMBEDDING_MODEL_NAME,
                           "chunking": rag.CHUNKING_CONFIG,
                           "snapshot": snapshot.config()},
                "sources": [], "indexed_chunk_ids": [],
            }, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8")
        os.chdir(str(cwd_b))
        try:
            rag.remove_file_from_index(first_source, mn)
            _check("b022.mneme_relative_blocks_after_cwd_switch", False,
                   "no exception")
        except rag.SnapshotIndexImmutableError:
            # detail 不含路径（异常消息嵌入真实持久化目录，两次构建必须
            # 逐字节一致）
            _check("b022.mneme_relative_blocks_after_cwd_switch", True,
                   "manifest 分支识别（绝对 persist 目录），CWD 切换后仍阻断")
    finally:
        for _client in b022_rel_clients:
            _close_client(_client)
        os.chdir(old_cwd)

    # (d) 外部绝对路径 PersistentClient：普通 parser / legacy 生命周期不变
    ext_abs = data_dir / "ext_abs_db"
    ext_client = _chromadb.PersistentClient(path=str(ext_abs))
    ext = ext_client.get_or_create_collection(
        name=f"{collection_name}_extabs", metadata={"hnsw:space": "cosine"})
    ext.add(ids=[f"{ext.name}-0"], documents=["external absolute probe"],
            metadatas=[{"source_id": "ext-probe",
                        "source_path": rag.canonical_source_path(
                            str(probe_a))}],
            embeddings=[[0.1] * 384])
    try:
        removed = rag.remove_file_from_index(
            str(probe_a), ext, chroma_path=str(ext_abs))
        _check("b022.external_absolute_lifecycle_works",
               removed == 1 and ext.count() == 0, f"removed={removed}")
    except rag.SnapshotIndexImmutableError as exc:
        _check("b022.external_absolute_lifecycle_works", False,
               f"unexpected rejection: {exc}")
    _close_client(ext_client)

    # 7. 攻击后零漂移（主 collection 内容 + sidecar 字节 + graph cache）
    after = _collection_state(collection, collection_name, chroma_dir)
    _check("integrity.zero_drift_after_attacks", after == before,
           _stable_json({"before": before, "after": after}))
    _check("integrity.graph_cache_untouched",
           kg_path.read_bytes() == b"cached-graph-probe",
           "graph cache 字节未变")

    return {
        "checks": checks,
        "passed_count": sum(1 for c in checks if c["ok"]),
        "count": before["count"],
        "source_count": len(snapshot.sources),
        "build_log_len": len(buf.getvalue()),
        "marker": {
            "key": rag.SNAPSHOT_INDEX_MARKER_KEY,
            "value": rag.SNAPSHOT_INDEX_MARKER_VALUE,
        },
    }


# ── 产物 ──────────────────────────────────────────────────────────────

def _data_quality_report(
    lifecycle: dict,
    reports: dict,
) -> dict:
    """确定性机械检查（data-analytics skill 不可用 → 等价复算）。

    checks 全部来自本脚本的实测与复算结果；errors 非空 → passed=False。
    （manifest 的 outputs 字节闭环由测试与 manifest self-hash 验证。）
    """
    errors: list[str] = []
    warnings: list[str] = []
    checks: list[dict] = []

    def _check(name: str, ok: bool, detail: str = "") -> None:
        checks.append({"name": name, "ok": bool(ok), "detail": detail})
        if not ok:
            errors.append(f"{name}: {detail}")

    for label, report in reports.items():
        _check(f"lineage.{label}_verified", report["verified"],
               f"{len(report['checks'])} checks, {len(report['drift'])} drift")
    for c in lifecycle["checks"]:
        _check(f"lifecycle.{c['name']}", c["ok"], c["detail"])

    return {
        "passed": not errors,
        "error_count": len(errors),
        "errors": errors,
        "warning_count": len(warnings),
        "warnings": warnings,
        "checks": checks,
        "note": _SKILL_NOTE,
        "scope": "Phase 6-B0.2 lifecycle hardening verification "
                 "(integrity/uniqueness/referential-lineage/consistency/"
                 "invariants, mechanical)",
    }


def _render_report(lifecycle: dict, reports: dict, hardened_sha: str) -> str:
    lines = [
        "# Lifecycle Immutability Report — Phase 6-B0.2",
        "",
        "## 范围",
        "",
        "- 只读验证：snapshot 索引可读取、可由同一有效 snapshot 显式重建，"
        "但生命周期 API 不得直接增删改。",
        "- 不修改任何冻结 / 6-A / B0 / B0.1 / C1 / C1.1 产物；无 LLM / 生成 "
        "/ 联网 / 检索策略实验；不持久化任何 Chroma 数据（临时目录，"
        "cleaned）。",
        "",
        "## Guard 覆盖的 API",
        "",
        "- `add_files_to_index` / `remove_file_from_index` / "
        "`sync_sources(dry_run=False)` / `add_sources`：入口 fail-closed "
        "拒绝（先于任何解析 / model.encode / collection 读写 / commit / "
        "sidecar 写入）；`add_sources` 不能成为绕过 `add_files_to_index` "
        "的旁路。",
        "- `prepare_index(snapshot=None)` / `build_index(snapshot=None)` "
        "（B0.2.1）：既有 snapshot collection 拒绝默认 parser 重建（先于 "
        "model 加载 / get_or_create / parser 解析 / collection mutation）；"
        "新 collection 的普通 parser 路径不受影响。",
        "- 只读路径保持可用：`compute_source_diff`、"
        "`sync_sources(dry_run=True)`。",
        "- 正常重建语义不变：`prepare_index(snapshot=...)` / "
        "`build_index(snapshot=...)` 仍是唯一合法更新路径。",
        "",
        "## 识别机制（不依赖调用方传参）",
        "",
        "- collection 级 immutable marker：`mneme.snapshot_index=immutable`"
        "（Chroma collection metadata，sqlite 持久化；新建 build 创建时写入"
        "并保留 `hnsw:space` 与既有 metadata）。",
        "- 旧 Phase 6-B0.1 collection（manifest `config.snapshot` 存在、尚无"
        " marker）同样被阻断；合法 snapshot rebuild 自动迁移写入 marker。",
        "- B0.2.1：旧 B0.1 manifest-only 判定使用 collection **自身实际**"
        "持久化目录（特征检测 `collection._client._system.settings."
        "persist_directory`，Chroma 1.5.9 实测可用），绝不信任调用方传入 "
        "的 `chroma_path`——错误路径与 `None` 均不可绕过；无法推导真实 "
        "位置（非本地 PersistentClient）时 fail-closed 保守拒绝，绝不把"
        "「不确定」降级为「可修改」。",
        "- B0.2.2：persist-directory 身份收紧——只接受 `is_persistent=True`"
        " 的真实持久化 client 且 persist_directory 为稳定绝对路径；"
        "EphemeralClient（is_persistent=False、残留 './chroma'）、remote、"
        "测试 double、缺失链路、仅剩未经记录的相对 persist path（创建时 "
        "CWD 已不可知）一律不可验证 → fail-closed 拒绝，绝不把「不确定」"
        "降级为「可修改」，也绝不用调用方 chroma_path 顶替真实位置；"
        "Mneme 自建 client 创建时 realpath(abspath(...)) 规范化保存绝对"
        "真实位置，CWD 切换后仍正确阻断；外部绝对路径 PersistentClient "
        "的普通 parser / legacy 生命周期不受影响。",
        "- marker 存在而 manifest/BM25 sidecar 缺失、损坏或与 marker 不一致"
        "时保守拒绝，绝不降级为普通 parser collection；调用方提供错误 "
        "`chroma_path` 不能绕过 marker。",
        "- 普通 parser / legacy 索引无 marker 且无 snapshot manifest → "
        "add/remove/sync/add_sources 与默认 rebuild 行为不变。",
        "",
        "## 实测结果（隔离临时 Chroma）",
        "",
        f"- snapshot：{lifecycle['count']} chunks / {lifecycle['source_count']} "
        "sources（真实冻结数据运行时为 1006 / 13）。",
        f"- 机械检查：{sum(1 for c in lifecycle['checks'] if c['ok'])}/"
        f"{len(lifecycle['checks'])} 项通过（明细见 summary 与 "
        "data-quality-report.json）。",
        "",
        "## 前置复算（fail-closed，任一漂移 → 零产物）",
        "",
    ]
    for label, report in reports.items():
        lines.append(
            f"- {label}：{len(report['checks'])} checks，"
            f"{len(report['drift'])} drift，verified={report['verified']}。")
    lines += [
        "",
        "## Chroma 1.5.9 行为记录（实测确认）",
        "",
        "- `collection.modify(metadata=...)` 整体替换 metadata，且 metadata "
        "携带 `hnsw:space` 键即抛 ValueError（不支持修改距离函数）——旧 "
        "B0.1 迁移写入 marker 时显式排除 `hnsw:space` 键；实测抹除 metadata "
        "dict 中的 `hnsw:space` 不影响检索（HNSW 空间配置存于 collection "
        "配置而非 metadata dict）。",
        "- 新建 snapshot collection 创建时即持久化 marker，`hnsw:space` 与 "
        "既有 metadata 完整保留。",
        "",
        "## 明确不是",
        "",
        "- 本产物不是 active、release 或人工批准；v2.0.11 仍是只读 "
        "CANDIDATE（activation_blocked=true、human_reviewed=false）。",
        "- 未运行 LLM / 生成模型 / LLM judge / 联网 API / query rewriting；"
        "无 overlay / active / split / locked / v2.1 产物。",
        "- lineage 闭环：hardened manifest self-hash = "
        f"`{hardened_sha}`。",
        "",
    ]
    return "\n".join(lines)


def _write_artifacts(
    out_dir: Path,
    *,
    lifecycle: dict,
    reports: dict,
    hardened_manifest: dict,
    cleaned: bool,
    declarations: dict,
) -> dict:
    """写出四个产物并构建 manifest（self-hash 约定 + inputs/outputs SHA）。"""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    summary = {
        "scope": "Phase 6-B0.2 / B0.2.1 / B0.2.2 frozen contract lifecycle "
                 "hardening (read-only verification)",
        "frozen_revision": "v2.0.11-owner-authorized-en048-same-source-repair",
        "frozen_revision_status": "CANDIDATE",
        "activation_blocked": True,
        "human_reviewed": False,
        "guarded_apis": [
            "add_files_to_index",
            "remove_file_from_index",
            "sync_sources(dry_run=False)",
            "add_sources",
            "prepare_index(snapshot=None) on existing snapshot collection "
            "(B0.2.1 parser-rebuild rejection)",
            "build_index(snapshot=None) on existing snapshot collection "
            "(B0.2.1 parser-rebuild rejection)",
        ],
        "readonly_apis": ["compute_source_diff", "sync_sources(dry_run=True)"],
        "rebuild_paths": [
            "prepare_index(snapshot=...)",
            "build_index(snapshot=...)",
        ],
        "immutability": {
            "marker": lifecycle["marker"],
            "mechanism": "collection 级 immutable marker（Chroma collection "
                         "metadata，sqlite 持久化）为权威信号；旧 B0.1 "
                         "manifest-only 形态经 manifest config.snapshot 阻断，"
                         "合法 rebuild 自动迁移写入 marker；marker 存在而 "
                         "sidecar 缺失/损坏/不一致 → 保守拒绝，绝不降级 "
                         "parser；B0.2.1：manifest-only 判定使用 collection "
                         "实际持久化目录（特征检测 persist_directory），"
                         "错误/None chroma_path 不可绕过，位置不可推导时 "
                         "fail-closed 拒绝；既有 snapshot collection 拒绝 "
                         "默认 parser 重建（snapshot=... 显式 rebuild 是唯一 "
                         "更新路径）；B0.2.2：persist 身份只接受 "
                         "is_persistent=True 且为稳定绝对路径的真实持久化 "
                         "client——EphemeralClient / remote / 测试 double / "
                         "仅剩相对 persist path 一律不可验证 → fail-closed；"
                         "Mneme 自建 client 创建时 realpath(abspath(...)) "
                         "规范化；外部绝对路径 client 生命周期不受影响",
            "checked_count": len(lifecycle["checks"]),
            "passed_count": sum(1 for c in lifecycle["checks"] if c["ok"]),
        },
        "verification": {
            label: {
                "verified": report["verified"],
                "checks": len(report["checks"]),
                "drift": len(report["drift"]),
            }
            for label, report in reports.items()
        },
        "cleaned": cleaned,
        "not_measured": {
            "note": "本阶段不重跑检索/评测指标；只验证生命周期不可变性与"
                    "只读路径。answer quality / citation faithfulness / "
                    "refusal accuracy 沿用既有 not_measured 声明",
        },
        "declarations": declarations,
    }
    summary_path = out_dir / "lifecycle-hardening-summary.json"
    summary_path.write_text(bl6a.canonical_json(summary), encoding="utf-8")

    hardened_sha = hardened_manifest.get("manifest_sha256", "")
    md = _render_report(lifecycle, reports, hardened_sha)
    (out_dir / "lifecycle-immutability-report.md").write_text(
        md, encoding="utf-8")

    # dq 先写（其检查只引用复算结果，不依赖 manifest）；manifest 最后写，
    # outputs SHA 从已落盘文件计算（与 bl6a.write_artifacts 顺序一致）
    dq = _data_quality_report(lifecycle, reports)
    (out_dir / "data-quality-report.json").write_text(
        bl6a.canonical_json(dq), encoding="utf-8")

    manifest = {
        "task": "v2.0.11-frozen-contract-lifecycle-hardening "
                "(Phase 6-B0.2 / B0.2.1 / B0.2.2)",
        "scope": "read-only lifecycle immutability verification; snapshot "
                 "index readable + rebuildable via verified snapshot, never "
                 "mutated through lifecycle APIs; B0.2.1: manifest-only "
                 "snapshot detection uses the collection's real persist dir "
                 "(caller chroma_path not trusted) and default parser "
                 "rebuild of an existing snapshot collection is rejected; "
                 "B0.2.2: persist identity requires is_persistent=True and "
                 "a stable absolute persist_directory (ephemeral / relative "
                 "/ opaque clients fail closed); Mneme-created clients "
                 "normalize their directory at creation time",
        "inputs": {
            name: {"path": str(Path(rec["path"]).resolve()),
                   "sha256": rec["sha256"]}
            for name, rec in hardened_manifest.get("inputs", {}).items()
            if not name.startswith("source:") and rec.get("path")
        },
        "frozen_manifest_shas": {
            "freeze": bl6a.self_hash_of_file(
                reports["frozen"]["manifest_path"]),
            "candidate": bl6a.self_hash_of_file(
                reports["frozen"]["candidate_manifest_path"]),
            "targeted": bl6a.self_hash_of_file(
                reports["frozen"]["targeted_manifest_path"]),
            "phase6a": bl6a.self_hash_of_file(reports["phase6a"]["manifest_path"]),
            "phase6b0": bl6a.self_hash_of_file(reports["phase6b0"]["manifest_path"]),
            "phase6b01_hardened": hardened_sha,
        },
        "lineage": {
            "phase6b01_hardened_manifest_sha256": hardened_sha,
            "phase6b0_manifest_sha256": bl6a.self_hash_of_file(
                reports["phase6b0"]["manifest_path"]),
            "phase6a_manifest_sha256": bl6a.self_hash_of_file(
                reports["phase6a"]["manifest_path"]),
            "note": "输入闭环到 Phase 6-B0.1 hardened manifest 与其已验证 "
                    "lineage（frozen 61 / 6A 50 / B0 64 / hardened 71 项"
                    "复算）；任一漂移 → 本阶段零产物",
        },
        "verification": {
            label: {
                "verified": report["verified"],
                "checks": len(report["checks"]),
                "drift": len(report["drift"]),
            }
            for label, report in reports.items()
        },
        "outputs": {
            name: bl6a.sha256_bytes(out_dir / name)
            for name in LIFECYCLE_OUTPUT_FILES
        },
        "declarations": declarations,
        "code": bl6a._git_head(),
        "dependencies": bl6a._dependencies(),
    }
    manifest["manifest_sha256"] = bl6a.self_hash(manifest)
    (out_dir / "manifest.json").write_text(
        bl6a.canonical_json(manifest), encoding="utf-8")

    return manifest


# ── 主流程 ────────────────────────────────────────────────────────────

def run_lifecycle_verification(
    *,
    revision_dir: Path,
    chunks_path: Path,
    chunk_manifest_path: Path,
    current_draft_path: Path,
    corpus_manifest_path: Path,
    phase6a_dir: Path,
    phase6b0_dir: Path,
    hardened_dir: Path,
    out_dir: Path,
    data_dir: Path | None = None,
    repo_root: Path | None = None,
    collection_name: str = COLLECTION_NAME,
) -> dict:
    """执行只读 lifecycle 硬化验证并写出全部产物。

    顺序（任一漂移 → BaselineDrift，零产物）：
    1. 冻结输入复算；2. 6A manifest 复算；3. 旧 B0 manifest 复算；
    4. hardened manifest 复算；5. 真实临时实测；6. 产物 + manifest。
    """
    repo_root = Path(repo_root or REPO_ROOT)
    out_dir = Path(out_dir)
    bl6a._check_output_containment(out_dir, [
        Path(revision_dir), Path(chunks_path).parent,
        Path(current_draft_path).parent, Path(corpus_manifest_path).parent,
        Path(phase6a_dir), Path(phase6b0_dir), Path(hardened_dir),
        REPO_ROOT / "evaluation/datasets/v2", REPO_ROOT / "data/v2-corpus",
    ])

    frozen_report = bl6a.verify_frozen_inputs(
        revision_dir=revision_dir, chunks_path=chunks_path,
        chunk_manifest_path=chunk_manifest_path,
        current_draft_path=current_draft_path,
    )
    if not frozen_report["verified"]:
        raise BaselineDrift("frozen input drift: " + json.dumps(
            frozen_report["drift"], ensure_ascii=False))
    phase6a_report = cbl.verify_phase6a_manifest(phase6a_dir)
    if not phase6a_report["verified"]:
        raise BaselineDrift("phase6a baseline manifest drift: " + json.dumps(
            phase6a_report["drift"], ensure_ascii=False))
    b0_report = hbl.verify_b0_manifest(phase6b0_dir)
    if not b0_report["verified"]:
        raise BaselineDrift("phase6b0 baseline manifest drift: " + json.dumps(
            b0_report["drift"], ensure_ascii=False))
    hardened_report = verify_hardened_manifest(hardened_dir)
    if not hardened_report["verified"]:
        raise BaselineDrift("phase6b01 hardened manifest drift: " + json.dumps(
            hardened_report["drift"], ensure_ascii=False))

    snapshot = cbl.load_contract_snapshot(
        chunks_path=chunks_path,
        chunk_manifest_path=chunk_manifest_path,
        corpus_manifest_path=corpus_manifest_path,
        repo_root=repo_root,
    )

    import src.rag as rag

    own_data_dir = data_dir is None
    data_dir = Path(data_dir) if data_dir is not None else Path(
        tempfile.mkdtemp(prefix="mneme-v211-lifecycle-"))
    data_dir.mkdir(parents=True, exist_ok=True)

    cleaned = False
    # B0.2.4 所有权边界：入口只回收相对别名（rel_db / ephemeral，防复用
    # 错位），运行前快照已有 client / system；结束只释放本次新建资源——
    # 运行前已存在的绝对路径 external client 保持可用
    import chromadb as _chromadb_api

    pre_rag_ids = {id(c) for c in rag._CHROMA_CLIENTS}
    pre_system_ids = set(
        _chromadb_api.api.client.SharedSystemClient
        ._identifier_to_system.keys())
    reclaimed = _reclaim_relative_chroma_aliases()
    try:
        lifecycle = _verify_lifecycle(snapshot, data_dir, collection_name)
    finally:
        _release_owned_chroma(pre_rag_ids, pre_system_ids, reclaimed)
        if own_data_dir:
            # Windows 下 chroma client close 后文件锁释放存在时序抖动：
            # 有界重试删除（确定性、可复算），保证 cleaned 结论可靠
            for _ in range(5):
                shutil.rmtree(data_dir, ignore_errors=True)
                if not data_dir.exists():
                    break
                time.sleep(0.2)
            cleaned = not data_dir.exists()

    reports = {
        "frozen": {
            **frozen_report,
            "manifest_path": revision_dir / "evaluation-freeze/manifest.json",
            "candidate_manifest_path": revision_dir / "manifest.json",
            "targeted_manifest_path": revision_dir / "targeted-re-review/manifest.json",
        },
        "phase6a": {**phase6a_report,
                    "manifest_path": Path(phase6a_dir) / "manifest.json"},
        "phase6b0": {**b0_report,
                     "manifest_path": Path(phase6b0_dir) / "manifest.json"},
        "phase6b01": {**hardened_report,
                      "manifest_path": Path(hardened_dir) / "manifest.json"},
    }
    hardened_manifest = json.loads(
        (Path(hardened_dir) / "manifest.json").read_text(encoding="utf-8"))
    declarations = {
        "llm_called": False,
        "generation_used": False,
        "network_used": False,
        "chroma_persisted": not cleaned,
        "retrieval_experiment_rerun": False,
        "overlay_generated": False,
        "active_generated": False,
        "split_generated": False,
        "locked_generated": False,
        "v2_1_generated": False,
        "frozen_inputs_touched": False,
        "phase6a_touched": False,
        "phase6b0_touched": False,
        "phase6b01_touched": False,
        "original_c1_touched": False,
        "c11_touched": False,
    }
    manifest = _write_artifacts(
        out_dir, lifecycle=lifecycle, reports=reports,
        hardened_manifest=hardened_manifest, cleaned=cleaned,
        declarations=declarations,
    )
    return {
        "status": "ok",
        "lifecycle": lifecycle,
        "reports": reports,
        "manifest": manifest,
        "cleaned": cleaned,
    }


def main(argv: list[str] | None = None) -> int:
    """CLI。退出码：0=成功；2=冻结/6A/B0/hardened 漂移（零产物）；1=其他。"""
    import argparse

    parser = argparse.ArgumentParser(
        description="Phase 6-B0.2: frozen contract lifecycle hardening "
                    "(read-only verification)")
    parser.add_argument("--revision-dir", type=Path,
                        default=bl6a.FROZEN_REVISION_DIR)
    parser.add_argument("--chunks", type=Path, default=bl6a.CHUNKS_PATH)
    parser.add_argument("--chunk-manifest", type=Path,
                        default=bl6a.CHUNKS_PATH.parent / "chunk-manifest.json")
    parser.add_argument("--current-draft", type=Path,
                        default=bl6a.CURRENT_DRAFT_PATH)
    parser.add_argument("--corpus-manifest", type=Path,
                        default=cbl.CORPUS_MANIFEST_PATH)
    parser.add_argument("--phase6a-dir", type=Path, default=PHASE6A_DIR)
    parser.add_argument("--phase6b0-dir", type=Path, default=PHASE6B0_DIR)
    parser.add_argument("--hardened-dir", type=Path, default=HARDENED_DIR)
    parser.add_argument("--output", type=Path, default=LIFECYCLE_DIR)
    parser.add_argument("--data-dir", type=Path, default=None)
    parser.add_argument("--repo-root", type=Path, default=REPO_ROOT)
    parser.add_argument("--collection-name", default=COLLECTION_NAME)
    args = parser.parse_args(argv)

    try:
        summary = run_lifecycle_verification(
            revision_dir=args.revision_dir,
            chunks_path=args.chunks,
            chunk_manifest_path=args.chunk_manifest,
            current_draft_path=args.current_draft,
            corpus_manifest_path=args.corpus_manifest,
            phase6a_dir=args.phase6a_dir,
            phase6b0_dir=args.phase6b0_dir,
            hardened_dir=args.hardened_dir,
            out_dir=args.output,
            data_dir=args.data_dir,
            repo_root=args.repo_root,
            collection_name=args.collection_name,
        )
    except BaselineDrift as exc:
        print(f"BaselineDrift: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:  # noqa: BLE001 - CLI 边界统一兜底
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(f"ok: {summary['manifest']['manifest_sha256']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
