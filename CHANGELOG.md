# Mneme Changelog

All notable changes to the Mneme project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [Unreleased]

### Fixed

- **v2 机器审阅副本严格导入（LLM_REVIEWED_DIAGNOSTIC_ONLY 诊断路径，TDD：41 个新测试）** — 新增 `scripts/corpus_v2_llm_review_apply.py`（apply / verify 两个子命令），处理其他会话产生的机器填写副本（`human-review-pack.llm-filled.jsonl`，reviewer=`LLM_ASSISTED_THIRD_PASS`）；**不调用任何 LLM/API**、不联网、不运行检索、生成评测、特征/阈值扫描：
  - **复用而非复制**：将 `corpus_v2_human_review_apply.py` 的校验逻辑抽取为共享函数（`_manifest_input_errors` / `_rebuild_original_pack` / `_evidence_errors`），LLM 路径直接复用（manifest 五类输入 SHA 复算、确定性重建 SHA 链、chunk/snippet/source 证据映射）；**绝不调用或改写其 HUMAN_REVIEWED 分支**（行为不变，原 28 测试保持绿）
  - **机器填写副本额外契约**：reviewer 必须非空且以 `LLM_ASSISTED_` 开头；reject / needs_followup 必须附 notes；空白 pack 文件 SHA 必须等于 manifest pack_sha256 且三个人工字段仍全空；third-pass manifest（total_cases / confirmed / reject / needs_followup / non_confirmed 集合与逐条 decision）与 report（头部统计 + 逐 case 清单统计）必须与填写副本复算一致；manifest 声明 `{path, sha256}` 条目则复算（当前 third-pass manifest 未声明 SHA 字段，工具自身产物 manifest 记录完整输入/输出 SHA-256 链）
  - **fail-closed 三分支**：① 任何非法状态（行数/键集/篡改/证据/统计漂移/空白包被填写）→ 整体失败且零输出；② 存在 reject / needs_followup → 只输出 `llm-review-issues.jsonl` + `llm-review-issues-report.md`，零 overlay；③ 仅 150/150 confirmed → 生成 `evaluation/datasets/v2/llm-reviewed-truth/llm-reviewed-truth-overlay.json`（status=`LLM_REVIEWED_DIAGNOSTIC_ONLY`、reviewer_type=`LLM`）+ manifest；产物与输出中**不得出现** `HUMAN_REVIEWED` / `HUMAN_APPROVED` / 上线批准 / 已完成人工审核 / 人工批准字样（fail-closed 扫描）
  - **真实运行**：机器填写副本核验通过（150 行、case_id 集合与空白包一致、非人工字段逐行规范化一致、68 confirmed / 82 reject / 0 needs_followup、82 条 reject 全部附 notes）→ 真实 apply 输出 issues 清单（82 条 blocked，零 overlay），两次运行逐字节一致；空白包 SHA 前后不变（`ceab00700da1…`）、人工字段全空；`llm-reviewed-truth/` 目录未创建
  - **结论**：该结果**不是人工终审，不能单独解除 v2.1 人工门槛**；不得自动进入 v2.1；待真人逐条填写空白包后另行人工导入；其他会话的 3 个 LLM 文件未暂存、未触碰

- **v2 人工终审结果严格导入（HUMAN_REVIEWED overlay，TDD：28 个新测试）** — 新增 `scripts/corpus_v2_human_review_apply.py`（apply / verify 两个子命令），导入人工填写后的审阅 pack（`human_review_decision` ∈ confirmed/reject/needs_followup、`human_reviewer` 非空）；**不调用任何 LLM/API**，不运行检索、生成评测、特征/阈值扫描：
  - **严格校验**：恰好 150 行（= pack manifest n_cases）、case_id 集合与原始 pack 一致、键集不增不减（行键 / evidence 键白名单）、除三个人工字段外每行与原始 pack 规范化 JSON 逐字段一致（任何篡改 → 失败）；证据引用重新映射到 chunks.jsonl（chunk 存在、snippet 连续、source 一致）
  - **fail-closed 三分支**：① 任一空/非法 decision、空 reviewer、重复/缺失/未知 case、篡改字段或证据、输入 SHA 漂移、原始 pack 重建不一致 → **整体失败且零输出**；② 任一 reject / needs_followup → 只输出 `human-review-issues.jsonl` + `human-review-issues-report.md`（问题清单），**绝不生成可用于评测的正式 overlay**；③ 仅 150/150 confirmed → 生成独立、确定性 `human-reviewed-truth-overlay.json`（status=`HUMAN_REVIEWED`，每 case 真值 + reviewer，按 case_id 排序）+ `human-reviewed-truth-overlay-manifest.json`（decision_counts / reviewers / 输入 SHA 链 / overlay_sha256）
  - **SHA 链与输入不可变性**：apply 前复算 pack manifest 记录的五类输入（draft / chunks / chunk_manifest / corpus_manifest / repair_ledger）SHA-256；用这些输入**确定性重建原始 pack**，重建 SHA 必须等于 manifest 的 pack_sha256；`verify` 子命令对既有 overlay 复检（overlay sha、全部文件类输入 sha、结构、decision_counts 与已填写 pack 复算一致）
  - **不伪称批准**：产物如实记录 `HUMAN_REVIEWED`，绝不自动宣称上线批准、不自动进入 v2.1；overlay 是独立产物，不改写 v2 草稿 / chunks / corpus manifest / case-freeze / split-lock / 生产配置；产物无时间戳，两次 apply 逐字节一致
  - **真实状态**：当前 `human-review-pack.jsonl` 人工字段仍全部为空（尚未人工填写）→ 真实目录 apply 正确拒绝（exit 2、零输出、未生成 overlay）；confirmed / issues / 非法三路径由合成 fixture 覆盖，真实语料 150 条全 confirmed 演练（tmp 目录）生成 overlay 且 verify 通过；`human-review/` 目录内另有其他会话产生的 3 个文件（`human-review-pack.llm-filled.jsonl` / `llm-third-pass-manifest.json` / `llm-third-pass-report.md`），非本任务产物，未暂存、未触碰
  - 验证：定向 28 测试 + 完整 pytest **1064 passed / 7 skipped**；py_compile OK；git diff --check exit 0；未修改任何既有输入；未 commit / push

- **v2 人工终审包准备（盲态、离线、fail-closed，TDD：28 个新测试）** — 生成可由真人逐条填写的人工终审包；**不调用任何 LLM/API**，不运行检索、生成评测、特征/阈值扫描；不修改任何 v2 草稿 / chunks / 语料 / manifest / case-freeze / split-lock 或生产配置：
  - 新增 `scripts/corpus_v2_human_review_pack.py`（build / verify 两个子命令），产物目录固定 `evaluation/datasets/v2/human-review/`：
    - `human-review-pack.jsonl`：必须恰好 150 行、按 case_id 稳定排序；每行只含 case_id / query / language / query_type / previous_turns（多轮链回溯，单轮为空）/ should_refuse / relevance_level / acceptable_answer_points / relevant_source_ids / evidence（每条 = source_id / chunk_id / 完整连续 snippet / section）/ 空白人工字段 human_review_decision / human_reviewer / human_review_notes
    - **盲态**：行键与证据键为严格白名单（多出任何键即失败）；包内绝不含自动二审 decision / confidence / rationale / 审阅模型名 / 修复 action / 任何 split/dev/holdout 身份 / 检索分数 / 候选集 / 历史评测结果——正则扫描禁止这些结构键（JSON 键形态，排除转义引号）+ 禁止字样（`HUMAN_APPROVED` / `reviewed-truth` / "已完成人工审核"）
    - `human-review-pack-manifest.json`：记录草稿、chunks、chunk-manifest、corpus-manifest、repair-ledger 五类输入 SHA-256 + pack_sha256（无时间戳，确定性）
    - `HUMAN_REVIEW_INSTRUCTIONS.md`：中文填写说明——confirmed（问题、答案点、拒答判定和所有证据都正确）/ reject（存在事实、证据、来源或拒答错误）/ needs_followup（人工无法确定，需补充来源或证据）；只填三个人工字段、答案点须有连续 snippet 支持、拒答行核对本地语料不可回答性、跨文档断言须各有证据、不得为凑 150 条 confirmed 放宽标准
    - `human-review-pack-report.md`：仅全量计数（条数 / relevance_level / should_refuse / language / query_type / 多轮行数 / 证据条目数）+ 字段说明 + 输入 SHA-256，不含任何 split 或评测指标
  - fail-closed：行数 150、case_id 唯一且与草稿集合完全一致；answerable 的 chunk 证据必须存在于 chunks.jsonl（source 与 chunk 归属一致）、snippet 连续（`snippet_is_evidence`）；人工字段初始必须全部为空（任何已填值 → 失败）；manifest 输入 SHA 漂移、缺失 chunk、重复/遗漏 case、非法字段、split 结构字段、禁止字样 → 一律失败；两次生成逐字节一致（真实语料验证）
  - `verify`：对既有产物重跑全部 fail-closed 校验（输入 SHA 复算、pack sha、行数/唯一/排序、键白名单、人工字段空、previous_turns 与草稿链一致、证据存在性与连续性、禁止字样/结构键）
  - 产物 SHA：draft `e289d1f0cff5…`、chunks `a23d739aa987…`、chunk_manifest `de5a580bac32…`、corpus_manifest `84f04699c07f…`、repair_ledger `c13235dfa65d…`、pack `ceab00700da1…`；150 行全量核验通过、与真实语料两次构建逐字节一致
  - 状态：人工终审包已准备，**尚未进行人工终审**（不伪称人工审核）；仅当 150 条均由真人填写后，才可另行讨论导入人工审阅结果，**仍不得进入 v2.1**；未修改草稿 / chunks / split；未 commit / push

- **v2 标注修复闭环（证据优先最小修复，TDD：19 个新测试）** — 对二审（LLM_ASSISTED_SECOND_PASS）flag 出的 10 条异常草稿（en-038 / en-040 / en-043 / en-046 / en-047 / mixed-025 / mixed-030 / mixed-032 / zh-050 / zh-059）执行证据驱动修复并全量重跑 150 条二审：
  - 新增 `scripts/corpus_v2_repair.py`（validate / report 两个子命令）——确定性 fail-closed 修复验证器：
    - ledger 的 case 集合必须**恰好**等于 10 条目标（缺少 / 多余 / 非法 action / 缺字段 → 失败）；每条 evidence 的 snippet SHA-256 必须与草稿 `chunk_text_snippet` 复算一致且是连续证据（`snippet_is_evidence`），ledger 证据必须恰好覆盖草稿中的全部证据
    - 10 条之外的非目标行必须与旧草稿逐行不变（字节级 JSON 相等）；150 条保持唯一、schema 合法（必需键 / relevance_level 枚举 / relevant_chunk_ids 与 relevant_chunks 一致）
    - annotation 必须保持 `LLM_ASSISTED` / `pending`（review_status=pending、reviewed_by 空、review_notes 含 LLM_ASSISTED），整行 JSON 出现 HUMAN/HUMAN_APPROVED 声明 → 失败；answerable 行必须非空证据；`changed_to_refusal` 只允许 `should_refuse=True` + `relevance_level="none"` 语义
    - `report`：生成 `repair-evidence-report.md`（逐条修复判定 + 证据 SHA 明细 + 全量二审汇总，不按 split）+ `repair-manifest.json`（旧/新草稿、chunks、ledger SHA-256 + 产物 SHA）
  - 修复判定（10 条全部 `corrected`，1 条真值不变）：
    - en-038：答案点不变，证据由章节标题替换为目录（3.2 Views / 3.3 Foreign Keys / 3.4 Transactions）与第 3 章正文
    - en-040：补齐 SQLite 完整语法图（begin/commit/rollback-stmt）与 PG Transactions 小节 BEGIN/COMMIT/ROLLBACK 原文
    - en-043：删除无证据的 PG 否定点，答案收缩为 SQLite 正面证据结论
    - en-046：source-only → chunk 级，补齐 f.write(string) / filehandle.write / fsPromises.writeFile 证据
    - en-047 / mixed-032：原"PG 第 2 章未收录 JOIN"与目录（2.6 Joins Between Tables）矛盾，更正为目录证据；SQLite 补齐 LEFT/RIGHT/FULL 操作符片段
    - mixed-025：source-only → chunk 级，头部编者栏证据（Adam Turner 和 Thomas Wouters）
    - mixed-030：删除无证据的"类是可复用代码单元"，改为 9. 类章节与 React Intro 直接表述
    - zh-050：原"未列出 datetime 变更"与文档实际内容矛盾，修正为弃用章节（utcnow / utcfromtimestamp）与 copy.replace 支持 datetime 类型
    - zh-059：`retained_after_evidence_check`——chunk 原文含"# 6. 模块¶"，答案正确，不改真值，仅扩展 snippet
  - 修复后重建 evidence-review pack（新草稿 SHA，evidence 146 → 158）并全量重跑 150 条 deepseek-chat 二审（禁止 gpt-5.6-sol；身份固定 LLM_ASSISTED_SECOND_PASS），fail-closed verify 通过
  - 产物：`evaluation/datasets/v2/review/` 下 `repair-ledger.jsonl`、`repair-evidence-report.md`、`repair-manifest.json` 与重建后的 pack / auto-review 全套；不生成正式 reviewed-truth overlay，不改生产配置，不运行检索 / 特征扫描 / 阈值选择 / 生成评测，不读取或输出 dev/holdout/split 身份；不 commit、不 push

- **v2 证据驱动二次审阅（LLM_ASSISTED_SECOND_PASS，TDD：17 个新测试）** — 对 150 条 LLM_ASSISTED 草稿执行独立二审，自动发现错误问答真值 / 拒答标签 / source-only 判断 / 多轮链关系，绝不伪称人工审核：
  - 新增 `scripts/corpus_v2_review.py`（pack / review / verify 三个子命令）：
    - `pack`：离线、确定性构建 evidence-review pack（150 条：query + previous-turn 上下文 + 草稿标签 + source/chunk 原文证据（snippet + 完整 chunk 文本）+ 每条 evidence SHA-256）；不含任何 split / dev / holdout / 检索分数 / 候选集字段；输入草稿与语料 SHA-256 写入 manifest；chunk 缺失、snippet 非连续证据、多轮链结构断裂（follow_up_to 缺失 / turn 不连续 / chain_id 不一致）、重复 case id → fail-closed 立即失败
    - `review`：按 case_id 逐条调用独立审阅 LLM（temperature=0.0；模型取自 `LLM_MODEL`，默认 `deepseek-chat`，**代码级禁止 gpt-5.6-sol**；审阅人身份固定 `LLM_ASSISTED_SECOND_PASS`），逐项核验 answerable/refusal、chunk/source 相关性、snippet 充分性、多轮 parent/turn 关系；输出 confirmed / reject / needs_followup + 置信度 + 结构化理由 + 问题类别；LLM 输出非法（不可解析 / 非法值 / 调用失败）→ 整体失败且不产出产物
    - `verify`：fail-closed 重校验——草稿 / chunks SHA 漂移、pack 被篡改、evidence SHA 复算不一致、case 重复/遗漏、reviewer 身份伪装 → 立即失败
  - 审计产物：`evaluation/datasets/v2/review/` 下 `auto-review.jsonl`（150 条）、`auto-review-evidence-report.md`（全量汇总：confirmed/reject/needs_followup 数量、草稿与二审一致率、置信度分布、问题类别分布、待修复清单；**不按 split 分析**）、`auto-review-fixlist.jsonl`（仅 reject/needs_followup 时生成）、`auto-review-manifest.json`
  - fail-closed 门槛：全部 150 条 confirmed 才输出 "LLM-assisted candidate review complete" 结论，且仍为 LLM_ASSISTED 状态、未经人工批准；reject / needs_followup 不自动篡改草稿，仅输出待修复清单
  - 约束：只读审阅——不修改 v2 原始草稿 / chunks / manifest / case-freeze / split-lock；不生成正式 reviewed-truth overlay；不改生产配置；不运行检索、特征扫描、alpha/阈值选择、LLM 生成评测；新产物单独暂存，不提交、不 push

- **v2 语料暂存包 Windows 可验证性修复（TDD：6 个新测试）** — 解决暂存区 whitespace 检查失败（`git diff --cached --check` exit 2）与许可证审计脚本在 Windows 默认 GBK 控制台崩溃：
  - 新增最小范围 `.gitattributes`：仅对 `data/v2-corpus/documents/**` 与 `data/v2-corpus/attribution/licenses/**` 关闭 whitespace 检查——原始下载文档与许可证证据必须与上游逐字节一致，尾随空白 / tab 属于原文内容，禁止为消除检查错误而改写；代码、JSONL、标注、manifest 一律不豁免；`git diff --cached --check` 恢复 exit 0
  - `scripts/corpus_v2_licenses.py`：成功输出改为纯 ASCII（`↔` 仅保留于以 UTF-8 显式写出的 markdown 报告），Windows 默认 GBK/cp936 控制台下不再抛 `UnicodeEncodeError`，不依赖用户设置 `PYTHONIOENCODING`
  - 新测试：`tests/test_corpus_v2_gitattributes.py`（豁免范围最小性——pattern 集合必须且仅是这两个目录树、每行仅 `-whitespace`；代表性 raw HTML / `_parts` / processed / 许可证文件 attribute 为 `unset`；范围外代码 / JSONL / manifest / attribution / CHANGELOG 保持 `unspecified`；`git diff --cached --check` exit 0）+ `tests/test_corpus_v2_licenses.py::test_cli_exit0_under_gbk_stdout_encoding`（`PYTHONIOENCODING=gbk` 子进程：exit 0、无 UnicodeEncodeError、成功输出可被 ASCII 严格解码）
  - 约束：未改写任何原始下载文档 / 许可证证据 / 标注 / split / chunk 内容；未触碰生产逻辑；不提交，仅补充暂存

- **group-aware split 跨进程不确定性永久修复（TDD：11 个新测试）** — `evaluation/compare.py::group_aware_split` 把 `set(chain_root_ids)` 直接转 list 后 shuffle，set 迭代顺序随 PYTHONHASHSEED 变化 → 同一 `--seed=42` 在不同进程得到不同 dev/holdout（旧实现实测：seed=1 的 holdout 为 multi-004/005/006 链，seed=0/42 为 multi-007/008/009/010 链）；此前仅用 `PYTHONHASHSEED=0` 运行绕过，非永久修复：
  - `group_aware_split`：chain root 分配前稳定排序（`sorted(chain_root_ids)`）再 `Random(seed)` shuffle、chain 遍历改 `sorted(chains.items())`、最终 dev/holdout 输出按 case_id 稳定排序 → 结果 JSONL / review pack / 锁配置可复现，**不依赖也不要求 PYTHONHASHSEED**；`--seed` 公开语义不变
  - 新增 `compute_split_fingerprint`（dev/holdout canonical case_id 列表的 SHA-256）：`evaluation/locked_config.py::build_locked_config` 新必填参数 `split_fingerprint`（新锁必须锁定 split，缺省/坏格式 ValueError）；`load_locked_config` 存在时校验格式、旧锁无该键向后兼容加载；`validate_locked_config` 新参数 `split_fingerprint`（锁已锁定时运行时不可得/不等 → fail-closed 拒绝）；`compare.main()` 在索引/LLM/QueryPlan 前校验当前 split 指纹（--config 预检）并在 --lock 生成时写入锁
  - 新测试：`tests/test_compare.py::TestGroupAwareSplitHashSeedDeterminism`（≥3 个不同 PYTHONHASHSEED 独立子进程断言 case_id 集合与顺序完全一致 + 输出稳定排序 + 指纹确定性/敏感性）+ `TestSplitFingerprint`（4 个）；`tests/test_locked_config.py::TestSplitFingerprintLocking`（build 必填/坏格式、load legacy 兼容、validate 匹配/漂移/不可得拒绝，6 个）+ CLI `test_holdout_split_fingerprint_mismatch_rejected_before_index`（伪造指纹在索引前拒绝）
  - **旧候选结果作废声明**：`production-baseline-20260804T2220/candidate-report.md` 的 dev 94/holdout 16 指标基于已作废拆分；修复后稳定 split 为 dev 95/holdout 15（split 指纹 `454892e4b9968e9ed85807b605fc6fffe920dd1aa3a665c29f8235eafeaa3690`）；正式基线需在新锁定指纹下重跑评测（本次约束：不重跑、不调用 LLM/API）
  - 稳定 split 重建产物：`results/graph-gate/stable-split-rebuild-20260804T234043/`（split-manifest.json、per-split ground-truth-map、review pack 导出/迁移（25 confirmed 全部回填 + 4 source-only 保留；2 reject 保留于 canonical pack 历史记录）、双 overlay（dev 21 confirmed + 4 source-only / holdout 4 confirmed + 4 source-only）、`lock-production-stable.json`（固定字段与历史锁逐字段一致 + split_fingerprint）、`verify_truth_integrity.py` PASS、`stable-split-addendum.md`（**事实修正：25 条 overlap 决策为 LLM 辅助审阅、非人工签署；guardrail 阈值建议仍待人工批准**））
  - 约束：不改写任何历史 results / decision-report.md / 原 candidate-report.md；不 stage/commit；未自动启用 Graph/reranker

- **Citation 评测语义修复（契约 v2：context-supported 引用有效性）** — 修复引用指标使用占位输入（`all_retrieved_ids=set()`、`context=""`）导致的失真：旧口径无法回答"答案引用的证据是否真的进入最终 LLM prompt context"：
  - `evaluation/citation_metrics.py`：新增契约 v2 入口 `evaluate_citations_context_aware()`（fail-closed：sources/context_chunk_ids/context_source_ids/candidate_chunk_ids/chunk_to_source/context_text 任一缺失抛 `ValueError`，禁止静默产出"有效/无效"指标；空列表/空串是真实空，合法）与 `parse_sources_citation_map()`（解析 `format_sources` 输出 → S#→chunk 权威映射，逐行确定性、首现保留、无 chunk_id 行跳过）
  - 三层语义显式区分：`citation_id_validity`（旧字段保留 = retrieval-level visible：引用 ID 在 sources 展示集中）、`context_supported_citation_validity`（新正式 guardrail 指标：引用 chunk ∈ context_chunk_ids → supported_chunk，或 chunk 的 source ∈ context_source_ids → supported_source）、最终答案引用有效性 = context-supported 层；`CitationEvidence` 逐引用记录判定状态（可审计）
  - 确定性处理：重复引用按唯一 ID 计一次；空引用 validity=0.0；幻觉/不可映射 → `fabricated`；候选池可见但未进 context → `retrieved_not_in_context`；多引用按 ID 数字升序逐条判定；source 口径与已修复的 source recall 一致（`_source_label_from_meta` source_name 优先，禁止 filename/hash 混用）
  - `citation_precision`/`citation_recall` 分母/分子改为只计 context-supported 引用（chunk 域），消除 `all_retrieved_ids=set()` 占位导致的 precision 恒 0；`faithfulness` 使用真实 context 文本（compare.py 由 context_chunk_ids 重建，`_rebuild_context_text`；generation_runner 用 sources 全文）
  - `evaluation/compare.py`：`_run_generation_arm` 三臂（A/B/C）统一传真实证据（sources 映射 + 检索网格 context/candidate 记录 + `_chunk_to_source_map`）；`retrieval_result` 缺失 → fail-closed（`RuntimeError` → error 记录，不产正常指标）；`GenerationCaseResult` 新增 `context_supported_citation_validity`/`fabricated_citation_count`/`retrieved_not_in_context_count`/`citation_status_counts`；`compute_summary` 聚合 `context_supported_citation_validity`/`fabricated_citation_avg`/`retrieved_not_in_context_avg`
  - `evaluation/generation_runner.py`：改用契约 v2 入口；runner 无独立检索网格，以 sources 解析 chunk 为 context 证据（生产 `_build_context` 与 `format_sources` 同源同截断，文档化于实现报告）
  - 新增 28 个单元测试（`tests/test_eval_citation_metrics.py` 24 个 + `tests/test_compare.py` 4 个）：sources 解析、context chunk/source 支持、候选池未进 context 无效、幻觉/空/重复/多引用确定性、source-only、缺输入 fail-closed、空 context 真实空、生产非流式/流式口径一致（format_sources 确定性 + citation_map 与 sources 解析 ID 集一致）、三臂传真实证据、retrieval_result 缺失 fail-closed、summary 聚合
  - 约束：不改 `RAG_RERANKER` 默认配置、Graph 逻辑、QueryPlan、锁配置、review overlay；不调用 LLM/API；不重跑真实评测；不改写任何已有 results 目录与 `decision-report.md`；实现报告见 `results/graph-gate/citation-eval-fix-<ts>/citation-evaluation-fix-report.md`

- **Reranker 正确性与公平对比修复（chunk-aware reranking + A/B/C context 对称化）** — 基于 `reranker-regression-diagnosis.md` 的最小可回归验证修复（诊断根因：reranker 只按 source_name 打分、B/C 独有 top-20 截断 + diversity 导致三臂不对称）：
  - `src/domain.py`：`RetrievalCandidate` 新增 `text` 字段（默认空串，向后兼容所有既有构造点），携带 chunk 实际文本
  - `src/retrieval.py`：`CrossEncoderReranker.rerank` 改为按 `(query, chunk_text)` 配对打分（禁止以 source_name 作为正文；空文本 fallback source_name 不崩溃）；排序加 `(rerank_score, index)` 稳定 tie-break，相同输入永远同序
  - `src/retrieval.py`：新增 `select_context_candidates()` 统一 context selector（source diversity + top-k 截断，保序确定性），作为 A/B/C 共用的「已排序候选 → context」入口
  - `evaluation/compare.py`：`_run_retrieval_arm` 与 `_graph_enhanced_answer_query` 中，A 臂也应用统一 selector（消除「A 无 diversity、B/C 独有截断」的不对称）；候选构造携带 `text=all_docs[i]`；三臂仅候选排序来源不同
  - `src/rag.py`：生产路径 `answer_query` 与流式路径同步应用 chunk-aware reranker + 统一 selector（评测与生产行为一致）
  - 新增 15 个单元测试（`tests/test_retrieval.py` 8 个 + `tests/test_compare.py` 7 个）：同源不同文本 chunk 得到不同分数、pair 正文必须是文本而非 source_name、空文本 fallback、并列分数 index tie-break 确定性、`select_context_candidates` 行为/截断/zh-002 类「同源第 4 个 chunk 被 max_per_source=3 挤出」回归场景/确定性、A 臂必须调用 selector、A 臂候选携带 chunk 文本

- **评测框架缺陷修复（自动化诊断流程中发现）** — 全自动诊断评测跑通 dev/holdout 过程中修复 4 处缺陷：
  - `compute_summary` 的 paired bootstrap 对 `GenerationCaseResult` 误调（访问 retrieval-only 字段）→ `AttributeError` 使 `--phase full` 保存生成 summary 前崩溃；加 `isinstance` 守卫，生成结果仅走 McNemar 分支（回归测试 2 个）
  - source 指标域不一致：`candidate_source_ids` 取自 chunk metadata 的 `source_id`（路径 SHA-256 哈希）与 dataset `relevant_source_ids`（文件名）不交集 → `source_recall@K` 恒为 0；新增 `_source_label_from_meta` 优先 `source_name` 对齐真值域（回归测试 5 个）
  - KG 缓存缺失：评测进程每次独立构建 KG（LLM 实体抽取非确定）→ locked-config 的 kg_sha256 后验跨进程恒失败；`evaluation/compare.py` 增加 KG 磁盘缓存（`{collection}_kg.json`，以 `index_fingerprint` 判据），`prepare_index` 改 `force_rebuild=False` 复用索引（回归覆盖于指纹测试）
  - `_kg_snapshot_sha256` 指纹口径：原用 `get_edge_data` 全属性（缓存 load 后丢失非 weight 属性）且对不可比较实体名抛 TypeError → 指纹漂移/None；改为与 `KnowledgeGraph.save` payload 一致的三元组 (source,target,weight) + 全 str 化排序，保证内存对象与缓存 load 对象指纹一致

### Added

- **v2 语料真值可追溯性与许可证证据整改（snippet 证据 fail-closed + 逐文档许可归属）** — 修复 v2 标注证据不可复现与许可证证据跨文档复用问题；不跑检索/特征扫描/LLM、不查看 holdout 特征、不 stage/commit：
  - **annotation-integrity 升级为 fail-closed**：`evaluation/corpus_v2.py` 新增 `normalize_snippet()`（**文档化 Markdown 格式归一化**：fenced/inline code、粗体/斜体/链接、标题/列表/表格标记、¶ 锚点字符、空白折叠；`>>>` REPL 提示符是正文内容不删除；大小写保留——大小写改写视为意译）+ `snippet_is_evidence()`（归一化后 snippet 必须是指定 chunk 文本的**连续子串**；空输入、意译、`...` 拼接、跨 chunk 粘贴一律拒绝）；TDD 13 个回归测试
  - **修复 73 个不匹配 chunk 引用（146 全部通过）**：`scripts/corpus_v2_content_{a,b,c,d}.py` 逐条更正 chunk_id（rust 4.1/4.2 从 chunk_5/6/7/10/11 更正到 37/38/40/48、SQLite SELECT/INSERT/Column Data Types/JOIN 更正到 24/66/13/40、Node.js FileHandle/highWaterMark/fsPromises.cp 更正到 15/17/31、py-en 4.7 match/索引/编码风格更正到 26/11/44、pg 窗口函数/Advanced Features 更正到 16/8、vue 组件基础更正到 19、react TaskApp 更正到 23、art-of-war 兵形象水更正到 chunk_94 等）并**从正确 chunk 原样复制连续证据片段**（保留换行与 markdown 标记，验证时双方对称归一化）
  - **merge/report 集成 fail-closed**：`scripts/corpus_v2_merge.py` 在 chunk 存在性/归属校验外新增 snippet 证据校验（任一不匹配即整体拒绝）；`scripts/corpus_v2_report.py` 新增 `annotation-evidence-report.md`（逐 ref 证据通过状态）并在报告重建前 fail-closed；重建 `annotation-integrity-report.md`（146/146 证据通过）、`annotation-pack-v2draft.jsonl`（150 行、review_decision 留空、**保持全部 LLM_ASSISTED，不生成正式 overlay**）
  - **许可证整改**：art-of-war 改用 **Project Gutenberg ebook 132 随附的完整 Gutenberg License 条款**（`licenses/gutenberg-ebook-132-license.txt`，从 gutenberg.org 官方 pg132.txt 提取；此前错误引用 sqlite 公共领域声明）；nodejs-fs 的 CC-BY-4.0 仅见于网站历史页脚、当前无法独立确认 → 改用 nodejs/node 仓库 LICENSE（MIT，明确涵盖 associated documentation files）`licenses/MIT-nodejs.txt`；**vue-guide-zh 许可证纠错：MIT → CC-BY-4.0**（vuejs/docs 仓库 LICENSE 文件实际声明 CC BY 4.0，`licenses/CC-BY-4.0-vuejs.txt`）；IETF-Trust-rfc5378.txt 原为空文件 → 从 rfc-editor.org 重下（37,980 字节）；`scripts/corpus_v2_licenses.py` 新增**逐文档归属审计**（fail-closed：attribution ↔ manifest ↔ 许可证文件三者一致、跨来源复用仅允许文档化同源组、任何不一致即不通过并禁止进入最终 manifest；`license-audit-report.md` 记录 13 来源全部可确认、**无 pending**）
  - **验证**：完整 pytest **995 passed / 7 skipped**（新增 21 个测试：snippet 证据 13 + 许可证审计 8）；py_compile OK；git diff --check exit 0；不可变性复验（chunk-manifest SHA 不变、case-freeze/split-lock 指纹不变——标注与许可证整改不影响封存；corpus-manifest.jsonl SHA 因 license 字段修正而更新为 f72abf55…）；生产代码零改动；未 stage/commit

- **评测语料 v2 扩充与封存执行（13 文档 / 1006 chunks / 150 例 LLM_ASSISTED 标注 / 新 holdout 已封存）** — 按 `plans/CORPUS-EXPANSION-PLAN-2026-08-05.md` 执行（方案见上一条目）；不修改生产默认、不启用 Graph/reranker、不调用评测 LLM、不 stage/commit：
  - **阶段 A 语料准入**：13 份新文档（中文 4：Python 教程 zh / 3.13 新特性 zh / datetime 模块 zh / Vue 指南；英文 6：SQLite 语法 / PostgreSQL 教程 / Rust Book 3–6 章 / RFC 3986 / 孙子兵法英译（公共领域）/ Node.js fs；混合 2：Python 术语表 zh / React 教程 zh）。许可证全部可验证（PSF-2.0 / MIT / CC-BY-4.0 / PostgreSQL / IETF-Trust / Public-Domain），`data/v2-corpus/attribution/` 含逐文档归属记录 + 8 份许可证原文；`evaluation/datasets/v2/corpus-manifest.jsonl` + `.json`（file_sha256 / size / license / source_url，manifest_sha256=0e7898cd…）；准入校验：与 v1 六篇文档无近重复（5-gram Jaccard ≥0.6 零命中）、敏感扫描 3 份文档命中官方署名邮箱（RFC 作者 / 文档引用）经复核保留（`sensitive-review.json`）；文件大小策略 ≤5MB/文件
  - **阶段 B 摄取**：新模块 `evaluation/corpus_v2.py`（TDD 25 测试）——HTML→Markdown 确定性转换（标准库 html.parser，剔除导航/脚本）、多章节文档组装、生产 chunker 分块（`src.rag.get_splitter`，chunk_id 与运行时一致 `{source_sha256_prefix}_chunk_{n}`）、敏感扫描（RFC 2606 保留域/示例名白名单）、5-gram 近重复、chunk 质量统计、corpus manifest；`data/v2-corpus/chunks/chunks.jsonl`（1006 chunks）+ `chunk-manifest.json`；`scripts/corpus_v2_prepare.py`（prepare/validate/chunks/manifest/attribution 五命令）
  - **阶段 C 150 例 LLM_ASSISTED 标注**：`scripts/corpus_v2_annotate.py` 骨架（id 续接 v1 前缀序列、18 层配额矩阵、难度 52/62/36、band_target 20/20/19/91、9 条链 24 轮含 2 条跨文档链与 1 拒答轮）+ 4 个内容文件（逐 chunk 精确引用）→ `evaluation/datasets/v2/annotations/v2-cases-draft.jsonl`；`scripts/corpus_v2_merge.py` fail-closed 校验（150 例 id 精确对应、chunk_id ⊆ chunk manifest 且归属正确、none/chunk/source 合法组合、source-only 2/150 ≤10%、链轮次连续 + follow_up_to 存在、no_answer 无证据）；产物：`annotation-pack-v2draft.jsonl`（review pack，review_decision 留空待人工终审）、`coverage-matrix.md`、`annotation-integrity-report.md`、`refusal-quality-report.md`（含旧 25 例 no_answer 与新语料冲突检测：关键词粗筛 + 人工复核，全部无实质证据冲突）
  - **阶段 D 新 holdout 封存**：新模块 `evaluation/split_seal.py`（TDD 20 测试）——freeze_case_ids / build_split（分层 group-aware：链原子、holdout ⊆ 新 150、每层 ≥1 组、splitmix64(seed+group) 纯确定性排序，不依赖 PYTHONHASHSEED）/ verify_lock / check_artifact_ids（产物含 holdout id → fail-closed）/ confirm_holdout（一次性确认，holdout ids 不落盘）；`evaluation/datasets/v2/split/`：case-freeze.json（全池 260 = 旧 110 legacy_dev + 新 150）、split-lock.json（split_fingerprint=eed351d2f97ef6e1506d9ac154d070840143c5ea134486787ed2a9511389f123、seed、stats；**不含任何 case id**）、seal-audit.json（18 层全部有 holdout 代表、3 条链完整入 holdout、holdout 40 例 = 新池 26.7% ∈ [0.22,0.30]、verify=True、封存前未对任何新用例运行检索/特征扫描）
  - **验证**：完整 pytest **974 passed / 7 skipped**（新增 45 个测试：corpus_v2 25 + split_seal 20）；py_compile 6 模块 OK；git diff --check exit 0；未 stage/commit；生产代码零改动
  - **已知风险**：① 标注为 LLM_ASSISTED 草稿，须人工终审（review pack 已导出）；② band_target 为构造意图，落带确认仅限 dev 侧 v2.1 扫描轮（holdout 禁止扫描）；③ 旧 110 例进入 dev 池，其 no_answer 在新语料下的无证据性质依赖抽查结论，正式评测前需 dev 检索复核；④ 新文档含导航/页脚残留文本（HTML 转换噪音），chunk 检索效果在评测中观察

- **评测语料 v2 扩充与新 holdout 构建方案（只读设计）** — 承接阶段 1.5 HGA 结论（样本不足 + 旧 holdout 已查看不可用），设计 v2 语料与标注协议；**零代码改动、不下载/抓取/导入外部文档、不调用 LLM/API、不改现有数据集与生产配置**（主方案 `plans/CORPUS-EXPANSION-PLAN-2026-08-05.md`）：
  - **盘点（只读）**：6 文档 / 736 chunks / 110 用例；chunk 前缀经 `source_id = sha256(规范化绝对路径)`（`src/rag.py:459`）反推映射——中文文档仅 18/736 chunk（≈2.4%）但中文查询占 42%，AI/LLM 论文占 ≈85% chunk；交织带 [0.0218, 0.0299] 仅 12 例；识别 G1–G10 十项覆盖缺口（中文 chunk 占比、领域单一、文档类型、无混合文档、多轮链、低分带、metadata 维度、hard 占比、同主题集群、source-only 真值）
  - **v2 准入规范**：来源三分类（用户自有 / 明许可证公开文档 / 政府公开数据）+ 硬性禁止（抓取/无许可证/付费/机密）；每篇必填 file_sha256/license/source_url/pub_date/parser；凭据类 0 容忍、个人数据脱敏或排除；SHA-256 精确去重 + 5-gram Jaccard ≥0.85 近重复人工裁决（含与 v1 六篇文档的跨版本近重复）；有效文本 ≥800 字符、PDF 无文本页 ≤10%、逐文档解析判定（无批次稀释）；chunk 主带 200–600 字符（≥90%）、抽检 20 chunk/篇、chunk-manifest 为权威来源（非 Chroma DB）
  - **规模与统计依据**：新 150 ±10%（全池 ≈260 = 旧 110 + 新 150）；zh/en/mixed 60/60/30；六类分布 single_fact 34 / metadata 19 / cross_document 31 / multi_turn 24 / mixed_intent 12 / no_answer 30；**G2 门槛推导**（dev SR ≥40 → 容许量 ≥4，Wilson 单侧 95% 上界 4/42 ≈0.20）；**FR 样本推导**（嵌套 5 折 GroupKFold 需 dev FR ≥12–15、holdout FR ≥5）；可检测性粗算（dev SR=42：真实错误率 30% → 观测 ≥5 概率 ≈99.7%，20% → ≈93%，10% → ≈44%——dev 只排"明显恶化"，精调靠 holdout）；交织带 dev ≥30 例 + 近带 ≥15 例（band_target 为构造意图，落带确认仅限 dev 侧 v2.1 扫描轮，holdout 禁止扫描）；新增 ≥8 条多轮链（≥2 跨文档链、≥1 拒答轮链）
  - **标注协议**：schema v2 增量字段（relevance_level / relevant_chunk_ids / relevant_chunks[].chunk_id / annotation / metadata.band_target + construction + chain_id），fail-closed 合法组合表（none/chunk/source），source-only 规则（≤10% 新增、每条 review_notes 理由、能定位必须 chunk）；两阶段审核（ZCode 起草 → 用户终审 approved/revise/reject）→ 100% approved 锁定 gt-v2.jsonl + gt-manifest.json（change request 流程）；双人 IAA 门槛 κ ≥0.85 / source ≥90% / chunk ≥80%
  - **全新 group-aware 划分协议**：旧 110 例全部归 dev（标记 explored），**holdout 只含新用例**（新池 25–30%，38–45 例，SR ≥10、FR ≥5、每层 ≥1 组）；划分前冻结 case-freeze.json；分层（18 层）× splitmix64(seed+group_key) 组排序纯确定性采样（不依赖 PYTHONHASHSEED）；split_fingerprint = SHA-256（corpus_version + freeze + 分组 + seed + splitter_version + dev/holdout 列表）；**split-lock.json 不含 holdout ids**（确认阶段重算 + 指纹校验）；阶段 A/B/C 封印与守卫（分析产物出现 holdout id → fail-closed 拒绝）；未来 `evaluation/split_seal.py` 契约（freeze_case_ids/build_split/verify_lock/check_artifact_ids/confirm_holdout，本计划不实施）
  - **数据版本与目录**：v2.0.0 联动三件套（corpus-manifest + case-freeze + split-lock）；`evaluation/datasets/v2/`（入 git：manifest/annotations/gt/split/v2.jsonl）+ `data/v2-corpus/`（不入 git：documents/chunks）+ `results/graph-gate/corpus-v2-<ts>/`（实验输出）
  - **标注模板** `plans/CORPUS-V2-ANNOTATION-TEMPLATE.md`：v2 JSON 模板、逐字段指南、合法组合表、band_target/construction 构造规则、多轮链规则、review pack 行格式、4 个完整示例（chunk 级 / source-only / 低分拒答 / 多轮链）
  - **验收 checklist** `plans/CORPUS-V2-ACCEPTANCE-CHECKLIST.md`：6 阶段（文档准入 → 索引分块 → 用例标注 → 审核锁定 → 划分冻结 → 规则选择/确认）逐项通过标准、失败动作与证据文件 + 数值门槛汇总表
  - **需用户提供**（§7）：新文档 8–16 篇（构成建议 + 每篇来源/许可证）、自有文档与第三方许可证授权、敏感信息决定、标注终审投入（150 例估 15–30 小时）、存放决定、双人 IAA 与否、后续 split_seal 实施指示
  - 验证：零代码改动（无 pytest 增量）；完整测试套件 929 passed / 7 skipped 无回归；py_compile 不适用；git diff --check exit 0；未 stage/commit

- **阶段 1.5 特征化拒答 —— 假设生成审计（HYPOTHESIS_GENERATING_ONLY）** — 用户将方案 A（候选规则筛选/预注册）收缩为只做假设生成：特征字典、特征表、全规则枚举与描述性统计，**不筛选规则、不预注册 LLM ablation、不使用 holdout 确认**（设计见 `plans/REFUSAL-SEPARABILITY-HYPOTHESIS-AUDIT-DESIGN-2026-08-05.md`）：
  - **新模块 `evaluation/refusal_separability.py`（纯离线，零 LLM）**：确定性特征提取（top1/2/3、gap12、mean5/10/all、std_all、count_ge_001/002/0025、n_candidate_sources，共 12 个有方差特征）；**标签隔离 fail-closed**（should_refuse/relevant_*/query_type/difficulty/case_id/review_* 等评测字段严禁作为特征，测试守护）；规则族（一元 ≥/≤、一元区间、二元 AND/OR、atom∨range/atom∧range，≤2 特征）；阈值网格 = 拒答子集观测值 + 中点；按放行签名去重枚举；PR 曲线；ASCII 可视化；TDD 新增 22 个测试
  - **枚举结果（dev 拒答子集 4 FR / 6 SR）**：595,984 条规则 → 873 个放行签名；**存在 FR=4/4、SR=0/6（precision=1.00）的"完美"签名（55 条规则）——但均为窄带记忆型**（如 `top3 ∈ [0.022948, 0.022962]` 宽度仅 0.000014，恰好套住 meta-006/meta-008 的观测值），属典型过拟合签名，佐证样本不足、不可泛化
  - **已知限制（报告必须声明）**：① 两特征复合规则为 post-hoc 假设（4 FR/6 SR 穷举，未验证）；② 现有 stable holdout 已被探索性查看，不能用于确认（仅以 exploratory_only 角色记录特征）；③ 当前样本不足以验证复合门控；④ 下一步需扩充语料并创建新的、未查看的 group-aware holdout
  - **未来协议（仅记录，不实施）**：扩充语料后 dev 内嵌套 GroupKFold（每折训练折选规则 → 验证折评估）；规则固定后仅在全新 holdout 评估一次；通过后再决定 LLM 受控实验
  - 生产影响：`DEFAULT_REFUSAL_THRESHOLD=0.03` 与基线拒答逻辑**保持不变**；未生成任何预注册；交付 `results/graph-gate/refusal-separability-hypothesis-20260805T184448/`（feature-dictionary.json、features.jsonl、rule-enumeration.json、pr-curves.json、separability-report.md、decision-report.md、manifest.json、run-commands.md，全部标记 HYPOTHESIS_GENERATING_ONLY）
  - 验证：完整 pytest **929 passed / 7 skipped**（新增 22 个测试）；py_compile OK；git diff --check exit 0；manifest 输入 SHA 复验 2/2 MATCH；历史产物未改动（decision-report.md 工作区改动 mtime 2026-08-02 为本任务前既有状态）；未 stage/commit

- **检索拒答阈值校准离线扫描（AUTOMATED_DIAGNOSTIC_NO_GO）** — 针对「baseline 16 条 dev false_refusal 中 5 条由检索前哨直接拒答、生成策略不可改善」的结论，研究 `DEFAULT_REFUSAL_THRESHOLD` 候选值（0.00/0.01/0.02/0.03）能否只释放前哨 false_refusal（设计见 `plans/REFUSAL-THRESHOLD-CALIBRATION-DESIGN-2026-08-05.md`，brainstorming 审批；G2 主口径经用户修订为「该 split 全部 should_refuse 的 10%」）：
  - **新模块 `evaluation/threshold_scan.py`（纯离线，零 LLM 调用）**：`refused_at`/`scan_thresholds`/`evaluate_split_gates`（G2 主口径 + 10/6/22 三基数敏感性表）/`admissible_thresholds`/`band_diagnostic`（分数带交织诊断）+ CLI（输出 threshold-scan.json/md、gate-pre-registration.json、decision-report.md、manifest.json、run-commands.md）；TDD 新增 22 个测试（`tests/test_threshold_scan.py`：空分数 t=0.00 仍拒答、边界语义、逐阈值放行集、G1/G2 判定与边界、敏感性、交织/可分离诊断、输出确定性）
  - **fail-closed 校验（不符即中止）**：① score 判定（max<0.03）与 generation JSONL 的 `evidence_context_sha256==""`（真实前哨拒答）逐 case 一致（dev 4 条：cross-010/en-013/meta-006/meta-008）；② 跨运行（production-baseline vs ablation）拒答分类一致（6 例分数微差不跨边界）；③ 派生前哨 FR 集合 == 预期 5 条（dev 4 + holdout meta-002）
  - **扫描结论**：全部拒答 case 分数位于 [0.0221, 0.03)，无 <0.02 的 case → 三个候选阈值放行集合完全相同（dev 10 = 4 FR + 6 应拒答；holdout 2 = 1 + 1）；**G1 PASS（5/5 ≥ 4/5）**、**G2 FAIL（dev 6 > 10%×22=2.2；holdout 1 > 10%×3=0.3；三种敏感性口径一致 FAIL）** → **无合格阈值 → AUTOMATED_DIAGNOSTIC_NO_GO，不进入 LLM 评测、不生成锁**
  - **诊断**：前哨 FR 分数带 [0.0260, 0.0299] 与正确拒答带 [0.0221, 0.0294] 完全交织——任何放行全部 dev FR 的阈值必然同时放行 ≥3 条正确拒答，**不存在任何阈值值（不限于候选集）能分离两类 case**；单一 max-score 阈值无法完成拒答校准，RAG-IMPROVEMENT-PLAN 阶段 1.5 应转向特征化拒答
  - **生产影响**：`DEFAULT_REFUSAL_THRESHOLD=0.03` 与 `RAG_REFUSAL_POLICY=baseline` 保持不变；不切换生产默认、不批准 guardrail；未构建 per-arm 阈值评测 infra（方案 A：仅交付可复现扫描包 `results/graph-gate/refusal-threshold-scan-20260805T154407/`）
  - 验证：完整 pytest **907 passed / 7 skipped**（新增 22 个测试）；py_compile OK；git diff --check exit 0；历史产物不可变性（manifest 输入 SHA 复验 4/4 MATCH；decision-report.md 工作区改动 mtime 2026-08-02 为本任务前既有状态）；未 stage/commit

- **拒答策略受控 Ablation（evidence_calibrated vs baseline，AUTOMATED_DIAGNOSTIC_NO_GO）** — 针对 false_refusal 集中于 cross_document/hard 的审计结论，实施并评测「仅改变生成阶段拒答策略」的受控实验（设计见 `plans/REFUSAL-POLICY-ABLATION-DESIGN-2026-08-05.md`，brainstorming 审批 + 用户规格修订）：
  - **新策略抽象（`src/rag.py`）**：`RAG_REFUSAL_POLICY`（默认 `baseline`，非法值导入期 fail-fast）；`evidence_calibrated` 仅向 system prompt 追加静态指令段（context 证据足以支持时必须作答并引用 [S1]…；仅当无文档片段包含所需信息时才拒答），**不含任何真值/评测信息**（11 个泄露模式单测断言 absent）；`PROMPT_TEMPLATE`/来源/引用格式不变
  - **PreparedAnswerEvidence（`src/domain.py`，生产级 frozen 对象）**：context 文本 + context_sha256、citation map（S#→chunk_id）、context/candidate chunk/source ids、top_scores、plan_fingerprint（rewrite+decompose 产物 SHA-256）、retrieval_fingerprint（候选+context 集 SHA-256）、refused（检索前哨拒答标记）；**`answer_query` 重构为 `prepare_answer_evidence` + `generate_answer`**（默认生产路径同样经过该证据路径，LLM 消息与重构前逐字节一致由回归测试守护）
  - **评测 A/B 共享证据**：新臂 `standard-calibrated`（`REFUSAL_ABLATION_ARMS`）；每 case 从共享 QueryPlan 构建一次 evidence（零 rewrite/decompose/retrieve/select 重跑），A/B 两臂仅分别调用生成步骤；`GenerationCaseResult` 写入 evidence/context 指纹；paired 分析对同 case A/B 的 context_sha256/citation map/candidate 集不一致 **fail-closed 拒绝**（dev 95 例实测零差异）
  - **锁定（`evaluation/locked_config.py`）**：新必填 per-arm `refusal_policy`（键集==arms）与 `effective_prompt_ids`（逐臂「实际 system prompt + addendum + PROMPT_TEMPLATE」SHA-256，键集==arms）；策略正文/策略名/臂映射任一漂移 → LLM 前拒绝；旧锁无键放行；旧 prompt_id 仅保留为历史兼容
  - **受控评测**（`results/graph-gate/refusal-ablation-20260805T133209/`）：新锁（复用稳定 split 指纹 `454892e4…3690` + 双 overlay + 相同 dataset/corpus/index/预算/模型）→ precheck PASS → smoke 15 条 false_refusal 双臂 PASS（A 15/15 拒答、B 14/15；**5 例为检索前哨拒答，生成策略不可改善**——审计未区分的分层）→ dev full（95×2 臂）EXIT=0
  - **dev 结果与门槛（预注册，fail-closed）**：false_refusal A=16/73（0.2192）→ B=18/73（0.2466）**G1 FAIL（反增 2）**；false_answer A=9/22→B=3/22 **G2 PASS（改善）**；micro=1.0（142/142、134/134）fab=0 nin=0 **G3 PASS**；answer_rate 0.8767→0.8219 **G4 FAIL**；coverage 0.6073→0.6119（CI 含 0）**G5 PASS** → **AUTOMATED_DIAGNOSTIC_NO_GO，未跑 holdout**；配对 W/L/T=8/4/83、McNemar p=0.388；**目标切片反恶化**：cross_document false_refusal 6→9、hard 5→6
  - **结论**：evidence_calibrated **不提升为生产默认**（默认保持 baseline，零自动切换）；根因 = 提示放宽的是「拒答倾向」而非「证据条件」（false_answer 改善但 cross_document 恶化）；建议后续走证据条件化门控（检索分数/覆盖率特征，RAG-IMPROVEMENT-PLAN 阶段 1.5）与检索拒答分层；guardrail 阈值维持 CANDIDATE 不批准
  - 每阶段独立子代理验证：phase1-verification.json（9/9 PASS，TDD 实现）、phase2-verification.json（7/7 PASS，受控评测/门槛/不可变性）；完整 pytest **885 passed / 7 skipped**（新增 53 个测试）；py_compile OK；git diff --check exit 0；历史产物不可变性 20/20 快照一致；未 stage/commit

- **生产基线正式候选评测 v2（CANDIDATE：稳定 split + split_fingerprint 锁定 + LLM 辅助审阅真值）** — 在 `results/graph-gate/production-baseline-stable-20260805T084256/` 以稳定 split 重跑生产基线（`arms=[standard]`、RAG_RERANKER=none、`RAG_SELECTOR_MAX_PER_SOURCE=3`、Graph 禁用、alpha=1.0），split 与 PYTHONHASHSEED 无关（框架已永久修复，split_fingerprint=`454892e4…3690` 锁定于 `lock-production-stable.json` 并在评测前 fail-closed 校验）：
  - 流程：precheck PASS（锁/稳定 split 指纹/双 overlay 消费 + truth gate/index 指纹/env/immutability 快照）→ 分层 smoke 6/6 PASS（中文/英文/多轮/source-only/拒答/citation，生产链路）→ dev full（95 例）+ holdout full（15 例）exit 0 → 每阶段独立子代理验证（phase1-verification.json 17 项 PASS、phase2-verification.json 16 项 PASS，指标独立复算零差异）
  - dev（95 例，answerable 73，拒答 22）：citation v2 micro=1.0000（153/153）、answer_rate=0.9041（66/73）、no_citation=0.0959（7/73）、answer_point_coverage=0.5799、context_recall=0.5403、source_recall@5=0.9829、false_refusal=0.1918（14/73）、error_rate=0
  - holdout（15 例，answerable 12，拒答 3）：micro=1.0000（22/22）、answer_rate=0.8333（10/12）、no_citation=0.1667（2/12）、coverage=0.6389、context_recall=0.7569、source_recall@5=0.9583、false_refusal=0.0833、error_rate=0
  - **旧候选（20260804T2220）不可直接比较**：split 成员变化（dev 94→95、holdout 16→15，holdout 链 multi-007/008/009/010 → multi-004/005/006）+ 旧运行未固定 hash seed；本报告数字取代旧数字作为当前 CANDIDATE 基线
  - **事实声明**：27 条真值决定为 LLM 辅助审阅（非人工签署）；guardrail 阈值建议（micro≥0.95、answer_rate≥0.80、no_citation≤0.20、false_refusal≤0.20）仍待人工批准；dev false_refusal 贴近阈值 0.20，建议人工复核拒答 case
  - 约束：未修改任何历史 results 产物与 decision-report.md；未 stage/commit；未自动启用 Graph/reranker；未修改生产默认；运行日志仅记录 PYTHONHASHSEED 环境值（稳定 split 不依赖）

- **false-refusal 与 guardrail 阈值只读审计包（CANDIDATE 辅助材料）** — 基于 `production-baseline-stable-20260805T084256/` 生成 `results/graph-gate/refusal-guardrail-audit-20260805T113849/`（离线、fail-closed、不改任何输入与配置）：
  - 精确提取 false_refusal（`should_refuse=False ∧ correctly_refused=False`，判定依据 `compute_refusal_accuracy` 短语匹配并逐条复算命中）：dev **14/73**（cross-005/007/009/010、en-012/013/016、meta-006/008、mixed-006/008、multi-009、zh-011/014）、holdout **1/12**（meta-002）；计数与 JSONL 不符即整体失败
  - 每 case 输出 query/应答要点/模型回答/拒答命中短语/检索 context（来源与 chunk 覆盖）/citation 状态/真值状态（含相关 chunk 是否进候选池与 context）；切片分析（language/query_type/difficulty/source-only/multi-turn，分子/分母 + Wilson 95% CI）显示 dev 误拒答集中于 cross_document（6/11=0.5455）与 hard（5/10=0.5000）；4 例真值 chunk 已进 context 仍被误拒（cross-007/009、mixed-008、meta-002@holdout）属模型侧误判
  - guardrail 敏感性：false_refusal 建议阈值 0.20 下 dev rate=0.1918 仅 **PASS margin -0.0082**（单例翻转：15/73=0.2055 即 FAIL；收紧至 0.18 直接 FAIL）；模拟 0.15/0.18/0.20/0.25 全部 PASS/FAIL 判定输出；citation v2 三指标（micro≥0.95、answer_rate≥0.80、no_citation≤0.20）全部以 candidate-report-data.json 的 numerator/denominator 复算（未手填），dev/holdout 全 PASS
  - 产物：`refusal-review-pack.jsonl`（15 行，键集一致）、`guardrail-sensitivity.json`、`refusal-guardrail-audit.md`、`manifest.json`（8 个输入 SHA-256 + 计数 + 不可变性声明）、可复现生成脚本 `generate_refusal_audit.py`
  - 验证：独立复算 34 项 PASS（统计守恒、rate×n 一致、阈值判定逻辑、报告数字与 JSON 一致）、immutability 快照 13/13 MATCH、完整 pytest 832 passed/7 skipped、py_compile OK、git diff --check exit 0
  - 结论：**未批准/未修改任何阈值**（0.20 为 CANDIDATE 建议，margin 过紧不建议自动收紧）；拒答优化应优先针对 cross_document 与 hard 切片（RAG-IMPROVEMENT-PLAN 阶段 1.5 拒答校准入口）；人工复核 15 条 false_refusal 待人工指示

- **生产基线正式候选评测（CANDIDATE：人工审核真值 + citation v2 guardrail 基线）** — 在 `results/graph-gate/production-baseline-20260804T2220/` 完成受控评测：`arms=[standard]`（RAG_RERANKER=none）、`RAG_SELECTOR_MAX_PER_SOURCE=3`（arm_selector_policy 锁定）、Graph 禁用（kg=None）、alpha=1.0；人工审核真值闭环（27/27 overlap 决定：25 confirmed / 2 rejected；4 条 source-only；8 个 meta-* case 补标；en-004/mixed-005 snippet 由意译修正为 chunk_27 逐字子串以恢复 exact 匹配）：
  - `evaluation/datasets/v1.jsonl`：en-004/mixed-005 的 relevant_chunks snippet 修正（意译 → chunk_27「2. Background > 2.1. Speculative Decoding」逐字子串，page 3），语义不变、仅恢复可匹配性
  - 产物（`production-baseline-20260804T2220/`）：`lock-production.json`（预检 PASS：corpus/index 指纹与旧锁一致）、`precheck.py`/`verify_truth_integrity.py`/`rebuild_gt_map.py`/`migrate_pack_decisions.py`（SHA 链与标注完整性 fail-closed 校验）、双 overlay（dev 19 confirmed + holdout 6 confirmed，均含 4 source-only）、dev-full（94 例）+ holdout-full（16 例）全部 exit 0、`candidate-report.md`（阈值建议：micro≥0.95、answer_rate≥0.80、no_citation≤0.20、false_refusal≤0.20）
  - dev/holdout 结果：citation v2 micro=1.0000（156/156、22/22）、answer_rate=0.8889（64/72）/0.8462（11/13）、no_citation=0.1111/0.1538、answer_point_coverage=0.6574/0.4359、context_recall=0.5703/0.5833、source_recall@5=0.9826/0.9615
  - **框架缺陷修复（重要）**：`group_aware_split` 的 multi-turn chain 分配依赖 set 迭代顺序（受 PYTHONHASHSEED 随机化），跨进程 split 可能不一致（overlay 生成与评测运行 mismatch → 真值门禁 fail-closed 拒绝）；本批全部流程固定 `PYTHONHASHSEED=0` 保证 rebuild↔评测严格一致；**历史各运行（auto-run/reranker-recheck/selector-ablation）未固定 hash seed，其 split 集合一致性未验证**，与新评测不可直接比较
  - 未修改任何历史 results 产物与 decision-report.md；未 stage/commit；未自动启用 Graph/reranker；阈值签署待人工

- **Evaluation dataset chunk-truth annotation** — Added exact-content chunk annotations for eight former missing-truth metadata cases; retained the four page-count/corpus-inventory cases as source-only to avoid treating PDF footer or corpus inventory metadata as answer-bearing text. The updated dataset requires a fresh review pack before strict import.

- **Citation v2 分母统一契约与历史产物离线对账（TDD：32 个新测试）** — 修复 2026-08-04 审计发现的「同一批产物中 citation 指标出现 0.875/0.847/0.713 等不同值」问题（根因：不同汇总路径分别以全体 case / 可答 case / 含 citation case 为分母且指标名未携带分母）：
  - `evaluation/citation_aggregation.py`：citation v2 聚合的**唯一入口**（compare.py summary、离线 replay、任何新分析必须调用，禁止各自手算）；分母唯一命名 `all_generation_cases` / `answerable_generation_cases` / `answers_with_any_citation` / `total_unique_citation_ids`；新指标 `context_supported_citation_validity_micro`（ID 层 micro：Σ支持 ID / Σ唯一 ID）、`context_supported_answer_rate`（≥1 支持引用的答案 / 可答 case）、`no_citation_answer_rate`、`citation_mention_rate`，每个携带 numerator / denominator（命名+计数）/ excluded_count / excluded_reason；**分母为 0 → value=None（unavailable），不伪装为 0**
  - 行/ID 双分区守恒恒等式 R1-R4 由 `check_conservation()` fail-closed 校验（分子 + 分母外行 + 分母内未命中 == 原始行数）；缺证据行（citation v1 时代产物）的引用状态视为**未知**，计入 excluded 而不进分母（否则把未知当不支持会伪装为 0）
  - legacy 隔离：旧键（citation_id_validity / citation_precision / citation_recall / faithfulness / context_supported_citation_validity 单值）保留兼容读取并标记 deprecated（`LEGACY_METRIC_KEYS`、`legacy_mean_metric` 仅对账用）；新 guardrail 只能经 `get_guardrail_metric()` 消费新指标（legacy/未知名抛 ValueError）
  - `evaluation/compare.py`：`compute_summary` 生成分支新增 `citation_v2` 块（统一 helper 产出），旧键保持旧口径不变（兼容读取）
  - `evaluation/reconcile_citation_denominators.py`：离线 replay 工具——从历史 generation-cases.jsonl 确定性重算新口径，对账 legacy 旧值（18/18 键与 JSONL 重算完全一致），v2 产物逐 case 校验存储 validity 与 status_counts 一致（0 不一致），v1 产物（auto-run / reranker-recheck）如实报告新口径 unavailable；输出 `results/graph-gate/citation-denominator-reconciliation-20260804T210032/`（reconciliation-summary.json + reconciliation-report.md），不改写任何历史产物
  - 对账结论：selector-ablation 全部可重算——dev S0/S3 answer_rate = 0.8750 / 0.8472（= 旧 s0s3-analysis「可答分母」值，语义澄清为答案层）、micro = 1.0000（150/150、145/145，无 fabricated/not-in-context）、no_citation 0.1250 / 0.1528；旧 0.713/0.691 为 legacy 全体分母均值，与新口径差异纯属分母口径（非指标 bug）；holdout 双臂 answer_rate 0.8333
  - 约束：不改生产默认（RAG_RERANKER=none、selector cap=3、Graph 不产品化）；未调用 LLM/API、未重跑评测、未改写历史 results 与 decision-report.md；不 stage/commit

- **Context Selector 策略消融评测（AUTOMATED_DIAGNOSTIC）** — 在 `results/graph-gate/selector-ablation-20260804T202048/` 完成 S0（selector-unlimited，不限同源）vs S3（selector-cap3，每源最多 3）受控 A/B 全量评测（dev 94 例 + holdout 15 例，双臂均 RAG_RERANKER=none、Graph 禁用、alpha=1.0、同进程共享 QueryPlan/候选池，lock-S0S3.json 含 per-arm arm_selector_policy fail-closed 校验；产物含 precheck/gen_locks/prep_smoke/analyze_s0s3 脚本、s0s3-analysis.json、dev/holdout failures.csv、selector-ablation-decision-report.md）：
  - 检索层 S0 显著更优：dev context_recall +0.089（配对 95%CI [−0.153, −0.032] 不含 0）、同源 rank≥4 相关 chunk 保留 22 vs 15/47、retention 0.720 vs 0.625；source 覆盖广度 S3 更广（context_source_recall 0.928 vs 0.903、单源 context 占比 10% vs 38%）
  - 生成层完全打平：dev answer_point_coverage 0.660 vs 0.662（Δ=+0.002，CI [−0.063,+0.069]，W/L/T=6/4/62）；citation v2（context_supported）0.875 vs 0.847、false_refusal 10 vs 15（均无显著差异）；holdout n=12 功效不足（cov Δ=+0.042，CI [−0.083,+0.250]，ctx_recall/cit v2 持平）
  - 自动决策 **AUTOMATED_DIAGNOSTIC_NO_GO**：dev 无稳定 answer 质量收益 → 未达 holdout 确认门槛；生产默认保持 cap=3 不自动切换；unlimited 列为人工复核候选（检索收益显著但未转化 answer 收益，且单源集中有跨文档覆盖风险）；未人工审核、未修改生产配置/历史产物/decision-report.md（immutability 复验 PASS）

- **Context Selector 策略消融基础设施（S0/S3 双臂 + per-arm selector policy）** — 支持「无 reranker 基线应使用不限同源还是每源最多 3」的决定性受控评测（TDD：20 个新测试先行失败后实现）：
  - `src/retrieval.py`：`apply_source_diversity`/`select_context_candidates` 支持 `max_per_source=None/0` = 不限同源（仅 top_k 截断、保序；生产默认 3 不变）
  - `src/rag.py`：新增模块变量 `SELECTOR_MAX_PER_SOURCE`（默认 3；`RAG_SELECTOR_MAX_PER_SOURCE` 环境变量 none|unlimited|0 → None、正整数 → 上限、非法值导入期 fail-fast）；`answer_query`/`answer_query_stream` 4 处 selector 调用点改读该变量（评测按臂临时覆盖 + finally 恢复）
  - `evaluation/compare.py`：新增消融臂 `selector-unlimited`（S0）/`selector-cap3`（S3）与显式映射 `ARM_SELECTOR_MAX_PER_SOURCE`（A/B/C 保持生产默认 3，行为不变）；`_run_retrieval_arm` 两处与 `_run_generation_arm` 按臂传 `max_per_source`（生成臂同时 patch reranker=none + SELECTOR_MAX_PER_SOURCE，finally 恢复）；`build_run_manifest` 记录 `arm_selector_policy`；CLI `--arms` 接受新臂
  - `evaluation/locked_config.py`：lock 新增可选键 `arm_selector_policy`（每臂 int≥1/null；0 必须写 null，非法形状 load 即拒绝；旧 A/B/C 锁无该键向后兼容）；`validate_locked_config` 含 selector 臂时必须已锁定（fail-closed）且逐臂比对运行时映射（防 S0/S3 配置漂移）；`collect_runtime_budgets` 的 `source_diversity_max_per_source` 改读 `SELECTOR_MAX_PER_SOURCE`（全局默认漂移可检）
  - 新增 20 个单元测试（`tests/test_retrieval.py` 5 + `tests/test_compare.py` 6 + `tests/test_locked_config.py` 9）：None/0 不限同源、S0/S3 共享 QueryPlan/候选池且唯一差异为 max_per_source、生成臂 patch/恢复、manifest 记录、CLI 接受新臂、lock 生成/加载/校验/漂移拒绝/旧锁兼容

- **Reranker 修复后受控重新评测（AUTOMATED_DIAGNOSTIC）** — 在 `results/graph-gate/reranker-recheck-20260804T185937/` 完成 A（RAG_RERANKER=none）vs B（修复后 chunk-aware reranker）受控 A/B 全量评测（dev 95 例 + holdout 15 例，Graph 禁用、alpha=1.0、双臂同进程共享 QueryPlan、同一 context selector 与 budgets，经 locked-config fail-closed 校验；产物含 precheck/gen_locks/prep_smoke/analyze_ab 脚本与 ab-analysis.json、reranker-recheck-decision-report.md）：
  - 检索层修复生效：dev context_recall +0.024、同源候选排名≥4 的相关 chunk 保留 12→20/45，zh-002 回归场景（同源第 4 chunk）A 未保留 → B 保留
  - 生成层无净收益：dev answer_point_coverage Δ=−0.001（CI [−0.071,+0.073]，W/L/T=5/6/62）；holdout 方向为负（Δ=−0.111，CI 上界 0.000；无引用答案 2→5）
  - 自动决策 **AUTOMATED_DIAGNOSTIC_NO_GO**：生产默认保持 `RAG_RERANKER=none`；未人工审核、未修改生产配置/历史产物/decision-report.md

- **P1 离线 source-level retrieval 评测补齐** — 补齐 `plans/GRAPH-RAG-EVALUATION-PLAN-2026-08-02.md` §5.1/§6.1 要求的 source recall 与 context source 覆盖指标，使 `relevance_level=source` 的 case 进入独立分母而不影响 chunk/context/citation 口径（与上批 review apply 真值门禁口径不倒退）：
  - `evaluation/metrics.py` 新增两个纯函数 `context_source_recall()` / `context_source_coverage()`：前者 `|context_sources ∩ relevant_sources| / |relevant_sources|`（与 chunk-level `context_recall` 对称），后者 `|context_sources ∩ relevant_sources| / |context_sources|`（与 `context_precision` 对称），空分母返回 0
  - `RetrievalCaseResult` 新增 `source_candidate_metrics(ks)`（候选层 source recall@5/10，复用 `source_recall_at_k`）与 `context_source_metrics()`（context 层 source recall/coverage）；所用 `candidate_source_ids`/`context_source_ids`/`relevant_source_ids` 均为运行时一次性写入结果的确定性字段，不依赖运行后不可得的 collection
  - `compute_summary` 检索分支新增 source 聚合：`source_valid = answerable 且有 relevant_source_ids`（含 source-only case，**不被** `has_chunk_truth` 过滤），输出 `n_source_valid`、`n_source_only`、`source_recall@5`、`source_recall@10`、`context_source_recall`、`context_source_coverage`；`n_chunk_valid` 与 chunk/context recall/precision/ndcg、Graph lift/pollution_rate、延迟口径全部不变
  - chunk/source 分母严格隔离：source-only case 仍不进入 chunk/context/citation 分母（`has_chunk_truth=False` 既有过滤保持），现仅进入独立 source 分母；paired bootstrap 与 Graph lift/pollution 仍仅用可靠 chunk 真值（source-only 因 `relevant_chunk_ids` 为空与 `has_chunk_truth=False` 天然被排除）
  - alpha 隔离不变：`compute_summary` 拒绝混合 alpha（既有校验）
  - `build_failures_csv_rows` 语义化标注：无可靠 chunk 真值的 case 按是否有 source 真值拆分 `source_level_only`（有 relevant_source_ids）与 `no_reliable_chunk_truth`（无任何真值），均不伪造 chunk-level win/loss/equal（`outcome=""`）；`graph_lift`/`graph_pollution` 直读（source-only 必为 False → `flip=False`）
  - 新增 12 个单元测试（`tests/test_compare.py`）：source 候选去重/截断 recall、context source recall/coverage（双分母与空集边界）、source-only 纳入分母、无 relevant_source 排除、chunk/source 分母隔离、alpha 隔离、无 overlay 兼容、paired bootstrap 不污染 + failures 行 source_level_only/no_reliable_chunk_truth 拆分

- **P1 人工审阅结果严格导入与消费门禁（review apply）** — 新增 `evaluation/review_apply.py`，实现已填写 review pack 的严格导入与 overlay 消费：
  - `apply_review_pack()`/CLI：输入 base dataset、base ground-truth-map 与已填写 review pack 目录，输出到用户指定新目录（拒绝与 pack 目录相同，绝不覆盖输入）；先校验 review-pack-manifest 的 dataset/ground-truth SHA-256（陈旧拒绝），再严格校验两 JSONL——行数必须等于 manifest 计数（重复/缺失/未知行拒绝）、键集必须等于导出模板（未知/缺失列拒绝）、`review_decision` 只能 confirmed/reject、`relevance_level` 只能 chunk/source；空值/非法值/陈旧输入/行集不全整体失败，**不产生部分输出**（原子写）
  - 确定性输出 `reviewed-truth-overlay.json` + `review-apply-manifest.json`：confirmed → reviewer_status=confirmed、reject → **rejected**（显式区分，绝不混淆）、relevance_level 按 case_id 保存；记录输入/输出 SHA 与计数，无 secret
  - `evaluation/compare.py` 新增可选 `--reviewed-truth`：prepare_index 前校验 overlay 版本/dataset SHA/case_id 与标注存在性；GT 构建后按稳定键 (case_id/source_id/normalized_snippet/候选 chunk IDs) 精确应用，未消费/重复匹配/非法决定在 QueryPlan/LLM 前失败并列出差异；真值门禁——source-only 放行并从 chunk/context/citation 分母排除（口径不倒退，日志报告 source-only 数）、chunk-level 无可靠真值失败并列出 case_id、overlap reject 致无真值且无显式 source 决定同样失败；不传 `--reviewed-truth` 保持旧行为
  - 使用路径写入 `evaluation/REVIEW_PACK_README.md`（填写 → apply → compare --reviewed-truth）
  - 新增 37 个单元测试（`tests/test_review_apply.py`）：确定性输出、manifest SHA 陈旧拒绝、空/非法/重复/缺失/未知行拒绝且无 partial output、confirmed/reject 显式应用、source-only 放行与分母排除、chunk-level/无决定无真值门禁失败、overlay 与 GT 不匹配在 prepare_index 前拒绝（LLM 未启动）、无 overlay 兼容

- **P1 离线 locked-config 基础设施** — 新增 `evaluation/locked_config.py`，实现版本化、确定性、无密钥的评测配置锁定（`plans/GRAPH-RAG-EVALUATION-PLAN-2026-08-02.md` §4.4/§12 的 alpha 锁定与 holdout 单次确认）：
  - `build_locked_config()`/`save_locked_config()`：锁定单一 alpha（显式提供，绝不从结果自动选择）、dataset/corpus/index/KG SHA-256 指纹、embedding/LLM/reranker 模型与 prompt 标识（SHA-256）、seed、arms 与 fusion/candidate/context/refusal 预算；provenance 说明来源为 development；同输入产出逐字节相同的 locked-config.json，不含任何 URL/token/API key
  - `load_locked_config()`/`validate_locked_config()`：fail-closed 加载与校验 —— 版本不支持、缺必需键、budgets 键集漂移、alpha grid 不等于锁定值、指纹/seed/arms/模型/预算漂移均返回差异字段并拒绝，错误消息不泄露 secrets；index/KG 指纹按预检（索引前，跳过）/后验（索引后，必须一致）两阶段校验
  - CLI 接入 `evaluation/compare.py`：`--lock` 仅允许 `--split development` 且必须显式 `--alpha`（与 `--validate-only`/`--config` 互斥）；`--split holdout` 必须提供 `--config`，且在 prepare_index 之前完成校验，不匹配即退出；锁定 alpha 后 alpha grid 强制等于锁定值
  - 从 `build_run_manifest` 提取 `_index_snapshot_sha256()`/`_kg_snapshot_sha256()` 供 manifest 与 lock 后验复用（行为不变）
  - 新增 34 个单元测试（`tests/test_locked_config.py`）：确定性/序列化、无密钥、load 拒绝、漂移拒绝、匹配放行、CLI 前置顺序（prepare_index 未被调用）

- **P1 locked-config 指纹强制返修（fail-closed 缺口）** — 独立验收发现 index/KG 指纹可为 null 且被 validate 跳过，存在绕过路径；已封堵：
  - `index_sha256` 任何臂都必须为完整 64 位 SHA-256：`load_locked_config()` 在加载阶段拒绝缺失/None/坏格式（错误只报字段名），`build_locked_config()` 在生成阶段拒绝（快照无法计算时不写 lock）
  - `kg_sha256` 按 arms+alpha 显式判定适用性（`_kg_fingerprint_required()`）：arms 含 graph-rerank 且 locked_alpha<1.0 时必须为完整 64 位 SHA-256（生成与预检双重拒绝 null）；非图或 alpha=1.0（C 不经过 Graph 通道）时 null 为 not-applicable 放行
  - `evaluation/compare.py`：`--lock` 生成时快照无法计算（None/坏格式）→ 明确失败并返回非 0，不写出未锁定的 locked-config.json
  - 新增 16 个回归测试（`tests/test_locked_config.py` 增至 50 个）：null/坏格式 index 拒绝、图 C+alpha<1 缺 KG 拒绝（含 main 级 prepare_index 未调用）、非图/alpha=1 kg=null 放行、--lock 无法计算快照失败且不写文件、真实匹配放行（非空可控假指纹注入 mock）

- **P1 真值人工确认审阅包（review pack）** — 新增 `evaluation/review_pack.py` 离线审阅工具，为 chunk 真值人工确认生成可复现审阅包：
  - 导出全部 `reviewer_status=needs_review` 条目（真实 v1 数据 27 条）：case_id、query、source/snippet、候选 chunk、匹配证据（可选 `--corpus-json` 提供 chunk 文本后生成 bigram 重叠比例与文本预览）与空白的 `review_decision`/`reviewer_notes` 字段
  - 单独导出可回答但缺 chunk 真值的 case（真实 v1 数据 12 条）：明确标记待人工判定 `relevance_level=chunk`（需补标内容 chunk）或 `source`（无内容 chunk 真值）
  - 工具只导出、不判定：不调用 LLM/API，不修改输入文件；`review-pack-manifest.json` 记录输入 SHA-256，相同输入产出逐字节相同的审阅包
  - `evaluation/compare.py` 最小 schema 扩展：`GroundTruthEntry` 新增可选 `relevance_level` 字段、`RELEVANCE_LEVELS` 常量、`validate_relevance_level()` 校验、`ground_truth_from_dict()`/`load_ground_truth_map()` 导入格式（兼容旧版无该字段的 ground-truth-map.json）
  - 新增 28 个单元测试（`tests/test_review_pack.py`）与使用说明（`evaluation/REVIEW_PACK_README.md`）

- **Knowledge-base and ingestion UX decisions** — Recorded the agreed first-run / returning-user flows, user-facing knowledge-base model, unique default names, per-knowledge-base source roots, and visible sync status (`plans/2026-08-02-knowledge-base-ux-decisions.md`).

- **Knowledge-base UX implementation plan** — Added the complete, staged plan for the knowledge-base registry, source-root synchronization, legacy migration, asynchronous task visibility, TUI flows, test coverage, and acceptance criteria (`plans/2026-08-02-knowledge-base-ux-improvement-plan.md`).

- **Graph RAG 阶段 4 入场评测方案** — 新增受控 A/B/C 实验、真值修复、指标与统计方法、GO/CONDITIONAL GO/NO-GO 门槛及可复现产物规范（`plans/GRAPH-RAG-EVALUATION-PLAN-2026-08-02.md`）

- **评测框架公平性修复（P0 补丁）** — 修复 `evaluation/compare.py` 中影响 A/B/C 可比性的关键失真：
  - 新增 `QueryPlan` dataclass + `prepare_query_plan()`：将 rewrite/decompose/基础检索/漂移防护提取为共享步骤
  - 新增 `build_query_plan_cache()`：alpha/arm 循环外一次性构建缓存，每个 case 只调用一次 LLM，所有 arm 和 alpha 复用同一 QueryPlan 实例
  - 新增 `merge_graph_candidates()`：RRF(k=60) 同量纲融合 Graph 候选到 base candidates，替代旧实现的 `(1-alpha)/(rank+1)` 计分（后者量纲与 base RRF ~0.016 不一致，不公平压过 base）
  - C 臂从「用 graph_augmented_retrieve 替换 base candidates」改为「在 base_candidates 上增量合并 Graph candidates」
  - alpha=1.0 时禁止加入 graph-only candidates，确保 C 与 B 的候选排序和 context 严格一致
  - 实体抽取改用 `query_plan.rewritten_query`（避免重复 LLM 调用），清理未使用的 `_KG` import
  - `b_context_ids` 从 arm 循环内移到 alpha 循环外层，C 组运行时若 B 基线缺失则抛出 RuntimeError
  - `RetrievalCaseResult` 新增 `alpha`、`graph_only_chunk_ids` 字段
  - 新增 14 个单元测试：merge_graph_candidates（base 保留/overlap/alpha=1 无 graph-only/RRF 同量级/dynamic_top_k 不污染）、build_query_plan_cache（每 case 一次调用/identity 共享/多轮 history 传递）、B 基线 lift/pollution、run_retrieval_grid（QueryPlan identity 复用验证）

- **评测框架公平性修复（P0 补丁续）** — 修复 reranker 依赖和 alpha 分组问题：

- **P0 图实体缓存 + 真值分母修复（返修）**：
  - `RetrievalCaseResult` 新增独立 `entity_ms: float` 字段（不再复用 `embedding_ms`）；`embedding_ms` 保留真实语义
  - `_run_retrieval_arm` 中 C 臂 alpha=1.0 时完全跳过图路径（KG 调用、图遍历、融合），在混合 alpha grid 中也比 B 无差异
  - 可靠 chunk 真值严格条件：`exact` 或 `(overlap|parent 且 reviewer=confirmed)`；已排除任意 confirmed 的 source_fallback/unmatched
  - `compute_summary` 的 chunk/context 分母限定为 `not should_refuse AND has_chunk_truth`；`excluded_no_chunk_truth` 只统计 answerable 无真值
  - paired_cb 仅对两侧都 answerable 且有可靠 chunk truth 的 case 配对，避免口径回流
  - 新增 8 个测试：entity_ms 独立字段、alpha=1.0 跳过 KG 混合 grid 回归、confirmed parent 纳入/非 overlap+confirmed 排除/should_refuse 不影响分母、mock extract_entities_from_query 直接调用 prepare_query_plan

- **P0 配对 bootstrap CI + p95 + manifest 完整化**：

- **P0 返修 — bootstrap chains + CLI sanitizer + _safe_url port**：

- **P0 manifest 返修 — endpoint / config hash / index-KG canonical / runtime version**：

- **P0 离线评测修复 — phase 语义 / McNemar / failures.csv**：
  - 修复 `--phase` 语义：`generation` 与 `full` 现在真正进入生成编排（`run_generation_grid`），不再静默只跑检索；复用同一 case/alpha 的 QueryPlan 缓存与检索结果做延迟归因，不重复 rewrite/decompose
  - `GenerationCaseResult` 新增 `alpha` 字段；新增 `group_generation_results_by_alpha()` 按 alpha 隔离
  - 产物按阶段命名：`generation` → `generation-cases.jsonl` + `summary.json`；`full` → 检索与生成产物并存（`generation-cases.jsonl` + `generation-summary.json`）；按 alpha 隔离且不混合
  - 新增 `mcnemar_exact()`：纯标准库两侧 exact 二项式检验，正确处理零 discordant pairs（p=1.0），返回可序列化字段；`compute_summary` 对生成结果自动计算 McNemar（拒答/false refusal 二元错误）
  - 新增 `build_failures_csv_rows()` + `write_failures_csv()`：B/C 按 case 对齐，win/loss/equal + graph lift/pollution/flip；无可靠 chunk 真值或拒答 case 不计相关性结论（outcome 为空 + notes）
  - `save_retrieval_results_by_alpha` 新增 `gen_results_by_alpha`/`include_retrieval` 可选参数；`save_results` 按结果类型写 `generation-cases.jsonl`
  - 新增 12 个测试：McNemar 边界（零 discordant/单侧/确定性/长度校验/序列化）、failures.csv（win/loss/flip/无真值排除/拒答/写回读）、生成网格复用检索结果、main phase 分支（generation 调用/retrieval 跳过）
  - `build_run_manifest` 优先读 `BASE_URL`（回退 `LLM_BASE_URL`），经 `_safe_url` 保留端口
  - 新增 `config_sha256`：config_path 存在时记录完整 SHA-256，不存在时为 None
  - index canonical 改为按 id 排序的 (id, metadata) 配对记录（重新排序不影响 hash）
  - KG canonical 扩展为 nodes + edges(含 weight) + entity_to_chunks + chunk_to_entities（排序） + fingerprint + manifest_version
  - `python_version` 始终写入当前 Python（不再因 import 失败丢失）
  - `main()` 空结果保护：`results_by_alpha` 为空时不崩溃
  - 新增 8 个测试：config hash 存在/变更/None、BASE_URL 端口脱敏/LLM_BASE_URL 回退、index 重排序稳定、KG hash 含 mapping+weight、python_version 始终存在、main(argv=None) 经完整 mock 链到 save helper
  - `compute_summary` 新增 `bootstrap_iterations`/`bootstrap_seed` 参数，内部用 `build_conversation_chains(cases)` 构建链映射并传给 bootstrap helper
  - `save_retrieval_results_by_alpha` 将 CLI 参数透传给每个 alpha 的 `compute_summary`
  - 新增 `_sanitize_cli_arg()`/`_sanitize_cli_args()`：REDACT `--token`/`--api-key`/`--secret`/`KEY=VALUE` 等凭据；`build_run_manifest` 自动调用
  - `main(argv=None)` 默认使用 `sys.argv[1:]`
  - `_safe_url` 修复：保留合法端口（`hostname:port`），移除 userinfo/query/fragment，IPv6 不崩溃
  - 新增 11 个测试：compute_summary multi-turn n_blocks < n_pairs、save helper 透传 bootstrap params、_safe_url port/IPv6/empty、CLI sanitizer token/KEY/URL 脱敏 + 普通参数保留 + manifest 集成
  - 修复 main() 中 alpha_values 在 build_query_plan_cache 调用前未定义（UnboundLocalError）；提前解析为唯一变量
  - 新增 `nearest_rank_percentile()`：p95 nearest-rank 替换旧 int(n*0.95) 取整；CLI 关键指标显示改用 retrieval_ms_p95
  - 新增 `paired_bootstrap_ci_cb()`：case-level paired bootstrap 95% CI，仅配对 answerable+has_chunk_truth，多轮按 block 重采样
  - `compute_summary` 中 paired_cb 改为 bootstrap helper；CLI 新增 --bootstrap-iterations/--bootstrap-seed
  - `build_run_manifest()` 重写：full git SHA、git_diff_sha256、dataset/corpus 完整 SHA-256、CLI args 快照、reranker mode/model、LLM endpoint 脱敏、依赖版本、index/KG snapshot SHA-256 + nodes/edges；敏感字段 REDACTED
  - 新增 15 个测试：bootstrap CI（种子可复现/全同 delta CI=均值/拒答+无真值排除/block 计数）、p95 nearest-rank（边界/中位数/空列表）、manifest（完整 SHA/URL 脱敏/CLI args/KG 同构同 hash/bootstrap 参数）
  - 新增 `validate_reranker()` helper：在 main() 中 QueryPlan 构建前检查 B/C 臂的 reranker 可用性，返回预检实例（A-only 返回 None），不可用时抛出 RuntimeError
  - `_run_retrieval_arm()` / `run_retrieval_grid()` 新增 `reranker` 参数：main() 将 validate_reranker 返回的实例注入到 grid，B/C 臂复用同一实例并直接调用 rerank；直接调用 _run_retrieval_arm 时仍保留 _get_reranker 防御性回退
  - 新增 `group_retrieval_results_by_alpha()` + `save_retrieval_results_by_alpha()`：按 alpha 分组和保存逻辑提取为独立生产 helper
  - `compute_summary()` 拒绝混合 alpha：收到多种 alpha 的 results 时直接 ValueError，防止 b_by_id 跨 alpha 覆盖
  - `build_run_manifest()` 新增 `active_alpha` 参数，manifest 传准确 alpha_values（不再传 None）
  - 新增 9 个单元测试：reranker 注入复用、alpha 混合拒绝、双 alpha 独立目录保存

- **P0 评测预检实现** — 完成评测方案 §11 中 P0 步骤的所有代码基础设施：
  - 新增 `evaluation/compare.py`：受控对比实验框架，A/B/C 三组共享 rewrite/decompose/embedding/reranker/生成，唯一差异为 Graph 通道和 reranker 开关
  - 修复 `evaluation/runner.py`：chunk 真值从 source 级扩大改为 snippet 级精确匹配（exact/overlap），不再系统性高估 Recall/nDCG；source ID 匹配优先使用 `source_name`（文件名）而非 SHA-256 hash
  - 修复 `evaluation/generation_runner.py`：`run_case()` 从自行拼装简化链路改为调用生产 `answer_query()` 完整管线（含 rewrite/decompose/reranker/parent-child/adjacent/citation validation）
  - 新增 `_meta_matches_source()`：解决数据集 source_id（文件名）与索引 metadata.source_id（SHA-256）不匹配问题
  - 新增 `_char_bigrams()`：中文友好的字符级 bigram 文本相似度计算，替代空格分词
  - 新增 `build_conversation_chains()`/`canonical_history_for_turn()`：多轮链构建和 canonical history 回放
  - 新增 `group_aware_split()`：多轮 chain 整体分配到同一侧的数据集拆分
  - 新增 `compute_answer_point_coverage()`：答案要点覆盖率计算
  - 新增 `_graph_enhanced_answer_query()`：Graph 增强的完整 answer_query（保留所有 Standard 步骤，仅替换检索为 Graph 增强）
  - 新增 CLI 入口：`python -m evaluation.compare --dataset v1 --corpus-dir test_texts --validate-only`
  - Ground truth 映射验证结果：87 entries, 60 exact, 27 overlap, 0 unmatched

- **P1 检索实验完成 — 结论：NO-GO**
  - 运行 A/B/C 三组受控检索实验（development split，95 条，alpha=0.7）
  - Graph 目标切片（21 条）context_recall C-B 差值：**-6.55pp**（门槛要求 ≥ +5pp）
  - 全部可回答查询（73 条）context_recall C-B 差值：**-5.54pp**（门槛要求下降 ≤ 2pp）
  - Graph pollution rate 19%：非相关 Graph chunk 挤出了 Standard 已召回的相关 chunk
  - 在线延迟翻倍：p50 从 750ms 增至 1524ms（C/B = 2.03，超出 ≤ 2.0 门槛）
  - 多轮切片严重退化：context_recall -21.43pp
  - 决策报告：`results/graph-gate/decision-report.md`
  - **不进入阶段 4**，保留 Standard RAG 作为生产默认
- **阶段 3.5：来源生命周期对账**

---

## 阶段 4 状态：NO-GO — 评测证明 Graph 无净收益

> 评测结果（2026-08-02）：受控 A/B/C 检索实验显示，Graph RAG 在目标切片的 context_recall **低于** Standard RAG 6.55pp（门槛要求 ≥ +5pp），且 Graph pollution rate 达 19%。延迟翻倍。
> 结论：**NO-GO**，不进入阶段 4。保留 Standard RAG 作为生产默认。详见 `results/graph-gate/decision-report.md`。

---
  - 新增 `compute_source_diff()`：计算 desired_paths 与当前索引的差异（to_add/to_update/to_remove/unchanged）
  - 新增 `sync_sources(desired_paths)`：同步索引到 desired-set 语义，删除多余来源、添加新文件、更新变更文件
  - 新增 `add_sources(delta_paths)`：只增不删模式，添加新文件/更新变更文件，不删除多余来源
  - `sync_sources()` 支持 `dry_run=True`：只计算差异不执行变更，用于展示差异并要求显式确认
  - CLI `--files` 语义文档化：sync 为 desired-set 语义，add 为增量语义
  - 新增 `tests/test_source_lifecycle.py`（9 个测试）
- **阶段 3.4：完整可观测性**
  - `src/metrics.py` 大幅增强：
    - `QueryMetric` 新增字段：index_ms、embedding_ms、rewrite_ms、decompose_ms、dense_ms、bm25_ms、rerank_ms、llm_ms、ttft_ms（分阶段延迟）
    - `QueryMetric` 新增字段：prompt_tokens、completion_tokens、total_tokens、citation_valid、citation_invalid（token 与引用）
    - `QueryMetric` 新增字段：rewrite_changed、rewrite_merge_overlap（rewrite 信息）
    - `MetricsRecorder` max_records 从 100 提升到 1000
    - `MetricsRecorder` 支持磁盘持久化（persist_path 参数），启动时自动加载历史记录
    - `summary()` 新增分阶段延迟统计、token 统计、引用有效率、rewrite 统计、context_k 统计
    - 向后兼容：旧格式记录（缺少新字段）加载时自动忽略
  - 新增 `tests/test_metrics_extended.py`（18 个测试）
- **阶段 3.3：持久化 Sparse / 增量更新**
  - `src/lexical.py` 新增 BM25 快照持久化与增量更新功能：
    - `save_bm25_snapshot()`：将 BM25 索引快照持久化到磁盘（原子写入）
    - `load_bm25_snapshot_from_disk()`：从磁盘加载快照，版本不兼容时返回 None 触发全量重建
    - `incremental_bm25_update()`：增量更新快照数据，只对新增/变更的 chunk 重新 tokenize，删除的 chunk 从快照移除
    - `build_bm25_from_snapshot()`：从快照数据构建 BM25 索引（跳过 tokenize 步骤）
    - `BM25_SNAPSHOT_VERSION = 2`：快照格式版本，旧版自动触发全量重建
  - 新增 `tests/test_bm25_persistence.py`（14 个测试）
- **阶段 3.2：数据目录与配置统一**
  - 新增 `src/config.py`：统一配置管理
    - `Settings` 数据类：集中管理所有配置项（data_dir、chroma_db_path、embedding/LLM 参数、安全限制、离线模式等）
    - `MNEME_DATA_DIR` 环境变量：控制数据目录，默认 `~/.mneme`，不再写入 `src/chroma_db`
    - `get_settings()` 全局单例，所有模块使用同一份配置
    - `ensure_dirs()` 自动创建数据目录
    - `to_dict()` 导出配置用于 status 展示
  - `CHROMA_DB_PATH` 改为从 Settings 动态计算，兼容旧路径
  - `DEFAULT_TEMPERATURE` 统一为 0.1（与 TUI/CLI 一致）
  - `.env.example` 新增 `MNEME_DATA_DIR`、`MNEME_OFFLINE`、`RAG_REFUSAL_THRESHOLD` 文档
  - 新增 `tests/test_config.py`（18 个测试）
- **阶段 3.1：单例模型与统一 LLM Gateway**
  - 新增 `src/llm_gateway.py`：统一 LLM 调用网关
    - `LLMErrorCategory` 枚举：错误分类（TIMEOUT/RATE_LIMIT/CONNECTION/AUTH/MODEL_NOT_FOUND/CONTEXT_LENGTH/SERVER_ERROR/CANCELLED/UNKNOWN）
    - `classify_error()`：将异常自动分类为 LLMErrorCategory
    - `get_or_load_model()`：进程级线程安全模型缓存，避免重复加载 embedding model
    - `llm_call()`：统一 LLM 调用入口，提供连接复用、timeout、有限重试+指数退避、并发控制、错误分类、token 统计
    - `llm_call_safe()`：安全版 LLM 调用，不抛异常，返回 (content, record)
    - `TokenUsage`/`LLMCallRecord` 数据类：token 使用量和调用记录
    - `get_call_summary()`：调用统计摘要（总调用数、错误率、平均延迟、token 用量、按类型/错误分类统计）
  - `answer_with_llm_history()` 和 `answer_with_llm_history_stream()` 改为通过 `llm_call()` 调用，不再各自创建 OpenAI client
  - `decompose_query_llm()` 改为通过 `llm_call_safe()` 调用
  - `rewrite_query_llm()` 改为通过 `llm_call_safe()` 调用
  - `tui/service.py` 的 `_ensure_model()` 改为使用 `get_or_load_model()` 进程级缓存
  - `prepare_index()` 改为使用 `get_or_load_model()` 进程级缓存
  - 增强 `should_decompose()` 守卫规则：中文简单问题（无多意图关键词、无中英混合、无分号分隔）跳过 LLM 拆解
  - 新增 `tests/test_llm_gateway.py`（31 个测试）
  - 修复 `test_query_decomposer.py` 和 `test_phase_c_quality.py` 适配 gateway
  - 新增 `src/rag_query_rewriter.py`：多轮对话查询改写模块
    - `should_rewrite()`：判断是否需要改写（无历史/过短/无代词则跳过）
    - `rewrite_query_llm()`：利用最近 5 轮历史将省略主语的追问改写为独立可检索问题
    - `merge_rewrite_results()`：合并原查询与改写查询的检索结果，去重取最优分数
    - `_PRONOUN_PATTERNS`：中英文代词/省略指示词正则匹配
    - `_QUESTION_STARTERS`：中文疑问词开头模式（怎么/如何/为什么/有哪些/有什么等）
  - 漂移防护：改写成功时额外用原 query 检索一路，合并去重，防止改写偏离丢失相关结果
  - `answer_query()` 和 `answer_query_stream()` 在查询拆解前先执行改写，改写后查询用于拆解和检索
  - 新增 `tests/test_query_rewriter.py`（24 个测试）
- **阶段 2.3：PDF/DOCX 重点解析增强 — 表格提取 + 字号标题检测 + 质量升级**
  - `pdf_loader.py` 新增 `_detect_heading_by_font_size()`：基于字号比例检测标题（众数字号 vs 最大字号）
  - `pdf_loader.py` 新增 `_format_table()`：将 pdfplumber 提取的二维表格格式化为 pipe-delimited 文本
  - `_extract_with_pdfplumber()` 集成 `page.extract_tables()` 提取表格，创建 TABLE 类型 Section
  - `_extract_with_fitz()` 返回 `table_count` 统计
  - `load()` 在 `table_count > 0` 时将 ParseQuality 从 NATIVE_TEXT 升级为 STRUCTURED
  - parser_version 升至 "2.0"
  - 新增 `tests/test_pdf_docx_parsing.py`（17 个测试）
- **阶段 2.2：Parent-Child/邻接扩展 — 小 chunk 召回 + 大 parent/邻接窗口回答**
  - `chunk_document()` 对超长 Section 创建 parent chunk（完整 Section 文本）+ child chunks（切分片段）
  - parent chunk 上限 `MAX_PARENT_CHUNK_CHARS=2000`，超过此长度的 Section 只创建 child chunks
  - child chunks 通过 `parent_chunk_id` 关联到 parent chunk
  - 新增 `expand_with_parent()`：召回 child chunk 时用 parent chunk 替换，提供更完整上下文
  - 新增 `expand_with_adjacent()`：召回 chunk 时自动包含前后相邻 chunk（max_expand=2）
  - `answer_query()` 和 `answer_query_stream()` 在 enrich_context 后依次应用 parent-child 扩展和邻接扩展
  - `chunks_to_index_data()` 输出 parent_chunk_id 和 chunk_type（parent/child/anchor）元数据
  - 新增 `tests/test_parent_child.py`（16 个测试）
- **阶段 2.1：标准文档模型 — Document → Section → Chunk 数据模型 + loaders/ 目录**
  - 新增 `src/domain.py` 文档结构模型：
    - `Section` 数据类：文档语义段落（标题、段落、表格等），含 heading_level、heading_path、page、char_start/end
    - `Chunk` 数据类：分块后的文本片段，保留 section_heading、section_type、parent_chunk_id
    - `Document` 数据类：解析后的文档，含 sections、chunks、parse_quality、parser_version
    - `SectionType` 枚举：HEADING/PARAGRAPH/TABLE/LIST/CODE/IMAGE/OTHER
    - `ParseQuality` 枚举：NATIVE_TEXT/STRUCTURED/OCR/LOW
    - `Document.is_low_quality` 属性：空文本页率 > 30% 视为低质量
  - 新增 `src/loaders/` 目录，将文档解析逻辑从 `src/rag.py` 迁移到独立模块：
    - `base.py`：`BaseLoader` 抽象基类 + `LoaderRegistry` 注册表
    - `pdf_loader.py`：PDF 解析器（PyMuPDF 优先/pdfplumber 降级），检测标题层级，计算解析质量
    - `docx_loader.py`：DOCX 解析器，提取段落标题层级和表格
    - `text_loader.py`：纯文本解析器，Markdown 检测 # 标题层级
  - 新增 `src/chunking.py`：基于 Section 边界的结构化分块
    - `chunk_document()`：优先在 Section 边界切分，超长 Section 二次切分
    - `chunks_to_index_data()`：将 Chunks 转换为索引所需数据
    - `CHUNKING_CONFIG_V3`：chunking version 升至 3
  - `_load_index_chunks()` 使用新 loader + chunking 模块，保留旧路径作为降级
  - `_build_context()` 在 chunk 前缀加入 `[Section: heading_path]` 信息
  - `format_sources()` 在来源信息中加入 `§ heading_path`
  - BM25 字段权重新增 `section_heading`（权重 1.5），标题路径参与 BM25 索引
  - PDF 标题检测正则：支持中文编号（一、二、）、括号编号（(1)/（2）），中文后空格可选
  - 低质量解析警告：`_load_index_chunks()` 在空文本页率过高时打印警告
  - 新增 `tests/test_document_model.py`（47 个测试）
- **阶段 1.6：引用闭环 — validate_citations 集成 + 一次修复 + 失败标记**
  - `answer_query()` 生成回答后自动调用 `validate_citations()` 校验引用 ID 合法性
  - 非法引用触发一次受限修复：`_repair_citations()` 将非法 ID 替换为数字最接近的合法 ID
  - 修复仍失败则标记 `unverified=True`，TUI 可据此展示警告
  - 新增 `_validate_and_repair_citations()` 和 `_repair_citations()` 函数
  - context_k 限制合法引用 ID 范围，确保只校验实际进入 prompt 的候选
  - 新增 `tests/test_citation_loop.py`（8 个测试）
- **阶段 1.5：拒答校准 — 可解释拒答特征 + RRF 阈值修复**
  - 修复 RRF `k=30` → `k=60`：降低单通道第一名的权重，使拒答阈值不再形同虚设
  - BM25 零分文档剔除：`rrf_merge()` 中 BM25 得分为 0 的文档不参与排名
  - 新增 `extract_refusal_features()`：从检索候选中提取可解释拒答特征（top_score、top1_top2_margin、effective_source_count、has_cjk 等）
  - 新增 `should_refuse_with_features()`：基于特征的拒答判断，支持 RRF 阈值（默认 0.015）和 Reranker 阈值（默认 0.3）
  - `QueryMetric` 新增 `refusal_type` 字段：区分 retrieval / generation / api_error 拒答
  - `_record_query_metric()` 自动推断拒答类型
  - 新增 10 个拒答特征提取和判断测试
- **阶段 1.4：Reranker + 来源多样性约束**
  - 新增 `src/retrieval.py`：Reranker Protocol、CrossEncoderReranker（延迟加载）、NoOpReranker（A/B 对比基线）、apply_source_diversity（每来源上限 3 个 chunk）
  - `answer_query()` 和 `answer_query_stream()` 在 RRF 融合后、`_build_context()` 前插入 reranker 步骤
  - Reranker 通过环境变量 `RAG_RERANKER` 控制：`"cross-encoder"` 启用，`"none"` 或未设置则不启用
  - 进程级 reranker 缓存，避免重复加载模型
  - 新增 `tests/test_retrieval.py`（11 个测试）
- **阶段 1.1+1.2：CJK n-gram tokenizer + 元数据字段加权 + 分块分隔符修复 + Embedding 对比工具**
  - 新增 `src/lexical.py`：CJK n-gram tokenizer（unigram + bigram）、元数据字段加权 BM25 语料构建、增量 BM25 索引构建
  - `_tokenize()` 委托给 `cjk_ngram_tokenize()`，连续 CJK 字符不再被当作一个 token
  - `build_bm25_index()` 委托给 `src/lexical.py`，支持 `metadatas` 参数实现字段加权
  - 分块分隔符加入中文标点 `。！？；`，`CHUNKING_CONFIG` version 升至 2
  - `index_fingerprint()` 包含 tokenizer 类型、chunking 版本、embedding 模型名，自动检测不兼容
  - 新增 `evaluation/embedding_benchmark.py`：Embedding 模型对比评测工具
  - 新增 `tests/test_lexical.py`（27 个测试）
  - 更新 `tests/test_retrieval_fix.py` 适配 n-gram tokenizer 行为
- **阶段 1.3：统一 Candidate 模型与 Top-K 语义** — 修复检索结果无统一数据模型和硬编码 top-5 的问题
  - 新增 `src/domain.py`：定义 `RetrievalCandidate`（检索候选，保留各通道原始分数和融合分数）、`RefusalFeatures`（拒答特征）、`CitationValidation`（引用校验结果）、`compute_context_k()`（基于 token budget 计算实际进入 prompt 的候选数）
  - 修复 `_build_context()` 硬编码 `[:5]` → 基于 `context_k` 参数动态计算
  - 修复 `format_sources()` 硬编码 `[:5]` → 与 `_build_context` 使用相同 `context_k`
  - 修复 `selected_count` 指标：记录实际进入 prompt 的数量而非 dynamic_top_k 的值
  - `QueryMetric` 新增 `context_k` 字段
  - 三层 K 语义明确：candidate_k（召回候选数）→ context_k（进入 prompt 数）→ display_k（展示来源数）
  - 新增 `tests/test_domain.py`（17 个测试）
- **Docker 支持** — 新增容器化部署，无需手动配置 Python 虚拟环境
  - `Dockerfile`：多阶段构建（builder + runtime），构建时预下载 `all-MiniLM-L6-v2` 嵌入模型，运行阶段不包含构建工具以减小镜像体积
  - `docker-compose.yml`：提供三种服务模式
    - `tui`（默认）：`docker compose up` 启动终端 UI，支持 `tty` + `stdin_open` 交互
    - `rag`：`docker compose run rag --files /data/xxx` 标准 RAG CLI
    - `graph-rag`：`docker compose run graph-rag --files /data/xxx` Graph RAG CLI
  - `.dockerignore`：排除 `.git`、`venv`、`chroma_db`、`models`、`docs` 等非运行文件
  - 数据持久化：`./data`（文档）、`./chroma_db`（向量索引）、`./models`（模型缓存）通过 volume 挂载
  - 环境变量通过 `.env` 文件自动注入，无需手动 `-e` 传递
  - 更新 `README.md` / `README.zh.md`，新增 Docker 安装方式（方式 A）
- **`mneme` 命令** — 注册 `console_scripts` 入口点，安装后可直接运行 `mneme` 启动 TUI（替代 `python -m tui`）
  - `pyproject.toml` 新增 `[project.scripts] mneme = "tui.__main__:main"`
  - `tui/__main__.py` 提取 `main()` 函数供 console_scripts 调用
  - `Dockerfile` ENTRYPOINT 改为 `mneme`
  - 更新 `README.md` / `README.zh.md` 启动命令
- **RAG 工程与使用效果改进报告** — 新增 `RAG-IMPROVEMENT-REPORT-2026-08-01.md`，基于当前实现与本地验证评估摄取、索引、检索、Graph RAG、回答引用、评测、性能、可观测性和安全，并给出分阶段实施路线图与验收指标
- **RAG 改进计划** — 新增 `plans/RAG-IMPROVEMENT-PLAN-2026-08-01.md`，基于改进报告制定四阶段实施计划：阶段 0 建立评测基线、阶段 1 修复 Standard RAG 核心闭环（中文 tokenizer、拒答校准、引用闭环、Top-K 统一）、阶段 2 结构化摄取与多轮检索、阶段 3 性能运维、阶段 4 条件性 Graph RAG 产品化；经审核修正 2 处事实错误（查询拆解守卫已存在、runner 函数名）、调整 3 处安排（拒答子集扩充至 25-30 条、Docker 修复提前至阶段 0、1.1/1.2 执行顺序依赖）、补充 4 项内容（CI 触发机制、holdout 子集、第一里程碑、schema/domain 边界）

### Added — 阶段 0：建立可比较基线

- **评测数据 schema** — 新增 `evaluation/schema.py`，定义 JSONL 评测标注格式
  - `EvalCase` 数据类：包含 `query`、`query_type`（6 类：single_fact / cross_document / metadata / multi_turn / no_answer / mixed_intent）、`language`（zh / en / mixed）、`relevant_source_ids`、`relevant_chunks`、`acceptable_answer_points`、`should_refuse`
  - `RelevantChunk` 数据类：标注具体相关段落（source_id、snippet、page、section）
  - 数据集 I/O：`save_dataset()` / `load_dataset()` 支持 JSONL 格式
  - 分层划分：`split_dataset()` 按 query_type 分层，12% holdout，seed=42 可复现
  - 完整性校验：`validate_dataset()` 检查 ID 唯一性、拒答矛盾、类型覆盖
- **评测数据集 v1** — 新增 `evaluation/datasets/v1.jsonl`，110 条评测用例
  - 覆盖 6 类查询：single_fact 35、metadata 16、no_answer 25、cross_document 13、mixed_intent 11、multi_turn 10
  - 语言分布：中文 46、英文 46、中英混合 18
  - 基于项目 test_texts/ 中的 6 份文档（2 份中文、4 份英文）标注
  - 训练集 97 条 + holdout 集 13 条
- **标注规范文档** — 新增 `evaluation/ANNOTATION_GUIDE.md`
- **检索评测指标** — 新增 `evaluation/metrics.py`
  - Recall@K、MRR、nDCG@K、Source Recall@K
  - `compute_retrieval_metrics()`：聚合指标计算
  - `compute_stratified_metrics()`：按语言/查询类型分层报告
- **检索评测 Runner** — 新增 `evaluation/runner.py`
  - `RetrievalRunner`：调用 Mneme 实际 parser/embedding/Chroma/BM25/RRF 链路
  - 逐例输出候选列表与 Recall@K、MRR、nDCG、source recall 指标
  - 按语言和查询类型分层报告
  - 拒答准确率评估
- **生成与引用评测** — 新增 `evaluation/generation_runner.py` 和 `evaluation/citation_metrics.py`
  - `GenerationRunner`：在检索结果基础上调用 LLM 生成回答
  - `CitationValidator`：调用 `src/citations.py` 的 `validate_citations()` 校验引用 ID 合法性
  - 引用 ID 有效性、引用精确率/召回率、faithfulness、拒答准确率
  - 生成评测独立运行，不把检索失败和生成失败混为一谈
- **评测 CLI 入口** — 新增 `evaluation/run.py`
  - `python -m evaluation.run --dataset v1 --output results/baseline.json`
  - 支持 `--validate-only`、`--corpus-dir`、`--verbose`、`--per-case-output`
- **CI 三层分层** — 修改 `.github/workflows/ci.yml`
  - Layer 1：快速纯单元测试，每次 PR 必跑
  - Layer 2：离线检索评测，main 分支 push / path-based / label-based / 每日定时触发
  - Layer 3：完整生成评测，仅通过 `run-generation-eval` label 手动触发
  - 检索回归检测：recall@5 低于阈值则标记失败
- **Docker 模型遮蔽修复** — 修复 bind mount 遮蔽镜像内预下载模型的问题
  - 新增 `docker-entrypoint.sh`：启动时检测挂载目录是否为空，若空则从 `/app/models-image` 恢复预下载模型
  - `Dockerfile`：预下载模型存入 `/app/models-image`（备份位置），挂载点仍为 `/app/models`
  - `docker-compose.yml`：所有服务使用 `docker-entrypoint.sh` 包装

### Tests

- 新增 `tests/test_eval_schema.py`：15 个测试（序列化、I/O、划分、校验）
- 新增 `tests/test_eval_metrics.py`：19 个测试（Recall@K、MRR、nDCG、Source Recall、聚合、分层）
- 新增 `tests/test_eval_citation_metrics.py`：21 个测试（引用有效性、精确率/召回率、faithfulness、拒答准确率）

### Removed

- 删除 `docs/` 目录（VitePress 文档站点及相关资源）

### Added

**Mneme VitePress 文档展示站**

- 新增 `docs/` 目录，使用 VitePress 构建静态文档站点：
  - 首页：Hero 区（Logo + 标语 + CTA）+ 6 个 Feature 卡片 + Quick Preview 代码块
  - 指南：快速开始、配置参考、TUI 命令速查
  - 功能文档：混合检索、Graph RAG、查询拆解、安全设计
  - 博客：中英文双语技术博客（原 `mneme-technical-blog-*` 迁移）
  - 参考：配置项速查表、支持文件类型、更新日志
  - 关于：项目愿景、架构原则、MIT License
- 自定义主题样式，匹配 TUI 的 Obsidian 深紫配色（`#a78bfa` 品牌色）
- 内置本地搜索、暗色/亮色模式切换、代码行号
- 新增 GitHub Actions 工作流 `.github/workflows/docs-deploy.yml`，构建后自动推送到 `realhenrylan.github.io` 仓库
- Logo 资源复制到 `docs/public/mneme-logo.svg` 供站点引用

**新增 Mneme 双语技术博客**

- 新增 `mneme-technical-blog-zh.md` 和 `mneme-technical-blog-en.md`，从混合检索、Graph RAG、索引一致性、引用边界、端点安全、TUI 并发模型和测试策略介绍当前项目实现。

**项目综合改进评估报告**

- 新增 `plans/2026-07-20-project-optimization-assessment.md`，记录索引一致性、测试与依赖、数据安全、性能、检索质量、架构与发布的改进建议及实施优先级。

**Embedding 模型加载支持本地路径和 ModelScope 自动下载**

- 新增 `_load_sentence_transformer()` 函数，统一模型加载逻辑：
  - 优先从本地路径加载（通过 `EMBEDDING_MODEL_PATH` 环境变量指定）
  - 本地没有时，**自动从 ModelScope 下载**（国内网络友好，无需登录）
  - 下载失败时给出清晰的错误提示和解决指引
- 修改 `src/rag.py`、`src/graph_rag.py`、`tui/service.py` 中所有 `SentenceTransformer()` 直接调用，改为使用 `_load_sentence_transformer()`
- 更新 `.env.example`，添加 `EMBEDDING_MODEL_PATH` 配置示例和 ModelScope 下载指引
- 默认关闭 Hugging Face 联网（`HF_HUB_OFFLINE=1`），避免首次启动时尝试连接 Hugging Face
- 新增依赖 `modelscope>=1.0.0`，确保 ModelScope 下载功能可用

### Changed

**Preserve the original logo glyphs in the transparent SVG**

- Rebuilt `.github/images/mneme-logo.svg` from the original logo pixels instead of substituting a system font.
- Removed the black background while preserving the original glyph shapes and antialiasing.
- Removed the obsolete PNG asset now that the SVG is self-contained.

**Replace the README PNG logo with a transparent SVG wordmark**

- Updated the README logo reference to `.github/images/mneme-logo.svg`.
- The new logo contains only the purple `MNEME` letters and has no background.

**消除 rag.py 与 graph_rag.py 之间的 CLI 循环代码重复（Issue #6 DRY 重构）**

- 新增 `src/cli_loop.py`，将 `rag.py` 和 `graph_rag.py` 的交互式 CLI 循环代码提取为公共模块
  - `run_interactive_session()`: 统一的交互式问答循环入口
  - `run_single_query()`: 单次查询（供 `--query` 路径使用）
  - `_print_elapsed()`: 统一计时打印格式
  - `_parse_add_paths()`: 解析 `+add` 命令中的文件路径，兼容全角逗号
  - `_graph_rag_answer()`: Graph RAG 回答生成（封装 6 步 pipeline）
- 重构 `rag.py` 的 `__main__` 使用 `cli_loop.run_interactive_session()`
- 重构 `graph_rag.py` 的 `main()` 使用 `cli_loop.run_interactive_session()` 和 `run_single_query()`
- 移除 `rag.py` 的 `--query` 死参数（原参数从未被使用）
- 新增 `_ensure_client_and_check_rebuild()` 辅助函数，消除 `prepare_index` 和 `prepare_graph_index` 中的重复逻辑（创建 PersistentClient + 判断 need_build）
- 新增测试：`tests/test_cli_loop.py`（9 个测试覆盖辅助函数和交互流程）
- 新增测试：`tests/test_prepare_index_helper.py`（3 个测试覆盖 helper 边界条件）

**消除重复定义与 sys.path 散落（Issue #7 DRY 重构）**

- 新增 `src/rag.SUPPORTED_EXTENSIONS`，统一扩展名列表（原 `TEXT_EXTENSIONS` 不含 `.pdf`/`.docx`，`_SUPPORTED_EXTENSIONS` 在 `tui/constants.py` 中重复定义）
- `tui/constants.py` 和 `tui/screens/home.py` 改为从 `src.rag` 导入 `SUPPORTED_EXTENSIONS`
- `_collection_exists()` 从 `tui/screens/home.py` 移除重复实现，统一从 `src.rag` 导入
- 移除 15 处 `sys.path` 运行时注入（`src/rag.py`、`src/graph_rag.py`、`tui/service.py`、`tui/screens/home.py`、`scripts/run_temperature_test.py` 及 10 个测试文件）
- `src/graph_rag.py` 中所有隐式绝对导入 `from rag import` 改为显式绝对导入 `from src.rag import`
- `tui/service.py` 和 `scripts/run_temperature_test.py` 中 `from graph_rag import` 改为 `from src.graph_rag import`
- 新增 `pyproject.toml` 支持 `pip install -e .` 可编辑安装
- 更新 `README.md` 启动说明（包含 `pip install -e .` 和 `PYTHONPATH` 两种方案）

**`_get_llm_client()` 改为模块级单例模式**

- 增加模块级 `_llm_client` 变量，`_get_llm_client()` 内部做惰性初始化
- 避免每次调用都新建 `OpenAI` 客户端实例，减少不必要的对象创建开销
- 对调用方完全透明，已有 mock 测试不受影响
- 新增 `tests/test_llm_client_singleton.py`（2 个 TDD 测试覆盖单例行为和环境变量读取）

### Fixed

**Skip LLM client initialization for empty graph batches**

- Return an empty entity-result list before validating `BASE_URL` when no chunks are provided, keeping empty graph builds offline and deterministic.

**P0 release closure: Graph RAG safety, endpoint policy, and Windows cleanup**

- Replaced executable Graph RAG pickle caches with schema-validated atomic JSON; legacy `.pkl` files are invalidated without being loaded.
- Bound the Graph RAG LLM client cache to the current API key and base URL so endpoint changes take effect immediately.
- Added shared HTTPS-by-default endpoint validation, remote-data disclosure in onboarding, document size/page/path limits, and a bounded remote context.
- Ensured the configured embedding model identifier is used consistently for ModelScope fallback and diagnostics.
- Added explicit Chroma client shutdown and fail-fast Windows test cleanup; cleanup failures are now visible instead of being ignored.
- Added P0 regression coverage for cache schema, client refresh, endpoint policy, resource limits, context bounds, and model fallback.
- Fixed remote-context truncation so source metadata and untrusted-document boundaries always remain complete; chunks are skipped when the safety frame cannot fit.
- Refreshed the bilingual README with current CLI commands, manifest/citation safety behavior, endpoint disclosure, resource limits, embedding fallback, project structure, and test instructions.

**Phase C: retrieval quality, evidence safety, and serialized index operations**

- Added deterministic retrieval benchmark utilities for Recall@k, MRR, nDCG, and configurable quality gates, with a checked-in smoke benchmark under `benchmarks/retrieval_quality.json`.
- Added query-local citation IDs (`S1`, `S2`, ...), source paths, PDF page locations, chunk IDs, and explicit untrusted-document boundaries for prompt-injection resistance.
- Added a configurable low-evidence refusal threshold so the LLM is not called when retrieval cannot provide sufficient support.
- Added a serialized TUI index queue, immutable query snapshots, bounded privacy-preserving runtime metrics, and incremental BM25 tokenization reuse.
- Added Phase C regressions for quality gates, citations, prompt-injection boundaries, refusal behavior, queue serialization, snapshots, and lexical cache reuse.

**Phase B: manifest-consistent indexing and atomic source updates**

- Added an atomic per-collection manifest with content hashes, source chunk IDs, embedding configuration, chunking configuration, and monotonically increasing manifest versions.
- Source additions, modifications, and deletions now update Chroma, the BM25 snapshot, and manifest sidecars together with rollback on failed commits.
- Graph RAG caches and TUI/CLI state now carry and validate the same manifest version; added end-to-end regressions for modification, deletion, same-name sources, duplicate text, and rollback.

**完成阶段 A：可靠底座修复**

- 测试清理改为跨平台实现，注册 `integration` marker，并通过 `MNEME_RUN_INTEGRATION=1` 将真实 LLM 测试设为显式开关；新增 Windows/Linux CI。
- 锁定 `pyproject.toml` 与 `requirements.txt` 的直接依赖版本，避免 ChromaDB 等依赖漂移。
- 配置保存失败时不再输出完整 API Key，增加明文密钥回归测试。
- 为索引 chunk 增加 `source_id`、规范化 `source_path`、`chunk_id` 和内容哈希；来源更新按精确来源替换，删除不再按 basename 匹配，重复文本检索和引用改用稳定 chunk ID。
- Graph RAG 缓存绑定当前索引指纹，来源新增、修改或删除后自动失效并重建；文件监听补充修改事件处理。

**Graph RAG 实体提取模型名不再硬编码**

- 修复 `src/graph_rag.py:83` 中 `model="deepseek-chat"` 硬编码问题
- 现在使用 `os.getenv("LLM_MODEL", DEFAULT_LLM_MODEL)`，优先读取环境变量，否则回退到 `DEFAULT_LLM_MODEL`
- 用户通过 TUI `/settings` 或环境变量切换模型后，Graph RAG 实体提取将使用正确的模型

**Graph RAG 全连接子图噪音修复（Dense Graph Fix）**

- `KnowledgeGraph.build_from_chunks()` 原逻辑对每个 chunk 的实体集合建立完全子图（所有实体两两连边），导致大量弱共现噪音
  - 实际问题：4046 实体产生 38755 条边（最大可能边数 8,183,035），平均度 19.2，图密度 0.47%，`get_related_entities()` 几乎返回全部邻居
- 修复方案：组合方案（方案 C），引入两个新参数：
  - `min_cooccur: int = 2` — 两个实体至少在 N 个 chunk 中共现才建边，过滤偶然共现噪音
  - `max_entities_per_chunk: int = 20` — 每 chunk 仅前 N 个实体参与建边，防止完全子图指数爆炸
- 实现方式：两趟法
  - 第一趟：逐 chunk 统计实体对共现次数（`cooccur_counts` dict）
  - 第二趟：按 `min_cooccur` 阈值过滤后建边
- 参数设计：`max_entities_per_chunk` 仅影响建边过程，`entity_to_chunks` 映射始终记录全部实体
- 向后兼容：默认值 `min_cooccur=2, max_entities_per_chunk=20`，调用方无需修改；如需恢复原行为，显式传 `min_cooccur=1, max_entities_per_chunk=sys.maxsize`
- 新增测试：`TestDenseGraphFix`（6 个 TDD 测试覆盖阈值过滤、截断边界、向后兼容、空 chunks、单实体、entity_to_chunks 完整性）
- 预期效果：边数从 ~38755 降至 ~3000-8000，平均度从 19.2 降至 ~2-4，图区分度显著提升

**Graph RAG 实体行静默丢弃 Bug**

- 修复 `extract_entities_llm_batch()` 中 LLM 返回的实体行以 `-`、`*`、`·` 开头时被静默丢弃的问题
- 根因：原逻辑 `elif line and not line.startswith(("-", "*", "·"))` 将所有以这三个字符开头的非空行过滤掉
- 修复：使用 `line.lstrip("-*· ")` 剥离列表标记前缀，保留实体文本
- 新增 `tests/test_graph_rag_batch.py::TestEntityParseWithListPrefix`（8 个参数化测试覆盖各种前缀场景）

**Graph RAG 模式下 enrich_context 集成缺失**

- 修复 Graph RAG 的 4 条查询路径未调用 `enrich_context` 的问题，导致 anchor chunk 未被 PDF 首页全文替换
- 影响路径：`graph_rag_pipeline()`、`--query` CLI、交互式循环、`graph_query_stream()`
- 新增 `tests/test_graph_rag_enrich.py`（4 个 TDD 测试覆盖全部路径）

## [1.1.0] - 2026-07-04

### Added

**首次启动引导向导 (Onboarding Wizard)**

新增首次启动引导流程，在检测到 `.env` 缺失或 `API_KEY`/`BASE_URL` 为空时自动启动：

- **Step 0**: 欢迎页 — 展示 Mneme 系统介绍和功能概述
- **Step 1**: Provider 选择 — 支持 DeepSeek、OpenAI、自定义三种 Provider
- **Step 2**: API Key 配置 — 输入 API Key，带格式校验（不以 `sk-` 开头时提示确认）
- **Step 2b**: Base URL 配置 — 仅自定义 Provider 需要手动输入
- **Step 3**: LLM 模型选择 — 根据 Provider 联动显示可用模型列表
- **Step 4**: 功能速览 — 展示 `/files`、`/settings`、`/mode` 等命令用法
- 配置完成后自动保存到 `.env` 文件并同步到环境变量

**Provider 与模型联动配置**

| Provider | Base URL | 可选模型 |
|----------|----------|----------|
| DeepSeek | `https://api.deepseek.com/v1` | deepseek-chat, deepseek-reasoner |
| OpenAI | `https://api.openai.com/v1` | gpt-4o, gpt-4o-mini, gpt-3.5-turbo |
| 自定义 | 手动输入 | 手动输入 |

**新增文件**

| 文件 | 说明 |
|------|------|
| `tui/env_check.py` | 无重依赖环境检测模块，供测试直接导入 |
| `tui/logo.py` | 共享 LOGO 常量模块，避免重复定义 |
| `tui/screens/onboarding.py` | 引导向导主逻辑 |
| `tests/test_onboarding.py` | 13 个测试用例（含 LOGO 复用验证） |

**修改文件**

| 文件 | 变更 |
|------|------|
| `tui/app.py` | 从 `env_check` 导入 `need_onboarding`，`run()` 中添加引导跳转 |
| `tui/screens/home.py` | 从 `logo.py` 导入 LOGO（删除重复定义） |
| `tui/screens/onboarding.py` | 从 `logo.py` 导入 LOGO（删除重复定义） |

**测试覆盖**

- `TestNeedOnboarding`: 5 tests — 触发条件 + 空白字符边界
- `TestOnboardingFlow`: 6 tests — 正常完成、取消、Ctrl+C、自定义 Provider、自定义模型、OpenAI 流程
- `TestLogoReuse`: 2 tests — LOGO 对象同一性 + 导入路径静态检查

### Changed

- `README.md` / `README.zh.md` 新增「首次启动 / First-Time Setup」章节，说明引导向导流程

---

## [1.0.3] - 2026-07-04

### Fixed

**错误场景不再显示 Sources**

- 修复 LLM 调用失败（RateLimitError/APIConnectionError/APIError）时同时显示错误消息和 Sources 的问题
- 新增 `LLMError` 自定义异常类，统一 LLM 错误处理
- `answer_with_llm_history_stream` 从 `yield` 错误消息改为 `raise LLMError`
- `answer_query_stream` 和 `graph_query_stream` 添加生成器包装器，捕获异常并通过 `_mneme_error` 信号传递
- `chat.py` 根据 `_mneme_error` 信号决定是否显示 Sources
- 新增 13 个 TDD 测试覆盖错误场景

---

## [1.0.2] - 2026-07-04

### Fixed

- 修复 `/settings` 中 **Temperature、Alpha、Top-K Min/Max** 四个设置项在重启后丢失的问题：
  - `RagApp.__init__()` 新增从 `.env` 读取 `LLM_TEMPERATURE`、`ALPHA`、`LLM_TOP_K_MIN`、`LLM_TOP_K_MAX`
  - `/settings` 修改设置写入 `.env` 后，重启应用将自动恢复上次保存的值

---

## [1.0.1] - 2026-07-03

### Fixed

**Issue #3: 多线程无锁写入 `_entity_cache` + 批量 API 调用形同虚设**

- 移除 `build_from_chunks` 中的 `ThreadPoolExecutor`，消除无锁并发写入 `_entity_cache` 的数据竞争风险
- 修复批量处理被错误调用的问题：之前每个 chunk 单独调用一次 API，现在正确批量处理（减少 80% API 调用）
- 新增 `batch_size` 参数控制批量大小，默认为 5
- `max_workers` 参数标记为废弃，传入非默认值时发出 `DeprecationWarning`
- 新增 `progress_callback` 参数支持增量进度回调

### Added

- 新增 `tests/test_graph_rag_batch.py` 测试文件，覆盖批量处理、向后兼容性、异常处理等场景

---

## [1.0.0] - 2026-07-03

### Added

- Initial release of Mneme (née RAG system) with TUI
- Core RAG pipeline with hybrid retrieval (BM25 + ChromaDB vector search)
- Graph RAG mode with knowledge graph construction
- Query decomposition for complex questions
- Hierarchical document enrichment (anchor chunk strategy)
- Rich-based terminal UI with interactive settings
- PDF, DOCX, Markdown, and text file support
- Temperature testing framework for model evaluation
- Comprehensive test suite with unit and integration tests

### KISS 原则重构 (2026-07-01)

#### `rag.py`

**文件类型检测简化**
- 删除 `MAGIC_SIGNATURES`、`read_magic_bytes()`、`check_magic_bytes()`、`is_text_content()`、`detect_office_type()` (~70 行死码)
- `detect_file_type()` 重写为纯扩展名判断

**rag_pipeline 索引入口合并**
- `rag_pipeline` 改为调用 `prepare_index()`，与 CLI 走同一条路径
- 消除了重复调用时产生重复向量条目的隐式 bug

**rag_pipeline 消除与 answer_query 的重复**
- 检索→dynamic_top_k→构建 context→LLM 生成的 16 行代码替换为单行 `answer_query(...)` 调用
- 消除 `" ".join` vs `"\n\n".join` 的不一致问题

**清理**
- 修复过时注释（魔数检测相关）
- 删除 `build_index` 中未使用的 `doc_id` 变量
- 修复 `prepare_index` 返回值注解
- `get_splitter` 嵌套字典展开为平铺 if/elif

**安全修复**
- `TEXT_EXTENSIONS` 中删除 `".env"`，阻止 API Key 文件被纳入检索池
- `build_index` 增加两重过滤：拒绝含 `..` 的路径，拒绝 `.env` 文件
- 新增 `SYSTEM_PROMPT` 常量，指令放入 `{"role": "system"}` 消息，与文档内容隔离
- 移除 `RAG_PROMPT_TEMPLATE` 和 `prompt_template` 参数

#### `graph_rag.py`

**真实分数替代伪造分数送 dynamic_top_k**
- `graph_augmented_retrieve` 返回类型由 `list[str]` 变为 `tuple[list[str], list[float]]`
- `graph_rag_pipeline` 移除 `scores = [1.0/(i+1) ...]` 伪造逻辑

**代码清理**
- 删除 `zip()` 教学注释 (12 行)
- 简化 `extract_entities_llm_batch` 缓存逻辑，删除辅助结构 (~20 行)
- 删除未使用的 `verbose = True`
- 删除未使用的 import (`re`, `json`, `asyncio`)
- 删除未使用的 `method` 参数（`extract_entities_from_query`）
- 删除 `collection.get()` 教学注释
- 删除未使用的 `rebuild_graph` 参数（`graph_rag_pipeline`）
- 恢复异常处理，删除空循环
- 删除 `all_results` 未使用变量
- 删除 `cooccur_window` 死参数
- 删除三引号悬空字符串
- 更新 docstring 返回值描述

**安全修复**
- 移除模块级 `_llm_client: Optional[OpenAI] = None` 全局变量及缓存逻辑
- `_get_llm_client()` 每次新建 client，key 随局部变量 GC 回收

### Graph RAG 改进 (2026-07-01)

- **索引只建一次，循环内复用**: 新增 `prepare_graph_index()` 函数，检查 collection 是否已存在；`graph_rag_pipeline` 中 `force_rebuild` 默认值从 `True` 改为 `False`
- **实现 `+add` 中途添加文件**: 导入 `add_files_to_index`，对话循环中增加 `+add` 分支
- **补齐 CLI 参数**: 新增 `--files`, `--collection`, `--rebuild`, `--query`, `--alpha`
- **显示参考来源**: `graph_augmented_retrieve` 返回值扩展为 `(indices, docs, scores)`
- **修复 Prompt 与解析不一致**: 删除无效指令行
- **实体提取截断从 500 提升到 1500**
- **融合重构 + alpha 权重修复**: `merged` 从 `list` 改为 `dict[str, float]`
- **修复 Collection 名称哈希碰撞**: `"".join` → `"|".join`
- **`_entity_cache` 改用文本 hash 作 key**
- **清理 unused imports + 类名**: `knowledgegraph` → `KnowledgeGraph`（PEP8）
- **图谱为空时给出提示**: 退化为纯语义检索时打印警告
- **修复 `get_related_entities` 大小写敏感匹配**: `seed_nodes` 查找改为大小写不敏感

### RAG TUI 前端 (2026-07-01)

基于 Python Textual 框架构建类 opencode 风格的 TUI 前端，支持 Standard RAG 和 Graph RAG 两种模式。

**新增文件:**

```
tui/
├── __init__.py
├── __main__.py
├── app.py                  # RagApp 主类 + 路由 + 全局 reactive 状态
├── service.py              # LocalRagService Thin Wrapper
├── theme.py                # Obsidian 深紫配色常量
├── theme.tcss              # Textual CSS 样式
├── keys.py                 # 快捷键 + Slash 命令定义
├── routes/
│   ├── home.py             # Home 页
│   ├── chat.py             # Chat 页
│   └── settings.py         # Settings 页
├── components/
│   ├── message.py          # UserMessage / AssistantMessage / ThinkingMessage
│   ├── prompt.py           # PromptInput
│   ├── sidebar.py          # 侧边栏
│   ├── footer.py           # 底部状态栏
│   ├── loading.py          # LoadingScreen
│   └── error.py            # ErrorWidget
└── dialogs/
    ├── command_palette.py  # Ctrl+P 命令面板
    ├── file_manager.py     # /files 文件管理
    ├── model_select.py     # /models 模型选择
    ├── status.py           # /status 系统状态
    └── help.py             # /help 帮助
```

**后端修改:**
- `rag.py`: `answer_with_llm_history_stream()`, `answer_query_stream()`, `remove_file_from_index()`
- `graph_rag.py`: `graph_query_stream()`, `KnowledgeGraph.build_from_chunks()` 新增 `progress_callback`

**Service 层**: `LocalRagService` — 进程内直调 Thin Wrapper，缓存 SentenceTransformer，阻塞操作通过 `asyncio.to_thread()` 包装

**TUI 功能:**
- Home 页: ASCII Logo + Standard/Graph 模式单选 + 文件路径输入 + Collection 名称
- Chat 页: 流式 LLM 回答 + 嵌入式来源引用 + 侧边栏 + 命令分发
- 快捷键: Ctrl+P 命令面板、Ctrl+L 侧边栏、Ctrl+N 新建、Ctrl+K 清空、Ctrl+C 退出
- Slash 命令: /files /models /settings /mode /alpha /rebuild /status /clear /export /help /quit
- 配色: Obsidian 深紫（#1e1a2e 背景 + #a78bfa 强调色）

**审计修复:**
- 第一轮 (5 P0 + 4 P1): `reactive(list)` 崩溃、对话框无法打开、CommandPalette 不执行、Graph add 后 KG 未更新、Standard→Graph 切换崩溃、FileAction 无 handler、/rebuild /export 无处理、settings.py 缺失
- 第二轮: SettingsScreen `.env` 路径修复

### 检索修复 + 查询拆解 + 分层 Enrich (2026-07-02)

#### `rag.py`

**PyMuPDF 优先策略**
- `load_pdf()` / `load_pdf_pages()` 先试 `fitz`，失败降级 `pdfplumber`
- PyMuPDF `page.get_text("text")` 保留 word 空格，修复 `UniversityofPennsylvania` 拼接问题

**Tokenize 重构**
- 新增 `_STRIP_PUNCT` + `_tokenize()`：支持双语/大小写/标点
- `build_bm25_index` 和 `retrieve_hybrid_with_sources` 改用 `_tokenize`

**Anchor chunk 生成**
- `build_index` / `add_files_to_index`：取 PDF 首页 `splitlines()[:5]` 作为 anchor chunk
- `rrf_merge` 增加 `documents`/`metadatas` 参数，anchor chunk RRF score ×2 提升

**Default 参数调整**
- `DEFAULT_TOP_K`: 20 → 70
- `DEFAULT_MIN_K`: 3 → 12
- `DEFAULT_MAX_K`: 20 → 70
- `DEFAULT_TEMPERATURE`: 0.1 → 0.2

**`prepare_index` 重构**
- 接受 `progress_callback` 参数
- `force_rebuild` 逻辑移到 `prepare_index` 层

**查询拆解 + 并发检索**
- 调用 `decompose_query_llm()` 拆解查询，`ThreadPoolExecutor` 并发执行子查询
- `best_score` dict 按 chunk 去重
- `enrich_context()`：anchor 命中时用首页全文替换 snippet

**流式接口**
- `answer_with_llm_history_stream()` / `answer_query_stream()`
- 错误处理：`RateLimitError` / `APIConnectionError` / `APIError`

#### `graph_rag.py`

- `KnowledgeGraph` 持久化：`save()` / `load()` — pickle 序列化
- `build_graph_index` / `build_from_chunks` / `prepare_graph_index` 传播 `progress_callback`
- CLI 对齐：暴露 `temperature` 参数

#### 测试与工具

| 文件 | 说明 |
|------|------|
| `test_retrieval_fix.py` | 8 项回归测试 |
| `test_query_decomposer.py` | 5 mock + 2 集成 + 2 回归 (9 项) |
| `test_hierarchical_enrich.py` | 4 单元 + 2 端到端 (6 项) |
| `fix_scoring.py` | 评分分析工具 |
| `generate_report.py` | 报告生成工具 |
| `run_temperature_test.py` | temperature 对比测试 |

#### 项目文件重组

- `rag.py` / `graph_rag.py` / `rag_query_decomposer.py` → `src/`
- 测试文件 → `tests/`
- 分析工具 → `scripts/`
- 废弃文件 → `archive/`
- `test_report/` → `reports/`

#### 计划文档

| 文件 | 摘要 |
|------|------|
| `plans/1782828324650-retrieval-fix-plan.md` | 检索修复计划 |
| `plans/1782828324650-query-decomposer-plan.md` | 查询拆解计划 |
| `plans/1782828324650-hierarchical-enrich-plan.md` | 分层 enrich 计划 |
| `plans/1782828324650-tui-rewrite-rich.md` | TUI 重写计划 |
| `plans/1782828324650-add-files-mid-session.md` | 会话中添加文件计划 |
| `plans/1782828324650-graph-rag-improvements.md` | Graph RAG 改进计划 |
| `plans/1782828324650-p0p1-security-fix-plan.md` | 安全修复计划 |
| `plans/1782828324650-review-verification.md` | 代码审阅验证 |
| `plans/1782828324650-retrieval-failure-report.md` | 检索失败分析 |
| `plans/rag-tui-frontend.md` | TUI 前端计划 |
| `plans/rag-first-principles-analysis-report.md` | 第一性原理分析 |
| `plans/SciClaw RAG技术总结.md` | 技术调研 |
| `plans/temperature-test-questions.md` | 测试问题集 |

### Security

#### [#1] - API Key Protection & .env Parser Fix (2026-07-03)

**#1a: API Key Exposure Prevention**
- Added `_mask_api_key()` to mask API keys in TUI (displays `sk-...xxxx` format)
- API keys no longer displayed in plaintext in settings interface
- `.env` file protected by `.gitignore` (not tracked in git history)

**#1b: .env Parser Hardening**
- Replaced fragile custom `_read_env`/`_write_env` with `python-dotenv` standard API
- Fixed handling of values containing `=`, `#`, quotes, and newlines
- Automatic quoting via `set_key()` prevents malformed `.env` entries
- Added 21 unit tests covering all edge cases

**Files Changed:**
- `tui/screens/chat.py`: Refactored env parsing, added masking
- `tests/test_env_security.py`: 21 new tests (all passing)
- `.env.example`: Added template file

### Changed

- `_toggle_mode()` in TUI now shows progress bar during knowledge graph construction
- Graph RAG knowledge graph files saved to `chroma_db/` directory

### Fixed

- [#1] Custom `.env` parser failed on values with `=`, `#`, quotes, or newlines
- [#1] `_mask_api_key` prefix calculation corrected (`key[:3]` = `"sk-"`)
- `build_bm25_index([])` 在空文档列表时触发 `ZeroDivisionError`（已知问题，CLI 主流程 `if not all_docs: exit(1)` 可正常退出）

### Format Sources & Cleanup

- `format_sources` docstring 精简：9 行示例输出替换为 1 行简洁描述
- `graph_rag.py` 删除未使用的导入（`detect_file_type`, `RAG_PROMPT_TEMPLATE`）
- 删除误导性注释（`EXTRACT_PROMPT_BATCH` 后）
- 删除 `entity_method` 死参数链（`build_from_chunks`, `graph_augmented_retrieve`, `build_graph_index`, `graph_rag_pipeline`）
- 修复 `graph_augmented_retrieve` 返回值注解

---

## [Unreleased]

### Added

- **自动目录监控 (File Watcher)** — 用 `watchdog` 替换 `/files → add` 交互流程
  - `tui/file_watcher.py`: `FileWatcher` 类，监听 `created`/`moved`/`deleted` 事件，2 秒防抖，dotfile/temp 文件过滤
  - `tui/constants.py`: 共享 `_SUPPORTED_EXTENSIONS` 常量，消除 `chat.py` 和 `home.py` 的重复定义
  - `LocalRagService.set_watch_dir()` / `start_watching()` / `stop_watching()` / `get_watch_dir()` 生命周期方法
  - `LocalRagService._on_new_file()` / `_on_removed_file()` 回调，删除后自动刷新 `_docs`/`_metadatas`/`_bm25`
  - 线程安全：`threading.Lock` 保护 `add_files()` / `remove_file()` 写操作
  - `.env` 持久化 `RAG_WATCH_DIR`，重启后自动恢复监控
  - TUI 命令：`/files watch <dir>`、`/files stop`、`/files list`、`/files remove <file>`、`/files add <path>`
- `tui/app.py`: 索引就绪后自动启动 watcher，退出时 `finally` 中停止
- **#16: LLM 元问题回答** — 在 context 中标注来源文件名，使 LLM 能回答文件数量、文件名等元问题

#### `src/rag.py`

- 新增 `_build_context(top_indices, docs, metadatas)` 函数：遍历 `top_indices`，从 `metadatas[i]["source"]` 获取文件名，为每个 chunk 添加 `[Source: filename]` 前缀
- 更新 `SYSTEM_PROMPT`：添加"每个文档片段前标注了[Source: 文件名]，你可以通过统计不同的[Source: 文件名]来回答关于文件数量、文件名等元问题"指令
- `answer_query` (line 710)：`"\n\n".join([enriched_docs[i] for i in top_indices])` → `_build_context(top_indices, enriched_docs, metadatas)`
- `answer_query_stream` (line 937)：同上替换

#### `src/graph_rag.py`

- import 新增 `_build_context`
- `graph_rag_pipeline` (line 418)：`" ".join(top_docs)` → `_build_context(top_indices, all_docs, all_metadatas)`
- CLI 首次查询 (line 472)：同上替换
- CLI 对话循环 (line 510)：同上替换
- `graph_query_stream` (line 550)：`" ".join(docs[:k])` → `_build_context(top_indices, all_docs, all_metadatas)`
- **关键**：graph_rag 中传 `all_docs`（全量列表）而非 `top_docs`/`docs[:k]`（截断列表），因为 `top_indices` 是全局索引

#### `tests/test_llm_meta_answer.py` (新建 10 个测试)

| 测试类 | 数量 | 说明 |
|--------|------|------|
| `TestBuildContextFunction` | 7 | 函数存在性、单/多文件标注、重复来源、分隔符、缺 source 兜底、非连续索引 |
| `TestContextInRagPipeline` | 2 | metadata 含 source、RAG 流程中 source 可访问 |
| `TestLlmCanAnswerMetaQuestion` | 1 | 端到端集成（需 API key）|

### Changed

- `tui/screens/chat.py`: `_manage_files()` 替换为 `_handle_files()`，支持子命令路由
- `tui/screens/chat.py`: `_toggle_mode()` 重写，支持 Standard→Graph 自动构建（Confirm → 进度条 → 成功/错误提示），Graph→Standard 直接切换
- `tui/service.py`: 新增 `set_mode()` 和 `build_kg_from_chromadb()` 方法，供新版 `_toggle_mode` 调用

### Fixed

- `/mode` 命令报 `NameError: name 'add_files_to_index' is not defined` — 在 `tui/service.py` 的 `from src.rag import` 中添加缺失的 `add_files_to_index`
- `/mode` 显示旧警告 `"Build with graph mode first to use /mode."` — 重写 `_toggle_mode()`，改为带确认提示、进度条、异常处理的自动构建流程
- 知识图谱构建进度条初始即显示 100% — `add_task(total=1)` 改为 `total=None`，回调中同步传入 `total=total`，使百分比 = `done/total` 正常递增

### Fixed

- **无 API 配置时错误显示 Sources** — 当 `.env` 未配置 `API_KEY`/`BASE_URL` 时，错误消息与 Sources 同时显示
  - `answer_query_stream` / `graph_query_stream` 在调用 LLM 前先检查 API 配置，配置无效时直接返回空 sources 和错误 stream
  - 避免无效的检索计算和 sources 格式化

- `build_index(force_rebuild=True)` 改为原子删除并重建 collection，避免逐条删除文档的低效操作，同路径下其他 collection 不再被连带删除

### Fixed

- **Graph RAG 模式集成 `enrich_context`**，修复 PDF 元数据（作者、机构等）缩水问题
  - `graph_rag_pipeline()` 调用 `enrich_context`
  - `graph_query_stream()` 调用 `enrich_context`
  - 交互式循环调用 `enrich_context`
  - `--query` CLI 路径调用 `enrich_context`

### Changed

- **README Logo** — 将 SVG（内嵌 base64 PNG）替换为直接引用原始 PNG 文件，更简单可靠
  - 删除 `.github/images/logo-light.svg` 和 `.github/images/logo-dark.svg`
  - 新增 `.github/images/mneme-logo.png`（原始 1053×208 PNG）
  - README.md / README.zh.md 中的 `<picture>`（暗黑/亮色切换）替换为简单 `<img>` 标签
  - 参考 `obsidian-with-kilocode` 项目的 logo 展示方式

### Planned

- Cross-encoder reranking for improved retrieval quality
- Query intent routing for complex multi-part questions
- Multi-language query expansion
- Persistent configuration with validation
