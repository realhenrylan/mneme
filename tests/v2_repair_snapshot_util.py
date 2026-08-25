"""Task 12 共享工具：从版本化修复目录重建「修复前」输入集。

Task 12（v2.0.1 持续 reject 最小证据修复）已批准地重生了空白
human-review pack 并原位更新了草稿。历史 real-corpus 测试校验的是
**修复前不变式**（blank pack 与 llm-filled pack 除三个人工字段外逐行
一致、盲包确定性重建一致、审计输入 SHA 链一致等）。本工具从
``evaluation/datasets/v2/revisions/v2.0.1-persistent-reject-repair/``
的字节快照（draft-before.jsonl / pack-before.jsonl）重建修复前输入，
使历史测试继续验证历史产物；pack manifest / report / instructions
由同一修复前草稿确定性重建（与历史字节一致）。
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REVISION_DIR = ROOT / "evaluation" / "datasets" / "v2" / "revisions" / \
    "v2.0.1-persistent-reject-repair"
SNAPSHOT_AVAILABLE = (REVISION_DIR / "draft-before.jsonl").is_file() and \
    (REVISION_DIR / "pack-before.jsonl").is_file()


def pre_repair_dir(tmp_path: Path) -> Path:
    """重建修复前输入目录（draft / pack / pack-manifest / report）。

    快照缺失（未运行过修复）时回退为当前文件——此时当前文件即为修复前
    状态。
    """
    if not SNAPSHOT_AVAILABLE:
        return ROOT / "evaluation" / "datasets" / "v2" / "human-review"
    sys.path.insert(0, str(ROOT))
    import scripts.corpus_v2_human_review_pack as hp  # noqa: PLC0415
    d = tmp_path / "pre-repair"
    d.mkdir(exist_ok=True)
    (d / "draft-before.jsonl").write_bytes(
        (REVISION_DIR / "draft-before.jsonl").read_bytes())
    # pack / manifest / report / instructions 由修复前草稿确定性重建
    hp.build_pack(d / "draft-before.jsonl", hp.DEFAULT_CHUNKS,
                  hp.DEFAULT_CHUNK_MANIFEST, hp.DEFAULT_CORPUS_MANIFEST,
                  hp.DEFAULT_LEDGER, d)
    return d


def pre_repair_pack(tmp_path: Path) -> Path:
    """修复前空白 pack 路径（快照优先，缺失回退当前文件）。"""
    if not SNAPSHOT_AVAILABLE:
        return ROOT / "evaluation" / "datasets" / "v2" / "human-review" / \
            "human-review-pack.jsonl"
    return pre_repair_dir(tmp_path) / "human-review-pack.jsonl"


def pre_repair_draft(tmp_path: Path) -> Path:
    """修复前草稿路径（快照优先，缺失回退当前文件）。"""
    if not SNAPSHOT_AVAILABLE:
        return ROOT / "evaluation" / "datasets" / "v2" / "annotations" / \
            "v2-cases-draft.jsonl"
    return pre_repair_dir(tmp_path) / "draft-before.jsonl"
