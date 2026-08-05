# Mneme 评测语料 v2 标注模板（annotation template）

> 配合 `plans/CORPUS-EXPANSION-PLAN-2026-08-05.md` §4 使用。
> 本文件定义 v2 用例的 JSON 模板、逐字段填写指南、合法组合、
> 构造规则示例与审核记录格式。**只读设计，不实施。**

---

## 1. 模板总览

每条用例 = JSONL 一行。**v2 = v1 全部字段 + 增量字段**（增量字段对
新用例必填；旧用例缺省值兼容）。

```json
{
  "id": "{prefix}-{seq}",
  "query": "……",
  "query_type": "single_fact | metadata | mixed_intent | cross_document | multi_turn | no_answer",
  "language": "zh | en | mixed",
  "relevant_source_ids": ["文件名.pdf"],
  "relevant_chunks": [
    {
      "source_id": "文件名.pdf",
      "chunk_id": "{source_sha256_prefix}_chunk_{n}",
      "chunk_text_snippet": "前 100–200 字符……",
      "page": 3,
      "section": "2.3 调度机制"
    }
  ],
  "relevant_chunk_ids": ["{source_sha256_prefix}_chunk_{n}"],
  "acceptable_answer_points": ["必须包含的关键事实……"],
  "should_refuse": false,
  "relevance_level": "chunk",
  "metadata": {
    "difficulty": "easy | medium | hard",
    "band_target": "normal | low_answerable | low_refuse | near_band",
    "construction": "natural | fuzzy_query | cross_doc | follow_up | out_of_corpus | metadata",
    "turn": 1,
    "follow_up_to": null,
    "chain_id": null
  },
  "annotation": {
    "annotated_by": "zcode-draft",
    "reviewed_by": "",
    "review_status": "pending",
    "review_notes": "",
    "annotation_version": "v2.0.0",
    "created_at": "2026-08-06"
  }
}
```

---

## 2. 字段填写指南

### 2.1 基础字段（沿用 v1 语义）

| 字段 | 必填 | 说明 | 常见错误 |
|---|---|---|---|
| `id` | ✓ | `{prefix}-{seq}`，全池唯一；prefix 沿用 zh / en / mixed / cross / meta / multi / noanswer；seq 在冻结清单中登记 | 与旧用例重复编号 |
| `query` | ✓ | 自然语言提问，模拟真实用户，不抄文档原句（low_answerable/low_refuse 用 §3.4 构造规则） | 过于形式化；直接引用文档标题 |
| `query_type` | ✓ | 六类枚举 | 跨文档比较误标 single_fact |
| `language` | ✓ | 按 query 语言标注（与文档语言无关） | 中英混合 query 漏标 mixed |
| `relevant_source_ids` | ✓ | 含答案的文档**文件名**（与语料 manifest 一致）；no_answer 为 `[]` | 写文档 hash/路径 |
| `relevant_chunks` | chunk 级必填 | 每项含 `source_id` + `chunk_id` + `chunk_text_snippet` + `page` + `section` | snippet 非原文；chunk_id 拼错 |
| `acceptable_answer_points` | ✓ | 原子化关键事实；数值类标注精确值；no_answer 为 `[]` | 要点过粗（整句）；漏列举项 |
| `should_refuse` | ✓ | 语料中**完全无**相关证据才为 true | 证据弱≠无证据 |

### 2.2 v2 增量字段

| 字段 | 必填 | 说明 |
|---|---|---|
| `relevance_level` | 新用例 ✓ | `chunk` / `source` / `none`，与 §3 合法组合一致 |
| `relevant_chunks[].chunk_id` | chunk 级 ✓ | 必须存在于 v2 chunk manifest |
| `relevant_chunk_ids` | chunk 级 ✓ | 与 relevant_chunks 一一对应、顺序一致 |
| `metadata.difficulty` | 新用例 ✓ | 沿用 v1：easy 直接陈述 / medium 跨段整合 / hard 跨文档或多步推理 |
| `metadata.band_target` | 新用例 ✓ | 构造意图（§4.1），非分数承诺 |
| `metadata.construction` | 新用例 ✓ | 构造方式（§4.2） |
| `metadata.chain_id` | 链中用例 ✓ | 链头 case id；单例为 null |
| `annotation.*` | 新用例 ✓ | 审核状态机（§5） |

---

## 3. 合法组合（fail-closed）

| relevance_level | should_refuse | relevant_source_ids | relevant_chunk_ids | 答案点 |
|---|---|---|---|---|
| `none` | true | `[]` | `[]` | `[]` |
| `chunk` | false | 非空 | 非空（⊆ manifest，⊆ 对应 source） | 非空 |
| `source` | false | 非空 | `[]` | 非空 |

**source-only 判定红线**：只有"答案点不可可靠定位到具体 chunk"
（元数据类：页数/文件名/文档数；数量类：全文档分布统计）才允许；
能定位的一律 `chunk`；每条 source-only 必须在 `review_notes` 写理由；
新增用例 source-only ≤10%。

---

## 4. 构造规则（query 草稿阶段）

### 4.1 band_target

| band_target | 意图 | 构造手法 |
|---|---|---|
| `normal` | 常规难度 | 直接、规范提问 |
| `low_answerable` | 可答但检索难命中 | 模糊指代、多义词、间接表述、口语化 |
| `low_refuse` | 主题相近但无证据 | 跨文档捏造组合、"用 X 方法处理 Y 主题" |
| `near_band` | 可答但证据分散 | 跨段整合、总结类、限定词查询 |

### 4.2 construction

| 值 | 说明 | 示例 |
|---|---|---|
| `natural` | 自然提问 | "南京面积是多少？" |
| `fuzzy_query` | 模糊/多义/口语化（低分可答构造） | "那篇讲外泄防护的文章里提到的拦截办法" |
| `cross_doc` | 跨文档比较/整合 | "比较 DSpark 与 survey 对时空数据的处理差异" |
| `follow_up` | 多轮追问（链内） | "它的调度部分呢？"（指代前轮主题） |
| `out_of_corpus` | 语料外但主题相近（低分拒答构造） | "DSpark 论文里对 mobility 数据集的评测结论"（实际未评测） |
| `metadata` | 文档元数据/版本类 | "哪篇文档包含发布说明？" |

### 4.3 多轮链构造

- 整链一次标注；首轮 `turn=1, follow_up_to=null, chain_id={首轮 id}`；
  后续轮 `turn=n, follow_up_to={上一轮 id}, chain_id={首轮 id}`；
- 每轮必须可独立判定 `should_refuse` 与 `acceptable_answer_points`
  （评测按单轮运行）；
- 链内建议节奏：事实 → 追问 → 切换子主题 → （可选）拒答轮；
- 链长 2–5 轮；链内容不允许跨 split（见主方案 §5）。

---

## 5. 审核记录（review pack v2 行）

```json
{
  "case_id": "zh-047",
  "query": "……",
  "query_type": "single_fact",
  "language": "zh",
  "annotated_fields": { "relevant_source_ids": ["…"], "relevance_level": "chunk", "…": "…" },
  "review_decision": "approved | revise | reject",
  "reviewer_notes": "理由（revise/reject 必填；source-only 必填）"
}
```

- `approved`：无需修改；`revise`：附修改意见后重标；`reject`：重写或剔除；
- 链内用例按链分组呈现；链中任一用例未 approved → 整链不锁定；
- 导出/导入沿用现有 `review_apply` fail-closed 语义（manifest SHA、
  行数、键集、必填值）。

---

## 6. 完整示例

### 6.1 chunk 级（正常可答）

```json
{
  "id": "zh-047",
  "query": "南京城市地理环境资料中记载的湖泊面积最大的是哪一个？",
  "query_type": "single_fact",
  "language": "zh",
  "relevant_source_ids": ["南京城市地理环境.docx"],
  "relevant_chunks": [
    {
      "source_id": "南京城市地理环境.docx",
      "chunk_id": "d8fa2a45c996_chunk_3",
      "chunk_text_snippet": "玄武湖面积3.78平方公里，是全市最大湖泊……",
      "page": null,
      "section": "水系"
    }
  ],
  "relevant_chunk_ids": ["d8fa2a45c996_chunk_3"],
  "acceptable_answer_points": ["玄武湖", "面积3.78平方公里"],
  "should_refuse": false,
  "relevance_level": "chunk",
  "metadata": {
    "difficulty": "medium",
    "band_target": "normal",
    "construction": "natural",
    "turn": 1,
    "follow_up_to": null,
    "chain_id": null
  },
  "annotation": {
    "annotated_by": "zcode-draft",
    "reviewed_by": "",
    "review_status": "pending",
    "review_notes": "",
    "annotation_version": "v2.0.0",
    "created_at": "2026-08-06"
  }
}
```

### 6.2 source-only（元数据类，需理由）

```json
{
  "id": "meta-040",
  "query": "语料中一共有几篇英文论文？",
  "query_type": "metadata",
  "language": "en",
  "relevant_source_ids": ["DSpark_paper.pdf", "2405.02357v2.pdf", "prevent-url-data-exfil.pdf"],
  "relevant_chunks": [],
  "relevant_chunk_ids": [],
  "acceptable_answer_points": ["3"],
  "should_refuse": false,
  "relevance_level": "source",
  "metadata": {
    "difficulty": "easy",
    "band_target": "normal",
    "construction": "metadata",
    "turn": 1,
    "follow_up_to": null,
    "chain_id": null
  },
  "annotation": {
    "annotated_by": "zcode-draft",
    "reviewed_by": "",
    "review_status": "pending",
    "review_notes": "答案点（文档计数）分布于整库，无单一 chunk 可承载；按 source-only 标注。",
    "annotation_version": "v2.0.0",
    "created_at": "2026-08-06"
  }
}
```

### 6.3 低分拒答构造（no_answer）

```json
{
  "id": "noanswer-056",
  "query": "DSpark 论文对 mobility 数据集的评测结论是什么？",
  "query_type": "no_answer",
  "language": "en",
  "relevant_source_ids": [],
  "relevant_chunks": [],
  "relevant_chunk_ids": [],
  "acceptable_answer_points": [],
  "should_refuse": true,
  "relevance_level": "none",
  "metadata": {
    "difficulty": "hard",
    "band_target": "low_refuse",
    "construction": "out_of_corpus",
    "turn": 1,
    "follow_up_to": null,
    "chain_id": null
  },
  "annotation": {
    "annotated_by": "zcode-draft",
    "reviewed_by": "",
    "review_status": "pending",
    "review_notes": "DSpark 论文未评测 mobility 数据集；主题相近诱导检索但证据缺失。",
    "annotation_version": "v2.0.0",
    "created_at": "2026-08-06"
  }
}
```

### 6.4 多轮链（第 2 轮）

```json
{
  "id": "multi-035",
  "query": "那它的调度部分是怎么设计的？",
  "query_type": "multi_turn",
  "language": "en",
  "relevant_source_ids": ["DSpark_paper.pdf"],
  "relevant_chunks": [
    {
      "source_id": "DSpark_paper.pdf",
      "chunk_id": "3be83454b299_chunk_157",
      "chunk_text_snippet": "The scheduler assigns …",
      "page": 6,
      "section": "4 Scheduling"
    }
  ],
  "relevant_chunk_ids": ["3be83454b299_chunk_157"],
  "acceptable_answer_points": ["scheduler 按优先级分配"],
  "should_refuse": false,
  "relevance_level": "chunk",
  "metadata": {
    "difficulty": "medium",
    "band_target": "normal",
    "construction": "follow_up",
    "turn": 2,
    "follow_up_to": "multi-034",
    "chain_id": "multi-034"
  },
  "annotation": {
    "annotated_by": "zcode-draft",
    "reviewed_by": "",
    "review_status": "pending",
    "review_notes": "",
    "annotation_version": "v2.0.0",
    "created_at": "2026-08-06"
  }
}
```

---

## 7. 校验清单（入库前自动检查）

- [ ] id 唯一且已登记于 case-freeze 清单
- [ ] 六类 query_type 全部覆盖；语言/难度分布符合 §3.3 目标
- [ ] 合法组合表全部成立（§3）
- [ ] chunk_id 存在于 chunk manifest 且属于对应 source
- [ ] no_answer：relevant_* 与答案点全空；其余类型：答案点非空
- [ ] 链完整性：follow_up_to 引用存在、turn 连续、chain_id 一致
- [ ] source-only ≤10% 且每条有 review_notes
- [ ] annotation.review_status = approved（终审后）
