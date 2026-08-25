# REPAIR_REPORT.md — v2.0.8 owner-authorized semantic-quality remediation

> owner-authorized candidate（链安全版）：不是人工审核、不是 active 版本、
> 不是 overlay、不是 v2.1 准入。确定性构建，无 LLM/API、无联网。

## 门禁（fail-closed，全部通过）
- v2.0.7 candidate = 148 cases；strict raw-codepoint-v1 evidence 161/161
- legacy = 0；unresolved = 0
- automated review = 126 confirmed / 22 reject / 0 needs_followup
- decision pack 覆盖 reject 22 条；五批次分布恰为 7 / 1 / 3 / 10 / 1；无 overlay
- 链依赖门禁：multi-030 依赖结构 == 授权 defer 依据（multi-031 follow_up_to / multi-032/033/034 chain_id），无漂移
- 退役依赖门禁通过（en-044 / en-050 / mixed-026 / zh-042 / zh-045 无任何 follow-up / chain / doc_target / case 引用依赖）

## 变更总览
- case：148 → 143（退役 5 条；延后 1 条）
- evidence：161 → 151
- 替换答案点（批次 A）：7 条；scope 扩展（批次 B）：1 条；翻译等价策略（批次 C）：3 条；
  移除答案点（批次 D）：4 条；退役（批次 D）：5 条；延后（multi-030）；定向盲态复审（批次 E）：mixed-027（单独步骤）

## 批次明细
### 批次 A — replace_answer_point_with_self_contained_exact_raw_text（7 条）
- `mixed-028`：答案点替换为 `5927c70d0f8e_chunk_0 {'end': 760, 'start': 567}`（`Combined with the reactivity system, Vue can intelligently f…`）；旧 token evidence 清理，新 raw-codepoint-v1 evidence 写入
- `mixed-029`：答案点替换为 `c9fd20815ea8_chunk_10 {'end': 1417, 'start': 1371}`（`CPython 没有一致应用针对迭代器定义
```
__iter__()
```
 的要求。…`）；旧 token evidence 清理，新 raw-codepoint-v1 evidence 写入
- `zh-023`：答案点替换为 `32c427fb50e2_chunk_10 {'end': 327, 'start': 262}`（`生成的序列绝不会包括给定的终止值；
```
range(10)
```
 生成 10 个值——长度为 10 的序列的所有…`）；旧 token evidence 清理，新 raw-codepoint-v1 evidence 写入
- `zh-026`：答案点替换为 `32c427fb50e2_chunk_22 {'end': 422, 'start': 400}`（`类似于
```
del a[:]
```
。…`）；旧 token evidence 清理，新 raw-codepoint-v1 evidence 写入
- `zh-029`：答案点替换为 `32c427fb50e2_chunk_45 {'end': 59, 'start': 14}`（````
json
```
 保存结构化数据¶
 字符串可以很容易地写入文件或从文件中读取。…`）；旧 token evidence 清理，新 raw-codepoint-v1 evidence 写入
- `zh-036`：答案点替换为 `32c427fb50e2_chunk_31 {'end': 1584, 'start': 1519}`（`如果未找到，它将在变量
```
sys.path
```
 所给出的目录列表中搜索名为
```
spam.py
```
…`）；旧 token evidence 清理，新 raw-codepoint-v1 evidence 写入
- `zh-054`：答案点替换为 `c9fd20815ea8_chunk_10 {'end': 1417, 'start': 1371}`（`CPython 没有一致应用针对迭代器定义
```
__iter__()
```
 的要求。…`）；旧 token evidence 清理，新 raw-codepoint-v1 evidence 写入
### 批次 B — expand_same_source_evidence_scope（1 条）
- `zh-040`：答案点不变；追加两条已验证 TOC evidence （`OWNER_AUTHORIZED_SAME_SOURCE_EVIDENCE_SCOPE_EXPANSION`）：`32c427fb50e2_chunk_1 {'end': 192, 'start': 182}`；`32c427fb50e2_chunk_1 {'end': 370, 'start': 360}`
### 批次 C — faithful_translation_equivalence_v1（3 条）
- `en-029`、`multi-019`、`zh-052`：策略文件 + 恰 3 条 ledger；不是自动 confirmed，后续仍需盲态复审
### 批次 D — 移除 unsupported 答案点（4 条）
- `en-042`：移除答案点 [{'answer_point_index': 0, 'answer_point': 'RFC 3986 defines generic URI syntax'}]；剩余 ['Node.js fs accepts file URL paths']
- `en-049`：移除答案点 [{'answer_point_index': 0, 'answer_point': 'Rust: String type owns heap memory'}]；剩余 ['SQLite: TEXT affinity for string columns']
- `en-051`：移除答案点 [{'answer_point_index': 0, 'answer_point': 'Python: lists as mutable sequences'}]；剩余 ['SQLite: SELECT returns rows with a fixed number of columns']
- `mixed-033`：移除答案点 [{'answer_point_index': 0, 'answer_point': 'static type checker 是查找类型问题的外部工具'}]；剩余 ['stdlib 是标准库（standard library）的缩写']
### 批次 D — 退役（5 条）
- 退役：en-044, en-050, mixed-026, zh-042, zh-045；固定原因 `no_semantically_sufficient_direct_evidence_after_owner_authorized_review`
- retired-cases = 5 条；retired-evidence = 9 条
### 批次 D — 延后（1 条，multi-030）
- `multi-030` 是 multi-031~034 的多轮链父节点，禁止单独退役：不修改其 draft/答案点/evidence/source-chunk 关系，不退役，不改 follow_up_to / chain_id 或任何子节点
- 延后原因：`retirement_deferred_due_to_active_follow_up_chain_dependency`；依赖 case：multi-031（follow_up_to）、multi-032/033/034（chain_id）
- 已写入 `deferred-chain-dependent-cases.jsonl`；manifest/report 明确这不是 resolved / confirmed / 已接受的质量结论，处置需所有者后续决策
### 批次 E — 定向盲态复审（1 条）
- `mixed-027`：candidate 数据不改动；单独执行 `review-targeted` 步骤（deepseek-v4-pro，Pro-only 契约）；结果仅诊断，失败标 `TARGETED_REVIEW_BLOCKED`，不生成 overlay、不改变 case 数据

## 严格验收
- 仅授权目标变更；非目标 draft/evidence 行逐字节不变（含 multi-030 与其链依赖 case multi-031~034）；case 唯一 143；保留 case 无零答案点
- evidence-after 151 行全部通过 raw-codepoint-v1 strict validator；所有 raw span 可重建
- 无 legacy / unresolved 残留；无 overlay / active / split / locked config / v2.1 产物
- manifest 自哈希与磁盘 SHA 一致；两次确定性构建逐字节一致

## SHA（关键输入）
- decision pack manifest：DECISION_PACK_OK
- v2.0.7 candidate manifest：`33a95a30e4632961…`

## 声明
- 未调用 LLM/API、未联网（批次 E 定向复审为单独的用户授权步骤）
- 未读取历史审阅结论、split/dev/holdout、锁配置或评测结果
- 未 stage / commit / push
