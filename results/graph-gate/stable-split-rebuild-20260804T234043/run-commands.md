# 稳定 split 重建：运行命令记录

> 本目录：稳定 split（group-aware split 永久修复后）离线真值产物重建。
> 约束遵守：不调用 LLM/API、不重跑 full 评测、不 stage/commit、
> 不改写任何历史 results / decision-report.md / 原 candidate-report.md。

## 1. 框架修复（TDD）

- RED：`tests/test_compare.py::TestGroupAwareSplitHashSeedDeterminism`（3 个
  PYTHONHASHSEED 子进程断言集合与顺序一致）——旧代码实测失败：
  seed=1 的 holdout 为 multi-004/005/006 链，seed=0/42 为 multi-007/008/009/010 链。
- GREEN：`evaluation/compare.py::group_aware_split` 稳定排序
  （`sorted(chain_root_ids)` + `sorted(chains.items())` + 输出按 case_id 排序）；
  新增 `compute_split_fingerprint`（canonical SHA-256）。
- 锁定：`evaluation/locked_config.py` build 必填 / load 格式校验（legacy 兼容）/
  validate fail-closed 比对；`compare.main()` 在索引/LLM 前校验
  （--config 预检传 `split_fingerprint`；--lock 生成写入）。
- 测试：`tests/test_locked_config.py::TestSplitFingerprintLocking` +
  CLI `test_holdout_split_fingerprint_mismatch_rejected_before_index`。

## 2. 重建产物（本目录）

```bash
python results/graph-gate/stable-split-rebuild-20260804T234043/rebuild_gt_maps.py
# → split-manifest.json（fingerprint=454892e4…, dev=95, holdout=15）
# → ground-truth-map-{dev,holdout}.json + review-pack-{dev,holdout}/

python results/graph-gate/stable-split-rebuild-20260804T234043/migrate_pack_decisions.py \
  results/graph-gate/review-pack-chunk-annotated \
  results/graph-gate/stable-split-rebuild-20260804T234043/review-pack-dev \
  results/graph-gate/stable-split-rebuild-20260804T234043/review-pack-dev-filled
# （holdout 同理）→ 21/21 + 4/4（dev）、4/4 + 4/4（holdout）全部迁移

python -m evaluation.review_apply --dataset evaluation/datasets/v1.jsonl \
  --ground-truth results/graph-gate/stable-split-rebuild-20260804T234043/ground-truth-map-dev.json \
  --review-pack results/graph-gate/stable-split-rebuild-20260804T234043/review-pack-dev-filled \
  --output results/graph-gate/stable-split-rebuild-20260804T234043/reviewed-production-dev \
  --notes "..."
# （holdout 同理）→ 双 split PASS

python results/graph-gate/stable-split-rebuild-20260804T234043/gen_lock.py
# → lock-production-stable.json（固定字段与 lock-production.json 一致 + split_fingerprint）

python results/graph-gate/stable-split-rebuild-20260804T234043/verify_truth_integrity.py
# → RESULT: PASS
```

## 3. 验证

```bash
python -m pytest tests/test_compare.py tests/test_locked_config.py \
  tests/test_review_apply.py tests/test_review_pack.py -q     # 全部通过
python -m pytest -q                                            # 完整套件
python -m py_compile evaluation/compare.py evaluation/locked_config.py ...
git diff --check
```

## 4. 事实披露

- 25 条 overlap 决策为 LLM 辅助审阅，非人工签署 → 见 `stable-split-addendum.md`；
- 2 条 reject（en-004、mixed-005）保留于 canonical pack 历史记录；
- 旧候选数字（dev 94/holdout 16）基于已作废拆分，新稳定 split 为
  dev 95/holdout 15（fingerprint `454892e4…`），正式基线需重跑评测。
