# v2.0.3 Reannotation Blocker Audit

只读、确定性审计；未生成 after 文件、overlay 或 active metadata。

- `anchor_catalog_insufficient`: 0 — none
- `scoped_chunk_evidence_absent`: 2 — zh-032, zh-033
- `answer_semantics_not_directly_supported`: 8 — mixed-022, mixed-028, mixed-029, zh-026, zh-029, zh-036, zh-054, zh-055
- `source_scope_expansion_required`: 0 — none
- `model_or_schema_action_invalid`: 3 — zh-023, zh-035, zh-037
- `integrity_or_contract_blocker`: 0 — none

所有候选均 `requires_owner_authorization=true` 且 `auto_applicable=false`。
