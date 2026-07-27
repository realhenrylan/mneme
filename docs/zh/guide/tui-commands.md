# TUI 命令

Mneme 基于 Rich 的终端 UI 支持斜杠命令和键盘快捷键。

## 斜杠命令

| 命令 | 说明 |
|---------|-------------|
| `/help` | 显示所有命令 |
| `/files` | 添加、删除、列出、监听或停止监听文件 |
| `/mode` | 切换 Standard RAG / Graph RAG |
| `/alpha` | 设置 Graph RAG 融合权重 |
| `/settings` | 查看或更改 API 设置 |
| `/models` | 列出可用模型 |
| `/status` | 显示索引和服务状态 |
| `/clear` | 清除聊天历史 |
| `/quit` | 退出 |

## 文件管理示例

```text
/files watch /path/to/directory
/files list
/files stop
/files add /path/to/file.pdf
/files remove /path/to/file.pdf
```

## 键盘快捷键

| 快捷键 | 操作 |
|----------|--------|
| `Ctrl+P` | 打开命令面板 |
| `Ctrl+L` | 切换侧边栏 |
| `Ctrl+N` | 新建会话 |
| `Ctrl+K` | 清除聊天 |
| `Ctrl+C` | 退出 |

## 模式切换

使用 `/mode` 在 Standard RAG 和 Graph RAG 之间切换。从 Standard 切换到 Graph RAG 时，Mneme 会：

1. 显示确认提示
2. 从当前索引构建知识图谱（带进度条）
3. 切换检索模式

切换回 Standard RAG 时，模式立即更改，无需重建。

## 设置

使用 `/settings` 查看和修改：
- API Key（安全遮蔽显示）
- Base URL
- LLM 模型
- Temperature
- Top-K Min / Max
- Alpha（Graph RAG 权重）

所有更改持久化到 `.env` 并立即生效。
