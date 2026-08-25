# 复现命令

```bash
python evaluation/refusal_separability.py \
  --dev-retrieval results/graph-gate/refusal-ablation-20260805T133209/dev-full/retrieval-cases.jsonl \
  --holdout-retrieval results/graph-gate/production-baseline-stable-20260805T084256/holdout-full/retrieval-cases.jsonl \
  --output-dir <timestamped-output-dir>
```

产物：feature-dictionary.json / features.jsonl / rule-enumeration.json /
pr-curves.json / separability-report.md / decision-report.md /
manifest.json / run-commands.md（全部标记
HYPOTHESIS_GENERATING_ONLY）。
