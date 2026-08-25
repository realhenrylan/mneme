"""Citation v2 唯一聚合契约（分母显式命名，禁止各自手算）。

背景（2026-08-04 审计发现）：同一批 selector-ablation 产物中 citation 指标出现
0.875 / 0.847 / 0.713 等不同值——不同汇总路径分别以「全体 case」「可答 case」
「含 citation 的 case」为分母，且指标名未携带分母，不能作为统一 guardrail。
本模块是 citation v2 聚合的**唯一入口**：compare.py 的 summary、离线 replay
（reconcile 工具）、任何新分析都必须调用本模块的聚合函数，禁止在调用方
手算均值。

分母契约（唯一命名，见 DENOM_* 常量）：
- all_generation_cases            该 arm 全部 generation case（含 refusal/error）
- answerable_generation_cases     非 should_refuse 且非 error 的 case
- answers_with_any_citation       answerable 中至少出现一个唯一引用 ID 的 case
- total_unique_citation_ids       所有可答答案的唯一引用 ID 总数
                                  （重复引用在 citation_metrics 层已按 ID 计
                                  一次；refusal/error 行的引用不进入此分母——
                                  false_answer 属于拒答错误，由拒答指标跟踪）

指标（value=None 表示分母为 0 → unavailable，禁止伪装为 0）：
- context_supported_citation_validity_micro：ID 层 micro 均值
  （Σ context-supported 唯一 ID / Σ 唯一 ID），numerator/denominator 单位为 ID；
- context_supported_answer_rate：至少一个 context-supported 引用的答案 / 可答 case；
- no_citation_answer_rate：无任何引用 ID 的答案 / 可答 case；
- citation_mention_rate：至少一个引用 ID 的答案 / 可答 case（补充）。

每个指标携带 numerator / denominator（命名+计数）/ excluded_count（分母外行数）
/ excluded_reason；行级守恒恒等式由 check_conservation() 校验：
    R1  n_all_cases == n_answerable + n_refused + n_error
    R2  n_answerable == n_supported_answers + n_cited_but_unsupported_answers
                       + n_no_citation + n_evidence_missing
    R3  total_unique_citation_ids == n_supported_ids + n_fabricated_ids
                                    + n_retrieved_not_in_context_ids
                                    + n_other_status_ids
    R4  （答案层指标）numerator + excluded_count + (denominator_count − numerator)
        == n_all_cases —— 即「分子 + 分母外行 + 分母内未命中行」与原始行数守恒；
        分母内未命中为 0 时退化为 numerator + excluded_count == n_all_cases。

缺证据行（citation v1 时代产物，无 citation_status_counts）的引用状态**未知**：
不得把「未知」当作「不支持」计入分母（否则伪装为 0）——它们计入各指标的
excluded_count 与 n_evidence_missing，答案层指标分母只统计有证据的可答行；
全部行缺证据时 denominator_count == 0 → value=None（unavailable）。

旧字段（citation_id_validity / citation_precision / citation_recall /
faithfulness / context_supported_citation_validity 单值）仅保留兼容读取
（CaseCitationCounts.legacy_*，经 legacy_mean_metric 对账），标记
legacy/deprecated；新 guardrail 只能通过 get_guardrail_metric() 消费本模块
输出 metrics 中的新字段（对 legacy/未知名称抛 ValueError）。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

# ── 分母命名（唯一） ─────────────────────────────────────────────────

DENOM_ALL_GENERATION_CASES = "all_generation_cases"
DENOM_ANSWERABLE_GENERATION_CASES = "answerable_generation_cases"
DENOM_ANSWERS_WITH_ANY_CITATION = "answers_with_any_citation"
DENOM_TOTAL_UNIQUE_CITATION_IDS = "total_unique_citation_ids"

# 新 guardrail 指标名（唯一可消费集合）
NEW_GUARDRAIL_METRICS = (
    "context_supported_citation_validity_micro",
    "context_supported_answer_rate",
    "no_citation_answer_rate",
    "citation_mention_rate",
)

# legacy（deprecated）聚合键——仅兼容读取，不得作为新 guardrail 输入
LEGACY_METRIC_KEYS = (
    "citation_id_validity",
    "citation_precision",
    "citation_recall",
    "faithfulness",
    "context_supported_citation_validity",
)

# 已知引用判定状态（citation_metrics 契约 v2）
_SUPPORTED_STATUSES = ("supported_chunk", "supported_source")
_KNOWN_STATUSES = _SUPPORTED_STATUSES + (
    "retrieved_not_in_context", "fabricated")


# ── case 级事实（提取的唯一抽象） ────────────────────────────────────


@dataclass(frozen=True)
class CaseCitationCounts:
    """单 case 的 citation 事实（从 GenerationCaseResult 或 JSONL 行确定性提取）。

    unique/supported/fabricated/... 为 None 表示该产物**无 context 证据**
    （如 citation v1 时代的 JSONL 缺 citation_status_counts），新口径不可重算。
    legacy_* 为旧字段值，仅用于对账，不参与新指标。
    """

    case_id: str
    arm: str
    should_refuse: bool
    error: str | None
    unique_citation_ids: int | None
    supported_citation_ids: int | None
    fabricated_citation_ids: int | None = 0
    retrieved_not_in_context_ids: int | None = 0
    other_status_ids: int | None = 0
    # legacy（deprecated，仅对账）
    legacy_citation_id_validity: float | None = None
    legacy_citation_precision: float | None = None
    legacy_citation_recall: float | None = None
    legacy_faithfulness: float | None = None
    legacy_context_supported_validity: float | None = None


def _status_counts_of(result: Any) -> dict[str, int]:
    counts = getattr(result, "citation_status_counts", None)
    if counts is None:
        return {}
    return {str(k): int(v) for k, v in counts.items()}


def _counts_from_status_map(status_counts: Mapping[str, int]) -> dict[str, int]:
    """status_counts → 唯一 ID 计数（evidence 逐唯一 ID 一条，求和即 ID 数）。"""
    supported = sum(
        status_counts.get(s, 0) for s in _SUPPORTED_STATUSES)
    fabricated = status_counts.get("fabricated", 0)
    not_in_context = status_counts.get("retrieved_not_in_context", 0)
    other = sum(
        v for k, v in status_counts.items() if k not in _KNOWN_STATUSES)
    return {
        "unique": supported + fabricated + not_in_context + other,
        "supported": supported,
        "fabricated": fabricated,
        "not_in_context": not_in_context,
        "other": other,
    }


def case_counts_from_result(result: Any) -> CaseCitationCounts:
    """从 GenerationCaseResult（live 路径）提取 case 级 citation 事实。

    Args:
        result: 具有 should_refuse / error / citation_status_counts /
            citation_id_validity 等字段的对象（GenerationCaseResult）。

    Returns:
        提取后的 CaseCitationCounts（唯一事实来源）。
    """
    status_counts = _status_counts_of(result)
    counts = _counts_from_status_map(status_counts)
    return CaseCitationCounts(
        case_id=result.case_id,
        arm=result.arm,
        should_refuse=bool(result.should_refuse),
        error=result.error,
        unique_citation_ids=counts["unique"],
        supported_citation_ids=counts["supported"],
        fabricated_citation_ids=counts["fabricated"],
        retrieved_not_in_context_ids=counts["not_in_context"],
        other_status_ids=counts["other"],
        legacy_citation_id_validity=_float_or_none(
            getattr(result, "citation_id_validity", None)),
        legacy_citation_precision=_float_or_none(
            getattr(result, "citation_precision", None)),
        legacy_citation_recall=_float_or_none(
            getattr(result, "citation_recall", None)),
        legacy_faithfulness=_float_or_none(
            getattr(result, "faithfulness", None)),
        legacy_context_supported_validity=_float_or_none(
            getattr(result, "context_supported_citation_validity", None)),
    )


def case_counts_from_jsonl_row(row: Mapping[str, Any]) -> CaseCitationCounts:
    """从 generation-cases.jsonl 行（replay 路径）提取 case 级 citation 事实。

    v2 schema（有 citation_status_counts）→ 完整计数；
    v1 schema（无 context 证据，如 auto-run / reranker-recheck）→
    unique/supported 为 None（不可重算），legacy 字段仍可读用于对账。
    """
    status_counts = row.get("citation_status_counts")
    if isinstance(status_counts, dict) and status_counts:
        counts = _counts_from_status_map(status_counts)
    elif isinstance(status_counts, dict):
        # 空 dict：v2 无引用答案（真实空，证据存在）
        counts = {"unique": 0, "supported": 0, "fabricated": 0,
                  "not_in_context": 0, "other": 0}
    else:
        # v1 schema：缺 context 证据
        counts = {"unique": None, "supported": None, "fabricated": 0,
                  "not_in_context": 0, "other": 0}
    return CaseCitationCounts(
        case_id=str(row.get("case_id", "")),
        arm=str(row.get("arm", "")),
        should_refuse=bool(row.get("should_refuse", False)),
        error=row.get("error"),
        unique_citation_ids=counts["unique"],
        supported_citation_ids=counts["supported"],
        fabricated_citation_ids=counts["fabricated"],
        retrieved_not_in_context_ids=counts["not_in_context"],
        other_status_ids=counts["other"],
        legacy_citation_id_validity=_float_or_none(
            row.get("citation_id_validity")),
        legacy_citation_precision=_float_or_none(
            row.get("citation_precision")),
        legacy_citation_recall=_float_or_none(row.get("citation_recall")),
        legacy_faithfulness=_float_or_none(row.get("faithfulness")),
        legacy_context_supported_validity=_float_or_none(
            row.get("context_supported_citation_validity")),
    )


def _float_or_none(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


# ── 指标值 ───────────────────────────────────────────────────────────


@dataclass(frozen=True)
class MetricValue:
    """单个指标的聚合结果；value=None 表示分母为 0 → unavailable。"""

    name: str
    denominator: str          # DENOM_* 命名
    denominator_count: int    # 分母集合大小（ID 或行，见 docstring）
    numerator: int            # 分子计数
    excluded_count: int       # 分母集合之外的行数（行单位）
    excluded_reason: str
    value: float | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "denominator": self.denominator,
            "denominator_count": self.denominator_count,
            "numerator": self.numerator,
            "excluded_count": self.excluded_count,
            "excluded_reason": self.excluded_reason,
            "value": self.value,
        }


# ── 聚合结果 ─────────────────────────────────────────────────────────


@dataclass(frozen=True)
class CitationAggregate:
    """行 / ID 双分区计数 + 新 guardrail 指标。

    行分区恒等式（check_conservation 校验）：
        n_all_cases == n_answerable + n_refused + n_error
        n_answerable == n_supported_answers + n_cited_but_unsupported_answers
                        + n_no_citation + n_evidence_missing
    ID 分区恒等式：
        total_unique_citation_ids == n_supported_ids + n_fabricated_ids
                                    + n_retrieved_not_in_context_ids
                                    + n_other_status_ids
    """

    n_all_cases: int
    n_refused: int
    n_error: int
    n_answerable: int
    n_evidence_missing: int          # 可答但产物缺 context 证据的行（v1 schema）
    n_with_any_citation: int         # answerable 且有证据且 unique > 0
    n_no_citation: int               # answerable 且有证据且 unique == 0
    n_supported_answers: int         # ≥1 context-supported 引用
    n_cited_but_unsupported_answers: int  # unique > 0 且 supported == 0
    total_unique_citation_ids: int
    n_supported_ids: int
    n_fabricated_ids: int
    n_retrieved_not_in_context_ids: int
    n_other_status_ids: int
    metrics: dict[str, MetricValue] = field(default_factory=dict)

    def check_conservation(self) -> None:
        """校验行 / ID 分区恒等式；违反即抛 ValueError（fail-closed）。"""
        violations: list[str] = []
        if self.n_all_cases != (
                self.n_answerable + self.n_refused + self.n_error):
            violations.append(
                "R1 n_all != n_answerable + n_refused + n_error: "
                f"{self.n_all_cases} != {self.n_answerable} + "
                f"{self.n_refused} + {self.n_error}")
        if self.n_answerable != (
                self.n_supported_answers
                + self.n_cited_but_unsupported_answers
                + self.n_no_citation + self.n_evidence_missing):
            violations.append("R2 answerable partition violated")
        if self.total_unique_citation_ids != (
                self.n_supported_ids + self.n_fabricated_ids
                + self.n_retrieved_not_in_context_ids
                + self.n_other_status_ids):
            violations.append("R3 ID partition violated")
        for m in self.metrics.values():
            if m.denominator == DENOM_ANSWERABLE_GENERATION_CASES:
                # 答案层指标（行单位）：分子 + 分母外行 + 分母内未命中行
                # == 原始行数；分母内未命中为 0 时退化为 numerator+excluded
                denom_internal_miss = m.denominator_count - m.numerator
                if m.numerator + m.excluded_count + denom_internal_miss \
                        != self.n_all_cases:
                    violations.append(
                        f"R4 {m.name}: numerator + excluded + "
                        f"denom-internal-miss != n_all "
                        f"({m.numerator} + {m.excluded_count} + "
                        f"{denom_internal_miss} != {self.n_all_cases})")
            elif m.denominator == DENOM_TOTAL_UNIQUE_CITATION_IDS:
                # ID 层指标（numerator/denominator 单位为 ID）：行级守恒 =
                # 分母外行数 == 无 ID 行 + 缺证据行；ID 级守恒由 R3 覆盖
                if m.excluded_count != (
                        self.n_no_citation + self.n_evidence_missing):
                    violations.append(
                        f"R4 {m.name}: excluded rows "
                        f"({m.excluded_count}) != n_no_citation + "
                        f"n_evidence_missing "
                        f"({self.n_no_citation} + "
                        f"{self.n_evidence_missing})")
        if violations:
            raise ValueError("citation aggregate conservation violated:\n- "
                             + "\n- ".join(violations))

    def to_dict(self) -> dict[str, Any]:
        return {
            "n_all_cases": self.n_all_cases,
            "n_refused": self.n_refused,
            "n_error": self.n_error,
            "n_answerable": self.n_answerable,
            "n_evidence_missing": self.n_evidence_missing,
            "n_with_any_citation": self.n_with_any_citation,
            "n_no_citation": self.n_no_citation,
            "n_supported_answers": self.n_supported_answers,
            "n_cited_but_unsupported_answers":
                self.n_cited_but_unsupported_answers,
            "total_unique_citation_ids": self.total_unique_citation_ids,
            "n_supported_ids": self.n_supported_ids,
            "n_fabricated_ids": self.n_fabricated_ids,
            "n_retrieved_not_in_context_ids":
                self.n_retrieved_not_in_context_ids,
            "n_other_status_ids": self.n_other_status_ids,
            "metrics": {k: v.to_dict() for k, v in self.metrics.items()},
        }


def _rate(numerator: int, denominator: int) -> float | None:
    """分母为 0 → None（unavailable），禁止伪装为 0。"""
    if denominator <= 0:
        return None
    return numerator / denominator


def aggregate_citations(
    counts: Sequence[CaseCitationCounts],
) -> CitationAggregate:
    """对 case 级 citation 事实做唯一聚合（契约 v2 唯一入口）。

    Args:
        counts: 逐 case 事实（必须经 case_counts_from_result /
            case_counts_from_jsonl_row 提取，禁止调用方手算）。

    Returns:
        CitationAggregate（行 / ID 双分区 + 新指标；value=None = unavailable）。

    Raises:
        ValueError: 行 / ID 分区恒等式被破坏（check_conservation）。
    """
    n_refused = 0
    n_error = 0
    n_evidence_missing = 0
    n_with_any = 0
    n_no_citation = 0
    n_supported_answers = 0
    n_cited_unsupported = 0
    total_unique = 0
    n_supported_ids = 0
    n_fabricated_ids = 0
    n_not_in_context_ids = 0
    n_other_ids = 0

    for c in counts:
        if c.error is not None:
            n_error += 1
            continue
        if c.should_refuse:
            n_refused += 1
            continue
        # answerable
        if c.unique_citation_ids is None:
            n_evidence_missing += 1
            continue
        unique = c.unique_citation_ids
        supported = c.supported_citation_ids or 0
        total_unique += unique
        n_supported_ids += supported
        n_fabricated_ids += c.fabricated_citation_ids or 0
        n_not_in_context_ids += c.retrieved_not_in_context_ids or 0
        n_other_ids += c.other_status_ids or 0
        if unique > 0:
            n_with_any += 1
            if supported > 0:
                n_supported_answers += 1
            else:
                n_cited_unsupported += 1
        else:
            n_no_citation += 1

    n_answerable = n_with_any + n_no_citation + n_evidence_missing
    n_all = n_answerable + n_refused + n_error
    # 可计算行 = 有引用证据的可答行；缺证据行（v1 产物）的引用状态未知，
    # 不得把「未知」当作「不支持」计入分母（否则伪装为 0）——它们计入
    # excluded_count，并反映在 n_evidence_missing / excluded_reason 中。
    n_computable = n_with_any + n_no_citation

    metrics: dict[str, MetricValue] = {
        "context_supported_citation_validity_micro": MetricValue(
            name="context_supported_citation_validity_micro",
            denominator=DENOM_TOTAL_UNIQUE_CITATION_IDS,
            denominator_count=total_unique,
            numerator=n_supported_ids,
            excluded_count=n_no_citation + n_evidence_missing,
            excluded_reason=(
                "answers with no citation IDs or missing context evidence "
                "contribute 0 IDs to the total_unique_citation_ids denominator"),
            value=_rate(n_supported_ids, total_unique),
        ),
        "context_supported_answer_rate": MetricValue(
            name="context_supported_answer_rate",
            denominator=DENOM_ANSWERABLE_GENERATION_CASES,
            denominator_count=n_computable,
            numerator=n_supported_answers,
            excluded_count=n_refused + n_error + n_evidence_missing,
            excluded_reason=(
                "rows outside answerable_generation_cases (refused or error) "
                "or missing citation evidence (uncomputable, not counted as "
                "unsupported)"),
            value=_rate(n_supported_answers, n_computable),
        ),
        "no_citation_answer_rate": MetricValue(
            name="no_citation_answer_rate",
            denominator=DENOM_ANSWERABLE_GENERATION_CASES,
            denominator_count=n_computable,
            numerator=n_no_citation,
            excluded_count=n_refused + n_error + n_evidence_missing,
            excluded_reason=(
                "rows outside answerable_generation_cases (refused or error) "
                "or missing citation evidence (uncomputable)"),
            value=_rate(n_no_citation, n_computable),
        ),
        "citation_mention_rate": MetricValue(
            name="citation_mention_rate",
            denominator=DENOM_ANSWERABLE_GENERATION_CASES,
            denominator_count=n_computable,
            numerator=n_with_any,
            excluded_count=n_refused + n_error + n_evidence_missing,
            excluded_reason=(
                "rows outside answerable_generation_cases (refused or error) "
                "or missing citation evidence (uncomputable)"),
            value=_rate(n_with_any, n_computable),
        ),
    }

    agg = CitationAggregate(
        n_all_cases=n_all,
        n_refused=n_refused,
        n_error=n_error,
        n_answerable=n_answerable,
        n_evidence_missing=n_evidence_missing,
        n_with_any_citation=n_with_any,
        n_no_citation=n_no_citation,
        n_supported_answers=n_supported_answers,
        n_cited_but_unsupported_answers=n_cited_unsupported,
        total_unique_citation_ids=total_unique,
        n_supported_ids=n_supported_ids,
        n_fabricated_ids=n_fabricated_ids,
        n_retrieved_not_in_context_ids=n_not_in_context_ids,
        n_other_status_ids=n_other_ids,
        metrics=metrics,
    )
    agg.check_conservation()
    return agg


# ── guardrail 消费入口（旧字段隔离） ────────────────────────────────


def get_guardrail_metric(
    aggregate: CitationAggregate | Mapping[str, Any],
    name: str,
) -> float | None:
    """消费新 guardrail 指标的**唯一**入口。

    Args:
        aggregate: CitationAggregate 或 to_dict() 输出。
        name: 新指标名（NEW_GUARDRAIL_METRICS）。

    Returns:
        指标值；None = unavailable（分母为 0）。

    Raises:
        ValueError: 指标名为 legacy/deprecated 或未知——guardrail 禁止消费。
    """
    if name in LEGACY_METRIC_KEYS:
        raise ValueError(
            f"{name!r} is a legacy/deprecated metric; guardrail must consume "
            f"new contract metrics only: {NEW_GUARDRAIL_METRICS}")
    if name not in NEW_GUARDRAIL_METRICS:
        raise ValueError(f"unknown guardrail metric {name!r}")
    if isinstance(aggregate, CitationAggregate):
        metric = aggregate.metrics[name]
    else:
        metric = aggregate["metrics"][name]
    return metric["value"] if isinstance(metric, Mapping) else metric.value


# ── legacy 对账（deprecated，仅 reconcile 用） ───────────────────────


_LEGACY_FIELDS = (
    "legacy_citation_id_validity",
    "legacy_citation_precision",
    "legacy_citation_recall",
    "legacy_faithfulness",
    "legacy_context_supported_validity",
)


def legacy_mean_metric(
    counts: Sequence[CaseCitationCounts],
    field_name: str,
) -> float | None:
    """旧「全体 case 分母均值」计算（deprecated；仅历史产物对账使用）。

    与旧 compute_summary 的聚合口径一致：对全部行（含 refusal）取均值。
    新 guardrail 不得使用本函数——它只服务于 reconciliation 的旧值复算。

    Args:
        counts: case 级事实列表。
        field_name: CaseCitationCounts 的 legacy_* 字段名。

    Returns:
        均值；无任何行有该字段值 → None。
    """
    if field_name not in _LEGACY_FIELDS:
        raise ValueError(f"unknown legacy field {field_name!r}")
    values = [getattr(c, field_name) for c in counts
              if getattr(c, field_name) is not None]
    if not values:
        return None
    return sum(values) / len(values)
