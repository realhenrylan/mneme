"""Loader 基类与注册表。"""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path

from src.domain import Document


class BaseLoader(ABC):
    """文档解析器基类。

    所有 loader 必须实现 load() 方法，返回统一的 Document 对象。
    """

    # 子类覆盖：支持的文件扩展名列表
    SUPPORTED_EXTENSIONS: list[str] = []

    @abstractmethod
    def load(self, filepath: str) -> Document:
        """解析文件，返回 Document 对象。"""
        ...

    def supports(self, filepath: str) -> bool:
        """判断是否支持该文件类型。"""
        suffix = Path(filepath).suffix.lower()
        return suffix in self.SUPPORTED_EXTENSIONS


class LoaderRegistry:
    """Loader 注册表，按文件类型分发到对应 loader。"""

    def __init__(self) -> None:
        self._loaders: dict[str, BaseLoader] = {}

    def register(self, loader: BaseLoader) -> None:
        """注册 loader，按其支持的扩展名建立映射。"""
        for ext in loader.SUPPORTED_EXTENSIONS:
            self._loaders[ext] = loader

    def get_loader(self, filepath: str) -> BaseLoader | None:
        """根据文件扩展名获取对应 loader。"""
        suffix = Path(filepath).suffix.lower()
        return self._loaders.get(suffix)

    def load(self, filepath: str) -> Document:
        """解析文件，自动选择 loader。

        Raises:
            ValueError: 不支持的文件类型
        """
        loader = self.get_loader(filepath)
        if loader is None:
            suffix = Path(filepath).suffix.lower()
            raise ValueError(f"不支持的文件类型: {suffix} ({filepath})")
        return loader.load(filepath)
