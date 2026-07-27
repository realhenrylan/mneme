# 关于 Mneme

Mneme 是一个本地文档检索增强生成（RAG）系统，以 **Mnemosyne**——希腊神话中的记忆女神——命名。

## 项目目标

将本地文档集合变成可验证、可查询的记忆。每个回答都应能追溯到具体的文件、页码和 chunk。

## Mneme 是什么

- 一个 **Python CLI**，用于一次性批处理文档问答
- 一个 **双语终端 UI**（TUI），用于带文件监听的交互式会话
- 一个 **混合检索引擎**，结合语义搜索（ChromaDB + Sentence Transformers）和词法搜索（BM25）
- 一个 **Graph RAG** 模式，用于跨文档关系查询
- 一个 **安全优先** 的系统，具有显式数据边界、端点验证和资源限制

## Mneme 不是什么

- 不是云服务 — 所有索引在本地运行
- 不是数据永远不会离开本机的保证 — 检索到的片段会发送到你配置的 LLM 端点
- 不是替代阅读原始文档 — 它通过快速检索和摘要增强阅读

## 架构原则

1. **身份优先** — 稳定的 `source_id`、`chunk_id` 和内容哈希防止索引漂移
2. **版本化变更** — 原子 manifest 更新保持向量存储、BM25 和图缓存一致
3. **显式边界** — 不可信文档标签将检索文本与系统指令分离
4. **可度量质量** — Recall@k、MRR、nDCG 和 quality gate 的 benchmark 工具
5. **离线安全测试** — CI 无需 API key 运行；集成测试为 opt-in

## 许可证

[MIT License](https://github.com/realhenrylan/mneme/blob/main/LICENSE)

## 作者

由 [Henry Lan](https://github.com/realhenrylan) 构建。

## 链接

- [GitHub 仓库](https://github.com/realhenrylan/mneme)
- [Issues & Discussions](https://github.com/realhenrylan/mneme/issues)
- [首页](/zh/)
