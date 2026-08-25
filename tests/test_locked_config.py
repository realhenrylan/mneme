"""Tests for evaluation.locked_config — P1 离线 locked-config 基础设施。

验证：
- 版本化、确定性、无密钥的 lock 生成/序列化/加载
- fail-closed 校验：版本/指纹/alpha grid/预算/模型漂移拒绝，匹配放行
- CLI：--lock 仅 development + 显式 alpha；holdout 缺锁/不匹配在索引前拒绝
- main(argv=None) 入口的前置校验顺序（prepare_index 不被调用）
"""

import hashlib
import json
from unittest.mock import patch

import pytest

from evaluation.compare import _compute_corpus_hash
from evaluation.locked_config import (
    BUDGET_KEYS,
    LOCKED_CONFIG_VERSION,
    LockedConfigError,
    _safe_display,
    build_locked_config,
    collect_runtime_budgets,
    collect_runtime_models,
    load_locked_config,
    save_locked_config,
    validate_locked_config,
)


# ── Fixtures / helpers ───────────────────────────────────────────────

@pytest.fixture
def dataset_path(tmp_path):
    path = tmp_path / "v1.jsonl"
    row = {
        "id": "c1", "query": "南京面积？", "query_type": "single_fact",
        "language": "zh", "relevant_source_ids": ["doc1.pdf"],
        "relevant_chunks": [{
            "source_id": "doc1.pdf", "chunk_text_snippet": "总面积6587",
            "page": None, "section": None,
        }],
        "acceptable_answer_points": ["6587"], "should_refuse": False,
        "metadata": {"difficulty": "easy"},
    }
    with open(path, "w", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")
    return path


@pytest.fixture
def corpus_dir(tmp_path):
    d = tmp_path / "corpus"
    d.mkdir()
    (d / "doc1.pdf").write_bytes(b"nanjing city area 6587")
    return d


FAKE_INDEX_SHA = "a" * 64
FAKE_KG_SHA = "b" * 64
FAKE_SPLIT_SHA = "c" * 64


def _dataset_split_fingerprint(dataset_path) -> str:
    """按 seed=42 计算 dataset 的真实 split 指纹（与 main() 同口径）。"""
    from evaluation.compare import compute_split_fingerprint, group_aware_split
    from evaluation.schema import load_dataset

    cases = load_dataset(dataset_path)
    dev, holdout = group_aware_split(cases, seed=42)
    return compute_split_fingerprint(dev, holdout)


def _build_lock(dataset_path, corpus_dir, alpha=0.7, arms=("standard",),
                split_fingerprint=None, **overrides):
    if split_fingerprint is None:
        # 默认锁定真实 split 指纹：CLI 集成测试（holdout 放行/--lock 生成）
        # 依赖 lock 与运行时计算的指纹一致
        split_fingerprint = _dataset_split_fingerprint(dataset_path)
    models = collect_runtime_models()
    from evaluation.locked_config import compute_effective_prompt_ids
    from src.rag import REFUSAL_POLICY_BASELINE
    refusal_policy = {arm: REFUSAL_POLICY_BASELINE for arm in arms}
    config = build_locked_config(
        locked_alpha=alpha,
        dataset_name=dataset_path.name,
        dataset_sha256=hashlib.sha256(dataset_path.read_bytes()).hexdigest(),
        corpus_sha256=_compute_corpus_hash(corpus_dir, ["doc1.pdf"]),
        seed=42,
        arms=list(arms),
        embedding_model=models["embedding_model"],
        llm_model=models["llm_model"],
        reranker_mode=models["reranker_mode"],
        reranker_model=models["reranker_model"],
        prompt_id=models["prompt_id"],
        budgets=collect_runtime_budgets(),
        index_sha256=FAKE_INDEX_SHA,
        kg_sha256=None,  # 非图（或 alpha=1.0）时 KG 指纹 not-applicable
        split_fingerprint=split_fingerprint,
        refusal_policy=refusal_policy,
        effective_prompt_ids=compute_effective_prompt_ids(refusal_policy),
    )
    config.update(overrides)
    return config


@pytest.fixture
def lock_path(tmp_path, dataset_path, corpus_dir):
    config = _build_lock(dataset_path, corpus_dir)
    path = tmp_path / "locked-config.json"
    save_locked_config(config, path)
    return path


# ── 生成 / 序列化 / 无密钥 ───────────────────────────────────────────

class TestSerializationDeterminism:
    def test_build_is_deterministic(self, dataset_path, corpus_dir):
        a = _build_lock(dataset_path, corpus_dir)
        b = _build_lock(dataset_path, corpus_dir)
        assert a == b
        assert json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)

    def test_save_is_byte_identical(self, tmp_path, dataset_path, corpus_dir):
        p1 = tmp_path / "l1.json"
        p2 = tmp_path / "l2.json"
        save_locked_config(_build_lock(dataset_path, corpus_dir), p1)
        save_locked_config(_build_lock(dataset_path, corpus_dir), p2)
        assert p1.read_bytes() == p2.read_bytes()

    def test_roundtrip_load(self, lock_path):
        lock = load_locked_config(lock_path)
        assert lock["version"] == LOCKED_CONFIG_VERSION
        assert lock["locked_alpha"] == 0.7
        assert lock["arms"] == ["standard"]

    def test_no_secrets_in_serialized_output(self, tmp_path, dataset_path, corpus_dir):
        path = tmp_path / "l.json"
        save_locked_config(_build_lock(dataset_path, corpus_dir), path)
        text = path.read_text(encoding="utf-8").lower()
        # 注意：'token' 出现在预算字段名 context_token_budget 中（非凭据），
        # 因此只检查凭据形态：URL、userinfo@、sk- 密钥前缀与密码字段。
        for hint in ("://", "@", "sk-", "password", "secret"):
            assert hint not in text, f"lock leaks {hint!r}"

    def test_provenance_explains_source(self, dataset_path, corpus_dir):
        lock = _build_lock(dataset_path, corpus_dir)
        prov = lock["provenance"]
        assert "development" in prov["source"]
        assert "never re-selected from holdout" in prov["locked_alpha_selected_from"]


# ── 加载失败（fail-closed） ──────────────────────────────────────────

class TestLoadRejects:
    def test_unsupported_version(self, lock_path):
        lock = load_locked_config(lock_path)
        lock["version"] = 999
        save_locked_config(lock, lock_path)
        with pytest.raises(LockedConfigError) as exc:
            load_locked_config(lock_path)
        assert any("version" in d for d in exc.value.diffs)

    def test_non_dict_root(self, tmp_path):
        p = tmp_path / "bad.json"
        p.write_text("[1,2,3]", encoding="utf-8")
        with pytest.raises(LockedConfigError):
            load_locked_config(p)

    def test_missing_required_key(self, lock_path):
        lock = load_locked_config(lock_path)
        del lock["seed"]
        save_locked_config(lock, lock_path)
        with pytest.raises(LockedConfigError) as exc:
            load_locked_config(lock_path)
        assert any("seed" in d for d in exc.value.diffs)

    def test_budgets_key_set_drift(self, lock_path):
        lock = load_locked_config(lock_path)
        # 删除一个白名单键 → load 必须拒绝（键集漂移）
        lock["budgets"].pop(BUDGET_KEYS[0])
        save_locked_config(lock, lock_path)
        with pytest.raises(LockedConfigError) as exc:
            load_locked_config(lock_path)
        assert any("budgets" in d for d in exc.value.diffs)

    def test_budgets_extra_key_rejected(self, lock_path):
        lock = load_locked_config(lock_path)
        lock["budgets"]["unknown_param"] = 1
        save_locked_config(lock, lock_path)
        with pytest.raises(LockedConfigError) as exc:
            load_locked_config(lock_path)
        assert any("unknown_param" in d for d in exc.value.diffs)

    def test_locked_alpha_must_be_number(self, lock_path):
        lock = load_locked_config(lock_path)
        lock["locked_alpha"] = "0.7"
        save_locked_config(lock, lock_path)
        with pytest.raises(LockedConfigError):
            load_locked_config(lock_path)

    def test_index_sha256_none_rejected(self, lock_path):
        """index=None 的旧式未锁定 config 在 load 阶段必须拒绝（任何臂不得绕过）。"""
        lock = load_locked_config(lock_path)
        lock["index_sha256"] = None
        save_locked_config(lock, lock_path)
        with pytest.raises(LockedConfigError) as exc:
            load_locked_config(lock_path)
        assert any("index_sha256" in d for d in exc.value.diffs)

    def test_index_sha256_missing_key_rejected(self, lock_path):
        lock = load_locked_config(lock_path)
        del lock["index_sha256"]
        save_locked_config(lock, lock_path)
        with pytest.raises(LockedConfigError) as exc:
            load_locked_config(lock_path)
        assert any("index_sha256" in d for d in exc.value.diffs)

    def test_index_sha256_bad_format_rejected(self, lock_path):
        """坏格式：过短 / 非 hex / 大写 —— 一律拒绝且只报字段名。"""
        lock = load_locked_config(lock_path)
        lock["index_sha256"] = "abc"
        save_locked_config(lock, lock_path)
        with pytest.raises(LockedConfigError) as exc:
            load_locked_config(lock_path)
        assert any("index_sha256" in d for d in exc.value.diffs)

        lock["index_sha256"] = "z" * 64
        save_locked_config(lock, lock_path)
        with pytest.raises(LockedConfigError):
            load_locked_config(lock_path)

        lock["index_sha256"] = "A" * 64
        save_locked_config(lock, lock_path)
        with pytest.raises(LockedConfigError):
            load_locked_config(lock_path)

    def test_kg_sha256_bad_format_rejected_but_none_allowed(self, lock_path):
        """kg 允许 None（not-applicable），但坏格式必须拒绝。"""
        lock = load_locked_config(lock_path)
        lock["kg_sha256"] = "not-a-hash"
        save_locked_config(lock, lock_path)
        with pytest.raises(LockedConfigError) as exc:
            load_locked_config(lock_path)
        assert any("kg_sha256" in d for d in exc.value.diffs)


# ── 生成侧指纹强制（build 拒绝 null/坏格式，不写未锁定 lock） ─────────

class TestBuildFingerprintEnforcement:
    def test_index_none_rejected(self, dataset_path, corpus_dir):
        models = collect_runtime_models()
        with pytest.raises(ValueError) as exc:
            build_locked_config(
                locked_alpha=0.7, dataset_name="v1",
                dataset_sha256="a" * 64, corpus_sha256="b" * 64,
                seed=42, arms=["standard"],
                embedding_model=models["embedding_model"],
                llm_model=models["llm_model"],
                reranker_mode=models["reranker_mode"],
                reranker_model=models["reranker_model"],
                prompt_id=models["prompt_id"],
                budgets=collect_runtime_budgets(),
                index_sha256=None, kg_sha256=None,
                split_fingerprint=FAKE_SPLIT_SHA,
            )
        assert "index_sha256" in str(exc.value)

    def test_index_bad_format_rejected(self, dataset_path, corpus_dir):
        models = collect_runtime_models()
        with pytest.raises(ValueError):
            build_locked_config(
                locked_alpha=0.7, dataset_name="v1",
                dataset_sha256="a" * 64, corpus_sha256="b" * 64,
                seed=42, arms=["standard"],
                embedding_model=models["embedding_model"],
                llm_model=models["llm_model"],
                reranker_mode=models["reranker_mode"],
                reranker_model=models["reranker_model"],
                prompt_id=models["prompt_id"],
                budgets=collect_runtime_budgets(),
                index_sha256="x" * 64, kg_sha256=None,
                split_fingerprint=FAKE_SPLIT_SHA,
            )

    def test_graph_alpha_below_one_requires_kg(self, dataset_path, corpus_dir):
        """图 C + alpha<1：kg=None 必须拒绝（不得写未锁定的 lock）。"""
        models = collect_runtime_models()
        arms = ["standard", "standard-rerank", "graph-rerank"]
        with pytest.raises(ValueError) as exc:
            build_locked_config(
                locked_alpha=0.7, dataset_name="v1",
                dataset_sha256="a" * 64, corpus_sha256="b" * 64,
                seed=42, arms=arms,
                embedding_model=models["embedding_model"],
                llm_model=models["llm_model"],
                reranker_mode=models["reranker_mode"],
                reranker_model=models["reranker_model"],
                prompt_id=models["prompt_id"],
                budgets=collect_runtime_budgets(),
                index_sha256=FAKE_INDEX_SHA, kg_sha256=None,
                split_fingerprint=FAKE_SPLIT_SHA,
                refusal_policy={arm: "baseline" for arm in arms},
                effective_prompt_ids={arm: "f" * 64 for arm in arms},
            )
        assert "kg_sha256" in str(exc.value)

    def test_graph_alpha_below_one_kg_bad_format_rejected(self, dataset_path, corpus_dir):
        models = collect_runtime_models()
        arms = ["standard", "standard-rerank", "graph-rerank"]
        with pytest.raises(ValueError):
            build_locked_config(
                locked_alpha=0.7, dataset_name="v1",
                dataset_sha256="a" * 64, corpus_sha256="b" * 64,
                seed=42, arms=arms,
                embedding_model=models["embedding_model"],
                llm_model=models["llm_model"],
                reranker_mode=models["reranker_mode"],
                reranker_model=models["reranker_model"],
                prompt_id=models["prompt_id"],
                budgets=collect_runtime_budgets(),
                index_sha256=FAKE_INDEX_SHA, kg_sha256="bad",
                split_fingerprint=FAKE_SPLIT_SHA,
            )

    def test_non_graph_kg_none_allowed(self, dataset_path, corpus_dir):
        """非图实验 kg=None 为 not-applicable，允许生成。"""
        lock = _build_lock(dataset_path, corpus_dir)
        assert lock["kg_sha256"] is None
        assert lock["index_sha256"] == FAKE_INDEX_SHA

    def test_graph_alpha_one_kg_none_allowed(self, dataset_path, corpus_dir):
        """图臂 alpha=1.0 时 C 不经过 Graph 通道，kg=None 允许。"""
        lock = _build_lock(
            dataset_path, corpus_dir, alpha=1.0,
            arms=("standard", "standard-rerank", "graph-rerank"),
        )
        assert lock["kg_sha256"] is None

    def test_kg_optional_when_supplied_valid(self, dataset_path, corpus_dir):
        """非图实验也可显式锁定 kg 指纹（64 hex 接受）。"""
        models = collect_runtime_models()
        lock = build_locked_config(
            locked_alpha=0.7, dataset_name="v1",
            dataset_sha256="a" * 64, corpus_sha256="b" * 64,
            seed=42, arms=["standard"],
            embedding_model=models["embedding_model"],
            llm_model=models["llm_model"],
            reranker_mode=models["reranker_mode"],
            reranker_model=models["reranker_model"],
            prompt_id=models["prompt_id"],
            budgets=collect_runtime_budgets(),
            index_sha256=FAKE_INDEX_SHA, kg_sha256=FAKE_KG_SHA,
            split_fingerprint=FAKE_SPLIT_SHA,
            refusal_policy={"standard": "baseline"},
            effective_prompt_ids={"standard": "f" * 64},
        )
        assert lock["kg_sha256"] == FAKE_KG_SHA


# ── split_fingerprint（split 确定性锁定） ─────────────────────────────

class TestSplitFingerprintLocking:
    """split 指纹锁定：build 必填 / load 格式校验（legacy 兼容）/
    validate fail-closed 比对。"""

    def test_build_requires_split_fingerprint(self, dataset_path, corpus_dir):
        """缺 split_fingerprint → ValueError（新锁必须锁定 split）。"""
        models = collect_runtime_models()
        with pytest.raises(ValueError) as exc:
            build_locked_config(
                locked_alpha=0.7, dataset_name="v1",
                dataset_sha256="a" * 64, corpus_sha256="b" * 64,
                seed=42, arms=["standard"],
                embedding_model=models["embedding_model"],
                llm_model=models["llm_model"],
                reranker_mode=models["reranker_mode"],
                reranker_model=models["reranker_model"],
                prompt_id=models["prompt_id"],
                budgets=collect_runtime_budgets(),
                index_sha256=FAKE_INDEX_SHA, kg_sha256=None,
            )
        assert "split_fingerprint" in str(exc.value)

    def test_build_rejects_bad_format(self, dataset_path, corpus_dir):
        """坏格式（非 64 hex）→ ValueError。"""
        models = collect_runtime_models()
        with pytest.raises(ValueError) as exc:
            build_locked_config(
                locked_alpha=0.7, dataset_name="v1",
                dataset_sha256="a" * 64, corpus_sha256="b" * 64,
                seed=42, arms=["standard"],
                embedding_model=models["embedding_model"],
                llm_model=models["llm_model"],
                reranker_mode=models["reranker_mode"],
                reranker_model=models["reranker_model"],
                prompt_id=models["prompt_id"],
                budgets=collect_runtime_budgets(),
                index_sha256=FAKE_INDEX_SHA, kg_sha256=None,
                split_fingerprint="not-a-hash",
            )
        assert "split_fingerprint" in str(exc.value)

    def test_build_writes_fingerprint(self, dataset_path, corpus_dir):
        """合法指纹写入 lock（确定性键序）。"""
        lock = _build_lock(dataset_path, corpus_dir)
        assert lock["split_fingerprint"] == _dataset_split_fingerprint(dataset_path)

    def test_load_accepts_legacy_lock_without_fingerprint(
        self, tmp_path, dataset_path, corpus_dir,
    ):
        """旧锁（无 split_fingerprint 键）可加载（历史审计兼容）。"""
        lock = _build_lock(dataset_path, corpus_dir)
        lock.pop("split_fingerprint")
        path = tmp_path / "legacy.json"
        save_locked_config(lock, path)
        loaded = load_locked_config(path)
        assert "split_fingerprint" not in loaded

    def test_load_rejects_bad_format(self, tmp_path, dataset_path, corpus_dir):
        """存在但坏格式 → LockedConfigError。"""
        lock = _build_lock(dataset_path, corpus_dir)
        lock["split_fingerprint"] = "not-a-hash"
        path = tmp_path / "bad.json"
        save_locked_config(lock, path)
        with pytest.raises(LockedConfigError) as exc:
            load_locked_config(path)
        assert any("split_fingerprint" in d for d in exc.value.diffs)

    def test_validate_match_passes(self, lock_path, dataset_path, corpus_dir):
        """运行时指纹与锁定一致 → 无差异。"""
        lock = load_locked_config(lock_path)
        runtime = _full_runtime_values(dataset_path, corpus_dir)
        runtime["split_fingerprint"] = lock["split_fingerprint"]
        diffs = validate_locked_config(lock, **runtime)
        assert diffs == []

    def test_validate_mismatch_rejected(self, lock_path, dataset_path, corpus_dir):
        """dataset/seed/split 算法漂移（指纹不等）→ 差异列出字段名。"""
        lock = load_locked_config(lock_path)
        wrong = "d" * 64
        assert wrong != lock["split_fingerprint"]
        diffs = validate_locked_config(
            lock, **_full_runtime_values(dataset_path, corpus_dir),
            split_fingerprint=wrong,
        )
        assert any("split_fingerprint" in d for d in diffs)

    def test_validate_locked_but_not_computable_rejected(
        self, lock_path, dataset_path, corpus_dir,
    ):
        """锁已锁定但运行时不可得（None）→ 拒绝（fail-closed）。"""
        lock = load_locked_config(lock_path)
        diffs = validate_locked_config(lock, split_fingerprint=None)
        assert any("split_fingerprint" in d for d in diffs)

    def test_validate_legacy_lock_without_fp_skipped(
        self, lock_path, dataset_path, corpus_dir,
    ):
        """旧锁无该键 → 跳过比对（提供或不提供都放行）。"""
        lock = load_locked_config(lock_path)
        lock.pop("split_fingerprint")
        diffs = validate_locked_config(
            lock, **_full_runtime_values(dataset_path, corpus_dir),
        )
        assert diffs == []
        diffs = validate_locked_config(
            lock, **_full_runtime_values(dataset_path, corpus_dir),
            split_fingerprint="d" * 64,
        )
        assert diffs == []


# ── 校验：匹配放行 / 漂移拒绝 ────────────────────────────────────────

def _full_runtime_values(dataset_path, corpus_dir, alpha_grid=None):
    models = collect_runtime_models()
    return dict(
        dataset_name=dataset_path.name,
        dataset_sha256=hashlib.sha256(dataset_path.read_bytes()).hexdigest(),
        corpus_sha256=_compute_corpus_hash(corpus_dir, ["doc1.pdf"]),
        seed=42,
        arms=["standard"],
        alpha_grid=alpha_grid,
        embedding_model=models["embedding_model"],
        llm_model=models["llm_model"],
        reranker_mode=models["reranker_mode"],
        reranker_model=models["reranker_model"],
        prompt_id=models["prompt_id"],
        budgets=collect_runtime_budgets(),
    )


class TestValidateMatching:
    def test_full_match_passes(self, lock_path, dataset_path, corpus_dir):
        lock = load_locked_config(lock_path)
        diffs = validate_locked_config(lock, **_full_runtime_values(dataset_path, corpus_dir))
        assert diffs == []

    def test_alpha_grid_none_passes(self, lock_path, dataset_path, corpus_dir):
        """未提供 grid（None）表示采用锁定 alpha，放行。"""
        lock = load_locked_config(lock_path)
        diffs = validate_locked_config(
            lock, **_full_runtime_values(dataset_path, corpus_dir, alpha_grid=None),
        )
        assert diffs == []

    def test_alpha_grid_equal_locked_passes(self, lock_path, dataset_path, corpus_dir):
        lock = load_locked_config(lock_path)
        diffs = validate_locked_config(
            lock, **_full_runtime_values(dataset_path, corpus_dir, alpha_grid=[0.7]),
        )
        assert diffs == []

    def test_non_graph_kg_none_is_applicable_skipped(self, lock_path, dataset_path, corpus_dir):
        """非图（arms=standard）时 kg_sha256=None 为 not-applicable，后验放行。"""
        lock = load_locked_config(lock_path)
        assert lock["kg_sha256"] is None
        assert lock["index_sha256"] == FAKE_INDEX_SHA  # index 始终锁定
        # 后验：index 指纹匹配、kg 未锁定 → 无差异
        diffs = validate_locked_config(
            lock, index_sha256=FAKE_INDEX_SHA, kg_sha256=None,
        )
        assert diffs == []

    def test_graph_alpha1_kg_none_not_applicable(self, lock_path, dataset_path, corpus_dir):
        """图臂 alpha=1.0 时 C 不经过 Graph 通道，kg=None 允许放行。"""
        lock = _build_lock(
            dataset_path, corpus_dir, alpha=1.0,
            arms=("standard", "standard-rerank", "graph-rerank"),
        )
        runtime = _full_runtime_values(dataset_path, corpus_dir)
        runtime["arms"] = ["standard", "standard-rerank", "graph-rerank"]
        runtime["alpha_grid"] = [1.0]
        diffs = validate_locked_config(lock, **runtime)
        assert diffs == []


class TestValidateDriftRejected:
    def test_alpha_grid_drift(self, lock_path, dataset_path, corpus_dir):
        lock = load_locked_config(lock_path)
        diffs = validate_locked_config(
            lock, **_full_runtime_values(dataset_path, corpus_dir, alpha_grid=[0.5, 0.7]),
        )
        assert any(d.startswith("alpha") for d in diffs)

    def test_dataset_hash_drift(self, lock_path, dataset_path, corpus_dir):
        lock = load_locked_config(lock_path)
        runtime = _full_runtime_values(dataset_path, corpus_dir)
        runtime["dataset_sha256"] = "deadbeef" * 8
        diffs = validate_locked_config(lock, **runtime)
        assert any(d.startswith("dataset_sha256") for d in diffs)

    def test_corpus_hash_drift(self, lock_path, dataset_path, corpus_dir):
        lock = load_locked_config(lock_path)
        runtime = _full_runtime_values(dataset_path, corpus_dir)
        runtime["corpus_sha256"] = "deadbeef" * 8
        diffs = validate_locked_config(lock, **runtime)
        assert any(d.startswith("corpus_sha256") for d in diffs)

    def test_seed_drift(self, lock_path, dataset_path, corpus_dir):
        lock = load_locked_config(lock_path)
        runtime = _full_runtime_values(dataset_path, corpus_dir)
        runtime["seed"] = 43
        diffs = validate_locked_config(lock, **runtime)
        assert any(d.startswith("seed") for d in diffs)

    def test_arms_drift(self, lock_path, dataset_path, corpus_dir):
        lock = load_locked_config(lock_path)
        runtime = _full_runtime_values(dataset_path, corpus_dir)
        runtime["arms"] = ["standard", "standard-rerank"]
        diffs = validate_locked_config(lock, **runtime)
        assert any(d.startswith("arms") for d in diffs)

    def test_model_drift(self, lock_path, dataset_path, corpus_dir):
        lock = load_locked_config(lock_path)
        runtime = _full_runtime_values(dataset_path, corpus_dir)
        runtime["llm_model"] = "different-model"
        diffs = validate_locked_config(lock, **runtime)
        assert any(d.startswith("llm_model") for d in diffs)

    def test_prompt_id_drift(self, lock_path, dataset_path, corpus_dir):
        lock = load_locked_config(lock_path)
        runtime = _full_runtime_values(dataset_path, corpus_dir)
        runtime["prompt_id"] = "0" * 64
        diffs = validate_locked_config(lock, **runtime)
        assert any(d.startswith("prompt_id") for d in diffs)

    def test_budget_drift(self, lock_path, dataset_path, corpus_dir):
        lock = load_locked_config(lock_path)
        runtime = _full_runtime_values(dataset_path, corpus_dir)
        runtime["budgets"] = dict(runtime["budgets"])
        runtime["budgets"]["fusion_rrf_k"] = 30
        diffs = validate_locked_config(lock, **runtime)
        assert any(d.startswith("budgets.fusion_rrf_k") for d in diffs)

    def test_locked_index_hash_but_not_computable(self, lock_path, dataset_path, corpus_dir):
        """lock 锁定了 index 指纹但运行时不可得（None）→ 拒绝（fail-closed）。"""
        lock = load_locked_config(lock_path)
        lock["index_sha256"] = "a" * 64
        diffs = validate_locked_config(lock, index_sha256=None, kg_sha256=None)
        assert any("index_sha256" in d for d in diffs)

    def test_index_hash_mismatch(self, lock_path, dataset_path, corpus_dir):
        lock = load_locked_config(lock_path)
        lock["index_sha256"] = "a" * 64
        diffs = validate_locked_config(
            lock, index_sha256="b" * 64, kg_sha256=None,
        )
        assert any(d.startswith("index_sha256") for d in diffs)

    def test_locked_kg_hash_but_no_kg_at_runtime(self, lock_path, dataset_path, corpus_dir):
        lock = load_locked_config(lock_path)
        lock["kg_sha256"] = "a" * 64
        diffs = validate_locked_config(
            lock, index_sha256=None, kg_sha256=None,
        )
        assert any("kg_sha256" in d for d in diffs)

    def test_graph_alpha_below_one_missing_kg_rejected_at_precheck(
        self, lock_path, dataset_path, corpus_dir,
    ):
        """预检（arms 已知）：图 C + alpha<1 时 kg=None 必须拒绝。

        这是 fail-closed 缺口回归：不得让图 holdout 以 null KG 指纹通过。
        构造方式：非图生成的 lock（kg=None）被手工改成图 arms ——
        模拟旧/伪造 config 绕过生成侧校验，验证 validate 预检兜底。
        """
        lock = _build_lock(dataset_path, corpus_dir)  # arms=standard, kg=None
        lock["arms"] = ["graph-rerank", "standard", "standard-rerank"]
        assert lock["kg_sha256"] is None
        runtime = _full_runtime_values(dataset_path, corpus_dir)
        runtime["arms"] = ["standard", "standard-rerank", "graph-rerank"]
        diffs = validate_locked_config(lock, **runtime)
        assert any("kg_sha256" in d for d in diffs)

    def test_graph_alpha_below_one_with_kg_locked_passes_precheck(
        self, lock_path, dataset_path, corpus_dir,
    ):
        """图 C + alpha<1 且 kg 已锁定：预检放行（后验指纹另行比对）。"""
        lock = _build_lock(dataset_path, corpus_dir)  # arms=standard, kg=None
        lock["arms"] = ["graph-rerank", "standard", "standard-rerank"]
        lock["kg_sha256"] = FAKE_KG_SHA
        runtime = _full_runtime_values(dataset_path, corpus_dir)
        runtime["arms"] = ["standard", "standard-rerank", "graph-rerank"]
        diffs = validate_locked_config(lock, **runtime)
        assert diffs == []

    def test_diffs_name_fields_not_values(self, lock_path, dataset_path, corpus_dir):
        """错误消息指出差异字段；值经防御性脱敏（不泄露 secrets）。"""
        assert _safe_display("sk-12345678") == "sk-12345678"  # 无敏感词原样
        assert _safe_display("secret-token-abc") == "***REDACTED***"
        lock = load_locked_config(lock_path)
        runtime = _full_runtime_values(dataset_path, corpus_dir)
        runtime["dataset_sha256"] = "x" * 64
        diffs = validate_locked_config(lock, **runtime)
        joined = "\n".join(diffs)
        assert "dataset_sha256" in joined
        assert "deadbeef" not in joined  # 只列字段名，不打印整个值


# ── CLI：--lock 生成 ─────────────────────────────────────────────────

def _main_mock_patches():
    return (
        patch("evaluation.compare.save_retrieval_results_by_alpha"),
        patch("evaluation.compare.run_retrieval_grid"),
        patch("evaluation.compare.build_query_plan_cache"),
        patch("evaluation.compare.validate_reranker"),
        patch("evaluation.compare.build_ground_truth_map"),
        patch("src.rag.prepare_index"),
    )


def _set_main_mocks(mock_prepare, mock_gt, mock_val, mock_cache, mock_grid, mock_save):
    mock_prepare.return_value = (None, None, None, [], [])
    mock_gt.return_value = []
    mock_val.return_value = None
    mock_cache.return_value = {}
    mock_grid.return_value = []  # main 尾部对空结果有 guard


def _run_main(argv):
    import evaluation.compare as compare_mod
    return compare_mod.main(argv)


class TestCliLockGeneration:
    @patch("evaluation.compare.save_retrieval_results_by_alpha")
    @patch("evaluation.compare.run_retrieval_grid")
    @patch("evaluation.compare.build_query_plan_cache")
    @patch("evaluation.compare.validate_reranker")
    @patch("evaluation.compare.build_ground_truth_map")
    @patch("src.rag.prepare_index")
    @patch("evaluation.compare._index_snapshot_sha256", return_value=FAKE_INDEX_SHA)
    def test_lock_writes_config(
        self, mock_index_sha, mock_prepare, mock_gt, mock_val, mock_cache,
        mock_grid, mock_save, dataset_path, corpus_dir, tmp_path,
    ):
        """--lock --alpha 0.7 --split development 生成 locked-config.json。

        快照以非空可控假指纹注入（不把 None 当成功路径）。
        """
        _set_main_mocks(mock_prepare, mock_gt, mock_val, mock_cache, mock_grid, mock_save)
        out = tmp_path / "locked"
        rc = _run_main([
            "--dataset", str(dataset_path),
            "--corpus-dir", str(corpus_dir),
            "--arms", "standard",
            "--split", "development",
            "--lock", "--alpha", "0.7",
            "--output", str(out),
        ])
        assert rc == 0
        mock_index_sha.assert_called_once()
        lock_file = out / "locked-config.json"
        assert lock_file.exists()
        lock = json.loads(lock_file.read_text(encoding="utf-8"))
        assert lock["locked_alpha"] == 0.7
        assert lock["index_sha256"] == FAKE_INDEX_SHA  # index 指纹被锁定
        assert lock["kg_sha256"] is None  # 非图：not-applicable
        # split 指纹被锁定（完整 64 位 hex，与当前 dataset 的 split 一致）
        split_fp = lock["split_fingerprint"]
        assert len(split_fp) == 64
        assert all(c in "0123456789abcdef" for c in split_fp)
        assert split_fp == _dataset_split_fingerprint(dataset_path)
        assert lock["dataset_sha256"] == hashlib.sha256(dataset_path.read_bytes()).hexdigest()
        # 生成后 manifest 记录 config_sha256（args.config 被设置）
        call_kwargs = mock_save.call_args_list[-1].kwargs
        assert call_kwargs["config_path"] == lock_file

    @patch("evaluation.compare.save_retrieval_results_by_alpha")
    @patch("evaluation.compare.run_retrieval_grid")
    @patch("evaluation.compare.build_query_plan_cache")
    @patch("evaluation.compare.validate_reranker")
    @patch("evaluation.compare.build_ground_truth_map")
    @patch("src.rag.prepare_index")
    def test_lock_fails_when_index_snapshot_uncomputable(
        self, mock_prepare, mock_gt, mock_val, mock_cache, mock_grid, mock_save,
        dataset_path, corpus_dir, tmp_path,
    ):
        """快照无法计算（collection 不可读 → None）时明确失败且不写 lock。"""
        _set_main_mocks(mock_prepare, mock_gt, mock_val, mock_cache, mock_grid, mock_save)
        out = tmp_path / "locked"
        rc = _run_main([
            "--dataset", str(dataset_path),
            "--corpus-dir", str(corpus_dir),
            "--arms", "standard",
            "--split", "development",
            "--lock", "--alpha", "0.7",
            "--output", str(out),
        ])
        assert rc == 1
        assert not (out / "locked-config.json").exists()
        mock_save.assert_not_called()

    @patch("evaluation.compare.save_retrieval_results_by_alpha")
    @patch("evaluation.compare.run_retrieval_grid")
    @patch("evaluation.compare.build_query_plan_cache")
    @patch("evaluation.compare.validate_reranker")
    @patch("evaluation.compare.build_ground_truth_map")
    @patch("src.rag.prepare_index")
    def test_lock_requires_explicit_alpha(
        self, mock_prepare, mock_gt, mock_val, mock_cache, mock_grid, mock_save,
        dataset_path, corpus_dir, tmp_path,
    ):
        """--lock 缺 --alpha → 拒绝，且索引工作未开始。"""
        _set_main_mocks(mock_prepare, mock_gt, mock_val, mock_cache, mock_grid, mock_save)
        rc = _run_main([
            "--dataset", str(dataset_path),
            "--corpus-dir", str(corpus_dir),
            "--arms", "standard",
            "--split", "development",
            "--lock",
            "--output", str(tmp_path / "out"),
        ])
        assert rc == 1
        mock_prepare.assert_not_called()

    @patch("evaluation.compare.save_retrieval_results_by_alpha")
    @patch("evaluation.compare.run_retrieval_grid")
    @patch("evaluation.compare.build_query_plan_cache")
    @patch("evaluation.compare.validate_reranker")
    @patch("evaluation.compare.build_ground_truth_map")
    @patch("src.rag.prepare_index")
    def test_lock_rejects_non_development_split(
        self, mock_prepare, mock_gt, mock_val, mock_cache, mock_grid, mock_save,
        dataset_path, corpus_dir, tmp_path,
    ):
        """--lock 仅允许 development；holdout 生成被拒绝。"""
        _set_main_mocks(mock_prepare, mock_gt, mock_val, mock_cache, mock_grid, mock_save)
        rc = _run_main([
            "--dataset", str(dataset_path),
            "--corpus-dir", str(corpus_dir),
            "--arms", "standard",
            "--split", "holdout",
            "--lock", "--alpha", "0.7",
            "--output", str(tmp_path / "out"),
        ])
        assert rc == 1
        mock_prepare.assert_not_called()


# ── CLI：holdout 前置校验 ────────────────────────────────────────────

class TestCliHoldoutValidation:
    @patch("evaluation.compare.save_retrieval_results_by_alpha")
    @patch("evaluation.compare.run_retrieval_grid")
    @patch("evaluation.compare.build_query_plan_cache")
    @patch("evaluation.compare.validate_reranker")
    @patch("evaluation.compare.build_ground_truth_map")
    @patch("src.rag.prepare_index")
    def test_holdout_without_config_rejected_before_index(
        self, mock_prepare, mock_gt, mock_val, mock_cache, mock_grid, mock_save,
        dataset_path, corpus_dir, tmp_path,
    ):
        """holdout 缺 --config → 拒绝，且 prepare_index 未被调用。"""
        _set_main_mocks(mock_prepare, mock_gt, mock_val, mock_cache, mock_grid, mock_save)
        rc = _run_main([
            "--dataset", str(dataset_path),
            "--corpus-dir", str(corpus_dir),
            "--arms", "standard",
            "--split", "holdout",
            "--output", str(tmp_path / "out"),
        ])
        assert rc == 1
        mock_prepare.assert_not_called()

    @patch("evaluation.compare.save_retrieval_results_by_alpha")
    @patch("evaluation.compare.run_retrieval_grid")
    @patch("evaluation.compare.build_query_plan_cache")
    @patch("evaluation.compare.validate_reranker")
    @patch("evaluation.compare.build_ground_truth_map")
    @patch("src.rag.prepare_index")
    def test_holdout_mismatched_config_rejected_before_index(
        self, mock_prepare, mock_gt, mock_val, mock_cache, mock_grid, mock_save,
        dataset_path, corpus_dir, tmp_path,
    ):
        """holdout + alpha 漂移的 config → 拒绝，索引未开始。"""
        _set_main_mocks(mock_prepare, mock_gt, mock_val, mock_cache, mock_grid, mock_save)
        drift = tmp_path / "drift.json"
        save_locked_config(
            _build_lock(dataset_path, corpus_dir, alpha=0.5), drift,
        )
        rc = _run_main([
            "--dataset", str(dataset_path),
            "--corpus-dir", str(corpus_dir),
            "--arms", "standard",
            "--split", "holdout",
            "--config", str(drift),
            "--alpha-grid", "0.7",
            "--output", str(tmp_path / "out"),
        ])
        assert rc == 1
        mock_prepare.assert_not_called()

    @patch("evaluation.compare.save_retrieval_results_by_alpha")
    @patch("evaluation.compare.run_retrieval_grid")
    @patch("evaluation.compare.build_query_plan_cache")
    @patch("evaluation.compare.validate_reranker")
    @patch("evaluation.compare.build_ground_truth_map")
    @patch("src.rag.prepare_index")
    def test_holdout_split_fingerprint_mismatch_rejected_before_index(
        self, mock_prepare, mock_gt, mock_val, mock_cache, mock_grid,
        mock_save, dataset_path, corpus_dir, tmp_path,
    ):
        """lock 的 split_fingerprint 与当前 split 不一致 → 索引前拒绝。

        构造：lock 锁定错误指纹（模拟 dataset/seed/split 算法漂移），
        main 必须在任何索引/LLM 工作前 fail-closed 拒绝。
        """
        _set_main_mocks(mock_prepare, mock_gt, mock_val, mock_cache, mock_grid, mock_save)
        forged = tmp_path / "forged-split.json"
        save_locked_config(
            _build_lock(dataset_path, corpus_dir,
                        split_fingerprint=FAKE_SPLIT_SHA),
            forged,
        )
        rc = _run_main([
            "--dataset", str(dataset_path),
            "--corpus-dir", str(corpus_dir),
            "--arms", "standard",
            "--split", "holdout",
            "--config", str(forged),
            "--output", str(tmp_path / "out"),
        ])
        assert rc == 1
        mock_prepare.assert_not_called()

    @patch("evaluation.compare.save_retrieval_results_by_alpha")
    @patch("evaluation.compare.run_retrieval_grid")
    @patch("evaluation.compare.build_query_plan_cache")
    @patch("evaluation.compare.validate_reranker")
    @patch("evaluation.compare.build_ground_truth_map")
    @patch("src.rag.prepare_index")
    @patch("evaluation.compare._index_snapshot_sha256", return_value=FAKE_INDEX_SHA)
    def test_holdout_matching_config_proceeds_to_index(
        self, mock_index_sha, mock_prepare, mock_gt, mock_val, mock_cache,
        mock_grid, mock_save, dataset_path, corpus_dir, lock_path, tmp_path,
    ):
        """holdout + 匹配 config（含 index 指纹）→ 放行到索引构建。"""
        _set_main_mocks(mock_prepare, mock_gt, mock_val, mock_cache, mock_grid, mock_save)
        rc = _run_main([
            "--dataset", str(dataset_path),
            "--corpus-dir", str(corpus_dir),
            "--arms", "standard",
            "--split", "holdout",
            "--config", str(lock_path),
            "--output", str(tmp_path / "out"),
        ])
        assert rc == 0
        mock_prepare.assert_called_once()
        # 后验 index 指纹参与比对（与 lock 一致 → 放行）
        mock_index_sha.assert_called_once()
        # 锁定 alpha 传入 query plan cache（grid 未提供 → 采用锁定值）
        mock_cache.assert_called_once()
        assert mock_cache.call_args.kwargs["alpha_values"] == [0.7]

    @patch("evaluation.compare.save_retrieval_results_by_alpha")
    @patch("evaluation.compare.run_retrieval_grid")
    @patch("evaluation.compare.build_query_plan_cache")
    @patch("evaluation.compare.validate_reranker")
    @patch("evaluation.compare.build_ground_truth_map")
    @patch("src.rag.prepare_index")
    def test_holdout_graph_alpha_below_one_missing_kg_rejected_before_index(
        self, mock_prepare, mock_gt, mock_val, mock_cache, mock_grid, mock_save,
        dataset_path, corpus_dir, tmp_path,
    ):
        """图 C + alpha<1 + kg=None 的 config → 预检拒绝，索引未开始。

        构造：非图生成的 lock 手工改成图 arms（模拟绕过生成侧的伪造
        config），验证 main 预检兜底。
        """
        _set_main_mocks(mock_prepare, mock_gt, mock_val, mock_cache, mock_grid, mock_save)
        forged = tmp_path / "forged.json"
        lock = _build_lock(dataset_path, corpus_dir)  # arms=standard, kg=None
        lock["arms"] = ["graph-rerank", "standard", "standard-rerank"]
        save_locked_config(lock, forged)
        rc = _run_main([
            "--dataset", str(dataset_path),
            "--corpus-dir", str(corpus_dir),
            "--arms", "standard", "standard-rerank", "graph-rerank",
            "--split", "holdout",
            "--config", str(forged),
            "--output", str(tmp_path / "out"),
        ])
        assert rc == 1
        mock_prepare.assert_not_called()

    @patch("evaluation.compare.save_retrieval_results_by_alpha")
    @patch("evaluation.compare.run_retrieval_grid")
    @patch("evaluation.compare.build_query_plan_cache")
    @patch("evaluation.compare.validate_reranker")
    @patch("evaluation.compare.build_ground_truth_map")
    @patch("src.rag.prepare_index")
    def test_main_argv_none_holdout_without_config_rejected(
        self, mock_prepare, mock_gt, mock_val, mock_cache, mock_grid, mock_save,
        dataset_path, corpus_dir, tmp_path,
    ):
        """main(argv=None) 使用 sys.argv[1:]；holdout 缺锁在前置阶段拒绝。"""
        _set_main_mocks(mock_prepare, mock_gt, mock_val, mock_cache, mock_grid, mock_save)
        with patch("sys.argv", [
            "compare.py",
            "--dataset", str(dataset_path),
            "--corpus-dir", str(corpus_dir),
            "--arms", "standard",
            "--split", "holdout",
            "--output", str(tmp_path / "out"),
        ]):
            import evaluation.compare as compare_mod
            rc = compare_mod.main(argv=None)
        assert rc == 1
        mock_prepare.assert_not_called()


# ── arm_selector_policy（per-arm selector 消融锁定） ──────────────────

class TestArmSelectorPolicy:
    """per-arm selector policy 锁定：生成/加载/校验（S0/S3 防漂移）。"""

    def test_build_with_policy_writes_field(self, dataset_path, corpus_dir):
        """build_locked_config 显式记录 arm_selector_policy。"""
        models = collect_runtime_models()
        config = build_locked_config(
            locked_alpha=1.0,
            dataset_name=dataset_path.name,
            dataset_sha256=hashlib.sha256(dataset_path.read_bytes()).hexdigest(),
            corpus_sha256=_compute_corpus_hash(corpus_dir, ["doc1.pdf"]),
            seed=42,
            arms=["selector-unlimited", "selector-cap3"],
            embedding_model=models["embedding_model"],
            llm_model=models["llm_model"],
            reranker_mode="none",
            reranker_model=models["reranker_model"],
            prompt_id=models["prompt_id"],
            budgets=collect_runtime_budgets(),
            index_sha256=FAKE_INDEX_SHA,
            kg_sha256=None,
            split_fingerprint=FAKE_SPLIT_SHA,
            refusal_policy={"selector-unlimited": "baseline",
                            "selector-cap3": "baseline"},
            effective_prompt_ids={"selector-unlimited": "f" * 64,
                                  "selector-cap3": "e" * 64},
            arm_selector_policy={
                "selector-unlimited": None,
                "selector-cap3": 3,
            },
        )
        assert config["arm_selector_policy"] == {
            "selector-unlimited": None,
            "selector-cap3": 3,
        }

    def test_build_without_policy_absent(self, dataset_path, corpus_dir):
        """未提供 policy 时 lock 不含该键（旧 A/B/C 锁向后兼容）。"""
        config = _build_lock(dataset_path, corpus_dir)
        assert "arm_selector_policy" not in config

    def test_load_accepts_valid_policy(self, tmp_path, dataset_path, corpus_dir):
        """合法 policy（int>=1 / null）可正常加载。"""
        config = _build_lock(dataset_path, corpus_dir,
                             arms=("selector-unlimited", "selector-cap3"))
        config["arm_selector_policy"] = {
            "selector-unlimited": None, "selector-cap3": 3}
        path = tmp_path / "lock.json"
        save_locked_config(config, path)
        loaded = load_locked_config(path)
        assert loaded["arm_selector_policy"]["selector-cap3"] == 3
        assert loaded["arm_selector_policy"]["selector-unlimited"] is None

    def test_load_rejects_bad_policy_shape(self, tmp_path, dataset_path, corpus_dir):
        """policy 非 dict / 值非法（字符串、0、负数）→ LockedConfigError。"""
        for bad in (
            {"selector-cap3": "3"},   # str 非 int/None
            {"selector-cap3": 0},     # 0 应写 null（unlimited 语义）
            {"selector-cap3": -1},    # 负数无意义
            "not-a-dict",             # 顶层非 dict
        ):
            config = _build_lock(dataset_path, corpus_dir,
                                 arms=("selector-cap3",))
            config["arm_selector_policy"] = bad
            path = tmp_path / "lock.json"
            save_locked_config(config, path)
            with pytest.raises(LockedConfigError):
                load_locked_config(path)

    def test_validate_policy_match_passes(self):
        """运行时 policy 与锁定一致 → 无差异。"""
        lock = {
            "arms": ["selector-cap3", "selector-unlimited"],  # 与 build 一致：排序归一化
            "locked_alpha": 1.0,
            "kg_sha256": None,
            "arm_selector_policy": {
                "selector-unlimited": None, "selector-cap3": 3},
        }
        diffs = validate_locked_config(
            lock,
            arms=["selector-unlimited", "selector-cap3"],
            arm_selector_policy={
                "selector-unlimited": None, "selector-cap3": 3},
        )
        assert diffs == []

    def test_validate_policy_drift_rejected(self):
        """policy 漂移（S3 被改成 unlimited）→ 差异列出字段名。"""
        lock = {
            "arms": ["selector-unlimited", "selector-cap3"],
            "locked_alpha": 1.0,
            "kg_sha256": None,
            "arm_selector_policy": {
                "selector-unlimited": None, "selector-cap3": 3},
        }
        diffs = validate_locked_config(
            lock,
            arms=["selector-unlimited", "selector-cap3"],
            arm_selector_policy={
                "selector-unlimited": None, "selector-cap3": None},
        )
        assert any("arm_selector_policy" in d for d in diffs)

    def test_validate_selector_arms_without_locked_policy_fails_closed(self):
        """含 selector 臂但 lock 未记录 policy → fail-closed 拒绝。"""
        lock = {
            "arms": ["selector-unlimited", "selector-cap3"],
            "locked_alpha": 1.0,
            "kg_sha256": None,
        }
        diffs = validate_locked_config(
            lock,
            arms=["selector-unlimited", "selector-cap3"],
            arm_selector_policy={
                "selector-unlimited": None, "selector-cap3": 3},
        )
        assert any("arm_selector_policy" in d for d in diffs)

    def test_validate_legacy_arms_without_policy_ok(self):
        """旧 A/B/C 锁无 policy 键 + standard 臂 → 不报差异（向后兼容）。"""
        lock = {
            "arms": ["standard"],
            "locked_alpha": 1.0,
            "kg_sha256": None,
        }
        diffs = validate_locked_config(
            lock,
            arms=["standard"],
            arm_selector_policy={"standard": 3},
        )
        assert diffs == []

    def test_validate_policy_unset_skipped(self):
        """后验阶段（_UNSET）不校验 policy。"""
        lock = {
            "arms": ["selector-cap3"],
            "locked_alpha": 1.0,
            "kg_sha256": None,
            "arm_selector_policy": {"selector-cap3": 3},
        }
        diffs = validate_locked_config(lock, arms=["selector-cap3"])
        assert diffs == []
