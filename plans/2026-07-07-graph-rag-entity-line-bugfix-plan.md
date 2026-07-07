# Graph RAG 实体行静默丢弃 Bug 修复计划

> 对应计划文档：`plans/2026-07-07-graph-rag-entity-line-bugfix-plan.md`
>
> 严重程度：LOW

---

## 一、问题分析

### 1.1 现象

在 `src/graph_rag.py:99` 的 LLM 响应解析逻辑中，如果 DeepSeek 返回的实体行以 `-`、`*` 或 `·` 开头（如 `- 人工智能`、`* 机器学习`），该行会被静默丢弃，不纳入实体列表。

### 1.2 根因

```python
# line 99 — BUG
elif line and not line.startswith(("-", "*", "·")):
    current.append(line)
```

条件 `not line.startswith(("-", "*", "·"))` 将所有以这三个字符开头的非空行过滤掉了。然而 LLM 在列举实体时，有时会自然使用列表符号前缀进行格式化。

### 1.3 非问题：分隔符匹配分析

用户提出的第二个怀疑点：

> 分隔符 `---段落` 与 LLM 的 `---段落1---` 格式不匹配（少了一端的 `---`）

经代码核实，**这不是 bug**：

| 位置 | 内容 |
|------|------|
| Prompt 格式（行 79） | `f"---段落{k + 1}---\n..."` → 输出 `---段落1---` |
| 解析条件（行 95） | `line.startswith("---段落")` |

`---段落1---` 以 `---段落` 开头，`startswith` 能正确匹配。此处的 `---段落1---` 两端的 `---` 是完整的，不存在不匹配。结论：无需修改。

### 1.4 影响范围

- 文件：`src/graph_rag.py`
- 函数：`extract_entities_llm_batch()`（第 52–114 行）
- 影响所有调用路径，包括批处理索引构建和单查询实体提取

### 1.5 触发条件

- LLM 响应中实体行以 `-`、`*` 或 `·` 开头
- 同一行中 `-`/`*`/`·` 后跟实体文本
- 空行不受影响（已被 `if line` 过滤）

---

## 二、修复方案

### 方案 A（推荐）— 剥离前缀后保留实体文本 ✅

在将行加入实体列表前，剥离掉开头的列表标记前缀：

```python
# Before (bug):
elif line and not line.startswith(("-", "*", "·")):
    current.append(line)

# After (fix):
elif line:
    current.append(line.lstrip("-*· "))
```

> **说明**：保留 `line` 真值检查，仅移除 `startswith` 过滤。`lstrip("-*· ")` 做字符集剥离——它会移除行首所有属于 `{'-', '*', '·', ' '}` 的字符，直到遇到不在集合中的字符为止。

| 输入 | `lstrip` 结果 | 说明 |
|------|--------------|------|
| `- 人工智能` | `人工智能` | ✅ 正常 |
| `* 机器学习` | `机器学习` | ✅ 正常 |
| `· 深度学习` | `深度学习` | ✅ 正常 |
| `-*- 混合标记` | `混合标记` | ⚠️ 连续标记都剥掉，合理 |
| `*args` | `args` | ⚠️ 实体名中的前导 `*` 会被剥掉。但原逻辑直接丢弃整行，`lstrip` 至少是改进 |
| `""` | (不执行) | ✅ 被 `elif line:` 拦截，不进入 |

### 方案 B — 完全移除过滤条件（不推荐）

```python
elif line:
    current.append(line)
```

**缺点**：会把 `- 实体` 中的 `- ` 前缀也作为实体文本的一部分，增加下游匹配时的噪声。

### 方案 C — 用正则匹配实体模式（不推荐）

```python
import re
ENTITY_PATTERN = re.compile(r"^[-*·]\s*(.+)$")
...
elif line:
    m = ENTITY_PATTERN.match(line)
    if m:
        current.append(m.group(1))
    elif not line.startswith(("-", "*", "·")):
        current.append(line)
```

**缺点**：过度设计，KISS 原则下不需要。

---

## 三、TDD 实施步骤（Red → Green → Refactor）

### Step R1: Red — 补充测试用例

在现有测试文件基础上，新增一个测试类，mock LLM 返回带列表标记的实体格式。

**测试函数**：`test_entity_parse_with_list_prefix`

| # | 用例 | Mock LLM 输出 | 预期 parsed 结果 |
|---|------|---------------|------------------|
| 1 | `-` 前缀实体 | `---段落1---\n- 人工智能\n- 机器学习` | `[["人工智能", "机器学习"]]` |
| 2 | `*` 前缀实体 | `---段落1---\n* 深度学习\n* 强化学习` | `[["深度学习", "强化学习"]]` |
| 3 | `·` 前缀实体 | `---段落1---\n· 自然语言处理\n· 计算机视觉` | `[["自然语言处理", "计算机视觉"]]` |
| 4 | 混合前缀 | `---段落1---\n- AI\n* ML\n· DL` | `[["AI", "ML", "DL"]]` |
| 5 | 无前缀实体（回归） | `---段落1---\n人工智能\n机器学习` | `[["人工智能", "机器学习"]]` |
| 6 | 空行不被注入 | `---段落1---\n人工智能\n\n机器学习` | `[["人工智能", "机器学习"]]` |
| 7 | 多段落含前缀 | `---段落1---\n- AI\n---段落2---\n* ML` | `[["AI"], ["ML"]]` |
| 8 | 无内容段落 | `---段落1---\n- AI\n---段落2---` | `[["AI"], []]` |

<details>
<summary>测试代码参考</summary>

```python
# tests/test_graph_rag_batch.py 中新增
# 
# 注意：
# 1. 使用 @patch("src.graph_rag._get_llm_client") — 这是模块中实际存在的函数，
#    extract_entities_llm_batch 内部调用它获取 client 实例。不可用 @patch("src.graph_rag.client")，
#    因为 client 是该函数内的局部变量，模块级不存在该名字。
# 2. 调用 _entity_cache.clear() 确保缓存隔离，避免前序缓存的实体导致 mock 未被
#    消费（假通过）。

@pytest.mark.parametrize(
    "mock_response,expected",
    [
        # 用例 1: 单段落，- 前缀
        pytest.param(
            "---段落1---\n- 人工智能\n- 机器学习",
            [["人工智能", "机器学习"]],
            id="hyphen_prefix"
        ),
        # 用例 2: 单段落，* 前缀
        pytest.param(
            "---段落1---\n* 深度学习\n* 强化学习",
            [["深度学习", "强化学习"]],
            id="asterisk_prefix"
        ),
        # 用例 3: 单段落，· 前缀
        pytest.param(
            "---段落1---\n· 自然语言处理\n· 计算机视觉",
            [["自然语言处理", "计算机视觉"]],
            id="dot_prefix"
        ),
        # 用例 4: 混合前缀
        pytest.param(
            "---段落1---\n- AI\n* ML\n· DL",
            [["AI", "ML", "DL"]],
            id="mixed_prefix"
        ),
        # 用例 5: 无前缀实体（回归）
        pytest.param(
            "---段落1---\n人工智能\n机器学习",
            [["人工智能", "机器学习"]],
            id="no_prefix_regression"
        ),
        # 用例 6: 空行不被注入
        pytest.param(
            "---段落1---\n人工智能\n\n机器学习",
            [["人工智能", "机器学习"]],
            id="empty_line_not_injected"
        ),
        # 用例 7: 多段落含前缀
        pytest.param(
            "---段落1---\n- AI\n---段落2---\n* ML",
            [["AI"], ["ML"]],
            id="multi_paragraph_with_prefix"
        ),
        # 用例 8: 无内容段落
        pytest.param(
            "---段落1---\n- AI\n---段落2---",
            [["AI"], []],
            id="empty_paragraph"
        ),
    ],
)
class TestEntityParseWithListPrefix:
    """验证带列表前缀的实体行能被正确解析（ListPrefix Bug 修复）"""

    def setup_method(self):
        """每测试前清空缓存，避免假通过"""
        _entity_cache.clear()

    @patch("src.graph_rag._get_llm_client")
    def test_entity_parse_with_list_prefix(
        self, mock_get_client, mock_response, expected
    ):
        # Arrange: mock LLM 返回带列表前缀的实体
        mock_client_obj = MagicMock()
        mock_resp = MagicMock()
        mock_resp.choices = [MagicMock(message=MagicMock(content=mock_response))]
        mock_client_obj.chat.completions.create.return_value = mock_resp
        mock_get_client.return_value = mock_client_obj

        # Act
        result = extract_entities_llm_batch(["虚构文本段落内容"])

        # Assert
        assert result == expected
```
</details>

### Step G1: Green — 实施修复

修改 `src/graph_rag.py:99`：

```python
# Before (bug):
elif line and not line.startswith(("-", "*", "·")):
    current.append(line)

# After (fix):
elif line:
    current.append(line.lstrip("-*· "))
```

### Step V1: 验证

```bash
cd D:\GitHub\mneme
python -m pytest tests/test_graph_rag_batch.py -x -v 2>&1
```

预期：所有测试（旧 + 新增 8 条）全部通过，0 failures。

### Step R2: Refactor（可选）

审视修复后代码是否可简化：

```python
for line in content.split("\n"):
    line = line.strip()
    if line.startswith("---段落"):
        if current:
            parsed.append(current)
            current = []
    elif line:
        current.append(line.lstrip("-*· "))
```

如果逻辑足够简洁，保持不动。

---

## 四、验证清单

| 检查项 | 预期 |
|--------|------|
| `-` 前缀实体被正确解析 | `"实体名"` 加入列表 |
| `*` 前缀实体被正确解析 | `"实体名"` 加入列表 |
| `·` 前缀实体被正确解析 | `"实体名"` 加入列表 |
| 无前缀实体不变（回归） | 同修复前行为 |
| 空行不注入实体列表 | 不在 `current` 中出现 `""` |
| 纯空格行不注入实体列表 | `strip()` 后为空，`elif line:` 拦截 |
| 多段落分隔正常 | 每个段落实体归入各自列表 |
| 现有全部测试通过 | `0 failures` |

---

## 五、更新 CHANGELOG

修复完成后在 CHANGELOG 中添加条目：

```
### Fixed
- 修复 Graph RAG 实体解析中 LLM 返回的 `-`/`*`/`·` 前缀实体行被静默丢弃的问题（#issue-number）
```

---

## 六、备注

- Bug 严重程度为 **LOW**，因为触发条件是 LLM 偶尔使用列表格式，不是每次必现
- 该 bug 是在 Issue #7 DRY 重构中引入的（`6f72c0c`），重构前的 `entity_extractor.py` 中没有这一条过滤
