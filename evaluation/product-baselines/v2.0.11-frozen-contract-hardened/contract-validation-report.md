# Contract Validation Report — v2.0.11 frozen contract baseline

## chunk snapshot contract 字段映射（chunks.jsonl → 产品索引）

| chunks.jsonl 字段 | 产品映射 | 说明 |
|---|---|---|
| `chunk_id` | Chroma id + metadata.chunk_id | `{source_sha256_prefix12}_chunk_{n}`，前缀 = `source_id[:12]`（逐 chunk 核验） |
| `index` | metadata.chunk_index | 每 source 内连续 0..n-1（已核验） |
| `source`（basename） | metadata.source_name / source | 展示与 evidence 对齐字段；**不是**身份主键 |
| `text` | Chroma document + BM25 输入 | 逐 chunk 文本 SHA 进入契约指纹 |
| corpus-manifest `path` | metadata.source_path + source_id | canonical 路径；`source_id = sha256(normcase(realpath))` 全 64 位 |
| corpus-manifest `file_sha256`/`size` | metadata.content_sha256 / source_size | 与磁盘字节核验 |

## 验证清单

- 验证检查项：**54** 全部通过（fail-closed：任一失败即零写入）。
- chunks：**1006**；sources：**13**；chunks_sha256：`3724ce4e32526c5d…`
- 调用方 source 集合与声明集合**精确一致**（无缺失/无额外）。
- 契约指纹：`4a78d5f357d7b7e6381da9a78fa15b9d2773b818a29ab52223b03b06ed20687e`
- 冻结输入校验（freeze/candidate/targeted-review manifest 复算）：通过 （61 项，漂移 0 项）
- Phase 6-A baseline manifest 复算：通过 （50 项，漂移 0 项）

## 索引与 sidecar（完整产品路径）

- collection：`v211_frozen_contract_baseline`，chunks=1006，manifest_version=1
- collection manifest `config.snapshot`：记录契约版本/指纹/输入 SHA（fingerprint 一致：True）
- BM25 sidecar：chunk_ids 与索引一致（1006 条）
- 隔离：Chroma 位于一次性临时目录 `C:\Users\HENRYL~1\AppData\Local\Temp\mneme-v211-contract-fsdo8f51\chroma_db`；从不引用 `src.rag.CHROMA_DB_PATH`，不触碰用户持久化索引。

## 明确不是

- v2.0.11 仍是只读 CANDIDATE（activation_blocked=true、human_reviewed=false），不代表 active、人工批准或 release。
- 本基线不是 answer-quality / citation-faithfulness / refusal 精度评测。