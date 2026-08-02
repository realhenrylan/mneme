"""文档解析器：统一输出 Document 对象。

每个 loader（PDF/DOCX/text）负责：
1. 读取源文件
2. 提取结构化段落（Section）
3. 输出统一的 Document 对象

分块（Chunking）由 src/chunking.py 负责，不在 loader 中执行。
"""

from src.loaders.base import BaseLoader, LoaderRegistry
from src.loaders.pdf_loader import PdfLoader
from src.loaders.docx_loader import DocxLoader
from src.loaders.text_loader import TextLoader

__all__ = [
    "BaseLoader", "LoaderRegistry",
    "PdfLoader", "DocxLoader", "TextLoader",
]
