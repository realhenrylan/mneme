# REVIEW_AND_SPLIT_REBUILD_REQUIRED

v2.0.10 is a **CANDIDATE** (`activation_blocked=true`, `human_reviewed=false`).

- This authorised deterministic remediation adds six same-source raw evidence rows, retires `multi-019`, and removes one byte-identical `mixed-033` duplicate evidence row.
- v2.0.9 draft/evidence/review/triage remain immutable inputs.
- A new full blind automated review of all 136 cases is required; no previous review result may be reused.
- Do not create active metadata, a split, a locked configuration, or a v2.1 artifact unless a later explicit gate permits it.
- Passing strict evidence validation is not human review, confirmation, or activation approval.
