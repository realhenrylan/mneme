"""构建分层 smoke 子集：数据集 JSONL + 派生 overlay（仅 AUTOMATED_DIAGNOSTIC 用途）。

子集 12 例，覆盖：zh（zh-001/zh-002）、多轮链（multi-001..003）、
graph_target=cross_document（cross-001/cross-002/mixed-006）、
source-only（meta-001/cross-008）、refusal（noanswer-001）。

overlay 为原 auto 标注 overlay 的过滤副本：只保留子集 case 的 entries/
case_relevance_levels，dataset_sha256 重算为子集文件哈希；不修改原 overlay。
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

OUT = Path(__file__).resolve().parent
OLD_RUN = ROOT / "results/graph-gate/auto-run-20260804T121410"
DATASET = ROOT / "evaluation/datasets/v1.jsonl"
ORIG_OVERLAY = OLD_RUN / "auto-reviewed-truth/reviewed-truth-overlay.json"

SMOKE_IDS = [
    "zh-001", "zh-002",
    "multi-001", "multi-002", "multi-003",
    "cross-001", "cross-002", "mixed-006", "mixed-001",
    "meta-001", "cross-008",
    "noanswer-001",
]

cases = [json.loads(l) for l in DATASET.read_text(encoding="utf-8").splitlines()]
smoke = [c for c in cases if c["id"] in SMOKE_IDS]
assert len(smoke) == len(SMOKE_IDS), (
    f"subset mismatch: {len(smoke)} != {len(SMOKE_IDS)}")
smoke_jsonl = "\n".join(json.dumps(c, ensure_ascii=False) for c in smoke) + "\n"
smoke_path = OUT / "smoke-v1.jsonl"
# newline="" 关闭 Windows CRLF 翻译，保证文件字节 == 哈希输入字节
with open(smoke_path, "w", encoding="utf-8", newline="") as f:
    f.write(smoke_jsonl)
smoke_hash = hashlib.sha256(smoke_path.read_bytes()).hexdigest()

ov = json.loads(ORIG_OVERLAY.read_text(encoding="utf-8"))
idset = set(SMOKE_IDS)
sub_ov = {
    "version": ov["version"],
    "dataset_sha256": smoke_hash,
    "ground_truth_sha256": ov["ground_truth_sha256"],  # 原值保留；本 overlay 仅 smoke 派生
    "entries": [e for e in ov["entries"] if e["case_id"] in idset],
    "case_relevance_levels": [
        e for e in ov["case_relevance_levels"] if e["case_id"] in idset
    ],
    "counts": {k: v for k, v in ov["counts"].items()},
    "notes": (
        "AUTOMATED_DIAGNOSTIC derived overlay for stratified smoke only: "
        "filtered subset of the auto-reviewed overlay; not human-reviewed; "
        "original overlay at auto-run-20260804T121410/auto-reviewed-truth/"
    ),
}
sub_ov["counts"]["n_entries"] = len(sub_ov["entries"])
sub_ov["counts"]["n_case_relevance_levels"] = len(sub_ov["case_relevance_levels"])
ov_path = OUT / "smoke-overlay.json"
ov_path.write_text(json.dumps(sub_ov, ensure_ascii=False, indent=2) + "\n",
                   encoding="utf-8")

print(f"✓ smoke-v1.jsonl: {len(smoke)} cases, sha256={smoke_hash}")
print(f"  languages={sorted({c['language'] for c in smoke})}")
print(f"  query_types={sorted({c['query_type'] for c in smoke})}")
print(f"  refusal={sum(1 for c in smoke if c.get('should_refuse'))}, "
      f"no_chunk_truth={sum(1 for c in smoke if not c.get('should_refuse') and not c.get('relevant_chunks'))}")
print(f"✓ smoke-overlay.json: {len(sub_ov['entries'])} entries, "
      f"{len(sub_ov['case_relevance_levels'])} case levels")
