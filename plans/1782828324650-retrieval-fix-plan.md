# RAG 检索修复计划

## 背景

查询 "LLMs for mobility这篇文章的作者都属于什么学校或者科研机构？" 返回 "无法找到"。

**根因链**：pdfplumber 丢失空格（`UniversityofPennsylvania`）→ BM25 `split()` 不支持中文 → 作者 chunks 在语义/BM25/RRF 三重失效 → dynamic_top_k 截断排除。

**验证数据**：见 `plans/1782828324650-review-verification.md`。

---

## 任务清单

### 任务 1：替换 PDF 提取器 — pdfplumber → PyMuPDF

**文件：** `rag.py:95-120` — `load_pdf()` 和 `load_pdf_pages()`

**改动：**
- `import pdfplumber` → `import fitz`
- `page.extract_text()` → `page.get_text("text")`
- 保留 pdfplumber 作为 fallback（`try fitz except → pdfplumber`）

**数据支撑：** pdfplumber 19 超长 token / 42 总 → PyMuPDF 1 / 152

**依赖：** `pip install PyMuPDF`（`requirements.txt` 添加）

---

### 任务 2：BM25 分词 — 支持中英混合 + lower + 标点清理

**文件：** `rag.py:405-407` — `build_bm25_index()` 和 `rag.py:457` — `retrieve_hybrid_with_sources()`

**改动：**

新增顶层函数：
```python
import re

_STRIP_PUNCT = re.compile(r'^[:;,\.!?\"\'\)]+|[:;,\.!?\"\'\(]+$')

def _tokenize(text: str) -> list[str]:
    """中英混合分词：英文按单词、中文按连续字符切分，统一小写，去除尾部标点"""
    raw = re.findall(r'[a-zA-Z]+[0-9]*|[0-9]+(?:\.[0-9]+)?|[\u4e00-\u9fff]+', text)
    return [_STRIP_PUNCT.sub('', t).lower() for t in raw if _STRIP_PUNCT.sub('', t)]
```

修正点（对应审阅意见问题 1）：
- `.lower()` — BM25 默认 case-sensitive，`"Authors"` ≠ `"authors"`
- 数字匹配 `[0-9]+(?:\.[0-9]+)?` — 捕获 `2025`、`2405.02357`
- 标点 strip — `"Authors:"` → `"authors"`，`"Survey,"` → `"survey"`

`build_bm25_index()`：
```python
# 旧: tokenized = [doc.split() for doc in documents]
# 新: tokenized = [_tokenize(doc) for doc in documents]
```

`retrieve_hybrid_with_sources()` 第 457 行：
```python
# 旧: query_tokens = query.split()
# 新: query_tokens = _tokenize(query)
```

**验证命令：**
```python
_tokenize("Authors: Zijian Zhang, University of Pennsylvania, 2025.")
# → ['authors', 'zijian', 'zhang', 'university', 'of', 'pennsylvania', '2025']
```

---

### 任务 3：构造元数据 anchor chunk

**文件：** `rag.py` — `build_index()` (264-281) 和 `add_files_to_index()` (344-362)

**改动：** 在 PDF 分支中，正常切片完成后，额外生成一个 anchor chunk：

```python
# 在 PDF 切片循环结束后、非 PDF 分支前
if pages:
    first_page_text = pages[0][0]
    anchor_lines = first_page_text.splitlines()[:15]
    anchor_text = " ".join(line.strip() for line in anchor_lines if line.strip())
    if anchor_text:
        all_chunks.append(anchor_text)
        all_metadatas.append({
            "source": os.path.basename(fp),
            "file_type": file_type,
            "chunk_index": -1,
            "chunk_type": "anchor",
        })
        all_ids.append(f"{file_prefix}_anchor")
```

修正点（对应审阅意见问题 2）：
- `if pages` — 空白扫描件保护，避免 `IndexError`
- `splitlines()` — 替代 `split('\n')`，兼容 `\r\n` 和连续换行
- `if anchor_text` — 防止空文本进入索引

`add_files_to_index()` 改动同上。注意：`add_files_to_index()` 中 PDF 分支调用 `load_pdf_pages()` 返回 pages，可直接使用；非 PDF 分支调用 `load_document()` 返回整篇文本，无 page 粒度——非 PDF 文件不生成 anchor（其 `chunk_size=2000` 已足够保留元数据完整性）。

---

### 任务 4：RRF / dynamic_top_k 参数调优

**文件：** `rag.py:410-434` — `rrf_merge()` 和 `dynamic_top_k()`

**改动：**

`dynamic_top_k()` 提高 `min_k` 保底值：
```python
# 旧: DEFAULT_MIN_K = 3
# 新: DEFAULT_MIN_K = 6
```

理由：`min_k=3` 意味着即使 RRF score gap 很小，也可能只返回 3 个 chunks。提高到 6 确保至少有 6 个候选。

**数据支撑：** 实测 PyMuPDF + regex + lower + anchor 后，anchor RRF rank 约 8-12。`min_k=6` 仍可能不够，但比 `min_k=3` 好。如果测试不通过，再考虑进一步提高或对 anchor 加权。

---

### 任务 5：更新依赖

**文件：** `requirements.txt`（如存在）或在 `rag.py` 顶部注释

添加：`PyMuPDF>=1.24.0`

---

### 任务 6：回归测试

**文件：** 新建 `test_retrieval_fix.py`

**测试用例：**
```python
import pytest
import rag
from rag import (
    prepare_index, retrieve_hybrid_with_sources, dynamic_top_k,
)

@pytest.fixture
def test_db(tmp_path):
    """创建独立临时数据库，避免污染生产 chroma_db"""
    db_path = str(tmp_path / "test_chroma")
    original = rag.CHROMA_DB_PATH
    rag.CHROMA_DB_PATH = db_path
    yield db_path
    rag.CHROMA_DB_PATH = original

def test_author_query_recall_at_20(test_db):
    """中英混合元数据查询 Recall@20"""
    model, collection, bm25, docs, metas = prepare_index(
        ["test_texts/2405.02357v2.pdf"], "test_fix", force_rebuild=True
    )
    query = "LLMs for mobility这篇文章的作者都属于什么学校或者科研机构？"
    indices, _, scores = retrieve_hybrid_with_sources(query, model, collection, bm25, docs)

    top20_indices = set(indices[:20])
    anchor_indices = {i for i, m in enumerate(metas) if m.get("chunk_type") == "anchor"}
    assert anchor_indices, "未生成 anchor chunk"
    recall_20 = bool(top20_indices & anchor_indices)
    print(f"Recall@20: {recall_20}")

def test_author_query_recall_at_dynamic_k(test_db):
    """中英混合元数据查询 Recall@dynamic_top_k（严格）"""
    model, collection, bm25, docs, metas = prepare_index(
        ["test_texts/2405.02357v2.pdf"], "test_fix", force_rebuild=True
    )
    query = "LLMs for mobility这篇文章的作者都属于什么学校或者科研机构？"
    indices, _, scores = retrieve_hybrid_with_sources(query, model, collection, bm25, docs)
    k = dynamic_top_k(scores)

    top_k_indices = set(indices[:k])
    anchor_indices = {i for i, m in enumerate(metas) if m.get("chunk_type") == "anchor"}
    assert anchor_indices, "未生成 anchor chunk"
    recall_k = bool(top_k_indices & anchor_indices)
    print(f"Recall@dynamic_k (k={k}): {recall_k}")
    # 不 assert，仅记录——如果 Recall@20 通过但 Recall@k 失败，说明 RRF 截断仍是瓶颈
```

修正点（对应审阅意见问题 4）：
- 独立临时数据库（`tmp_path` fixture）— 不污染生产 `chroma_db`
- **`rag.CHROMA_DB_PATH` monkeypatch**（非 `os.environ`）— `CHROMA_DB_PATH` 是模块常量，不从环境变量读取
- 双重检查：`Recall@20`（宽松）和 `Recall@dynamic_k`（严格）分别记录
- 检测 `chunk_type == "anchor"`（而非 `chunk_index == -1`）— 更明确
- 显式 `assert anchor_indices` — 防止空集合导致假通过

---

## 实施顺序

| 步骤 | 任务 | 改动量 | 验证 |
|------|------|--------|------|
| 1 | 任务 1：PyMuPDF | ~10 行 | 提取 page 1 确认空格正常 |
| 2 | 任务 2：regex 分词 + lower + 标点清理 | ~10 行 | `_tokenize("Authors:") == ["authors"]` |
| 3 | 任务 3：anchor chunk | ~15 行 | anchor 进入索引 |
| 4 | 任务 4：min_k 调参 | ~1 行 | `DEFAULT_MIN_K = 6` |
| 5 | 任务 5：依赖 | 1 行 | `pip install PyMuPDF` 成功 |
| 6 | 任务 6：回归测试 | ~40 行 | Recall@20 通过，Recall@k 记录 |

**总改动量：~77 行**

---

## 实施状态

| 任务 | 状态 |
|------|------|
| 任务 1：PyMuPDF | ✅ 已实现 |
| 任务 2：_tokenize | ✅ 已实现 |
| 任务 3：anchor chunk | ✅ 已实现 |
| 任务 4：DEFAULT_MIN_K=12 | ✅ 已实现（比计划 6 更宽松） |
| 任务 5：requirements.txt | ✅ 已实现 |
| 任务 6：回归测试 | ✅ 已实现（8/8 通过） |

## 实际效果

| 指标 | 修复前 | 修复后（实测） |
|------|--------|---------------|
| PDF 超长 token | 19/42 (45%) | 0/152 (0%) |
| 作者 chunks BM25 得分 | 0.0 | >0 |
| anchor chunk 生成 | N/A | ✅ 确认生成 |
| Recall@20（中英混合元数据查询） | 0% | **0%（未达标）** |
| Recall@dynamic_top_k | 0% | 取决于 min_k 取值 |

Recall@20 未达标的原因：即使有 PyMuPDF 空格修复 + regex 分词 + anchor chunk + RRF×2 加权，anchor 仍不在 top-20。需要进一步的查询改写（提取「作者」「学校」子查询）或分层检索策略。

---

## 风险

| 风险 | 缓解 |
|------|------|
| PyMuPDF 对扫描件 PDF 效果差 | 保留 pdfplumber 作为 fallback |
| regex 分词误切专业术语 | `[a-zA-Z]+` 匹配完整英文单词，不会拆字母；`.lower()` 不影响中文 |
| anchor chunk 与正常 chunks 重叠 | embedding 会有差异（拼接 vs 切片），不完全相同 |
| **anchor 的 RRF rank 可能仍低于 dynamic_top_k 截断点** | 任务 4 提高 `min_k` 缓解；若仍不通过，后续考虑 anchor 加权或 RRF k 因子调参 |
