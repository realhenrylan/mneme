"""
环境配置检测模块
================
提供首次启动引导触发条件检测，无重依赖，可被测试直接导入。
"""

import os


def need_onboarding(env_file: str = ".env") -> bool:
    """
    检测是否需要启动引导向导。

    条件：
      - .env 文件不存在，或
      - API_KEY 为空，或
      - BASE_URL 为空

    Args:
        env_file: .env 文件路径，默认为当前目录下的 ".env"

    Returns:
        bool: True 表示需要引导

    Note:
        使用 load_dotenv + os.getenv 避免 get_key 的 stderr 噪音。
        此函数无重依赖，可被单元测试直接导入。
    """
    from dotenv import load_dotenv

    if not os.path.isfile(env_file):
        return True

    # 加载 .env 到环境变量（不输出 stderr 噪音）
    load_dotenv(env_file)

    api_key = os.environ.get("API_KEY", "").strip()
    base_url = os.environ.get("BASE_URL", "").strip()

    return not api_key or not base_url