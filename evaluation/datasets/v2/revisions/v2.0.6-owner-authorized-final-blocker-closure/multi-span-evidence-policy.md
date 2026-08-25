# multi_span_exact_evidence_v1（zh-035）

## 定义
当一个答案点（此处为 zh-035 的 `fibo.py`）在语料中存在多个完全相同、可重建的 verbatim raw span 时，不得任选其中一个作为唯一证据；全部 span 均作为该答案点的证据写入。

## 已记录 span（6 个，稳定排序，全部满足 chunk_text[start:end] == raw_evidence_span）

- `python-tutorial-en.md` / `e564a122a7a2_chunk_61` `[1492,1499)` 其他 source（需显式 scope expansion）
- `python-tutorial-en.md` / `e564a122a7a2_chunk_64` `[1523,1530)` 其他 source（需显式 scope expansion）
- `python-tutorial-en.md` / `e564a122a7a2_chunk_65` `[190,197)` 其他 source（需显式 scope expansion）
- `python-tutorial-zh.md` / `32c427fb50e2_chunk_30` `[550,557)` declared source 内
- `python-tutorial-zh.md` / `32c427fb50e2_chunk_31` `[992,999)` declared source 内
- `python-tutorial-zh.md` / `32c427fb50e2_chunk_31` `[1263,1270)` declared source 内

## 治理
- 本 policy 为需所有者批准的新 evidence policy，此处已由所有者授权启用。
- 跨 source span 的 scope 扩展已显式记录为 `OWNER_AUTHORIZED_MULTI_SOURCE_EXACT_EVIDENCE_SCOPE_EXPANSION`，见 manifest 与 reannotation-diff。
- 每个 span 独立记录 raw source、chunk、`[start,end)` 与 raw span SHA（见 multi-span-evidence-ledger.jsonl）。
- 记录者：OWNER_AUTHORIZED_FINAL_BLOCKER_CLOSURE；candidate 状态：revision_status=CANDIDATE、activation_blocked=true。
