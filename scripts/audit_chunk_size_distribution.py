"""A1 审计：v1 test_texts 索引 与 v2 sealed chunks 的 chunk 长度分布（只读）。

背景（设计文档 ``plans/22-SMALL-ITEMS-31-CLOSEOUT-DESIGN-2026-08-29.md``
Part 1-A）：run-2 实测 4 字符 heading 残片（chunk_12，"1. 2"）经邻接扩展
进入 context。阈值 ``MIN_ADJACENT_CHUNK_CHARS`` 的初值定 20，最终值由本
审计证据冻结：先统计 < 候选阈值的块数量与形态，据此定档并留档。

本脚本零写入：
- v1 树（test_texts/）只读，chunk 结构经 chunk_document 内存重建（与
  prepare_index 同路径，不落盘、无 chroma 写入）；
- v2 sealed（data/v2-corpus/chunks/chunks.jsonl）只读。

用法：
    python scripts/audit_chunk_size_distribution.py --out-dir results/audit-chunk-size
输出：
    distribution.json  纯统计（机器可读，阈值冻结依据）
    report.md          人类可读报告（形态样例随附）
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from statistics import median, quantiles
from typing import Any

# 阈值冻结候选档：审计统计每一档的块数，最终值由设计文档冻结
CANDIDATE_THRESHOLDS = (10, 15, 20, 25, 30, 40, 50)
# 审计宽度：形态样例只对低于此长度的块逐条留档（不泛滥）
SAMPLE_STRIP_WINDOW = 50

_HEADING_RE = re.compile(r"^(#{1,6}\s*|\d{1,3}[\.、)]\s*|\d{1,3}\s+|[A-Z][A-Z0-9 \-]{2,})")
_LIST_RE = re.compile(r"^(\s*[-*•·]\s*|\d{1,3}[\.\)]\s*|[①②③④⑤⑥⑦⑧⑨⑩])")


@dataclass
class ChunkInfo:
    """审计用的最小块信息（无重依赖，v1/v2 通用）。"""
    source: str
    chunk_id: str
    chunk_type: str  # v1 来自 metadata；v2 sealed 无类型字段 → "pending"
    text: str
    length: int = 0  # len(text.strip())

    def __post_init__(self) -> None:
        self.length = len(self.text.strip())


def classify_fragment(text: str) -> str:
    """形态启发式：标题残片 / 列表碎片 / 正文短节（供报告，非判定）。"""
    stripped = text.strip()
    if not stripped:
        return "empty"
    if _HEADING_RE.match(stripped):
        return "heading_fragment"
    if _LIST_RE.match(stripped):
        return "list_fragment"
    return "body_fragment"


@dataclass
class AuditReport:
    v1_chunks: list[ChunkInfo] = field(default_factory=list)
    v2_chunks: list[ChunkInfo] = field(default_factory=list)

    # ── 汇总裁缆 ──────────────────────────────────────────────

    def _summarize(self, chunks: list[ChunkInfo]) -> dict[str, Any]:
        lengths = sorted(c.length for c in chunks) if chunks else []
        total = len(lengths)
        below: dict[str, int] = {}
        for t in CANDIDATE_THRESHOLDS:
            below[str(t)] = sum(1 for x in lengths if x < t)
        qs = quantiles(lengths, n=100) if total > 1 else []
        # quantiles(n=100) 不能直接当百分位用（分 100 段取 99 个分位点），
        # 用近似：取 1/10/25/50/75/90/99 百分位
        pct = {
            f"p{name}": (
                lengths[min(total - 1, int(round(total * frac)))]
                if total else None)
            for name, frac in (
                ("0", 0.0), ("10", 0.10), ("25", 0.25), ("50", 0.50),
                ("75", 0.75), ("90", 0.90), ("99", 0.99))
        }
        return {
            "total": total,
            "min": lengths[0] if total else None,
            "max": lengths[-1] if total else None,
            "median": median(lengths) if total else None,
            "percentiles": pct,
            "below_threshold_counts": below,
            "below_ratio": {k: (v / total if total else 0.0)
                            for k, v in below.items()},
        }

    def _type_distribution(self, chunks: list[ChunkInfo]) -> dict[str, Any]:
        by_type: dict[str, list[ChunkInfo]] = {}
        for c in chunks:
            by_type.setdefault(c.chunk_type, []).append(c)
        out: dict[str, Any] = {}
        for t, items in sorted(by_type.items()):
            sub = self._summarize(items)
            out[t] = {
                "count": len(items),
                "below_counts": {
                    str(k): sum(1 for c in items if c.length < k)
                    for k in CANDIDATE_THRESHOLDS},
                "below_20_ratio": sub["below_threshold_counts"]["20"] / len(items)
                if items else 0.0,
            }
        return out

    def _sample_short(self, chunks: list[ChunkInfo], limit: int = 60) -> list[dict]:
        short = sorted(
            (c for c in chunks if c.length < SAMPLE_STRIP_WINDOW),
            key=lambda c: c.length)
        return [
            {"source": c.source, "chunk_id": c.chunk_id,
             "chunk_type": c.chunk_type, "length": c.length,
             "shape": classify_fragment(c.text),
             "preview": c.text.strip()[
                 :80].replace("\n", "\\n")}
            for c in short[:limit]
        ]

    def build(self) -> dict[str, Any]:
        return {
            "candidate_thresholds": list(CANDIDATE_THRESHOLDS),
            "method": (
                "v1: src.loaders.LoaderRegistry -> chunk_document（与 "
                "prepare_index 同路径，内存重建零写入）；"
                "v2: 只读 data/v2-corpus/chunks/chunks.jsonl"),
            "v1": {
                "summary": self._summarize(self.v1_chunks),
                "by_chunk_type": self._type_distribution(self.v1_chunks),
                "shape_distribution": dict(Counter(
                    classify_fragment(c.text) for c in self.v1_chunks)),
                "short_samples": self._sample_short(self.v1_chunks),
            },
            "v2": {
                "summary": self._summarize(self.v2_chunks),
                "by_source": self._type_distribution(
                    [c for c in self.v2_chunks]),
                "shape_distribution": dict(Counter(
                    classify_fragment(c.text) for c in self.v2_chunks)),
                "short_samples": self._sample_short(self.v2_chunks),
            },
        }


# ── 数据装载 ───────────────────────────────────────────────────

def load_v1_chunks(texts_dir: Path) -> list[ChunkInfo]:
    """v1 test_texts：与 prepare_index 同路径内存重建 chunk 结构。"""
    from src.loaders import DocxLoader, LoaderRegistry, PdfLoader, TextLoader
    from src.chunking import chunk_document, chunks_to_index_data

    registry = LoaderRegistry()
    registry.register(PdfLoader())
    registry.register(DocxLoader())
    registry.register(TextLoader())

    out: list[ChunkInfo] = []
    for path in sorted(texts_dir.iterdir()):
        if not path.is_file():
            continue
        document = registry.load(str(path))
        document.chunks = chunk_document(document)
        texts, metadatas, ids = chunks_to_index_data(document)
        for text, meta, cid in zip(texts, metadatas, ids):
            out.append(ChunkInfo(
                source=path.name, chunk_id=cid,
                chunk_type=str(meta.get("chunk_type", "")), text=text))
    return out


def load_v2_chunks(chunks_jsonl: Path) -> list[ChunkInfo]:
    """v2 sealed chunks.jsonl（只读；sealed 行无 chunk_type 字段）。"""
    out: list[ChunkInfo] = []
    with open(chunks_jsonl, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            out.append(ChunkInfo(
                source=str(row.get("source", "")),
                chunk_id=str(row.get("chunk_id", "")),
                chunk_type="pending",  # sealed 行不含类型字段
                text=str(row.get("text", "")),
            ))
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--v1-texts-dir", default="test_texts",
                        help="v1 test_texts 目录（只读）")
    parser.add_argument("--v2-chunks", default="data/v2-corpus/chunks/chunks.jsonl",
                        help="v2 sealed chunks.jsonl（只读）")
    parser.add_argument("--out-dir", default="results/audit-chunk-size",
                        help="审计输出目录")
    args = parser.parse_args(argv)

    report = AuditReport(
        v1_chunks=load_v1_chunks(Path(args.v1_texts_dir)),
        v2_chunks=load_v2_chunks(Path(args.v2_chunks)),
    )
    data = report.build()

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "distribution.json").write_text(
        json.dumps(data, ensure_ascii=False, indent=1, sort_keys=True) + "\n",
        encoding="utf-8")

    # 人类可读报告
    lines = [
        "# A1 审计：chunk 长度分布（阈值冻结依据）",
        "",
        f"- 方法：{data['method']}",
        f"- 候选阈值档：{CANDIDATE_THRESHOLDS}",
        "",
    ]
    for name in ("v1", "v2"):
        s = data[name]["summary"]
        lines += [
            f"## {name}（共 {s['total']} 块）",
            "",
            f"- 长度（strip 后字符）：min={s['min']} median={s['median']} "
            f"max={s['max']}",
            f"- 百分位：{s['percentiles']}",
            f"- < 候选阈值数量：{s['below_threshold_counts']}",
            f"- 形态分布：{data[name]['shape_distribution']}",
            "",
        ]
        if name == "v1":
            lines.append("- 按 chunk_type：")
            for t, sub in data[name]["by_chunk_type"].items():
                lines.append(
                    f"  - `{t}`: {sub['count']} 块，<20 字符 {sub['below_counts'].get('20', 0)}"
                    f"（含 <50 样例见下）")
            lines.append("")
        lines.append(f"### {name} 短块样例（<{SAMPLE_STRIP_WINDOW} 字符，按长度升序，最多 60 条）")
        lines.append("")
        lines.append("| source | chunk_id | type | len | shape | preview |")
        lines.append("| --- | --- | --- | --- | --- | --- |")
        for s in data[name]["short_samples"]:
            preview = s["preview"].replace("|", "\\|")
            lines.append(
                f"| {s['source']} | {s['chunk_id']} | {s['chunk_type']} | "
                f"{s['length']} | {s['shape']} | {preview} |")
        lines.append("")
    (out_dir / "report.md").write_text("\n".join(lines), encoding="utf-8")

    print(f"[audit] v1={data['v1']['summary']['total']} 块, "
          f"v2={data['v2']['summary']['total']} 块")
    print(f"[audit] 汇总写至 {out_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
