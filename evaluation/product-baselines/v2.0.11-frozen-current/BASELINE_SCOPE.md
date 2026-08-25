# BASELINE_SCOPE — v2.0.11 frozen product retrieval baseline

## 本阶段测了什么

- 检索链路：生产 `model.encode` → Chroma（hnsw:space=cosine）→ BM25（CJK n-gram）→ RRF（k=60），对冻结 1006 chunks 建索引，136 条查询逐条跑当前检索代码（`src.rag.retrieve_hybrid_with_sources`）。
- 指标：chunk `recall@5/10/20`、`nDCG@5/10/20`、`MRR`、source recall@5/10/20；按 language / query_type / refusal 分组，每组记录 有效分母 n；无 chunk-level truth 的 31 个 refusal case 不进入召回分母。
- 最差失败样本清单（稳定排序，见 failure-analysis.md）。

## parser 阶段为什么独立测量（关键前提）

- 冻结语料由 `get_splitter`（纯 RecursiveCharacterTextSplitter，text 2000/200）构建；当前运行时 `_load_index_chunks` 走 src/loaders + src/chunking v3 Section 分块。实测复现审计：冻结 1006 chunks → 当前 chunker 重建 2947 chunks，文本精确命中 274（见 baseline-summary.json parser_drift_audit 逐 source 明细）。
- 因此冻结 evidence 的 `chunk_id` 真值**只对冻结 chunks 成立**；基线以冻结 chunks 为索引内容（检索链 embedding/Chroma/BM25/RRF 与产品逐函数一致），parser 行为以漂移审计单独报告，不混入召回指标。
- 含义：当前产品若直接索引语料文档，其 chunk 边界与冻结真值不兼容，chunk 级召回将不可测量——这是 Phase 6-B 的首要候选改进方向。

## 隔离与安全

- Chroma 位于一次性临时数据目录（`MNEME_DATA_DIR` 语义由适配器自行 `PersistentClient` 承担），从不引用 `src.rag.CHROMA_DB_PATH`，物理上不触碰用户持久化索引；不写 collection manifest / BM25 sidecar。
- 不调用生成模型 / LLM judge；无网络调用；不修改 v2.0.11 任何文件；不 stage / commit / push。
- 冻结输入校验：通过。

## 明确不是

- v2.0.11 仍是只读 CANDIDATE（activation_blocked=true、human_reviewed=false、TARGETED_REVIEW_BLOCKED），不代表 active、人工批准或 release。
- 本基线不是 answer-quality / citation / refusal 精度评测。