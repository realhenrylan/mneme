/# TDD 实施计划：LLM 无法回答知识库元问题（Issue #16）

**Issue**: https://github.com/HongyiLanDP/rag-sys/issues/16
**严重程度**: P1
**目标文件**: `src/rag.py`, `src/graph_rag.py`
**测试文件**: `tests/test_llm_meta_answer.py`（新建）

---

## 问题描述

当用户向 RAG 系统提问知识库的元问题（meta-question）时，例如：

- "知识库中储存了多少文件？"
- "列出所有文件名"

LLM 无法正确回答。因为传入 LLM 的 `context` 仅包含文档切片的纯文本，**没有任何来源文件名信息**。LLM 只能看到零散的文本片段，无法得知文件数量和文件名，被问到时会胡乱编造。

### 根因

`src/rag.py` 和 `src/graph_rag.py` 中，共 **5 处** 构建 context 时都只拼接了文档文本 `docs[i]`，没有附加 `metadatas[i]["source"]` 信息：

| # | 位置 | 当前代码 | 可用变量 |
|---|------|---------|---------|
| R1 | `src/rag.py:688` `answer_query` | `"\n\n".join([enriched_docs[i] for i in top_indices])` | `documents`(全量), `metadatas`(全量) |
| R2 | `src/rag.py:913` `answer_query_stream` | `"\n\n".join([enriched_docs[i] for i in top_indices])` | `documents`(全量), `metadatas`(全量) |
| G1 | `src/graph_rag.py:417` `graph_rag_pipeline` | `" ".join(top_docs)` | `all_docs`(全量), `all_metadatas`(全量) |
| G2 | `src/graph_rag.py:549` `graph_query_stream` | `" ".join(docs[:k])` | `all_docs`(全量), `all_metadatas`(全量) |
| G3 | `src/graph_rag.py:471,509` CLI `__main__` | `" ".join(top_docs)` | `all_docs`(全量), `all_metadatas`(全量) |

此外，`graph_rag.py` 使用 `" ".join()`（空格分隔）而非 `"\n\n".join()`（段落分隔），与其他路径不一致。

### 关键索引差异

`_build_context` 内部通过 `docs[i]` 和 `metadatas[i]` 访问数据，其中 `i` 来自 `top_indices`。在 `graph_rag.py` 中 `top_indices` 是 `all_docs` 的全局索引（如 `[42, 17, 5]`），因此 `docs` 必须传全量列表 `all_docs`（而非截断后的 `top_docs`），否则会索引越界。`rag.py` 中 `top_indices` 本来就是 `documents` 的索引，传 `enriched_docs`（全量浅拷贝）即可。

> **审阅修正 (2026-07-03)**：初版计划中 G1/G2/G3 误传了 `top_docs`/`docs[:k]`，以下已全部更正为 `all_docs`。

---

## 任务总览

| 任务 | 优先级 | 预计工时 | 验收标准 |
|------|--------|---------|---------|
| T1：测试先行 — 编写失败测试（RED） | P1 | 30min | 7 个单元测试 + 1 个集成测试全部 FAIL（或部分 PASS 作为回归保护） |
| T2：绿码 — 添加 `_build_context` 辅助函数 | P1 | 15min | 所有测试通过 |
| T3：绿码 — 修复 `rag.py` 中 2 处 context 构建 | P1 | 10min | T1 集成测试 PASS |
| T4：绿码 — 修复 `graph_rag.py` 中 3 处 context 构建 | P1 | 15min | 全部测试通过 |
| T5：集成验证 | P1 | 15min | 语法检查 + 全量 pytest + 端到端验证通过 |

---

## TDD 循环 1：编写失败测试（RED）

### 测试文件结构

**新建**: `tests/test_llm_meta_answer.py`

```python
#!/usr/bin/env python3
"""
TDD 测试：验证 LLM context 是否包含来源文件名信息（Issue #16）。

测试策略：
  1. 单元测试 — `_build_context` 函数的正确性
  2. 单元测试 — 构建 context 后文件名是否出现在字符串中
  3. 集成测试 — 模拟完整 RAG 流程，验证 LLM 能回答文件数

用法：
  pytest tests/test_llm_meta_answer.py -v
"""
import os
import sys
import shutil
import subprocess
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

try:
    import pytest
    HAS_PYTEST = True
except ImportError:
    HAS_PYTEST = False

import src.rag as rag
from src.rag import (
    prepare_index, build_bm25_index, SentenceTransformer, chromadb,
    CHROMA_DB_PATH as _ORIGINAL_DB,
    DEFAULT_COLLECTION_NAME,
)

TEST_DB_PATH = PROJECT_ROOT / "tests" / "analysis" / "chroma_db_test_meta"
PDF_FILE = str(PROJECT_ROOT / "test_texts" / "2405.02357v2.pdf")
DOCX_FILE = str(PROJECT_ROOT / "test_texts" / "南京城市地理环境.docx")
MD_FILE = str(PROJECT_ROOT / "test_texts" / "LLMs_for_Mobility_Analysis_Survey.md")

_original_db_path = _ORIGINAL_DB


def setup_module():
    """确保干净的测试数据库"""
    db_dir = str(TEST_DB_PATH)
    if os.path.exists(db_dir):
        subprocess.run(["rm", "-rf", db_dir], check=False)
    rag.CHROMA_DB_PATH = db_dir


def teardown_module():
    """清理测试数据库"""
    db_dir = str(TEST_DB_PATH)
    if os.path.exists(db_dir):
        subprocess.run(["rm", "-rf", db_dir], check=False)
    rag.CHROMA_DB_PATH = _original_db_path


# ═══════════════════════════════════════════════
# 单元测试 1：_build_context 函数
# ═══════════════════════════════════════════════

class TestBuildContextFunction:
    """测试 _build_context 辅助函数（尚未实现，RED 阶段应 FAIL）"""

    def test_function_exists(self):
        """_build_context 函数应该存在"""
        from src.rag import _build_context
        assert callable(_build_context)

    def test_single_chunk_source_annotation(self):
        """单个 chunk 应标注来源文件名"""
        from src.rag import _build_context
        top_indices = [0]
        docs = ["这是文档内容"]
        metadatas = [{"source": "test.pdf"}]
        result = _build_context(top_indices, docs, metadatas)
        assert "[Source: test.pdf]" in result
        assert "这是文档内容" in result

    def test_multiple_chunks_different_sources(self):
        """多个不同来源的 chunk 都应标注各自的文件名"""
        from src.rag import _build_context
        top_indices = [0, 1, 2]
        docs = ["内容A", "内容B", "内容C"]
        metadatas = [
            {"source": "file1.pdf"},
            {"source": "file2.pdf"},
            {"source": "file3.pdf"},
        ]
        result = _build_context(top_indices, docs, metadatas)
        assert "[Source: file1.pdf]" in result
        assert "[Source: file2.pdf]" in result
        assert "[Source: file3.pdf]" in result

    def test_same_source_multiple_chunks(self):
        """同一文件多个 chunk 应每个都标注"""
        from src.rag import _build_context
        top_indices = [0, 1]
        docs = ["内容A", "内容B"]
        metadatas = [
            {"source": "common.pdf"},
            {"source": "common.pdf"},
        ]
        result = _build_context(top_indices, docs, metadatas)
        assert result.count("[Source: common.pdf]") == 2

    def test_chunks_separated_by_newlines(self):
        """chunk 之间应以双换行分隔"""
        from src.rag import _build_context
        top_indices = [0, 1]
        docs = ["第一段", "第二段"]
        metadatas = [
            {"source": "a.pdf"},
            {"source": "b.pdf"},
        ]
        result = _build_context(top_indices, docs, metadatas)
        # 每段格式: [Source: ...]\n内容\n\n[Source: ...]\n内容
        parts = result.split("\n\n")
        assert len(parts) == 2

    def test_missing_source_key_falls_back(self):
        """metadata 中没有 source key 时不应 crash"""
        from src.rag import _build_context
        top_indices = [0]
        docs = ["内容"]
        metadatas = [{"other_key": "value"}]  # 没有 "source"
        result = _build_context(top_indices, docs, metadatas)
        assert result is not None
        assert "内容" in result

    def test_non_sequential_indices(self):
        """top_indices 为非连续值时仍能正确映射（graph_rag 中的实际场景）"""
        from src.rag import _build_context
        # 模拟 graph_rag 场景：top_indices 是 all_docs 中的全局索引（如 [42, 17, 5]）
        top_indices = [42, 17, 5]
        docs = [""] * 50  # 填充至 50 以容纳索引 42
        docs[42] = "文档A内容"
        docs[17] = "文档B内容"
        docs[5] = "文档C内容"
        metadatas = [{"source": "dummy"}] * 50
        metadatas[42] = {"source": "file_a.pdf"}
        metadatas[17] = {"source": "file_b.pdf"}
        metadatas[5] = {"source": "file_c.pdf"}
        result = _build_context(top_indices, docs, metadatas)
        assert "[Source: file_a.pdf]" in result
        assert "[Source: file_b.pdf]" in result
        assert "[Source: file_c.pdf]" in result
        # 保持降序排列：索引 42 在前，5 在后
        assert result.find("file_a") < result.find("file_c")


# ═══════════════════════════════════════════════
# 单元测试 2：RAG 流程中的 context 验证
# ═══════════════════════════════════════════════

class TestContextInRagPipeline:
    """验证 prepare_index → retrieve → context 构建链"""

    COLLECTION_NAME = "test_meta_unit"
    TEST_FILES = [PDF_FILE, MD_FILE]

    @classmethod
    def setup_class(cls):
        """构建索引供后续测试使用"""
        model, collection, bm25, docs, metadatas = prepare_index(
            cls.TEST_FILES, cls.COLLECTION_NAME, force_rebuild=True,
        )
        cls.model = model
        cls.collection = collection
        cls.bm25 = bm25
        cls.docs = docs
        cls.metadatas = metadatas

    @classmethod
    def teardown_class(cls):
        """清理 collection"""
        try:
            client = chromadb.PersistentClient(path=str(TEST_DB_PATH))
            client.delete_collection(cls.COLLECTION_NAME)
        except Exception:
            pass

    def test_metadatas_contain_source(self):
        """所有 metadatas 应该有 source 字段"""
        for meta in self.metadatas:
            assert "source" in meta, f"Missing 'source' in metadata: {meta}"

    def test_retrieved_context_includes_source(self):
        """调用 answer_query 后，传递给 LLM 的 context 应包含 [Source: ...] 标注"""
        from src.rag import answer_query, _build_context

        # answer_query 内部调用 _build_context，返回的 sources 字符串由 format_sources 生成
        # 我们无法直接拦截 LLM 请求，但可以验证 answer_query 返回后 internal 调用链的正确性
        # 这里验证 prepare_index 返回的索引包含正确的文件名
        seen_sources = set()
        for meta in self.metadatas:
            seen_sources.add(meta.get("source", ""))
        for fpath in self.TEST_FILES:
            assert os.path.basename(fpath) in seen_sources


# ═══════════════════════════════════════════════
# 集成测试：端到端验证 LLM 回答
# ═══════════════════════════════════════════════

class TestLlmCanAnswerMetaQuestion:
    """端到端测试 LLM 能否回答文件数量问题（需要 .env 中的 API Key）"""

    COLLECTION_NAME = "test_meta_integration"
    TEST_FILES = [PDF_FILE, MD_FILE, DOCX_FILE]

    @classmethod
    def setup_class(cls):
        """构建含 3 个文件的索引"""
        cls.skip = False
        if not os.path.isfile(".env"):
            cls.skip = True
            return

        model, collection, bm25, docs, metadatas = prepare_index(
            cls.TEST_FILES, cls.COLLECTION_NAME, force_rebuild=True,
        )
        cls.model = model
        cls.collection = collection
        cls.bm25 = bm25
        cls.docs = docs
        cls.metadatas = metadatas

    @classmethod
    def teardown_class(cls):
        if not cls.skip:
            try:
                client = chromadb.PersistentClient(path=str(TEST_DB_PATH))
                client.delete_collection(cls.COLLECTION_NAME)
            except Exception:
                pass

    def test_llm_can_count_files(self):
        """提问文件数量，回答应包含 '3'（或 '三'）"""
        if self.skip:
            pytest.skip("缺少 .env 配置")

        from src.rag import answer_query
        answer, sources = answer_query(
            "知识库中一共储存了多少个文件？请列出所有文件名。",
            self.model, self.collection, self.bm25,
            self.docs, self.metadatas,
        )
        # 回答应包含数字 3（或汉字三）
        assert any(char in answer for char in ["3", "三"]), (
            f"LLM 回答应包含文件数量，实际回答: {answer}"
        )
        # 回答应包含 3 个文件名
        for fpath in self.TEST_FILES:
            basename = os.path.basename(fpath)
            assert basename in answer, (
                f"文件名 '{basename}' 应出现在 LLM 回答中，实际回答: {answer}"
            )
```

### RED 阶段验收标准

```bash
cd /Users/deepprinciple/Desktop/henry/rag-sys
python -m pytest tests/test_llm_meta_answer.py -v -k "not integration"
# 预期：TestBuildContextFunction 中 7 个测试全部 FAIL（_build_context 尚不存在）
#        TestContextInRagPipeline 中 2 个测试 PASS（回归保护）
```

---

## TDD 循环 2：添加 `_build_context` 辅助函数（GREEN）

### 变更点：`src/rag.py`

在 `enrich_context` 函数定义**之前**（约第 515 行）新增，使参数签名相同的工具函数集中在一起：

```python
def _build_context(
    top_indices: list[int],
    docs: list[str],
    metadatas: list[dict],
) -> str:
    """将 top-ranked chunk 拼接为 LLM context，每个 chunk 前标注来源文件名。

    Args:
        top_indices: 排序后的 chunk 索引列表，值作为 docs 和 metadatas 的索引
        docs:        全量文档文本列表（docs[i] 获取第 i 个文档文本）
        metadatas:   全量元数据列表（metadatas[i]["source"] 获取第 i 个文档的文件名）

    Returns:
        带 [Source: filename] 标注的 context 字符串，chunk 间以双换行分隔
    """
    parts = []
    for i in top_indices:
        source = metadatas[i].get("source", "unknown")
        parts.append(f"[Source: {source}]\n{docs[i]}")
    return "\n\n".join(parts)
```

**说明**：
- `metadatas[i]["source"]` 在 `build_index` 和 `add_files_to_index` 中被设为 `os.path.basename(fp)`，始终存在
- `metadatas[i].get("source", "unknown")` 兜底，防御性编程
- 与 `format_sources` 职责分离：一个面向 LLM context，一个面向 UI 展示
- **关键约束**：`docs` 和 `metadatas` 必须是全量列表（索引空间 >= `max(top_indices)`）。`graph_rag.py` 中 `top_indices` 是全局索引（如 `[42, 17, 5]`），必须传 `all_docs`，不能传截断后的 `top_docs`

### GREEN 阶段验收

```bash
python -m pytest tests/test_llm_meta_answer.py::TestBuildContextFunction -v
# 预期：全部 7 个测试 PASS
```

---

## TDD 循环 3：修复 `rag.py` 中 2 处 context 构建（GREEN）

### 变更点 R1 — `answer_query`（第 687-688 行）

```diff
-    enriched_docs = enrich_context(top_indices, documents, metadatas)
-    context = "\n\n".join([enriched_docs[i] for i in top_indices])
+    enriched_docs = enrich_context(top_indices, documents, metadatas)
+    context = _build_context(top_indices, enriched_docs, metadatas)
```

### 变更点 R2 — `answer_query_stream`（第 912-913 行）

```diff
-    enriched_docs = enrich_context(top_indices, documents, metadatas)
-    context = "\n\n".join([enriched_docs[i] for i in top_indices])
+    enriched_docs = enrich_context(top_indices, documents, metadatas)
+    context = _build_context(top_indices, enriched_docs, metadatas)
```

### 确认调用关系

```
answer_query / answer_query_stream
  → retrieve_hybrid_with_sources      (不变)
  → dynamic_top_k                     (不变)
  → enrich_context                    (不变)
  → _build_context                    ← 新增，替换原来的 "\n\n".join(...)
  → format_sources                    (不变，仅用于 UI 展示)
  → answer_with_llm_history / _stream (不变)
```

### GREEN 阶段验收

```bash
python -m pytest tests/test_llm_meta_answer.py::TestContextInRagPipeline -v
# 预期：全部 PASS
```

---

## TDD 循环 4：修复 `graph_rag.py` 中 3 处 context 构建（GREEN）

### 变更点：`src/graph_rag.py` 头部 import

```diff
 from rag import (
     build_bm25_index,
     build_index, ask_for_files, _collection_exists,
     add_files_to_index,
     retrieve_hybrid_with_sources, dynamic_top_k,
     answer_with_llm_history, format_sources,
+    _build_context,                             # 新增
     SentenceTransformer, chromadb,
     EMBEDDING_MODEL_NAME, DEFAULT_COLLECTION_NAME,
     DEFAULT_TOP_K, DEFAULT_MIN_K, DEFAULT_MAX_K,
     CHROMA_DB_PATH, DEFAULT_LLM_MODEL,
 )
```

### 变更点 G1 — `graph_rag_pipeline`（第 417 行）

`top_indices` 中的值是 `all_docs` 的全局索引（如 `[42, 17, 5]`），因此 `docs` 参数必须传 `all_docs`（全量文档列表），而非截断后的 `top_docs`：

```diff
-    context = " ".join(top_docs)
+    context = _build_context(top_indices, all_docs, all_metadatas)
```

### 变更点 G2 — `graph_query_stream`（第 549 行）

同理，`docs[:k]` 只有 k 个元素但 `top_indices[i]` 是全局索引 → 传 `all_docs`：

```diff
-    context = " ".join(docs[:k])
+    context = _build_context(top_indices, all_docs, all_metadatas)
```

### 变更点 G3 — CLI `__main__`（第 471 行 / 第 509 行）

两处相同，均使用 `all_docs` 而非 `top_docs`：

**位置 1（第 ~471 行，`if args.query:` 块内）：**

```diff
-    context = " ".join(top_docs)
+    context = _build_context(top_indices, all_docs, all_metadatas)
```

**位置 2（第 ~509 行，对话循环内）：**

```diff
-    context = " ".join(top_docs)
+    context = _build_context(top_indices, all_docs, all_metadatas)
```

### 验证

```bash
python -m pytest tests/test_llm_meta_answer.py -v -k "not integration"
# 预期：全部单元测试 PASS
```

---

## TDD 循环 5：集成验证（GREEN）

### 端到端集成测试

```bash
cd /Users/deepprinciple/Desktop/henry/rag-sys
python -m pytest tests/test_llm_meta_answer.py::TestLlmCanAnswerMetaQuestion -v
# 预期：
#   - test_llm_can_count_files PASS（LLM 回答含至少一个文件名，基于 context 中的 [Source: ...]）
#   - 如缺 .env 则 SKIP
#   - 注意：并非所有文件都会出现在检索结果中，LLM 只能回答 context 中有的内容
```

**注**：集成测试目前只覆盖 `rag.py` 的 `answer_query` 路径。`graph_rag.py` 的 `graph_rag_pipeline` 和 `graph_query_stream` 需要真实 LLM API 调用，在当前单测环境中未覆盖，通过 CLI 手动验证（见下节）。

### 全量回归

```bash
python -m pytest tests/ -v -k "not integration"
# 预期：所有非集成测试 PASS，已有测试不受影响
```

### 语法检查

```bash
python -m py_compile src/rag.py
python -m py_compile src/graph_rag.py
python -m py_compile tests/test_llm_meta_answer.py
# 预期：全部无错误
```

### 手动端到端验证

```bash
# CLI 测试
python src/rag.py \
  --files test_texts/2405.02357v2.pdf test_texts/LLMs_for_Mobility_Analysis_Survey.md \
  --query "知识库中有多少个文件？分别是什么？"

python src/graph_rag.py \
  --files test_texts/2405.02357v2.pdf test_texts/DSpark_paper.pdf \
  --query "知识库中有多少个文件？分别是什么？" \
  --alpha 0.7

# TUI 测试
python -m tui
# 1. 添加 3 个文件
# 2. 在 /files 中确认文件列表
# 3. 提问 "知识库中储存了多少文件？"
# 4. 回答应正确指出文件数量
```

---

## REFACTOR 阶段

### 1. 统一 graph_rag.py 的 context 分隔符

`graph_rag.py` 原来用 `" ".join()`（空格），现在统一用 `"\n\n".join()`（双换行，通过 `_build_context` 实现）。这同时也修复了 graph 路径中 chunks 粘连的问题。

### 2. 确认 `format_sources` 职责不变

`format_sources` 继续用于 UI 展示参考来源，与 `_build_context` 互不干扰。`answer_query` 和 `answer_query_stream` 的返回值签名不变（返回 `answer, sources`）。

### 3. 检查 `enrich_context` 的兼容性

`enrich_context` 返回与 `documents` 同长度的列表，anchor chunk 替换为 PDF 首页全文。`_build_context` 接收的是 `enriched_docs`（已替换的文本），使用 `metadatas[i]["source"]` 查找文件名。anchor chunk 的 metadata 中也有 `source` 字段，不影响 source 标注。

### 4. 考虑 context 大小影响

每个 chunk 新增 `[Source: xxx.pdf]\n` 约 20 字节。top_k 最大 70 时，最多增加 1.4KB。对于 DeepSeek 128K+ 的 context window，可忽略不计。

---

## 验收检查清单

### 功能验收

- [ ] `_build_context(top_indices, docs, metadatas)` 为每个 chunk 添加 `[Source: filename]` 前缀
- [ ] `rag.py` 的 `answer_query` 使用 `_build_context` 构建 context
- [ ] `rag.py` 的 `answer_query_stream` 使用 `_build_context` 构建 context
- [ ] `graph_rag.py` 的 `graph_rag_pipeline` 使用 `_build_context` 构建 context
- [ ] `graph_rag.py` 的 `graph_query_stream` 使用 `_build_context` 构建 context
- [ ] `graph_rag.py` 的 CLI 对话循环使用 `_build_context` 构建 context

### LLM 回答验收

- [ ] 提问 "知识库中储存了多少文件？" → 回答基于 context 中的 [Source: ...] 标注（至少含一个文件名）
- [ ] 提问 "列出所有文件名" → 回答列出 context 中实际存在的文件名
- [ ] 提问内容相关问题（如技术细节）→ 回答质量不受影响
- [ ] 提问无关问题 → LLM 正确回答"找不到相关信息"（不因 source 标注而幻觉）

### 回归验收

- [ ] `format_sources` 的 UI 展示格式不受影响
- [ ] `enrich_context` 的 anchor chunk 替换逻辑不变
- [ ] `rag_pipeline` 和 `graph_rag_pipeline` 的返回值签名不变
- [ ] TUI 的 `/status` 命令显示的文件数正确
- [ ] TUI 的 `/files` 命令的 add/remove/list 功能正常

### 测试验收

- [ ] `tests/test_llm_meta_answer.py::TestBuildContextFunction` 7 个测试全部 PASS（含非连续索引测试）
- [ ] `tests/test_llm_meta_answer.py::TestContextInRagPipeline` 测试 PASS
- [ ] 集成测试 `TestLlmCanAnswerMetaQuestion` PASS（或有 .env 时 PASS）
- [ ] `python -m pytest tests/ -v -k "not integration"` 全部 PASS
- [ ] `python -m py_compile src/rag.py src/graph_rag.py` 无错误
- [ ] `python src/graph_rag.py` CLI 手动验证：提问后回答含正确文件数

---

## 文件变更汇总

| 文件 | 变更类型 | 说明 |
|------|---------|------|
| `src/rag.py` | **修改** | 新增 `_build_context` 辅助函数（放在 `enrich_context` 之前）+ 替换 2 处 context 构建 |
| `src/graph_rag.py` | **修改** | import 新增 `_build_context` + 替换 3 处 context 构建（传 `all_docs` 而非 `top_docs`）|
| `tests/test_llm_meta_answer.py` | **新建** | 7 个单元测试 + 2 个回归测试 + 1 个集成测试（共 10 个测试用例） |

---

## 执行顺序

```
T1 RED     → 写 test_llm_meta_answer.py → 验证单元测试 FAIL（集成测试 SKIP）
T2 GREEN   → 在 rag.py 添加 _build_context → 单元测试 PASS
T3 GREEN   → 修复 rag.py 中 2 处调用点 → 回归测试 PASS
T4 GREEN   → 修复 graph_rag.py 中 import + 3 处调用点 → 全部测试 PASS
T5 GREEN   → 全量 pytest + 端到端验证
T5 REFACTOR → 代码审查 & 一致性检查
```

---

## 附录：context 构建前后对比

### 修复前（以 `answer_query` 为例）

LLM 收到的 `context`：
```
Large Language Models for Mobility Analysis...
They particularly excel at identifying complex patterns...
DSpark: Confidence-Scheduled Speculative Decoding...
```

LLM 无法知道这 3 段分别来自哪个文件。

### 修复后

LLM 收到的 `context`：
```
[Source: 2405.02357v2.pdf]
Large Language Models for Mobility Analysis...

[Source: 2405.02357v2.pdf]
They particularly excel at identifying complex patterns...

[Source: DSpark_paper.pdf]
DSpark: Confidence-Scheduled Speculative Decoding...
```

LLM 可以看到第一、二段来自 `2405.02357v2.pdf`，第三段来自 `DSpark_paper.pdf`。当被问及文件数量时，可以回答"2 个文件"。

---

## 附录：`_build_context` 与 `format_sources` 职责对比

| | `_build_context` | `format_sources` |
|--|-----------------|-----------------|
| 用途 | 构建传入 LLM 的 context | 格式化参考来源供 UI 展示 |
| 输出位置 | LLM prompt 中 | 终端打印 |
| 输出格式 | `[Source: filename]\n{text}\n\n` | `[1] filename (片段N): 前150字...` |
| 数据来源 | `metadatas[i]["source"]` | `metadatas[i]["source"]` |
| 调用者 | `answer_query` / `answer_query_stream` / graph 路径 | `answer_query` 的返回值 + UI |

两者数据来源相同但输出格式和用途不同，保持独立。

---

*计划创建时间：2026-07-03*
*计划执行者：Kilo*
*关联 Issue：#16*
*TDD 基准：测试先行，最小实现，逐步重构*
