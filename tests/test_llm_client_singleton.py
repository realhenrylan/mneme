"""
测试 _get_llm_client 单例缓存行为。

TDD: Red → Green → Refactor

设计说明：
- 测试按角色分为两类：
  1. Red/Green 区分测试 — `test_returns_same_instance_on_multiple_calls`
     Red 阶段 FAIL（非单例），Green 阶段 PASS（单例）
  2. 行为不变性守卫 — `test_uses_environment_variables`
     两个阶段均 PASS，确保重构后函数仍正确读取环境变量

删除说明（第二轮回审阅结论）：
- `test_creates_new_instance_after_cache_cleared`: Red/Green 两阶段均 PASS，
  无法区分行为。且直接操作 `_llm_client = None` 测试的是内部实现而非公共契约。
- `test_get_llm_client_called_once_per_extract`: 验证的是调用次数而非单例行为，
  Red 阶段也 PASS（当前代码本来就在循环外只调用一次）。

Mock 策略注解：
- 不 mock OpenAI 类——测试目标是函数是否返回同一对象，而非构造行为
- Red 阶段模块尚无 _llm_client 变量，setup_method 的赋值相当于预声明，
  不会引发 AttributeError（Python 动态属性赋值不会检查变量是否存在）
"""
import sys
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import src.graph_rag as graph_rag
from openai import OpenAI


class TestGetLLMClientSingleton:
    """测试 _get_llm_client 单例行为"""

    def setup_method(self):
        """清空缓存并恢复 OpenAI 类，确保测试隔离

        注：其他测试可能 mock 了 OpenAI 类，导致 _llm_client
        缓存了 MagicMock 对象。此处恢复真实的 OpenAI 类，
        并清空单例缓存，确保每个测试独立运行。
        """
        graph_rag.OpenAI = OpenAI
        graph_rag._llm_client = None

    def test_returns_same_instance_on_multiple_calls(self):
        """多次调用返回同一实例

        TDD 角色：Red/Green 区分测试
        - Red:   FAIL — 非单例，每次返回新实例，client1 is not client2
        - Green: PASS — 单例，返回同一实例，client1 is client2
        """
        with patch.dict("os.environ", {"API_KEY": "test-key", "BASE_URL": "https://test.com"}):
            client1 = graph_rag._get_llm_client()
            client2 = graph_rag._get_llm_client()

            assert client1 is not None
            assert client1 is client2

    def test_uses_environment_variables(self):
        """验证首次调用时读取环境变量

        TDD 角色：行为不变性守卫
        - Red:   PASS — 非单例也读环境变量
        - Green: PASS — 单例也读环境变量（首次调用时）
        - Refactor 价值：防止单例缓存了旧的环境变量值
        """
        with patch.dict("os.environ", {"API_KEY": "my-key", "BASE_URL": "https://my-url.com"}):
            with patch("src.graph_rag.OpenAI") as mock_openai_class:
                # 恢复 graph_rag 中的 OpenAI 为 mock（测试隔离）
                graph_rag.OpenAI = mock_openai_class
                graph_rag._llm_client = None

                client = graph_rag._get_llm_client()

                # 验证 OpenAI 构造函数被调用时传入了正确的环境变量
                mock_openai_class.assert_called_once_with(
                    api_key="my-key",
                    base_url="https://my-url.com",
                )
                # 返回的是 mock 实例
                assert client is mock_openai_class.return_value
