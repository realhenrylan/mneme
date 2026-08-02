# Mneme RAG 评测标注规范

> 版本：v1
> 更新日期：2026-08-01

---

## 一、概述

本规范定义了 Mneme RAG 评测数据集的标注流程和标准。评测数据集用于衡量检索和生成质量，所有后续优化都应在此数据集上证明净收益或净损失。

### 核心原则

1. **可复现**：相同数据集 + 相同代码 + 相同模型 → 相同分数
2. **防过拟合**：训练子集用于调参，holdout 子集仅用于最终验收
3. **独立评估**：检索评测和生成评测独立运行，不把检索失败和生成失败混为一谈

---

## 二、数据格式

### JSONL 格式

每行一个 JSON 对象，代表一条评测用例。文件编码为 UTF-8。

### 字段说明

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `id` | string | ✓ | 唯一标识符，格式：`{类型缩写}-{序号}`，如 `zh-001`、`en-015`、`cross-003` |
| `query` | string | ✓ | 自然语言查询字符串 |
| `query_type` | string | ✓ | 查询类型，见下方枚举 |
| `language` | string | ✓ | 查询语言：`zh`（中文）、`en`（英文）、`mixed`（中英混合） |
| `relevant_source_ids` | string[] | ✓ | 包含答案的源文件名列表。应拒答的查询为空数组 |
| `relevant_chunks` | object[] | | 相关 chunk 列表，每个包含 `source_id`、`chunk_text_snippet`、`page`、`section` |
| `acceptable_answer_points` | string[] | ✓ | 正确回答必须包含的关键事实要点。应拒答的查询为空数组 |
| `should_refuse` | boolean | ✓ | 系统是否应拒答（语料中无相关证据） |
| `metadata` | object | | 附加标注信息，如 `difficulty`、`turn`、`follow_up_to` |

### 查询类型枚举

| 类型 | 值 | 说明 | 示例 |
| --- | --- | --- | --- |
| 单文档事实 | `single_fact` | 答案来自单个文档的事实 | "南京的面积是多少？" |
| 跨文档比较 | `cross_document` | 需要对比多个文档的信息 | "比较DSpark和mobility survey的LLM应用" |
| 元数据查询 | `metadata` | 关于文档本身的查询 | "哪篇文档讨论了数据泄露防护？" |
| 多轮追问 | `multi_turn` | 依赖上下文的追问 | "它的海拔最高点呢？" |
| 无答案/拒答 | `no_answer` | 语料中无相关证据 | "南京的GDP是多少？" |
| 混合意图 | `mixed_intent` | 中英混合或多意图查询 | "DSpark论文中Qwen3-4B提升了多少？" |

---

## 三、标注流程

### 3.1 准备阶段

1. 确定评测语料（源文档集合）
2. 通读所有源文档，建立内容索引
3. 确定每类查询的目标数量

### 3.2 编写查询

1. **覆盖原则**：每类查询至少 10 条，总量 80-150 条
2. **语言分布**：中文、英文、中英混合各占约 1/3
3. **难度分布**：easy / medium / hard 约为 4:4:2
4. **查询应自然**：模拟真实用户提问方式，避免过于形式化

### 3.3 标注相关来源

1. 逐条阅读查询，在源文档中定位相关段落
2. 记录 `relevant_source_ids`：包含答案的文档文件名
3. 记录 `relevant_chunks`：具体的相关段落信息
   - `source_id`：文档文件名
   - `chunk_text_snippet`：相关文本片段（前 100-200 字符）
   - `page`：页码（PDF 文档）
   - `section`：章节标题（如有）

### 3.4 标注答案要点

1. 提取回答该查询必须包含的关键事实
2. 每个要点应独立、原子化
3. 数值类答案标注精确值和可接受的近似表达
4. 列举类答案标注所有必须提及的项

**示例**：

查询："南京有哪些重要的河湖？"

```
acceptable_answer_points: ["长江", "秦淮河", "玄武湖", "莫愁湖"]
```

### 3.5 标注拒答

1. 如果语料中**完全没有**相关证据，标记 `should_refuse: true`
2. 拒答查询的 `relevant_source_ids` 和 `acceptable_answer_points` 必须为空
3. 拒答查询应覆盖：
   - 语料完全不涉及的主题（如"量子计算原理"）
   - 语料涉及但缺少具体数据的问题（如"南京的GDP"）
   - 需要实时信息的问题（如"今天天气"）

---

## 四、质量检查

### 4.1 自动验证

运行 `python -m evaluation.run --dataset v1 --validate-only` 检查：

- ID 唯一性
- `should_refuse=true` 但有相关来源（矛盾）
- `should_refuse=false` 但无答案要点（遗漏）
- 查询类型覆盖完整性

### 4.2 人工抽检

- 随机抽取 10% 用例，验证标注准确性
- 重点检查跨文档查询的相关来源是否完整
- 检查拒答查询是否确实无法从语料中找到答案

---

## 五、数据集划分

### 训练/holdout 划分

- 使用 `evaluation.schema.split_dataset()` 进行分层划分
- holdout 比例：12%（约 10-15 条）
- 划分按 `query_type` 分层，确保每类在 holdout 中有代表
- **调参只看训练子集，最终验收在 holdout 上跑**

### 版本管理

- 数据集文件：`evaluation/datasets/v1.jsonl`
- 版本号在 `evaluation.schema.SCHEMA_VERSION` 中维护
- 修改数据集时必须更新版本号

---

## 六、标注规范补充

### 多轮查询标注

多轮查询需要额外标注：

```json
{
  "metadata": {
    "turn": 2,
    "follow_up_to": "multi-001"
  }
}
```

- `turn`：当前是第几轮（从 1 开始）
- `follow_up_to`：上一轮的 case ID

### 难度定义

| 难度 | 标准 |
| --- | --- |
| easy | 答案在文档中直接陈述，无需推理 |
| medium | 需要跨段落整合或简单推理 |
| hard | 需要跨文档比较、多步推理或处理模糊信息 |

### 引用标注

对于需要引用验证的查询，在 `relevant_chunks` 中标注具体的 chunk 信息，以便后续引用评测使用。
