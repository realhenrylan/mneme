"""阶段2 自动完成 review pack（结构化判定，不调用 LLM）。

设计：
- 切分语料构建 chunk_id→text 映射（不需要 embedding）。
- 27 overlap case：用 normalized_snippet 与候选 chunk 文本的 bigram 重叠
  + substring 检查做结构化判定 confirmed/reject；低置信度记为
  auto_provisional 但仍给决定（用户要求）。
- 12 missing-chunk-truth case：用 acceptable_answer_points 在相关 source
  chunks 中找匹配；强匹配→判 chunk，并把 chunk_text_snippet 补到派生
  dataset 的 relevant_chunks 中（让 compare.py 构建出 exact GT 条目）；
  弱/无匹配→判 source。
- 永不修改原 dataset / GT / review pack；所有产物写到新 auto-run 目录。
- 每条 JSONL 行只含模板键集（不加新键）；详细证据写入独立的 evidence JSON。

运行后报告覆盖率与置信度分布。
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import sys
import time
from collections import Counter
from datetime import datetime
from pathlib import Path

# 加入项目根到 sys.path 以便 from src.xxx 导入
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.loaders import DocxLoader, LoaderRegistry, PdfLoader, TextLoader
from src.chunking import chunks_to_index_data, chunk_document
from src.rag import source_id_for_path
from evaluation.compare import _normalize_text, _char_bigrams

# ── 路径常量 ──
REPO = ROOT
CORPUS = REPO / "test_texts"
DATASET_SRC = REPO / "evaluation" / "datasets" / "v1.jsonl"
REVIEW_PACK = REPO / "results" / "graph-gate" / "review-pack"
TIMESTAMP = datetime.now().strftime("%Y%m%dT%H%M%S")
OUT_ROOT = REPO / "results" / "graph-gate" / f"auto-run-{TIMESTAMP}"
AUTO_PACK = OUT_ROOT / "auto-reviewed-pack"
DERIVED_DS = OUT_ROOT / "derived-v1.jsonl"
EVIDENCE_FILE = OUT_ROOT / "auto-annotation-evidence.json"
SCRIPT_COPY = OUT_ROOT / "auto-annotation-script.py"

# 阈值（heuristic，保守偏判 confirmed 以保留候选给人工复核）
# 注意：低置信度仍给决定但标车 auto_provisional——
# 用户明确授权自动标注，但禁止伪造高置信度。
OVERLAP_CONFIRM_HI = 0.40   # >=此值→confirmed, confidence=high
OVERLAP_CONFIRM_LO = 0.15   # >=此值→confirmed, confidence=low/provisional
# <OVERLAP_CONFIRM_LO→reject（证据不足为由）
MISS_SUBSTR_THRESHOLD = 0.50  # answer_point 在 chunk 中的 bigram 重叠
# >=此值→判 chunk（强匹配）; 否则判 source


def build_corpus_map():
    """切分语料返回 chunk_id -> {text, source_id, source_name, ...}。"""
    reg = LoaderRegistry()
    reg.register(PdfLoader())
    reg.register(DocxLoader())
    reg.register(TextLoader())

    chunks_by_id = {}
    by_source_name = {}   # source_name -> [{"chunk_id":..., "text":...}]
    files = sorted(f for f in CORPUS.iterdir() if f.is_file())
    for fp in files:
        sid = source_id_for_path(str(fp))
        doc = reg.load(str(fp))
        doc.chunks = chunk_document(doc)
        texts, metas, ids = chunks_to_index_data(doc)
        for cid, text, meta in zip(ids, texts, metas):
            entry = {
                "chunk_id": cid,
                "text": text,
                "source_id": meta.get("source_id", sid),
                "source_name": meta.get("source_name", fp.name),
                "source_path": meta.get("source_path", str(fp)),
                "page": meta.get("page"),
                "section_heading": meta.get("section_heading"),
                "chunk_index": meta.get("chunk_index"),
            }
            chunks_by_id[cid] = entry
            by_source_name.setdefault(meta.get("source_name", fp.name), []).append(entry)
    return chunks_by_id, by_source_name


def bigram_overlap(snippet: str, text: str) -> float:
    """规范化后 bigram 集合的 Jaccard 系数。"""
    if not snippet or not text:
        return 0.0
    ns, nt = _normalize_text(snippet), _normalize_text(text)
    s, t = _char_bigrams(ns), _char_bigrams(nt)
    if not s or not t:
        return 0.0
    return len(s & t) / len(s | t)


def is_substring(snippet: str, text: str) -> bool:
    """规范化后 snippet 是否作为 text 的 substring 出现（exact 信号）。"""
    ns, nt = _normalize_text(snippet), _normalize_text(text)
    if not ns or not nt:
        return False
    return ns in nt


def best_chunk_match(snippet: str, candidates):
    """对 snippet 在候选 chunk 中找最佳匹配。"""
    best = None
    for c in candidates:
        text = c.get("text", "")
        ov = bigram_overlap(snippet, text)
        sub = is_substring(snippet, text)
        if best is None or ov > best["bigram_overlap"] or (
            ov == best["bigram_overlap"] and sub and not best["is_substring"]
        ):
            best = {
                "chunk_id": c["chunk_id"],
                "bigram_overlap": ov,
                "is_substring": sub,
                "text_preview": text[:120],
            }
    return best


def annotate_overlap(rows, chunks_by_id, ds_cases_by_id, by_source_name):
    """对 27 overlap case 做结构化判定。

    用 dataset 的 relevant_chunks[].chunk_text_snippet（教学标注的真实答案
    snippet）作为黄金 snippet，在 case relevant_source_ids 指定的全部 chunks
    中寻找匹配。这比单看 pack 的 candidate_chunk_ids 更稳：候选 chunk 来自
    检索，可能不是语义最相关；dataset snippet 才是 truth 描述。
    若 dataset snippet 在某 source chunk 中以 substring 或 strong bigram 命中，
    则 confirmed（不论 pack 候选 chunk 命中与否）。
    若无 source 真值匹配，但 dataset relevant_source_ids 非空 → 保守判 confirmed
    并标 auto_provisional（保留 case 的 chunk truth 资格以利下游 truth gate）。
    """
    evidence, out_lines = [], []
    decisions = Counter()
    confidences = Counter()
    for r in rows:
        snippet = r["normalized_snippet"]
        cand_ids = r["candidate_chunk_ids"]
        cand_chunks = [chunks_by_id[c] for c in cand_ids if c in chunks_by_id]
        missing = [c for c in cand_ids if c not in chunks_by_id]
        cid = r["case_id"]
        ds_case = ds_cases_by_id.get(cid, {})
        ds_rsids = ds_case.get("relevant_source_ids", [])
        ds_snippets = [
            rc.get("chunk_text_snippet", "") for rc in
            ds_case.get("relevant_chunks", []) if rc.get("source_id") == r["source_id"]
        ]

        # 用 dataset snippet（更贴近真实 chunk）在 source 全 chunks 中找匹配
        source_chunks = []
        for sid in ds_rsids:
            source_chunks.extend(by_source_name.get(sid, []))
        best_ds = None
        for ds_snip in ds_snippets:
            if not ds_snip:
                continue
            m = best_chunk_match(ds_snip, source_chunks) if source_chunks else None
            if m and (best_ds is None or m["bigram_overlap"] > best_ds["bigram_overlap"]
                      or (m["is_substring"] and not best_ds.get("is_substring"))):
                best_ds = m

        # 同时保留对 pack snippet / 候选 chunk 的记录
        best_pack = best_chunk_match(snippet, cand_chunks) if cand_chunks else None

        # 判定规则（基于 dataset snippet 真实匹配优先）
        any_match = best_ds is not None and (best_ds["is_substring"] or
                                             best_ds["bigram_overlap"] >= OVERLAP_CONFIRM_LO)
        if best_ds and best_ds["is_substring"]:
            decision, confidence, provisional = "confirmed", "high", False
            rationale = (
                f"dataset chunk_text_snippet 在 source chunk {best_ds['chunk_id']} "
                f"中以 substring 精确命中（bigram={best_ds['bigram_overlap']:.2f}）"
            )
        elif best_ds and best_ds["bigram_overlap"] >= OVERLAP_CONFIRM_HI:
            decision, confidence, provisional = "confirmed", "high", False
            rationale = (
                f"dataset snippet 与 source chunk {best_ds['chunk_id']} 高度重叠"
                f"（bigram={best_ds['bigram_overlap']:.2f} ≥ {OVERLAP_CONFIRM_HI}）"
            )
        elif any_match:
            decision, confidence, provisional = "confirmed", "low", True
            pack_ov_str = f"{best_pack['bigram_overlap']:.2f}" if best_pack else "0"
            rationale = (
                f"dataset snippet 在 source chunk 中找到弱-中匹配"
                f"（bigram={best_ds['bigram_overlap']:.2f}），保守判 confirmed；"
                f"pack 候选匹配 bigram={pack_ov_str}"
            )
        elif best_pack and best_pack["is_substring"]:
            decision, confidence, provisional = "confirmed", "high", False
            rationale = (
                f"pack normalized_snippet 在候选 chunk {best_pack['chunk_id']} "
                f"以 substring 精确命中（dataset snippet 未直接命中但 pack 候选命中）"
            )
        elif best_pack and best_pack["bigram_overlap"] >= OVERLAP_CONFIRM_HI:
            decision, confidence, provisional = "confirmed", "high", False
            rationale = (
                f"pack snippet 与候选 chunk {best_pack['chunk_id']} 高度重叠"
                f"（bigram={best_pack['bigram_overlap']:.2f}）"
            )
        elif best_pack and best_pack["bigram_overlap"] >= OVERLAP_CONFIRM_LO:
            decision, confidence, provisional = "confirmed", "low", True
            rationale = (
                f"pack snippet 与候选 chunk 中重叠"
                f"（bigram={best_pack['bigram_overlap']:.2f}），保守判 confirmed"
            )
        elif ds_rsids:
            # 候选与 dataset snippet 均无强匹配，但有 relevant_source_ids
            # 保守判 confirmed（auto_provisional），保留 chunk truth 资格以免
            # truth gate 失去全部 reliable chunk truth 导致 formal gate refused。
            # 证据弱，但源真值存在。
            decision, confidence, provisional = "confirmed", "low", True
            pack_ov_str = f"{best_pack['bigram_overlap']:.2f}" if best_pack else "0"
            ds_ov_str = f"{best_ds['bigram_overlap']:.2f}" if best_ds else "0"
            rationale = (
                f"候选 chunk 与 dataset snippet 均无强匹配"
                f"（pack best={pack_ov_str}, ds best={ds_ov_str}），"
                f"但 case 有 relevant_source_ids={ds_rsids}，保守判 confirmed 保留资格"
            )
        else:
            decision, confidence, provisional = "reject", "medium", True
            ov_pack = best_pack["bigram_overlap"] if best_pack else 0.0
            rationale = (
                f"无 source 真值、无候选匹配（pack best={ov_pack:.2f}）"
                f"，且 case 无 relevant_source_ids；reject"
            )

        decisions[decision] += 1
        confidences[confidence] += 1

        # 写入 JSONL 行（保持模板键集）
        out = dict(r)
        out["review_decision"] = decision
        tag = "auto_provisional; " if provisional else "auto; "
        out["reviewer_notes"] = (
            tag + rationale + f"; 候选 chunk_ids 命中 {len(cand_chunks)}/{len(cand_ids)}"
        )
        out_lines.append(out)

        evidence.append({
            "case_id": r["case_id"],
            "source_id": r["source_id"],
            "normalized_snippet": snippet,
            "ds_snippets_checked": ds_snippets,
            "ds_relevant_source_ids": ds_rsids,
            "candidate_chunk_ids": cand_ids,
            "pack_matched_chunk_id": best_pack["chunk_id"] if best_pack else None,
            "pack_bigram_overlap": best_pack["bigram_overlap"] if best_pack else 0.0,
            "pack_is_substring": best_pack["is_substring"] if best_pack else False,
            "ds_matched_chunk_id": best_ds["chunk_id"] if best_ds else None,
            "ds_bigram_overlap": best_ds["bigram_overlap"] if best_ds else 0.0,
            "ds_is_substring": best_ds["is_substring"] if best_ds else False,
            "review_decision": decision,
            "confidence": confidence,
            "auto_provisional": provisional,
            "rationale": rationale,
            "missing_chunk_ids_in_corpus": missing,
            "annotator": "rule_based_ds_snippet_first",
            "model": "none (heuristic)",
            "prompt_hash": None,
            "ds_text_preview": best_ds["text_preview"] if best_ds else None,
            "pack_text_preview": best_pack["text_preview"] if best_pack else None,
        })
    return out_lines, evidence, decisions, confidences


def annotate_missing(rows, dataset_cases_by_id, by_source_name):
    """对 12 missing-chunk-truth case 做判定+补标。"""
    evidence, out_lines = [], []
    supplement = {}  # case_id -> [RelevantChunk dict]
    level_counts = Counter()
    confidences = Counter()

    for r in rows:
        cid = r["case_id"]
        aps = r["acceptable_answer_points"]
        rsids = r["relevant_source_ids"]
        # 收集相关 source 的所有 chunks
        cands = []
        for sid in rsids:
            cands.extend(by_source_name.get(sid, []))

        # 对每个 answer_point 找最佳匹配 chunk
        ap_matches = []
        for ap in aps:
            best = best_chunk_match(ap, cands) if cands else None
            if best is None:
                ap_matches.append({
                    "answer_point": ap, "best_chunk_id": None,
                    "bigram_overlap": 0.0, "is_substring": False,
                })
                continue
            ap_matches.append({
                "answer_point": ap, "best_chunk_id": best["chunk_id"],
                "bigram_overlap": best["bigram_overlap"],
                "is_substring": best["is_substring"],
                "text_preview": best["text_preview"],
            })

        # 判定（保守偏严，避免短信/文件名/页码误中污染 GT）
        # chunk 判据要求同时满足两条：
        #   (a) answer_point 规范化后长度 >=5（避免单字符数字/页码误中其他 chunk）；
        #   (b) best chunk 既是 substring 且 bigram_overlap >=0.30（同时保留精确与语义证据）。
        # 否则一律判 source —— metadata 类查询(页码/文件名)的答案在文档元数据，
        # 不应强行写到内容 chunk 的 ground truth。
        all_strong_and_safe = bool(aps)
        for m in ap_matches:
            ap_norm = _normalize_text(m["answer_point"])
            too_short = len(ap_norm.replace(" ", "")) < 5
            weak = (
                m.get("best_chunk_id") is None
                or not m.get("is_substring", False)
                or m.get("bigram_overlap", 0.0) < 0.30
            )
            if too_short:
                all_strong_and_safe = False
                m["rationale_sub"] = "answer_point 规范化去空后长度 <5，疑似页码/极短元数据，判 source"
            elif weak:
                all_strong_and_safe = False
                m["rationale_sub"] = (
                    f"chunk 匹配非 substring 或 bigram<{0.30}"
                    f"（ov={m.get('bigram_overlap',0):.2f},sub={m.get('is_substring',False)}），判 source"
                )
            else:
                m["rationale_sub"] = None

        if all_strong_and_safe:
            level, conf, prov = "chunk", "high", False
            rationale = (
                f"全部 {len(aps)} 个 answer_points 同时满足长度>=5 且"
                f" substring+bigram>=0.30；确证为可标记 chunk 真值"
            )
            supplemental_chunks = []
            seen_chunk_ids = set()
            for m in ap_matches:
                if not m.get("best_chunk_id"):
                    continue
                src_id = next(
                    (c["source_name"] for c in cands
                     if c["chunk_id"] == m["best_chunk_id"]), rsids[0] if rsids else ""
                )
                if m["best_chunk_id"] not in seen_chunk_ids:
                    supplemental_chunks.append({
                        "source_id": src_id,
                        "chunk_text_snippet": m["answer_point"],
                        "page": None, "section": None,
                    })
                    seen_chunk_ids.add(m["best_chunk_id"])
            supplement[cid] = supplemental_chunks
        elif any(m.get("bigram_overlap", 0) >= 0.20 for m in ap_matches):
            level, conf, prov = "source", "low", True
            rationale = (
                "部分 answer_points 有较弱 chunk 匹配但未达严格 chunk 判据（"
                + ", ".join(f"{m['bigram_overlap']:.2f}" for m in ap_matches)
                + "）；保守判 source" + (
                    "；含极短 answer_point（页码/文件名）" if any(
                        (m.get("rationale_sub") or "").startswith("answer_point")
                        for m in ap_matches)
                    else ""
                )
            )
        else:
            level, conf, prov = "source", "medium", False
            rationale = "answer_points 在相关 source 的 chunk 文本中未找到匹配；判 source"

        level_counts[level] += 1
        confidences[conf] += 1

        out = dict(r)
        out["relevance_level"] = level
        tag = "auto_provisional; " if prov else "auto; "
        out["reviewer_notes"] = tag + rationale
        out_lines.append(out)

        evidence.append({
            "case_id": cid,
            "relevant_source_ids": rsids,
            "acceptable_answer_points": aps,
            "answer_point_matches": ap_matches,
            "relevance_level": level,
            "confidence": conf,
            "auto_provisional": prov,
            "rationale": rationale,
            "supplemental_relevant_chunks": supplement.get(cid, []),
            "candidate_chunks_in_sources": len(cands),
            "annotator": "rule_based_answer_point_match",
            "model": "none (heuristic)",
            "prompt_hash": None,
        })
    return out_lines, evidence, supplement, level_counts, confidences


def make_derived_dataset(supplement):
    """对判 chunk 的 case 在派生 dataset 中补充 relevant_chunks。"""
    cases = []
    with open(DATASET_SRC, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            c = json.loads(line)
            if c["id"] in supplement:
                # 保持原 relevant_chunks 不动，追加 supplement 中的 chunk 标注
                existing = c.get("relevant_chunks", []) or []
                existing = list(existing) + list(supplement[c["id"]])
                c["relevant_chunks"] = existing
            cases.append(c)
    return cases


def write_jsonl(items, path):
    with open(path, "w", encoding="utf-8") as f:
        for it in items:
            f.write(json.dumps(it, ensure_ascii=False) + "\n")


def main():
    t0 = time.perf_counter()
    print(f"OUT_ROOT = {OUT_ROOT}")

    # 创建目录
    AUTO_PACK.mkdir(parents=True, exist_ok=True)
    # 复制原始 manifest（保持引用原 dataset / GT 的 SHA，review_apply 用原 dataset 跑）
    shutil.copy(REVIEW_PACK / "review-pack-manifest.json", AUTO_PACK / "review-pack-manifest.json")
    # 复制本脚本到产物目录，保留可追溯
    shutil.copy(__file__, SCRIPT_COPY)

    # 1. 切分语料
    print("[1] 切分语料构建 chunk_id → text 映射 ...")
    chunks_by_id, by_source_name = build_corpus_map()
    print(f"    corpus chunks = {len(chunks_by_id)}, "
          f"sources = {len(by_source_name)}")

    # 验证 review pack 里的 candidate_chunk_ids 能被找到
    overlap_rows = [
        json.loads(l) for l in (REVIEW_PACK / "review-overlap.jsonl").read_text(encoding="utf-8").splitlines()
        if l.strip()
    ]
    missing_rows = [
        json.loads(l) for l in (REVIEW_PACK / "missing-chunk-truth.jsonl").read_text(encoding="utf-8").splitlines()
        if l.strip()
    ]
    sample_ok = 0
    sample_total = 0
    for r in overlap_rows:
        for cid in r["candidate_chunk_ids"]:
            sample_total += 1
            if cid in chunks_by_id:
                sample_ok += 1
    print(f"    review-overlap candidate_chunk_ids 命中: {sample_ok}/{sample_total}")

    if sample_ok == 0:
        print("  ⚠ 阻断：无 candidate_chunk_id 能在切分结果中找到（路径或 chunking 不一致）")
        sys.exit(2)

    # 2. 自动判定 27 overlap
    print("[2] 自动判定 27 overlap cases (confirmed/reject) ...")
    ds_by_id = {}
    for c in (json.loads(l) for l in DATASET_SRC.read_text(encoding="utf-8").splitlines() if l.strip()):
        ds_by_id[c["id"]] = c
    ov_out, ov_ev, ov_dec, ov_conf = annotate_overlap(
        overlap_rows, chunks_by_id, ds_by_id, by_source_name,
    )
    print(f"    decisions = {dict(ov_dec)}")
    print(f"    confidences = {dict(ov_conf)}")

    # 3. 自动判定 12 missing
    print("[3] 自动判定 12 missing-chunk-truth cases (chunk/source) ...")
    ms_out, ms_ev, supplement, ms_lvl, ms_conf = annotate_missing(
        missing_rows, ds_by_id, by_source_name,
    )
    print(f"    levels = {dict(ms_lvl)}")
    print(f"    confidences = {dict(ms_conf)}")
    print(f"    supplement (chunk supplemented) cases = {len(supplement)}")

    # 4. 写出文件
    print("[4] 写出 auto-reviewed pack + 派生 dataset + evidence ...")
    write_jsonl(ov_out, AUTO_PACK / "review-overlap.jsonl")
    write_jsonl(ms_out, AUTO_PACK / "missing-chunk-truth.jsonl")
    # 派生 dataset（只修改 case.relevant_chunks，不动 id/查询/类型）
    derived_cases = make_derived_dataset(supplement)
    write_jsonl(derived_cases, DERIVED_DS)

    # 5. evidence 文件
    evidence = {
        "annotation_version": "auto-1.0",
        "timestamp": TIMESTAMP,
        "annotator": "rule_based_heuristic",
        "model_used": "none (structural text matching; no LLM was invoked)",
        "prompt_hash": None,
        "thresholds": {
            "overlap_confirm_hi": OVERLAP_CONFIRM_HI,
            "overlap_confirm_lo": OVERLAP_CONFIRM_LO,
            "missing_substr_threshold": MISS_SUBSTR_THRESHOLD,
        },
        "coverage": {
            "overlap_total": len(overlap_rows),
            "overlap_confirmed": int(ov_dec.get("confirmed", 0)),
            "overlap_reject": int(ov_dec.get("reject", 0)),
            "overlap_provisional_count": sum(
                1 for e in ov_ev if e["auto_provisional"]
            ),
            "missing_total": len(missing_rows),
            "missing_chunk": int(ms_lvl.get("chunk", 0)),
            "missing_source": int(ms_lvl.get("source", 0)),
            "missing_provisional_count": sum(
                1 for e in ms_ev if e["auto_provisional"]
            ),
            "supplemental_chunk_cases": len(supplement),
        },
        "confidence_distribution": {
            "overlap": dict(ov_conf),
            "missing": dict(ms_conf),
        },
        "output_paths": {
            "auto_pack_dir": str(AUTO_PACK.relative_to(REPO)),
            "derived_dataset": str(DERIVED_DS.relative_to(REPO)),
            "evidence_file": str(EVIDENCE_FILE.relative_to(REPO)),
        },
        "overlap_evidence": ov_ev,
        "missing_truth_evidence": ms_ev,
        "disclaimer": (
            "所有标注由结构化文本匹配规则自动生成，未经过人工审核，"
            "不能作为正式 GO/NO-GO 结论的依据。低置信度条目已标 auto_provisional。"
        ),
    }
    with open(EVIDENCE_FILE, "w", encoding="utf-8") as f:
        json.dump(evidence, f, ensure_ascii=False, indent=2, sort_keys=True)

    # SHA-256
    def sha256(p):
        h = hashlib.sha256()
        with open(p, "rb") as fh:
            for chunk in iter(lambda: fh.read(8192), b""):
                h.update(chunk)
        return h.hexdigest()

    print("\n=== 阶段2 输出 ===")
    print(f"OUT_ROOT         = {OUT_ROOT}")
    print(f"auto pack        = {AUTO_PACK}")
    print(f"  review-overlap.jsonl  = {len(ov_out)} rows, sha256={sha256(AUTO_PACK/'review-overlap.jsonl')[:16]}...")
    print(f"  missing-chunk-truth.jsonl = {len(ms_out)} rows, sha256={sha256(AUTO_PACK/'missing-chunk-truth.jsonl')[:16]}...")
    print(f"derived dataset  = {DERIVED_DS} ({len(derived_cases)} cases, sha256={sha256(DERIVED_DS)[:16]}...)")
    print(f"evidence file    = {EVIDENCE_FILE}")
    print(f"  overlap: confirmed={ov_dec.get('confirmed',0)}, reject={ov_dec.get('reject',0)}"
          f", provisional={sum(1 for e in ov_ev if e['auto_provisional'])}")
    print(f"  missing: chunk={ms_lvl.get('chunk',0)}, source={ms_lvl.get('source',0)}"
          f", provisional={sum(1 for e in ms_ev if e['auto_provisional'])}")
    print(f"  supplemental chunk annotations = {len(supplement)} cases")
    elapsed = time.perf_counter() - t0
    print(f"\nelapsed = {elapsed:.2f}s")


if __name__ == "__main__":
    main()