# 安全设计

Mneme 将策略集中在 `src/security.py` 中，CLI、TUI、查询拆解和 Graph RAG 共享同一套检查。

## 端点安全

- **默认 HTTPS**：远程端点要求 HTTPS；回环地址（`localhost`、`127.0.0.1`、`::1`）允许 HTTP
- **显式覆盖**：非本地 HTTP 需要显式的 `MNEME_ALLOW_INSECURE_HTTP=1` 覆盖
- **客户端刷新**：Graph RAG 缓存绑定当前 API key 和 base URL，端点变更立即生效

## 文档安全措施

| 控制 | 默认值 | 目的 |
|---------|---------|---------|
| 文档大小限制 | 50 MiB（`52428800`） | 防止意外索引巨大文件 |
| PDF 页数限制 | 2000 页 | 限制提取时间和内存 |
| 文档根目录 | 可选（`MNEME_DOCUMENT_ROOT`） | 限制索引到特定目录树 |
| `.env` 拒绝 | 始终 | 防止 API Key 被索引 |

## 上下文边界

检索到的文本被放入显式的不可信文档边界中：

```text
[Source: report.pdf] [Citation: S1]
<untrusted_document chunk_id="source-a_chunk_3">
检索到的文本 ...
</untrusted_document>
```

模型被指示将此部分视为数据而非指令。即使文档中包含"忽略前面的指令"等文字，它也应留在不可信文档区域内。

### 上下文截断安全

上下文长度受限制（默认：60,000 字符）。Mneme 只截断 `document_text`，保留完整的来源标记、引用和开闭边界。当完整安全框架容纳不下时跳过该 chunk。安全边界不应该是预算紧张时第一个被牺牲的东西。

## 缓存安全

- Graph RAG 缓存使用 **Schema 验证的原子 JSON**，而不是加载 pickle
- 缓存必须匹配当前索引指纹和 manifest 版本
- 旧版 `.pkl` 文件在不加载的情况下失效

## 数据披露

索引和检索在本地运行，但检索到的文档片段会在查询拆解、Graph RAG 实体提取和回答生成时发送到配置的端点。引导向导会明确披露这一点。
