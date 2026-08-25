# Schema Compatibility Report — v1 EvalCase ↔ v2.0.11 draft/evidence

## 结论

v2.0.11 `draft-after.jsonl` **不能**直接喂给 v1 `evaluation.schema.load_dataset`/`EvalCase.from_dict`：draft 行携带 v1 契约之外的字段（annotation / doc_target / is_refusal_turn / note / relevance_level / relevant_chunk_ids），且 `relevant_chunks` 元素含 `chunk_id` 键。适配器在内存中完成字段映射（本文件），绝不回写 v2.0.11。

## draft 字段映射

| 字段 | 映射 | 说明 |
|---|---|---|
| acceptable_answer_points | 直接映射 | v1 契约字段 |
| id | 直接映射 | v1 契约字段 |
| language | 直接映射 | v1 契约字段 |
| metadata | 直接映射 | v1 契约字段 |
| query | 直接映射 | v1 契约字段 |
| query_type | 直接映射 | v1 契约字段 |
| relevant_chunks | 直接映射 | v1 契约字段 |
| relevant_source_ids | 直接映射 | v1 契约字段 |
| should_refuse | 直接映射 | v1 契约字段 |
| annotation | 不映射 | 标注溯源元数据（annotated_by/review_status），不是评测真值，v1 EvalCase 无此字段 |
| doc_target | 不映射 | 草稿构造字段（仅 18/136 行存在），运行时无真值角色 |
| is_refusal_turn | 不映射 | 草稿链内标记（18/136 行），拒答语义由 v1 兼容的 should_refuse 表达 |
| note | 不映射 | 人工可读标注备注，不进入指标 |
| relevance_level | 不映射 | 派生标记（chunk/none），与真值存在性冗余 |
| relevant_chunk_ids | 不映射 | draft 侧镜像；真值以 evidence-after.jsonl 为准，不一致时记录 divergence |

## evidence 字段映射

真值（chunk/source 级）以 `evidence-after.jsonl` 为准；`chunk_text_sha256` 已 149/149 与冻结 `chunks.jsonl` 逐字节核验。snippet / char_range / coordinate_contract 等溯源字段不进入指标。

## 数据观测（冻结数据固有特性，不做“修复”）

- draft↔evidence chunk 集不一致 case：**17**
- draft↔evidence source 集不一致 case：**8**
- mapping failure（evidence chunk_id 不在冻结语料）：**0**
- case 数：total=136，with_chunk_truth=105，no_chunk_truth=31

## 冻结校验

- 冻结输入校验：通过 （61 项复算，漂移 0 项）