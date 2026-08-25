# Citation v2 分母统一 — 历史产物离线对账报告

> 只读对账：从历史 generation-cases.jsonl 确定性重算新口径；
> 不改写任何历史 summary / 报告 / JSONL；输出仅在本目录。

## 一、分母契约（唯一命名）

| 分母 | 含义 |
|---|---|
| `all_generation_cases` | 该 arm 全部 generation case（含 refusal/error） |
| `answerable_generation_cases` | 非 should_refuse 且非 error 的 case |
| `answers_with_any_citation` | answerable 中至少一个唯一引用 ID 的 case |
| `total_unique_citation_ids` | 可答答案的唯一引用 ID 总数（重复引用计一次） |

新指标（value=None = 分母为 0 → unavailable，不伪装为 0）：

| 指标 | numerator | denominator | excluded_count |
|---|---|---|---|
| `context_supported_citation_validity_micro` | context-supported 唯一 ID 数 | `total_unique_citation_ids` | 无引用/缺证据答案数（行） |
| `context_supported_answer_rate` | ≥1 个 context-supported 引用的答案数 | `answerable_generation_cases` | refusal+error 行数 |
| `no_citation_answer_rate` | 无引用 ID 的答案数 | `answerable_generation_cases` | refusal+error 行数 |
| `citation_mention_rate` | 至少一个引用 ID 的答案数 | `answerable_generation_cases` | refusal+error 行数 |

旧键（citation_id_validity / citation_precision / citation_recall /
faithfulness / context_supported_citation_validity 单值）为 legacy/deprecated，仅兼容读取；guardrail 只能消费上表新指标。

## 二、逐运行对账

### auto-run-20260804T121410（auto-run（citation v1 时代））

- 可重算新口径：**否**
- 运行目录：`D:\GitHub\mneme\results\graph-gate\auto-run-20260804T121410`

#### dev-full（rows=285）

| arm | 旧值（legacy 全体分母） | 旧分析值（可答分母，若可读） | 新：validity_micro | 新：answer_rate | 新：no_citation_rate | 分母（answerable / unique IDs） |
|---|---|---|---|---|---|---|
| graph-rerank | citation_id_validity=0.6526 | — | unavailable | unavailable | unavailable | 0 / 0 |
| standard | citation_id_validity=0.7263 | — | unavailable | unavailable | unavailable | 0 / 0 |
| standard-rerank | citation_id_validity=0.6316 | — | unavailable | unavailable | unavailable | 0 / 0 |

#### holdout-full（rows=48）

| arm | 旧值（legacy 全体分母） | 旧分析值（可答分母，若可读） | 新：validity_micro | 新：answer_rate | 新：no_citation_rate | 分母（answerable / unique IDs） |
|---|---|---|---|---|---|---|
| graph-rerank | citation_id_validity=0.6250 | — | unavailable | unavailable | unavailable | 0 / 0 |
| standard | citation_id_validity=0.6875 | — | unavailable | unavailable | unavailable | 0 / 0 |
| standard-rerank | citation_id_validity=0.5000 | — | unavailable | unavailable | unavailable | 0 / 0 |

### reranker-recheck-20260804T185937（reranker-recheck（citation v1 时代））

- 可重算新口径：**否**
- 运行目录：`D:\GitHub\mneme\results\graph-gate\reranker-recheck-20260804T185937`

#### dev-full（rows=190）

| arm | 旧值（legacy 全体分母） | 旧分析值（可答分母，若可读） | 新：validity_micro | 新：answer_rate | 新：no_citation_rate | 分母（answerable / unique IDs） |
|---|---|---|---|---|---|---|
| standard | citation_id_validity=0.6947 | ab-analysis.json:0.8493 | unavailable | unavailable | unavailable | 0 / 0 |
| standard-rerank | citation_id_validity=0.6526 | ab-analysis.json:0.8356 | unavailable | unavailable | unavailable | 0 / 0 |

#### holdout-full（rows=30）

| arm | 旧值（legacy 全体分母） | 旧分析值（可答分母，若可读） | 新：validity_micro | 新：answer_rate | 新：no_citation_rate | 分母（answerable / unique IDs） |
|---|---|---|---|---|---|---|
| standard | citation_id_validity=0.6667 | ab-analysis.json:0.8333 | unavailable | unavailable | unavailable | 0 / 0 |
| standard-rerank | citation_id_validity=0.4667 | ab-analysis.json:0.5833 | unavailable | unavailable | unavailable | 0 / 0 |

### selector-ablation-20260804T202048（selector-ablation（citation v2））

- 可重算新口径：**是**
- 运行目录：`D:\GitHub\mneme\results\graph-gate\selector-ablation-20260804T202048`

#### dev-full（rows=188）

| arm | 旧值（legacy 全体分母） | 旧分析值（可答分母，若可读） | 新：validity_micro | 新：answer_rate | 新：no_citation_rate | 分母（answerable / unique IDs） |
|---|---|---|---|---|---|---|
| selector-cap3 | citation_id_validity=0.6915; context_supported_citation_validity=0.6915 | s0s3-analysis.json:0.8472 | 1.0000 | 0.8472 | 0.1528 | 72 / 145 |
| selector-unlimited | citation_id_validity=0.7128; context_supported_citation_validity=0.7128 | s0s3-analysis.json:0.8750 | 1.0000 | 0.8750 | 0.1250 | 72 / 150 |

#### holdout-full（rows=30）

| arm | 旧值（legacy 全体分母） | 旧分析值（可答分母，若可读） | 新：validity_micro | 新：answer_rate | 新：no_citation_rate | 分母（answerable / unique IDs） |
|---|---|---|---|---|---|---|
| selector-cap3 | citation_id_validity=0.6667; context_supported_citation_validity=0.6667 | s0s3-analysis.json:0.8333 | 1.0000 | 0.8333 | 0.1667 | 12 / 23 |
| selector-unlimited | citation_id_validity=0.7333; context_supported_citation_validity=0.7333 | s0s3-analysis.json:0.8333 | 1.0000 | 0.8333 | 0.1667 | 12 / 25 |

## 三、不可解释情况

- **auto-run-20260804T121410/dev-full/graph-rerank**：73 行缺 context 证据（citation v1 时代产物），context-supported 新口径不可重算 → unavailable。
- **auto-run-20260804T121410/dev-full/standard**：73 行缺 context 证据（citation v1 时代产物），context-supported 新口径不可重算 → unavailable。
- **auto-run-20260804T121410/dev-full/standard-rerank**：73 行缺 context 证据（citation v1 时代产物），context-supported 新口径不可重算 → unavailable。
- **auto-run-20260804T121410/holdout-full/graph-rerank**：13 行缺 context 证据（citation v1 时代产物），context-supported 新口径不可重算 → unavailable。
- **auto-run-20260804T121410/holdout-full/standard**：13 行缺 context 证据（citation v1 时代产物），context-supported 新口径不可重算 → unavailable。
- **auto-run-20260804T121410/holdout-full/standard-rerank**：13 行缺 context 证据（citation v1 时代产物），context-supported 新口径不可重算 → unavailable。
- **reranker-recheck-20260804T185937/dev-full/standard**：73 行缺 context 证据（citation v1 时代产物），context-supported 新口径不可重算 → unavailable。
- **reranker-recheck-20260804T185937/dev-full/standard-rerank**：73 行缺 context 证据（citation v1 时代产物），context-supported 新口径不可重算 → unavailable。
- **reranker-recheck-20260804T185937/holdout-full/standard**：12 行缺 context 证据（citation v1 时代产物），context-supported 新口径不可重算 → unavailable。
- **reranker-recheck-20260804T185937/holdout-full/standard-rerank**：12 行缺 context 证据（citation v1 时代产物），context-supported 新口径不可重算 → unavailable。

## 四、guardrail 就绪性

- 可作为 citation v2 guardrail 基线候选的运行：**仅 citation v2 schema 且重算一致者**（本批为 `selector-ablation-20260804T202048`）。
- v1 时代运行（auto-run / reranker-recheck）的 citation 指标（含 precision/recall/faithfulness 占位值）不得作为 guardrail输入，仅作 legacy 对账记录。
- guardrail 阈值建立前必须固定分母（本契约已显式命名）；历史报告中的 0.875/0.847（可答分母）与 0.713/0.691（全体分母）差异由此解释，非指标 bug。

*本报告由 `evaluation/reconcile_citation_denominators.py` 只读生成；未修改任何历史产物。*
