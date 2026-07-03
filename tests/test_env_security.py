"""安全修复 Issue #1 — TDD 测试套件（#1b：.env 解析器脆弱性）"""

import os
import pytest

from tui.screens.chat import _read_env, _write_env


@pytest.fixture
def temp_env(tmp_path):
    """创建临时 .env 文件，测试后自动清理。"""
    env_file = tmp_path / ".env"
    env_file.write_text("")  # 初始为空
    # 切到临时目录
    original_dir = os.getcwd()
    os.chdir(tmp_path)
    yield env_file
    os.chdir(original_dir)


class TestReadEnv:
    """测试 _read_env 的 5 个解析缺陷修复"""

    def test_read_simple_key_value(self, temp_env):
        """基础功能：简单 KEY=VALUE"""
        temp_env.write_text("API_KEY=sk-123\n")
        assert _read_env("API_KEY") == "sk-123"

    def test_read_value_with_equals(self, temp_env):
        """缺陷1：Value 含 = 时完整读取"""
        temp_env.write_text("KEY=a=b=c\n")
        assert _read_env("KEY") == "a=b=c"

    def test_read_value_with_hash(self, temp_env):
        """缺陷2：Value 含 # 时读取完整值"""
        temp_env.write_text("KEY=value#with#hash\n")
        assert _read_env("KEY") == "value#with#hash"

    def test_read_value_with_quotes(self, temp_env):
        """缺陷3：Value 被引号包裹时去掉引号"""
        temp_env.write_text('KEY="quoted value"\n')
        assert _read_env("KEY") == "quoted value"

    def test_read_empty_value(self, temp_env):
        """缺陷4：空值返回空字符串（不报错）"""
        temp_env.write_text("EMPTY_KEY=\n")
        assert _read_env("EMPTY_KEY") == ""

    def test_read_missing_key(self, temp_env):
        """不存在的 Key 返回空字符串"""
        temp_env.write_text("OTHER=value\n")
        assert _read_env("NOT_EXIST") == ""

    def test_read_with_trailing_comment(self, temp_env):
        """缺陷5：行尾注释被忽略"""
        temp_env.write_text("KEY=value # this is a comment\n")
        assert _read_env("KEY") == "value"

    def test_read_case_insensitive(self, temp_env):
        """大小写敏感查找：python-dotenv 的 get_key 区分大小写"""
        temp_env.write_text("API_KEY=sk-123\n")
        # get_key 大小写敏感：小写 key 无法匹配大写的 API_KEY
        assert _read_env("api_key") == ""   # 期望：空字符串（未找到）


class TestWriteEnv:
    """测试 _write_env 的 5 个写入缺陷修复"""

    def test_write_simple(self, temp_env):
        """基础功能：写入简单值"""
        _write_env("KEY", "value")
        assert _read_env("KEY") == "value"

    def test_write_value_with_equals(self, temp_env):
        """缺陷1：Value 含 = 时正确写入并可完整读回"""
        _write_env("KEY", "a=b=c")
        assert _read_env("KEY") == "a=b=c"

    def test_write_value_with_hash(self, temp_env):
        """缺陷2：Value 含 # 时正确写入并可读回"""
        _write_env("KEY", "x#y")
        assert _read_env("KEY") == "x#y"

    def test_write_value_with_newline(self, temp_env):
        """缺陷3：Value 含换行时文件格式不损坏"""
        _write_env("KEY", "line1\nline2")
        # 读取时应能正确解析（python-dotenv 处理多行值）
        assert _read_env("KEY") == "line1\nline2"
        # 文件仍可被其他 Key 读取
        _write_env("OTHER", "val")
        assert _read_env("OTHER") == "val"

    def test_write_value_with_quotes(self, temp_env):
        """缺陷4：Value 含引号时正确转义"""
        _write_env("KEY", 'a"b')
        assert _read_env("KEY") == 'a"b'

    def test_update_existing_key(self, temp_env):
        """更新已存在的 Key（非追加）"""
        temp_env.write_text("KEY=old\nOTHER=keep\n")
        _write_env("KEY", "new")
        # 改用 _read_env 验证，不依赖底层文件格式（quote_mode="always" 会加引号）
        assert _read_env("KEY") == "new"
        assert _read_env("OTHER") == "keep"

    def test_append_new_key(self, temp_env):
        """追加新 Key 到文件末尾"""
        temp_env.write_text("EXISTING=value\n")
        _write_env("NEW_KEY", "new_value")
        # 改用 _read_env 验证，不依赖底层文件格式
        assert _read_env("EXISTING") == "value"
        assert _read_env("NEW_KEY") == "new_value"

    def test_preserves_existing_content(self, temp_env):
        """写入新 Key 不破坏已有内容"""
        original = "A=1\nB=2\n"
        temp_env.write_text(original)
        _write_env("C", "3")
        # 改用 _read_env 逐项验证，不依赖 splitlines() 精确匹配
        assert _read_env("A") == "1"
        assert _read_env("B") == "2"
        assert _read_env("C") == "3"


class TestApiKeyMasking:
    """测试 #1a 修复：API Key 在 TUI 中不应明文显示"""

    def test_mask_api_key_standard_format(self):
        """标准格式 sk-xxx 应掩码为 sk-...xxxx（最后4位可见）"""
        from tui.screens.chat import _mask_api_key
        api_key = "sk-1234567890abcdef"
        masked = _mask_api_key(api_key)
        assert masked == "sk-...cdef"
        assert "1234567890ab" not in masked

    def test_mask_api_key_short_key(self):
        """短 Key（<=8位）全部掩码"""
        from tui.screens.chat import _mask_api_key
        api_key = "sk-1234"
        masked = _mask_api_key(api_key)
        assert masked == "sk-...****"

    def test_mask_api_key_empty(self):
        """空 Key 返回占位符"""
        from tui.screens.chat import _mask_api_key
        assert _mask_api_key("") == "<not set>"

    def test_mask_api_key_none(self):
        """None 返回占位符"""
        from tui.screens.chat import _mask_api_key
        assert _mask_api_key(None) == "<not set>"

    def test_mask_preserves_prefix(self):
        """保留前缀（如 sk-）"""
        from tui.screens.chat import _mask_api_key
        api_key = "sk-proj-abcdef123456"
        masked = _mask_api_key(api_key)
        assert masked.startswith("sk-")
