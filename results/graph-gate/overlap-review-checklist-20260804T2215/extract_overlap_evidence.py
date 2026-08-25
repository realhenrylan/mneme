"""本地只读：从 eval-autorun-lock 索引提取 25 条未确认 overlap 的候选 chunk 文本证据。

生成 results/graph-gate/overlap-review-checklist-<ts>/ 参考清单，
供人工补填 review_decision。不修改任何历史产物。
"""
import html
import json
import re
import unicodedata
from pathlib import Path

import chromadb

TS = "20260804T2215"


def normalize_text(s: str) -> str:
    s = html.unescape(s or "")
    s = unicodedata.normalize("NFKC", s)
    s = s.lower()
    # 去掉空白与标点（保留字母数字）
    s = "".join(
        ch for ch in s
        if ch.isalnum() or ch in "."
    )
    return s


def char_bigrams(t: str) -> set:
    return {t[i:i + 2] for i in range(max(0, len(t) - 1))}


def best_window_overlap(snippet: str, chunk_text: str) -> float:
    """snippet 与 chunk 的最佳滑动窗口 bigram 重叠（窗口宽 = 2×snippet）。"""
    sb = char_bigrams(snippet)
    win = max(8, len(snippet) * 2)
    best = 0.0
    step = max(1, win // 4)
    for start in range(0, max(1, len(chunk_text) - win + 1), step):
        cb = char_bigrams(chunk_text[start:start + win])
        if not sb:
            continue
        ov = len(sb & cb) / len(sb)
        best = max(best, ov)
    return best


def main() -> None:
    client = chromadb.PersistentClient(path="C:/Users/Henry Lan/.mneme/chroma_db")
    col = client.get_collection("eval-autorun-lock")
    data = col.get(include=["documents", "metadatas"])
    chunks = {}
    for cid, doc, meta in zip(data["ids"], data["documents"], data["metadatas"]):
        chunks[cid] = {
            "source": (meta or {}).get("source_name") or (meta or {}).get("source", ""),
            "text": doc,
        }

    pack = Path("results/graph-gate/review-pack-chunk-annotated/review-overlap.jsonl")
    rows = [json.loads(l) for l in open(pack, encoding="utf-8")]

    out = []
    for r in rows:
        if r.get("review_decision"):
            continue
        sn = normalize_text(r["normalized_snippet"])
        sb = char_bigrams(sn)
        evidence = []
        for cid in r.get("candidate_chunk_ids", []):
            ch = chunks.get(cid)
            if ch is None:
                evidence.append({
                    "chunk_id": cid, "source": "?", "bigram_overlap": None,
                    "preview": "<<chunk not in index>>",
                })
                continue
            cb = char_bigrams(normalize_text(ch["text"]))
            ov = round(len(sb & cb) / len(sb), 4) if sb and cb else 0.0
            win_ov = best_window_overlap(sn, normalize_text(ch["text"]))
            # 最佳窗口上下文：在原始文本中定位 snippet 相关区域
            norm_chunk = normalize_text(ch["text"])
            win = max(8, len(sn) * 2)
            best_start = 0
            best = 0.0
            step = max(1, win // 4)
            for start in range(0, max(1, len(norm_chunk) - win + 1), step):
                o = len(sb & char_bigrams(norm_chunk[start:start + win])) / len(sb) if sb else 0.0
                if o > best:
                    best, best_start = o, start
            # 把规范化偏移映射回原始文本（按字符比例近似）
            raw = ch["text"]
            if norm_chunk:
                ratio = len(raw) / len(norm_chunk)
                raw_start = min(len(raw) - 1, int(best_start * ratio))
                raw_start = max(0, raw_start - 80)
                preview = re.sub(r"\s+", " ", raw[raw_start:raw_start + 360])
            else:
                preview = re.sub(r"\s+", " ", raw)[:240]
            evidence.append({
                "chunk_id": cid, "source": ch["source"],
                "bigram_overlap": ov, "best_window_overlap": round(best, 4),
                "preview": preview,
            })
        out.append({
            "case_id": r["case_id"], "query": r["query"],
            "source_id": r["source_id"],
            "normalized_snippet": r["normalized_snippet"],
            "candidate_chunks": evidence,
        })

    d = Path(f"results/graph-gate/overlap-review-checklist-{TS}")
    d.mkdir(parents=True, exist_ok=True)
    lines = [
        "# Overlap 人工审核待确认清单（25 条）", "",
        "> 从 `~/.mneme/chroma_db/eval-autorun-lock`（736 chunks）本地只读提取候选 chunk 文本；",
        "> bigram_overlap = |snippet 与 chunk 的字符 bigram 交集| / |snippet bigram|（review_pack 同口径）。",
        "> 请在 `results/graph-gate/review-pack-chunk-annotated/review-overlap.jsonl` 中",
        "> 为每条填写 `review_decision`（confirmed / reject）。", "",
    ]
    for i, item in enumerate(out, 1):
        lines.append(f"## {i}. {item['case_id']} / {item['source_id']}")
        lines.append(f"- query: {item['query']}")
        lines.append(f"- snippet: `{item['normalized_snippet']}`")
        for ev in item["candidate_chunks"]:
            ov = f"{ev['bigram_overlap']:.4f}" if ev["bigram_overlap"] is not None else "N/A"
            wov = f"{ev['best_window_overlap']:.4f}" if ev.get("best_window_overlap") is not None else "N/A"
            lines.append(
                f"- chunk `{ev['chunk_id'][:12]}…` (source={ev['source']}, "
                f"bigram={ov}, best-window={wov}): {ev['preview']}"
            )
        lines.append("")
    (d / "overlap-review-checklist.md").write_text(
        "\n".join(lines), encoding="utf-8",
    )
    (d / "overlap-review-checklist.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8",
    )
    print(f"written: {d}")
    print(f"entries: {len(out)}")


if __name__ == "__main__":
    main()
