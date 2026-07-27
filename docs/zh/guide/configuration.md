# 配置

复制 `.env.example` 作为起点。主要设置如下：

| 变量 | 默认值 | 说明 |
|----------|---------|-------------|
| `API_KEY` | — | OpenAI 兼容 API Key |
| `BASE_URL` | `https://api.openai.com/v1` | LLM 端点；远程端点必须使用 HTTPS |
| `LLM_MODEL` | `deepseek-chat` | 聊天和查询拆解模型 |
| `LLM_TEMPERATURE` | `0.2` | 生成温度 |
| `LLM_TOP_K_MIN` | `12` | 标准检索的最小检索 chunk 数 |
| `LLM_TOP_K_MAX` | `70` | 标准检索的最大检索 chunk 数 |
| `ALPHA` | `0.7` | Graph RAG 语义/图融合权重 |
| `RAG_WATCH_DIR` | — | TUI 监听的目录 |
| `EMBEDDING_MODEL_PATH` | — | 本地 Embedding 模型路径；优先使用 |
| `EMBEDDING_MODEL_NAME` | `all-MiniLM-L6-v2` | 用于本地/ModelScope 加载的 Embedding 模型 ID |
| `MNEME_DOCUMENT_ROOT` | — | 允许索引文件的可选根目录 |
| `MNEME_MAX_DOCUMENT_BYTES` | `52428800` | 最大文档大小，50 MiB |
| `MNEME_MAX_PDF_PAGES` | `2000` | 单个 PDF 接受的最大页数 |
| `MNEME_MAX_REMOTE_CONTEXT_CHARS` | `60000` | 发送到 LLM 端点的最大检索上下文 |
| `MNEME_ALLOW_INSECURE_HTTP` | 未设置 | 显式允许非本地 HTTP 端点；仅用于受控开发 |

## Embedding 模型加载

Embedding 模型首先从配置的本地路径或缓存加载。如果不可用，Mneme 使用配置的模型 ID 进行 ModelScope 回退；默认为 `all-MiniLM-L6-v2`。

## 端点安全

对于非本地端点，默认要求 HTTPS。纯 HTTP 仅允许用于回环地址，如 `localhost`、`127.0.0.1` 和 `::1`。非本地 HTTP 端点需要显式的 `MNEME_ALLOW_INSECURE_HTTP=1` 覆盖。

## 文档安全措施

- 文档大小、PDF 页数和可选的允许文档根目录可以受限
- `.env` 被明确拒绝为可索引文档
- 检索到的文本被放入显式的不可信文档边界中，以抵抗提示注入
