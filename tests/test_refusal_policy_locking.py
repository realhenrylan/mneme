"""refusal_policy + effective_prompt_ids 锁定的单元测试（拒答策略消融）。

覆盖（RED → GREEN）：
- build 必填 refusal_policy / effective_prompt_ids（缺省、坏格式、非法值拒绝）；
- 两字段键集必须与 arms 完全一致；
- load 有键时格式校验、旧锁无键放行；
- validate：完整匹配 PASS、策略名/臂映射漂移拒绝、addendum 文本漂移
  （effective_prompt_id 变化）拒绝（LLM 前）、locked-but-not-computable 拒绝；
- 旧 prompt_id 保留（历史兼容），新实验校验以 effective_prompt_ids 为准。
"""
from __future__ import annotations

import hashlib
import json
from unittest.mock import patch

import pytest

from evaluation.compare import _compute_corpus_hash
from evaluation.locked_config import (
    build_locked_config,
    collect_runtime_budgets,
    collect_runtime_models,
    validate_locked_config,
)

FAKE_INDEX_SHA = "a" * 64
FAKE_SPLIT_SHA = "c" * 64

REFUSAL_POLICY_BY_ARM = {
    "standard": "baseline",
    "standard-calibrated": "evidence_calibrated",
}


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


def _base_kwargs(dataset_path, corpus_dir, arms):
    models = collect_runtime_models()
    return dict(
        locked_alpha=0.7,
        dataset_name=dataset_path.name,
        dataset_sha256="d" * 64,
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
        kg_sha256=None,
        split_fingerprint=FAKE_SPLIT_SHA,
    )


def _ablation_lock(dataset_path, corpus_dir):
    from evaluation.locked_config import compute_effective_prompt_ids
    return build_locked_config(
        **_base_kwargs(dataset_path, corpus_dir,
                       ["standard", "standard-calibrated"]),
        refusal_policy=dict(REFUSAL_POLICY_BY_ARM),
        effective_prompt_ids=compute_effective_prompt_ids(REFUSAL_POLICY_BY_ARM),
    )


def _ablation_runtime(dataset_path, corpus_dir):
    from evaluation.locked_config import compute_effective_prompt_ids
    models = collect_runtime_models()
    return dict(
        dataset_name=dataset_path.name,
        dataset_sha256="d" * 64,
        corpus_sha256=_compute_corpus_hash(corpus_dir, ["doc1.pdf"]),
        seed=42,
        arms=["standard", "standard-calibrated"],
        alpha_grid=[0.7],
        embedding_model=models["embedding_model"],
        llm_model=models["llm_model"],
        reranker_mode=models["reranker_mode"],
        reranker_model=models["reranker_model"],
        prompt_id=models["prompt_id"],
        budgets=collect_runtime_budgets(),
        refusal_policy=dict(REFUSAL_POLICY_BY_ARM),
        effective_prompt_ids=compute_effective_prompt_ids(REFUSAL_POLICY_BY_ARM),
    )


class TestBuildRequiresPolicyFields:
    def test_missing_refusal_policy_rejected(self, dataset_path, corpus_dir):
        with pytest.raises(ValueError, match="refusal_policy"):
            build_locked_config(**_base_kwargs(dataset_path, corpus_dir, ["standard"]))

    def test_missing_effective_prompt_ids_rejected(self, dataset_path, corpus_dir):
        with pytest.raises(ValueError, match="effective_prompt_ids"):
            build_locked_config(
                **_base_kwargs(dataset_path, corpus_dir, ["standard"]),
                refusal_policy={"standard": "baseline"},
            )

    def test_policy_keys_must_match_arms(self, dataset_path, corpus_dir):
        with pytest.raises(ValueError, match="refusal_policy"):
            build_locked_config(
                **_base_kwargs(dataset_path, corpus_dir, ["standard"]),
                refusal_policy={"standard": "baseline", "extra": "baseline"},
                effective_prompt_ids={"standard": "f" * 64},
            )

    def test_effective_prompt_ids_keys_must_match_arms(self, dataset_path, corpus_dir):
        with pytest.raises(ValueError, match="effective_prompt_ids"):
            build_locked_config(
                **_base_kwargs(dataset_path, corpus_dir, ["standard"]),
                refusal_policy={"standard": "baseline"},
                effective_prompt_ids={"standard": "f" * 64, "extra": "e" * 64},
            )

    def test_invalid_policy_value_rejected(self, dataset_path, corpus_dir):
        with pytest.raises(ValueError, match="refusal_policy"):
            build_locked_config(
                **_base_kwargs(dataset_path, corpus_dir, ["standard"]),
                refusal_policy={"standard": "bogus"},
                effective_prompt_ids={"standard": "f" * 64},
            )

    def test_bad_effective_prompt_id_format_rejected(self, dataset_path, corpus_dir):
        with pytest.raises(ValueError, match="effective_prompt_ids"):
            build_locked_config(
                **_base_kwargs(dataset_path, corpus_dir, ["standard"]),
                refusal_policy={"standard": "baseline"},
                effective_prompt_ids={"standard": "not-a-sha"},
            )


class TestLockRoundTrip:
    def test_both_fields_written(self, dataset_path, corpus_dir):
        from evaluation.locked_config import load_locked_config, save_locked_config
        lock = _ablation_lock(dataset_path, corpus_dir)
        assert lock["refusal_policy"] == REFUSAL_POLICY_BY_ARM
        assert set(lock["effective_prompt_ids"]) == set(REFUSAL_POLICY_BY_ARM)
        assert all(len(v) == 64 for v in lock["effective_prompt_ids"].values())
        path = tmp = dataset_path.parent / "lock.json"
        save_locked_config(lock, tmp)
        loaded = load_locked_config(tmp)
        assert loaded["refusal_policy"] == REFUSAL_POLICY_BY_ARM

    def test_prompt_id_retained_for_history(self, dataset_path, corpus_dir):
        lock = _ablation_lock(dataset_path, corpus_dir)
        assert "prompt_id" in lock
        assert lock["prompt_id"] == collect_runtime_models()["prompt_id"]


class TestValidatePolicyLocking:
    def test_full_match_passes(self, dataset_path, corpus_dir):
        lock = _ablation_lock(dataset_path, corpus_dir)
        diffs = validate_locked_config(lock, **_ablation_runtime(dataset_path, corpus_dir))
        assert diffs == []

    def test_policy_drift_rejected(self, dataset_path, corpus_dir):
        """臂映射/策略名漂移 → 拒绝。"""
        from evaluation.locked_config import compute_effective_prompt_ids
        lock = _ablation_lock(dataset_path, corpus_dir)
        runtime = _ablation_runtime(dataset_path, corpus_dir)
        runtime["refusal_policy"] = {
            "standard": "baseline", "standard-calibrated": "baseline",
        }
        runtime["effective_prompt_ids"] = compute_effective_prompt_ids(
            runtime["refusal_policy"])
        diffs = validate_locked_config(lock, **runtime)
        assert any("refusal_policy" in d for d in diffs)

    def test_addendum_text_drift_rejected(self, dataset_path, corpus_dir):
        """同名策略但 addendum 文本变化 → effective_prompt_id 不同 → 拒绝（LLM 前）。"""
        from evaluation.locked_config import compute_effective_prompt_ids
        import src.rag as rag
        lock = _ablation_lock(dataset_path, corpus_dir)
        runtime = _ablation_runtime(dataset_path, corpus_dir)
        with patch.object(
            rag, "EVIDENCE_CALIBRATED_SYSTEM_PROMPT_ADDENDUM",
            rag.EVIDENCE_CALIBRATED_SYSTEM_PROMPT_ADDENDUM + " (revised)",
        ):
            drifted = compute_effective_prompt_ids(REFUSAL_POLICY_BY_ARM)
        assert drifted != runtime["effective_prompt_ids"]
        runtime["effective_prompt_ids"] = drifted
        diffs = validate_locked_config(lock, **runtime)
        assert any("effective_prompt_ids" in d for d in diffs)

    def test_locked_but_not_computable_rejected(self, dataset_path, corpus_dir):
        lock = _ablation_lock(dataset_path, corpus_dir)
        runtime = _ablation_runtime(dataset_path, corpus_dir)
        runtime["refusal_policy"] = None
        runtime["effective_prompt_ids"] = None
        diffs = validate_locked_config(lock, **runtime)
        assert any("refusal_policy" in d for d in diffs)
        assert any("effective_prompt_ids" in d for d in diffs)

    def test_legacy_lock_without_policy_fields_skipped(self, dataset_path, corpus_dir):
        """旧锁（无两键）向后兼容放行；新实验不得只依赖旧 prompt_id。"""
        lock = build_locked_config(
            **_base_kwargs(dataset_path, corpus_dir, ["standard"]),
            refusal_policy={"standard": "baseline"},
            effective_prompt_ids={"standard": "f" * 64},
        )
        del lock["refusal_policy"]          # 模拟旧锁：无策略字段
        del lock["effective_prompt_ids"]
        assert "refusal_policy" not in lock
        assert "effective_prompt_ids" not in lock
        runtime = _ablation_runtime(dataset_path, corpus_dir)
        runtime["arms"] = ["standard"]
        runtime.pop("refusal_policy")
        runtime.pop("effective_prompt_ids")
        diffs = validate_locked_config(lock, **runtime)
        assert diffs == []
