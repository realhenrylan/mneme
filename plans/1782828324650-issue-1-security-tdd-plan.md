# TDD 实施计划：安全修复 Issue #1

**Issue**: https://github.com/HongyiLanDP/rag-sys/issues/1#issue-4799722593
**严重程度**: CRITICAL
**目标文件**: `tui/screens/chat.py`
**相关文件**: `requirements.txt`, `.gitignore`
**测试文件**: `tests/test_env_security.py`（新建）

---

## 任务总览

| 任务 | 优先级 | 预计工时 | 验收标准 |
|------|--------|---------|---------|
 | T1：测试先行 — 编写失败测试（RED） | P0 | 30min | 测试覆盖两条缺陷，部分初始通过（回归保护） |
| T2：绿码 — 用 `python-dotenv` 替换自定义解析器 | P0 | 45min | 全部测试通过，功能等价 |
| T3：掩码显示 API Key | P1 | 20min | 测试覆盖，UI 只显示 `sk-...xxxx` |
| T4：添加 `.env.example` 模板 | P1 | 10min | 文件存在且不含真实 Key |
| T5：集成验证 & 清理 | P0 | 20min | 语法检查 + 手动路径验证通过 |

---

## TDD 循环 1：替换 `_read_env` / `_write_env`（P0）

### RED 阶段：编写失败测试

**文件**: `tests/test_env_security.py`

```python
"""安全修复 Issue #1 — TDD 测试套件（#1b：.env 解析器脆弱性）"""

import os
import tempfile
import pytest
from pathlib import Path
from dotenv import set_key, get_key, unset_key

# 被测模块将在 TDD 绿码阶段实现
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
```

 **验收标准（RED 阶段）**：
 ```bash
 cd /Users/deepprinciple/Desktop/henry/rag-sys
 python -m pytest tests/test_env_security.py -v
 # 预期：test_read_value_with_quotes、test_read_with_trailing_comment FAIL
 #       其余 PASS（旧实现与 python-dotenv 行为重合，充当回归保护）
 ```

---

### GREEN 阶段：最小实现

**修改文件**: `tui/screens/chat.py`

**变更点**（仅在 import 区和函数体，不修改调用逻辑）：

```python
# ===== 在文件头 import 区（第 1-14 行后）添加 =====
from dotenv import get_key, set_key, unset_key  # Issue #1b 修复

# ===== 替换 _read_env（第 349-358 行）=====
def _read_env(key: str) -> str:
    """Read a single value from .env file using python-dotenv."""
    return get_key(".env", key) or ""

# ===== 替换 _write_env（第 361-378 行）=====
def _write_env(key: str, value: str) -> None:
    """Update or append a key=value in .env file using python-dotenv."""
    set_key(".env", key, value)  # quote_mode 默认 "always"
```

**关键说明**：
- `set_key` 的 `quote_mode` 默认即为 `"always"`（已验证 `inspect.signature`）
- `get_key` 自动处理引号包裹、行尾注释、空值、含 `=` 的 value
- 无需修改第 404/405 行（`_read_env` 调用点）
- 无需修改第 441/445/450/457/468/479/489/509 行（`_write_env` 调用点）

**验证（GREEN 阶段）**：
```bash
python -m pytest tests/test_env_security.py -v
# 预期：全部 PASS
```

---

### REFACTOR 阶段：代码审查

- 确认 `import os` 保留（`_configure_settings` 和 `_switch_model` 中 `os.environ` 仍在使用）
- 确认 `load_dotenv` 的 import 在 `chat.py` 中**不需要新增**（`src/rag.py` 已加载）
- 检查 Pylint/Ruff 无新警告

---

## TDD 循环 2：API Key 掩码显示（P1）

### RED 阶段：编写测试

**添加到 `tests/test_env_security.py`**：

```python
class TestApiKeyMasking:
    """测试 #1a 修复：API Key 在 TUI 中不应明文显示"""

    def test_mask_api_key_standard_format(self):
        """标准格式 sk-xxx 应掩码为 sk-...xxxx（最后4位可见）"""
        api_key = "sk-1234567890abcdef"
        masked = _mask_api_key(api_key)
        assert masked == "sk-...cdef"
        assert "1234567890ab" not in masked

    def test_mask_api_key_short_key(self):
        """短 Key（<=8位）全部掩码"""
        api_key = "sk-1234"
        masked = _mask_api_key(api_key)
        assert masked == "sk-...****"

    def test_mask_api_key_empty(self):
        """空 Key 返回占位符"""
        assert _mask_api_key("") == "<not set>"

    def test_mask_api_key_none(self):
        """None 返回占位符"""
        assert _mask_api_key(None) == "<not set>"

    def test_mask_preserves_prefix(self):
        """保留前缀（如 sk-）"""
        api_key = "sk-proj-abcdef123456"
        masked = _mask_api_key(api_key)
        assert masked.startswith("sk-")
```

**验收标准（RED）**：
```bash
python -m pytest tests/test_env_security.py::TestApiKeyMasking -v
# 预期：FAIL — _mask_api_key 尚未定义
```

---

### GREEN 阶段：最小实现

**修改文件**: `tui/screens/chat.py`

**方案 A：新增 `_mask_api_key` 工具函数**

 ```python
 def _mask_api_key(key: str | None) -> str:
     """掩码显示 API Key，仅保留 'sk-' 前缀和最后 4 位。"""
     if not key:
         return "<not set>"
     if len(key) <= 8:
         return "sk-...****"
     return f"{key[:3]}...{key[-4:]}"   # key[:3] = "sk-"
 ```

**方案 B：直接修改 `_trunc` 调用处（第 404-405 行）**

```python
# 改为（第 404-405 行）
api_key = _mask_api_key(_read_env("API_KEY"))
base_url = _mask_api_key(_read_env("BASE_URL")) if _read_env("BASE_URL") else "<not set>"
```

**推荐方案 A**（关注点分离，`_mask_api_key` 可独立测试）。

**验证（GREEN）**：
```bash
python -m pytest tests/test_env_security.py::TestApiKeyMasking -v
# 预期：全部 PASS
```

---

### REFACTOR 阶段：UI 调用点微调

- 确认 `_trunc` 在掩码后不再截断（掩码后长度固定，无需 `_trunc`）
- 确保 `_switch_model`（第 501 行）不需要类似掩码（模型名非敏感信息）

---

## TDD 循环 3：`.env.example` 模板（P1）

### RED 阶段：验收测试

```bash
# 验证文件不存在
test -f .env.example && echo "FAIL" || echo "PASS"
# 预期：PASS（文件尚不存在）
```

---

### GREEN 阶段：创建模板

**新建文件**: `.env.example`

```ini
# RAG System Environment Configuration
# 复制此文件为 .env 并填入真实值
# ⚠️ 切勿将 .env 提交到版本控制

# OpenAI 兼容 API
API_KEY=sk-your-api-key-here
BASE_URL=https://api.openai.com/v1

# LLM 模型（可选，默认 deepseek-chat）
# LLM_MODEL=deepseek-chat

# 温度参数（可选，默认 0.1）
# LLM_TEMPERATURE=0.1

# Top-K 范围（可选，默认 3-20）
# LLM_TOP_K_MIN=3
# LLM_TOP_K_MAX=20

# Graph RAG Alpha（可选，默认 0.7）
# ALPHA=0.7
```

**验证（GREEN）**：
```bash
test -f .env.example && echo "PASS" || echo "FAIL"
# 预期：PASS
```

---

### REFACTOR 阶段：文档对齐

- 在 `README.md` 中补充 `.env.example` 的使用说明（如需要）

---

## TDD 循环 4：集成验证（P0）

### RED 阶段：功能验证

```bash
# 1. 语法检查
python -m py_compile tui/screens/chat.py  # 预期：无错误

# 2. pytest 全量运行
python -m pytest tests/ -v  # 预期：安全相关测试通过，其余测试不变

# 3. TUI 启动（手动）
python -m tui  # 预期：能进入设置界面，API Key 掩码显示

# 4. .env 写入验证
echo "TEST_KEY=test_value" > /tmp/test_env_check
# 通过 _write_env 写入后验证 python-dotenv 可读回
```

---

### GREEN 阶段：修复集成问题

- 若 `src/rag.py` 的 `load_dotenv()` 在 TUI 启动后未刷新，确认 `_write_env` 后是否需要手动 reload（见"延迟发现"说明）
- 确保 `requirements.txt` 的 `python-dotenv>=1.0.0` 版本满足 `set_key`/`get_key` API

---

### REFACTOR 阶段：最终清理

- 删除测试用的 `_MOCK_ENV` 硬编码（如需要）
- 确保 `pytest` 不因临时 `.env` 文件干扰（`temp_env` fixture 已隔离）

---

## 延迟发现说明（#1a 补充）

### 问题：TUI 修改 Key 后 `src/` 层不刷新

**现状**：
```python
# src/rag.py 第 35 行（模块加载时执行一次）
load_dotenv()  # 只读一次 .env，后续不自动 reload

# tui/screens/chat.py 第 441 行（用户修改 Key）
_write_env("API_KEY", val)
os.environ["API_KEY"] = val  # 同步到环境变量，src/ 层通过 os.getenv 可读到
```

**分析**：`_write_env` 写文件 + `os.environ["API_KEY"] = val` 双写策略确保 `src/` 层能读到新值。若删除 `os.environ` 赋值而只写文件，`src/` 层的 `os.getenv("API_KEY")` 仍返回旧值（因为 `load_dotenv()` 不重载）。

**决策**：**保留 `os.environ` 赋值**，这是当前架构下的功能必需，非缺陷。

**未来重构方向**（超出本次范围）：
- 将 `api_key` 作为参数传递，而非依赖环境变量
- 或在 `src/` 层每次调用前执行 `load_dotenv(override=True)`

---

## 验收检查清单

### #1a（API Key 泄露防护）

- [ ] TUI 设置界面中 API Key 仅显示 `sk-...cdef`（最后4位）
- [ ] 完整 Key 不打印到终端/日志
- [ ] `.env` 文件权限建议 `600`（可选自动化检查）

### #1b（.env 解析器修复）

- [ ] `_read_env` 支持 value 含 `=`、`#`、引号、空值
- [ ] `_write_env` 写入后可被 `_read_env` 完整读回
- [ ] `_write_env` 更新已有 Key 时不动其他行
- [ ] 所有 10 处调用点（404/405/441/445/450/457/468/479/489/509）功能不变

### 附加防护

- [ ] `.env.example` 存在且无真实 Key
- [ ] `python -m pytest tests/test_env_security.py -v` 全部通过
- [ ] 语法检查通过
- [ ] 无 Ruff/Pylint 新警告

---

## 执行顺序（严格 TDD）

```
T1 RED   → 写测试 → 验证全部失败
T1 GREEN → 改 _read_env/_write_env → 测试通过
T1 REFACTOR → 代码审查

T2 RED   → 加 _mask_api_key 测试 → 验证失败
T2 GREEN → 实现 _mask_api_key → 测试通过
T2 REFACTOR → UI 调用点调整

T3 GREEN → 创建 .env.example → 验收通过
T3 REFACTOR → README 补充

T4 RED   → 全量 pytest → 发现集成问题
T4 GREEN → 修复集成问题
T4 REFACTOR → 最终清理
```

---

## 文件变更汇总

 | 文件 | 变更类型 | 说明 |
 |------|---------|------|
 | `tests/test_env_security.py` | **新建** | 18+ 个测试用例（#1b 解析 + #1a 掩码） |
 | `tui/screens/chat.py` | **修改** | import 新增 `dotenv`；替换 `_read_env`/`_write_env`；新增 `_mask_api_key` |
 | `.env.example` | **新建** | 模板文件，不含真实 Key |
 | `README.md` | **可选修改** | 补充环境配置说明 |

 ---

 ## 审阅后修正记录（2025-07-03）

 | # | 修正位置 | 原内容 | 修正后 | 优先级 |
 |---|---------|--------|--------|--------|
 | 1 | `tests/test_env_security.py:132-138` | `lines = temp_env.read_text().splitlines(); assert "KEY=new" in lines` | 改用 `_read_env("KEY") == "new"` 验证 | 🔴 阻塞 |
 | 2 | `tests/test_env_security.py:140-146` | `content = temp_env.read_text(); assert "NEW_KEY=new_value" in content` | 改用 `_read_env` 验证 | 🔴 阻塞 |
 | 3 | `tests/test_env_security.py:148-153` | `assert temp_env.read_text().splitlines() == ["A=1", "B=2", "C=3"]` | 改用 `_read_env` 逐项验证 | 🔴 阻塞 |
 | 4 | `tui/screens/chat.py:267` | `return f"{key[:4]}...{key[-4:]}"` | `return f"{key[:3]}...{key[-4:]}"`（key[:3]="sk-"） | 🔴 阻塞 |
 | 5 | `tests/test_env_security.py:92-97` | 与 test_read_simple_key_value 完全重复的测试 | 改为真正的**大小写敏感**测试：`assert _read_env("api_key") == ""` | 🟡 可选 |
 | 6 | `tests/test_env_security.py:159-161` | RED 阶段预期"全部 FAIL" | 改为"部分 FAIL，其余 PASS（回归保护）" | 🟡 文档 |

 **修正原因**：
 - 修正项 1-3：`set_key` 默认 `quote_mode="always"` 会为 value 加双引号，`KEY="new"` 与断言 `KEY=new` 不匹配
 - 修正项 4：`key[:4]` 取 `"sk-1"` 而非期望的 `"sk-"`，导致掩码结果为 `"sk-1...cdef"` ❌
 - 修正项 5：删除冗余，保留真正的大小写敏感行为验证
 - 修正项 6：旧实现的简单 key=value 解析与 python-dotenv 行为重合，RED 阶段不会全部失败

---

 *计划创建时间：2025-07-03*
 *计划执行者：Kilo*
 *TDD 基准：测试先行，最小实现，逐步重构*
