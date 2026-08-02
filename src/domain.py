"""运行时领域模型：文档结构、检索候选、拒答特征、引用校验。

与 evaluation/schema.py 的区别：
- evaluation/schema.py 是"标注者写入、runner 读取"的评测数据契约
- 本模块是"检索/生成链路传递"的运行时类型，携带各通道原始分数和融合状态
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from enum import Enum
from typing import Any


# ═══════════════════════════════════════════════════════════════
# 文档结构模型（阶段 2.1）
# ═══════════════════════════════════════════════════════════════

class SectionType(str, Enum):
    """文档段落类型。"""
    HEADING = "heading"
    PARAGRAPH = "paragraph"
    TABLE = "table"
    LIST = "list"
    CODE = "code"
    IMAGE = "image"
    OTHER = "other"


class ParseQuality(str, Enum):
    """解析质量等级。

    - NATIVE_TEXT: 原生数字文本，高质量提取
    - STRUCTURED: 结构化解析，保留标题/表格等语义
    - OCR: OCR 识别，可能存在识别错误
    - LOW: 低质量提取，空文本率高或格式丢失严重
    """
    NATIVE_TEXT = "native_text"
    STRUCTURED = "structured"
    OCR = "ocr"
    LOW = "low"


@dataclass(frozen=True)
class Section:
    """文档中的一个语义段落（标题、段落、表格等）。

    Section 是文档解析的最小语义单元，后续分块（Chunk）基于 Section 边界切分。
    """
    section_type: SectionType
    text: str
    heading_level: int | None = None  # 1-6 for headings, None for others
    heading_path: str = ""  # 层级路径，如 "1.2.3 方法论"
    page: int | None = None  # 所在页码
    char_start: int = 0  # 在原文中的字符起始位置
    char_end: int = 0  # 在原文中的字符结束位置
    metadata: dict[str, Any] = field(default_factory=dict)  # 扩展元数据（表格行列数等）


@dataclass(frozen=True)
class Chunk:
    """分块后的文本片段，是检索和嵌入的基本单元。

    Chunk 由 Section 切分而来，保留来源 Section 的语义信息。
    """
    text: str
    chunk_id: str
    chunk_index: int  # 在同一 source 内的序号
    page: int | None = None
    section_heading: str = ""  # 所属 section 的标题路径
    section_type: SectionType = SectionType.OTHER
    char_start: int = 0
    char_end: int = 0
    parent_chunk_id: str | None = None  # Parent-Child 关系（阶段 2.2）
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class Document:
    """解析后的文档，包含元数据和结构化段落列表。

    所有 loader（PDF/DOCX/text）输出统一的 Document 对象，
    后续分块和索引基于 Document 进行。
    """
    source_id: str
    source_path: str
    source_name: str
    file_type: str  # "pdf" | "docx" | "text"
    sections: list[Section] = field(default_factory=list)
    chunks: list[Chunk] = field(default_factory=list)
    parse_quality: ParseQuality = ParseQuality.NATIVE_TEXT
    parser_version: str = "1.0"
    # 来源文件元数据
    content_sha256: str = ""
    source_size: int = 0
    source_mtime_ns: int = 0
    # 解析质量指标
    total_pages: int | None = None
    empty_text_pages: int = 0
    # 扩展元数据
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def full_text(self) -> str:
        """拼接所有 section 的文本。"""
        return "\n".join(s.text for s in self.sections if s.text)

    @property
    def empty_text_rate(self) -> float:
        """空文本页率（仅 PDF 有意义）。"""
        if self.total_pages and self.total_pages > 0:
            return self.empty_text_pages / self.total_pages
        return 0.0

    @property
    def is_low_quality(self) -> bool:
        """是否为低质量解析。"""
        if self.parse_quality == ParseQuality.LOW:
            return True
        # 空文本页率超过 30% 视为低质量
        if self.total_pages and self.total_pages > 0 and self.empty_text_rate > 0.3:
            return True
        return False


# ═══════════════════════════════════════════════════════════════
# 检索候选与拒答特征（阶段 1.3-1.5）
# ═══════════════════════════════════════════════════════════════


@dataclass(frozen=True)
class RetrievalCandidate:
    """检索候选，保留各通道原始分数和融合分数。

    各通道分数为 None 表示该通道未召回此候选。
    """

    index: int  # 在 collection 中的原始位置
    chunk_id: str
    source_id: str
    source_name: str

    # 各通道原始分数
    dense_similarity: float | None = None
    bm25_score: float | None = None
    rrf_score: float | None = None
    graph_score: float | None = None
    rerank_score: float | None = None

    # 各通道排名
    dense_rank: int | None = None
    bm25_rank: int | None = None
    rrf_rank: int | None = None

    def with_scores(
        self,
        *,
        rrf_score: float | None = None,
        rrf_rank: int | None = None,
        rerank_score: float | None = None,
    ) -> RetrievalCandidate:
        """返回更新了指定分数的新候选（frozen dataclass 不可变，用 replace）。"""
        return replace(
            self,
            rrf_score=rrf_score if rrf_score is not None else self.rrf_score,
            rrf_rank=rrf_rank if rrf_rank is not None else self.rrf_rank,
            rerank_score=rerank_score if rerank_score is not None else self.rerank_score,
        )


@dataclass(frozen=True)
class RefusalFeatures:
    """拒答判断的可解释特征。

    每个特征都有明确的业务含义，便于调试和阈值调优。
    """

    top_score: float  # reranker 最高分（若有）或 RRF 最高分
    top1_top2_margin: float  # top1 与 top2 的分数差
    effective_source_count: int  # 有效来源数（score > 0 的不同来源）
    query_length: int  # 查询长度
    has_cjk: bool  # 是否含中文
    max_dense_similarity: float  # dense 通道最高相似度
    max_bm25_score: float  # BM25 通道最高分


@dataclass
class CitationValidation:
    """引用校验结果。"""

    valid_ids: set[str]  # 合法引用 ID
    invalid_ids: set[str]  # 非法引用 ID
    repaired: bool = False  # 是否经过修复
    repair_success: bool = False  # 修复是否成功
    unverified: bool = False  # 是否标记为不可验证


def compute_context_k(
    candidates: list[RetrievalCandidate],
    token_budget: int = 3000,
    avg_chunk_tokens: int = 200,
    min_k: int = 3,
    max_k: int = 10,
) -> int:
    """基于 token budget 计算实际进入 prompt 的候选数。

    token_budget: LLM context 中分配给检索证据的 token 预算（默认 3000，约 4K 字符）
    avg_chunk_tokens: 每个 chunk 的平均 token 数（默认 200，基于 DEFAULT_CHUNK_SIZE=500 字符 ÷ ~2.5 字符/token）
    """
    budget_k = max(min_k, min(max_k, token_budget // avg_chunk_tokens))
    return min(len(candidates), budget_k)
