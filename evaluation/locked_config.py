"""P1 locked-config 基础设施：版本化、确定性、无密钥的评测配置锁定。

评测方案 (plans/GRAPH-RAG-EVALUATION-PLAN-2026-08-02.md §4.4/§12) 要求：
alpha 在开发集网格扫描后锁定，holdout 只允许使用已锁定配置且不得回调。
本模块实现 fail-closed 的锁定流程：

1. **生成**（``build_locked_config``）：基于 development 结果显式选择单一
   alpha，连同 dataset/corpus/index/KG 指纹、模型与 prompt 标识、reranker、
   fusion/candidate/context/refusal 预算、seed 等可比性参数固化为
   locked-config.json。**绝不根据 holdout 结果自动选 alpha**。
2. **加载**（``load_locked_config``）：版本不支持、结构非法、budget 键集
   漂移均抛 ``LockedConfigError``，不做降级。
3. **校验**（``validate_locked_config``）：调用方按阶段提供运行时值
   （预检不提供 index/KG 指纹；后验提供），差异以字段名列表返回；
   缺失、版本不支持、指纹/参数不一致、alpha grid 不等于锁定值都明确失败。
   错误消息不泄露 secrets（``_safe_display`` 防御性脱敏）。

无密钥保证：lock 只含模型名、prompt 标识（SHA-256）、指纹、数值预算与
静态 provenance 文本，不写任何 URL/token/API key。

CLI
---
::

    # 生成（仅 development，必须显式 alpha）：
    python -m evaluation.compare --lock --alpha 0.7 --split development \
        --arms standard standard-rerank graph-rerank --corpus-dir test_texts \
        --dataset evaluation/datasets/v1.jsonl --output results/graph-gate/locked

    # holdout（必须显式提供 locked config，任何索引/LLM 工作前校验）：
    python -m evaluation.compare --split holdout --phase full \
        --config results/graph-gate/locked/locked-config.json --corpus-dir test_texts \
        --dataset evaluation/datasets/v1.jsonl --output results/graph-gate/holdout
"""

from __future__ import annotations

import hashlib
import inspect
import json
import os
from pathlib import Path
from typing import Any

from evaluation.compare import ARM_GRAPH_RERANK, SELECTOR_ABLATION_ARMS

LOCKED_CONFIG_VERSION = 1

# 顶层必需键（load 时检查，缺键即失败）
REQUIRED_LOCK_KEYS = (
    "version", "locked_alpha", "dataset", "dataset_sha256", "corpus_sha256",
    "index_sha256", "kg_sha256", "embedding_model", "llm_model",
    "reranker_mode", "reranker_model", "prompt_id", "arms", "seed",
    "budgets", "provenance",
)

# budgets 白名单键（键集漂移即失败；键序即确定性序列化顺序）
BUDGET_KEYS = (
    "candidate_top_k", "candidate_min_k", "candidate_max_k",
    "context_token_budget", "context_avg_chunk_tokens",
    "context_min_k", "context_max_k", "context_chunk_size",
    "context_chunk_overlap", "adjacent_max_expand",
    "source_diversity_max_per_source", "rerank_top_k",
    "fusion_rrf_k", "refusal_threshold", "generation_temperature",
)

# 防御性敏感词（错误消息/序列化兜底，正常 lock 不含这些内容）
_SENSITIVE_HINTS = (
    "api_key", "apikey", "token", "password", "secret",
    "authorization", "credential", "://", "@",
)

# 校验哨兵：调用方未提供该阶段字段（跳过该项检查）
_UNSET = object()


def _is_full_sha256(value: Any) -> bool:
    """是否为完整 64 位小写 hex SHA-256（指纹合法格式）。"""
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(c in "0123456789abcdef" for c in value)
    )


def _kg_fingerprint_required(arms: list[str], locked_alpha: float) -> bool:
    """KG 指纹是否必须锁定：graph-rerank 臂且 locked_alpha < 1.0。

    alpha=1.0 时 C 臂完全跳过 Graph 通道（与 B 无差异），KG 指纹
    not-applicable；非图实验同样 not-applicable。
    """
    return ARM_GRAPH_RERANK in arms and locked_alpha < 1.0


class LockedConfigError(ValueError):
    """locked-config 加载/校验失败（携带差异描述列表）。"""

    def __init__(self, diffs: list[str]):
        super().__init__("; ".join(diffs))
        self.diffs = list(diffs)


def _safe_display(value: Any) -> str:
    """显示值前的防御性脱敏（正常 lock 字段不含敏感内容）。"""
    s = str(value)
    low = s.lower()
    if any(h in low for h in _SENSITIVE_HINTS):
        return "***REDACTED***"
    return s


# ── 运行时环境采集（本地常量，不触发模型/网络加载） ──────────────────

def collect_runtime_models() -> dict[str, str | None]:
    """读取当前模型与 prompt 标识（与 build_run_manifest 同口径）。"""
    from src.rag import (
        DEFAULT_LLM_MODEL,
        EMBEDDING_MODEL_NAME,
        PROMPT_TEMPLATE,
        RAG_RERANKER_MODE,
        RERANKER_MODEL_NAME,
        SYSTEM_PROMPT,
    )
    prompt_id = hashlib.sha256(
        (SYSTEM_PROMPT + "\n" + PROMPT_TEMPLATE).encode("utf-8"),
    ).hexdigest()
    return {
        "embedding_model": EMBEDDING_MODEL_NAME,
        "llm_model": os.getenv("LLM_MODEL", DEFAULT_LLM_MODEL),
        "reranker_mode": RAG_RERANKER_MODE,
        "reranker_model": RERANKER_MODEL_NAME,
        "prompt_id": prompt_id,
    }


def default_refusal_policy_by_arm(arms: list[str]) -> dict[str, str]:
    """运行时默认的 per-arm 拒答策略映射（评测按臂覆盖 RAG_REFUSAL_POLICY）。

    拒答策略消融臂（standard-calibrated）→ evidence_calibrated；
    其余臂 → baseline（生产默认不变）。build/validate 与运行时共用，
    臂映射漂移（新增/改名臂）会在锁校验阶段 fail-closed 拒绝。
    """
    from src.rag import (
        REFUSAL_POLICY_BASELINE,
        REFUSAL_POLICY_EVIDENCE_CALIBRATED,
    )

    return {
        arm: (REFUSAL_POLICY_EVIDENCE_CALIBRATED
              if arm.endswith("-calibrated") else REFUSAL_POLICY_BASELINE)
        for arm in arms
    }


def compute_effective_prompt_ids(policy_by_arm: dict[str, str]) -> dict[str, str]:
    """每臂「实际 system prompt + policy addendum + PROMPT_TEMPLATE」的 SHA-256。

    与 build/validate 共用同一来源（src.rag.system_prompt_for_policy）——
    策略正文（addendum 文本）、策略名或臂映射任一漂移都会改变指纹，
    锁校验（validate_locked_config）在 LLM 前 fail-closed 拒绝。
    旧 prompt_id（基础 SYSTEM_PROMPT + PROMPT_TEMPLATE）仅保留为历史
    兼容，不作为拒答策略消融实验的提示词锁。
    """
    from src.rag import PROMPT_TEMPLATE, system_prompt_for_policy

    return {
        arm: hashlib.sha256(
            (system_prompt_for_policy(policy) + "\n" + PROMPT_TEMPLATE)
            .encode("utf-8"),
        ).hexdigest()
        for arm, policy in policy_by_arm.items()
    }


def collect_runtime_budgets() -> dict[str, Any]:
    """读取当前影响可比性的预算参数（确定性键序）。

    来源：src.rag 常量、src.domain.compute_context_k 默认参数、compare.py
    中硬编码的融合/扩展参数（RRF k=60、adjacent max_expand=2 等）。
    """
    from src.domain import compute_context_k
    from src.rag import (
        DEFAULT_CHUNK_OVERLAP,
        DEFAULT_CHUNK_SIZE,
        DEFAULT_MAX_K,
        DEFAULT_MIN_K,
        DEFAULT_REFUSAL_THRESHOLD,
        DEFAULT_TEMPERATURE,
        DEFAULT_TOP_K,
        SELECTOR_MAX_PER_SOURCE,
    )
    sig = inspect.signature(compute_context_k)
    return {
        "candidate_top_k": DEFAULT_TOP_K,
        "candidate_min_k": DEFAULT_MIN_K,
        "candidate_max_k": DEFAULT_MAX_K,
        "context_token_budget": sig.parameters["token_budget"].default,
        "context_avg_chunk_tokens": sig.parameters["avg_chunk_tokens"].default,
        "context_min_k": sig.parameters["min_k"].default,
        "context_max_k": sig.parameters["max_k"].default,
        "context_chunk_size": DEFAULT_CHUNK_SIZE,
        "context_chunk_overlap": DEFAULT_CHUNK_OVERLAP,
        "adjacent_max_expand": 2,
        # 全局默认同源上限（生产默认 3；selector 消融时 per-arm 策略以
        # lock 的 arm_selector_policy 为准，本字段反映全局运行时默认值）
        "source_diversity_max_per_source": SELECTOR_MAX_PER_SOURCE,
        "rerank_top_k": 20,
        "fusion_rrf_k": 60,
        "refusal_threshold": DEFAULT_REFUSAL_THRESHOLD,
        "generation_temperature": DEFAULT_TEMPERATURE,
    }


# ── 生成 ─────────────────────────────────────────────────────────────

def build_locked_config(
    *,
    locked_alpha: float,
    dataset_name: str,
    dataset_sha256: str,
    corpus_sha256: str,
    seed: int,
    arms: list[str],
    embedding_model: str,
    llm_model: str,
    reranker_mode: str,
    reranker_model: str | None,
    prompt_id: str,
    budgets: dict[str, Any],
    index_sha256: str | None = None,
    kg_sha256: str | None = None,
    split_fingerprint: str | None = None,
    decision_notes: str = "",
    arm_selector_policy: dict[str, int | None] | None = None,
    refusal_policy: dict[str, str] | None = None,
    effective_prompt_ids: dict[str, str] | None = None,
) -> dict[str, Any]:
    """构建 locked-config 字典（确定性：同输入 → 同字节）。

    locked_alpha 必须由调用方（CLI --alpha）显式提供——本函数不读取
    任何评测结果，绝不自动选 alpha。

    split_fingerprint：dev/holdout 拆分的 canonical SHA-256（来自
    compare.compute_split_fingerprint），**必填**（fail-closed——新锁必须
    锁定 split，dataset/seed/split 算法变化导致的集合漂移在运行前拒绝）。
    旧锁（无该键）加载时向后兼容（见 load_locked_config）。

    arm_selector_policy：每臂 context selector 同源上限（None = 不限同源；
    正数 = 每源最多 N）。selector 消融（S0/S3）运行时必须提供并在
    validate 阶段逐臂比对（fail-closed 防配置漂移）；未提供时 lock 不含
    该键（旧 A/B/C 锁向后兼容）。

    指纹强制（fail-closed，无 null 绕过路径）：
    - index_sha256 任何臂都必须为完整 64 位 SHA-256；
    - kg_sha256 仅当 arms 含 graph-rerank 且 locked_alpha<1.0 时必须为
      完整 64 位 SHA-256；否则可为 None（not-applicable，如非图或
      alpha=1.0 时 C 臂不经过 Graph 通道）。
    快照无法计算（None/坏格式）时抛 ValueError，调用方不得降级写锁。
    """
    if not _is_full_sha256(index_sha256):
        raise ValueError(
            "index_sha256 must be a full 64-char SHA-256 "
            "(index fingerprint is never skippable)",
        )
    if not _is_full_sha256(split_fingerprint):
        raise ValueError(
            "split_fingerprint must be a full 64-char SHA-256 "
            "(split determinism must be locked)",
        )
    # 生成阶段拒答策略（per-arm）与有效提示指纹：新锁必填（fail-closed——
    # 策略正文/策略名/臂映射任一漂移都在 LLM 前拒绝）。旧锁无这两键时
    # 向后兼容加载（load/validate 跳过），但新实验不得只用旧 prompt_id。
    from src.rag import REFUSAL_POLICIES as _REFUSAL_POLICIES
    if refusal_policy is None:
        raise ValueError(
            "refusal_policy must be provided (per-arm generation refusal "
            "policy must be locked)",
        )
    if set(refusal_policy) != set(arms):
        raise ValueError(
            f"refusal_policy keys must exactly match arms "
            f"(keys={sorted(refusal_policy)}, arms={sorted(arms)})",
        )
    bad_policies = sorted(
        arm for arm, p in refusal_policy.items() if p not in _REFUSAL_POLICIES)
    if bad_policies:
        raise ValueError(
            f"refusal_policy contains invalid policy value(s) for arms "
            f"{bad_policies}; must be one of {_REFUSAL_POLICIES}",
        )
    if effective_prompt_ids is None:
        raise ValueError(
            "effective_prompt_ids must be provided (per-arm effective prompt "
            "fingerprint must be locked)",
        )
    if set(effective_prompt_ids) != set(arms):
        raise ValueError(
            f"effective_prompt_ids keys must exactly match arms "
            f"(keys={sorted(effective_prompt_ids)}, arms={sorted(arms)})",
        )
    bad_ids = sorted(
        arm for arm, v in effective_prompt_ids.items() if not _is_full_sha256(v))
    if bad_ids:
        raise ValueError(
            f"effective_prompt_ids value(s) for arms {bad_ids} must be full "
            f"64-char SHA-256",
        )
    if _kg_fingerprint_required(list(arms), float(locked_alpha)):
        if not _is_full_sha256(kg_sha256):
            raise ValueError(
                "kg_sha256 must be a full 64-char SHA-256 for graph-rerank "
                "arm with locked_alpha<1.0",
            )
    cfg: dict[str, Any] = {
        "version": LOCKED_CONFIG_VERSION,
        "locked_alpha": float(locked_alpha),
        "dataset": dataset_name,
        "dataset_sha256": dataset_sha256,
        "corpus_sha256": corpus_sha256,
        "index_sha256": index_sha256,
        "kg_sha256": kg_sha256,
        "split_fingerprint": split_fingerprint,
        "embedding_model": embedding_model,
        "llm_model": llm_model,
        "reranker_mode": reranker_mode,
        "reranker_model": reranker_model,
        "prompt_id": prompt_id,
        "refusal_policy": dict(refusal_policy),
        "effective_prompt_ids": dict(effective_prompt_ids),
        "arms": sorted(arms),
        "seed": seed,
        "budgets": {key: budgets[key] for key in BUDGET_KEYS},
        "provenance": {
            "source": "development evaluation (alpha grid scan)",
            "locked_alpha_selected_from": (
                "development split only; never re-selected from holdout results"
            ),
            "decision_notes": decision_notes,
            "generated_by": "evaluation.locked_config",
        },
    }
    if arm_selector_policy is not None:
        cfg["arm_selector_policy"] = dict(arm_selector_policy)
    return cfg


def save_locked_config(config: dict[str, Any], path: Path) -> None:
    """确定性落盘 locked-config.json（indent=2 + 末尾换行）。"""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(config, f, ensure_ascii=False, indent=2)
        f.write("\n")


# ── 加载 ─────────────────────────────────────────────────────────────

def load_locked_config(path: Path) -> dict[str, Any]:
    """读取 locked-config.json；版本/结构非法 → LockedConfigError。

    fail-closed：版本不支持、非对象根、缺少必需键、budgets 键集漂移、
    locked_alpha 非数值均直接失败，不做任何降级。

    指纹强制：index_sha256 必须为完整 64 位 SHA-256（任何臂都不得绕过）；
    kg_sha256 允许 None（not-applicable，按 arms+alpha 在 validate 判定）
    或完整 64 位 SHA-256。缺失/None/坏格式在加载阶段即拒绝，错误只
    展示字段名，不打印值。
    """
    path = Path(path)
    try:
        with open(path, "r", encoding="utf-8") as f:
            raw = json.load(f)
    except (OSError, json.JSONDecodeError) as exc:
        raise LockedConfigError([f"unreadable locked config: {exc}"]) from exc
    if not isinstance(raw, dict):
        raise LockedConfigError(["locked config root must be a JSON object"])
    version = raw.get("version")
    if version != LOCKED_CONFIG_VERSION:
        raise LockedConfigError([
            f"unsupported locked config version: {_safe_display(version)} "
            f"(supported: {LOCKED_CONFIG_VERSION})",
        ])
    missing = [k for k in REQUIRED_LOCK_KEYS if k not in raw]
    if missing:
        raise LockedConfigError([f"missing field: {k}" for k in sorted(missing)])
    budgets = raw.get("budgets")
    if not isinstance(budgets, dict):
        raise LockedConfigError(["budgets must be a JSON object"])
    extra = sorted(set(budgets) - set(BUDGET_KEYS))
    missing_b = sorted(set(BUDGET_KEYS) - set(budgets))
    if extra or missing_b:
        raise LockedConfigError([
            f"budgets keys mismatch (extra={extra}, missing={missing_b})",
        ])
    alpha = raw.get("locked_alpha")
    if isinstance(alpha, bool) or not isinstance(alpha, (int, float)):
        raise LockedConfigError(["locked_alpha must be a number"])
    if not _is_full_sha256(raw.get("index_sha256")):
        raise LockedConfigError([
            "index_sha256: must be a full 64-char SHA-256 "
            "(index fingerprint is required for every run)",
        ])
    kg_sha = raw.get("kg_sha256")
    if kg_sha is not None and not _is_full_sha256(kg_sha):
        raise LockedConfigError([
            "kg_sha256: must be null or a full 64-char SHA-256",
        ])
    # split_fingerprint：新锁必填（build 强制）；旧锁（无该键）向后兼容
    # 加载，仅当存在时校验格式（validate 阶段决定是否比对）
    split_fp = raw.get("split_fingerprint")
    if split_fp is not None and not _is_full_sha256(split_fp):
        raise LockedConfigError([
            "split_fingerprint: must be null or a full 64-char SHA-256",
        ])
    # arm_selector_policy（可选键，向后兼容旧 A/B/C 锁）：存在时必须为
    # dict，键为臂名，值为 null（不限同源）或 int>=1（每源上限）。
    # 0/负数/字符串/布尔在加载阶段即拒绝（0 的 unlimited 语义必须写 null）。
    policy = raw.get("arm_selector_policy")
    if policy is not None:
        if not isinstance(policy, dict):
            raise LockedConfigError(["arm_selector_policy must be a JSON object"])
        bad: list[str] = []
        for k, v in policy.items():
            if not isinstance(k, str):
                bad.append("arm_selector_policy: key must be a string")
                continue
            if isinstance(v, bool) or not (
                v is None or (isinstance(v, int) and v >= 1)
            ):
                bad.append(
                    f"arm_selector_policy.{_safe_display(k)}: must be null "
                    f"or int >= 1 (0 means unlimited; use null)",
                )
        if bad:
            raise LockedConfigError(bad)
    # refusal_policy / effective_prompt_ids（拒答策略消融新锁必含；旧锁无
    # 键向后兼容加载）：存在时必须为 dict、键集与 arms 一致、值合法。
    from src.rag import REFUSAL_POLICIES as _REFUSAL_POLICIES
    arms_in_lock = raw.get("arms", [])
    rp = raw.get("refusal_policy")
    if rp is not None:
        if not isinstance(rp, dict):
            raise LockedConfigError(["refusal_policy must be a JSON object"])
        if set(rp) != set(arms_in_lock):
            raise LockedConfigError([
                "refusal_policy keys must exactly match arms",
            ])
        bad_rp = [a for a, p in rp.items() if p not in _REFUSAL_POLICIES]
        if bad_rp:
            raise LockedConfigError([
                f"refusal_policy.{_safe_display(a)}: invalid policy value "
                f"(must be one of {_REFUSAL_POLICIES})" for a in bad_rp
            ])
    epi = raw.get("effective_prompt_ids")
    if epi is not None:
        if not isinstance(epi, dict):
            raise LockedConfigError(["effective_prompt_ids must be a JSON object"])
        if set(epi) != set(arms_in_lock):
            raise LockedConfigError([
                "effective_prompt_ids keys must exactly match arms",
            ])
        bad_epi = [a for a, v in epi.items() if not _is_full_sha256(v)]
        if bad_epi:
            raise LockedConfigError([
                f"effective_prompt_ids.{_safe_display(a)}: must be a full "
                f"64-char SHA-256" for a in bad_epi
            ])
    return raw


# ── 校验（fail-closed） ──────────────────────────────────────────────

def validate_locked_config(
    lock: dict[str, Any],
    *,
    dataset_name: Any = _UNSET,
    dataset_sha256: Any = _UNSET,
    corpus_sha256: Any = _UNSET,
    seed: Any = _UNSET,
    arms: Any = _UNSET,
    alpha_grid: Any = _UNSET,
    embedding_model: Any = _UNSET,
    llm_model: Any = _UNSET,
    reranker_mode: Any = _UNSET,
    reranker_model: Any = _UNSET,
    prompt_id: Any = _UNSET,
    budgets: Any = _UNSET,
    index_sha256: Any = _UNSET,
    kg_sha256: Any = _UNSET,
    split_fingerprint: Any = _UNSET,
    arm_selector_policy: Any = _UNSET,
    refusal_policy: Any = _UNSET,
    effective_prompt_ids: Any = _UNSET,
) -> list[str]:
    """fail-closed 校验锁定配置，返回差异描述列表（空列表 = 放行）。

    阶段语义：
    - 预检（任何索引/LLM 工作前）：提供除 index/KG 指纹外的全部运行时值；
      此阶段按 arms+alpha 判定 KG 指纹适用性（graph-rerank + alpha<1 时
      kg_sha256 必须已锁定）；含 selector 消融臂时 arm_selector_policy
      必须已锁定且与运行时逐臂一致。
    - 后验（索引/KG 构建后）：只提供 index_sha256 / kg_sha256 指纹。
    - 未提供（_UNSET）的字段跳过检查。
    - index 指纹在 load 已强制完整 64 位 SHA-256；后验时运行时指纹不可得
      （None）或不等 → 拒绝（任何臂都不得绕过）。
    - kg 指纹：lock 未锁定（None，not-applicable）时后验跳过比对；
      已锁定则运行时不可得（None）或不等 → 拒绝。
    - alpha_grid 若提供（非 None）必须恰好等于 [locked_alpha]。
    """
    diffs: list[str] = []

    def _check(field: str, lock_value: Any, run_value: Any) -> None:
        if run_value is _UNSET:
            return  # 本阶段不校验该字段
        if lock_value != run_value:
            diffs.append(
                f"{field}: lock={_safe_display(lock_value)} "
                f"run={_safe_display(run_value)}",
            )

    _check("dataset", lock.get("dataset"), dataset_name)
    _check("dataset_sha256", lock.get("dataset_sha256"), dataset_sha256)
    _check("corpus_sha256", lock.get("corpus_sha256"), corpus_sha256)
    _check("seed", lock.get("seed"), seed)
    # arms 需排序归一化；_UNSET 哨兵必须在 transform 前拦截
    if arms is not _UNSET:
        _check("arms", lock.get("arms"), sorted(arms))
        # KG 指纹适用性（预检：arms 已知）：graph-rerank + alpha<1 时
        # kg_sha256 不得为 null —— 不得让图 holdout 以 null KG 指纹通过。
        if lock.get("kg_sha256") is None and _kg_fingerprint_required(
            sorted(arms), lock.get("locked_alpha"),
        ):
            diffs.append(
                "kg_sha256: required (graph-rerank arm with locked_alpha<1.0) "
                "but not locked",
            )
        # per-arm selector policy：含 selector 消融臂时 lock 必须已记录
        #（fail-closed——无 policy 的 lock 无法防 S0/S3 配置漂移）。
        if lock.get("arm_selector_policy") is None and any(
            a in SELECTOR_ABLATION_ARMS for a in arms
        ):
            diffs.append(
                "arm_selector_policy: required (selector ablation arms in "
                "run) but not locked",
            )
    _check("embedding_model", lock.get("embedding_model"), embedding_model)
    _check("llm_model", lock.get("llm_model"), llm_model)
    _check("reranker_mode", lock.get("reranker_mode"), reranker_mode)
    _check("reranker_model", lock.get("reranker_model"), reranker_model)
    # prompt_id 为可选增强锁定：lock 未锁定则不校验
    if lock.get("prompt_id") is not None and prompt_id is not _UNSET:
        _check("prompt_id", lock.get("prompt_id"), prompt_id)

    # budgets 逐键对比（键集已在 load 时白名单校验）
    if budgets is not _UNSET:
        lock_budgets = lock.get("budgets", {})
        for key in BUDGET_KEYS:
            lv = lock_budgets.get(key)
            rv = budgets.get(key)
            if lv != rv:
                diffs.append(
                    f"budgets.{key}: lock={_safe_display(lv)} "
                    f"run={_safe_display(rv)}",
                )

    # per-arm selector policy 逐臂比对（已锁定时；_UNSET 跳过——后验阶段）
    if arm_selector_policy is not _UNSET:
        locked_policy = lock.get("arm_selector_policy")
        if locked_policy is not None and arm_selector_policy != locked_policy:
            diffs.append(
                f"arm_selector_policy: lock={_safe_display(locked_policy)} "
                f"run={_safe_display(arm_selector_policy)}",
            )

    # alpha：grid 必须恰好等于锁定值；None（未提供）表示采用锁定值，放行
    if alpha_grid is not _UNSET and alpha_grid is not None:
        if not (isinstance(alpha_grid, (list, tuple))
                and len(alpha_grid) == 1
                and alpha_grid[0] == lock.get("locked_alpha")):
            diffs.append(
                f"alpha: locked_alpha={_safe_display(lock.get('locked_alpha'))} "
                f"run grid={_safe_display(alpha_grid)}",
            )

    # index/KG 指纹：lock 未锁定（None）跳过；运行时可算时必须相等；
    # 锁定但运行时不可得（None）→ 拒绝（无法验证，fail-closed）
    if lock.get("index_sha256") is not None and index_sha256 is not _UNSET:
        if index_sha256 is None:
            diffs.append("index_sha256: locked but not computable at run time")
        elif index_sha256 != lock["index_sha256"]:
            diffs.append(
                f"index_sha256: lock={_safe_display(lock['index_sha256'])} "
                f"run={_safe_display(index_sha256)}",
            )
    if lock.get("kg_sha256") is not None and kg_sha256 is not _UNSET:
        if kg_sha256 is None:
            diffs.append("kg_sha256: locked but not computable at run time")
        elif kg_sha256 != lock["kg_sha256"]:
            diffs.append(
                f"kg_sha256: lock={_safe_display(lock['kg_sha256'])} "
                f"run={_safe_display(kg_sha256)}",
            )
    # split 指纹：新锁必含（build 强制）；锁已锁定时运行时不可得（None）
    # 或不等 → 拒绝（dataset/seed/split 算法漂移 fail-closed）。旧锁无该
    # 键（legacy）→ 跳过比对，仅保证可加载（历史锁审计兼容）。
    if lock.get("split_fingerprint") is not None and split_fingerprint is not _UNSET:
        if split_fingerprint is None:
            diffs.append(
                "split_fingerprint: locked but not computable at run time",
            )
        elif split_fingerprint != lock["split_fingerprint"]:
            diffs.append(
                f"split_fingerprint: lock="
                f"{_safe_display(lock['split_fingerprint'])} "
                f"run={_safe_display(split_fingerprint)}",
            )

    # 生成拒答策略与有效提示指纹（拒答策略消融新锁必含；旧锁无键跳过）。
    # effective_prompt_ids 由调用方以 compute_effective_prompt_ids 重算
    # 传入——策略正文（addendum 文本）、策略名或臂映射任一漂移都会使
    # 指纹不等 → fail-closed 拒绝（任何 LLM 调用前）。
    if lock.get("refusal_policy") is not None and refusal_policy is not _UNSET:
        if refusal_policy is None:
            diffs.append(
                "refusal_policy: locked but not computable at run time",
            )
        elif refusal_policy != lock["refusal_policy"]:
            diffs.append(
                f"refusal_policy: lock={_safe_display(lock['refusal_policy'])} "
                f"run={_safe_display(refusal_policy)}",
            )
    if (lock.get("effective_prompt_ids") is not None
            and effective_prompt_ids is not _UNSET):
        if effective_prompt_ids is None:
            diffs.append(
                "effective_prompt_ids: locked but not computable at run time",
            )
        elif effective_prompt_ids != lock["effective_prompt_ids"]:
            diffs.append(
                "effective_prompt_ids: lock="
                f"{_safe_display(lock['effective_prompt_ids'])} "
                f"run={_safe_display(effective_prompt_ids)}",
            )

    return diffs
