# 配置参考

Mneme 通过 `.env` 文件中的环境变量进行配置。

## 核心 LLM 设置

| 变量 | 必需 | 默认值 | 说明 |
|----------|----------|---------|-------------|
| `API_KEY` | 是 | — | OpenAI 兼容 API Key |
| `BASE_URL` | 是 | `https://api.openai.com/v1` | LLM 端点 URL |
| `LLM_MODEL` | 是 | `deepseek-chat` | 聊天补全模型 |
| `LLM_TEMPERATURE` | 否 | `0.2` | 采样温度（0.0–2.0） |

## 检索设置

| 变量 | 必需 | 默认值 | 说明 |
|----------|----------|---------|-------------|
| `LLM_TOP_K_MIN` | 否 | `12` | 最小检索 chunk 数 |
| `LLM_TOP_K_MAX` | 否 | `70` | 最大检索 chunk 数 |
| `ALPHA` | 否 | `0.7` | Graph RAG 融合权重（0.0–1.0） |

## Embedding 模型

| 变量 | 必需 | 默认值 | 说明 |
|----------|----------|---------|-------------|
| `EMBEDDING_MODEL_PATH` | 否 | — | 预下载模型的本地路径 |
| `EMBEDDING_MODEL_NAME` | 否 | `all-MiniLM-L6-v2` | ModelScope 回退的模型 ID |

如果设置了 `EMBEDDING_MODEL_PATH`，Mneme 从该路径加载。否则尝试本地缓存，然后回退到 ModelScope 自动下载。

## 文件监听

| 变量 | 必需 | 默认值 | 说明 |
|----------|----------|---------|-------------|
| `RAG_WATCH_DIR` | 否 | — | 监听文件变更的目录 |

## 安全限制

| 变量 | 必需 | 默认值 | 说明 |
|----------|----------|---------|-------------|
| `MNEME_DOCUMENT_ROOT` | 否 | — | 限制索引到此目录树 |
| `MNEME_MAX_DOCUMENT_BYTES` | 否 | `52428800` | 最大文件大小（50 MiB） |
| `MNEME_MAX_PDF_PAGES` | 否 | `2000` | 每个 PDF 最大页数 |
| `MNEME_MAX_REMOTE_CONTEXT_CHARS` | 否 | `60000` | 发送到 LLM 端点的最大上下文 |
| `MNEME_ALLOW_INSECURE_HTTP` | 否 | 未设置 | 设为 `1` 允许非本地 HTTP |

## 示例 `.env`

```dotenv
# 必需
API_KEY=sk-your-api-key-here
BASE_URL=https://api.deepseek.com/v1
LLM_MODEL=deepseek-chat

# 可选
LLM_TEMPERATURE=0.2
LLM_TOP_K_MIN=12
LLM_TOP_K_MAX=70
ALPHA=0.7

# Embedding
EMBEDDING_MODEL_NAME=all-MiniLM-L6-v2

# 监听
RAG_WATCH_DIR=/path/to/docs

# 安全
MNEME_MAX_DOCUMENT_BYTES=52428800
MNEME_MAX_PDF_PAGES=2000
```

## Provider 速查

| Provider | `BASE_URL` | `LLM_MODEL` |
|----------|-----------|-------------|
| DeepSeek | `https://api.deepseek.com/v1` | `deepseek-chat`、`deepseek-reasoner` |
| OpenAI | `https://api.openai.com/v1` | `gpt-4o`、`gpt-4o-mini`、`gpt-3.5-turbo` |
| 自定义 | 你的 URL | 你的模型 |
