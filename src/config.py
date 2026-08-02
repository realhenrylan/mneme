"""统一配置管理 — Settings 类 + MNEME_DATA_DIR 环境变量。

设计原则：
1. 所有配置集中管理，CLI/TUI/rag.py 使用同一份默认值
2. MNEME_DATA_DIR 环境变量控制数据目录，默认 ~/.mneme
3. 包目录只读也可运行（数据不写入 src/ 下）
4. 离线模式不能隐式触发远程 ModelScope 下载
5. 所有配置项有文档
"""

import os
from dataclasses import dataclass, field
from pathlib import Path


def _resolve_data_dir() -> Path:
    """解析数据目录路径。

    优先级：
    1. MNEME_DATA_DIR 环境变量
    2. ~/.mneme（用户主目录下）

    不再使用 src/chroma_db 作为默认路径，避免包目录写入问题。
    """
    env_dir = os.getenv("MNEME_DATA_DIR", "").strip()
    if env_dir:
        return Path(env_dir)
    return Path.home() / ".mneme"


def _resolve_document_root() -> Path:
    """解析文档根目录。"""
    env_root = os.getenv("MNEME_DOCUMENT_ROOT", "").strip()
    if env_root:
        return Path(env_root)
    return Path.cwd() / "documents"


@dataclass
class Settings:
    """Mneme 统一配置。

    所有配置项均可通过环境变量覆盖，环境变量名与字段名对应。
    布尔值环境变量：设为 "1"/"true"/"yes" 为 True，其余为 False。
    """

    # ── 数据目录 ──
    data_dir: Path = field(default_factory=_resolve_data_dir)
    document_root: Path = field(default_factory=_resolve_document_root)

    # ── Chroma DB ──
    chroma_db_path: Path = field(default=None)  # 延迟计算

    # ── Embedding 模型 ──
    embedding_model_name: str = field(default_factory=lambda: (
        os.getenv("EMBEDDING_MODEL_PATH", "").strip()
        or os.getenv("EMBEDDING_MODEL_NAME", "").strip()
        or "all-MiniLM-L6-v2"
    ))

    # ── LLM 配置 ──
    llm_model: str = field(default_factory=lambda: os.getenv("LLM_MODEL", "deepseek-chat"))
    llm_temperature: float = field(default_factory=lambda: float(os.getenv("LLM_TEMPERATURE", "0.1")))
    llm_top_k_min: int = field(default_factory=lambda: int(os.getenv("LLM_TOP_K_MIN", "3")))
    llm_top_k_max: int = field(default_factory=lambda: int(os.getenv("LLM_TOP_K_MAX", "20")))

    # ── 检索配置 ──
    alpha: float = field(default_factory=lambda: float(os.getenv("ALPHA", "0.7")))
    refusal_threshold: float = field(default_factory=lambda: float(
        os.getenv("RAG_REFUSAL_THRESHOLD", "0.03")
    ))
    default_chunk_size: int = 500
    default_chunk_overlap: int = 50

    # ── Reranker ──
    reranker_mode: str = field(default_factory=lambda: os.getenv("RAG_RERANKER", "none").lower())
    reranker_model_name: str = field(default_factory=lambda: os.getenv(
        "RAG_RERANKER_MODEL", "cross-encoder/ms-marco-MiniLM-L-6-v2",
    ))

    # ── 安全与限制 ──
    allow_insecure_http: bool = field(default_factory=lambda: os.getenv(
        "MNEME_ALLOW_INSECURE_HTTP", "",
    ).strip() in ("1", "true", "yes"))
    max_document_bytes: int = field(default_factory=lambda: int(os.getenv(
        "MNEME_MAX_DOCUMENT_BYTES", "52428800",
    )))
    max_pdf_pages: int = field(default_factory=lambda: int(os.getenv("MNEME_MAX_PDF_PAGES", "2000")))
    max_remote_context_chars: int = field(default_factory=lambda: int(os.getenv(
        "MNEME_MAX_REMOTE_CONTEXT_CHARS", "60000",
    )))

    # ── 离线模式 ──
    offline_mode: bool = field(default_factory=lambda: os.getenv(
        "MNEME_OFFLINE", "",
    ).strip() in ("1", "true", "yes"))

    def __post_init__(self):
        """计算派生路径。"""
        if self.chroma_db_path is None:
            self.chroma_db_path = self.data_dir / "chroma_db"

    def ensure_dirs(self):
        """确保数据目录存在。"""
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.chroma_db_path.mkdir(parents=True, exist_ok=True)

    def to_dict(self) -> dict:
        """导出为字典（用于 status 展示和调试）。"""
        return {
            "data_dir": str(self.data_dir),
            "chroma_db_path": str(self.chroma_db_path),
            "document_root": str(self.document_root),
            "embedding_model_name": self.embedding_model_name,
            "llm_model": self.llm_model,
            "llm_temperature": self.llm_temperature,
            "llm_top_k_range": (self.llm_top_k_min, self.llm_top_k_max),
            "alpha": self.alpha,
            "refusal_threshold": self.refusal_threshold,
            "reranker_mode": self.reranker_mode,
            "allow_insecure_http": self.allow_insecure_http,
            "max_document_bytes": self.max_document_bytes,
            "max_pdf_pages": self.max_pdf_pages,
            "offline_mode": self.offline_mode,
        }


# ── 全局单例 ──
_global_settings: Settings | None = None


def get_settings() -> Settings:
    """获取全局 Settings 单例。"""
    global _global_settings
    if _global_settings is None:
        _global_settings = Settings()
    return _global_settings


def reset_settings():
    """重置 Settings 单例（主要用于测试）。"""
    global _global_settings
    _global_settings = None
