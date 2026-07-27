# 支持的文件类型

Mneme 可以索引和检索以下文件类型：

| 类型 | 扩展名 |
|------|-----------|
| PDF | `.pdf` |
| Word | `.docx` |
| 文本和 Markdown | `.txt`、`.md`、`.markdown`、`.log` |
| 网页和数据 | `.html`、`.htm`、`.json`、`.csv`、`.xml`、`.yaml`、`.yml` |
| 配置文件 | `.toml`、`.cfg`、`.ini`、`.conf` |
| 源代码 | `.py`、`.js`、`.ts`、`.css`、`.sql`、`.sh`、`.bat` |

## PDF 处理

Mneme 使用 **PyMuPDF**（`fitz`）作为主要 PDF 解析器，**pdfplumber** 作为回退。这种双策略确保跨不同 PDF 生成方法的稳健文本提取。

- 保留词间距以防止拼接问题（如 `UniversityofPennsylvania`）
- 每个 PDF 的前 5 行用作"anchor chunk"以提升检索相关性
- 通过 `MNEME_MAX_PDF_PAGES` 强制执行最大页数

## 安全说明

以下文件被**明确拒绝**索引：
- `.env` 文件（防止 API Key 暴露）
- 包含 `..` 的路径（目录遍历保护）

## 文档限制

| 限制 | 默认值 | 控制变量 |
|-------|---------|------------------|
| 最大文件大小 | 50 MiB | `MNEME_MAX_DOCUMENT_BYTES` |
| 最大 PDF 页数 | 2000 | `MNEME_MAX_PDF_PAGES` |
| 允许的根目录 | 可选 | `MNEME_DOCUMENT_ROOT` |

超过这些限制的文件在索引时会被跳过，并显示清晰的日志消息。
