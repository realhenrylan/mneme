"""Tests for src/lexical.py — CJK n-gram tokenizer, field weighting, BM25 index."""

from __future__ import annotations

import pytest
from src.lexical import (
    cjk_ngram_tokenize,
    is_cjk,
    build_weighted_bm25_corpus,
    build_bm25_index,
    _tokenize_legacy,
)


# ── is_cjk ──


class TestIsCjk:
    """CJK 字符判断。"""

    def test_common_cjk(self):
        assert is_cjk("南") is True
        assert is_cjk("京") is True

    def test_ascii_not_cjk(self):
        assert is_cjk("A") is False
        assert is_cjk("1") is False

    def test_punctuation_not_cjk(self):
        assert is_cjk("。") is False  # CJK 标点不是汉字
        assert is_cjk("，") is False

    def test_extension_a(self):
        # CJK Extension A 范围 0x3400-0x4DBF
        assert is_cjk("\u3400") is True

    def test_extension_b(self):
        # CJK Extension B 范围 0x20000-0x2A6DF
        assert is_cjk("\U00020000") is True


# ── cjk_ngram_tokenize ──


class TestCjkNgramTokenize:
    """CJK n-gram tokenizer 测试。"""

    def test_pure_cjk_generates_unigram_and_bigram(self):
        """纯 CJK 文本生成 unigram + bigram。"""
        tokens = cjk_ngram_tokenize("南京")
        # unigrams: "南", "京"; bigram: "南京"
        assert "南" in tokens
        assert "京" in tokens
        assert "南京" in tokens

    def test_three_cjk_chars(self):
        """三个 CJK 字符生成 unigram + bigram。"""
        tokens = cjk_ngram_tokenize("南京总")
        # unigrams: 南, 京, 总; bigrams: 南京, 京总
        assert "南" in tokens
        assert "京" in tokens
        assert "总" in tokens
        assert "南京" in tokens
        assert "京总" in tokens

    def test_mixed_cjk_and_english(self):
        """中英混合文本。"""
        tokens = cjk_ngram_tokenize("南京总面积约6587km2")
        # CJK 部分：南, 南京, 京, 京总, 总, 总面, 面, 面积, 积
        # 英文/数字部分：6587km2
        assert "南京" in tokens
        assert "面积" in tokens
        assert "6587km2" in tokens

    def test_pure_english(self):
        """纯英文文本按空格分词。"""
        tokens = cjk_ngram_tokenize("What is RAG?")
        assert tokens == ["what", "is", "rag"]

    def test_pure_numbers(self):
        """纯数字。"""
        tokens = cjk_ngram_tokenize("123 456")
        assert "123" in tokens
        assert "456" in tokens

    def test_empty_string(self):
        """空字符串返回空列表。"""
        assert cjk_ngram_tokenize("") == []

    def test_single_cjk_char(self):
        """单个 CJK 字符只生成 unigram。"""
        tokens = cjk_ngram_tokenize("南")
        assert tokens == ["南"]

    def test_cjk_with_punctuation(self):
        """CJK 文本中的标点作为分隔符。"""
        tokens = cjk_ngram_tokenize("南京。北京")
        # "南京" 和 "北京" 被句号分隔
        assert "南京" in tokens
        assert "北京" in tokens
        # 不应产生跨句号的 bigram
        assert "京北" not in tokens

    def test_lowercase_english(self):
        """英文 token 小写化。"""
        tokens = cjk_ngram_tokenize("Hello World")
        assert "hello" in tokens
        assert "world" in tokens

    def test_strips_punctuation(self):
        """英文 token 去除首尾标点。"""
        tokens = cjk_ngram_tokenize("(hello), world!")
        assert "hello" in tokens
        assert "world" in tokens


# ── _tokenize_legacy ──


class TestTokenizeLegacy:
    """原始 tokenizer（向后兼容和基线对比）。"""

    def test_cjk_as_single_token(self):
        """连续 CJK 被当作一个 token（原始行为）。"""
        tokens = _tokenize_legacy("南京总面积")
        assert "南京总面积" in tokens

    def test_english_words(self):
        tokens = _tokenize_legacy("What is RAG")
        assert "what" in tokens
        assert "rag" in tokens


# ── build_weighted_bm25_corpus ──


class TestBuildWeightedBm25Corpus:
    """字段加权 BM25 语料构建。"""

    def test_default_weights(self):
        """默认权重：source_name 重复 2 次，section 重复 1 次。"""
        docs = ["chunk text"]
        metas = [{"source_name": "doc.pdf", "section": "intro"}]
        corpus = build_weighted_bm25_corpus(docs, metas)
        # content + source_name*2 + section*1
        assert corpus == ["chunk text doc.pdf doc.pdf intro"]

    def test_no_source_name(self):
        """缺少 source_name 时不重复。"""
        docs = ["chunk text"]
        metas = [{}]
        corpus = build_weighted_bm25_corpus(docs, metas)
        assert corpus == ["chunk text"]

    def test_custom_weights(self):
        """自定义权重：只包含指定的字段。"""
        docs = ["chunk text"]
        metas = [{"source_name": "doc.pdf", "section": "intro"}]
        corpus = build_weighted_bm25_corpus(docs, metas, field_weights={"source_name": 3.0})
        # content + source_name*3 (section 不在自定义权重中，不重复)
        assert corpus == ["chunk text doc.pdf doc.pdf doc.pdf"]

    def test_no_weights(self):
        """空权重映射：不重复任何字段。"""
        docs = ["chunk text"]
        metas = [{"source_name": "doc.pdf"}]
        corpus = build_weighted_bm25_corpus(docs, metas, field_weights={})
        assert corpus == ["chunk text"]


# ── build_bm25_index ──


class TestBuildBm25Index:
    """BM25 索引构建。"""

    def test_basic_index_creation(self):
        """基本索引创建，多文档语料确保 IDF 为正。"""
        docs = ["南京是江苏省省会", "北京是中国的首都", "上海是经济中心"]
        index = build_bm25_index(docs)
        assert index is not None
        # 应该能查询
        scores = index.get_scores(cjk_ngram_tokenize("南京"))
        assert len(scores) == 3
        # 南京在第一个文档，应比其他文档分数高
        assert scores[0] > scores[1]
        assert scores[0] > scores[2]

    def test_cjk_ngram_vs_legacy(self):
        """CJK n-gram tokenizer 应比 legacy tokenizer 有更好的中文召回。"""
        # 多文档语料确保 IDF 为正
        docs = ["南京总面积约6587平方公里", "北京人口约2189万人", "上海GDP总量领先"]
        index_ngram = build_bm25_index(docs, use_cjk_ngram=True)
        index_legacy = build_bm25_index(docs, use_cjk_ngram=False)

        # 查询"面积"：n-gram 应能匹配到 bigram "面积"
        query_ngram = cjk_ngram_tokenize("面积")
        query_legacy = _tokenize_legacy("面积")

        scores_ngram = index_ngram.get_scores(query_ngram)
        scores_legacy = index_legacy.get_scores(query_legacy)

        # n-gram 应有正分数（"面积" bigram 在第一个文档中）
        assert scores_ngram[0] > 0
        # legacy tokenizer 将"南京总面积约6587平方公里"当作一个 token，"面积"无法匹配
        assert scores_ngram[0] > scores_legacy[0]

    def test_with_metadatas(self):
        """带元数据的索引构建，多文档确保 IDF 为正。"""
        docs = ["chunk text about RAG", "chunk text about LLM", "chunk text about GNN"]
        metas = [
            {"source_name": "rag_guide.pdf", "section": "intro"},
            {"source_name": "llm_guide.pdf", "section": "basics"},
            {"source_name": "gnn_guide.pdf", "section": "advanced"},
        ]
        index = build_bm25_index(docs, metadatas=metas)
        # 查询 source_name 应能匹配
        scores = index.get_scores(cjk_ngram_tokenize("rag_guide"))
        assert scores[0] > 0

    def test_incremental_snapshot_reuse(self):
        """增量快照复用：未变更的 chunk 不重新 tokenization。"""
        docs = ["doc1 text", "doc2 text"]
        ids = ["c1", "c2"]
        index1 = build_bm25_index(docs, ids=ids)
        snapshot = {
            "document_hashes": getattr(index1, "document_hashes", {}),
            "tokenized": getattr(index1, "tokenized_by_chunk_id", {}),
        }
        # 用相同文档重建，应复用 tokenization
        index2 = build_bm25_index(docs, ids=ids, previous_snapshot=snapshot)
        assert index2 is not None

    def test_empty_documents(self):
        """空文档列表不崩溃。"""
        index = build_bm25_index([])
        assert index is not None

    def test_with_chunk_ids(self):
        """指定 chunk ID。"""
        docs = ["text1", "text2"]
        ids = ["id_1", "id_2"]
        index = build_bm25_index(docs, ids=ids)
        cache = getattr(index, "tokenized_by_chunk_id", {})
        assert "id_1" in cache
        assert "id_2" in cache
