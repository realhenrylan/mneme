# 复现命令

```bash
python evaluation/threshold_scan.py \
  --dev-retrieval results/graph-gate/refusal-ablation-20260805T133209/dev-full/retrieval-cases.jsonl \
  --dev-retrieval-cross results/graph-gate/production-baseline-stable-20260805T084256/dev-full/retrieval-cases.jsonl \
  --dev-generation results/graph-gate/refusal-ablation-20260805T133209/dev-full/generation-cases.jsonl \
  --holdout-retrieval results/graph-gate/production-baseline-stable-20260805T084256/holdout-full/retrieval-cases.jsonl \
  --output-dir <timestamped-output-dir>
```

产物：threshold-scan.json / threshold-scan.md / 
gate-pre-registration.json / decision-report.md / manifest.json / 
run-commands.md。
