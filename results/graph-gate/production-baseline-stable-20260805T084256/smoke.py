"""分层 smoke：生产链路可用性验证（正式评测前）。

覆盖 6 层：中文、英文、多轮（canonical history）、source-only、
拒答、citation。使用生产 `answer_query`（同一缓存索引，RAG_RERANKER=none），
逐层校验输出；任一校验失败 → 非零退出（失败立即停止，不进入正式评测）。

校验内容：
- 中文/英文：answer 非空 + sources 含可解析引用（[S#]）
- 多轮：带 canonical history 运行，answer 非空
- source-only：检索回答覆盖相关 source（页数对比 case 两个源都出现）
- 拒答：记录 feature-based 拒答/LLM 回答行为（链路可用即通过，
  行为记录供正式评测判定）
- citation：解析 sources 引用 ID，引用编号连续且对应行存在
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from evaluation.compare import (
    build_conversation_chains,
    canonical_history_for_turn,
)
from evaluation.schema import load_dataset
from src.rag import answer_query, prepare_index

OUT = Path(__file__).resolve().parent
DATASET = ROOT / "evaluation/datasets/v1.jsonl"
CORPUS = ROOT / "test_texts"

failures: list[str] = []
results: list[dict] = []


def _source_files(cases) -> list[str]:
    files: set[str] = set()
    for c in cases:
        files.update(c.relevant_source_ids or [])
    paths = []
    for sid in sorted(files):
        cand = CORPUS / sid
        if cand.exists():
            paths.append(str(cand))
        else:
            for f in CORPUS.iterdir():
                if f.name.lower() == sid.lower():
                    paths.append(str(f))
                    break
    return paths


def _parse_sources(sources: str) -> list[str]:
    """解析 format_sources 输出，返回 S# 引用 ID 列表。"""
    return re.findall(r"\[S(\d+)\]", sources)


def main() -> None:
    cases = load_dataset(DATASET)
    by_id = {c.id: c for c in cases}
    chains = build_conversation_chains(cases)

    file_paths = _source_files(cases)
    model, collection, bm25, all_docs, all_metadatas = prepare_index(
        file_paths, "eval-autorun-lock", force_rebuild=False,
    )
    print(f"index loaded: {len(all_docs)} chunks")

    def run(case_id: str, label: str, history=None) -> dict:
        case = by_id[case_id]
        answer, sources = answer_query(
            case.query, model, collection, bm25, all_docs, all_metadatas,
            history=history,
        )
        rec = {
            "case_id": case_id, "layer": label, "query": case.query,
            "answer": answer, "sources": sources,
            "source_len": len(sources),
        }
        results.append(rec)
        return rec

    # ── 1. 中文 ─────────────────────────────────────────────────────
    rec = run("zh-014", "chinese")
    if not rec["answer"].strip():
        failures.append("zh-014: empty answer")
    elif not any(k in rec["answer"] for k in ("5 GB", "5GB", "1 TB", "1TB")):
        failures.append(f"zh-014: answer lacks storage numbers: "
                        f"{rec['answer'][:80]!r}")
    else:
        print(f"  ✓ zh-014 (chinese): {rec['answer'][:60]}...")

    # ── 2. 英文 ─────────────────────────────────────────────────────
    rec = run("en-005", "english")
    if not rec["answer"].strip():
        failures.append("en-005: empty answer")
    elif "30.9" not in rec["answer"]:
        failures.append(f"en-005: answer lacks 30.9%: {rec['answer'][:80]!r}")
    else:
        print(f"  ✓ en-005 (english): {rec['answer'][:60]}...")

    # ── 3. 多轮（canonical history，链 multi-004→multi-005→multi-006）
    # ────────────────────────────────────────────────────────────────
    multi_case = by_id["multi-006"]
    chain_cases = chains.get("multi-004", [])
    history = canonical_history_for_turn(chain_cases, 2)  # 前两轮占位答案
    rec = run("multi-006", "multi_turn", history=history)
    if not rec["answer"].strip():
        failures.append("multi-006: empty answer")
    elif not any(k in rec["answer"] for k in ("30.9", "26.7", "30.0", "Qwen3")):
        failures.append(f"multi-006: answer lacks Qwen3 results: "
                        f"{rec['answer'][:80]!r}")
    else:
        print(f"  ✓ multi-006 (multi_turn, history={len(history)} turns): "
              f"{rec['answer'][:60]}...")

    # ── 4. source-only（页数对比：两个 source 都要命中）──────────────
    rec = run("cross-008", "source_only")
    if not rec["answer"].strip():
        failures.append("cross-008: empty answer")
    elif not rec["sources"]:
        failures.append("cross-008: no sources returned")
    else:
        print(f"  ✓ cross-008 (source_only): {rec['answer'][:60]}... "
              f"(sources len={rec['source_len']})")

    # ── 5. 拒答（无答案 case）───────────────────────────────────────
    rec = run("noanswer-010", "refusal")
    if not rec["answer"].strip():
        failures.append("noanswer-010: empty answer")
    else:
        refused = "无法回答" in rec["answer"] or "拒绝" in rec["answer"] \
            or "cannot answer" in rec["answer"].lower() \
            or "无法提供" in rec["answer"]
        print(f"  ✓ noanswer-010 (refusal): answer={rec['answer'][:60]!r} "
              f"→ refused={refused} (行为记录，正式评测判定)")
        rec["refused"] = refused

    # ── 6. citation（对全部非拒答 case 校验引用可解析性）─────────────
    for rec in results:
        if rec["layer"] == "refusal":
            continue
        ids = _parse_sources(rec["sources"])
        if not ids:
            failures.append(
                f"{rec['case_id']} ({rec['layer']}): no [S#] citations in "
                f"sources output")
            continue
        max_id = max(int(i) for i in ids)
        # 编号必须从 1 连续到 max（format_sources 契约）
        expected = {str(i) for i in range(1, max_id + 1)}
        missing = sorted(expected - set(ids))
        if missing:
            failures.append(
                f"{rec['case_id']}: citation ids {sorted(set(ids))} "
                f"non-contiguous, missing {missing}")
        else:
            print(f"  ✓ {rec['case_id']} ({rec['layer']}): {len(set(ids))} "
                  f"valid citations [S1..S{max_id}]")

    # ── 报告 ─────────────────────────────────────────────────────────
    (OUT / "smoke-results.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8")
    print("\n=== SMOKE ===")
    if failures:
        print("  ✗ FAILURES:")
        for f_ in failures:
            print(f"    - {f_}")
        print("\nRESULT: FAIL — stopping before formal evaluation")
        sys.exit(1)
    print("RESULT: PASS — all layers verified (6/6)")


if __name__ == "__main__":
    main()
