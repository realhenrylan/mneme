"""G1-S.1：synthetic capture/replay 硬化验收测试（TDD）。

覆盖验收（Phase 6-G1-S.1 阻断项）：
- capability 身份校验：直接构造拒绝、issuer 签发可用、使用期路径重校验；
- chunks contract 强制：缺失 / 字节漂移 / 行数漂移 / chunk_id 映射漂移；
- synthetic 路径边界：受保护评测资产树内的路径在 read/mkdir/write 前拒绝；
- sync/stream planning profile 隔离；
- 两次独立 capture/replay 构建逐字节一致。

全部使用本地 synthetic fixture（零 LLM / 零网络 / 零真实检索）。
"""
from __future__ import annotations

import builtins
import json
from pathlib import Path
from unittest import mock

import pytest

import src.rag as rag
from src import query_plan_capture as qpc

DOCS = ["d0 文本", "d1 文本", "d2 文本"]
METAS = [
    {"chunk_id": "chunk_0", "source_id": "s0", "source_name": "a.md",
     "source": "a.md", "chunk_index": 0},
    {"chunk_id": "chunk_1", "source_id": "s1", "source_name": "b.md",
     "source": "b.md", "chunk_index": 0},
    {"chunk_id": "chunk_2", "source_id": "s2", "source_name": "c.md",
     "source": "c.md", "chunk_index": 0},
]
# guard 全部跳过 → 零 LLM（rewrite: 无历史；decompose: 简单中文）
SIMPLE_QUERY = "这篇论文讲了什么？"

REPO_ROOT = Path(__file__).resolve().parents[1]
PROTECTED_REVISIONS = REPO_ROOT / "evaluation" / "datasets" / "v2" / "revisions"
PROTECTED_BASELINES = REPO_ROOT / "evaluation" / "product-baselines"


def _fake_retrieve(sq, model, collection, bm25, documents, metadatas, k=None):
    """确定性 fake 检索：同分候选 1、2 在 0 之前被观察到。"""
    return [1, 2, 0], ["d1 文本", "d2 文本", "d0 文本"], [0.7, 0.7, 0.9]


def _fake_retrieve_single(sq, model, collection, bm25, documents, metadatas, k=None):
    """仅命中 chunk_0（chunk_1/chunk_2 不进入 base_candidates）。"""
    return [0], ["d0 文本"], [0.9]


def _chunks_file(tmp_path, docs=DOCS, metas=METAS) -> Path:
    """与 metadatas 一一对应的 synthetic chunks JSONL。"""
    path = tmp_path / "synthetic-chunks.jsonl"
    lines = [
        json.dumps(
            {"chunk_id": meta["chunk_id"],
             "text": docs[i] if i < len(docs) else ""},
            ensure_ascii=False,
        )
        for i, meta in enumerate(metas)
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def _runtime_plan(monkeypatch, *, docs=DOCS, metas=METAS,
                  retrieval_k=None, planning_profile="sync",
                  retrieve=_fake_retrieve):
    monkeypatch.setattr(rag, "retrieve_hybrid_with_sources", retrieve)
    return rag._plan_query_runtime(
        SIMPLE_QUERY, None, None, None, docs, metas, history=None,
        retrieval_k=retrieval_k, planning_profile=planning_profile,
    )


def _evidence_for(runtime, docs=DOCS, metas=METAS):
    return rag.prepare_answer_evidence(
        SIMPLE_QUERY, None, None, None, docs, metas, history=None,
        query_plan=runtime,
    )


def _do_capture(tmp_path, monkeypatch, *, root_name="capture",
                docs=DOCS, metas=METAS, chunks=None,
                retrieve=_fake_retrieve):
    """issuer context + capability 的一次完整 synthetic capture。"""
    chunks = chunks or _chunks_file(tmp_path, docs, metas)
    runtime = _runtime_plan(monkeypatch, docs=docs, metas=metas,
                            retrieve=retrieve)
    evidence = _evidence_for(runtime, docs, metas)
    ctx = qpc.SYNTHETIC_CAPTURE_ISSUER.create_context(
        tmp_path / root_name, chunks,
    )
    cap = qpc.SYNTHETIC_CAPTURE_ISSUER.create_capability(ctx)
    qpc.capture_synthetic_plan(runtime, evidence, cap, metas)
    return ctx, runtime, evidence


def _replay(ctx, docs=DOCS, metas=METAS):
    cap = qpc.SYNTHETIC_CAPTURE_ISSUER.create_capability(ctx)
    return qpc.replay_synthetic_plan(cap, None, None, None, docs, metas)


def _spy_io(monkeypatch):
    """记录 builtins.open 与 Path.mkdir 调用（wraps 保留原行为）。"""
    opened: list[str] = []
    mkdirs: list[str] = []
    real_open = builtins.open

    def spy_open(file, mode="r", *a, **k):
        opened.append(str(file))
        return real_open(file, mode, *a, **k)

    real_mkdir = Path.mkdir

    def spy_mkdir(self, *a, **k):
        mkdirs.append(str(self))
        return real_mkdir(self, *a, **k)

    monkeypatch.setattr(builtins, "open", spy_open)
    monkeypatch.setattr(Path, "mkdir", spy_mkdir)
    return opened, mkdirs


# ═══════════════════════════════════════════════════════════════
# 阻断项 1：capability 身份校验（issuer marker；误用防护）
# ═══════════════════════════════════════════════════════════════

class TestCapabilityIdentity:
    def test_directly_constructed_capability_rejected(self, tmp_path, monkeypatch):
        """普通调用方直接构造 SyntheticCaptureCapability 必须被拒绝。"""
        ctx, runtime, evidence = _do_capture(tmp_path, monkeypatch)
        forged = qpc.SyntheticCaptureCapability(object(), ctx)
        with pytest.raises(ValueError, match="issuer|forged|issue"):
            qpc.capture_synthetic_plan(runtime, evidence, forged, METAS)

    def test_issuer_capability_accepted(self, tmp_path, monkeypatch):
        """issuer 签发的 capability 必须可用（同一 context 可再次签发）。"""
        ctx, runtime, evidence = _do_capture(tmp_path, monkeypatch)
        cap = qpc.SYNTHETIC_CAPTURE_ISSUER.create_capability(ctx)
        assert isinstance(cap, qpc.SyntheticCaptureCapability)
        assert _replay(ctx)  # 重新签发的 capability 可 replay

    def test_capability_requires_issuer_context(self):
        """capability 只能由 issuer 从 SyntheticCaptureContext 签发。"""
        with pytest.raises(TypeError):
            qpc.SYNTHETIC_CAPTURE_ISSUER.create_capability(
                {"output_root": "/tmp/x", "chunks_path": "/tmp/y"},
            )

    def test_capability_not_serializable(self, tmp_path, monkeypatch):
        ctx, _, _ = _do_capture(tmp_path, monkeypatch)
        cap = qpc.SYNTHETIC_CAPTURE_ISSUER.create_capability(ctx)
        with pytest.raises(TypeError):
            json.dumps(cap)


# ═══════════════════════════════════════════════════════════════
# 阻断项 2：chunks contract 强制
# ═══════════════════════════════════════════════════════════════

class TestChunksContract:
    def test_capture_records_chunks_contract(self, tmp_path, monkeypatch):
        ctx, _, _ = _do_capture(tmp_path, monkeypatch)
        row = json.loads(
            (ctx.output_root / qpc.CAPTURE_FILE_NAME).read_text(encoding="utf-8"),
        )
        contract = row["pipeline_contract"]
        assert set(("chunks_bytes_sha256", "chunks_line_count",
                    "chunks_chunk_ids")) <= set(contract)
        assert contract["chunks_chunk_ids"] == ["chunk_0", "chunk_1", "chunk_2"]
        assert contract["chunks_line_count"] == 3

    def test_capture_missing_chunks_file_rejected(self, tmp_path, monkeypatch):
        runtime = _runtime_plan(monkeypatch)
        evidence = _evidence_for(runtime)
        ctx = qpc.SYNTHETIC_CAPTURE_ISSUER.create_context(
            tmp_path / "capture", tmp_path / "no-such-chunks.jsonl",
        )
        cap = qpc.SYNTHETIC_CAPTURE_ISSUER.create_capability(ctx)
        with pytest.raises(FileNotFoundError):
            qpc.capture_synthetic_plan(runtime, evidence, cap, METAS)
        assert not (tmp_path / "capture").exists()  # 写盘前 fail-closed

    def test_capture_chunks_mapping_mismatch_rejected(self, tmp_path, monkeypatch):
        """chunks 文件 chunk_id 映射与 metadatas 不一致 → capture 拒绝。"""
        runtime = _runtime_plan(monkeypatch)
        evidence = _evidence_for(runtime)
        chunks = tmp_path / "mismatched.jsonl"
        chunks.write_text(
            '{"chunk_id": "chunk_1", "text": "d1"}\n'
            '{"chunk_id": "chunk_0", "text": "d0"}\n'
            '{"chunk_id": "chunk_2", "text": "d2"}\n',
            encoding="utf-8",
        )
        ctx = qpc.SYNTHETIC_CAPTURE_ISSUER.create_context(
            tmp_path / "capture", chunks,
        )
        cap = qpc.SYNTHETIC_CAPTURE_ISSUER.create_capability(ctx)
        with pytest.raises(ValueError, match="mapping|chunk_id"):
            qpc.capture_synthetic_plan(runtime, evidence, cap, METAS)
        assert not (tmp_path / "capture").exists()

    def test_capture_rejects_metadatas_without_chunk_id(self, tmp_path, monkeypatch):
        runtime = _runtime_plan(monkeypatch)
        evidence = _evidence_for(runtime)
        chunks = _chunks_file(tmp_path)
        bad_metas = [dict(m) for m in METAS]
        bad_metas[1].pop("chunk_id")
        ctx = qpc.SYNTHETIC_CAPTURE_ISSUER.create_context(
            tmp_path / "capture", chunks,
        )
        cap = qpc.SYNTHETIC_CAPTURE_ISSUER.create_capability(ctx)
        with pytest.raises(ValueError, match="chunk_id"):
            qpc.capture_synthetic_plan(runtime, evidence, cap, bad_metas)

    def test_replay_chunks_bytes_drift_rejected(self, tmp_path, monkeypatch):
        ctx, _, _ = _do_capture(tmp_path, monkeypatch)
        ctx.chunks_path.write_text(
            '{"chunk_id": "chunk_0", "text": "TAMPERED"}\n'
            '{"chunk_id": "chunk_1", "text": "d1"}\n'
            '{"chunk_id": "chunk_2", "text": "d2"}\n',
            encoding="utf-8",
        )
        with pytest.raises(ValueError, match="chunks"):
            _replay(ctx)

    def test_replay_recorded_line_count_drift_rejected(self, tmp_path, monkeypatch):
        ctx, _, _ = _do_capture(tmp_path, monkeypatch)
        jsonl = ctx.output_root / qpc.CAPTURE_FILE_NAME
        row = json.loads(jsonl.read_text(encoding="utf-8"))
        row["pipeline_contract"]["chunks_line_count"] = 99
        crafted = tmp_path / "crafted"
        qpc._write_sealed(crafted, [row], "synthetic-run", "turn-1")
        bad_ctx = qpc.SYNTHETIC_CAPTURE_ISSUER.create_context(crafted, ctx.chunks_path)
        with pytest.raises(ValueError, match="chunks"):
            _replay(bad_ctx)

    def test_replay_recorded_mapping_drift_rejected(self, tmp_path, monkeypatch):
        ctx, _, _ = _do_capture(tmp_path, monkeypatch)
        jsonl = ctx.output_root / qpc.CAPTURE_FILE_NAME
        row = json.loads(jsonl.read_text(encoding="utf-8"))
        row["pipeline_contract"]["chunks_chunk_ids"] = [
            "chunk_2", "chunk_1", "chunk_0",
        ]
        crafted = tmp_path / "crafted"
        qpc._write_sealed(crafted, [row], "synthetic-run", "turn-1")
        bad_ctx = qpc.SYNTHETIC_CAPTURE_ISSUER.create_context(crafted, ctx.chunks_path)
        with pytest.raises(ValueError, match="chunks"):
            _replay(bad_ctx)

    def test_replay_rejects_legacy_trace_without_chunks_contract(
            self, tmp_path, monkeypatch):
        """禁止兼容无 chunks contract 的旧 capture（fail-closed）。"""
        ctx, _, _ = _do_capture(tmp_path, monkeypatch)
        jsonl = ctx.output_root / qpc.CAPTURE_FILE_NAME
        row = json.loads(jsonl.read_text(encoding="utf-8"))
        for key in ("chunks_bytes_sha256", "chunks_line_count", "chunks_chunk_ids"):
            row["pipeline_contract"].pop(key, None)
        crafted = tmp_path / "crafted"
        qpc._write_sealed(crafted, [row], "synthetic-run", "turn-1")
        bad_ctx = qpc.SYNTHETIC_CAPTURE_ISSUER.create_context(crafted, ctx.chunks_path)
        with pytest.raises(ValueError, match="chunks"):
            _replay(bad_ctx)


# ═══════════════════════════════════════════════════════════════
# 阻断项 3：synthetic 路径边界（运行时强制）
# ═══════════════════════════════════════════════════════════════

class TestSyntheticBoundary:
    def test_create_context_rejects_revisions_path(self, tmp_path):
        with pytest.raises(ValueError, match="protected|boundary|evaluation"):
            qpc.SYNTHETIC_CAPTURE_ISSUER.create_context(
                PROTECTED_REVISIONS / "nested" / "capture",
                tmp_path / "chunks.jsonl",
            )

    def test_create_context_rejects_product_baselines_path(self, tmp_path):
        with pytest.raises(ValueError, match="protected|boundary|evaluation"):
            qpc.SYNTHETIC_CAPTURE_ISSUER.create_context(
                PROTECTED_BASELINES / "v2.0.11-frozen-current" / "capture",
                tmp_path / "chunks.jsonl",
            )

    def test_create_context_rejects_protected_chunks_path(self, tmp_path):
        with pytest.raises(ValueError, match="protected|boundary|evaluation"):
            qpc.SYNTHETIC_CAPTURE_ISSUER.create_context(
                tmp_path / "capture",
                PROTECTED_REVISIONS / "chunks.jsonl",
            )

    def test_create_context_rejects_relative_path_escaping_into_tree(self, tmp_path):
        """相对/.. 路径解析后落入受保护树也必须拒绝（resolve 后判定）。"""
        rel = Path("evaluation") / "datasets" / "v2" / "revisions" / "cap"
        with pytest.raises(ValueError, match="protected|boundary|evaluation"):
            qpc.SYNTHETIC_CAPTURE_ISSUER.create_context(rel, tmp_path / "c.jsonl")

    def test_create_capability_revalidates_bypassed_context(self, tmp_path):
        """绕过 create_context 直接构造受保护 context → issuer 拒绝签发。"""
        ctx = qpc.SyntheticCaptureContext(
            PROTECTED_REVISIONS / "cap", tmp_path / "chunks.jsonl",
        )
        with pytest.raises(ValueError, match="protected|boundary|evaluation"):
            qpc.SYNTHETIC_CAPTURE_ISSUER.create_capability(ctx)

    def test_capture_protected_path_rejected_before_any_io(self, tmp_path, monkeypatch):
        """capture 对受保护路径必须在任何 open/mkdir/write 之前拒绝。"""
        ctx, runtime, evidence = _do_capture(tmp_path, monkeypatch)
        cap = qpc.SYNTHETIC_CAPTURE_ISSUER.create_capability(ctx)
        cap._context = qpc.SyntheticCaptureContext(
            PROTECTED_BASELINES / "cap", ctx.chunks_path,
        )
        opened, mkdirs = _spy_io(monkeypatch)
        with pytest.raises(ValueError, match="protected|boundary|evaluation"):
            qpc.capture_synthetic_plan(runtime, evidence, cap, METAS)
        assert opened == []
        assert mkdirs == []

    def test_replay_protected_path_rejected_before_any_read(self, tmp_path, monkeypatch):
        """replay 对受保护路径必须在任何 read 之前拒绝（使用期重校验）。"""
        ctx, _, _ = _do_capture(tmp_path, monkeypatch)
        cap = qpc.SYNTHETIC_CAPTURE_ISSUER.create_capability(ctx)
        cap._context = qpc.SyntheticCaptureContext(
            PROTECTED_REVISIONS / "cap", ctx.chunks_path,
        )
        opened, mkdirs = _spy_io(monkeypatch)
        with pytest.raises(ValueError, match="protected|boundary|evaluation"):
            qpc.replay_synthetic_plan(cap, None, None, None, DOCS, METAS)
        assert opened == []
        assert mkdirs == []

    def test_output_root_must_be_new_target(self, tmp_path, monkeypatch):
        """输出目录必须是新建目标：已存在目录（空或非空）一律拒绝。"""
        ctx, runtime, evidence = _do_capture(tmp_path, monkeypatch)
        existing = tmp_path / "existing"
        existing.mkdir()
        (existing / "other-file.txt").write_text("x", encoding="utf-8")
        bad_ctx = qpc.SYNTHETIC_CAPTURE_ISSUER.create_context(
            existing, ctx.chunks_path,
        )
        cap = qpc.SYNTHETIC_CAPTURE_ISSUER.create_capability(bad_ctx)
        with pytest.raises(ValueError, match="already exists|new target"):
            qpc.capture_synthetic_plan(runtime, evidence, cap, METAS)
        assert (existing / qpc.CAPTURE_FILE_NAME).exists() is False


# ═══════════════════════════════════════════════════════════════
# 阻断项 5：sync/stream planning profile 隔离
# ═══════════════════════════════════════════════════════════════

class TestProfileIsolation:
    def test_sync_runtime_plan_capturable(self, tmp_path, monkeypatch):
        ctx, runtime, _ = _do_capture(tmp_path, monkeypatch)
        assert runtime.planning_profile == "sync"
        assert runtime.retrieval_k is None
        assert (ctx.output_root / qpc.CAPTURE_FILE_NAME).exists()

    def test_stream_runtime_plan_capture_rejected(self, tmp_path, monkeypatch):
        """answer_query_stream 产生的 plan（profile=stream）必须 fail-closed。"""
        runtime = _runtime_plan(
            monkeypatch, retrieval_k=20, planning_profile="stream",
        )
        evidence = _evidence_for(runtime)
        ctx = qpc.SYNTHETIC_CAPTURE_ISSUER.create_context(
            tmp_path / "capture", _chunks_file(tmp_path),
        )
        cap = qpc.SYNTHETIC_CAPTURE_ISSUER.create_capability(ctx)
        with pytest.raises(ValueError, match="stream|profile"):
            qpc.capture_synthetic_plan(runtime, evidence, cap, METAS)
        assert not (tmp_path / "capture").exists()  # 写文件前 fail-closed

    def test_sync_profile_with_non_default_width_rejected(
            self, tmp_path, monkeypatch):
        """profile=sync 但检索宽度与 sync contract 不一致 → 拒绝。"""
        runtime = _runtime_plan(monkeypatch, retrieval_k=10)
        evidence = _evidence_for(runtime)
        ctx = qpc.SYNTHETIC_CAPTURE_ISSUER.create_context(
            tmp_path / "capture", _chunks_file(tmp_path),
        )
        cap = qpc.SYNTHETIC_CAPTURE_ISSUER.create_capability(ctx)
        with pytest.raises(ValueError, match="retrieval_k|width"):
            qpc.capture_synthetic_plan(runtime, evidence, cap, METAS)
        assert not (tmp_path / "capture").exists()

    def test_stream_runtime_plan_records_stream_profile(self, monkeypatch):
        """stream 产生的 runtime plan 显式记录 profile=stream / 宽度=20。"""
        runtime = _runtime_plan(
            monkeypatch, retrieval_k=20, planning_profile="stream",
        )
        assert runtime.planning_profile == "stream"
        assert runtime.retrieval_k == 20


# ═══════════════════════════════════════════════════════════════
# 字节确定性：两次独立 capture/replay 逐字节一致
# ═══════════════════════════════════════════════════════════════

class TestByteDeterminism:
    def test_two_independent_capture_replay_roundtrips_agree(
            self, tmp_path, monkeypatch):
        """同一 captured plan 在不同目录/时刻写出 → 字节一致；replay 证据一致。"""
        ctx_a, _, ev_a = _do_capture(tmp_path, monkeypatch, root_name="a")
        ctx_b, _, ev_b = _do_capture(tmp_path, monkeypatch, root_name="b")
        for name in (qpc.CAPTURE_FILE_NAME, qpc.MANIFEST_FILE_NAME):
            assert (ctx_a.output_root / name).read_bytes() == \
                (ctx_b.output_root / name).read_bytes(), name

        re_a = _replay(ctx_a)
        re_b = _replay(ctx_b)
        assert len(re_a) == len(re_b) == 1
        for field in ("plan_fingerprint", "retrieval_fingerprint",
                      "context_sha256", "context", "candidate_chunk_ids",
                      "context_chunk_ids", "refused", "refusal_reason",
                      "top_scores"):
            assert getattr(re_a[0], field) == getattr(re_b[0], field), field
        assert re_a[0].plan_fingerprint == ev_a.plan_fingerprint
        assert re_b[0].plan_fingerprint == ev_b.plan_fingerprint


# ═══════════════════════════════════════════════════════════════
# 阻断项 4：manifest outputs closure 复算
# ═══════════════════════════════════════════════════════════════

class TestOutputsClosure:
    def test_outputs_closure_tampered_with_recomputed_self_hash_rejected(
            self, tmp_path, monkeypatch):
        """只篡改 outputs_sha256 并正确重算 manifest self-hash → replay 仍拒绝。"""
        ctx, _, _ = _do_capture(tmp_path, monkeypatch)
        manifest_path = ctx.output_root / qpc.MANIFEST_FILE_NAME
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        payload["outputs_sha256"] = "f" * 64
        payload.pop("manifest_sha256")
        payload["manifest_sha256"] = qpc._sha256_text(
            qpc._canonical_manifest_json(payload),
        )
        manifest_path.write_bytes(
            (qpc._canonical_manifest_json(payload) + "\n").encode("utf-8"),
        )
        with pytest.raises(ValueError, match="outputs_sha256"):
            _replay(ctx)

    def test_outputs_closure_absence_rejected(self, tmp_path, monkeypatch):
        """outputs_sha256 键缺失（self-hash 重算后）同样拒绝。"""
        ctx, _, _ = _do_capture(tmp_path, monkeypatch)
        manifest_path = ctx.output_root / qpc.MANIFEST_FILE_NAME
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        payload.pop("outputs_sha256")
        payload.pop("manifest_sha256")
        payload["manifest_sha256"] = qpc._sha256_text(
            qpc._canonical_manifest_json(payload),
        )
        manifest_path.write_bytes(
            (qpc._canonical_manifest_json(payload) + "\n").encode("utf-8"),
        )
        with pytest.raises(ValueError, match="outputs_sha256"):
            _replay(ctx)


# ═══════════════════════════════════════════════════════════════
# 合同修正 A：refusal threshold 记录并比较解析后生效值
# ═══════════════════════════════════════════════════════════════

class TestEffectiveRefusalThreshold:
    def test_contract_records_effective_parsed_threshold(
            self, tmp_path, monkeypatch):
        """解析后生效值进 contract；原始 env 只作为 provenance 记录。"""
        monkeypatch.setenv("RAG_REFUSAL_THRESHOLD", "0.05")
        ctx, _, _ = _do_capture(tmp_path, monkeypatch)
        row = json.loads(
            (ctx.output_root / qpc.CAPTURE_FILE_NAME).read_text(encoding="utf-8"),
        )
        contract = row["pipeline_contract"]
        assert contract["refusal_threshold"] == 0.05
        assert row["provenance"]["refusal_threshold_env"] == "0.05"

    def test_replay_blocks_effective_threshold_drift(self, tmp_path, monkeypatch):
        """生效值变化（同 env 来源）→ replay 硬阻断。"""
        monkeypatch.setenv("RAG_REFUSAL_THRESHOLD", "0.05")
        ctx, _, _ = _do_capture(tmp_path, monkeypatch)
        monkeypatch.setenv("RAG_REFUSAL_THRESHOLD", "0.09")
        with pytest.raises(ValueError, match="refusal_threshold"):
            _replay(ctx)

    def test_invalid_env_falls_back_to_default(self, tmp_path, monkeypatch):
        """非法 env 与产品解析逻辑一致回退 default，replay 可通过。"""
        monkeypatch.setenv("RAG_REFUSAL_THRESHOLD", "not-a-number")
        ctx, _, _ = _do_capture(tmp_path, monkeypatch)
        row = json.loads(
            (ctx.output_root / qpc.CAPTURE_FILE_NAME).read_text(encoding="utf-8"),
        )
        assert row["pipeline_contract"]["refusal_threshold"] == \
            rag.DEFAULT_REFUSAL_THRESHOLD
        assert len(_replay(ctx)) == 1

    def test_env_raw_value_not_a_blocking_key(self, tmp_path, monkeypatch):
        """原始 env 仅 provenance：env 值变化但解析后值不变 → 不阻断。"""
        monkeypatch.setenv("RAG_REFUSAL_THRESHOLD", "0.050")
        ctx, _, _ = _do_capture(tmp_path, monkeypatch)
        monkeypatch.setenv("RAG_REFUSAL_THRESHOLD", "5e-2")
        # 两种写法解析后同为 0.05 → 生效值未漂移 → replay 通过
        assert len(_replay(ctx)) == 1


# ═══════════════════════════════════════════════════════════════
# 合同修正 B：provenance drift warning-only 比较（prompt/model/history）
# ═══════════════════════════════════════════════════════════════

class TestProvenanceDriftCoverage:
    def test_model_provenance_drift_warns_only(self, tmp_path, monkeypatch):
        """requested_model 与当前默认模型不一致 → 只告警不阻断。"""
        ctx, _, _ = _do_capture(tmp_path, monkeypatch)
        monkeypatch.setattr(rag, "DEFAULT_LLM_MODEL", "other-model")
        with pytest.warns(UserWarning, match="model"):
            evidences = _replay(ctx)
        assert len(evidences) == 1

    def test_history_provenance_recorded_and_noted_on_replay(
            self, tmp_path, monkeypatch):
        """history provenance 在 capture 记录；零 LLM replay 无 history 输入
        可比 → warning-only 说明，不阻断。"""
        chunks = _chunks_file(tmp_path)
        monkeypatch.setattr(rag, "retrieve_hybrid_with_sources", _fake_retrieve)
        history = [("X是什么？", "X是...")]
        runtime = rag._plan_query_runtime(
            SIMPLE_QUERY, None, None, None, DOCS, METAS, history=history,
        )
        evidence = _evidence_for(runtime)
        ctx = qpc.SYNTHETIC_CAPTURE_ISSUER.create_context(
            tmp_path / "capture", chunks,
        )
        cap = qpc.SYNTHETIC_CAPTURE_ISSUER.create_capability(ctx)
        qpc.capture_synthetic_plan(runtime, evidence, cap, METAS, history=history)
        row = json.loads(
            (ctx.output_root / qpc.CAPTURE_FILE_NAME).read_text(encoding="utf-8"),
        )
        assert row["provenance"]["history_sha256"] is not None
        with pytest.warns(UserWarning, match="history"):
            evidences = _replay(ctx)
        assert len(evidences) == 1

    def test_prompt_provenance_drift_warns_only(self, tmp_path, monkeypatch):
        """prompt SHA 漂移 → 只告警不阻断（与 G1-S 既有行为一致）。"""
        ctx, _, _ = _do_capture(tmp_path, monkeypatch)
        monkeypatch.setattr(
            "src.rag_query_rewriter.REWRITE_PROMPT", "CHANGED PROMPT",
        )
        with pytest.warns(UserWarning, match="REWRITE_PROMPT"):
            evidences = _replay(ctx)
        assert len(evidences) == 1


# ═══════════════════════════════════════════════════════════════
# G1-S.2 缺口 1：replay 必须验证当前 index metadata 的完整 chunks 映射
# ═══════════════════════════════════════════════════════════════

class TestReplayMetadataMapping:
    def test_replay_unhit_candidate_metadata_drift_rejected_before_prepare(
            self, tmp_path, monkeypatch):
        """capture 仅命中 chunk_0；replay 前只篡改未命中的 chunk_2 metadata
        → 必须拒绝，且尚未进入 prepare_answer_evidence。"""
        ctx, _, _ = _do_capture(tmp_path, monkeypatch,
                                retrieve=_fake_retrieve_single)
        bad_metas = [dict(m) for m in METAS]
        bad_metas[2]["chunk_id"] = "chunk_2_TAMPERED"

        prepare_calls: list[tuple] = []
        real_prepare = rag.prepare_answer_evidence

        def spy_prepare(*args, **kwargs):
            prepare_calls.append((args, kwargs))
            return real_prepare(*args, **kwargs)

        monkeypatch.setattr(rag, "prepare_answer_evidence", spy_prepare)
        with pytest.raises(ValueError, match="chunk_id"):
            qpc.replay_synthetic_plan(
                qpc.SYNTHETIC_CAPTURE_ISSUER.create_capability(ctx),
                None, None, None, DOCS, bad_metas,
            )
        assert prepare_calls == []  # 校验发生在 prepare 之前

    def test_replay_metadatas_missing_chunk_id_rejected(self, tmp_path, monkeypatch):
        ctx, _, _ = _do_capture(tmp_path, monkeypatch)
        bad_metas = [dict(m) for m in METAS]
        bad_metas[1].pop("chunk_id")
        with pytest.raises(ValueError, match="chunk_id"):
            _replay(ctx, metas=bad_metas)

    def test_replay_metadatas_duplicate_chunk_id_rejected(self, tmp_path, monkeypatch):
        ctx, _, _ = _do_capture(tmp_path, monkeypatch)
        bad_metas = [dict(m) for m in METAS]
        bad_metas[1]["chunk_id"] = "chunk_0"
        with pytest.raises(ValueError, match="duplicate chunk_id"):
            _replay(ctx, metas=bad_metas)

    def test_replay_metadatas_extra_entry_rejected(self, tmp_path, monkeypatch):
        """index metadata 出现 chunks contract 之外的额外条目 → 拒绝。"""
        ctx, _, _ = _do_capture(tmp_path, monkeypatch)
        bad_metas = [dict(m) for m in METAS] + [
            {"chunk_id": "chunk_3", "source_id": "s3",
             "source_name": "d.md", "source": "d.md"},
        ]
        with pytest.raises(ValueError, match="mapping|chunk_id"):
            _replay(ctx, metas=bad_metas)

    def test_replay_metadatas_order_swap_rejected(self, tmp_path, monkeypatch):
        """index metadata 的 chunk_id 顺序与 chunks contract 不一致 → 拒绝。"""
        ctx, _, _ = _do_capture(tmp_path, monkeypatch)
        bad_metas = [dict(m) for m in METAS]
        bad_metas[0]["chunk_id"], bad_metas[1]["chunk_id"] = (
            bad_metas[1]["chunk_id"], bad_metas[0]["chunk_id"],
        )
        with pytest.raises(ValueError, match="mapping"):
            _replay(ctx, metas=bad_metas)


# ═══════════════════════════════════════════════════════════════
# G1-S.2 缺口 2：manifest 原始字节必须强制 LF-only + 字段 fail-closed
# ═══════════════════════════════════════════════════════════════

class TestManifestBytesAndFields:
    def test_manifest_crlf_rejected(self, tmp_path, monkeypatch):
        """只把有效 manifest 的 LF 改为 CRLF（不改任何逻辑字段/self-hash）
        → replay 必须拒绝。"""
        ctx, _, _ = _do_capture(tmp_path, monkeypatch)
        manifest_path = ctx.output_root / qpc.MANIFEST_FILE_NAME
        original = manifest_path.read_bytes()
        assert b"\r" not in original
        crlf = original.replace(b"\n", b"\r\n")
        manifest_path.write_bytes(crlf)
        with pytest.raises(ValueError, match="CR|LF"):
            _replay(ctx)

    def test_manifest_schema_version_tampered_with_recomputed_self_hash_rejected(
            self, tmp_path, monkeypatch):
        """schema_version 篡改 + self-hash 重算 → 值比对仍拒绝。"""
        ctx, _, _ = _do_capture(tmp_path, monkeypatch)
        manifest_path = ctx.output_root / qpc.MANIFEST_FILE_NAME
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        payload["schema_version"] = 999
        payload.pop("manifest_sha256")
        payload["manifest_sha256"] = qpc._sha256_text(
            qpc._canonical_manifest_json(payload),
        )
        manifest_path.write_bytes(
            (qpc._canonical_manifest_json(payload) + "\n").encode("utf-8"),
        )
        with pytest.raises(ValueError, match="schema_version"):
            _replay(ctx)

    def test_manifest_file_field_tampered_with_recomputed_self_hash_rejected(
            self, tmp_path, monkeypatch):
        """manifest.file 篡改 + self-hash 重算 → 值比对仍拒绝。"""
        ctx, _, _ = _do_capture(tmp_path, monkeypatch)
        manifest_path = ctx.output_root / qpc.MANIFEST_FILE_NAME
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        payload["file"] = "other.jsonl"
        payload.pop("manifest_sha256")
        payload["manifest_sha256"] = qpc._sha256_text(
            qpc._canonical_manifest_json(payload),
        )
        manifest_path.write_bytes(
            (qpc._canonical_manifest_json(payload) + "\n").encode("utf-8"),
        )
        with pytest.raises(ValueError, match="file"):
            _replay(ctx)

    def test_manifest_valid_lf_bytes_pass(self, tmp_path, monkeypatch):
        """合规 LF-only manifest（含正确 schema_version/file）replay 通过。"""
        ctx, _, _ = _do_capture(tmp_path, monkeypatch)
        manifest_path = ctx.output_root / qpc.MANIFEST_FILE_NAME
        assert b"\r" not in manifest_path.read_bytes()
        assert len(_replay(ctx)) == 1
