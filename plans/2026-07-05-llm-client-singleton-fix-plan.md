# `_get_llm_client` 单例化 — TDD 修复计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 `_get_llm_client()` 改为模块级缓存/单例模式，避免每次函数调用都新建 `OpenAI` 客户端实例。

**Architecture:** 最小改动方案：在模块级增加 `_llm_client: OpenAI | None = None` 变量，`_get_llm_client` 内部做惰性初始化。对调用方完全透明。

**Tech Stack:** Python, pytest, unittest.mock

---

## 问题分析

### 当前代码（`src/graph_rag.py:31-35`）

```python
def _get_llm_client() -> OpenAI:
    return OpenAI(
        api_key = os.getenv("API_KEY"),
        base_url = os.getenv("BASE_URL"),
    )
```

每次调用都创建一个全新的 `OpenAI` 客户端实例。虽然 TCP 连接可能被 `urllib3` 连接池复用，但：
- 每次新建对象带来不必要的构造开销
- `OpenAI` 构造函数内部会初始化相关资源
- `extract_entities_llm_batch` 被多次调用（如 `build_from_chunks` 中）时，每次都会重建客户端

### 调用链路

```
extract_entities_from_query(query)
  └─ extract_entities_llm_batch([query])   ← 调用 1 次
       └─ _get_llm_client()                  ← 创建 1 次

KnowledgeGraph.build_from_chunks(chunks)
  └─ extract_entities_llm_batch(chunks)      ← 调用 1 次
       └─ _get_llm_client()                  ← 创建 1 次
```

> **注**：当前 `_get_llm_client()` 在 `extract_entities_llm_batch` 中被调用**一次**（在 for 循环之前，而非每个 batch），因此实际上不会被「每个 batch」重复调用。但作为模块级函数，它的语义应当是「获取共享客户端实例」而非「每次新建」。如果未来 `extract_entities_llm_batch` 被高频调用，对象堆积会更明显。

### 对标 `rag.py`

`rag.py:648` 和 `rag.py:868` 也采用同样的「每次创建」模式。但本次修复范围限定在 `graph_rag.py`，`rag.py` 的同类问题可另立 Issue 跟踪。

---

## 方案

### 模块级缓存（惰性单例）

```python
_llm_client: OpenAI | None = None

def _get_llm_client() -> OpenAI:
    global _llm_client
    if _llm_client is None:
        _llm_client = OpenAI(
            api_key = os.getenv("API_KEY"),
            base_url = os.getenv("BASE_URL"),
        )
    return _llm_client
```

### 设计决策

| 方案 | 评价 | 选择理由 |
|---|---|---|
| `@functools.lru_cache(maxsize=1)` | 简洁但引入新 import，且缓存不可见（隐式） | — |
| `@functools.cache` | 同上，Python 3.9+ | — |
| **模块级变量 + 惰性初始化** | 显式、零依赖、Python 2/3 兼容 | ✅ 选择 |
| 类级单例 | 过度设计 | — |

### 不变部分

- 函数签名不变（`() -> OpenAI`）
- 已有 mock 测试全部保持通过（它们 mock 的是 `src.graph_rag._get_llm_client` 整个函数，缓存在 mock 层之下不可见）
- 行为语义不变：首次调用时读取环境变量，后续返回同一实例
- 环境变量在进程启动后不变化的前提成立（非热更新场景）

### 风险分析

| 风险 | 影响 | 缓解措施 |
|---|---|---|
| 进程内修改环境变量后客户端配置过时 | 极低（Python 不常动态改 env） | 是预期行为，非 bug |
| 线程安全 | 两线程同时首次调用可能各自创建 | `OpenAI` 构造本身不是临界区；若需线程安全可加 `threading.Lock`，当前不必须 |
| 客户端 SSL/TLS 会话过期 | 由 `httpx` 内部连接池管理 | 无需处理 |

---

## 影响范围

| 位置 | 变更 |
|---|---|
| `src/graph_rag.py:31-35` | ✅ `_get_llm_client` 函数体重写，增加模块级 `_llm_client` 变量 |
| 已有调用方（`extract_entities_llm_batch`） | ❌ 无变更（调用方式不变） |
| 已有测试（`tests/test_graph_rag_batch.py`） | ❌ 无变更（mock 透明） |
| `rag.py` | ❌ 无变更（本次不涉及） |

---

## 实施任务

### Task 1: 写失败测试（Red 阶段）

**Files:**
- Create: `tests/test_llm_client_singleton.py`
- Modify: (none yet)

> **说明**：测试验证 `_get_llm_client` 多次调用返回同一实例。由于该函数是模块级私有函数，测试通过 `src.graph_rag` 模块的命名空间访问。
>
> **注意**：首次调用后缓存了 `OpenAI` 实例，后续测试如果改了环境变量，需通过 `reimport` 或 `clear cache` 来隔离。因此提供 `setup_method` 清空缓存。

- [ ] **Step 1: 创建测试文件**

```python
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


class TestGetLLMClientSingleton:
    """测试 _get_llm_client 单例行为"""

    def setup_method(self):
        """清空缓存确保隔离

        注：Red 阶段模块尚无 _llm_client 变量，
        此赋值相当于预声明，Python 动态属性赋值不会报错。
        Green 阶段后，此操作用于清空单例缓存。
        """
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
        """验证客户端使用环境变量中的 API_KEY 和 BASE_URL

        TDD 角色：行为不变性守卫
        - Red:   PASS — 非单例也读环境变量
        - Green: PASS — 单例也读环境变量（首次调用时）
        - Refactor 价值：防止单例缓存了旧的环境变量值
        """
        with patch.dict("os.environ", {"API_KEY": "my-key", "BASE_URL": "https://my-url.com"}):
            client = graph_rag._get_llm_client()

            # OpenAI 构造函数会将 api_key, base_url 存为实例属性
            assert client.api_key == "my-key"
            # base_url 是 httpx.URL 对象，需用 str() 显式比较
            assert str(client.base_url) == "https://my-url.com"
```

- [ ] **Step 2: 运行测试，确认失败**

```bash
cd /d/GitHub/mneme && python -m pytest tests/test_llm_client_singleton.py -v
```

预期：`test_returns_same_instance_on_multiple_calls` FAIL — 当前 `_get_llm_client` 每次都 `return OpenAI(...)`，`client1 is client2` 不成立。
`test_uses_environment_variables` PASS — 非单例也读环境变量，行为不变性守卫在 Red 阶段通过是预期的。

---

### Task 2: 修改 `_get_llm_client` 为单例（Green 阶段）

**Files:**
- Modify: `src/graph_rag.py`

- [ ] **Step 1: 增加模块级缓存变量，重写函数**

修改 `src/graph_rag.py` 中第 29-35 行：

```python
# 旧（第 28-35 行）
from openai import OpenAI
_entity_cache: dict[str, list[str]] = {}

def _get_llm_client() -> OpenAI:
    return OpenAI(
        api_key = os.getenv("API_KEY"),
        base_url = os.getenv("BASE_URL"),
    )

# 新
from openai import OpenAI
_entity_cache: dict[str, list[str]] = {}
_llm_client: OpenAI | None = None

def _get_llm_client() -> OpenAI:
    global _llm_client
    if _llm_client is None:
        _llm_client = OpenAI(
            api_key = os.getenv("API_KEY"),
            base_url = os.getenv("BASE_URL"),
        )
    return _llm_client
```

> **关于类型标注**：`OpenAI | None` 是 Python 3.10+ 的联合类型语法。`graph_rag.py` 未强制 Python 版本下限，但已使用 `from __future__ import annotations`（第 1 行），因此即使 Python 3.9 也能正常运行（PEP 604 的 `X | Y` 语法在 `from __future__ import annotations` 下被延迟为字符串，不会触发运行时错误）。

- [ ] **Step 2: 跑测试确认 Green**

```bash
cd /d/GitHub/mneme && python -m pytest tests/test_llm_client_singleton.py -v
```

预期：PASS

- [ ] **Step 3: 确认已有测试未被破坏**

```bash
cd /d/GitHub/mneme && python -m pytest tests/test_graph_rag_batch.py -v --tb=short
```

预期：PASS（已有测试 mock 的是 `src.graph_rag._get_llm_client` 整个函数，缓存逻辑在 mock 层之下，不影响原有行为）

- [ ] **Step 4: 提交**

```bash
cd /d/GitHub/mneme
git add tests/test_llm_client_singleton.py src/graph_rag.py
git commit -m "perf: singleton _get_llm_client to avoid repeated OpenAI client creation"
```

---

### Task 3: 回归测试

- [ ] **Step 1: 跑全部测试**

```bash
cd /d/GitHub/mneme && python -m pytest tests/ -v --tb=short 2>&1
```

预期：所有测试通过（0 failures）

- [ ] **Step 2: 确认关键测试未被破坏**

重点关注：
- `tests/test_graph_rag_batch.py` — graph_rag 批量处理核心测试
- `tests/test_graph_rag_enrich.py` — enrich_context 集成测试
- `tests/test_retrieval_fix.py` — 检索修复测试

---

### Task 4: 更新 CHANGELOG

**Files:**
- Modify: `CHANGELOG.md`

- [ ] **Step 1: 追加变更记录**

在 `CHANGELOG.md` 中找到 `## [Unreleased]` 段（若无则新建），在其 `### Fixed` 或 `### Changed` 小节下追加：

```markdown
## [Unreleased]

### Changed
- `_get_llm_client()` 改为模块级单例模式，复用 OpenAI 客户端实例，减少不必要的对象创建
```

- [ ] **Step 2: 提交**

```bash
cd /d/GitHub/mneme
git add CHANGELOG.md
git commit -m "chore: update CHANGELOG for _get_llm_client singleton fix"
```

---

## 验证清单

- [ ] `test_returns_same_instance_on_multiple_calls` — PASS（Green 阶段）
- [ ] `test_uses_environment_variables` — PASS
- [ ] 全部已有测试 — PASS（0 failures）
  - `tests/test_graph_rag_batch.py` — 不变（mock `_get_llm_client` 整个函数，缓存透明）
  - `tests/test_graph_rag_enrich.py` — 不变
  - `tests/test_retrieval_fix.py` — 不变
- [ ] Lint 无错误（`python -m py_compile src/graph_rag.py` — exit 0）
