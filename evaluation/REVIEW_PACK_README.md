# P1 真值人工确认审阅包（review pack）使用说明

> 服务于 `plans/GRAPH-RAG-EVALUATION-PLAN-2026-08-02.md` §5.1：正式评测前
> 必须人工确认 chunk 真值。本工具**只导出、不判定**——它不调用 LLM/API，
> 不修改任何输入文件，也不替人填写结论。

## 1. 用途

| 产物 | 内容 | 人工要做的事 |
| --- | --- | --- |
| `review-overlap.jsonl` | 全部 `reviewer_status=needs_review` 的 overlap 匹配条目（27 条） | 逐条填写 `review_decision`（`confirmed` / `reject`）与 `reviewer_notes` |
| `missing-chunk-truth.jsonl` | 可回答但缺 chunk 真值的 case（数量随数据集标注变化） | 逐条填写 `relevance_level`（`chunk` / `source`）与 `reviewer_notes` |
| `review-pack-manifest.json` | 输入文件 SHA-256、版本与统计 | 无需修改 |

判定口径（与评测框架一致）：

- `review_decision=confirmed` 的 overlap 条目才会被 `compute_summary`
  等消费方视为可靠 chunk 真值；`reject` 表示该 snippet 与候选 chunk
  不匹配，需另行补标或降级为 source 级。
- `relevance_level=chunk`：该 case 存在可补标的内容 chunk 真值，需继续
  补标 `relevant_chunks`；`relevance_level=source`：元数据类问题不存在
  内容 chunk 真值，只能按 source 级评估（不进入 chunk/context/citation
  recall 分母，但进入 source recall 与答案评测）。

## 2. 运行

```powershell
python -m evaluation.review_pack `
  --dataset evaluation/datasets/v1.jsonl `
  --ground-truth results/graph-gate/dev/ground-truth-map.json `
  --output results/graph-gate/review-pack
```

可选：提供 chunk 文本快照以生成匹配证据（每条候选 chunk 的 bigram
重叠比例与文本预览），帮助人工判断：

```powershell
python -m evaluation.review_pack `
  --dataset evaluation/datasets/v1.jsonl `
  --ground-truth results/graph-gate/dev/ground-truth-map.json `
  --corpus-json chunks.json `
  --output results/graph-gate/review-pack
```

`chunks.json` 格式（从已有 Chroma collection 导出，本地操作）：

```python
import json, chromadb
client = chromadb.PersistentClient(path="data/chroma")
data = client.get_collection("kb_chunks").get(include=["documents", "metadatas"])
rows = [{"chunk_id": i, "source_id": m.get("source_id", ""), "text": d}
        for i, d, m in zip(data["ids"], data["documents"], data["metadatas"])]
json.dump(rows, open("chunks.json", "w", encoding="utf-8"), ensure_ascii=False)
```

不提供 `--corpus-json` 时 `match_evidence` 为空列表，候选 chunk ID 仍然
导出，可在语料中人工核对。

## 3. 字段说明

### review-overlap.jsonl（每条 needs_review 条目一行）

| 字段 | 来源 | 说明 |
| --- | --- | --- |
| `case_id` / `query` / `query_type` / `language` | dataset | case 上下文 |
| `source_id` / `normalized_snippet` | ground-truth-map | 标注片段（规范化后） |
| `candidate_chunk_ids` | ground-truth-map | overlap 匹配到的候选 chunk |
| `match_evidence` | 本地计算 | 每候选 chunk 的 `bigram_overlap`（snippet 与 chunk 字符 bigram 重叠比例，与匹配判定同口径）与 `text_preview` |
| `reviewer_status` | ground-truth-map | 恒为 `needs_review` |
| **`review_decision`** | **人工填写** | `confirmed`（匹配成立）或 `reject`（不成立） |
| **`reviewer_notes`** | **人工填写** | 备注（可选） |

### missing-chunk-truth.jsonl（每条缺真值 case 一行）

| 字段 | 来源 | 说明 |
| --- | --- | --- |
| `case_id` / `query` / `query_type` / `language` | dataset | case 上下文 |
| `relevant_source_ids` / `acceptable_answer_points` / `metadata` | dataset | 现有标注 |
| **`relevance_level`** | **人工填写** | `chunk`（需补标内容 chunk）或 `source`（无内容 chunk 真值） |
| **`reviewer_notes`** | **人工填写** | 备注（可选） |

## 4. 可复现性与安全

- 相同输入文件产出**逐字节相同**的审阅包：排序确定、无时间戳、
  manifest 记录输入 SHA-256。
- 工具只读输入（dataset / ground-truth-map / corpus 快照），只写
  `--output` 目录；不 stage/commit，不修改 `results/` 历史产物。
- 合法值校验：`relevance_level` 仅接受 `None` / `chunk` / `source`
  （`evaluation.compare.validate_relevance_level`），导入旧版
  ground-truth-map（无该字段）自动兼容。

## 5. 完整使用路径：填写 → 严格导入 → 评测消费

```text
第 1 步  人工填写（review pack 内两个 JSONL）
   ↓
第 2 步  python -m evaluation.review_apply --dataset ... --ground-truth ... \
             --review-pack <pack目录> --output <新目录>
   ↓
第 3 步  python -m evaluation.compare --reviewed-truth <overlay> ...
```

### 第 1 步：人工填写

在 review pack 目录内编辑：

- `review-overlap.jsonl`：每条 `review_decision` 填 `confirmed`（匹配成立）
  或 `reject`（不成立）；`reviewer_notes` 可选。
- `missing-chunk-truth.jsonl`：每条 `relevance_level` 填 `chunk`（需补标
  内容 chunk）或 `source`（无内容 chunk 真值）；`reviewer_notes` 可选。

**必须逐条填写**：未填（空值）会整体失败。

### 第 2 步：严格导入（evaluation.review_apply）

```powershell
python -m evaluation.review_apply `
  --dataset evaluation/datasets/v1.jsonl `
  --ground-truth results/graph-gate/dev/ground-truth-map.json `
  --review-pack results/graph-gate/review-pack `
  --output results/graph-gate/reviewed
```

fail-closed 校验（任何一项失败都整体拒绝、**不产生部分输出**）：

| 校验 | 说明 |
| --- | --- |
| manifest SHA | review-pack-manifest 记录的 dataset/ground-truth SHA-256 必须与当前输入一致（陈旧输入拒绝） |
| 行数 | 两 JSONL 行数必须等于 manifest 计数（重复/缺失/未知行拒绝） |
| 键集 | 每行键必须等于导出模板（未知/缺失列拒绝） |
| 必填值 | `review_decision` 只能是 `confirmed`/`reject`；`relevance_level` 只能是 `chunk`/`source`；空值拒绝 |

成功后输出到**新目录**（不得与 pack 目录相同，绝不覆盖输入）：

- `reviewed-truth-overlay.json`：版本化 overlay —— confirmed 映射为
  `reviewer_status=confirmed`，reject 映射为 `rejected`（**绝不把 reject
  当 confirmed**）；relevance_level 按 case_id 保存；无任何 secret。
- `review-apply-manifest.json`：输入/输出 SHA、计数与可选 notes。

### 第 3 步：评测消费（evaluation.compare --reviewed-truth）

```powershell
python -m evaluation.compare --dataset v1 --corpus-dir test_texts `
  --arms standard standard-rerank graph-rerank `
  --reviewed-truth results/graph-gate/reviewed/reviewed-truth-overlay.json `
  --output results/graph-gate/dev
```

消费端门禁（fail-closed）：

- **prepare_index 前**：overlay 版本/SHA 校验、case_id 存在性、标注
  存在性（dataset 中无该标注 → 陈旧 overlay 拒绝）。
- **GT 构建后、QueryPlan/LLM 前**：overlay 按稳定键
  (case_id/source_id/normalized_snippet/候选 chunk IDs) 精确应用；未消费
  条目、重复匹配、非法决定都失败并列出差异。
- **真值门禁**（LLM 前）：`relevance_level=source` → source-only，放行并
  从 chunk/context/citation 分母排除（现有统计口径不倒退，日志报告
  source-only 数；source recall 尚未实现）；`relevance_level=chunk` 但
  无可靠 chunk 真值 → 失败并列出 case_id 要求补标；overlap reject 导致
  case 失去全部可靠 chunk 真值且无显式 source 决定 → 同样失败。
- **不传 `--reviewed-truth`** 时保持旧行为（overlay 完全可选）。
