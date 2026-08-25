# production-baseline-stable-20260805T084256 — 运行命令记录

> 目的：在**稳定 split + split_fingerprint 锁定配置**下正式重跑生产基线
> 评测（dev 95 / holdout 15，split 与 PYTHONHASHSEED 无关），产出
> CANDIDATE v2 报告。全部产物标注为 CANDIDATE，非人工签署、非正式上线批准。
>
> 生产基线：arms=[standard]（RAG_RERANKER=none）、
> RAG_SELECTOR_MAX_PER_SOURCE=3（arm_selector_policy={"standard": 3}）、
> Graph 禁用（kg_sha256=None）、alpha=1.0。
> 锁：stable-split-rebuild-20260804T234043/lock-production-stable.json
> （split_fingerprint=454892e4…3690，固定字段与历史锁逐字段一致）。

## 1. precheck（PASS）

```bash
RAG_RERANKER=none PYTHONHASHSEED=0 python precheck.py
# PASS：locked config（含 split_fingerprint）/ 稳定 split 指纹 /
#       双 overlay 消费 + truth gate / index 指纹 / env / immutability 快照
```

## 2. 分层 smoke（PASS 6/6）

```bash
RAG_RERANKER=none PYTHONHASHSEED=0 python smoke.py
# 中文 zh-014 / 英文 en-005 / 多轮 multi-006（canonical history 2 轮）/
# source-only cross-008 / 拒答 noanswer-010（feature-based 拒答触发）/
# citation（4 case 引用 [S1..Smax] 全部连续）
# → smoke-results.json
```

## 3. 阶段 1 独立子代理验证（PASS 17 项，phase1-verification.json）

独立复算：双 PYTHONHASHSEED 下 split 指纹逐字节一致 == 锁；
dataset/corpus/index SHA；overlay 消费与 gate；smoke 记录。
观察项（非阻断）：holdout overlay 的 case_relevance_levels 引用 dev 侧
4 个 source-only（review_pack 全数据集导出机制，无功能影响）。

## 4. 正式评测（均 exit 0）

```bash
# dev full（95 例）
RAG_RERANKER=none PYTHONHASHSEED=0 PYTHONUNBUFFERED=1 python -m evaluation.compare \
  --dataset v1 --corpus-dir test_texts --split development --phase full \
  --arms standard --alpha-grid 1.0 --seed 42 \
  --config "...\stable-split-rebuild-20260804T234043\lock-production-stable.json" \
  --reviewed-truth "...\stable-split-rebuild-20260804T234043\reviewed-production-dev\reviewed-truth-overlay.json" \
  --collection-name eval-autorun-lock \
  --output "...\production-baseline-stable-20260805T084256\dev-full" \
  --bootstrap-iterations 1000 --bootstrap-seed 42   # → dev-full.log

# holdout full（15 例，同一锁 + holdout overlay）
# 同上，--split holdout + reviewed-production-holdout overlay → holdout-full.log
```

## 5. 指标提取与报告

```bash
python extract_candidate_report.py   # → candidate-report-data.json
# candidate-report.md（CANDIDATE v2：LLM 辅助审阅真值 + 稳定 split；
# 旧结果不可比原因；阈值建议待人工批准）
```

## 6. 验证

```bash
python -m pytest -q                  # 完整套件
python -m py_compile ...             # 变更文件
git diff --check
# immutability：precheck-snapshot.json 快照复验（历史 results 未改写）
```

## 关键环境

- PYTHONHASHSEED=0 仅记录（稳定 split 不依赖；子代理已用 =0/=42 双环境复证）
- LLM_MODEL=deepseek-chat（锁校验通过）；API_KEY/BASE_URL 存在性检查（值不落盘）
