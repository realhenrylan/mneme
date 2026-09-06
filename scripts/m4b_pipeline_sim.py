"""M4b 管道模拟：生产完整管道（select/扩展/reconcile/context）零 LLM 重放。

区别于此前的候选面侦查（`m4b_retrieval_recon.py`，只到融合面）：本脚本
走 `prepare_answer_evidence` 的 **query_plan 重放路径**（检索结果由本地
重放注入 plan，零 LLM 规划），以真实生产函数执行：
dynamic_top_k → select_context_candidates（max_per_source=3）→
expand_with_parent/adjacent → reconcile → _build_context。

用途（M4b 预注册的「预期机制」数值化）：
- 配置 A（生产默认）重放缺口率 ↔ 与 M2 实测 0.8115 对照（差 = rewrite 差异）；
- 配置 B（臂2 V3 档位：RAG_DYNAMIC_MIN_K=25 / max_k=25 / budget=7000）→
  臂2 P1 预期；→
- 配置 C（A + 不限同源 max_per_source=None）：多样性挤占量化（诊断）。

用法::

    python scripts/m4b_pipeline_sim.py [--out results/answer-level/m4b-pipe-sim.scratch.jsonl]
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from evaluation.generation_runner import _normalize_chunk_id  # noqa: E402


# 配置（实验语义绑定 M4b §3.1；未标注"诊断"的为臂定义）
CONFIGS = {
    "A_prod_default": {"RAG_DYNAMIC_MIN_K": None, "RAG_DYNAMIC_MAX_K": None,
                       "RAG_CONTEXT_MAX_K": None, "RAG_CONTEXT_TOKEN_BUDGET": None,
                       "max_per_source": None,  # None=模块默认（生产=3）
                       },
    "B_arm2_selector": {"RAG_DYNAMIC_MIN_K": "25", "RAG_DYNAMIC_MAX_K": None,
                        "RAG_CONTEXT_MAX_K": "25", "RAG_CONTEXT_TOKEN_BUDGET": "7000",
                        "max_per_source": None,
                        },
    "C_unlimited_source_diag": {"RAG_DYNAMIC_MIN_K": None, "RAG_DYNAMIC_MAX_K": None,
                                "RAG_CONTEXT_MAX_K": None, "RAG_CONTEXT_TOKEN_BUDGET": None,
                                "max_per_source": "unlimited",  # 诊断：量化同源挤占
                                },
}


def _apply_config(cfg_name: str, rag_module) -> None:
    # 先全量重置所有受控通道（配置间残余清零），再应用目标配置。
    for key in ("RAG_DYNAMIC_MIN_K", "RAG_DYNAMIC_MAX_K",
                "RAG_CONTEXT_MAX_K", "RAG_CONTEXT_TOKEN_BUDGET"):
        os.environ.pop(key, None)
    rag_module.SELECTOR_MAX_PER_SOURCE = 3  # 生产默认（env 无覆盖时）

    cfg = CONFIGS[cfg_name]
    for key, value in cfg.items():
        if key.startswith("RAG_"):
            if value is not None:
                os.environ[key] = value
        else:
            if value == "unlimited":
                rag_module.SELECTOR_MAX_PER_SOURCE = None
            elif value is not None:
                rag_module.SELECTOR_MAX_PER_SOURCE = int(value)


def build_index(corpus_dir: Path, dataset_path: Path, chroma_path: Path):
    from scripts.m4b_retrieval_recon import build_index as recon_build_index

    return recon_build_index(corpus_dir, dataset_path, chroma_path, "m4b_pipe_sim")


def run_config(cases, model, collection, bm25, docs, metadatas, cfg_name: str,
               top_k: int = 300) -> list[dict]:
    import src.rag as rag

    _apply_config(cfg_name, rag)
    # 模块级常量随 Settings 刷新语义 vs 直接 env：RAG_CONTEXT/EXPANSION 为
    # 常量——这里依赖本脚本进程内"先于任何 prepare 调用"的干净 env（进程
    # 单启动、逐配置串行、配置间还原 env 残余已由 _apply_config 全量覆盖）。
    rows = []
    for case in cases:
        cid = case["id"] if "id" in case else case.get("case_id", "")
        query = case["query"]
        truth = {_normalize_chunk_id(x) for x in (case.get("relevant_chunk_ids") or [])}
        if not truth:
            continue

        sink: dict = {}
        indices, _, scores = rag.retrieve_hybrid_with_sources(
            query, model, collection, bm25, docs, metadatas,
            k=top_k, _channel_sink=sink,
        )
        # 索引下标 → RRF 分数映射（plan base_candidates；与检索等价）
        base = {i: float(s) for i, s in zip(indices, scores)}
        plan = SimpleNamespace(
            rewritten_query=query, rewrite_log={"changed": False},
            sub_queries=[query], base_candidates=base,
        )
        ev = rag.prepare_answer_evidence(
            query, model, collection, bm25, docs, metadatas, query_plan=plan,
        )
        ctx_norm = {_normalize_chunk_id(x) for x in ev.context_chunk_ids}
        rows.append({
            "case_id": cid,
            "config": cfg_name,
            "candidate_count": len(base),
            "context_k": ev.context_k,
            "truth_in_context": bool(ctx_norm & truth),
            "truth_count": len(truth),
            "refused": ev.refused,
        })
    return rows


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default="results/answer-level/m4b-pipe-sim.scratch.jsonl")
    parser.add_argument("--configs", nargs="*", default=list(CONFIGS),
                        help="要跑的配置名（默认全部）")
    args = parser.parse_args(argv)

    corpus_dir = Path("data/v2-corpus/documents/processed")
    dataset_path = Path("evaluation/datasets/v2.1.jsonl")

    with open(dataset_path, encoding="utf-8") as f:
        cases = [json.loads(line) for line in f]
    print(f"[pipe-sim] cases={len(cases)} configs={args.configs}")

    with tempfile.TemporaryDirectory(
        prefix="mneme-m4b-pipe-", ignore_cleanup_errors=True) as tmp:
        chroma_path = Path(tmp) / "chroma_db"
        model, collection, bm25, docs, metadatas = build_index(
            corpus_dir, dataset_path, chroma_path)
        all_rows = []
        for cfg_name in args.configs:
            rows = run_config(cases, model, collection, bm25, docs, metadatas, cfg_name)
            all_rows.extend(rows)
            n = len(rows)
            gap = sum(1 for r in rows if not r["truth_in_context"])
            refused = sum(1 for r in rows if r["refused"])
            print(f"[pipe-sim] {cfg_name}: n={n} 缺口={gap} ({gap/n:.4f}) "
                  f"拒答={refused}")

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        for row in all_rows:
            f.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
    print(f"[pipe-sim] wrote -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
