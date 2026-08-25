"""Tests for scripts.evaluate_v211_frozen_contract_lifecycle_hardened —
Phase 6-B0.2.

The lifecycle hardening verification must:
- re-verify frozen inputs (61 checks) → Phase 6-A manifest → old Phase 6-B0
  manifest → Phase 6-B0.1 hardened manifest, in that fail-closed order
  (any drift → BaselineDrift, zero outputs);
- run a real temp-Chroma lifecycle probe on the contract snapshot: all four
  mutation APIs rejected with zero drift, read-only diff/dry-run, fail-closed
  marker matrix, old-B0.1 migration, parser lifecycle unchanged;
- produce 4 artifacts with a self-hashed manifest closed over inputs/outputs;
- not touch the frozen revision, 6-A, B0, B0.1 dirs, or persist Chroma data.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import pytest

import scripts.evaluate_v211_frozen_contract_lifecycle_hardened as lh
from tests.test_evaluate_v211_frozen_product_contract import (  # noqa: E402
    _canonical, _self_hash, _sha256_bytes, _fixture_full,
)
from tests.test_index_contract import _snapshot_tree  # noqa: E402


def _fixture_baseline_dir(root: Path, fx: dict[str, Path], name: str,
                          task: str) -> Path:
    """fake 6A/B0/B0.1 风格基线目录（manifest self-hash + inputs/outputs
    字节 SHA 自洽；frozen_outputs 空）。"""
    d = root / name
    d.mkdir(parents=True, exist_ok=True)
    (d / "baseline-summary.json").write_text(
        _canonical({"fake": task}), encoding="utf-8")
    manifest = {
        "task": task,
        "inputs": {
            "chunks.jsonl": {"path": str(fx["chunks"]),
                             "sha256": _sha256_bytes(fx["chunks"].read_bytes())},
            "chunk-manifest.json": {"path": str(fx["chunk_manifest"]),
                                    "sha256": _sha256_bytes(
                                        fx["chunk_manifest"].read_bytes())},
            "corpus-manifest.json": {"path": str(fx["corpus"]),
                                     "sha256": _sha256_bytes(
                                         fx["corpus"].read_bytes())},
        },
        "frozen_outputs": {},
        "outputs": {
            "baseline-summary.json": _sha256_bytes(
                (d / "baseline-summary.json").read_bytes()),
        },
        "manifest_sha256": "PLACEHOLDER",
    }
    manifest["manifest_sha256"] = _self_hash(manifest)
    (d / "manifest.json").write_text(_canonical(manifest), encoding="utf-8")
    return d


@pytest.fixture()
def fx(tmp_path):
    return _fixture_full(tmp_path)


def _run(fx: dict[str, Path], tmp_path: Path, out_dir: Path | None = None,
         *,
         b0_dir: Path | None = None,
         hd_dir: Path | None = None,
         data_dir: Path | None = None,
         **kwargs):
    b0 = (b0_dir if b0_dir is not None
          else _fixture_baseline_dir(tmp_path / "phase6b0", fx, "phase6b0",
                                     "fixture-phase6b0"))
    hd = (hd_dir if hd_dir is not None
          else _fixture_baseline_dir(tmp_path / "phase6b01", fx, "phase6b01",
                                     "fixture-phase6b01"))
    out = Path(out_dir) if out_dir is not None else tmp_path / "out"
    return lh.run_lifecycle_verification(
        revision_dir=fx["revision"],
        chunks_path=fx["chunks"],
        chunk_manifest_path=fx["chunk_manifest"],
        current_draft_path=fx["draft"],
        corpus_manifest_path=fx["corpus"],
        phase6a_dir=fx["phase6a"],
        phase6b0_dir=b0,
        hardened_dir=hd,
        out_dir=out,
        data_dir=data_dir,
        repo_root=fx["root"],
        **kwargs,
    )


# ── Group 1: 完整流程 + 产物闭环 ──────────────────────────────────────

def test_lifecycle_verification_fixture_ok(fx, tmp_path):
    out_dir = tmp_path / "out"
    summary = _run(fx, tmp_path, out_dir=out_dir)
    assert summary["status"] == "ok"
    for name in lh.LIFECYCLE_OUTPUT_FILES + ("manifest.json",):
        assert (out_dir / name).is_file()

    manifest = json.loads((out_dir / "manifest.json")
                          .read_text(encoding="utf-8"))
    assert manifest["manifest_sha256"] == _self_hash(manifest)
    for name, sha in manifest["outputs"].items():
        assert hashlib.sha256((out_dir / name).read_bytes()).hexdigest() == sha
    assert manifest["lineage"]["phase6b01_hardened_manifest_sha256"]

    # 实测检查全过（含四类 mutation 拒绝、只读路径、fail-closed 矩阵、
    # 旧 B0.1 迁移、parser 生命周期不变、零漂移）
    lifecycle = summary["lifecycle"]
    assert lifecycle["passed_count"] == len(lifecycle["checks"])
    names = {c["name"] for c in lifecycle["checks"]}
    assert "immutability.add_files_rejected" in names
    assert "immutability.remove_file_rejected" in names
    assert "immutability.sync_sources_rejected" in names
    assert "immutability.add_sources_rejected" in names
    assert "readonly.compute_source_diff" in names
    assert "readonly.sync_sources_dry_run" in names
    assert "fail_closed.wrong_chroma_path" in names
    assert "fail_closed.marker_only_no_manifest" in names
    assert "fail_closed.malformed_manifest" in names
    assert "fail_closed.marker_manifest_mismatch" in names
    assert "migration.b01_manifest_only_blocked" in names
    assert "migration.marker_written_by_rebuild" in names
    assert "legacy.parser_add_works" in names
    assert "legacy.parser_remove_works" in names
    assert "integrity.zero_drift_after_attacks" in names
    # B0.2.1：错误/None chroma_path 不能绕过旧 B0.1 manifest-only；
    # snapshot collection 拒绝默认 parser 重建；parser 默认 rebuild 不变
    assert "b021.b01_wrong_chroma_path_blocked" in names
    assert "b021.b01_none_chroma_path_blocked" in names
    assert "b021.b01_none_path_left_no_residue" in names
    assert "b021.parser_rebuild_marker_collection_rejected" in names
    assert "b021.parser_rebuild_b01_manifest_only_rejected" in names
    assert "b021.build_index_parser_rebuild_rejected" in names
    assert "b021.parser_reuse_still_works" in names
    assert "b021.wrong_path_rebuild_touches_only_wrong_dir" in names
    assert "b021.wrong_path_rebuild_preserves_real_collection" in names
    # B0.2.2：persist-directory 身份收紧（EphemeralClient / 相对路径 +
    # CWD 切换 fail-closed / Mneme 相对 client 绝对化 / 外部绝对路径正常）
    assert "b022.ephemeral_settings_observed" in names
    assert "b022.ephemeral_add_rejected" in names
    assert "b022.ephemeral_remove_rejected" in names
    assert "b022.ephemeral_sync_rejected" in names
    assert "b022.ephemeral_add_sources_rejected" in names
    assert "b022.ephemeral_parser_rebuild_rejected" in names
    assert "b022.ephemeral_zero_drift" in names
    assert "b022.external_relative_stays_relative" in names
    assert "b022.relative_add_fail_closed" in names
    assert "b022.relative_remove_fail_closed" in names
    assert "b022.relative_sync_fail_closed" in names
    assert "b022.relative_add_sources_fail_closed" in names
    assert "b022.relative_none_path_fail_closed" in names
    assert "b022.relative_prepare_parser_rebuild_rejected" in names
    assert "b022.relative_build_parser_rebuild_rejected" in names
    assert "b022.relative_zero_drift" in names
    assert "b022.relative_no_residue_in_new_cwd" in names
    assert "b022.mneme_relative_stores_absolute" in names
    assert "b022.mneme_relative_blocks_after_cwd_switch" in names
    assert "b022.external_absolute_lifecycle_works" in names
    assert lifecycle["count"] == 9 and lifecycle["source_count"] == 3

    # DQ：核心检查全过、无错误
    dq = json.loads((out_dir / "data-quality-report.json")
                    .read_text(encoding="utf-8"))
    assert dq["passed"] is True and dq["error_count"] == 0
    assert all(c["ok"] for c in dq["checks"])
    assert any(c["name"] == "lineage.frozen_verified" for c in dq["checks"])
    assert any(c["name"] == "lineage.phase6b01_verified" for c in dq["checks"])

    # 报告存在且含关键事实
    md = (out_dir / "lifecycle-immutability-report.md").read_text(
        encoding="utf-8")
    assert "add_files_to_index" in md
    assert "mneme.snapshot_index" in md


def test_lifecycle_verification_immune_to_polluted_relative_cache(
        fx, tmp_path, monkeypatch):
    """B0.2.3 回归（最小顺序复现形态）：验证脚本必须对「相对路径标识的
    脏 SharedSystemClient 缓存」免疫——先还原顺序复现的污染形态（dirA 下
    PersistentClient(path='rel_db')，故意不 close、不清缓存），再运行
    验证脚本；脚本入口必须释放全局 system 缓存（测量对象不被复用错位，
    b022.relative_prepare_parser_rebuild_rejected 等检查全过），且结束
    后不向宿主进程残留相对标识 system / 缓存。"""
    import chromadb
    from chromadb.api.client import SharedSystemClient

    pollute = tmp_path / "pollute"
    pollute.mkdir()
    monkeypatch.chdir(str(pollute))
    polluter = chromadb.PersistentClient(path="rel_db")
    probe = polluter.get_or_create_collection(name="polluted_probe")
    probe.add(ids=["polluted-0"], documents=["polluted"],
              metadatas=[{"source_id": "polluted",
                          "source_path": str(pollute / "none.md")}],
              embeddings=[[0.1] * 384])
    # 故意不 close / 不清缓存（还原修复前第一个测试遗留的污染形态）
    assert "rel_db" in SharedSystemClient._identifier_to_system
    monkeypatch.chdir(str(tmp_path))

    out_dir = tmp_path / "out"
    summary = _run(fx, tmp_path, out_dir=out_dir)
    assert summary["status"] == "ok"
    lifecycle = summary["lifecycle"]
    assert lifecycle["passed_count"] == len(lifecycle["checks"])
    names = {c["name"] for c in lifecycle["checks"]}
    assert "b022.relative_prepare_parser_rebuild_rejected" in names
    # 脚本结束释放：不向宿主进程残留相对标识 / 共享 system 缓存
    assert "rel_db" not in SharedSystemClient._identifier_to_system
    assert "ephemeral" not in SharedSystemClient._identifier_to_system


def test_stable_json_metadata_order_independent():
    """B0.2.4：内容相同、插入顺序相反的 metadata dict 必须生成完全相同的
    持久化 detail（稳定键排序）——collection.metadata 键序跨构建不确定，
    曾导致两次真实构建 data-quality-report.json / manifest.json 不一致。"""
    a = {"mneme.snapshot_index": "immutable", "hnsw:space": "cosine"}
    b = {"hnsw:space": "cosine", "mneme.snapshot_index": "immutable"}
    assert a == b and list(a) != list(b)  # 前置：内容相同、插入顺序不同
    assert lh._stable_json(a) == lh._stable_json(b)


def test_two_independent_builds_byte_identical(fx, tmp_path):
    """B0.2.4：两次独立 lifecycle verification 的四个产物必须逐字节一致
    （check detail 一律稳定键排序，不含跨构建不确定内容）。"""
    out_a = tmp_path / "out_a"
    out_b = tmp_path / "out_b"
    _run(fx, tmp_path, out_dir=out_a)
    _run(fx, tmp_path, out_dir=out_b)
    for name in lh.LIFECYCLE_OUTPUT_FILES + ("manifest.json",):
        assert (out_a / name).read_bytes() == (out_b / name).read_bytes(), name


def test_external_absolute_client_survives_verification(fx, tmp_path):
    """B0.2.4：验证脚本运行前已存在的绝对路径 external PersistentClient
    在脚本运行后必须仍可用（system 不得被 stop/清空、原记录仍可读）。
    B0.2.3 的全局释放会 stop 该 system（count() 抛 'RustBindingsAPI'
    object has no attribute 'bindings'）——本测试在 B0.2.3 上 RED。"""
    import chromadb
    from chromadb.api.client import SharedSystemClient

    ext_dir = tmp_path / "ext_db"
    ext_client = chromadb.PersistentClient(path=str(ext_dir))
    col = ext_client.get_or_create_collection(name="survivor")
    col.add(ids=["surv-0"], documents=["survivor doc"],
            metadatas=[{"source_id": "surv",
                        "source_path": str(ext_dir / "s.md")}],
            embeddings=[[0.1] * 384])
    assert col.count() == 1

    out_dir = tmp_path / "out"
    summary = _run(fx, tmp_path, out_dir=out_dir)
    assert summary["status"] == "ok"

    # 原 client 仍可用：记录可读、system 仍在缓存且未被 stop
    assert col.count() == 1
    assert col.get(ids=["surv-0"])["documents"] == ["survivor doc"]
    assert str(ext_dir) in SharedSystemClient._identifier_to_system
    ext_client.close()


def test_manifest_inputs_closed_to_hardened_lineage(fx, tmp_path):
    out_dir = tmp_path / "out"
    _run(fx, tmp_path, out_dir=out_dir)
    manifest = json.loads((out_dir / "manifest.json")
                          .read_text(encoding="utf-8"))
    # inputs 至少闭环到 hardened manifest 声明的输入（chunks 等）
    assert manifest["inputs"]["chunks.jsonl"]["sha256"]
    assert manifest["verification"]["frozen"]["verified"] is True
    assert manifest["verification"]["phase6b01"]["verified"] is True


# ── Group 2: fail-closed（任一漂移 → 零产物）──────────────────────────

def test_fail_closed_on_frozen_drift(fx, tmp_path):
    path = fx["chunks"]
    rows = [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines()]
    rows[0]["text"] += " TAMPERED"
    path.write_text(
        "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows),
        encoding="utf-8")
    out_dir = tmp_path / "out"
    with pytest.raises(lh.BaselineDrift):
        _run(fx, tmp_path, out_dir=out_dir)
    assert not out_dir.exists()


def test_fail_closed_on_phase6a_drift(fx, tmp_path):
    path = fx["phase6a"] / "manifest.json"
    doc = json.loads(path.read_text(encoding="utf-8"))
    doc["task"] = "tampered"
    path.write_text(_canonical(doc), encoding="utf-8")
    out_dir = tmp_path / "out"
    with pytest.raises(lh.BaselineDrift):
        _run(fx, tmp_path, out_dir=out_dir)
    assert not out_dir.exists()


def test_fail_closed_on_phase6b0_drift(fx, tmp_path):
    b0 = _fixture_baseline_dir(tmp_path / "phase6b0", fx, "phase6b0",
                               "fixture-phase6b0")
    path = b0 / "manifest.json"
    doc = json.loads(path.read_text(encoding="utf-8"))
    doc["task"] = "tampered"
    path.write_text(_canonical(doc), encoding="utf-8")
    out_dir = tmp_path / "out"
    with pytest.raises(lh.BaselineDrift):
        _run(fx, tmp_path, out_dir=out_dir, b0_dir=b0)
    assert not out_dir.exists()


def test_fail_closed_on_hardened_drift(fx, tmp_path):
    hd = _fixture_baseline_dir(tmp_path / "phase6b01", fx, "phase6b01",
                               "fixture-phase6b01")
    path = hd / "manifest.json"
    doc = json.loads(path.read_text(encoding="utf-8"))
    doc["task"] = "tampered"
    path.write_text(_canonical(doc), encoding="utf-8")
    out_dir = tmp_path / "out"
    with pytest.raises(lh.BaselineDrift):
        _run(fx, tmp_path, out_dir=out_dir, hd_dir=hd)
    assert not out_dir.exists()


def test_does_not_touch_protected_inputs(fx, tmp_path):
    guard = [
        fx["revision"], fx["chunks"].parent, fx["draft"].parent,
        fx["phase6a"], fx["corpus"].parent,
    ]
    before = _snapshot_tree(guard)
    out_dir = tmp_path / "out"
    _run(fx, tmp_path, out_dir=out_dir)
    after = _snapshot_tree(guard)
    assert before == after


def test_temp_chroma_cleaned(fx, tmp_path):
    out_dir = tmp_path / "out"
    # 不传 data_dir → 脚本自建临时目录，结束后清理（cleaned=True）
    summary = _run(fx, tmp_path, out_dir=out_dir, data_dir=None)
    assert summary["cleaned"] is True  # own temp data dir removed
    assert summary["manifest"]["declarations"]["chroma_persisted"] is False


# ── Group 4: B0.2.5 — 同进程顺序依赖回归 ───────────────────────────────

def test_relative_client_collection_reads_only_in_creation_cwd(
        fx, tmp_path, monkeypatch):
    """B0.2.5 RED→GREEN（精确 CWD 场景）：b022 的 rel_db 相对 client 只记录
    相对 persist 路径（sqlite URL 是相对串，连接一旦重开即按当前 CWD 解析
    ——曾在切到 cwd_b 后的 ``rag._collection_data(rel)`` 上抛
    InternalError: unable to open database file，同进程顺序触发）。真实
    collection 的读取（before 与零漂移复读）只能在创建它的 cwd_a 发生；
    cwd_b 内只做 guard 在任何 collection 读取之前就拒绝的 fail-closed
    检查。当前实现仍在 cwd_b 读 rel（violations 非空）→ RED。"""
    import src.rag as rag

    violations: list[str] = []
    real = rag._collection_data

    def _tracking(collection, include_embeddings=False):
        try:
            persist = collection._client._system.settings.persist_directory
        except Exception:
            persist = None
        if persist == "rel_db":  # 相对 client：读取只允许发生在创建 CWD
            cwd = os.getcwd()
            if not os.path.isdir(os.path.join(cwd, "rel_db")):
                violations.append(cwd)
        return real(collection, include_embeddings=include_embeddings)

    monkeypatch.setattr(rag, "_collection_data", _tracking)

    summary = _run(fx, tmp_path, out_dir=tmp_path / "out")
    assert summary["status"] == "ok"
    lifecycle = summary["lifecycle"]
    assert lifecycle["passed_count"] == len(lifecycle["checks"])
    names = {c["name"] for c in lifecycle["checks"]}
    for name in ("b022.relative_add_fail_closed",
                 "b022.relative_remove_fail_closed",
                 "b022.relative_sync_fail_closed",
                 "b022.relative_add_sources_fail_closed",
                 "b022.relative_none_path_fail_closed",
                 "b022.relative_prepare_parser_rebuild_rejected",
                 "b022.relative_build_parser_rebuild_rejected",
                 "b022.relative_zero_drift",
                 "b022.relative_no_residue_in_new_cwd"):
        assert name in names
    assert violations == [], f"rel collection read from wrong CWD: {violations}"


def test_consecutive_verifications_with_external_client_alive(fx, tmp_path):
    """B0.2.5：单个测试内连续三次 lifecycle verification（两次显式
    data_dir、一次 own-temp），每次前后保有外部绝对路径
    PersistentClient——每次 status=ok、外部 client 每次后仍可读、
    own-temp run cleaned=True（回归 B0.2.4 验收阻断的跨套件顺序问题：
    连续运行不得破坏运行前已有 client）。"""
    import chromadb
    from chromadb.api.client import SharedSystemClient

    ext_dir = tmp_path / "ext_db"
    ext_client = chromadb.PersistentClient(path=str(ext_dir))
    col = ext_client.get_or_create_collection(name="survivor_seq")
    col.add(ids=["surv-0"], documents=["survivor doc"],
            metadatas=[{"source_id": "surv",
                        "source_path": str(ext_dir / "s.md")}],
            embeddings=[[0.1] * 384])

    for i, data_dir in enumerate((tmp_path / "data1", tmp_path / "data2",
                                  None)):
        summary = _run(fx, tmp_path, out_dir=tmp_path / f"out{i}",
                       data_dir=data_dir)
        assert summary["status"] == "ok"
        assert col.count() == 1
        assert col.get(ids=["surv-0"])["documents"] == ["survivor doc"]
        assert str(ext_dir) in SharedSystemClient._identifier_to_system
        if data_dir is None:
            assert summary["cleaned"] is True
    ext_client.close()


def test_prepare_rejection_releases_same_dir_client_promptly(fx, tmp_path,
                                                             monkeypatch):
    """B0.2.5 RED→GREEN：prepare_index 预期拒绝仍会新建/注册同物理目录
    （<cwd_a>/rel_db）的绝对路径 Rag client——检查结束后必须立即只释放
    本检查新建的 client/system，不得留置到整个验证结束（两个 system
    同时持有同一 sqlite 文件）；运行前已有的绝对路径 external client
    绝不关闭。当前实现留置到验证结束 → RED。"""
    import chromadb
    from chromadb.api.client import SharedSystemClient

    import src.rag as rag

    pre_rag_ids = {id(c) for c in rag._CHROMA_CLIENTS}
    pre_system_ids = set(SharedSystemClient._identifier_to_system.keys())

    observed: dict = {}
    real_build_index = rag.build_index

    def _spy_build_index(file_paths, collection_name, *args, **kwargs):
        # b022 的 build_index 检查紧跟在 prepare_index 检查之后——此时
        # prepare 检查新建的同目录 client/system 必须已经释放
        if collection_name == f"{lh.COLLECTION_NAME}_rel":
            observed["rag_clients"] = list(rag._CHROMA_CLIENTS)
            observed["system_ids"] = set(
                SharedSystemClient._identifier_to_system.keys())
        return real_build_index(file_paths, collection_name, *args, **kwargs)

    monkeypatch.setattr(rag, "build_index", _spy_build_index)

    ext_dir = tmp_path / "ext_db"
    ext_client = chromadb.PersistentClient(path=str(ext_dir))
    ext_col = ext_client.get_or_create_collection(name="keepme")
    ext_col.add(ids=["k-0"], documents=["keep"],
                metadatas=[{"source_id": "k"}],
                embeddings=[[0.1] * 384])

    summary = _run(fx, tmp_path, out_dir=tmp_path / "out")
    assert summary["status"] == "ok"
    # 运行前已有 external client 不被 stop / 清空，仍可读
    assert ext_col.count() == 1
    assert str(ext_dir) in SharedSystemClient._identifier_to_system

    # prepare 检查新建的同目录 rel_db client/system 已即时释放
    new_clients = [c for c in observed["rag_clients"]
                   if id(c) not in pre_rag_ids]
    for client in new_clients:
        try:
            persist = client._system.settings.persist_directory
        except Exception:
            persist = None
        assert os.path.basename(str(persist)) != "rel_db", \
            f"prepare_index 新建的同目录 client 未及时释放: {persist}"
    new_system_ids = observed["system_ids"] - pre_system_ids
    for ident in new_system_ids:
        # 相对标识 "rel_db" 是 rel_client 自身 system（检查期间合法存活）；
        # 只需确认 prepare_index 新建的「同物理目录绝对路径」system 已释放
        assert not (os.path.isabs(ident)
                    and os.path.basename(os.path.normpath(ident)) == "rel_db"), \
            f"prepare_index 新建的同目录 system 未及时释放: {ident}"
    ext_client.close()


def test_temp_chroma_cleaned_failure_sequence_regression(fx, tmp_path,
                                                         monkeypatch):
    """B0.2.5：把 B0.2.4 验收失败的跨套件顺序形态纳入回归（不能只靠单独
    运行通过）——先污染 'rel_db'（故意不 close、不清缓存）→ 验证脚本
    运行 → 创建外部绝对路径 client → 再连续两次验证（一次 own-temp），
    全部 status=ok、外部 client 始终可读、own-temp cleaned=True、结束不
    向宿主进程残留相对标识 system。"""
    import chromadb
    from chromadb.api.client import SharedSystemClient

    pollute = tmp_path / "pollute"
    pollute.mkdir()
    monkeypatch.chdir(str(pollute))
    polluter = chromadb.PersistentClient(path="rel_db")
    probe = polluter.get_or_create_collection(name="polluted_probe_seq")
    probe.add(ids=["polluted-0"], documents=["polluted"],
              metadatas=[{"source_id": "polluted",
                          "source_path": str(pollute / "none.md")}],
              embeddings=[[0.1] * 384])
    # 故意不 close / 不清缓存（还原跨套件顺序的污染形态）
    assert "rel_db" in SharedSystemClient._identifier_to_system
    monkeypatch.chdir(str(tmp_path))

    summary = _run(fx, tmp_path, out_dir=tmp_path / "out0")
    assert summary["status"] == "ok"

    ext_dir = tmp_path / "ext_db"
    ext_client = chromadb.PersistentClient(path=str(ext_dir))
    col = ext_client.get_or_create_collection(name="survivor_seq2")
    col.add(ids=["surv-0"], documents=["survivor doc"],
            metadatas=[{"source_id": "surv",
                        "source_path": str(ext_dir / "s.md")}],
            embeddings=[[0.1] * 384])

    summary2 = _run(fx, tmp_path, out_dir=tmp_path / "out1",
                    data_dir=tmp_path / "data1")
    assert summary2["status"] == "ok"
    assert col.count() == 1

    summary3 = _run(fx, tmp_path, out_dir=tmp_path / "out2", data_dir=None)
    assert summary3["status"] == "ok"
    assert summary3["cleaned"] is True
    assert col.count() == 1
    assert col.get(ids=["surv-0"])["documents"] == ["survivor doc"]
    assert str(ext_dir) in SharedSystemClient._identifier_to_system

    assert "rel_db" not in SharedSystemClient._identifier_to_system
    assert "ephemeral" not in SharedSystemClient._identifier_to_system
    ext_client.close()


def test_main_exit_codes(fx, tmp_path):
    b0 = _fixture_baseline_dir(tmp_path / "phase6b0", fx, "phase6b0",
                               "fixture-phase6b0")
    hd = _fixture_baseline_dir(tmp_path / "phase6b01", fx, "phase6b01",
                               "fixture-phase6b01")
    args = [
        "--revision-dir", str(fx["revision"]),
        "--chunks", str(fx["chunks"]),
        "--chunk-manifest", str(fx["chunk_manifest"]),
        "--current-draft", str(fx["draft"]),
        "--corpus-manifest", str(fx["corpus"]),
        "--phase6a-dir", str(fx["phase6a"]),
        "--phase6b0-dir", str(b0),
        "--hardened-dir", str(hd),
        "--output", str(tmp_path / "out"),
        "--data-dir", str(tmp_path / "data"),
        "--repo-root", str(fx["root"]),
    ]
    assert lh.main(args) == 0
    assert (tmp_path / "out" / "manifest.json").is_file()

    # hardened 漂移 → exit 2，零产物
    path = hd / "manifest.json"
    doc = json.loads(path.read_text(encoding="utf-8"))
    doc["task"] = "tampered"
    path.write_text(_canonical(doc), encoding="utf-8")
    out2 = tmp_path / "out2"
    assert lh.main([
        "--revision-dir", str(fx["revision"]),
        "--chunks", str(fx["chunks"]),
        "--chunk-manifest", str(fx["chunk_manifest"]),
        "--current-draft", str(fx["draft"]),
        "--corpus-manifest", str(fx["corpus"]),
        "--phase6a-dir", str(fx["phase6a"]),
        "--phase6b0-dir", str(b0),
        "--hardened-dir", str(hd),
        "--output", str(out2),
        "--data-dir", str(tmp_path / "data2"),
        "--repo-root", str(fx["root"]),
    ]) == 2
    assert not out2.exists()


# ── Group 3: real frozen data (skip-guarded) ──────────────────────────

pytestmark_real = pytest.mark.skipif(
    not lh.HARDENED_DIR.exists() or not lh.PHASE6B0_DIR.exists(),
    reason="frozen v2.0.11 revision and Phase 6-B0/B0.1 baselines are local",
)


@pytestmark_real
def test_real_lifecycle_verification_1006(tmp_path):
    """真实冻结 snapshot（1006 chunks / 13 sources）：四类 mutation 拒绝、
    只读路径、fail-closed 矩阵、零漂移，产物与 manifest 闭环。"""
    out_dir = tmp_path / "out"
    summary = lh.run_lifecycle_verification(
        revision_dir=lh.bl6a.FROZEN_REVISION_DIR,
        chunks_path=lh.bl6a.CHUNKS_PATH,
        chunk_manifest_path=lh.bl6a.CHUNKS_PATH.parent / "chunk-manifest.json",
        current_draft_path=lh.bl6a.CURRENT_DRAFT_PATH,
        corpus_manifest_path=lh.cbl.CORPUS_MANIFEST_PATH,
        phase6a_dir=lh.PHASE6A_DIR,
        phase6b0_dir=lh.PHASE6B0_DIR,
        hardened_dir=lh.HARDENED_DIR,
        out_dir=out_dir,
        data_dir=tmp_path / "data",
        repo_root=lh.REPO_ROOT,
    )
    lifecycle = summary["lifecycle"]
    assert lifecycle["count"] == 1006
    assert lifecycle["source_count"] == 13
    assert lifecycle["passed_count"] == len(lifecycle["checks"])

    manifest = json.loads((out_dir / "manifest.json")
                          .read_text(encoding="utf-8"))
    assert manifest["manifest_sha256"] == _self_hash(manifest)
    for name, sha in manifest["outputs"].items():
        assert hashlib.sha256((out_dir / name).read_bytes()).hexdigest() == sha
    dq = json.loads((out_dir / "data-quality-report.json")
                    .read_text(encoding="utf-8"))
    assert dq["passed"] is True and dq["error_count"] == 0
