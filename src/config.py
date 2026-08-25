"""统一配置管理 — Settings 类 + MNEME_DATA_DIR 环境变量。

设计原则：
1. Settings 是本阶段受管配置的唯一默认值来源；CLI/TUI/rag.py 共用同一契约
2. MNEME_DATA_DIR 环境变量控制数据目录，默认 ~/.mneme；路径支持 ~ 展开
   （Windows 下展开为 %USERPROFILE%），相对路径按进程启动目录解释并绝对化；
   数据目录在进程启动（模块导入）时解析
3. 包目录只读也可运行（数据不写入 src/ 下）
4. MNEME_OFFLINE=1 的精确承诺仅限：禁止隐式远程 ModelScope 下载
   （本地模型加载与 LLM API 调用不受影响）
5. 非法数值/非法范围在 Settings 构造时 fail-fast，错误信息包含配置名，
   发生在任何索引构建、模型加载、网络访问或目录写入之前
6. 所有配置项有文档（.env.example / README）
7. 唯一启动配置入口：`<启动目录>/.env`（CWD）在本模块导入时即加载，
   早于任何 Settings 构造（security/rag 的导入期 get_settings() 也能看到
   .env 值）；真实环境变量始终优先（.env 加载不覆盖既有变量）。
   `reset_settings()` 是 TUI/onboarding 的刷新入口：重新读取当前 CWD 的
   `.env` 并真实反映文件修改（含键删除），但绝不覆盖显式进程环境变量。
"""

import math
import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import dotenv_values

# ── 契约默认常量（受管配置的唯一默认值来源；rag.py/security.py 从这里派生）──
DEFAULT_EMBEDDING_MODEL = "all-MiniLM-L6-v2"
DEFAULT_LLM_MODEL = "deepseek-chat"
DEFAULT_LLM_TEMPERATURE = 0.1
DEFAULT_LLM_TOP_K_MIN = 3          # 用户 Top-K 区间下界（TUI/流式路径）
DEFAULT_LLM_TOP_K_MAX = 20         # 用户 Top-K 区间上界（TUI/流式路径）
DEFAULT_ALPHA = 0.7
DEFAULT_REFUSAL_THRESHOLD = 0.03
DEFAULT_RERANKER_MODE = "none"
DEFAULT_RERANKER_MODEL_NAME = "cross-encoder/ms-marco-MiniLM-L-6-v2"
DEFAULT_MAX_DOCUMENT_BYTES = 52428800
DEFAULT_MAX_PDF_PAGES = 2000
DEFAULT_MAX_REMOTE_CONTEXT_CHARS = 60000

# ── 内部检索宽度（与用户 Top-K 是不同概念；固定常量，不提供环境变量覆盖）──
# 同步路径（answer_query）：retrieve k=RETRIEVAL_CANDIDATE_K，
# dynamic_top_k 的默认边界为 RETRIEVAL_DYNAMIC_MIN_K/MAX_K。
RETRIEVAL_CANDIDATE_K = 70
RETRIEVAL_DYNAMIC_MIN_K = 12
RETRIEVAL_DYNAMIC_MAX_K = 70

# ── Graph 内部动态 Top-K 边界（Graph 增强检索的内部截断策略；固定常量，
#    无环境变量覆盖）──
# 与用户 Top-K 区间 LLM_TOP_K_MIN/MAX（3–20，TUI/流式路径，可配置）是
# 两个独立概念：Graph 内部策略恢复既有 3/50 默认，绝不绑定用户区间。
GRAPH_DYNAMIC_MIN_K = 3
GRAPH_DYNAMIC_MAX_K = 50

TRUE_VALUES = ("1", "true", "yes")
RERANKER_MODES = ("none", "cross-encoder")


def _cwd_dotenv_path() -> Path | None:
    """启动目录（CWD）下的 .env 路径；CWD 不可用时返回 None。"""
    try:
        return Path(os.getcwd()) / ".env"
    except OSError:
        return None


# 模块导入时刻（任何 .env 加载之前）的进程环境变量快照：这些键是“显式
# 进程环境变量”，任何 .env 加载/刷新都绝不覆盖它们。
_initial_env_keys: frozenset = frozenset(os.environ)

# 由本模块从 .env 注入过的键及其注入值（重置时用于识别“我们拥有”的键：
# 仅当当前环境值仍等于我们上次写入的值时，才随文件修改刷新/删除；被外部
# 改写（如 TUI 同步 os.environ、测试 monkeypatch）的键视为显式进程环境
# 变量，保持优先、绝不覆盖）。
_dotenv_values: dict = {}


def load_dotenv_at_startup() -> None:
    """唯一启动配置入口：加载/刷新 `<启动目录>/.env` 到进程环境。

    - 显式进程环境变量始终优先：`_initial_env_keys`（本模块导入前已存在
      的键）与运行期被外部改写的键都不会被 .env 覆盖；
    - 在模块导入时调用一次；`reset_settings()` 再调用一次（onboarding
      写入 .env / 测试切换 CWD 后重建 Settings）——刷新时真实反映 .env
      文件修改：值更新、新增键注入、已删除键从进程环境移除（仅限“仍持有
      我们上次注入值”的键，即未被外部改写的键）；
    - 不触网、不创建目录、找不到文件时视为空文件（我们注入过的键被清理，
      值回落到 Settings 默认）。
    """
    global _dotenv_values
    dotenv_path = _cwd_dotenv_path()
    values = dotenv_values(dotenv_path) if dotenv_path is not None else {}
    file_keys = {key for key in values if key not in _initial_env_keys}

    # 1. 清理：我们注入过、现文件已删除（或文件消失）、且未被外部改写的键
    for key in list(_dotenv_values):
        if key in _initial_env_keys or key not in file_keys:
            if os.environ.get(key) == _dotenv_values[key]:
                os.environ.pop(key, None)
            _dotenv_values.pop(key, None)

    # 2. 注入/刷新：文件键。当前环境值仍是我们上次注入的值（或尚不存在）
    #    时随文件更新；否则视为显式进程环境变量，保持优先。
    for key, value in values.items():
        if key in _initial_env_keys:
            continue
        current = os.environ.get(key)
        last = _dotenv_values.get(key)
        if current is None or (last is not None and current == last):
            os.environ[key] = value
            _dotenv_values[key] = value


# 唯一启动配置入口：任何 Settings 构造（含 security/rag 导入期 get_settings()）
# 都发生在本行之后，因此 .env 值必定先于 Settings 进入进程。
load_dotenv_at_startup()


def _env_str(name: str, default: str) -> str:
    raw = os.getenv(name, "").strip()
    return raw or default


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError as exc:
        raise ValueError(
            f"配置 {name}={raw!r} 不是合法数字，请在 .env 或环境中修正后重启",
        ) from exc


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise ValueError(
            f"配置 {name}={raw!r} 不是合法整数，请在 .env 或环境中修正后重启",
        ) from exc


def _env_bool(name: str) -> bool:
    return os.getenv(name, "").strip().lower() in TRUE_VALUES


def _to_abs_path(value: str) -> Path:
    """展开 ~ 并把相对路径按当前工作目录绝对化（不触网、不创建目录）。"""
    return Path(os.path.abspath(os.path.expanduser(value)))


def _resolve_data_dir() -> Path:
    """解析数据目录路径。

    优先级：
    1. MNEME_DATA_DIR 环境变量（支持 ~ 展开；相对路径按进程启动目录解释）
    2. ~/.mneme（用户主目录下）

    不再使用 src/chroma_db 作为默认路径，避免包目录写入问题。
    """
    env_dir = os.getenv("MNEME_DATA_DIR", "").strip()
    if env_dir:
        return _to_abs_path(env_dir)
    return Path.home() / ".mneme"


def _resolve_document_root() -> Path:
    """解析文档根目录（支持 ~ 展开；相对路径按进程启动目录解释）。"""
    env_root = os.getenv("MNEME_DOCUMENT_ROOT", "").strip()
    if env_root:
        return _to_abs_path(env_root)
    return Path.cwd() / "documents"


def _resolve_embedding_model() -> str:
    """解析 embedding 模型标识。

    优先级：EMBEDDING_MODEL_PATH（本地路径）> EMBEDDING_MODEL_NAME（模型 ID）。
    与其他受管路径一致，EMBEDDING_MODEL_PATH 在 Settings 构造时完成 `~`
    展开与相对路径绝对化（按进程启动目录），因此调用期 CWD 改变后实际
    loader 收到的参数不会漂移；EMBEDDING_MODEL_NAME 视为模型 ID，原样保留。
    """
    env_path = os.getenv("EMBEDDING_MODEL_PATH", "").strip()
    if env_path:
        return str(_to_abs_path(env_path))
    return _env_str("EMBEDDING_MODEL_NAME", DEFAULT_EMBEDDING_MODEL)


def _require_in_range(value: float, low: float, high: float, name: str) -> None:
    if not (low <= value <= high):
        raise ValueError(
            f"配置 {name}={value!r} 超出允许范围 [{low}, {high}]，"
            "请在 .env 或环境中修正后重启",
        )


# ── 共享校验器（Settings 与显式覆盖入口共用同一规则；fail-fast）──
# 显式覆盖（rag.answer_query / answer_query_stream / _plan_query_runtime /
# prepare_answer_evidence / generate_answer / answer_with_llm_history(_stream)
# / graph_rag 入口等）必须在进入规划器、检索器、LLM gateway 或任何写路径
# 之前通过与 Settings 构造完全一致的校验：温度必须是 [0.0, 2.0] 内的有限
# 数值（拒绝 NaN/inf）；用户 Top-K 必须是两个 >= 1 的整数且 min <= max。

def _is_llm_temperature_valid(value: float) -> bool:
    """温度共用规则：有限数值且 0.0 <= value <= 2.0（拒绝 NaN/inf）。"""
    return math.isfinite(value) and 0.0 <= value <= 2.0


def validate_llm_temperature(value) -> float:
    """校验显式 temperature 覆盖值（与 Settings 共用同一规则）。

    仅接受 [0.0, 2.0] 内的有限、非布尔数值；NaN/inf/非数字/布尔值
    （True/False）一律拒绝——布尔值是 int 子类，`float(True) == 1.0`
    曾让 `validate_llm_temperature(True)` 通过。合法字符串数值保留
    既有兼容行为（与 Settings `.env` 解析路径一致），规范化 float。
    错误信息包含配置名 LLM_TEMPERATURE。返回规范化 float。
    """
    if isinstance(value, bool):
        raise ValueError(
            f"配置 LLM_TEMPERATURE={value!r} 不是合法数字，"
            "必须是 [0.0, 2.0] 内的有限数值",
        )
    try:
        fv = float(value)
    except (TypeError, ValueError):
        raise ValueError(
            f"配置 LLM_TEMPERATURE={value!r} 不是合法数字，"
            "必须是 [0.0, 2.0] 内的有限数值",
        ) from None
    if not _is_llm_temperature_valid(fv):
        raise ValueError(
            f"配置 LLM_TEMPERATURE={fv!r} 超出允许范围 [0.0, 2.0]"
            "（必须是有限数值）",
        )
    return fv


def _is_user_top_k_valid(min_k, max_k) -> bool:
    """用户 Top-K 共用规则：两个整数、均 >= 1、min <= max。"""
    return (
        isinstance(min_k, int) and not isinstance(min_k, bool)
        and isinstance(max_k, int) and not isinstance(max_k, bool)
        and min_k >= 1 and max_k >= 1 and min_k <= max_k
    )


def validate_user_top_k_range(min_k, max_k) -> tuple[int, int]:
    """校验显式用户 Top-K 区间（与 Settings 共用同一规则）。

    两个整数、均 >= 1、且 min <= max；错误信息明确关联配置名
    LLM_TOP_K_MIN / LLM_TOP_K_MAX。返回 (min_k, max_k)。
    """
    for name, value in (("LLM_TOP_K_MIN", min_k), ("LLM_TOP_K_MAX", max_k)):
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError(
                f"配置 {name}={value!r} 不是整数，必须是 >= 1 的整数",
            )
        if value < 1:
            raise ValueError(
                f"配置 {name}={value!r} 必须 >= 1",
            )
    if min_k > max_k:
        raise ValueError(
            f"配置范围矛盾：LLM_TOP_K_MIN ({min_k}) > LLM_TOP_K_MAX ({max_k})",
        )
    return (min_k, max_k)


def validate_user_top_k_container(top_k_range) -> tuple[int, int]:
    """校验显式用户 Top-K 范围容器（与 Settings 共用同一规则）。

    仅接受恰好包含两个整数（且均非布尔）的序列（tuple/list）：
    长度必须为 2、1 <= min <= max。拒绝 `(3, 20, 999)`、`(3,)`、非序列
    （如 int/str）、布尔值容器、浮点元素——必须在调用方任何下标使用或
    `max(top_k_range)` 之前完成（否则 `(3,)` 会抛 IndexError、
    `(3,20,999)` 会静默忽略第三个元素）。错误信息明确关联配置名
    LLM_TOP_K_MIN / LLM_TOP_K_MAX。返回规范化 (min_k, max_k)。
    """
    if isinstance(top_k_range, bool) or not isinstance(
            top_k_range, (tuple, list)):
        raise ValueError(
            "配置 LLM_TOP_K_MIN/LLM_TOP_K_MAX 必须是恰好两个整数的序列"
            f"（1 <= MIN <= MAX），收到 {top_k_range!r}",
        )
    if len(top_k_range) != 2:
        raise ValueError(
            "配置 LLM_TOP_K_MIN/LLM_TOP_K_MAX 必须是恰好两个整数的序列"
            f"（1 <= MIN <= MAX），收到长度 {len(top_k_range)} 的 "
            f"{top_k_range!r}",
        )
    return validate_user_top_k_range(top_k_range[0], top_k_range[1])


def _is_alpha_valid(value: float) -> bool:
    """ALPHA 共用规则：有限数值且 0.0 <= value <= 1.0（拒绝 NaN/inf）。"""
    return math.isfinite(value) and 0.0 <= value <= 1.0


def validate_alpha(value) -> float:
    """校验显式 alpha 覆盖值（与 Settings 共用同一规则）。

    仅接受 [0.0, 1.0] 内的有限、非布尔数值；NaN/inf/非数字/布尔值
    一律拒绝（布尔值是 int 子类，`0.0 <= True <= 1.0` 曾让
    Settings/显式值把 True 当合法 alpha）。合法字符串数值保留既有
    兼容行为（与 Settings `.env` 解析路径一致），规范化 float。
    错误信息包含配置名 ALPHA。返回规范化 float。
    """
    if isinstance(value, bool):
        raise ValueError(
            f"配置 ALPHA={value!r} 不是合法数字，必须是 [0.0, 1.0] 内的"
            "有限数值",
        )
    try:
        fv = float(value)
    except (TypeError, ValueError):
        raise ValueError(
            f"配置 ALPHA={value!r} 不是合法数字，必须是 [0.0, 1.0] 内的"
            "有限数值",
        ) from None
    if not _is_alpha_valid(fv):
        raise ValueError(
            f"配置 ALPHA={fv!r} 超出允许范围 [0.0, 1.0]（必须是有限数值）",
        )
    return fv


@dataclass
class Settings:
    """Mneme 统一配置。

    所有配置项均可通过环境变量覆盖，环境变量名与字段名对应。
    覆盖优先级：真实环境变量 > .env（本模块在导入时从启动目录加载，
    reset_settings() 时重新读取并反映文件修改）> 契约默认值。
    布尔值环境变量：设为 "1"/"true"/"yes" 为 True，其余为 False。
    非法数值/非法范围在构造时抛 ValueError（信息含配置名），且构造过程
    不创建任何目录、不触网。
    """

    # ── 数据目录 ──
    data_dir: Path = field(default_factory=_resolve_data_dir)
    document_root: Path = field(default_factory=_resolve_document_root)
    # 是否显式设置了 MNEME_DOCUMENT_ROOT：未显式设置时安全层沿用历史
    # 行为（不施加根目录限制）；显式设置后 validate_document_path 使用
    # 本字段已解析（绝对化）的 document_root，不按调用期 CWD 重新解释。
    document_root_explicit: bool = field(
        default_factory=lambda: bool(os.getenv("MNEME_DOCUMENT_ROOT", "").strip())
    )

    # ── 派生路径（延迟计算）──
    chroma_db_path: Path = field(default=None)   # data_dir / "chroma_db"
    model_cache_dir: Path = field(default=None)  # data_dir / "models"

    # ── Embedding 模型 ──
    # EMBEDDING_MODEL_PATH（本地路径）在构造时完成 ~ 展开与绝对化；
    # EMBEDDING_MODEL_NAME 为模型 ID。两者都不随调用期 CWD 漂移。
    embedding_model_name: str = field(default_factory=_resolve_embedding_model)

    # ── LLM 配置 ──
    llm_model: str = field(default_factory=lambda: _env_str(
        "LLM_MODEL", DEFAULT_LLM_MODEL))
    llm_temperature: float = field(default_factory=lambda: _env_float(
        "LLM_TEMPERATURE", DEFAULT_LLM_TEMPERATURE))
    llm_top_k_min: int = field(default_factory=lambda: _env_int(
        "LLM_TOP_K_MIN", DEFAULT_LLM_TOP_K_MIN))
    llm_top_k_max: int = field(default_factory=lambda: _env_int(
        "LLM_TOP_K_MAX", DEFAULT_LLM_TOP_K_MAX))

    # ── 内部检索宽度（与用户 Top-K 不同概念；固定常量，无环境变量覆盖）──
    retrieval_candidate_k: int = RETRIEVAL_CANDIDATE_K
    retrieval_dynamic_min_k: int = RETRIEVAL_DYNAMIC_MIN_K
    retrieval_dynamic_max_k: int = RETRIEVAL_DYNAMIC_MAX_K

    # ── 检索配置 ──
    alpha: float = field(default_factory=lambda: _env_float("ALPHA", DEFAULT_ALPHA))
    refusal_threshold: float = field(default_factory=lambda: _env_float(
        "RAG_REFUSAL_THRESHOLD", DEFAULT_REFUSAL_THRESHOLD))
    default_chunk_size: int = 500
    default_chunk_overlap: int = 50

    # ── Reranker ──
    reranker_mode: str = field(default_factory=lambda: _env_str(
        "RAG_RERANKER", DEFAULT_RERANKER_MODE).lower())
    reranker_model_name: str = field(default_factory=lambda: _env_str(
        "RAG_RERANKER_MODEL", DEFAULT_RERANKER_MODEL_NAME))

    # ── 安全与限制 ──
    allow_insecure_http: bool = field(default_factory=lambda: _env_bool(
        "MNEME_ALLOW_INSECURE_HTTP"))
    max_document_bytes: int = field(default_factory=lambda: _env_int(
        "MNEME_MAX_DOCUMENT_BYTES", DEFAULT_MAX_DOCUMENT_BYTES))
    max_pdf_pages: int = field(default_factory=lambda: _env_int(
        "MNEME_MAX_PDF_PAGES", DEFAULT_MAX_PDF_PAGES))
    max_remote_context_chars: int = field(default_factory=lambda: _env_int(
        "MNEME_MAX_REMOTE_CONTEXT_CHARS", DEFAULT_MAX_REMOTE_CONTEXT_CHARS))

    # ── 离线模式（精确承诺：仅禁止隐式远程 ModelScope 下载）──
    offline_mode: bool = field(default_factory=lambda: _env_bool("MNEME_OFFLINE"))

    def __post_init__(self):
        """计算派生路径并校验数值/范围（fail-fast，零写入）。"""
        if self.chroma_db_path is None:
            self.chroma_db_path = self.data_dir / "chroma_db"
        if self.model_cache_dir is None:
            self.model_cache_dir = self.data_dir / "models"

        # ── 范围校验（先于任何索引/模型加载/网络/目录写入）──
        # 与显式覆盖入口共用同一校验器（validate_llm_temperature /
        # validate_user_top_k_range / validate_alpha），唯一差异是
        # .env 修正提示。
        try:
            self.llm_temperature = validate_llm_temperature(
                self.llm_temperature)
            self.llm_top_k_min, self.llm_top_k_max = validate_user_top_k_range(
                self.llm_top_k_min, self.llm_top_k_max)
            self.alpha = validate_alpha(self.alpha)
        except ValueError as exc:
            raise ValueError(
                f"{exc}，请在 .env 或环境中修正后重启",
            ) from exc
        _require_in_range(self.refusal_threshold, 0.0, float("inf"),
                          "RAG_REFUSAL_THRESHOLD")
        if self.reranker_mode not in RERANKER_MODES:
            raise ValueError(
                f"配置 RAG_RERANKER={self.reranker_mode!r} 无效，必须是 "
                f"{list(RERANKER_MODES)} 之一，请在 .env 或环境中修正后重启",
            )
        for name, value in (
            ("MNEME_MAX_DOCUMENT_BYTES", self.max_document_bytes),
            ("MNEME_MAX_PDF_PAGES", self.max_pdf_pages),
            ("MNEME_MAX_REMOTE_CONTEXT_CHARS", self.max_remote_context_chars),
        ):
            if value < 1:
                raise ValueError(
                    f"配置 {name}={value!r} 必须为正整数，"
                    "请在 .env 或环境中修正后重启",
                )
        # 内部检索宽度常量完整性（防御性；无环境变量覆盖）
        if self.retrieval_dynamic_min_k < 1 or \
                self.retrieval_dynamic_max_k < 1 or \
                self.retrieval_dynamic_min_k > self.retrieval_dynamic_max_k:
            raise ValueError(
                "内部检索宽度常量非法：retrieval_dynamic_min_k "
                f"({self.retrieval_dynamic_min_k}) / retrieval_dynamic_max_k "
                f"({self.retrieval_dynamic_max_k})",
            )

    def ensure_dirs(self):
        """确保数据目录存在（显式调用才写入）。"""
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.chroma_db_path.mkdir(parents=True, exist_ok=True)

    def to_dict(self) -> dict:
        """导出为字典（用于 status 展示和调试）。"""
        return {
            "data_dir": str(self.data_dir),
            "chroma_db_path": str(self.chroma_db_path),
            "model_cache_dir": str(self.model_cache_dir),
            "document_root": str(self.document_root),
            "document_root_explicit": self.document_root_explicit,
            "embedding_model_name": self.embedding_model_name,
            "llm_model": self.llm_model,
            "llm_temperature": self.llm_temperature,
            "llm_top_k_range": (self.llm_top_k_min, self.llm_top_k_max),
            "retrieval_candidate_k": self.retrieval_candidate_k,
            "retrieval_dynamic_k_range": (
                self.retrieval_dynamic_min_k, self.retrieval_dynamic_max_k,
            ),
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

# ── Settings 刷新回调注册表 ──
# rag.py 等模块在导入时注册回调；reset_settings() 重建单例后逐个调用，
# 使模块级派生的配置常量（DEFAULT_LLM_MODEL 等公开兼容名）同步刷新，
# 不再停留在进程启动时的旧默认值。
_settings_refresh_callbacks: list = []


def register_settings_refresh_callback(callback) -> None:
    """注册 Settings 重置时的刷新回调（幂等；rag.py 刷新模块级配置常量）。"""
    _settings_refresh_callbacks.append(callback)


def get_settings() -> Settings:
    """获取全局 Settings 单例。"""
    global _global_settings
    if _global_settings is None:
        _global_settings = Settings()
    return _global_settings


def get_effective_env_value(key: str) -> str:
    """读取统一配置边界内的有效字符串值（进程环境优先）。"""
    value = os.environ.get(key)
    if value is not None:
        return value.strip()
    dotenv_path = _cwd_dotenv_path()
    if dotenv_path is None:
        return ""
    return str(dotenv_values(dotenv_path).get(key) or "").strip()


def persist_env_settings(values: dict[str, str]) -> set[str]:
    """持久化 TUI 受管值并返回当前显式进程环境键。

    写入只触碰启动目录 `.env`；显式进程环境仍由 gateway/运行时拥有，
    因此不会被同步或覆盖。调用方应在写入后调用 `reset_settings()` 刷新。
    """
    explicit_keys = {
        key for key, value in values.items()
        if key in os.environ and (
            key in _initial_env_keys
            or (key not in _dotenv_values and key in os.environ)
            or (key in _dotenv_values and os.environ[key] != _dotenv_values[key])
        )
    }
    from dotenv import set_key

    dotenv_path = _cwd_dotenv_path() or Path('.env')
    for key, value in values.items():
        set_key(str(dotenv_path), key, value)
        if key not in explicit_keys and os.environ.get(key) == _dotenv_values.get(key):
            os.environ.pop(key, None)
            _dotenv_values.pop(key, None)
    return explicit_keys


def reset_settings():
    """重置 Settings 单例（测试；产品用于 onboarding 保存后重载）。

    重置前重新加载启动目录 `.env`（load_dotenv_at_startup）：
    - onboarding/TUI 刚写入的 .env 修改（新值、新键、删除的键）真实反映
      进新 Settings；
    - 显式进程环境变量（本模块导入前已存在的键）始终优先，绝不被覆盖。
    随后调用已注册刷新回调（rag.py/security.py 的模块级配置常量随之刷新）。
    """
    global _global_settings
    load_dotenv_at_startup()
    _global_settings = None
    for callback in _settings_refresh_callbacks:
        callback()
