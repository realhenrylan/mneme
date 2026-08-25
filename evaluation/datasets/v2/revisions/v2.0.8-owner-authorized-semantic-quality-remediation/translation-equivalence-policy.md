# faithful_translation_equivalence_v1 — 严格限域翻译等价策略

## 适用范围

仅适用于 v2.0.7 reject semantic-quality decision pack 明示的 3 条 case：
`en-029`、`multi-019`、`zh-052`（逐答案点记录见 `translation-equivalence-ledger.jsonl`，恰 3 条）。
不得扩展到其他 case，也不得静默修改全局 review 标准。

## 规则

1. 中文答案点可由英文 source 的忠实语义等价表达支持；
2. 原文不得不存在该含义；答案点不得增加任何限定、比较、因果或结论；
3. 保留 source 原文、raw range、raw span、中文答案点、理由与授权标识；
4. **该策略不是自动 confirmed**——后续仍需盲态复审
   （deepseek-v4-pro / temperature=0.0 / max_tokens=8000 /
   thinking disabled / max_retries=3，无 fallback、无混用）；
5. 本策略不产生 overlay / active metadata / split / v2.1 产物，
   不改变 candidate draft/evidence。

## 授权

授权标识：`OWNER_AUTHORIZED_SEMANTIC_QUALITY_REMEDIATION_CHAIN_SAFE`；执行时间（确定性）：`2026-08-11T00:00:00+00:00`。
