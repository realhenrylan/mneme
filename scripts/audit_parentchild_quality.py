"""B1 审计：parent 划分质量（只读，不改任何资产）。

背景（设计文档 ``plans/22-SMALL-ITEMS-31-CLOSEOUT-DESIGN-2026-08-29.md``
Part 1-B）：chunk_12 是 4 字符 child 且 parent 指向 chunk_6——``chunk_document``
对超长 Section 二次切分后无碎块合并。本审计确认该系统性问题覆盖面。

维度：
1. tiny child（< 30 字符，设计冻结的候选阈值）数量/形态/按 source 分布；
2. parent 尺寸分布（55 个 parent 的 len 统计）；
3. child ⊆ parent 包含健全性（child 文本应是 parent 文本的连续子串）；
4. tiny child 是否 heading 残片（形态启发式分类）。

v2 sealed chunks.jsonl 无 parent/child 关系字段 → 仅统计 tiny chunk 分布
并标注「sealed 无关系字段」，关系维度只对 v1 索引成立。

用法：
    python scripts/audit_parentchild_quality.py --out-dir results/audit-parentchild-quality
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# 与 A1 审计脚本共享工具：scripts/ 不是包，以同目录导入
sys.path.insert(0, str(Path(__file__).resolve().parent))
from audit_chunk_size_distribution import (  # noqa: E402
    ChunkInfo, classify_fragment, load_v2_chunks,
)

# 设计冻结的 tiny child 候选阈值（B1 审计先于 B2 修复决策）
TINY_CHILD_CHARS = 30


def _norm(text: str) -> str:
    """空白归一（与 containment 口径一致的归一函数）。"""
    return " ".join((text or "").split())


@dataclass
class RelationAudit:
    v1_chunks: list[ChunkInfo] = field(default_factory=list)
    v2_chunks: list[ChunkInfo] = field(default_factory=list)

    def build(self) -> dict[str, Any]:
        v1 = self._audit_v1(self.v1_chunks)
        v2 = self._audit_v2(self.v2_chunks)
        return {
            "tiny_child_threshold_chars": TINY_CHILD_CHARS,
            "method": (
                "v1: chunk_document 内存重建（与 prepare_index 同路径，零写入）；"
                "按 chunk_type=child / parent_chunk_id 重建 parent-child 关系。"
                "v2: sealed chunks.jsonl 无关系字段，仅 tiny 分布。"),
            "v1": v1,
            "v2": v2,
        }

    def _audit_v1(self, chunks: list[ChunkInfo]) -> dict[str, Any]:
        return self._audit_v1_with_relations(chunks)

    def _audit_v1_with_relations(self, chunks: list[ChunkInfo]) -> dict[str, Any]:
        # 所有 child（含 tiny）与 parent 关系
        by_parent: dict[tuple[str, str], list[ChunkInfo]] = defaultdict(list)
        parent_by_id: dict[str, ChunkInfo] = {}
        child_by_id: dict[str, ChunkInfo] = {}
        for c in chunks:
            if c.chunk_type == "parent":
                parent_by_id[c.chunk_id] = c
            elif c.chunk_type == "child":
                child_by_id[c.chunk_id] = c

        # 关系重建：metadatas 无法从 ChunkInfo 恢复 parent_chunk_id——在
        # 装载阶段由脚本把 parent_chunk_id 绑定到 ChunkInfo.parent_id
        # （见 load_v1_chunks_with_relations），缺省为空 → 本路径退化为
        # 无关系统计（fail-open 标注）。
        has_relations = any(getattr(c, "parent_id", None) for c in chunks)
        parent_children: dict[str, list[str]] = defaultdict(list)
        for c in chunks:
            pid = getattr(c, "parent_id", None)
            if pid:
                parent_children[pid].append(c)

        # tiny child 统计
        tiny = [c for c in chunks
                if c.chunk_type == "child" and c.length < TINY_CHILD_CHARS]
        tiny_by_source: dict[str, int] = defaultdict(int)
        tiny_shapes: dict[str, int] = defaultdict(int)
        for c in tiny:
            tiny_by_source[c.source] += 1
            tiny_shapes[classify_fragment(c.text)] += 1

        # parent 尺寸分布
        parent_lengths = sorted(
            c.length for c in chunks if c.chunk_type == "parent")

        # child ⊆ parent 包含健全性
        containment_bad: list[dict] = []
        checked = 0
        for c in chunks:
            pid = getattr(c, "parent_id", None)
            if not pid or c.chunk_type != "child":
                continue
            parent = parent_by_id.get(pid)
            if parent is None:
                containment_bad.append({
                    "chunk_id": c.chunk_id, "type": "missing_parent",
                    "parent_id": pid})
                continue
            checked += 1
            if c.text.strip() not in parent.text.strip():
                # 归一化后再试（换行歧义）
                if _norm(c.text) not in _norm(parent.text):
                    containment_bad.append({
                        "chunk_id": c.chunk_id,
                        "type": "not_substring",
                        "parent_id": pid,
                        "child_preview": c.text.strip()[:60],
                    })

        return {
            "has_relation_data": has_relations,
            "tiny_child_count": len(tiny),
            "tiny_child_by_source": dict(sorted(tiny_by_source.items())),
            "tiny_child_shapes": dict(tiny_shapes),
            "tiny_child_samples": [
                {"source": c.source, "chunk_id": c.chunk_id, "length": c.length,
                 "shape": classify_fragment(c.text),
                 "preview": c.text.strip()[:80].replace("\n", "\\n")}
                for c in sorted(tiny, key=lambda x: x.length)],
            "parent_count": len(parent_lengths),
            "parent_length_stats": {
                "min": parent_lengths[0] if parent_lengths else None,
                "median": (parent_lengths[len(parent_lengths) // 2]
                           if parent_lengths else None),
                "max": parent_lengths[-1] if parent_lengths else None,
            },
            "parent_by_source": dict(sorted(Counter(
                c.source for c in chunks if c.chunk_type == "parent").items())),
            "containment_checked": checked,
            "containment_violations": containment_bad[:20],
            "containment_violation_count": len(containment_bad),
        }

    def _audit_v2(self, chunks: list[ChunkInfo]) -> dict[str, Any]:
        tiny = [c for c in chunks if c.length < TINY_CHILD_CHARS]
        return {
            "tiny_chunk_count": len(tiny),
            "tiny_chunk_samples": [
                {"source": c.source, "chunk_id": c.chunk_id, "length": c.length,
                 "shape": classify_fragment(c.text),
                 "preview": c.text.strip()[:80].replace("\n", "\\n")}
                for c in sorted(tiny, key=lambda x: x.length)],
            "note": "sealed 行无 chunk_type/parent_chunk_id 字段，关系维度不适用",
        }


def _load_v1_with_relations(texts_dir: Path) -> list[ChunkInfo]:
    """与 prepare_index 同路径重建 v1 chunks，且把 parent 关系绑定到对象。"""
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
        # 直接遍历 chunk 对象（保留 parent_chunk_id 关系）
        document.chunks = chunk_document(document)
        for chunk in document.chunks:
            chunk_type = str(chunk.metadata.get("chunk_type", ""))
            info = ChunkInfo(
                source=path.name, chunk_id=chunk.chunk_id,
                chunk_type=chunk_type, text=chunk.text)
            info.parent_id = chunk.parent_chunk_id  # type: ignore[attr-defined]
            out.append(info)
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--v1-texts-dir", default="test_texts",
                        help="v1 test_texts 目录（只读）")
    parser.add_argument("--v2-chunks", default="data/v2-corpus/chunks/chunks.jsonl",
                        help="v2 sealed chunks.jsonl（只读）")
    parser.add_argument("--out-dir", default="results/audit-parentchild-quality",
                        help="审计输出目录")
    args = parser.parse_args(argv)

    audit = RelationAudit(
        v1_chunks=_load_v1_with_relations(Path(args.v1_texts_dir)),
        v2_chunks=load_v2_chunks(Path(args.v2_chunks)),
    )
    data = audit.build()

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "audit.json").write_text(
        json.dumps(data, ensure_ascii=False, indent=1, sort_keys=True) + "\n",
        encoding="utf-8")

    v1 = data["v1"]
    lines = [
        "# B1 审计：parent 划分质量（只读）",
        "",
        f"- tiny child 阈值：< {TINY_CHILD_CHARS} 字符",
        f"- v1: tiny child 共 **{v1['tiny_child_count']}** 块，"
        f"按 source: {v1['tiny_child_by_source']}；"
        f"形态: {v1['tiny_child_shapes']}",
        f"- v1: parent {v1['parent_count']} 块，尺寸 min={v1['parent_length_stats']['min']} "
        f"median={v1['parent_length_stats']['median']} "
        f"max={v1['parent_length_stats']['max']}",
        f"- v1: child⊆parent 健全性：检查 {v1['containment_checked']} 个 child，"
        f"违规 {v1['containment_violation_count']}（非子串或缺 parent）",
        f"- v1: tiny child 样例：",
        "",
        "| source | chunk_id | len | shape | preview |",
        "| --- | --- | --- | --- | --- |",
    ]
    for s in v1["tiny_child_samples"]:
        lines.append(f"| {s['source']} | {s['chunk_id']} | {s['length']} | "
                     f"{s['shape']} | {s['preview'].replace('|', '\\\\|')} |")
    if v1["containment_violations"]:
        lines += ["", "### child⊆parent 违规样例", ""]
        for v in v1["containment_violations"][:10]:
            lines.append(f"- `{v['chunk_id']}` → {v['type']} "
                         f"（parent={v.get('parent_id')}）"
                         f" preview={v.get('child_preview', '')!r}")
    lines += ["", f"- v2: tiny chunk（<30 字符）共 **{data['v2']['tiny_chunk_count']}** 块；"
                  "sealed 无关系字段，关系维度不适用", ""]
    (out_dir / "report.md").write_text("\n".join(lines), encoding="utf-8")

    print(f"[audit] v1 tiny_child={v1['tiny_child_count']} "
          f"parent={v1['parent_count']} "
          f"containment_violations={v1['containment_violation_count']}"
          f"（checked={v1['containment_checked']}）")
    print(f"[audit] v2 tiny={data['v2']['tiny_chunk_count']} 块")
    print(f"[audit] 汇总写至 {out_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
