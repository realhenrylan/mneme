"""Tests for evaluation.run dataset/corpus defaults（评测 runner 切到 v2.1）。

runner 的默认数据集切换为 v2.1 后，裸名数据集需要能解析到各自语料目录
（v1 → test_texts，v2.1 → v2 语料 processed 目录）；显式 --corpus-dir
必须永远优先，保证既有密封实验的显式用法不受影响。
"""

from pathlib import Path

from evaluation.run import (
    DATASET_CORPUS_DEFAULTS,
    DEFAULT_DATASET,
    EVAL_ROOT,
    resolve_corpus_dir,
    resolve_dataset_path,
)

REPO = EVAL_ROOT.parent


class TestDefaultDataset:
    """默认数据集 = v2.1（人工终审 overlay 激活的正式评测集）。"""

    def test_default_is_v21(self):
        assert DEFAULT_DATASET == "v2.1"

    def test_default_dataset_resolves_and_exists(self):
        p = resolve_dataset_path(DEFAULT_DATASET)
        assert p == REPO / "evaluation" / "datasets" / "v2.1.jsonl"
        assert p.exists()


class TestCorpusRegistry:
    """裸名数据集 → 缺省语料目录注册表。"""

    def test_registry_covers_both_datasets(self):
        assert set(DATASET_CORPUS_DEFAULTS) == {"v1", "v2.1"}

    def test_v21_corpus_resolves_to_processed_dir(self):
        d = resolve_corpus_dir("v2.1", None)
        assert d == REPO / "data" / "v2-corpus" / "documents" / "processed"
        assert d.is_dir()
        # v2.1 全部 13 个 source 都能在此目录精确命中
        names = {p.name for p in d.iterdir()}
        for s in ("python-tutorial-en.md", "rust-book-core.md", "art-of-war.txt"):
            assert s in names

    def test_v1_corpus_resolves_to_test_texts(self):
        d = resolve_corpus_dir("v1", None)
        assert d == REPO / "test_texts"
        assert d.is_dir()

    def test_explicit_corpus_dir_wins(self):
        explicit = Path("D:/some/custom/corpus")
        assert resolve_corpus_dir("v2.1", explicit) == explicit

    def test_unknown_name_yields_none(self):
        assert resolve_corpus_dir("v9", None) is None
