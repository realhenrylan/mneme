"""
环境配置检测模块
================
提供首次启动引导触发条件检测，无重依赖，可被测试直接导入。
"""

import os


def need_onboarding(env_file: str = ".env") -> bool:
    """
    检测是否需要启动引导向导。

    条件：统一配置层注入后的 API_KEY 或 BASE_URL 为空。

    真实进程环境变量优先，因此即使 CWD 下没有 `.env`，完整的进程凭据
    也不会触发引导。`env_file` 仅为既有调用方保留，不再参与加载或判定。

    Args:
        env_file: .env 文件路径，默认为当前目录下的 ".env"

    Returns:
        bool: True 表示需要引导

    Note:
        `.env` 由 `src.config` 在模块导入期统一加载；此函数不再自行加载。
        此函数无重依赖，可被单元测试直接导入。
    """
    # 通过统一层刷新当前 CWD `.env`；不自行解析或覆盖显式进程环境。
    from src.config import reset_settings
    reset_settings()

    api_key = os.environ.get("API_KEY", "").strip()
    base_url = os.environ.get("BASE_URL", "").strip()

    return not api_key or not base_url