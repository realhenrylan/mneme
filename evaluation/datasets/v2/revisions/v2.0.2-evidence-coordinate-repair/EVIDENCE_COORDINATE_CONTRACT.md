# Evidence Coordinate Contract: `raw-codepoint-v1`

## Scope

本契约用于 v2.0.2 evidence 坐标迁移。v2.0.1 的 `char_range` 是在展示规范化文本上计算的 legacy 值，不得解释为原始 chunk 坐标。

## Canonical locator

- `coordinate_contract` 固定为 `raw-codepoint-v1`。
- `raw_chunk_char_range.start` 为 inclusive，`end` 为 exclusive。
- 坐标单位是 Python Unicode code point，直接作用于原始 `chunks.jsonl` 的 `text` 字符串；不是 UTF-8 byte offset，也不是规范化文本 offset。
- `raw_evidence_span` 必须满足 `chunk_text[start:end] == raw_evidence_span`，逐 Unicode code point 相等；chunk SHA 必须匹配输入快照。
- 只有唯一、连续、可重建的 raw span 才能迁移。缺 chunk、source 不一致、空值、越界、SHA 不自洽、重复匹配或无法证明的映射必须 fail-closed 并进入 `coordinate-unresolved.jsonl`。

## Display snippet

`snippet` 是展示字段，不承担定位职责。`snippet_normalization=display-whitespace-v1` 只把 CRLF、LF 和 Unicode whitespace run 显示为一个 ASCII 空格；保留 Markdown 标题、列表、表格、链接、inline/fenced code、代码内容、中文标点、大小写、顺序和全部语义字符。不删除格式标记，不重排、不拼接、不改写文本。

因此：raw range 是证据定位的唯一锚点；display snippet 只能由 raw span 确定性生成，不能反向猜测 raw range。

## Compatibility and migration

旧 `char_range` 作为 `legacy_char_range` 保存，仅用于审计。迁移产物新增 `raw_chunk_char_range`、`raw_evidence_span`、`coordinate_contract`、`snippet_normalization` 和 `mapping_algorithm_version`，不静默改变旧字段含义。原始 draft、chunks、答案点、query、case/source/chain 信息和机器审阅 decision 不修改。

任何 unresolved 条目都会阻断 v2.0.2 active；本版本只保留 candidate revision，不覆盖 active evidence，不生成 overlay，不进入 v2.1。只有 161/161 通过 strict validator 且 unresolved=0 才允许激活。

## Determinism

所有 JSONL 按稳定 case/chunk 顺序写出；manifest 的 `manifest_sha256` 对去除自身字段后的规范化 JSON（UTF-8、末尾 LF）计算。输出路径使用相对文件名，保证临时目录无关的逐字节确定性。
