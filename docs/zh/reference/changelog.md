# 更新日志

完整更新日志请查看 GitHub：[CHANGELOG.md](https://github.com/realhenrylan/mneme/blob/main/CHANGELOG.md)

## 亮点

### 未发布

- **Embedding 模型自动下载**：本地缓存不可用时回退到 ModelScope 下载 `all-MiniLM-L6-v2`（国内网络友好）
- **CLI 循环重构**：将 `rag.py` 和 `graph_rag.py` 的共享交互会话逻辑提取到 `src/cli_loop.py`
- **导入清理**：消除 `sys.path` hack 和循环导入；添加 `pyproject.toml` 支持可编辑安装
- **LLM 客户端单例**：模块级惰性初始化，减少 `OpenAI` 客户端创建开销
- **Logo 刷新**：从原始字形重建的透明 SVG 字标

### 1.1.0（2026-07-04）

- **引导向导**：首次启动设置向导，用于 API key、Provider、Base URL 和模型选择
- **Provider 与模型联动**：DeepSeek、OpenAI 和自定义 Provider 预设及可用模型列表

### 1.0.3（2026-07-04）

- 修复错误场景错误地同时显示 Sources 和错误消息

### 1.0.2（2026-07-04）

- 修复 Temperature、Alpha、Top-K Min/Max 设置重启后丢失

### 1.0.1（2026-07-03）

- 修复 Graph RAG 批处理中线程不安全的 `_entity_cache` 写入和错误的逐 chunk API 调用

### 1.0.0（2026-07-03）

- 首次发布，包含 TUI、混合检索、Graph RAG、查询拆解和完整测试套件

---

完整的版本历史（包含所有变更、修复和重构详情），请访问 [GitHub 仓库](https://github.com/realhenrylan/mneme/blob/main/CHANGELOG.md)。
