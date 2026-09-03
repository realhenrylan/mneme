"""Answer-hit mechanical metric (containment family) for Mneme RAG eval.

答案级评测线 M1 的机械下界指标：评测要点（acceptable_answer_points）
经空白/大小写归一后，是否被生成答案的归一文本**包含**。

口径（章程 M1 + owner 批示 2026-08-30）
--------------------------------------
- containment 族：``normalize(point) in normalize(answer)``——与
  stage2 parent-child run-3 仪器同族（大小写 + 空白归一），保证口径
  沿革可追溯（``metric_version = "al1-containment-v1"``）。
- 空要点**显式排除**：归一后为空的要点记 ``excluded_empty``，不计入
  分母——空白要点若留在分母会稀释命中率，属静默口径污染。
- ``answer_hit_rate = hit_count / effective_point_count``；有效要点数
  为 0（全空/无要点）时返回 ``None``（无可判定），聚合时跳过并单独
  计数，绝不把 None 当 0 分摊。
- 结构性局限（如实披露）：同义改写、中英互译、指代变换型要点会被
  系统性漏判——本指标只做**命中下界**，语义等价兜底留给 M3 受约束
  LLM judge（章程方案 B）。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

# 口径版本随 manifest 密封（沿用 parentchild_ab 的 metric_version 惯例）
ANSWER_HIT_METRIC_VERSION = "al1-containment-v1"

# 空白归一：任意连续空白（含换行/制表）折叠为单空格；strip 交由调用侧
# 归一函数末尾统一处理（re.sub 不去首尾）。
_WHITESPACE_RUN = re.compile(r"\s+")


def normalize_for_containment(text: str) -> str:
    """containment 判定的归一口径：小写化 + 连续空白折叠为单空格 + 去首尾。"""
    return _WHITESPACE_RUN.sub(" ", text).strip().lower()


@dataclass(frozen=True)
class PointVerdict:
    """单条要点的判定明细（可审计）。

    verdict: ``hit``（包含）/ ``miss``（未包含）/ ``excluded_empty``（空要点，
    不计分母）。
    """

    point_text: str
    normalized: str
    verdict: str


@dataclass(frozen=True)
class AnswerHitResult:
    """一个评测 case 的 answer-hit 判定结果。

    ``answer_hit_rate`` 在 ``effective_point_count == 0`` 时为 ``None``：
    表示"无可判定要点"，语义上区别于 0.0（有要点且全部未命中）。
    """

    point_results: tuple[PointVerdict, ...]
    hit_count: int
    effective_point_count: int
    answer_hit_rate: Optional[float]


def compute_answer_hit(
    answer: str,
    acceptable_answer_points: list[str],
) -> AnswerHitResult:
    """按 containment 口径判定生成答案对评测要点的覆盖。

    Args:
        answer: LLM 生成的答案文本。
        acceptable_answer_points: 人工终审确认的答案要点（v2.1 真值）。

    Returns:
        AnswerHitResult，含逐要点明细与聚合命中率（空要点显式排除）。
    """
    normalized_answer = normalize_for_containment(answer)

    point_results: list[PointVerdict] = []
    hit_count = 0
    effective_count = 0
    for point in acceptable_answer_points:
        normalized_point = normalize_for_containment(point)
        if not normalized_point:
            # 空要点显式排除：进明细留痕，但不参与分母
            point_results.append(PointVerdict(
                point_text=point, normalized=normalized_point,
                verdict="excluded_empty",
            ))
            continue
        effective_count += 1
        if normalized_point in normalized_answer:
            hit_count += 1
            point_results.append(PointVerdict(
                point_text=point, normalized=normalized_point, verdict="hit",
            ))
        else:
            point_results.append(PointVerdict(
                point_text=point, normalized=normalized_point, verdict="miss",
            ))

    rate: Optional[float] = (
        hit_count / effective_count if effective_count > 0 else None
    )
    return AnswerHitResult(
        point_results=tuple(point_results),
        hit_count=hit_count,
        effective_point_count=effective_count,
        answer_hit_rate=rate,
    )
