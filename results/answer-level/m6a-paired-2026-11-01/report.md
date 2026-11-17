# M6a 配对重放附录评测报告（2026-11-01）

- 协议：M6a paired replay addendum 2026-11-01（已签 Q2-a..d）
- 分支：eval/m6a-paired-2026-11-01（基线 746712d）
- 最终裁决：**INVALID**（一致性前置失败；不裁 C1/C2/C3；judge/al3 未运行）

## 1. C1/C2/C3 裁决

**未裁决**。任务书五.1「所有 context_chunk_ids_ordered 必须能解析，缺失即
停止」与五.5「任一断言失败 → 写 INVALID，停止，不跑 judge/al3」的停止条件
触发；按七「一致性…失败 → INVALID」，且禁止以部分结果裁决，C1/C2/C3 全部
不裁（值 = 未裁决，非 0/非 FAIL）。

## 2. INVALID 根因：chunk_id 域错位（机械复算证据）

- chunk store（data/v2-corpus/chunks/chunks.jsonl）：src.rag.get_splitter RecursiveCharacterTextSplitter size=2000 overlap=200（chunk-manifest.json，corpus v2.0.0，1006 chunks）。
- 运行时索引：运行时索引 section/切片切分（prepare_index，2947 chunks）。两者同用
  `{source_sha256_prefix12}_chunk_{n}` 格式，但 `_chunk_{n}` 序号空间
  语义不同（同 ID 异文）。
- 前置可解析性：150 例中
  **138 例**含 store 中不存在的
  context_chunk_ids_ordered（distinct 420 /
  920 个 ID 缺失；缺失编号恰为超出 store 各
  源上限的部分）。
- 同 ID 文本校验（折叠空白后 snippet ⊆ store 文本）：
  **0 /
  1877 吻合** —— 即使 ID 可解析也是同 ID 异文，
  不可用于重建 context。
- 真值域归属：dataset relevant_chunk_ids
  （113/113 全部在
  store 域内）→ 真值 = store 切分域，运行时 context = 另一套切分域。
- 任务书五.3 的 chunk store 文本仅对 store 域 ID 有意义；在域错位下重放会
  测错对象，故按契约停止。

## 3. 基线（唯一生成，已密封，验收闸全过）

- 150/150 有 full_sources 与 context_chunk_ids_ordered；cases_failed=0；
  无 [Generation error] 答案；capture on 的断言（S1..Sn 连续）全过。
- 新基线聚合：recall_avg=0.0656、
  precision_avg=0.0466、
  fabricated=0、
  retrieved_not_in_context=0
  （与 M4c 的 0.0456/0.0400 对比含运行间非确定性；且两值均受上述域错位
  影响，属域碰撞噪声，仅如实记录）。
- paired：**未裁决**（重放仅 12 例可解析且同 ID 异文，为不可用部分结果，
  不进任何裁决）。

## 4. C2 / G2′

**未计算**：answer judge 与 al3 两轮均未运行（INVALID 停止，0 LLM 调用）。

## 5. 槽位归因（add / retarget / delete）

仅 12 例部分重放的机械记录（不可用于裁决）：add=0、
retarget=7、
delete=0、
fail_closed=0。

## 6. 预算

- 口径：签批口径：生成 calls=150（1 生成调用/例）；judge/al3 未运行 0 调用；replay 0 LLM 调用。
- 生成 tokens=1177717（calls=150）；
  replay 0；judge 0；al3 0。
- 合计 tokens=1177717 / 上界 1500000；
  calls=150 / 上界 400；未触及预算上界。

## 7. 哈希与完整性

- M6a 冻结模块（git show 614e260:src/citation_selection.py）：
  ee9963c76cbf580238b5914a3b1a34d6265bdd66a5bdbfeb3523a457bccc1613
  （校验 通过）。
- src/ 相对 746712d 零改动：通过。
- 密封目录校验：

- baseline: ok=True
- judge: ok=True（未运行） problems=['未运行（目录不存在）']
- al3_round1: ok=True（未运行） problems=['未运行（目录不存在）']
- al3_round2: ok=True（未运行） problems=['未运行（目录不存在）']

- 产物清单与逐文件哈希：manifest.json（自哈希）。

## 8. 局限与阻塞

- **阻塞**：chunk store 与运行时索引切分域不一致（见 §2），无法在不改动
  产品/数据契约的前提下完成配对重放。可行的解阻方向（供签批方决策，本次
  未执行）：(a) 用与 store 相同的 splitter 重建评测侧离线 context 文本映射；
  (b) 由数据方提供 runtime 域 chunk 文本库；(c) 修订 addendum 的 chunk
  store 前提。
- 新基线不是 M4c 密封控制臂；本次未做任何补跑/重跑/换种子/改阈值。

## 9. 偏离与说明

- replay 脚本首轮在加载冻结模块时因 importlib 未注册 sys.modules 崩溃
  （发生在任何数据处理之前，0 产物）；修复 loader 后执行一次正式重放
  （确定性离线，0 LLM 调用），其 12 例部分产物仅存档为证据，不裁决。
- generation_runner 新增纯 stdout 预算监控行（[budget]），不改行为/产物。
- preflight 在任务书 B 清单外增加三个 fail-closed 前置闸（LLM 凭据、输出
  目录不存在、chunks 语料在），全过后生成。
- M4c manifest 哈希锚采用 manifest 自哈希口径（936d34bb…）。
- 问题清单：

- 离线重放一致性断言失败（见 consistency.json）
- 离线重放一致性前置失败（chunk store 无法解析全部 context_chunk_ids_ordered，缺失即停止，任务书五.1/五.5）
- judge/al3 未运行（INVALID 停止条件触发，0 LLM 调用）
