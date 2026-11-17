"""M6a 配对重放附录 preflight（2026-11-01 已签 addendum，Q2-a..d）。

只读校验，机械判定，任一失败 → 非零退出、不生成基线。校验项 =
任务书三、B 清单 + 后续阶段硬前提（输出目录不存在、chunks 语料在、
LLM 凭据可用——后者缺失会让 answer_query 逐例异常而 cases_failed=0，
150/150 capture 验收将无从谈起，故前置把关）。

输出 results/answer-level/m6a-paired-preflight-2026-11-01/preflight.json
（目录 fail-closed，拒绝已存在）。
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]

OUT_DIR = ROOT / "results" / "answer-level" / "m6a-paired-preflight-2026-11-01"

BASE_COMMIT = "746712d"
M6A_MODULE_COMMIT = "614e260"
M6A_MODULE_SHA256 = (
    "ee9963c76cbf580238b5914a3b1a34d6265bdd66a5bdbfeb3523a457bccc1613")
M4C_DIR = ROOT / "results" / "answer-level" / "m4c-arm2-2026-09-06"
M4C_OUTCOMES_SHA256 = (
    "157e86dc09d159419372dba78ee7d5951f9fef8b09925c8447f0394cc995667d")
M4C_REPORT_SHA256 = (
    "a8b8856b7ec09f3bce2b15892b35af543b64e56a32195830682b159fad61bed7")
M4C_MANIFEST_SELF_SHA256 = (
    "936d34bb9af6d368670d833777a0f6ee0877b2e98801fefd2f8d97f440c28b52")
DATASET_V21_SHA256 = (
    "4597167dadd72ba972373bedc44d27c858b7c7ddbe42f8ede9d37021b38e92a9")
DATASET_PATH = ROOT / "evaluation" / "datasets" / "v2.1.jsonl"
CHUNKS_PATH = ROOT / "data" / "v2-corpus" / "chunks" / "chunks.jsonl"

# 臂2 配置（M5d PASS 后 owner 批准的产品默认；预注册 §三）
ARM2_REFUSAL_THRESHOLD = 0.015
ARM2_DYNAMIC_MIN_K = 25
ARM2_CONTEXT_MAX_K = 25
ARM2_CONTEXT_TOKEN_BUDGET = 7000
ARM2_LLM_MODEL = "deepseek-chat"
ARM2_LLM_TEMPERATURE = 0.1

# 环境覆盖黑名单：任何一项被注入即非臂2
ENV_OVERRIDE_KEYS = (
    "RAG_REFUSAL_THRESHOLD", "RAG_DYNAMIC_MIN_K", "RAG_DYNAMIC_MAX_K",
    "RAG_CONTEXT_MAX_K", "RAG_CONTEXT_TOKEN_BUDGET", "LLM_TEMPERATURE",
)

# 后续阶段输出目录（全部必须尚不存在；生成/裁决侧 fail-closed）
STAGE_OUT_DIRS = (
    "m6a-paired-base-2026-11-01",
    "m6a-paired-2026-11-01",
    "m6a-paired-judge-2026-11-01",
    "m6a-paired-al3-round1-2026-11-01",
    "m6a-paired-al3-round2-2026-11-01",
)

CHECKS: list[dict[str, Any]] = []


def check(cid: str, name: str, ok: bool, detail: Any = None) -> bool:
    entry: dict[str, Any] = {"id": cid, "name": name, "ok": bool(ok)}
    if detail is not None:
        entry["detail"] = detail
    CHECKS.append(entry)
    mark = "PASS" if ok else "FAIL"
    print(f"[{mark}] {cid} {name}")
    if not ok and detail is not None:
        print(f"       {json.dumps(detail, ensure_ascii=False)[:800]}")
    return bool(ok)


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(Path(path).read_bytes())


def dump_body(obj: dict[str, Any]) -> str:
    """与 generation/judge runner 一致的自哈希序列化约定。"""
    return json.dumps(obj, ensure_ascii=False, indent=1, sort_keys=True) + "\n"


def git(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args], cwd=str(ROOT), capture_output=True,
        timeout=120,
    )


def load_json(path: Path) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    text = Path(path).read_text(encoding="utf-8")
    return [json.loads(line) for line in text.splitlines() if line.strip()]


def verify_manifest_self_hash(manifest: dict[str, Any]) -> bool:
    body = {k: v for k, v in manifest.items() if k != "manifest_sha256"}
    return sha256_bytes(dump_body(body).encode("utf-8")) == manifest.get(
        "manifest_sha256")


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=False)

    # ── 1. src/ 零改动（评测分支不得触碰产品代码） ──
    diff = git("diff", f"{BASE_COMMIT}..HEAD", "--", "src/")
    check("src_diff_empty",
          f"git diff {BASE_COMMIT}..HEAD -- src/ 为空",
          diff.returncode == 0 and not diff.stdout.strip(),
          {"stdout_len": len(diff.stdout),
           "stderr": diff.stderr.decode("utf-8", "replace")[:400]})

    # ── 2. M4c 三哈希（历史参照的完整性锚） ──
    outcomes_sha = sha256_file(M4C_DIR / "outcomes.jsonl")
    check("m4c_outcomes_sha256", "M4c outcomes.jsonl 文件哈希",
          outcomes_sha == M4C_OUTCOMES_SHA256,
          {"expected": M4C_OUTCOMES_SHA256, "actual": outcomes_sha})
    report_sha = sha256_file(M4C_DIR / "report.json")
    check("m4c_report_sha256", "M4c report.json 文件哈希",
          report_sha == M4C_REPORT_SHA256,
          {"expected": M4C_REPORT_SHA256, "actual": report_sha})
    manifest = load_json(M4C_DIR / "manifest.json")
    self_hash = manifest.get("manifest_sha256")
    check("m4c_manifest_self_hash", "M4c manifest 自哈希",
          self_hash == M4C_MANIFEST_SELF_SHA256
          and verify_manifest_self_hash(manifest),
          {"expected": M4C_MANIFEST_SELF_SHA256, "actual": self_hash})

    # ── 3. 从 M4c outcomes 复算 recall / precision ──
    m4c_rows = load_jsonl(M4C_DIR / "outcomes.jsonl")
    recalls = [r["citation_metrics"]["citation_recall"] for r in m4c_rows]
    precisions = [r["citation_metrics"]["citation_precision"] for r in m4c_rows]
    mean_recall = sum(recalls) / len(recalls)
    mean_precision = sum(precisions) / len(precisions)
    check("m4c_recall_recomputed",
          "M4c 复算 citation_recall 0.045556 -> 0.0456",
          round(mean_recall, 6) == 0.045556 and round(mean_recall, 4) == 0.0456,
          {"raw": mean_recall, "round6": round(mean_recall, 6),
           "round4": round(mean_recall, 4), "n": len(m4c_rows)})
    check("m4c_precision_recomputed",
          "M4c 复算 citation_precision 0.0400",
          round(mean_precision, 4) == 0.04,
          {"raw": mean_precision, "round4": round(mean_precision, 4),
           "n": len(m4c_rows)})

    # ── 4. dataset v2.1 哈希与规模 ──
    ds_sha = sha256_file(DATASET_PATH)
    check("dataset_v21_sha256", "dataset v2.1 SHA-256",
          ds_sha == DATASET_V21_SHA256,
          {"expected": DATASET_V21_SHA256, "actual": ds_sha})
    sys.path.insert(0, str(ROOT))
    from evaluation.schema import load_dataset  # noqa: E402
    cases = load_dataset(DATASET_PATH)
    check("dataset_case_count", "dataset v2.1 = 150 cases",
          len(cases) == 150, {"count": len(cases)})

    # ── 5. 配置 = 臂2（实效值 + 无环境覆盖） ──
    import src.config  # noqa: F401  （触发 .env 载入，覆盖检查才有意义）
    from src.config import get_settings
    settings = get_settings()
    check("config_refusal_threshold", "refusal = 0.015",
          settings.refusal_threshold == ARM2_REFUSAL_THRESHOLD,
          {"actual": settings.refusal_threshold})
    check("config_dynamic_min_k", "dynamic min = 25",
          settings.retrieval_dynamic_min_k == ARM2_DYNAMIC_MIN_K,
          {"actual": settings.retrieval_dynamic_min_k})
    rag_text = (ROOT / "src" / "rag.py").read_text(encoding="utf-8")
    check("config_context_max_k", "context max = 25",
          '_env_int_override("RAG_CONTEXT_MAX_K", 25)' in rag_text,
          {"source_literal": '_env_int_override(\"RAG_CONTEXT_MAX_K\", 25)'})
    check("config_context_token_budget", "budget = 7000",
          '_env_int_override("RAG_CONTEXT_TOKEN_BUDGET", 7000)' in rag_text,
          {"source_literal":
              '_env_int_override(\"RAG_CONTEXT_TOKEN_BUDGET\", 7000)'})
    overrides = {k: os.environ.get(k) for k in ENV_OVERRIDE_KEYS
                 if os.environ.get(k)}
    check("config_no_env_overrides", "无 RAG_*/LLM_* 覆盖注入",
          not overrides, overrides or None)
    check("config_llm_arm2",
          "LLM model=deepseek-chat, temperature=0.1",
          settings.llm_model == ARM2_LLM_MODEL
          and settings.llm_temperature == ARM2_LLM_TEMPERATURE,
          {"model": settings.llm_model,
           "temperature": settings.llm_temperature})
    api_key = os.getenv("API_KEY") or ""
    base_url = os.getenv("BASE_URL") or ""
    check("llm_credentials", "API_KEY/BASE_URL 可用",
          bool(api_key) and bool(base_url),
          {"api_key_masked": (api_key[:6] + "…") if api_key else None,
           "base_url": base_url or None})

    # ── 6. src/rag.py 无 M6a hook ──
    hook_hits = [kw for kw in ("citation_selection", "retarget_citations")
                 if kw in rag_text]
    check("rag_no_m6a_hook",
          "src/rag.py 无 citation_selection/retarget hook（grep 为空）",
          not hook_hits, {"hits": hook_hits} if hook_hits else None)

    # ── 7. M6a 模块 SHA（冻结实现，git show 614e260） ──
    blob = git("show", f"{M6A_MODULE_COMMIT}:src/citation_selection.py")
    module_sha = sha256_bytes(blob.stdout) if blob.returncode == 0 else None
    check("m6a_module_sha256",
          f"M6a 模块 SHA（git show {M6A_MODULE_COMMIT}:src/citation_selection.py）",
          module_sha == M6A_MODULE_SHA256,
          {"expected": M6A_MODULE_SHA256, "actual": module_sha})

    # ── 8. capture 默认 off ──
    from evaluation.generation_runner import GenerationResult  # noqa: E402
    gen_text = (ROOT / "evaluation" / "generation_runner.py").read_text(
        encoding="utf-8")
    gr_fields = {f.name: f for f in GenerationResult.__dataclass_fields__.values()}
    capture_defaults_empty = (
        gr_fields["full_sources"].default == ""
        and gr_fields["context_chunk_ids_ordered"].default_factory is list
    )
    cli_default_off = (
        '--capture-full-context", action="store_true", default=False'
        in gen_text)
    check("capture_default_off",
          "capture 默认关闭（CLI store_true default=False + 字段默认空）",
          capture_defaults_empty and cli_default_off,
          {"fields_default_empty": capture_defaults_empty,
           "cli_default_off": cli_default_off})

    # ── 9. 后续阶段输出目录必须不存在 + chunks 语料在 ──
    existing = [d for d in STAGE_OUT_DIRS
                if (ROOT / "results" / "answer-level" / d).exists()]
    check("stage_out_dirs_absent", "后续输出目录均不存在",
          not existing, {"existing": existing} if existing else None)
    check("chunks_store_present",
          "data/v2-corpus/chunks/chunks.jsonl 可解析且非空",
          CHUNKS_PATH.exists() and CHUNKS_PATH.stat().st_size > 0,
          {"path": str(CHUNKS_PATH),
           "bytes": CHUNKS_PATH.stat().st_size if CHUNKS_PATH.exists() else 0})

    ok = all(c["ok"] for c in CHECKS)
    preflight = {
        "stage": "m6a-paired-preflight",
        "protocol": "M6a paired replay addendum 2026-11-01 (signed)",
        "branch": subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=str(ROOT),
            capture_output=True, text=True, timeout=60).stdout.strip(),
        "base_commit": BASE_COMMIT,
        "head_commit": subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=str(ROOT),
            capture_output=True, text=True, timeout=60).stdout.strip(),
        "m6a_module_commit": M6A_MODULE_COMMIT,
        "m6a_module_sha256": module_sha,
        "dataset_sha256": ds_sha,
        "config": {
            "refusal_threshold": settings.refusal_threshold,
            "retrieval_dynamic_min_k": settings.retrieval_dynamic_min_k,
            "context_max_k": ARM2_CONTEXT_MAX_K,
            "context_token_budget": ARM2_CONTEXT_TOKEN_BUDGET,
            "llm_model": settings.llm_model,
            "llm_temperature": settings.llm_temperature,
        },
        "m4c_recomputed": {
            "citation_recall_raw": mean_recall,
            "citation_recall_round4": round(mean_recall, 4),
            "citation_precision_raw": mean_precision,
            "citation_precision_round4": round(mean_precision, 4),
        },
        "checks": CHECKS,
        "ok": ok,
    }
    (OUT_DIR / "preflight.json").write_text(
        dump_body(preflight), encoding="utf-8")
    print(f"\n[preflight] {'ALL PASS' if ok else 'FAILED'} "
          f"-> {OUT_DIR / 'preflight.json'}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
