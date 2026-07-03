# RAG 检索失败分析报告

**问题查询：** "LLMs for mobility这篇文章的作者都属于什么学校或者科研机构？"  
**实际回答：** "根据提供的文档内容，无法找到"  
**预期回答：** University of Pennsylvania, University of Washington, Princeton University, University of Arizona, University of South California, Duke Kunshan University

---

## 一、根因总结

检索系统未能将查询指向包含作者/机构信息的 chunks。**作者 chunks（5, 6, 7）在语义检索和 BM25 检索中均未进入 top-20**，导致 LLM 收到的 context 中完全没有作者/机构信息。

具体原因有三层，按严重程度排序：

| 优先级 | 原因 | 影响 |
|--------|------|------|
| P0 | PDF 文本提取无空格，破坏 tokenization 和 embedding | BM25 和语义检索均失效 |
| P1 | 作者 chunks 太短（3-4 行），语义信息稀薄 | 短文本天然匹配劣势 |
| P2 | 查询是混合语义（主题 + 元数据），单一检索路径无法覆盖 | 需要查询分解或多路召回 |

---

## 二、详细诊断数据

### 2.1 PDF 文本提取质量

pdfplumber 从 PDF 提取的文本**单词之间没有空格**：

```
原始 PDF:     Zijian Zhang, University of Pennsylvania
提取结果:     ZijianZhang,Co-firstAuthor
              UniversityofPennsylvania,Philadelphia,Pennsylvania,19104
```

**影响：**
- BM25 分词器（按空格切分）将 `UniversityofPennsylvania` 视为**一个 token**，无法匹配查询中的 `University` 或 `Pennsylvania`
- embedding 模型对无空格文本的语义理解能力大幅下降

### 2.2 BM25 分词对比

**查询 tokens（按空格切分）：**
```
['LLMs', 'for', 'mobility这篇文章的作者都属于什么学校或者科研机构？']
```
只有 3 个 token，中文部分被当作一个整体 token。

**作者 chunk 5 tokens（前 10 个）：**
```
['LargeLanguageModelsforMobilityAnalysisinTransportationSystems:',
 'ASurveyon', 'ForecastingTasks', 'ZijianZhang,Co-firstAuthor',
 'TheDepartmentofComputerandInformationScience',
 'UniversityofPennsylvania,Philadelphia,Pennsylvania,19104', ...]
```

**匹配分析：** 查询中的 `LLMs`、`for`、`mobility` 均无法与 `LargeLanguageModels...` 或 `UniversityofPennsylvania...` 匹配。BM25 得分为 **0**。

### 2.3 语义检索排名

| 排名 | chunk idx | cosine distance | 内容摘要 |
|------|-----------|-----------------|----------|
| 1 | 29 | 0.4589 | "transportation and mobility planning solutions..." |
| 2 | 145 | 0.4729 | "challenges that must be overcome..." |
| 3 | 71 | 0.4748 | "LLM applications in transportation forecasting..." |
| ... | ... | ... | ... |
| **未进 top-20** | **5** | **0.2349** | **"ZijianZhang, UniversityofPennsylvania..."** |
| **未进 top-20** | **6** | **0.1596** | **"ZepuWang, UniversityofWashington..."** |
| **未进 top-20** | **7** | **0.1996** | **"RuolinLi, UniversityofSouthCalifornia..."** |

作者 chunks 的 cosine similarity 仅为 0.16-0.23，而 top-1 内容 chunk 为 0.54。**语义差距巨大。**

### 2.4 BM25 单独排名

作者 chunks（5, 6, 7）**同样不在 BM25 top-20 中**。BM25 top-1 得分 2.01，作者 chunks 得分为 0（完全无匹配 token）。

### 2.5 RRF 融合后

RRF 融合了语义 + BM25 结果，两种检索路径都未命中作者 chunks → **最终 top-20 中完全没有作者信息**。`dynamic_top_k` 选出 6 个 chunks 送给 LLM，全部是关于 LLMs 在交通领域应用的泛化讨论。

---

## 三、根因拆解

### 原因 1：PDF 文本提取无空格（P0）

**位置：** `rag.py:119-136` — `load_pdf_pages()` 使用 pdfplumber

pdfplumber 的 `extract_text()` 在某些 PDF 布局下会丢失单词间空格，尤其是：
- 学术论文的作者信息区域（多列布局、脚注格式）
- 标题区域（大字号、非常规排版）

**验证：** 同一篇论文的 MD 版本（`LLMs_for_Mobility_Analysis_Survey.md`）切片后，chunk 0 包含完整且格式正确的作者/机构信息：
```
**Authors:** Zijian Zhang, Yujie Sun, Zepu Wang, Yuqi Nie, Xiaobo Ma, Ruolin Li, Peng Sun, Xuegang Ban
**Affiliations:** University of Pennsylvania, University of Washington, Princeton University, ...
```

### 原因 2：短 chunks 在检索中天然弱势（P1）

**位置：** `rag.py:163-178` — `get_splitter()` 配置

PDF 作者信息被切为 3 个短 chunk（每个约 200-300 字符），内容只有姓名、系名、邮箱地址。这类"元数据型"文本：
- 语义 embedding 信息密度低，无法与查询的主题语义匹配
- BM25 依赖关键词重叠，但 PDF 提取的 token 完全变形

### 原因 3：混合语义查询无法单路召回（P2）

**位置：** `rag.py:437-480` — `retrieve_hybrid_with_sources()`

查询 "LLMs for mobility这篇文章的作者都属于什么学校或者科研机构？" 包含两个语义意图：
1. **主题定位**：`LLMs for mobility` → 需要找到这篇论文
2. **元数据查询**：`作者` `学校` `科研机构` → 需要找到作者信息 chunks

当前检索系统将整个查询作为一个整体进行 embedding，语义重心偏向主题部分（"LLMs for mobility"），元数据意图被稀释。

---

## 四、预期解决方法

### 方案 1：PDF 文本后处理 — 修复空格问题（推荐，P0 优先级）

**改动位置：** `rag.py` — `load_pdf_pages()` 返回后增加后处理

**思路：** 在 PDF 文本提取后，用正则表达式修复常见空格缺失问题：
- `CamelCase` → `Camel Case`（检测大小写边界）
- 连续大写字母后跟小写：`Universityof` → `University of`
- 逗号/句号后缺空格

**风险：** 可能误切专业术语（如 `BERT`、`GPT-3`），需要保守规则。

**预期效果：** BM25 能正确分词 `University of Pennsylvania`，语义 embedding 质量提升。

### 方案 2：优先使用 MD/文本格式（推荐，低成本）

**思路：** 当同时存在 PDF 和 MD 版本时，优先使用 MD 文件。MD 文件保留了结构化格式（标题、加粗、列表），切片质量远优于 PDF。

**验证数据：**
- MD chunk 0（1859 chars）包含完整标题 + 全部作者 + 全部机构
- PDF chunks 5-7（各 200-300 chars）信息被拆散且无空格

### 方案 3：查询分解（Query Decomposition）（P2 优先级）

**改动位置：** `rag.py` — `answer_query()` 前增加查询分解步骤

**思路：** 用 LLM 将复杂查询分解为多个子查询，分别检索后合并结果：
```
原始查询: "LLMs for mobility这篇文章的作者都属于什么学校或者科研机构？"
↓ 分解为:
子查询 1: "LLMs for mobility survey paper"        → 定位论文
子查询 2: "authors affiliations university"        → 定位作者信息
```

**优点：** 根本性解决混合语义查询问题。  
**缺点：** 增加一次 LLM 调用延迟。

### 方案 4：chunk 元数据增强（P2 优先级）

**改动位置：** `rag.py` — `build_index()` 中 chunk metadata

**思路：** 在每个 chunk 的 metadata 中添加文件级元数据（作者、机构、标题），使检索时能匹配到元数据字段：
```python
all_metadatas.append({
    "source": "2405.02357v2.pdf",
    "title": "Large Language Models for Mobility Analysis...",
    "authors": "Zijian Zhang, Yujie Sun, ...",
    "affiliations": "University of Pennsylvania, ...",
    ...
})
```

**优点：** 即使 chunk 内容不含作者信息，metadata 也能被检索到。  
**缺点：** 需要额外的元数据提取步骤（可用 LLM 自动提取）。

### 方案 5：增大检索窗口 + 重排序（P2 优先级）

**改动位置：** `rag.py` — `retrieve_hybrid_with_sources()` 和 `dynamic_top_k()`

**思路：**
- 将 `n_results` 从 20 增大到 50
- 增加 cross-encoder 重排序步骤，用更精确的模型对候选 chunks 重排

---

## 五、推荐实施顺序

| 步骤 | 方案 | 工作量 | 预期收益 |
|------|------|--------|----------|
| 1 | 方案 2：优先使用 MD 格式 | 低 | 立即解决同类问题 |
| 2 | 方案 1：PDF 文本后处理 | 中 | 根治 PDF 提取质量 |
| 3 | 方案 3：查询分解 | 中 | 提升复杂查询能力 |
| 4 | 方案 4：元数据增强 | 中 | 提升元数据类查询 |
| 5 | 方案 5：增大检索窗口 | 低 | 边际提升 |

---

## 六、关键数据摘要

| 指标 | 值 |
|------|-----|
| 作者 chunks (5,6,7) 语义检索排名 | **未进 top-20** |
| 作者 chunks BM25 排名 | **未进 top-20** |
| 作者 chunks cosine similarity | 0.16 ~ 0.23 |
| Top-1 内容 chunk cosine similarity | 0.54 |
| PDF 提取 token 示例 | `UniversityofPennsylvania` (无空格) |
| MD 切片作者信息 | chunk 0 包含完整作者+机构 (1859 chars) |
| PDF 切片作者信息 | chunks 5-7 各 200-300 chars，信息碎片化 |
| `dynamic_top_k` 选出的 chunks 数 | 6 |
| 送给 LLM 的 context 中作者信息 | **无** |
