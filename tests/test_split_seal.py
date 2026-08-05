"""Tests for evaluation.split_seal — v2 group-aware dev/holdout sealing.

Covers: case freeze, deterministic stratified group split (chains atomic,
holdout ⊂ new pool, ratio/stratum gates), fingerprint lock/verify,
artifact leak scan, and one-shot holdout confirmation recomputation.
Deterministic, zero LLM.
"""

from __future__ import annotations

import json

import pytest

from evaluation.split_seal import (
    build_split,
    check_artifact_ids,
    confirm_holdout,
    freeze_case_ids,
    group_key_for,
    splitmix64_sort_key,
    verify_lock,
)

# fixture：3 个层（single_fact×zh / no_answer×en / metadata×mixed），
# 每层多个组（链 + 单例），接近真实规模使 holdout 比例落在 [0.22, 0.30]
FIXTURE = [
    {"id": "a-001", "query_type": "single_fact", "language": "zh",
     "should_refuse": False, "partition": "legacy_dev",
     "chain_id": None},
    {"id": "a-002", "query_type": "single_fact", "language": "zh",
     "should_refuse": False, "partition": "new", "chain_id": "ch1"},
    {"id": "a-003", "query_type": "single_fact", "language": "zh",
     "should_refuse": False, "partition": "new", "chain_id": "ch1"},
    {"id": "a-004", "query_type": "no_answer", "language": "en",
     "should_refuse": True, "partition": "new", "chain_id": None},
    {"id": "a-005", "query_type": "no_answer", "language": "en",
     "should_refuse": True, "partition": "new", "chain_id": "ch2"},
    {"id": "a-006", "query_type": "no_answer", "language": "en",
     "should_refuse": True, "partition": "new", "chain_id": "ch2"},
    {"id": "a-007", "query_type": "metadata", "language": "mixed",
     "should_refuse": False, "partition": "new", "chain_id": None},
    {"id": "a-008", "query_type": "single_fact", "language": "zh",
     "should_refuse": False, "partition": "new", "chain_id": None},
    {"id": "a-009", "query_type": "single_fact", "language": "zh",
     "should_refuse": False, "partition": "new", "chain_id": None},
    {"id": "a-010", "query_type": "no_answer", "language": "en",
     "should_refuse": True, "partition": "new", "chain_id": None},
    {"id": "a-011", "query_type": "no_answer", "language": "en",
     "should_refuse": True, "partition": "new", "chain_id": None},
    {"id": "a-012", "query_type": "metadata", "language": "mixed",
     "should_refuse": False, "partition": "new", "chain_id": None},
    {"id": "a-013", "query_type": "single_fact", "language": "zh",
     "should_refuse": False, "partition": "new", "chain_id": None},
    {"id": "a-014", "query_type": "no_answer", "language": "en",
     "should_refuse": True, "partition": "new", "chain_id": None},
    {"id": "a-015", "query_type": "metadata", "language": "mixed",
     "should_refuse": False, "partition": "new", "chain_id": None},
    {"id": "a-016", "query_type": "metadata", "language": "mixed",
     "should_refuse": False, "partition": "new", "chain_id": None},
]


class TestFreeze:
    def test_freeze_ordered_and_sha(self):
        fr = freeze_case_ids(FIXTURE, corpus_version="v2.0.0")
        assert fr["corpus_version"] == "v2.0.0"
        assert fr["case_ids"] == sorted(c["id"] for c in FIXTURE)
        assert len(fr["case_ids_sha256"]) == 64
        assert fr["partition"]["legacy_dev"] == ["a-001"]
        assert sorted(fr["partition"]["new"]) == [c["id"] for c in FIXTURE
                                                  if c["id"] != "a-001"]

    def test_freeze_deterministic(self):
        f1 = freeze_case_ids(FIXTURE, corpus_version="v2.0.0")
        f2 = freeze_case_ids(FIXTURE, corpus_version="v2.0.0")
        assert json.dumps(f1, sort_keys=True) == json.dumps(f2, sort_keys=True)

    def test_freeze_changes_with_input(self):
        f1 = freeze_case_ids(FIXTURE, corpus_version="v2.0.0")
        f2 = freeze_case_ids(FIXTURE[:-1], corpus_version="v2.0.0")
        assert f1["case_ids_sha256"] != f2["case_ids_sha256"]


class TestGroupKey:
    def test_chain_group_key(self):
        assert group_key_for({"chain_id": "ch1", "id": "a-002"}) == "ch1"

    def test_singleton_group_key_is_id(self):
        assert group_key_for({"chain_id": None, "id": "a-001"}) == "a-001"

    def test_sort_key_deterministic(self):
        assert splitmix64_sort_key(42, "ch1") == splitmix64_sort_key(42, "ch1")
        assert splitmix64_sort_key(42, "ch1") != splitmix64_sort_key(43, "ch1")
        assert splitmix64_sort_key(42, "ch1") != splitmix64_sort_key(42, "ch2")


class TestBuildSplit:
    def test_deterministic(self):
        fr = freeze_case_ids(FIXTURE, corpus_version="v2.0.0")
        s1 = build_split(fr, seed=42, holdout_ratio=0.25)
        s2 = build_split(fr, seed=42, holdout_ratio=0.25)
        assert s1.dev_ids == s2.dev_ids
        assert s1.holdout_ids == s2.holdout_ids
        assert s1.fingerprint == s2.fingerprint

    def test_holdout_only_new_cases(self):
        fr = freeze_case_ids(FIXTURE, corpus_version="v2.0.0")
        s = build_split(fr, seed=42, holdout_ratio=0.25)
        assert "a-001" not in s.holdout_ids
        assert set(s.holdout_ids) <= set(fr["partition"]["new"])

    def test_chains_are_atomic(self):
        fr = freeze_case_ids(FIXTURE, corpus_version="v2.0.0")
        s = build_split(fr, seed=42, holdout_ratio=0.25)
        # ch1 {a-002,a-003} and ch2 {a-005,a-006} never split
        ch1 = {"a-002", "a-003"}
        ch2 = {"a-005", "a-006"}
        for chain in (ch1, ch2):
            overlap = chain & set(s.holdout_ids)
            assert overlap in (set(), chain)

    def test_stratum_min_one_group(self):
        fr = freeze_case_ids(FIXTURE, corpus_version="v2.0.0")
        s = build_split(fr, seed=1, holdout_ratio=0.3)
        stats = s.stats
        assert stats["n_groups_new"] == 13
        assert stats["n_groups_holdout"] >= 3
        assert stats["holdout_ratio"] >= 0.22
        assert stats["holdout_ratio"] <= 0.30

    def test_fingerprint_sensitive_to_seed(self):
        fr = freeze_case_ids(FIXTURE, corpus_version="v2.0.0")
        s1 = build_split(fr, seed=42, holdout_ratio=0.25)
        s2 = build_split(fr, seed=43, holdout_ratio=0.25)
        assert s1.fingerprint != s2.fingerprint

    def test_partition_union_is_pool(self):
        fr = freeze_case_ids(FIXTURE, corpus_version="v2.0.0")
        s = build_split(fr, seed=42, holdout_ratio=0.25)
        # split 覆盖全部 new 用例；legacy 恒为 dev 池（由调用方并入）
        assert sorted(s.dev_ids + s.holdout_ids) == sorted(fr["partition"]["new"])
        assert set(s.dev_ids) & set(fr["partition"]["legacy_dev"]) == set()


class TestVerifyLock:
    def test_verify_matches(self):
        fr = freeze_case_ids(FIXTURE, corpus_version="v2.0.0")
        s = build_split(fr, seed=42, holdout_ratio=0.25)
        lock = {"split_fingerprint": s.fingerprint, "seed": 42,
                "holdout_ratio": 0.25, "splitter_version": s.splitter_version,
                "case_freeze_sha256": fr["case_ids_sha256"]}
        assert verify_lock(lock, fr) is True

    def test_verify_fails_on_input_drift(self):
        fr = freeze_case_ids(FIXTURE, corpus_version="v2.0.0")
        s = build_split(fr, seed=42, holdout_ratio=0.25)
        lock = {"split_fingerprint": s.fingerprint, "seed": 42,
                "holdout_ratio": 0.25, "splitter_version": s.splitter_version,
                "case_freeze_sha256": "0" * 64}
        assert verify_lock(lock, fr) is False

    def test_verify_fails_on_wrong_fingerprint(self):
        fr = freeze_case_ids(FIXTURE, corpus_version="v2.0.0")
        s = build_split(fr, seed=43, holdout_ratio=0.25)
        lock = {"split_fingerprint": s.fingerprint, "seed": 42,
                "holdout_ratio": 0.25, "splitter_version": s.splitter_version,
                "case_freeze_sha256": fr["case_ids_sha256"]}
        assert verify_lock(lock, fr) is False


class TestCheckArtifactIds:
    def test_holdout_id_in_artifact_rejected(self, tmp_path):
        p = tmp_path / "features.jsonl"
        p.write_text('{"case_id": "a-005"}\n{"case_id": "a-001"}\n',
                     encoding="utf-8")
        with pytest.raises(ValueError):
            check_artifact_ids([str(p)], {"a-005"})

    def test_clean_artifact_passes(self, tmp_path):
        p = tmp_path / "features.jsonl"
        p.write_text('{"case_id": "a-001"}\n', encoding="utf-8")
        check_artifact_ids([str(p)], {"a-005"})  # 不抛异常

    def test_missing_file_rejected(self, tmp_path):
        with pytest.raises(ValueError):
            check_artifact_ids([str(tmp_path / "nope.jsonl")], {"a-005"})


class TestConfirmHoldout:
    def test_confirm_recomputes_same_holdout(self, tmp_path):
        fr = freeze_case_ids(FIXTURE, corpus_version="v2.0.0")
        s = build_split(fr, seed=42, holdout_ratio=0.25)
        out = tmp_path / "holdout-confirmation.json"
        confirmed = confirm_holdout(
            fr, seed=42, holdout_ratio=0.25, fingerprint=s.fingerprint,
            output=str(out))
        assert confirmed["holdout_ids"] == sorted(s.holdout_ids)
        assert confirmed["fingerprint_matched"] is True
        assert out.exists()

    def test_confirm_fails_on_fingerprint_mismatch(self, tmp_path):
        fr = freeze_case_ids(FIXTURE, corpus_version="v2.0.0")
        s = build_split(fr, seed=42, holdout_ratio=0.25)
        with pytest.raises(ValueError):
            confirm_holdout(fr, seed=42, holdout_ratio=0.25,
                            fingerprint="0" * 64,
                            output=str(tmp_path / "x.json"))
