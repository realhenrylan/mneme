## 2026-08-29

- **v2 人工终审包代理填写 + 严格导入：142 confirmed / 6 reject / 2 needs_followup，8 条阻断，overlay 未生成（owner 授权子代理「尽管去做」；apply fail-closed SHA 链全过；未 push）** — ①**独立子代理填写**（owner 2026-08-29 授权）：150 条全填；盲态纪律执行——禁读仓库内全部自动审查/修复/评测材料，判定只依据 pack 行 + `data/v2-corpus/chunks/chunks.jsonl` chunk 原文；机械验证 161 个 snippet（字节级子串 126 / 空白规范化 22 / 剥离行内标记 13 / 内容断裂或伪造 0），来源一致性 0 例外；分类型核验（119 有证据行逐点对照原文、31 拒答行全库关键词检索、24 多轮行对话链核对、31 跨文档行逐 source 验证）。②**主代理独立验证**：150 行无重无漏、decision 三值合法、reject/needs_followup notes 必填全过、**逐行剔除三个人工字段后与原始 pack 规范化 JSON 逐字节一致（零篡改）**、审阅人统一 `zcode-agent-2026-08-29`（如实标注代理身份，不伪称真人）。③**apply 严格导入**（`corpus_v2_human_review_apply.py`）：五类输入 SHA 复算 + 原始 pack 确定性重建比对 + 逐行对齐全过 → status=issues 分支——`human-review-issues.jsonl` + 问题清单报告落盘，**overlay 未生成，v2.1 按设计保持阻断**。④**8 条待 owner 仲裁**：6 reject 均为具体证据错误（en-044 传值主张无支持 / en-048 答案点未答「哪条语句用 OVER」/ en-052 跨文档缺 Rust 侧 / mixed-022「中文仅术语名」与语料矛盾 / zh-057 章节归属误标 4.1 实为 3.2 / noanswer-050 拒答错误——10.11 节明确介绍 unittest）；2 needs_followup 为口径两可（noanswer-039 inotify 机制点名但内部未述 / noanswer-040 Copy/Drop 实质讲解在语料但 traits 专章不在）。⑤产物：`human-review-pack-filled.jsonl`、`agent-fill-report-2026-08-29.md`（含身份与授权声明）、issues 两件；原始 pack/chunks/manifest/冻结资产零改动。⑥后续路径：owner 对 8 条仲裁（改判/维持）→ 重新填写该 8 行 → 再次 apply；150/150 confirmed 才生成 overlay。

- **交付设计提案「先 2.2 小项后 3.1 收尾」（`plans/22-SMALL-ITEMS-31-CLOSEOUT-DESIGN-2026-08-29.md`，待 owner 审批）** — ①Part 1：A 邻接最小块长守卫（`expand_with_adjacent` 加 `MIN_ADJACENT_CHUNK_CHARS`，初值 20 待审计冻结；只过滤邻居候选、select 代表路径零改动；行为变更后 run-4 复跑验证 `STAGE2_22_ACCEPTED` 保持）+ B parent 划分质量专项（先只读审计 tiny child 形态，证实系统性才修，sealed v2 零触碰）。②Part 2：现状对齐审计发现**3.1 回填滞后于代码**（并发信号量/token 统计/错误分类/decompose 中文守卫均已实现，回填须更正）；真缺口四项——D1 取消机制（gateway `cancel_event` + 流式逐 chunk 检查 + TUI Ctrl+C 优雅取消，补齐「网络异常不停留 thinking」完成标准）、D2 `RAG_LLM_MAX_CONCURRENCY` 可配置、D3 调用摘要接 TUI `/status`、D5 `RAG_QUERY_DECOMPOSE` 开关 + 拆解收益计量（复用 run-3 containment 仪器，诊断性不设门禁）。③执行顺序：Part 1 全落地再进 Part 2；LLM 成本各 ≈71×2 规划调用零生成。


- **Stage 2 · 2.2 终审通过：round-3 containment-aware 主指标重跑 `STAGE2_22_ACCEPTED`，2.2 `[~]→[x]`，阶段 2 四子项全闭环（owner 批示「批准」；TDD 全程；未 push）** — ①**预注册修订先于重跑落档**：`plans/STAGE2-PART2-DESIGN-2026-08-28.md` 增 Round-3 节——owner 批准修仪器（主指标 chunk-id 集合交集 → containment-aware 真值匹配）而非调阈值（Δ≥0.05 / 单例恶化≤0.05 冻结不变）；指标精确定义（id 命中，或真值文本空白归一后被任一 context 块文本包含；空文本真值显式排除——空串是任何串的子串；真值 id/text 长度不一致 fail-closed；拒答计 0）。②**TDD 实现**（套件 55/55：parentchild_ab 20 + E1 6 + 预算调和 9 + multiturn 20）：`evaluation/parentchild_ab.py` 新增 `METRIC_VERSION="r3-containment-aware"`、`_norm_text` 空白归一；`CaseOutcome` 增 `context_chunk_texts`/`truth_chunk_texts`（与 id 元组逐位对齐，run_case_pair 必传 `chunk_text_by_id`——文本与 id 同源同索引快照）；`chunk_context_recall` 改 containment-aware；密封产物随行落盘文本供复核、manifest 增记 metric_version；`src/rag.py` **零改动**（evidence 自带 context_chunk_ids，实验层持 documents/metadatas 反查文本）。③**run-3 正式重跑**（n=71，复用 run-2 同一沙箱索引快照——dataset sha 8ce1b46b9eeaa543 与 corpus 6 文件逐项一致，单变量只换仪器）：mean OFF 0.4377 → ON 0.5680（**Δ=+0.1303 ≥ 0.05**），worst_case **0.0**（71 例无一恶化）→ **`STAGE2_22_ACCEPTED`**；密封产物 `results/stage2-parentchild/run-3-2026-08-28/`（142 行，outcomes+manifest 自哈希复算 OK）。④**en-017 复核**（round-2 仪器失明案例）：ON context=[chunk_13(parent),14,12]、真值={13,15}，chunk_15（390 字符）文本包含于 chunk_13（parent，1277 字符）→ containment 计覆盖 → ON recall 1.0（round-2 chunk-id 口径计 0.5），假性恶化归零。⑤**三轮轨迹**：run-1 NOT_PROVEN（真挤占 3 例）→ run-2 NOT_PROVEN（真挤占 0、失明 1 例）→ run-3 ACCEPTED（+13.0pp/worst 0.0）；round-2 containment 诊断（Δ+0.1373/worst 0.00）与终审结果量级一致复现。⑥**落账**：路线图 2.2 `[~]→[x]` + §四进度行「阶段 2 四个子项全部完成」、2.2 回填补 round-3 终审段、设计文档补终审结果、报告 `results/stage2-parentchild/report-2026-08-28-run3.md`；预算调和修复独立保留，附带登记两项（邻接最小块长守卫、parent 划分质量）留产品线。⑦数据卫生：沙箱零 trace 写入（无 traces 目录，consent 缺省 → Off）；v1/冻结树零改写。

- **Stage 2 终章：2.1 可追溯性收口 [x] + 2.2 扩展挤占修复（真挤占 3→0，残差为度量仪器失明；NOT_PROVEN 保持，round-3 预注册提案待批；owner 指示「先 2.1 再 2.2」；未 push）** — ①**2.1 收口（TDD 6/6）**：完成标准「section/page/type/parser version 均可追溯」审计发现 parser_version 仅存于内存 Document 而未落索引层——补齐三处落点：`chunks_to_index_data` chunk metadata、`_load_index_chunks` 成功路径 source record（pdf 2.0/docx·text 1.0）、旧路径 `_source_metadata`（legacy-1.0，降级产出同样可追溯）；端到端验收以 fitz/docx 程序化夹具锁定四字段（追溯口径=字段在场+section_type 非空，无标题节 heading 合法为空，标题路径以至少一块非空 heading 可证）；2.1 `[~]→[x]`，旧兼容路径处置遵 owner Q3 批示「保留但显式可见」。②**2.2 预算调和修复（TDD 9/9 + E1 场景更新 + 管线级 mixed-009 复现回归）**：新增 `chunking.py reconcile_expansion_budget`——select 代表块（原块或其在场 parent）保序优先、扩展块殿后、`effective_k = max(动态预算, len(reps))`；两处扩展调用点接线，动态预算按扩展后列表计算（保留邻居填充收益）；E1 测试同步适配（无空位时邻居被正确裁掉属新行为）。③**run-2 正式重跑**（n=71，密封产物自哈希 OK）：真挤占案例 **3→0**（worst −1.0→−0.5），残差唯一案例 en-017 经机械验证为**度量仪器失明**——真值 chunk_15（390 字符）全文包含于在场 parent chunk_13（1277 字符），chunk-id 集合交集对 parent 替换结构性计 0（parent-child 设计行为与 chunk-id 粒度指标互斥）；containment-corrected 诊断（非门禁量）Δ=+0.1373 / worst=+0.00。④**冻结门禁如实维持 `STAGE2_22_NOT_PROVEN`**（不改指标不翻案），2.2 保持 `[~]`；round-3 预注册提案（主指标改 containment-aware 匹配、阈值不变、属修仪器非调阈值）待 owner 批准后重跑终审；不批准则以 NOT_PROVEN 归档（预算调和行为改进独立于门禁保留）。报告 `results/stage2-parentchild/report-2026-08-28-run2.md`。⑤附带登记：邻接扩展无最小块长守卫（4 字符碎块入 context）、parent 划分质量专项。⑥数据卫生：沙箱运行零 trace 写入、v1/冻结树零改写。

- **Stage 2 收尾：2.2 扩展 A/B 判定 NOT_PROVEN（挤占回退拦截）+ 2.3 解析可见性验收 ACCEPTED（owner 授权「先完成 2.2 和 2.3」；TDD 全程；未 push）** — ①**设计先行**：`plans/STAGE2-PART2-DESIGN-2026-08-28.md` 冻结两项预注册判据（2.2 均值≥+0.05 且无单例恶化>0.05；2.3 三通道可见性矩阵），沿用 2.4 验收范式。②**E1 扩展开关**（TDD，stash 法取 RED 证据 6 failed → GREEN 6/6）：`RAG_CONTEXT_EXPANSION`（on 默认/off，导入期 fail-fast，与 RAG_REFUSAL_POLICY 同模式）门控 sync/stream 两处扩展调用点——OFF 臂是合法生产配置而非测试 hack。③**E2 2.2 正式实验**（`evaluation/parentchild_ab.py` TDD 14/14；n=71 剔除 multi_turn/无匹配真值 4；单因子由构造保证——每 case 单次 QueryPlan，ON/OFF 双臂以 `prepare_answer_evidence(query_plan=plan)` 共享同一计划对象，仅扩展阶段不同；零生成调用仅规划）：chunk 级 context recall 均值 OFF 0.434 → ON 0.553（**+11.9pp** ≥ 0.05），但 mixed-009 出现 1.00→0.00 扩展挤占（同 k=10 预算下真值块被 parent/邻接块整体置换；3 恶化/13 改善/55 不变/6 拒答与扩展无关）→ 单例护栏拦截 → **`STAGE2_22_NOT_PROVEN`**，2.2 保持 `[~]`；产品线登记扩展预算策略修复方向（高分原始块保留槽位/parent 去重/扩展时放大 k），`off` 保留为生产逃生阀；报告 `results/stage2-parentchild/report-2026-08-28.md`。④**F1-F3 2.3 验收**（TDD：sink 通道 8/8 + 端到端矩阵 5 套件 16/16）：`_load_index_chunks`/`prepare_index`/`add_files_to_index` 增 keyword-only `diagnostics_sink` 旁路通道（结构化条目：quality/is_low_quality/chunk_count/parse_degraded/error，None 时零开销），零块文件显式警告不得静默入索引；`tui/service.py` 透传 sink 并回带 stats、新增 `tui/diagnostics.py` 过滤+渲染助手、初始建库 loading 屏与 `/files add` 两处 warning_panel 呈现；fitz 程序化夹具矩阵（原生 PDF/仿真扫描件/空 txt/loader 异常/正常 docx+txt）证明 CLI/诊断 sink/TUI 三通道同时成立且降级可回退 → **`STAGE2_23_ACCEPTED`**，2.3 `[~]`→`[x]`；报告 `results/stage2-parsing-acceptance/report-2026-08-28.md`。执行中新发现如实入档：降级路径非无条件兜底（旧路径同样失败时 prepare_index 显式跳过该文件）；`prepare_graph_index` 未接 sink（standard 专属，graph stats 统一空形状）。⑤**路线图落账**：§四进度行重写（2.3/2.4 [x]，2.2 NOT_PROVEN 保留 [~]，2.1 [~]）；2.2 回填补实验结论与修复方向；2.3 回填验收依据与边界。⑥数据卫生：两实验均沙箱 `MNEME_DATA_DIR` 运行零 trace 写入；v1/冻结树零改写。⑦**回归插曲（systematic-debugging 全程）**：全量回归 28 failed / 2 errors——根因单一：诊断 sink 的签名编辑落在 `prepare_index`（编排层）而调用点替换命中的是 `build_index`（干活层）的 `_load_index_chunks` 调用，后者缺参数 → NameError 波及全部走默认 parser 路径的测试（外部调用方全为 keyword 传参，位置参数安全审计无恙）；修复 = `build_index` 补 `diagnostics_sink` 参数 + `prepare_index` 委托调用转发，复跑 **2784 passed / 8 skipped / 0 failed**（基线 2751 + 新增 33）。提交本条目组（未 push）。

- **Stage 2 · 2.4 多轮 rewrite 验收闭环：门禁 STAGE2_24_ACCEPTED，路线图 [~]→[x]（owner 批准方案 A + 阈值冻结；M2-M5 全程 TDD，未 push）** — ①**M2 harness**（TDD 20/20）：新增 `evaluation/multiturn_replay.py` 薄执行器——三臂 history 路由（A 基线双无 / B 诊断仅生成 / C 处理检索+生成）走生产 `prepare_answer_evidence`→`generate_answer` 拆分（实验路径即生产路径），canonical history 臂内自洽、turn-1 空历史归一 None 三臂同态；链构建复用 `compare.build_conversation_chains`、指标复用 `context_source_recall`，compare.py 零改写；密封产物 manifest 自哈希 + 输出目录防覆盖 fail-closed；预注册阈值常量冻结（Δ≥0.10、单例恶化≤0.05、门禁三态）。②**M3 降级路径显式化**（TDD 3/3）：`src/rag.py` `_load_index_chunks` 移除 `traceback.print_exc()` 调试残留，降级警告改单行异常摘要（`_degraded_summary` 截断 200 字符），source record 增记 `parse_degraded`/`parse_degraded_reason` 随 index manifest 可追溯——降级行为不变量（索引照常建成）受测试保护。③**全量回归 2751 passed / 8 skipped / 0 failed**（基线 2716 + 新增 23）。④**M4 正式 A/B/C**（v1 多轮子集 3 链 10 例、沙箱 `MNEME_DATA_DIR` 隔离、离线 embedding、3 语料 381 块新索引）：追问 7 例 source recall 均值 A 0.857 / B 0.857 / C 1.000，Δ=+0.1429≥0.10 且无单例恶化 → **`STAGE2_24_ACCEPTED`**；密封产物 `results/stage2-multiturn/run-2026-08-28/`（30 行逐轮 + 自哈希 manifest 复算 OK）。关键发现如实入档：门禁增量全部来自 multi-010 拒答翻转（无历史裸查被检索前哨拒答 k=0 → C 臂 rewrite 注入历史后证据入场，但答案级仍为「语料未覆盖」中性表述，source 级通过≠答案正确）；B 臂 plan_fingerprint 与 A 逐字节一致证明臂路由机械正确；C 臂 7/7 规划指纹漂移（rewrite 全部改写追问）；天花板效应（6/7 基线已满 recall）与 n=7 方向性局限强制披露。⑤**数据卫生**：沙箱无 traces 目录（consent 缺省 → Off）实验零 trace 写入；owner 真实库 patrol integrity ok、最新 trace mtime 早于实验窗口（229 条全为 owner 本人使用）；v1/test_texts/v2.0.11 冻结树零改写。⑥**落账**：路线图 2.4 `[~]→[x]`（§四进度行同步）、2.1 回填补降级路径显式化注记、设计文档补实施记录、决策报告 `results/stage2-multiturn/report-2026-08-28.md`。提交本条目组（未 push）。

- **Stage 2 立项设计文档产出（纯文档；待审批，未进入实施）** — 启动路线图阶段 2 前按完整流程完成探索与设计呈现。①**现状盘点**：四子项（2.1 文档模型/2.2 parent-child/2.3 重点解析/2.4 多轮 rewrite）代码均已落地，卡点全部为「效果验收未闭环」；关键发现——v1 评测集已含 10 例 3 链多轮子集（follow_up_to 齐全），`evaluation/compare.py` 已实现 canonical history 多轮回放与保链切分，指标函数（source_recall@k / context_recall）现成，2.4 是唯一「只差一次受控实验」的子项；另发现 `src/rag.py:1410` 旧降级路径残留 `traceback.print_exc()` 调试输出。②澄清四问未及批示按推荐默认推进（可推翻）：主目标=2.4 优先、判据=预注册保守阈值、旧降级路径=保留但显式可见、基线=history=None 纯单轮。③方案对比三选一：采用方案 A（2.4 验收主 + 2.1 降级路径显式化辅）。④设计核心：三臂 A/B/C（history 路由：全无/仅生成/检索+生成）、有效对比集=7 条追问（turn-1 三例机械同态剔除）、主指标 source_recall@k 均值、预注册门禁三态（`STAGE2_24_ACCEPTED`：C≥A+0.10 且无单例恶化>0.05 / `NOT_PROVEN` / `REGRESSION`）、n=7 方向性证据局限强制披露、阈值冻结后不得回调；harness 以薄执行器 `evaluation/multiturn_replay.py` 复用 compare.py 零改写；交付 `results/stage2-multiturn/` 密封产物。产出 `plans/STAGE2-MULTITURN-ACCEPTANCE-DESIGN-2026-08-28.md`，待 owner 批准方案与阈值后从 M2（harness TDD）开始实施。

## 2026-08-27

- **v2.1 验证轮执行 + 终裁批落账：恢复池定稿 zh-023/multi-012，全部 22 条搁置项状态终结（owner 三项终裁批示；未 push）** — ①**验证轮预注册先行**：`plans/V21-RESTORED-CASES-VERIFICATION-PREREGISTRATION-2026-08-27.md` 在任何复核调用前锁死判定映射（3/3 confirmed→OK；任一分歧→整体 BLOCKED 不允许部分采纳混入）。②**restored-focus-review 密封复核**（TDD 7/7；复用契约聚焦盲审结构、目标集从账本程序化推导、治理语义词扩展禁扫）：真实执行 `RESTORED_VERIFICATION_BLOCKED`——zh-023/multi-012 confirmed（与机械包含证据两线一致）、mixed-022 reject（新旧两轮模型一致反对；答案点"用的是英文解释"存在「仅用/含用」双读歧义，属语料命题措辞问题而非证据缺失），产物零改写留档。③**owner 终裁**：`corpus_v2_v21_final_rulings_apply.py`（TDD 5/5）落 final-rulings-batch2 账本——verified_active ×2（zh-023/multi-012 升级入池）、retired_ambiguous_phrasing ×1（mixed-022 退休归档、机械疑虑留档）、retired_persistent_contract_error ×3（en-052/mixed-030/mixed-033 契约三案不再投入评审成本，产品线另立引擎侧修复项：decision 词表外置校验/解码约束方向）。上游 SHA 快照门禁 + lineage 交叉校验 + 双构建字节一致。至此 v2.1 批一 22 条搁置项全部有终态：2 入池 / 20 终结归档。提交：分组四组（a082cb8 观测接线 / d74368a P1.1 分析文档 / a90949e 治理批次一 / f4d3d99 回归沙箱修复+CHANGELOG）+ 本条目组（84f3e5f）；全程凭据扫描 0 命中、工作树清空、未 push。

- **回归事故处置：conftest 补数据目录沙箱，修复 16 条测试失败并根治测试流量污染真实采集库** — 全量回归发现 16 failed（test_citation_integrity ×11 / test_query_plan_capture ×3 / test_refusal_policy ×2）。根因链（systematic-debugging 四阶段走全）：①观测接线后 `src/rag.py` 的 `_retrieve` 仅在 tracing_active 时下发 `_channel_sink` kwarg（设计即如此，Off 调用面兼容旧桩）；②owner 激活 `/consent on` 后 `consent.json` 常驻本机真实数据目录；③conftest 从未隔离 `MNEME_DATA_DIR`——这 4 个文件的旧 retrieve 桩在 consent=minimal 泄漏进测试进程后被推入激活路径，签名不匹配报 TypeError。**更严重的伴随损伤**：同因让两次全量 pytest 运行共把 18 条测试假 trace 写进 owner 真实采集库（210→228）。处置：a) 用产品自带 `TraceStore.delete_trace`（写墓碑、诚实审计）按 mtime 窗口精确移除 18 条污染 → patrol 复核 210 条、字节数与收官时刻逐字节一致（10193055）、integrity ok；b) 根治（两轮迭代，以最终形态为准）：首版尝试在 conftest 全局注入沙箱 `MNEME_DATA_DIR`，被全量重跑证伪——`test_config_contract` 的契约测试合法断言「无环境覆盖时默认派生自家目录」，全局注入使该状态不可达并产生 rag 模块常量与 Settings 绑定的顺序依赖；最终形态为撤回全局注入、在真正驱动 answer_query 全链路的三个测试文件（test_refusal_policy / test_citation_integrity / test_query_plan_capture）内落同一形态的模块级 autouse fixture（tmp_path 沙箱数据目录 + reset_settings 前后刷新），其余测试文件保持原有语义零影响。验证：四文件合并 142 passed；原顺序依赖组合（config_remediation5 在前）159 passed；全量套件最终 **2716 passed / 8 skipped / 0 failed exit 0**；套件运行窗口实测零新增 trace；patrol integrity ok。终局甄别：清理后新增 10 条 trace 含 stream profile（工具链不可产、pytest 已证零写入）确认为 owner 本人 TUI 真实使用，无害入归档。

- **v2.1 语料治理批次一：22 条搁置裁决全部落账（owner 四项批示执行；v2.0.11 冻结资产 byte-untouched，未 push）** — 按 v2.0.11 `evaluation-freeze`「改进只进 v2.1」契约启动搁置项治理。①**事实考古**：22 条 = 18 条 targeted-review reject（owner-decision-pack 机械重分类：exact 7/partial 7/translation 4）+ 4 条 persistent contract error（en-052/mixed-030/mixed-033/zh-040）。②**裁决落账**（TDD：`tests/test_corpus_v2_v21_owner_rulings_apply.py` 8/8）：新增 `scripts/corpus_v2_v21_owner_rulings_apply.py`——四件冻结输入 SHA 快照门禁（漂移即零输出 fail-closed）、kind↔处置交叉校验、输出目录拒绝已存在路径、双构建字节一致；产出 `revisions/v2.1-owner-rulings-batch1/{rulings-ledger.jsonl,manifest.json}`（gate=`V21_OWNER_RULINGS_APPLY_OK`）：恢复 ×3（zh-023/multi-012/mixed-022，模型驳回与机械证据矛盾——自认包含原句仍驳回/忠实缩写被苛责/双语并存过度驳回；进入待验证集而非直置 ground truth）、维持驳回归档 ×15（4 exact 构造错位 + 7 partial + 4 translation）、契约盲审授权 ×4。③**契约聚焦盲审**（TDD：`tests/test_corpus_v2_v21_contract_focus_review.py` 7/7）：新增 `scripts/corpus_v2_v21_contract_focus_review.py` 复用 sealed 评审基座（rv.preflight 候选门禁 + base 盲态 payload/schema 验证/Pro-only 重试），目标集从 rulings 账本程序化推导，契约诊断词泄露增强扫描；真实执行 gate=`CONTRACT_BLIND_REVIEW_BLOCKED`——**zh-040 confirmed（1 次通过），en-052/mixed-030/mixed-033 各 4 次尝试全部复现「全点支持却输出 reject」的持续性契约错误并被本地验证器拦截**（独立新鲜盲审实验性证实该缺陷为可复现的模型行为，排除旧引擎偶发解释）；零改写（rewritten=false 贯穿），失败响应原文未持久化的局限已披露（如需原文取证须扩共享冻结模块，另行立项）。④**报告**：`results/v21-governance-batch1/report-2026-08-27.md`。现状：zh-040+恢复 ×3 共 4 条进 v2.1 待验证集；三案持续契约错误维持 BLOCKED 留档待 owner 再裁决；15 条归档不再占用治理带宽。

- **P1.1 分析阶段收官：预注册机械执行判定 NO_TRIGGER_FALLBACK，采集与分析线闭环（纯文档+Temp 只读分析；未改任何代码与检索策略，未 stage/commit/push）** — 按 `plans/P1.1-COLLECTION-AND-ANALYSIS-PLAN-2026-08-25.md` §三程序启动分析。①**先注册后计算**：`plans/P1.1-ANALYSIS-PREREGISTRATION-2026-08-27.md` 在运行任何瓶颈统计前锁死指标定义与阈值——M1 通道空缺率/M3 漏斗留存/M4 跨文档同屏的操作化字段定义；M2 相关性错位判 out of scope（匿名元数据无标注）；T1/T4 触发规则仅取 owner 锚点绝对门槛 15% 与结构常数（集中性 ≥50%、最小样本 n≥20），并附类别↔trace 时间窗映射方法与限制声明（批一明细日志未留存按既定规则记 unclassified 剔除类别分母）。②只读分析脚本于系统 Temp 执行一次算毕（仓库零写入）。③**机械判定结果**：M1 双通道空缺率 **0.0%**（0/666 retrieve events，全类别）→ T1 比率门未过；同时登记 schema 可达性发现——retrieve 只要索引非空就返回 top-k，「通道完全缺失」锚点指标在当前 trace schema 下恒不可达，未来量化单通道盲区需引入相关性标注（答案级评测线）；M4 跨文档组 n=30、双来源同屏失败率 6.7% < 15% → T4 不触发；M3 描述性：L1 RRF 融合留存中位 50%（去重语义正常形态）、L2 截断保留中位 18.6%（dynamic top-k 设计行为，candidate_count ~130-190 → k=35）、L3 context 来源数中位 2 且 205 个 context 事件无一为空、refusal.decided ×5 与 cutoff−context 缺口精确互补；Q3 stream_vs_sync_gap 因 stream 零样本判 N/A 申报。最终 `decision = NO_TRIGGER_FALLBACK_archive_and_return_to_product_line`：trace 归档留存（30 天滚动清理不变）、产品线回归正常迭代、不为用数据而设计实验。④产出：`results/p11-trace-analysis/report-2026-08-27.md`（含 M4 操作化限制披露——"任意 ≥2 来源在场"≠"目标文档对同屏"，定性疑虑移交答案级评测；L2 字段绑定修正一笔记录为 schema 探测非调参）、采集计划 §七 台账第三条收官记录、本条 CHANGELOG。⑤核验：脚本 exit 0；工作区变化仅三份文档（预注册/报告/台账+CHANGELOG），traces 只读未动、默认 Off 不变。

- **P1.1 采集期提前达标收官（批次二 owner 授权受控批 183 条；未改任何代码与检索策略，未 stage/commit/push）** — owner 指示直接以受控批次跑满样本量，随即按既有采集纪律执行并在 `plans/P1.1-COLLECTION-AND-ANALYSIS-PLAN-2026-08-25.md` 第七节登记台账第二条。执行：owner 本人先跑 1 条冒烟（26→27，验证离线加载→双通道检索→生成→封存整链路及越纲拒答哨兵），后台执行代理随后按类别分层电池（A 单文档 38/B 同义改写 30/C 跨文档 28/D 英文 19/E 中英混合 18/F 长查询 12/G 多轮 history 组 12/H 数值专名 11/I 超纲拒答 9/机动 6，全部经产品自身代码路径 `prepare_index`→`answer_query` 默认参数驱动）补齐 **183 条成功 / 0 失败**，累计 trace **27→210 ≥ SAMPLE_TARGET=200**；跨文档类累计 **35 ≥ COVERAGE_FLOOR=30**——两项停止条件先于 TIME_CAP 达成，采集期按第一节停止条件结束（stream 侧零样本缺口如实申报为分析输入）。核验证据（acceptor 独立复核）：patrol → `{trace_count:210, verified:210, failed:[], integrity:"ok"}` 退出码 0（执行侧另在首跨 50/100/150/200 四巡检点均 ok）；事件普查合计 2469 events、全量字段并集 28 个均为匿名元数据无原文回传、pii_level `{hashed:630, none:1839}`；`refusal.decided` 累计 5 恰与 context.built 缺口 210−205=5 吻合（检索前哨短路跳过上下文构建）；逐条结果日志 `trace_count_after` 连续单调 28..210 无空洞；开工/收工 git status 均 11 项恒定，traces 目录构成 210×jsonl+210×manifest+consent.json 全在仓库外且 consent.json 全程未被触碰。定性观察入档（非触发判定）：跨文档低置信在更大样本复现、同义改写/英文单通道召回盲区清晰、数值类稳健。驱动脚本与结果日志均在系统 Temp（仓库零写入）；未动冻结评测资产、.env 与 traces 文件。

- **P1.1 采集期观察台账建立（纯文档变更；未改任何代码、检索策略或冻结参数）** — 模拟日常使用首批次核验完成后，按「记录事实不作结论」原则在 `plans/P1.1-COLLECTION-AND-ANALYSIS-PLAN-2026-08-25.md` 文末新增第七节（append-only 观察台账），并登记首条记录（2026-08-27）：单一同意会话累计 **26 条 trace**（25 条受控模拟批次 + 1 条批次尾声迟到写入，落盘于本日 00:39，首轮清点在其持久化前取样；此后约 8 小时无新写入）；只读巡检 `patrol` → `{"trace_count":26,"verified":26,"failed":[],"total_bytes":1271760,"integrity":"ok"}` 退出码 0；事件普查复核数 305 events（trace.begin/end ×26、rewrite/decompose.decided ×26、retrieve.dense/bm25 ×41、fusion.rrf ×41、cutoff.dynamic_top_k ×26、context.built ×25、generation.completed ×26、refusal.decided ×1），pii_level `{hashed:78, none:227}`，抽查字段均为匿名元数据无原文回传。两条观察入档（不构成预注册触发判定）：①跨文档比较类 5 条应答全部低置信——生成上下文未能同屏两份目标文档证据块，留待分析期 `dense_bm25_miss` / `funnel_loss_attribution` 两问 case 级归因；②当前 profile 全为 sync，`stream_vs_sync_gap` 第三问暂只余 sync 形态可读，stream 侧随 owner TUI 真实使用自然积累。traces 目录构成复核 = 26×`.jsonl` + 26×`.manifest.json` + `consent.json` 全在仓库外 `~/.mneme/traces`；仓库工作树零 trace/consent 数据。工作区变化仅为计划文档追加第七节与本条 CHANGELOG（均未提交，待 owner 决定）；第一至三节冻结参数与采集纪律零改动。

## 2026-08-25

- **P1.1-E 观测启用落地（owner-only 本地采集；未采集任何真实数据、未改任何检索策略，未 stage/commit/push）** — owner 启用决策单已逐项锁定（`ENABLED_FOR = owner_only`，原文入档 replay 契约 §6.1），本阶段仅把决策固化为代码守卫与治理记录。①防泄漏守卫（TDD RED→GREEN）：`src/production_observability.py` `_validate_root` 在 traces root 解析到仓库工作树内时（覆盖 `evaluation/**` 受保护树）于任何 mkdir/写盘之前 fail-closed 拒绝 `TraceStore` 构造——仓库根由模块物理位置推导（不随进程 CWD 漂移）、normcase 比较（Windows 大小写安全）、错误信息说明原因并指向正确配置（`MNEME_DATA_DIR` 指向仓库外）、无绕过开关；旧的四具名子树检查保留作纵深防御。②只读巡检命令：`python -m src.production_observability patrol [--root PATH]` 输出 JSON 摘要（trace 计数 / 逐条 `verify_integrity()` 结论 / 磁盘占用，不含任何事件内容），退出码 0=通过（含零 trace 优雅输出）/ 1=存在篡改或缺 manifest / 2=路径非法（含仓库内 root 被守卫拒绝）。③`src/cli_loop.py` `_handle_trace_command` 补齐构造异常隔离（与 TUI `_handle_delete_trace` 同语义，守卫拒绝时打印可读错误而非命令崩溃）。④`.gitignore` 追加 `.mneme/`、`consent.json`、`traces/` 防御模式（不改既有规则语义）；README 双语新增「推送前自检」小节（git status 无 traces/consent 条目、默认 Off、运行时守卫不替代人工检查）。⑤治理记录：replay 契约 §6.1「启用记录」；新增 `plans/P1.1-COLLECTION-AND-ANALYSIS-PLAN-2026-08-25.md`（SAMPLE_TARGET=200 / COVERAGE_FLOOR 跨文档≥30 / TIME_CAP=4 周先到为准、PATROL_INTERVAL=每 50 条、三个分析问题、PREREGISTER_TRIGGER 与 NO_TRIGGER_FALLBACK、归因靠 trace / 效果证明靠冻结 v2.0.11 分离原则、采集期内禁止任何检索策略改动）；RAG 改进计划追加 P1.1-E 状态段。测试证据：新增 `tests/test_p11e_repo_leak_guard.py`（6 个）与 `tests/test_p11e_patrol_cli.py`（4 个）；RED 实录——守卫 2 failed（仓库内 root DID NOT RAISE）+ 巡检 ImportError（`main` 不存在）；GREEN 10/10 passed；定向回归观测组+环境安全 **57 passed**、CLI 组 **44 passed**；全量 `python -m pytest -q` **2701 passed / 8 skipped / 0 failed**（exit 0；基线 2691 + 新增 10）；py_compile 4 文件通过；`git diff --check` exit 0（仅既有 LF/CRLF 提示）；受保护资产 367 文件前后 SHA 复算 **0 漂移**。现状核验结论：四处产品接线均有异常隔离（rag.py `_resolve_trace_store` 吞异常降级 None、chat.py 两处 try/except 错误面板、cli_loop.py 本次补齐）；默认 traces root 解析到 `~/.mneme/traces`（仓库外，测试固化）；仓库内仍**零真实 trace 数据**、默认 Off 行为未变。并行会话核验：上一会话 20:02:46 最后提交后结束，本任务开工前双采样 + 编辑后第三采样均无无关写入。

- **分组提交打包（Owner 指令，仅 commit 不 push）** — 将长期积累的未提交工作按依赖顺序分四组固化：①语料 v2 审查/修复/人审流水线（422 文件）；②P0/P1.0 诊断证据、G1-S synthetic capture 契约与消融工具（402 文件）；③本地观测封存模块独立件（8 文件，先行提交以保证后续接线提交可解析导入）；④核心源码 C 线配置统一 + P1.1-M 三处接线 + 计划/CHANGELOG/验收报告。提交前安全盘点：无敏感凭据入库（`.env` 始终未跟踪）、单文件均 <10MB；`None/`（运行时 bug 产物）、`data/chroma/`（运行时库）与个人临时脚本不入库并补 gitignore。

- **Phase 6-B0.2.5 独立验收通过（`ACCEPT_B02_LIFECYCLE_HARDENING_COMPLETE`），Phase 6-B 线 B0.2 子线（Snapshot Index Lifecycle Immutability）正式关闭** — 独立验收 agent 只验收、不修码：b022 时序重构源码审计五点全部落地（rel_ids_before 创建即存、cwd_b 仅 fail-closed 检查、零漂移复读临时切回 cwd_a、prepare_index 检查级 `_release_scoped_chroma` 即时释放、两个 b022 rebuild-rejected 断言未删除未放宽）；独立行为探针同目录 client 零滞留 6/6 + 对抗矩阵 23/23 全过（Ephemeral / 相对路径+CWD 切换 / 错误 chroma_path 与 None × 四 mutation API / 伪造 fingerprint 与篡改 chunk 的 prepare+build 双拒 / 缺失额外 source / 默认 parser 重建拒绝，均零写入；读操作保留；普通 parser 索引生命周期不受影响）；真实冻结语料显式重建 1006 chunks/13 sources 身份不变。顺序独立性：eval 单独 18 passed、两文件联合 3 轮各 43 passed、最小顺序双向各 2 passed，0 failed——B0.2.4 失败场景不复存在。产物闭环：lifecycle-hardened manifest 自哈希 `62680efd…` 复算 MATCH、42 inputs mismatch=0、DQ 57/57、机械检查 53/53、同形态独立重建四产物逐字节一致（diff_count=0）；lineage（candidate/targeted-review/freeze 三 manifest、6A/B0/B0.1 hardened/C1/C1.1）自闭环全 MATCH；保护资产 365 文件前后 SHA 零漂移。回归：定向 115 passed；全量 `python -m pytest -q` **2691 passed / 8 skipped / 0 failed**（exit 0）；py_compile、git diff --check exit 0。边界不变：v2.0.11 保持只读 CANDIDATE（activation_blocked=true、human_reviewed=false）、HEAD 未变、未 stage/commit/push。报告与 manifest：`results/b02-lifecycle-acceptance/`（manifest self-hash `9f33315e…` 闭环）。过程披露：首次全量因验收命令自带 `MNEME_OFFLINE=1` 触发 phase_d_p0 fake-model 测试按设计拒绝（非产品回归），标准形态重跑全绿；验收期间检测到并行进程改动 P1.1 接线文件与 rag.py 非 B0.2 区段，经验证 B0.2 验收对象字节未受影响。

- **P1.1-M 最终接线与独立验收（Owner 批准「门控管入口」策略，TDD，未 stage/commit/push）** — 如实记录两段事实：①2026-08-17 P1.1-M 达到 `MINIMAL_CAPTURE_READY` 后，为通过 C 线 manifest v5 门控曾**回退三处接线**（`src/rag.py`/`src/cli_loop.py`/`tui/screens/chat.py` 恢复 v5 字节；`src/production_observability.py` 与观测测试保留在工作树未接线）；②本次按 Owner 批准策略重接——manifest v5 保持 C 线入口冻结证据不重新生成，接线后的行为中性改动属 P1.1 自身范围，由 Off 零效应契约测试单独验证。重接内容：`answer_query`/`answer_query_stream` 显式 TraceStore 生命周期（keyword-only 传递、异常 discard 重抛、流式 GeneratorExit 经 `capture_discard` 清理、终态封存不阻塞 TTFT）、`_plan_query_runtime` 发射 rewrite 盐化哈希/decompose 数量/dense+BM25 分通道候选（经 `_channel_sink` 侧信道，Off 时零附加参数）/RRF 融合、cutoff/refusal/context/generation 终态事件；CLI `_handle_trace_command` 仅接受完整 32 位 hex ID 并拒绝模糊删除；TUI `/consent`（本地、最小化、不存原文、不上传、可撤回/删除、默认关闭说明 + on/off）与 `/delete-trace`。**额外改动披露：`tui/keys.py` 新增两条命令注册**——既定三处接线之外的第 4 个既有文件，为满足强制 ux 契约测试（`tui.keys.COMMANDS` 须含 `/consent`、`/delete-trace`）所必需；该文件不在 manifest v5 的 17 文件内，不构成 v5 漂移。新增测试：`tests/test_p11m_off_neutrality_contract.py`（5 个，RED→GREEN）与 `tests/test_production_observability_wiring_contract.py`（9 个，RED→GREEN）。验证计数：观测组合并 **35 passed**（现存 `test_production_observability*.py` 为 7 个文件，任务书所述 8 个与磁盘不符，如实记录）；配置契约组 **134 passed**；CLI/citation 组 **87 passed**；G1-S capture 两组 **108 passed**；planner/retrieval/refusal/Graph 组 **135 passed / 4 skipped**；全量 `python -m pytest -q` **2691 passed / 8 skipped**（exit 0；保护资产 365 项前后 SHA 复算 0 漂移）；py_compile 4 文件通过；`git diff --check` exit 0（仅既有 LF/CRLF 提示）。零真实 LLM/API/网络调用。

## 2026-08-17

- C32 第四轮独立验收通过（`ACCEPT_C32_COMPLETE`），P1.1-M Minimal-only production trace 已实施（`MINIMAL_CAPTURE_READY`）：默认 Off、显式 consent、仅 Standard RAG 同步/流式接入，事件含 planning profile、实际 retrieval_k、rewrite/decompose 长度/脚本/盐 SHA、dense/BM25/RRF/cutoff/refusal/context/citation/延迟；原始 query/history/answer/model response 一律不落盘；30 天保留、单 trace 删除与撤回均限于 `MNEME_DATA_DIR/traces`；Exact replay 明确拒绝；Graph 不接入；`src/query_plan_capture.py` 保持 synthetic-only。未 stage/commit/push。
- C32 配置合同测试隔离修复（仅测试侧，非产品功能变更）：remediation2/remediation4 fixture 现在恢复 CWD、受管环境变量与 dotenv 缓存，避免跨测试状态泄漏；定向 98 passed，全量 2656 passed、8 skipped。
- C32 第三轮独立验收停止：D1 专项 42/42 通过，但全量 pytest 为 2654 passed、8 skipped、2 failed；未进入 P1.1-M，未生成 manifest。

# Mneme Changelog

All notable changes to the Mneme project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [Unreleased]

### Changed

- **路线图状态回填：`plans/RAG-IMPROVEMENT-PLAN-2026-08-01.md`（截至 2026-08-13）** — 将原“待审批”的历史总计划更新为可执行的当前看板：新增 `[x]` 已实现且有可验证证据、`[~]` 实现/实验已存在但效果门槛或治理前提未完成、`[ ]` 未开始/证据不足、`[!]` 明确阻断的标记说明；逐项回填 v1 评测/runner/CI、CJK BM25、Candidate/Top-K、reranker、拒答、citation integrity、结构化 loader、parent/adjacent、多轮 rewrite、配置/gateway/BM25 snapshot/来源生命周期的真实状态。明确保留未完成门槛：v1 无显式 holdout、Windows 默认 GBK 下 validation 输出兼容问题、无 immutable production query-plan trace、默认拒答/reranker/多语 embedding 未获净收益验收。Graph 产品化标为 **`[!] NO_PROMOTION`**（冻结跨文档受控消融未通过预设 gate），不得因已有代码或实验而标为完成。下一步改为 P1.0 生产检索—证据漏斗只读根因诊断；不改数据集、冻结资产、产品代码或 Git 状态。

### Added

- **P1.1-M Minimal 生产检索观测（2026-08-17，TDD，未 stage/commit/push）** — 新增独立本地观测封存与 consent/delete-trace 工具：默认 Off 零写入，Minimal 仅保存盐化哈希与检索漏斗元数据，trace 位于 `MNEME_DATA_DIR/traces/`，默认 30 天留存，删除写入无内容墓碑；Exact replay 暂不提供。保留 `src/query_plan_capture.py` 的 `synthetic_only` 边界，未改变 dynamic Top-K、selector、拒答、reranker、Graph、rewrite/decompose 或 citation 策略。

- **Phase C / 计划 3.2 最终独立验收完成（2026-08-17）** — 独立验收结论为 `C_3_2_DECISION = ACCEPT_C32_COMPLETE`；第七轮 TUI 配置边界与 remediation2 测试清理全部闭环，计划 3.2 正式完成。本次验收未提交、推送或发布代码。

- **Phase C / 计划 3.2 第七轮验收最小返工（2026-08-17，测试清理，未 stage/commit/push）** — 修正 remediation2 模型分支契约测试的环境清理：临时 `.env` 注入的 `LLM_MODEL=old-model` 不再泄漏为跨测试进程环境变量，保持配置优先级契约与后续 remediation4 组合测试可重复运行。**计划 3.2 保持 `[~]`，等待独立验收。**

- **Phase C / 计划 3.2 第七轮最小返工（2026-08-17，TUI 配置边界，TDD RED→GREEN，未 stage/commit/push）** — `tui/env_check.py` 不再独立加载 `.env`，首次引导仅依据统一配置层注入后的 `API_KEY`/`BASE_URL` 判定；TUI 设置与 onboarding 只通过统一持久化/`reset_settings()` 刷新路径处理 `.env`，不再静默覆盖显式进程环境变量，并补充 fresh-process 隔离契约测试与中英文配置优先级说明。API_KEY/BASE_URL 继续归属 LLM gateway，未改检索策略、dynamic Top-K、拒答、reranker、Graph、citation、P1.0/P1.1、评测冻结资产或数据集。**计划 3.2 保持 `[~]`，等待新的独立验收。**

- **Phase C / 计划 3.2 独立验收（2026-08-14，只读审计 + 隔离 fresh-process 探针 + 全量测试；零 LLM/网络/ModelScope，未 stage/commit/push，未修改任何 C 线源码）** — 结论固定为 **`C_3_2_DECISION = STOP_C32_ACCEPTANCE_FAILED`**（报告：`results/config-contract-acceptance/c32-acceptance-report.md`）。9 项门槛独立复核，8 项通过：Settings 唯一默认值来源（rag/security/TUI/CLI/Graph 全部消费同一 Settings，残留并行字面量均为值一致兜底并如实记录）；`MNEME_DATA_DIR`（默认 `~/.mneme`、`~` 展开、相对路径绝对化，Chroma/BM25/manifest/模型缓存均落数据根，导入/`get_settings()` 零写入——临时目录探针证明不写包目录/CWD/真实用户目录）；`.env` 优先级（真实 env > CWD `.env` > 契约默认）与 `reset_settings()` 后新值生效（含 rag 常量刷新回调）；用户 Top-K `(3,20)` 与内部检索宽度 `(70,12,70)` 明确分离；非法配置在导入期 fail-fast（临时数据根零创建，含 `.env` 非法值）；`MNEME_OFFLINE=1` 仅禁隐式 ModelScope（fake spy 零调用、缺本地模型给纯本地错误、本地模型照常加载）；无新增 production capture/trace/遥测/检索算法/Graph 算法变化（对 HEAD diff 逐 hunk 审计；Graph 用户 Top-K 默认 3/50→3/20 属已声明的契约统一）；受保护资产 367 文件全量测试前后逐文件 SHA-256 与合并摘要 `6c797801…` 完全一致。测试：配置定向 147 passed、相关回归 275 passed、全量 pytest 2566 passed / 8 skipped（exit 0）、零写入编译 68/68、`git diff --check` exit 0。**阻断缺陷（另开修复任务，本验收未自行修复）**：TUI 会话内 LLM 模型切换回归——`tui/service.py::_llm_model` 改读缓存 Settings 后，`tui/screens/chat.py` 的 `/models` 与 `/settings → LLM Model` 只写 `.env`/`os.environ` 而不调用 `reset_settings()`，会话内切换后同进程查询仍用旧模型直至重启（fresh-process 探针 `["deepseek-chat","deepseek-chat","switched-model"]` 复现；返工前该路径为调用期 os.getenv 读取、即时生效）。如实边界：仓库遗留 `None/chroma.sqlite3`（08-12 22:16 首轮实现窗口产物，当前代码未复现该落点）与 `data/chroma/`（08-04 遗留）待卫生清理；`tests/test_source_identity.py` 未隔离 `MNEME_DATA_DIR` 时向真实用户目录 `~/.mneme/chroma_db` 写 `source_identity_test.*`（测试卫生项）。本记录仅陈述独立验收结果与范围，**不构成已提交、已发布或生产启用的任何声明**。

- **P1.1-G0：生产检索观测、精确 replay 与隐私边界契约设计（纯设计阶段，未实现任何 capture，未 stage/commit/push）** — 承接 P1.0 `STOP_EVIDENCE_INSUFFICIENT`，产出 `plans/P1.1-PRODUCTION-OBSERVABILITY-REPLAY-CONTRACT-2026-08-13.md`（目标/非目标、三级 opt-in、事件 schema、不可变/删除/replay 规则、失败模式表、owner 决策表、停止条件 + 现有可观测性矩阵附录）：目标只限五个问题（dense/BM25 通道归因、漏斗环节定位、sync/stream 对照、rewrite/decompose 计划归因、受控实验前置）；**三级显式 opt-in**（Off 默认关闭 / Minimal diagnostic 显式开启 / Exact replay 单独同意），明文 query/history/原始模型响应默认不采集（哈希或 owner 逐项批准）；**版本化事件 schema**（`trace.begin`/`rewrite.decided`/`retrieve.dense`/`retrieve.bm25`/`fusion.rrf`/`cutoff.dynamic_top_k`/`refusal.decided`/`selector.applied`/`context.built`/`trace.end` 等 14 类事件，沿用稳定 source_id/chunk_id/指纹身份，禁止 basename/正文匹配重建）；**封存规则**（JSONL 行哈希 + manifest 自哈希闭环、历史 segment 不可原地改写、删除可见且删除后不可 replay、Exact replay 默认零 LLM 注入已记录 plan、漂移逐项 fail-closed/warning-only）；**失败模式表**（10 类，回答永远优先于可选观测）；**owner 决策表**（8 项：exact replay 是否允许、各敏感字段是否允许保存、路径/加密/保留期/删除、consent UX、stream/sync 对照、性能开销、样本量门槛、answer-level promotion gate）；**停止条件**（未获 owner 明确决定前不得实现真实 production capture）。**只读核验结论**：当前生产路径不存在任何持久化 trace——`GLOBAL_METRICS`（`src/metrics.py:186`）无 persist_path、`llm_gateway._call_records` 内存 500 条、通道级候选在 `rrf_merge` 内即丢失、rewrite/decompose 的 `StageProvenance` 不落盘且 served version 固定 `"unknown"`；G1-S harness 保持 `CAPTURE_MODE="synthetic_only"` 不改造为生产采集器。**明确不承诺**：本设计不改任何默认产品策略（dynamic top-k / selector max_per_source / 拒答 / reranker / Graph / rewrite-decompose），不宣称质量提升，local-only 不称云端遥测，未实现任何采集。

- **P1.0：生产检索—证据漏斗只读根因诊断（全程只读，零代码修改，未 stage/commit/push）** — 结论固定为 **`P1.0_DECISION = STOP_EVIDENCE_INSUFFICIENT`**。基于当前生产源码 + 冻结产物（`evaluation/product-baselines/v2.0.11-frozen-contract-hardened/per-case-retrieval-results.jsonl` 等）+ 确定性本地复算（不落盘、零 LLM）：漏斗 case 级瀑布（105 个 chunk-truth case）——候选召回 96.2% → final context 保留 61.0%；损失分层：候选完全缺失 4/105（根因不可分，无通道级 trace）、dynamic top-k 截断 18/105（cut 分布 12–61）、selector 损失 17/105（C2b 细分显示**全部**为 `max_per_source=3` 同源跳过、0 例为 top_k 截断）、相邻扩展重截断 2/105；parent 扩展在 v2 corpus 不触发（1006 chunks 全 normal）；context 字符预算默认不触发（60000 vs ~3800 实际）。**不推荐任何改动的依据**：selector S0/S3 受控消融（`results/graph-gate/selector-ablation-20260804T202048/`）证明检索层指标显著改善（context_recall 0.666 vs 0.577，95%CI 不含 0）不传导答案质量（answer_point_coverage 0.660 vs 0.662，McNemar p=0.625）→ AUTOMATED_DIAGNOSTIC_NO_GO；拒答阈值扫描（`refusal-threshold-scan-20260805T154407`）NO_GO（RRF 分数带不可分离，false_refusal 10–15/94）；特征化拒答仅 4 FR/6 SR 样本不足；reranker 臂 recall 无增益；Graph 已有正式 NO-GO。rewrite/decompose 不可精确归因（继承 F0：无不可变 production trace）。**后续观测需求**（P1.1-G0 的输入）：通道级检索 trace、不可变 production query-plan trace、stream(20)/sync(70) 对照、false-refusal 扩充样本 + 未查看 holdout。全程未修改 v2.0.11/frozen/revisions/G1-S/数据集/配置，未调用 LLM/API/网络。

- **Phase C / 计划 3.2「数据目录与配置统一」第六轮返工：ALPHA/范围容器/gateway 温度 fail-fast 闭环 + BASE_URL 文档修正（独立验收第六轮复现缺陷，TDD RED→GREEN，未 stage/commit/push）** — ① **共享 ALPHA 校验（`src/config.py`）**：新增 `validate_alpha`（仅接受有限、非布尔数值且 0.0–1.0，拒绝 NaN/inf/非数字/布尔；错误信息含 `ALPHA`；字符串数值兼容保留并有测试说明）；`Settings.__post_init__` 与全部显式覆盖入口（`graph_rag_pipeline`/`graph_query_stream`/`cli_loop._graph_rag_answer`）共用——实测复现（`alpha=2.0` 曾进入 `prepare_graph_index()` 写路径；`alpha=nan` 曾进入 retrieval；CLI Graph 路径 `alpha=2.0` 曾进入 retrieval）修复后均在索引构建/检索前抛含配置名的 ValueError 且调用数 0。② **用户 Top-K 范围容器校验**：新增 `validate_user_top_k_container`（`validate_user_top_k_range` 兼容保留），`answer_query_stream`/`graph_query_stream` 在任何下标使用、`max(top_k_range)`、planner/retrieval 之前完成——实测复现（`(3,20,999)` 曾只验前两个元素随后进入 planner/retrieval；`(3,)` 曾抛 IndexError）修复后 `(3,20,999)`/`(3,)`/非序列/布尔/浮点均抛含 `LLM_TOP_K_MIN`/`LLM_TOP_K_MAX` 的 ValueError 且调用数 0；用户 3–20 与内部 70/12/70、Graph 内部 3/50 的分离未变。③ **gateway 直接调用温度 fail-fast**：`llm_gateway.llm_call` 在创建 client/发起请求前对最终 temperature（显式或 Settings 解析）统一校验——实测复现（`temperature=2.5` 曾到达 `client.chat.completions.create`）修复后 `2.5`/`-0.1`/NaN/inf/True 均抛含 `LLM_TEMPERATURE` 的 ValueError 且 `_get_client` 0 调用；`llm_call_safe` 非法温度零 client/零网络。④ **布尔值拒绝**：`validate_llm_temperature(True)` 曾返回 1.0，现拒绝 True/False（合法字符串数值保留，测试说明）。⑤ **文档修正**：`.env.example`/`README.md`/`README.zh.md` 的 `BASE_URL` 明确为必填 gateway 配置（无内置默认值；仅设置 `API_KEY` 以 `API_KEY or BASE_URL not configured` fail-fast），不再虚构默认值。未改检索策略、dynamic Top-K 数值、拒答默认策略、reranker、Graph 默认策略、citation 语义、`RAG_REFUSAL_THRESHOLD` G1-S 逐调用语义（G1-S/Graph/CLI 回归零漂移）。**TDD**：新增 `tests/test_config_remediation6_contract.py`（31 个：RAG/Graph 流式 `(3,20,999)`/`(3,)`/非序列/布尔/浮点拒绝且 planner/retrieval/gateway 零调用、`graph_rag_pipeline(alpha=2.0)` 索引构建零调用、`graph_query_stream(alpha=nan)` 与 CLI `alpha=2.0` retrieval 零调用、`llm_call`/`llm_call_safe` 非法温度（2.5/-0.1/NaN/inf/True）零 client、合法 `0.66`/`0.7`/`(3,20)` 行为保留、fresh-process 三类 fail-fast 零调用）——**RED 26 failed / 5 passed**（5 个通过项为修复前即满足的锁定测试：浮点元素经元素校验器拒绝、合法路径、字符串数值兼容，如实标注）→ **GREEN 31 passed**。验证（全部系统 temp、fake API_KEY/BASE_URL、fake/fail-fast gateway 与检索，零真实 LLM/网络/密钥/主目录写入）：配置契约 + remediation2/3/4/5/6 + `test_llm_gateway.py` + `test_env_security.py` + `test_onboarding.py` **216 passed**；planner/capture/Graph/CLI/citation/retrieval/refusal 回归（13 文件）**298 passed / 4 skipped**；清空真实凭据 + CWD=系统 temp 隔离验证（remediation6/5 + gateway + rewriter + decomposer + env_security）**133 passed / 4 skipped**（前后 API_KEY/LLM_MODEL 均不存在）；py_compile 6/6、C 线 `git diff --check` exit 0、新增文件 `git diff --no-index --check` 无 whitespace 错误、手工字节扫描 CLEAN（唯一 trailing space 位于 `src/rag.py:1924`，为 HEAD 既有、不在本轮 diff，未触碰）。**计划 3.2 保持 `[~]`，等待新的独立验收。**

- **Phase C / 计划 3.2「数据目录与配置统一」第五轮返工：显式覆盖值 fail-fast 统一校验（独立验收第五轮复现缺陷，TDD RED→GREEN，未 stage/commit/push）** — ① **共享校验器（`src/config.py`）**：新增 `validate_llm_temperature`（有限数值且 `0.0–2.0`，拒绝 NaN/inf/非数字；错误信息含 `LLM_TEMPERATURE`）与 `validate_user_top_k_range`（两个整数、均 ≥ 1、min ≤ max；错误信息明确关联 `LLM_TOP_K_MIN`/`LLM_TOP_K_MAX`）；`Settings.__post_init__` 改用同一校验器（仅保留 `.env` 修正提示差异），Settings 与显式覆盖入口共用同一规则。② **显式覆盖 fail-fast（在任何进入规划器、检索器、LLM gateway 或写路径之前）**：`answer_query`、`answer_query_stream`（校验在计算 `max(top_k_range)` 与 `_plan_query_runtime` 之前）、`prepare_answer_evidence`、`_plan_query_runtime`、`generate_answer`、`answer_with_llm_history(_stream)`、`graph_rag.graph_query_stream`、`graph_rag_pipeline` 均在解析后立即校验——实测复现（`temperature=2.5` 曾进入规划器触发 rewrite/decompose LLM 路径；`top_k_range=(0, 20)` 曾以检索宽度 20 进入规划器）修复后非法值抛含配置名的 ValueError，且 planner/retrieval/gateway 调用数均为 0。③ **合法路径不变**：显式 `temperature=0.66` 继续优先于 Settings 并贯穿 rewrite/decompose；合法 `(3, 20)` 的检索宽度仍为 `max(top_k_range)=20`；未改模型选择、检索宽度策略、动态 Top-K、拒答、reranker、Graph 默认策略、citation 语义（G1-S 全部测试零漂移）；公开签名未动。④ **whitespace**：`tests/test_query_plan_capture.py` 移除文件末尾多余空行（字节级只删末尾空行，未格式化无关内容）。**TDD**：新增 `tests/test_config_remediation5_contract.py`（17 个：同步/流式入口 `2.5`/`-0.1`/`NaN`/`inf` 拒绝且零调用、`(0,20)`/`(21,20)` 拒绝且零调用、规划器与 `prepare_answer_evidence` 直接调用路径拒绝、`generate_answer`/`answer_with_llm_history` 拒绝且 gateway 零调用、合法 `(3,20)+0.66` 成功且显式优先 + 宽度 20、fresh-process 温度/Top-K fail-fast 零调用）——**RED 16 failed / 1 passed**（1 个通过项为合法路径锁定测试，修复前即应通过，如实标注）→ **GREEN 17 passed**。验证（全部系统 temp、fake API_KEY/BASE_URL、fake/fail-fast gateway 与检索，零真实 LLM/网络/密钥/主目录写入）：配置契约 + remediation2/3/4/5 + `test_llm_gateway.py` + `test_env_security.py` + `test_onboarding.py` **185 passed**；planner/capture/Graph/CLI/citation/retrieval/refusal 回归（13 文件，含 `test_graph_rag_batch`/`test_cli_loop`）**298 passed / 4 skipped**；py_compile 5/5、C 线 `git diff --check` exit 0、新增文件 `git diff --no-index --check` 无 whitespace 错误、手工逐文件扫描 CLEAN（tracked 文件行尾风格逐字节保持 CRLF/LF 不变）。**计划 3.2 保持 `[~]`，等待新的独立验收。**

- **Phase C / 计划 3.2「数据目录与配置统一」第四轮返工：显式 temperature 贯穿查询规划 + TUI 温度范围统一（独立验收第四轮复现缺陷，TDD RED→GREEN，未 stage/commit/push）** — ① **缺陷 A：显式温度未贯穿规划**。`src/rag.py::_plan_query_runtime()` 新增向后兼容可选参数 `llm_temperature`（`None` 时调用期回退 `Settings.llm_temperature`，未传参行为不变）；`prepare_answer_evidence()` 新增 `llm_temperature` 参数并转发给规划器；`answer_query()` 与 `answer_query_stream()` 把各自已解析的显式温度传入规划路径——实测复现（Settings 0.10、调用者传 0.66 时规划路径 rewrite/decompose 曾使用 0.10）修复后：`LLM_TEMPERATURE=0.10` + 显式 `0.66` → 真实规划路径的 fake rewrite/decompose gateway 观察到 `0.66`；未显式传温度时仍使用当前 Settings（fresh-process：CWD `.env` 0.91 生效）。未改模型选择、检索宽度、provenance/capture 语义（G1-S 全部测试零漂移）。② **缺陷 B：TUI 温度范围**。`tui/screens/chat.py::_configure_settings()` 提示与合法范围统一为 `0.0–2.0`（与 Settings/`.env.example`/README 一致）：合法输入 `1.5` 原样写入 `.env` 并经 `reset_settings()` 立即生效（不再静默 clamp 为 1.0）；`>2`/`<0`/非数字显示明确错误（`error_panel`）并保持原配置不变——不写入 `.env`、不重置 Settings、不静默 clamp；未扩大其他配置项 UX。**TDD**：新增 `tests/test_config_remediation4_contract.py`（11 个：同步入口显式温度贯穿、流式入口显式温度贯穿、规划器 Settings 回退锁定、规划器显式温度优先、prepare 转发温度、fresh-process 显式温度 > CWD `.env`、fresh-process `.env` 温度生效锁定、TUI 1.5 保真保存、TUI 2.5/-1/非数字拒绝且不写不重置并有可观察错误）——**RED 9 failed / 2 passed**（2 个通过项为回退行为锁定测试，修复前即应通过，如实标注）→ **GREEN 11 passed**。验证（全部系统 temp、fake API_KEY/BASE_URL、fake/fail-fast gateway 与检索，零真实 LLM/网络/密钥/主目录写入）：配置三组 + remediation2/3/4 + `test_llm_gateway.py` + `test_env_security.py` **155 passed**；planner/capture/Graph/CLI/citation/retrieval/refusal 回归（11 文件）**258 passed / 4 skipped**；清空真实凭据 + CWD=系统 temp 隔离验证 **96 passed / 4 skipped**；fresh-process smoke 覆盖环境变量优先、CWD `.env`、路径稳定、离线 ModelScope 零调用、显式温度优先（remediation1/2/4 既有与新增用例）。py_compile 3/3、C 线 `git diff --check` exit 0；`git diff --cached --name-only` 仍为原 26 项，冻结资产/受保护目录零触碰。**计划 3.2 保持 `[~]`，等待新的独立验收。**

- **Phase C / 计划 3.2「数据目录与配置统一」第三轮返工：planner 双 .env 入口移除、model/temperature 统一委托、planning 温度贯通、gateway 测试隔离（独立验收第三轮复现缺陷，TDD RED→GREEN，未 stage/commit/push）** — ① **唯一 `.env` 入口**：`src/rag_query_decomposer.py` / `src/rag_query_rewriter.py` 删除模块级 `load_dotenv()`（第二套 `.env` 加载语义消除；`.env` 仅由 `src.config` 统一加载，API_KEY/BASE_URL 仍属 gateway 边界、两模块只做无 key/非法端点读取预检，不发起调用）。② **受管参数统一委托**：两模块 `_decompose_query_provenanced`/`decompose_query_llm`/`_rewrite_query_provenanced`/`rewrite_query_llm` 的 `model`/`temperature` 默认改 None、调用期从 `Settings` 解析（显式参数仍优先；消除未说明的 `deepseek-chat`/`0.0` 静态默认分叉；G1-S `StageProvenance` 记录解析后生效值，capture/replay 语义不变）。③ **planning 温度贯通**：`src/rag._plan_query_runtime()` 同时解析并显式传递 `llm_model` 与 `llm_temperature` 给 rewrite/decompose——`LLM_TEMPERATURE=0.66` 经真实 planning 路径到达 fake gateway 时值仍为 0.66（未改检索算法/Top-K/拒答/reranker/Graph 策略/citation 语义）。④ **测试隔离（不放宽 gateway）**：`tests/test_config_remediation2_contract.py` 两个 gateway 调用测试与 `tests/test_llm_gateway.py` 两个 extra_body 测试显式设置安全 fake `API_KEY`/`BASE_URL` 并继续 mock `_get_client`（此前依赖仓库根 `.env` 凭据泄漏进 pytest 进程才通过）；`tests/test_query_plan_capture.py::test_thin_wrapper_delegates_exactly` 改为 `_MOCK_ENV` + 确定性 fake `llm_call_safe`（消除对真实凭据/网络路径的依赖，并随契约改为“薄包装 = 以 Settings 解析值调 provenanced 实现”）。**TDD**：新增 `tests/test_config_remediation3_contract.py`（6 个：fresh-process 导入两模块不注入 package-root `.env`、两模块源码无 load_dotenv、planning 温度/模型贯通、包装默认委托 Settings、显式参数优先、planning 显式 llm_model 优先）——**RED 4 failed / 2 passed**（2 个通过项为 fresh-process 导入探针与显式参数优先锁定测试，修复前即应通过，如实标注）→ **GREEN 6 passed**。验证（全部系统 temp、fake、网络 fail-fast spy，零真实 LLM/密钥/网络）：配置三组 + remediation2/3 + `test_llm_gateway.py` + `test_env_security.py` **144 passed**；planner/capture/Graph/CLI/citation/retrieval 回归 **239 passed / 4 skipped**；**清空真实凭据 + CWD=系统 temp 的隔离验证 177 passed / 4 skipped**（唯一例外为 `test_query_plan_capture_hardening.py::test_create_context_rejects_relative_path_escaping_into_tree` 的既有 CWD=仓库根假设——该文件在仓库根下运行 239 passed 中通过，本轮未改其逻辑，如实标注）。py_compile 7/7、C 线 `git diff --check` exit 0；`git diff --cached --name-only` 仍为原 26 项，冻结资产/受保护目录零触碰。**计划 3.2 保持 `[~]`，等待新的独立验收。**

- **Phase C / 计划 3.2「数据目录与配置统一」第二轮返工：gateway 配置委托、reset 真实契约、陈旧消费者、Graph 内部 3/50 恢复（独立验收第二轮复现缺陷，TDD RED→GREEN，未 stage/commit/push）** — 修复五类复现缺陷，并**修正此前记录中“Graph 策略未改 / 仅用户 Top-K 3/50→3/20 属契约统一”的失实表述**（上轮实际把 `graph_rag_pipeline` 与 `cli_loop._graph_rag_answer` 的内部 `dynamic_top_k` 从固定 3/50 错绑到了用户 LLM_TOP_K 区间；本轮恢复，见④）。① **gateway 单一配置委托**：`src/llm_gateway.py` 移除自行 `load_dotenv()`（原 no-arg 调用经 find_dotenv 在非仓库 CWD 下仍会把 package-root `.env` 注入进程）与 `os.getenv("LLM_MODEL", "deepseek-chat")` 绕过——`llm_call`/`llm_call_safe` 的 model/temperature 默认改 None 并在调用期从 `Settings` 解析（显式传入值不受影响）；`API_KEY`/`BASE_URL` 保留在 gateway 边界（只读进程环境，不自行加载 .env）。② **`.env`/reset 真实契约**：`src/config.load_dotenv_at_startup()` 改为“初始环境变量快照 + 注入键簿记”刷新——`reset_settings()` 真实反映 CWD `.env` 文件修改（值更新/新增键/删除键），且绝不覆盖显式进程环境变量（含运行期被外部改写、如 TUI `os.environ` 同步或测试 monkeypatch 的键）；首次加载语义不变。③ **reset 后无陈旧消费者**：`src/graph_rag.py`/`tui/service.py` 不再 by-value 导入 `CHROMA_DB_PATH`/`EMBEDDING_MODEL_NAME`（新增调用期解析 `_graph_chroma_db_path()`/`_graph_embedding_model_name()`/`LocalRagService._chroma_db_path()`）；`src/security.py` 资源上限常量注册刷新回调随 reset 更新；`tui/screens/chat.py` 的 `/models` 与 `/settings → LLM Model` 改后走与 onboarding 相同的 `reset_settings()` 刷新路径，实际 LLM 调用参数立即使用新模型。④ **Graph 内部 Top-K 恢复既有 3/50**：`src/config.py` 新增固定常量 `GRAPH_DYNAMIC_MIN_K=3`/`GRAPH_DYNAMIC_MAX_K=50`（无 env 覆盖），`graph_rag_pipeline` 与 `cli_loop._graph_rag_answer` 恢复使用；用户 Top-K 区间（`LLM_TOP_K_MIN/MAX`，默认 3–20，TUI/流式）保持独立，`graph_query_stream` 仍从 Settings 解析用户区间；`.env.example` 与中英文 README 明确区分两者。⑤ **EMBEDDING_MODEL_PATH 构造期解析**：与其他受管路径一致，在 Settings 构造时完成 `~` 展开与相对路径绝对化（新增 `_resolve_embedding_model`），调用期 CWD 改变后实际 loader 参数不漂移；文档同步。**TDD**：新增 `tests/test_config_remediation2_contract.py`（21 个：fresh-process package-root `.env` 不泄入 gateway、`.env` 修改/删键 + reset、进程 env 优先且其余键刷新、Graph/TUI/security 调用期解析与刷新、TUI 模型切换→实际 LLM 调用参数、Graph 内部 3/50 与用户 3–20 分离、EMBEDDING_MODEL_PATH `~`/相对→绝对与 CWD 漂移、`.env` 离线翻转 + reset 后 fake ModelScope 零调用；全部 fake，零 LLM/网络/主目录写入）+ 更新 `test_config_startup_contract.py` CLI Graph Top-K 断言 3/20→3/50。**RED 21 failed / 1 passed**（唯一通过项为用户流式 Top-K 锁定测试，修复前即应通过，如实标注）→ **GREEN 22 passed**；受影响回归组（config/gateway/env_security/graph/CLI/citation/capture/retrieval 等 13 文件）**326 passed**；全量 pytest **2587 passed / 8 skipped**（exit 0，2566 + 21 新增，零回归）。py_compile 9/9、`git diff --check`（C 线范围）exit 0；`git diff --cached --name-only` 仍为原 26 项（不含任何本返工文件），受保护资产与冻结目录零触碰。**计划 3.2 保持 `[~]`，等待新的独立验收。**

- **Phase C / 计划 3.2「数据目录与配置统一」返工：唯一启动配置入口（独立验收后，TDD RED→GREEN，未 stage/commit/push）** — 首轮实现被独立验收判定不闭环（真实 `.env` 进入进程过晚、RAG 常量/TUI/Graph/CLI 静态默认与原始 os.getenv 分叉、CWD `.env` 不被加载、文档根随 CWD 漂移），本返工把配置收敛为「启动解析一次、处处消费同一 Settings」：**唯一启动配置入口**：`src/config.py` 在模块导入时——任何 Settings 构造之前（含 `src/security`/`src/rag` 的导入期 `get_settings()`）——从 `<启动目录>/.env`（CWD）加载一次（`load_dotenv(path, override=False)`：进程真实环境变量始终优先；无文件/无 CWD 静默跳过，零网络零写入）；`reset_settings()` 先重载 `.env` 再重建单例，并经**刷新回调注册表**（`register_settings_refresh_callback`）同步刷新 rag 模块级常量（`EMBEDDING_MODEL_NAME`/`EMBEDDING_MODEL_DISPLAY`/`CHROMA_DB_PATH`/`DEFAULT_LLM_MODEL`/`DEFAULT_TEMPERATURE`/`DEFAULT_REFUSAL_THRESHOLD`/`RAG_RERANKER_MODE`/`RERANKER_MODEL_NAME`——公开名称/签名全部保留；内部检索宽度 70/12/70 仍为无 env 固定常量）；`src/rag.py` 移除迟到的 `load_dotenv()`。**调用期默认（不再冻结静态默认）**：`answer_with_llm_history(_stream)`/`generate_answer`/`answer_query`/`answer_query_stream`/`_plan_query_runtime` 的 model/temperature/top_k_range 默认改 None 并在调用期从 Settings 解析；`retrieval_refused` 默认来自 Settings，逐调用 env 覆盖与非法值回退语义保留（G1-S 锁定测试全绿）。**单一消费者**：`validate_document_path` 使用 Settings 已解析的 `document_root`（新增 `document_root_explicit` 字段：未显式设置仍沿用历史不限根行为；显式设置后启动时绝对化、不随调用期 CWD 漂移）；CLI/Graph（`cli_loop._graph_rag_answer`、`graph_rag.graph_query_stream`/`graph_rag_pipeline`/`extract_entities_llm_batch`、`--alpha` 默认改 None）的 alpha/temperature/Top-K/llm_model 全部消费 Settings（Graph 用户 Top-K 默认 3/50→契约 3/20；检索策略函数 `graph_augmented_retrieve` 签名未动）；`tui/service.py` `_llm_model`/`_ensure_model` 改读 Settings、query 默认改 None 流经流式入口解析。**TDD**：新增 `tests/test_config_startup_contract.py`（11 个：fresh-process CWD `.env` 进 Settings+rag 常量、进程 env 优先、非法 .env 导入期 fail-fast、`.env`-only 离线 fake ModelScope 零调用、RAG 实际默认参数消费 Settings、reset 后常量刷新、流式签名 None、TUI RagApp CWD `.env`、CLI Graph alpha/temperature/Top-K 调用期解析、文档根 CWD 漂移两例）；**RED 11 failed / 51 passed**（三文件组，失败精确对应六类验收缺陷）→ **GREEN 62 passed**；`tests/test_config_contract.py` 流式签名断言随契约更新（top_k_range 默认 None），两处 dotenv 测试补 os.environ 显式还原（测试自身卫生）；`tests/test_graph_rag_model_selection.py` 三例更新为契约模式（env→reset_settings）。**验证**：受影响回归组 635 passed（唯一失败为既有 `importlib.reload` 顺序污染——与字母序全量无关，`test_phase_c_quality`+graph 模型选择单独跑 9 passed）；全量 `python -m pytest -q` **2566 passed / 8 skipped**（exit 0，较基线 2555 新增 11 个契约测试零回归）；py_compile、`git diff --check` 通过（exit 0）。**如实边界**：`retrieval_refused`/`query_plan_capture` 的逐调用 env 覆盖语义保留（G1-S 锁定）；evaluation.compare 对 `RAG_RERANKER_MODE` 的 setattr 消融臂语义不变；`RAG_WATCH_DIR` 仍为 TUI 专属 env-first；`API_KEY`/`BASE_URL` 所有权仍在 LLM gateway；`docker-compose.yml` 旧挂载（`./chroma_db`、`./models`）待另行统一；计划 3.2 保持 `[~]` 待独立验收，未改检索算法、Graph 策略、reranker 默认开关、拒答阈值语义、citation 行为与冻结资产。

- **Product P0.2.1：`rag_pipeline` 来源展示闭环（TDD RED→GREEN，未 stage/commit/push）** — 补齐 P0.2 第三条路径的展示缺口：此前 `src/rag.py::rag_pipeline` 用 `answer, _ = answer_query(...)` 丢弃了与 citation status 同源的 sources，用户只见引用状态行却看不到实际来源。修改仅限 `rag_pipeline`：接收 `answer, sources`，在回答之后、citation status 之前按 CLI 既有风格打印 `参考来源` 与 `sources`（与 `run_interactive_session` 一致：`\n参考来源：\n{sources}\n`）；空 sources（拒答等）不打印来源块；返回值仍仅为 `answer`，函数签名与其它路径行为不变；不新增标准 `--query` 参数（不属于本范围）。**同口径保证**：sources 与 status 的合法 ID 集来自同一 `answer_query` 返回值（同一 evidence、同一 context_k），`format_sources` 与 `valid_citation_ids_for_context` 均经 `make_citation_records` 按 rank 分配 `S{rank}`。**TDD**：`tests/test_cli_citation_integrity.py` 新增 `TestRagPipelineSourcesClosure`（5 个：合法 `[S1][S2]` 原回答不变 + 同一 `[S1]`/`[S2]` 来源块 + 随后"引用已验证"且顺序正确；非法 `[S99]` 原文保留 + 仍展示实际 `[S1]` 来源 + 随后"引用未验证"；拒答无来源块无 banner 且返回值不变；实际打印来源块 ID 与 status 合法 ID 集精确一致；生成仅一次本地 fake + `llm_call_safe` 零调用 fail-fast）。测试不 patch `answer_query`——patch `prepare_answer_evidence`（构造 evidence 跳过真实检索/规划）与 `answer_with_llm_history`（固定回答），sources 生成与 status 计算均走真实代码；`llm_call_safe` 被 patch 为 `AssertionError` side-effect（任何意外触达 LLM gateway 立即失败）。**RED 证据**：3 failed（合法/非法/口径一致三例因"参考来源"缺失失败）→ **GREEN 25 passed**（20 + 5）；拒答与零 LLM 两例防御性测试在 RED 下即通过（当前实现恰好满足）。**如实记录（测试自身修复）**：首轮 RED 中零 LLM 测试因测试代码把 `monkeypatch.setattr` 返回值（None）当作 mock 使用而 `AttributeError`——先修测试代码再复跑确认 RED；测试未触达真实 LLM/API。

- **Product P0.2：非流式 CLI 的 Citation Integrity parity（六条真实非流式产品路径接入引用终态，TDD RED→GREEN，未 stage/commit/push）** — 补齐 P0.1 之外的全部真实非流式用户入口，P0.1 规则不变（`[S99]` 绝不替换、非法/缺失 → `unverified` 且回答正文原样、拒答/API 错误/无证据 → `not_required`、只验证编号与 evidence 对应关系不声称语义已验证、零额外 LLM/API 调用、无全局可变状态）。**共享 helper**：`src/rag.py` 新增 `evaluate_answer_status(answer, valid_ids)`（拒答/API 错误/校验三态统一，`answer_query` 的 sink 逻辑改用它消除重复）；`src/citations.py` 新增 `format_citation_status_line(status)`（CLI 纯文本状态行：`⚠ 引用未验证：非法引用编号 …（原回答未改动）` / `⚠ 引用未验证：回答未引用任何来源（原回答未改动）` / `✓ 引用已验证（编号与来源一致）`；not_required/None → 不显示）。**六条路径接入（每条都按实际进入 prompt 的 context / 实际展示的 sources 计算合法 ID——`valid_citation_ids_for_context` 与 `format_sources` 同口径）**：① 标准 CLI interactive（`cli_loop.run_interactive_session` 标准分支：`answer_query(..., _citation_status_sink=...)` → 独立打印状态行，`history.append((query, answer))` 只存原始回答，提示绝不混入 history）；② 标准单次查询（`cli_loop.run_single_query` 标准分支：keyword-only `_citation_status_sink` 转发，返回 `(answer, sources)` 不变）；③ `src/rag.py::rag_pipeline`（sink + 状态行打印，返回值不变）；④ Graph CLI interactive（`run_interactive_session` graph 分支，同上 history 规则）；⑤ Graph `--query`（`graph_rag.main` 传 sink 给 `run_single_query` 并打印状态行）；⑥ `src/graph_rag.py::graph_rag_pipeline`（按 top_indices/context_k 计算合法 ID + `evaluate_answer_status` + 状态行打印，拒答短路分支不显示任何提示）。`_graph_rag_answer` 新增 keyword-only `_citation_status_sink`（第 7 步校验，与 graph streaming 同口径；不传时行为不变）。**TDD**：新增 `tests/test_cli_citation_integrity.py`（20 个：helper 单元 6 / `_graph_rag_answer` 真实校验 6（合法/非法/缺失/API 错误/零额外 LLM/无 sink 兼容）/ `run_single_query` 转发 3 / interactive 集成 3（标准+Graph banner 且第二轮 history 只含原始回答、verified 行）/ pipelines 3（rag_pipeline unverified 行、graph pipeline 两次调用 verified+missing、拒答无提示）/ `--query` main 1（SystemExit 0 + 状态行））RED（17 failed：`evaluate_answer_status` 不存在、sink 参数 TypeError、状态行未打印）→ GREEN 20 passed。**如实记录（测试修复）**：初版 pipeline 测试 patch `src.rag.answer_with_llm_history` 未拦截 graph_rag 的模块级 import 绑定，导致该测试意外走到真实 LLM（用户机器配置了 API_KEY）——已改为 patch `src.graph_rag.answer_with_llm_history`；`graph_rag.main` 的 `exit(0)` 以 `SystemExit` 抛出，测试用 `pytest.raises(SystemExit)` 断言退出码 0；graph interactive 的 fake 签名对齐 `_graph_rag_answer`。范围声明：未修改 v2.0.11/frozen/revisions/G1-S harness、模型配置或生产 trace/LLM 留存机制；最终测试全部使用本地 fake——但开发过程中曾因一次错误 patch 触发真实 LLM 调用（见上"如实记录（测试修复）"，已发现并修正），不声称全程零网络。

- **Product P0.1：Citation Integrity for Streaming UI（真实产品回答链路 + TUI 展示，TDD RED→GREEN，未 stage/commit/push）** — 让真实 TUI 回答明确区分"引用已验证"与"引用不可验证"，不再静默制造或伪造引用归属。**禁止"最近合法编号替换"**：`src/rag.py::_validate_and_repair_citations` 不再调用 `_repair_citations`（函数已删除）——非法引用（如 `[S99]`）保留原回答文本并标记 unverified，绝不被自动改成 `[S1]`/`[S2]`（编号替换不能证明事实由该来源支持）；纯格式规范化暂不实施（仅在能无歧义证明指向同一合法 ID 时才允许）。**引用终态 side-channel（无全局可变状态）**：`src/domain.py` 新增 `CitationStatus`（state=verified/unverified/not_required + valid_ids/invalid_ids/missing/reason，只验证"编号是否对应实际 evidence"，不声称语义蕴含或事实真实性）；`src/citations.py` 新增共享校验器 `evaluate_citation_status` 与 `valid_citation_ids_for_context`（与 `format_sources` 严格同口径——实际展示的 sources 与合法 ID 集永远一致）。**标准与 Graph 流式路径一致**：`src/rag.py` 新增 `StreamResult`（可迭代，旧调用方 `stream, sources = ...` + `for chunk in stream` 不变），`answer_query_stream` 与 `src/graph_rag.py::graph_query_stream` 均返回 `StreamResult`——完整消费后对完整回答按"实际进入 prompt 的 context / 实际展示的 sources"计算合法 ID 并产出 `citation_status` 终态；拒答（`not_required(refused)`）与 API/transport 错误（`not_required(api_error)`，按产品固定错误消息判定，流式带 `[]` 非流式不带均覆盖）不要求引用；有文档证据时非法 ID 或零引用 → unverified；全部合法 → verified。**非流式一致**：`answer_query` 新增 keyword-only `_citation_status_sink`（不传时行为与旧调用方逐字一致），同一输入与 streaming 得到相同 `CitationStatus`（测试断言 `sink[0] == stream.citation_status`）；`evaluation.compare` 继续调用 `_validate_and_repair_citations`（签名不变），evaluation 臂生成的 answer 从此保留 LLM 原文（不再被改写美化），`invalid_ids/unverified` 如实报告。**TUI 展示**：`tui/screens/chat.py` 新增 `citation_status_panel` 纯函数（unverified → "引用未验证"独立提示含非法编号或"未引用任何来源"，verified → "引用已验证（编号与来源一致）"，not_required/None → 不显示，避免误导），`run_chat_loop` 在流完整消费后读取 `stream.citation_status` 并在回答/来源之外独立打印——提示绝不混入 `history`（集成测试断言下一轮 service 收到的 history 只含纯回答文本）。**零额外调用**：校验纯文本处理，不发起任何 LLM/API 调用（测试断言 `llm_call.call_count == 1`，规划零 `llm_call_safe`）。**TDD**：新增 `tests/test_citation_integrity.py`（25 个：status 单元 6 / valid-ids 口径 1 / standard stream 六态+零调用 7 / graph stream 3 / 非流式 parity 5 / TUI 渲染+集成 3）RED（`ImportError: cannot import name 'CITATION_NOT_REQUIRED'` 等）→ GREEN；`tests/test_citation_loop.py` 随去修复语义更新（5 个：非法引用保留原文 + `unverified=True` + `repaired=False`）。**迁移说明（旧调用方）**：`answer_query_stream`/`graph_query_stream` 返回 `(stream, sources)` 不变，stream 变为可迭代 `StreamResult`（附加 `citation_status` 属性，流消费完毕后可读）；`answer_query` 返回 `(answer, sources)` 不变，status 经可选 keyword-only `_citation_status_sink` 获取；`_validate_and_repair_citations` 签名不变但不再改写回答。范围声明：未修改 evaluation 数据集/frozen/revisions/G1-S harness/模型配置/生产 trace 或 LLM 留存机制；全部测试本地 fake（零 LLM/网络）。

- **Phase 6-G1-S.2：sealed replay 两处验收缺口修复（replay index 完整映射 + manifest 字节级 LF-only，TDD RED→GREEN，未 stage/commit/push）** — 只修 sealed replay 验收缺口，不进入 G1-P、不做生产 capture、不碰冻结资产。**缺口 1（replay 必须验证当前 index metadata 的完整 chunks 映射）**：此前 `_validate_chunks_contract` 只比对 recorded contract 与 chunks 文件，未比对 replay 传入的 `metadatas`——未命中候选的 metadata 漂移会漏过。修复：`_validate_chunks_contract` 返回当前 chunks 契约，replay 在任何 `prepare_answer_evidence(query_plan=...)` 调用前用 `_require_chunks_match_metadatas`（capture/replay 共用，新增显式重复检测）严格验证当前 `metadatas` 的稳定 `chunk_id` 有序列表与 `chunks_chunk_ids` 完全一致——缺失/重复/额外/顺序变化/未命中候选的 metadata 漂移全部 fail-closed。**缺口 2（manifest 原始字节强制 LF-only）**：此前 `manifest_path.read_text(encoding="utf-8")` 的 universal newlines 会掩盖 CRLF 篡改（self-hash 是 canonical JSON 哈希，不含换行，逻辑字段不变时 CRLF 版本可通过）。修复：先 `read_bytes()`，在 UTF-8 decode / JSON parse 前拒绝任何 `b"\r"`（与 capture.jsonl 同一策略），随后再解析并验证 self-hash / file bytes / line hashes / outputs closure；顺带补 `_validate_manifest` 对 `schema_version == CAPTURE_SCHEMA_VERSION` 与 `file == CAPTURE_FILE_NAME` 的 fail-closed 值验证（篡改后重算 self-hash 仍拒绝）。**TDD**：新增 `tests/test_query_plan_capture_hardening.py` 2 个测试组（9 个：`TestReplayMetadataMapping` 5——未命中候选漂移拒绝 + spy 断言 `prepare_calls == []`（未进入 prepare）/缺失/重复/额外/顺序；`TestManifestBytesAndFields` 4——仅 LF→CRLF 不改任何字段拒绝/`schema_version` 篡改+self-hash 重算拒绝/`file` 篡改+self-hash 重算拒绝/合规 LF manifest 通过）。**RED 证据**：6 failed（`DID NOT RAISE`——未命中候选 `chunk_2` metadata 篡改后 replay 错误成功；CRLF 被 text 读取掩盖；schema/file 篡改未拒）→ **GREEN 108 passed**（99 + 9）。既有 `test_query_plan_capture.py::test_replay_missing_chunk_id_rejected` 的 match 随完整映射校验更新（`"missing from current index"`→`"chunk_id"`，拒绝语义不变）；G1-S.1 全部行为保留（issuer capability / 受保护路径拒绝 / chunks 强制 / sync-only capture / outputs closure / 零 LLM 零检索 replay）。

- **Phase 6-G1-S.1：synthetic capture/replay 硬化验收修复（5 项阻断 + 2 项合同修正，TDD 双循环 RED→GREEN，未 stage/commit/push）** — 对 G1-S 实施的验收修复，不进入 G1-P、不做生产 capture、不碰冻结资产。**阻断项 1（capability 不可伪造）**：`SyntheticCaptureCapability` 改为 issuer 私有 marker 身份校验——普通调用方直接构造 `SyntheticCaptureCapability(object(), ctx)` 被拒；issuer 签发的可用；明确为误用防护、不宣称抵抗同进程恶意反射。**阻断项 2（chunks contract 强制）**：`chunks_path` 不再可选项——issuer 绑定的 `SyntheticCaptureContext`（输出根 + chunks 文件）贯穿 capture/replay；capture 记录 chunks 字节 SHA、行数、有序 chunk_id 映射并校验与 metadatas 一一对应（非 UTF-8/非 JSON 行/chunk_id 缺失/重复/映射不一致均 fail-closed 零写入）；replay 必须提供同一 chunks 输入，字节/行数/映射任一漂移拒绝，无 chunks 契约的旧 capture 一律拒绝（fail-closed，禁止兼容）。**阻断项 3（synthetic 边界运行时强制）**：`_assert_synthetic_boundary` 对输出根与 chunks 输入做 resolve 归一后判定，落入仓库受保护评测资产树（含冻结基线树）内即在任何 read/mkdir/write 前拒绝（open/mkdir spy 断言零调用）；issuer 三重校验（create_context / create_capability / 每次 `_require_capability` 使用期重校验），任意 `Path` 不再构成 escape hatch；输出根必须是新建目标（已存在目录一律拒绝，禁止混写）；保留"不是安全沙箱"的如实说明。**阻断项 4（outputs closure 复算）**：`_validate_manifest` 逐行复算 evidence receipt 有序 SHA 闭环并与 `outputs_sha256` 比对——只篡改 `outputs_sha256` 且重算 manifest self-hash 后 replay 仍拒绝（新增专项测试）。**阻断项 5（sync/stream profile 隔离）**：`_RuntimeQueryPlan` 显式记录 `planning_profile`（sync/stream）与 `retrieval_k`（实际检索宽度），`_plan_query_runtime` 新增 `planning_profile` 参数、`answer_query_stream` 传 `"stream"`；capture 只接受 profile=sync 且 retrieval_k=None 的 plan，stream plan 或宽度与 sync contract 不一致的 plan 在写文件前 fail-closed；产品 sync/stream 行为不变、无 streaming capture API。**合同修正 A（refusal threshold）**：`pipeline_contract` 记录并阻断比较解析后生效值（与 `rag.retrieval_refused` 同一解析逻辑：env 有效取解析值、非法回退 default）；原始 env 字符串仅作 provenance 记录（`provenance.refusal_threshold_env`），不参与阻断——`"0.050"`→`"5e-2"` 这类解析值不变的 env 变化不阻断。**合同修正 B（provenance warning-only）**：`_warn_provenance_drift` 扩展为对 replay 时可提供的全部 provenance 做 warning-only 比较——prompt SHA（rewrite/decompose）、model（captured stage `requested_model` vs 当前默认模型，`"unknown"` 不比较）、history（零 LLM replay 无输入可比，仅提示已记录）；不为比较调用任何 LLM。**API 变化**：`capture_synthetic_plan(runtime_plan, evidence, capability, metadatas, history=...)`、`replay_synthetic_plan(capability, model, collection, bm25, documents, metadatas)`——output_root/chunks 一律经 issuer 签发的 capability 提供。**TDD**：新增 `tests/test_query_plan_capture_hardening.py`（34 个：capability 4 / chunks 8 / 路径边界 8 / outputs closure 2 / profile 4 / refusal threshold 4 / provenance 3 / 字节一致性 1）；`tests/test_query_plan_capture.py` 既有 65 个随 API 更新调用点后全部保留。**循环 1 RED**（55 failed：`TypeError: _plan_query_runtime() got an unexpected keyword argument 'planning_profile'` 等）→ **GREEN 90 passed**；**循环 2 RED**（7 failed：outputs closure 未复算、无 refusal 解析值、无 model/history warn）→ **GREEN 99 passed**。**既有测试顺序污染（非本阶段缺陷，未修，如实记录）**：`test_refusal_policy.py::test_import_time_fail_fast_on_invalid_env` 的 `importlib.reload(rag)` 在 `SYSTEM_PROMPT += security boundary` 之前抛 ValueError → 同进程组合运行 `test_refusal_policy.py` + `test_phase_c_quality.py` 时 prompt-injection 断言失败；单文件各通过、全量按字母序（phase < refusal）不受影响。

- **Phase 6-G1-S（1/3）：synthetic query-plan capture 领域对象 + 两阶段 planner provenance（TDD RED→GREEN，未 stage/commit/push）** — 承接 G0.2 规格。**对象边界（G0.2 一）**：`src/domain.py` 新增 `StageProvenance`（guard_result/outcome/requested_model/temperature/max_tokens/timeout/max_retries/retries_used/served_version，served version 无可靠来源恒 `"unknown"`、不伪造、不捕获原始 LLM response 或其 SHA）、`CapturedCandidateHit`（rank/chunk_id/score——无 chunk_index）、`CapturedQueryPlan`（仅稳定可序列化字段，不得从 evidence 反推）、`CapturedEvidenceReceipt`（plan/base_candidates/retrieval fingerprint + context_sha256 + 有序 candidate/context chunk_ids + refused/refusal_reason）；`evaluation.compare.QueryPlan` 不持久化、产品代码不依赖 evaluation。**两阶段 provenance（G0.2 四）**：`src/rag_query_rewriter.py`/`src/rag_query_decomposer.py` 各新增 `_*_provenanced` 单一实现（outcome 枚举与既有 fallback 逐路径对齐：rewrite 6 种 no_rewrite_needed/no_api_key/invalid_endpoint/llm_failed/llm_returned_unchanged/llm_rewrite；decompose 6 种 guard_skipped/no_api_key/invalid_endpoint/llm_failed/invalid_json/llm_decomposed，含空 list/非 list/invalid JSON 归 invalid_json），公开 `rewrite_query_llm`/`decompose_query_llm` 改为薄包装（新增仅限关键字的 `_provenance_sink` 侧信道，对公开调用方不可见；被 mock 拦截时 stage 不产生，capture 将 fail-closed）。**TDD**：新增 `tests/test_query_plan_capture.py`（20 个 RED→GREEN，先 ImportError 后全绿）；既有 `tests/test_query_rewriter.py`+`tests/test_query_decomposer.py` 30 passed / 4 skipped 零漂移。

- **Phase 6-G1-S（2/3）：共享 planning helper `_plan_query_runtime`（同步/流式共用，行为零漂移；未 stage/commit/push）** — **私有 `_RuntimeQueryPlan`**（`src/rag.py`，仅运行时：best_score chunk_index→float、merged 实际观察顺序、scores_flat、两阶段 stage；`base_candidates` property 满足 `prepare_answer_evidence(query_plan=...)` duck-typing）。**`_plan_query_runtime`** 从 `prepare_answer_evidence` 普通分支与 `answer_query_stream` 抽出并共用：保留两条路径现状参数（prepare：`retrieval_k=None` → 沿用 retrieve 默认 k=70、dynamic top-k (12,70)；stream：`retrieval_k=max(top_k_range)`=20、dynamic top-k (3,20)；`retrieval_k=None` 时不传 k 关键字，兼容既有测试 fake 签名）；保留 `as_completed` 汇集、按 chunk 去重、rewrite 漂移防护与实际排序语义；**不改变生产 equal-score tie 行为**（稳定排序 + 插入顺序，无 chunk_id 次级排序）。`answer_query`/`answer_query_stream` 无 capability 时零新增 I/O、签名向后兼容。**TDD**：新增 7 个（helper↔普通分支一致、同分观察顺序保留、unpatched provenance 存在、流式↔同步 parity、query_plan 注入分支零规划零检索、两默认路径零写入 open-spy）；既有 `tests/test_phase_c_quality.py`/`test_refusal_policy.py`/`test_retrieval.py`/`test_llm_gateway.py` 等 123 passed / 4 skipped 零漂移。**如实记录**：发现既有测试顺序污染（`test_refusal_policy.py::test_import_time_fail_fast_on_invalid_env` 的 `importlib.reload(rag)` 在 `SYSTEM_PROMPT += security boundary` 前抛 ValueError → 同进程后续 `test_phase_c_quality.py::test_prompt_injection_...` 失败；全量按字母序 phase<refusal 不受影响，本次未修、非本阶段缺陷）。

- **Phase 6-G1-S（3/3）：`src/query_plan_capture.py` — synthetic capture/seal/plan-evidence replay（TDD RED→GREEN，未 stage/commit/push）** — **capability**：`SyntheticCaptureCapability` 不可 JSON/JSON/pickle 序列化（`__reduce__` 抛 TypeError），仅 `SYNTHETIC_CAPTURE_ISSUER` 可构造；普通 dict/string/object scope 一律拒绝（误用防护，不宣称抵抗同进程恶意代码）；`output_root` 必须显式传入（无默认持久化路径），已存在 trace 拒绝覆盖。**capture**：`capture_synthetic_plan(runtime_plan, evidence, capability, output_root, metadatas, chunks_path=None, history=None, ...)`——校验 capability/reranker=none/provenance 非 None（planner 被桩拦截 → fail-closed）/evidence.plan_fingerprint 与 runtime plan 一致/chunk_id 缺失重复；稳定候选 = `[rank, chunk_id, score]`（无 chunk_index；score 为有限 float 的 repr 往返字符串，拒 NaN/Inf/bool）；`base_candidates_fingerprint` 对有序列表计算（交换同分候选改变指纹，与 order-insensitive `retrieval_fingerprint` 职责分离）；行含两阶段 `StageProvenance` + `CapturedEvidenceReceipt`（plan/base_candidates/retrieval fingerprint、context_sha256、有序 candidate/context chunk_ids、refused/refusal_reason）+ `pipeline_contract`（schema/engine semver、reranker、remote_context_limit 实测值、compute_context_k 默认参、selector 上限、dynamic top-k 默认范围、adjacent max_expand、refusal 阈值 env+default）+ provenance 块（REWRITE/DECOMPOSE prompt SHA + history 指纹）——**不含原始 LLM response 或其 SHA**。**seal（G0.2 七字节约定）**：JSONL 行 `ensure_ascii=False, sort_keys=True, separators=(",", ":")+"\n"`；manifest `indent=1, sort_keys=True+"\n"`；Windows 显式 `newline="\n"` 禁 CRLF；`line_sha256`=移除自身字段后的 canonical 行 SHA；manifest 覆盖有序 line_hashes、原始 JSONL bytes SHA、有序 outputs receipt SHA、pop 自身后 self-hash；无时间戳/路径进 canonical（同 plan 不同目录两次 capture 字节逐位相等）。**replay**：`replay_synthetic_plan(capture_root, model, collection, bm25, documents, metadatas, chunks_path=None) -> list[PreparedAnswerEvidence]`——校验行 sha→manifest 三闭环→schema/mode→`_ReplayQueryPlan`（稳定 chunk_id 映射回当前 index，缺失/重复 fail-closed；rank 必须连续等于位置；score 必须 canonical；fingerprint 复算）→按捕获 rank 顺序插入 dict（依赖 prepare query_plan 分支 stable sort 保留同分插入顺序，`test_replay_preserves_captured_equal_score_rank` 锁定）→`prepare_answer_evidence(query_plan=...)` 零 LLM/零检索/零生成→receipt 逐项复算比对。**drift 契约**：pipeline contract 任一项漂移（selector/remote limit/engine semver/schema/reranker 非 none/chunks bytes SHA）→ fail-closed；prompt SHA 等 provenance 漂移仅 `warnings.warn` 不阻断。**TDD**：`tests/test_query_plan_capture.py` 累计 65 个（RED：38 failed ImportError→修复 line_hashes 定义→全绿）；全部使用本地 fake（零 LLM/网络/真实检索），synthetic fixture 与冻结数据无关；防冻路径扫描测试锁定模块源码不含冻结路径引用。

- **Phase 6-A：v2.0.11 冻结当前产品只读检索基线（真实运行，`evaluation/product-baselines/v2.0.11-frozen-current/`，不 stage/commit/push）** — 新增 `scripts/evaluate_v211_frozen_product_baseline.py` 与 TDD 测试 `tests/test_evaluate_v211_frozen_product_baseline.py`（27 个，全绿；全量 pytest 2197 passed / 8 skipped）。**冻结边界核验（fail-closed，零漂移）**：复算 freeze manifest（self-hash `cd75d485…` + 24 inputs/3 outputs SHA）、candidate manifest（字节 `6cab6786…` + self-hash `066b0f7f…` + 14 inputs）、targeted-review manifest（字节 `220ed9c2…` + self-hash `5445379f…` + 17 inputs）——61 项检查全部一致（含 `current-v2-draft.jsonl` = `annotations/v2-cases-draft.jsonl`、v2.0.10/v2.0.8 历史 revision 与 translation-equivalence 文件的分域解析；注意 `review-manifest.json` 同名不同义：freeze 中指 v2.0.11 targeted manifest、targeted 中指 v2.0.10 automated-review manifest）。**schema 兼容性**：v2.0.11 `draft-after.jsonl` 不能直接喂 v1 `EvalCase.from_dict`（draft 行含 v1 契约外字段 + `relevant_chunks` 含 `chunk_id` 键）→ 适配器内存映射并逐字段记录 mapping/不映射原因；真值以 `evidence-after.jsonl` 为准（`chunk_text_sha256` 149/149 与冻结 chunks 逐字节核验），draft↔evidence chunk 集不一致 17 case / source 集不一致 8 case 如实记录为冻结数据观测；mapping failure 0。**关键前提（parser 漂移，独立审计不混入指标）**：冻结语料由 `get_splitter`（纯分块）构建，当前运行时 `_load_index_chunks` 走 src/loaders + src/chunking v3 Section 分块——实测冻结 1006 chunks → 当前 chunker 重建 2947 chunks、文本精确命中仅 274（如 python-tutorial-zh.md 9%、vue-guide-zh.md 3%）；因此 chunk 级真值只对冻结 chunks 成立，基线以冻结 chunks 为索引内容（检索链 `model.encode`→Chroma hnsw:cosine→BM25(CJK n-gram)→RRF k=60 与产品逐函数一致），parser 行为单独报告。**实测指标（105 个真值 case 分母；31 个 refusal case 无 chunk-level truth，不伪造 0 分，仅检索分数观测）**：chunk recall@5=0.6159 / @10=0.6670 / @20=0.7583、nDCG@5=0.5272 / @10=0.5449 / @20=0.5708、MRR=0.5398、source recall@5=0.9524 / @10=0.9810 / @20=0.9810；按 language（en 43 / zh 42 / mixed 20）与 query_type（single_fact 32 / cross_document 26 / metadata 18 / multi_turn 17 / mixed_intent 12）分组；失败样本 33 个 chunk 未进 top-20、3 个 source 未进 top-20（最差 mixed-019 双零）。**隔离与安全**：Chroma 建于一次性临时数据目录（适配器自建 `PersistentClient`，从不引用 `src.rag.CHROMA_DB_PATH`，物理上不触碰用户持久化索引，不写 sidecar manifest/BM25）；不调用生成模型/LLM judge/无网络（HF_HUB_OFFLINE=1 强制离线）；冻结输入前后 SHA 快照逐字节不变。**确定性**：三次独立运行聚合指标逐位一致；同索引重复查询逐位一致；但跨构建 HNSW 图构建非确定（深 rank 近邻扰动，82 处 raw 差异、2 case 的 per-case 指标微变，如 zh-037 mrr 0.0714→0.0667）——如实记录为环境/链路事实（Phase 6-B 候选：固定 HNSW seed 或小语料精确检索）。产物 7 个：baseline-summary.json / per-case-retrieval-results.jsonl / failure-analysis.md / schema-compatibility-report.md / BASELINE_SCOPE.md / data-quality-mechanical-check.json（21 项六维机械检查全过）/ manifest.json（self-hash 约定 + 40 inputs/3 frozen outputs/7 outputs SHA + 代码 HEAD 8e3be0c（dirty）+ 依赖/模型身份 + 隔离方式）。`data-analytics:analyze-data-quality` skill 在本环境不可用（可用技能列表无此技能），已如实记录并实施等价确定性六维机械检查。**边界声明**：v2.0.11 仍是只读 CANDIDATE（activation_blocked=true、human_reviewed=false、TARGETED_REVIEW_BLOCKED），不代表 active、人工批准或 release；本基线不是 answer-quality/citation/refusal 精度评测（可测性审计见 failure-analysis.md）；未 stage/commit/push。

- **Phase 6-B0：chunk snapshot index contract（`src/index_contract.py`）+ v2.0.11 冻结产品 contract 基线（真实运行，`evaluation/product-baselines/v2.0.11-frozen-contract/`，不 stage/commit/push）** — 把 Phase 6-A 发现的 parser/chunker 漂移消除为受 manifest 约束的产品能力：`prepare_index`/`build_index` 新增可选参数 `snapshot`/`chroma_path`（默认 None → 既有 parser 路径与 sidecar 位置行为逐字节不变），显式请求时用**已验证的 chunks snapshot** 建索引并跳过 parser。**contract（17 项验证，全部发生在任何 collection/sidecar 写入之前，任一失败抛 `SnapshotContractError` 零写入）**：chunk-manifest `chunks_sha256` 复算（corpus_v2_prepare 约定）、chunk_id 唯一/格式 `{12hex}_chunk_{n}`/index 连续、per_source 计数、source 身份三方对齐（corpus-manifest canonical path ↔ 磁盘内容 SHA/size ↔ 全 64 位 `source_id`=路径哈希，chunk_id 前缀 == `source_id[:12]`）、调用方 source 集合与声明集合**精确一致**（无缺失/无额外）、逐 chunk 文本完整性哈希进契约指纹；身份主键为 source_id/source_path（basename 仅展示）。**产品集成**：collection manifest `config.snapshot` 记录契约版本/指纹/输入 SHA，指纹变化或缺失 → 安全重建（绝不误复用旧索引；解析路径检测到旧 snapshot 段也判不匹配）；`chroma_path` 贯通 prepare/build/add/remove/sync/compute_source_diff 与全部 sidecar 读写（新增可选参数，默认 CHROMA_DB_PATH 不变）；`python -m src.index_contract build …` CLI（exit 2=验证失败零写入）。**TDD**：新增 `tests/test_index_contract.py`（32 个）与 `tests/test_evaluate_v211_frozen_product_contract.py`（17 个）RED→GREEN；全量 pytest 2246 passed / 8 skipped（原 2197 + 49）；`tests/test_source_lifecycle.py` 断言随 `sync_sources` 可选参数更新；`tests/conftest.py` 顶部设置 `HF_HUB_OFFLINE`/`TRANSFORMERS_OFFLINE`（huggingface_hub 常量在 import 期缓存离线标志，pytest 进程内仅靠 rag 的 setdefault 仍会触发联网探测——测试基建加固，无产品行为变化）。**真实端到端（先复算后输出）**：freeze/candidate/targeted-review 61 项复算零漂移 + Phase 6-A baseline manifest 复算（self-hash + 40 inputs/3 frozen_outputs/6 outputs 字节）零漂移 → `prepare_index(snapshot, chroma_path=一次性临时目录)` 全产品路径建 1006 chunks 索引（collection manifest `config.snapshot` 与 BM25 sidecar 均验证一致）→ 136 case 生产检索。**实测指标（分母与 6A 一致：105 truth/31 refusal/0 mapping failure）**：chunk recall@5=0.6159 / @10=0.6670 / @20=0.7583、nDCG@5/10/20=0.5251/0.5427/0.5687、MRR=0.5350、source recall@5/10/20=0.9524/0.9810/0.9810——recall 与 source recall 与 6A 逐位一致，nDCG/MRR 差异 −0.0022/−0.0048 与 contract 自身跨构建 HNSW 方差同量级（如 zh-048 在两次 contract 构建间 mrr 0.5↔1.0、ndcg 0.693↔0.920，6A↔contract 差异为同一签名），per-case 指标差异 3 case / 检索集合差异 34 case 全部如实记录，不做掩盖。**隔离与安全**：Chroma + 全部 sidecar 在临时目录（`cleaned=True`），用户 `CHROMA_DB_PATH` 前后字节快照不变；冻结输入（revision/chunks/draft/processed 语料/corpus-manifest）89 项字节快照前后逐字节不变；无 LLM/生成路径、无网络（强制离线）；未 stage/commit/push。**产物 6 个**：contract-baseline-summary.json / per-case-retrieval-results.jsonl / contract-validation-report.md（字段映射表+验证清单）/ comparison-to-phase6a.md / data-quality-report.json（26 项六维+contract lineage 机械检查全过）/ manifest.json（self-hash + 55 inputs/3 frozen_outputs/6 phase6a_outputs/6 outputs SHA + contract 指纹 `4a78d5f3…` + 代码 HEAD 8e3be0c（dirty）+ 依赖/模型/隔离/确定性）。`data-analytics:analyze-data-quality` skill 在本环境不可用（可用技能列表无此技能），已如实记录并实施等价确定性机械检查。**边界声明**：v2.0.11 仍是只读 CANDIDATE（activation_blocked=true、human_reviewed=false），不代表 active、人工批准或 release；本基线不是 answer-quality/citation-faithfulness/refusal 精度评测；Phase 6-C（cross-document 检索改进）只有在本 contract 完整通过后才可讨论——本阶段**只提出，不实施**。

- **Phase 6-B0.1：chunk snapshot contract 产品入口硬化（修复 3 个已独立复现的阻断缺陷；真实运行 `evaluation/product-baselines/v2.0.11-frozen-contract-hardened/`，不 stage/commit/push）** — 对 B0 的 `prepare_index`/`build_index` 入口边界做 fail-closed 硬化，不进入 Phase 6-C、不做检索调参/query decomposition/reranker/HNSW seed/LLM/语料修订。**修复的缺陷（TDD RED→GREEN，`tests/test_index_contract.py` Group 4/5 新增 5 个失败用例）**：① `build_index` 先 `get_or_create_collection` 后校验 source 集合——不匹配时已产生空 collection 与 `chroma.sqlite3`；② 已有合法 snapshot collection 时传入缺少一个 source 的 `file_paths` 会静默复用、不触发 `build_index` 也不拒绝；③ `dataclasses.replace(valid_snapshot, chunks=篡改文本, validation=(), fingerprint="forged")` 仍被接受并写入篡改文本。**硬化机制（不信任内存对象，无私有布尔标记）**：`ChunkSnapshot` 新增 provenance 字段（chunks/chunk-manifest/corpus-manifest 路径 + repo_root）；`src.index_contract.verify_snapshot_current` 在**使用期**重跑 `load_chunk_snapshot` 全量验证并比对**重建契约指纹 / chunk 内容 / source 集合**（身份主键为 canonical path 与全 64 位 `source_id`，basename 仅展示），返回重建后的新 snapshot——索引内容永远来自受验证输入的重建；`src.rag.prepare_index` 与 `build_index`（各自独立）在任何 PersistentClient / 模型加载 / collection / manifest / BM25 sidecar 写入**之前**执行入口验证 + `file_paths` 与 snapshot 源集合**精确一致**校验；复用已有 collection 前预检 manifest `sources` 与 snapshot 一致（不一致 → 拒绝复用并强制安全重建，绝不静默复用或悄悄重建）；失败抛 `SnapshotContractError`/`ValueError`（fail-closed，绝不降级 parser）；`_ensure_client_and_check_rebuild`/`build_index` 双重防护。**TDD**：新增 `tests/test_index_contract.py` 硬化组（5 个）+ `scripts/evaluate_v211_frozen_product_contract_hardened.py` 与 `tests/test_evaluate_v211_frozen_product_contract_hardened.py`（13 个：旧 B0 manifest 复算 lineage、fail-closed 零产物、旧 B0/冻结输入字节不变、无 LLM、main 退出码 0/2）；全量 pytest **2264 passed / 8 skipped**（原 2246 + 18）；py_compile、git diff --check 通过。**真实端到端（先复算后输出）**：旧 B0 manifest 复算 64 项（self-hash `b3fc4b6e…` + 55 inputs/3 frozen_outputs/5 outputs 字节）零漂移 + 冻结 61 项 + 6A manifest 零漂移 → 硬化后的完整产品入口建 1006 chunks 索引（两次独立构建）→ 136 case 生产检索。**实测指标（分母与 6A/B0 一致：105 truth/31 refusal/0 mapping failure）**：chunk recall@5=0.6159 / @10=0.6670 / @20=0.7583、nDCG@5/10/20=0.5272/0.5449/0.5708、MRR=0.5398、source recall@5/10/20=0.9524/0.9810/0.9810——**契约指纹与旧 B0 逐位一致**（`4a78d5f3…`，证明入口硬化不改变索引内容）；与 B0 对比 recall/source recall Δ=0.0、nDCG/MRR Δ=+0.0022/+0.0048（B0 自身跨构建确定性即有此量级噪声：raw 差异 78 处 / 指标受影响 10 case，如 zh-048 mrr 0.5↔1.0——如实记录，不伪称逐 case 字节一致）；与 6A 对比 Δ≈1e-5 级（−0.0001/−0.0000）。**隔离与安全**：Chroma + 全部 sidecar 在一次性临时目录（`cleaned=True`），用户 `CHROMA_DB_PATH` 字节快照不变；旧 B0 产物与冻结输入前后字节不变（独立复算核验）；无 LLM/生成路径、无网络（强制离线）；禁止产物扫描无新增 overlay/active/split/locked/v2.1。**产物 7 个**：B0 同名 6 个（contract-baseline-summary.json 含 `hardening` 段与 `comparison_to_phase6b0`；data-quality-report.json 27 项含 `contract.b0_manifest_verified`/`contract.b0_lineage_sha`；manifest.json 含 `lineage.phase6b0_manifest_sha256=b3fc4b6e…` + self-hash + 55 inputs/3 frozen_outputs/6 phase6a_outputs/6 outputs SHA 闭环）+ `comparison-to-phase6b0.md`（修复说明 + Δ 对比 + 确定性）。`data-analytics:analyze-data-quality` skill 在本环境不可用（可用技能列表与 `~/.zcode/skills`、`~/.agents/skills` 均无此技能，已实际核对），如实记录并实施等价确定性机械复算。**边界声明**：v2.0.11 仍是只读 CANDIDATE（activation_blocked=true、human_reviewed=false），不代表 active、人工批准或 release；本基线不是 answer-quality/citation-faithfulness/refusal 精度评测；Phase 6-C 只有在本 contract 完整通过后才可讨论——本阶段**只提出，不实施**。

- **Phase 6-C1：v2.0.11 冻结基线上的跨文档检索受控消融（真实运行，`evaluation/product-baselines/v2.0.11-cross-document-ablation/`，不 stage/commit/push）** — 在已验收的 hardened snapshot contract（B0.1）上评估候选**确定性检索策略**是否可证明提升 cross-document evidence-chunk 排序；不改测试集/语料/v2.0.11，不调用任何 LLM/生成模型/LLM judge/联网 API/query rewriting 服务，不改默认产品检索行为。**探索结论**：draft 无 previous-turn 文本字段（仅 chain_id/turn 元数据）→ variant 只来源于原 query（已记录）；既有 `rag_query_decomposer/rewriter` 均为 LLM 驱动（红线禁用）；复用产品检索核心 `retrieve_hybrid_with_sources`（dense+BM25+RRF k=60）。**候选策略 `mechanical-clause-rrf` v1.0**（新增 `src/retrieval_ablation.py`，显式 opt-in）：variants = 完整 query（恒为 variants[0]）+ 强分句（`。！？；!?;`+换行）+ 长句（>60 字）弱分句（`，,、`）+ 中英语言边界段——全部为原 query 字面子串，去重、非空、上限 8，确定性可复算；逐 variant 复用产品检索核心；跨 variant RRF(k=60) 融合，单 variant 原样透传（single-query 臂与既有基线 runner 逐字节一致，证明 harness 不扰动默认路径），≥2 variants 稳定 tie-break 按 `chunk_id` 升序；每个结果保留 `source_id/source_path/chunk_id` + 来自哪些 variant 的 rank/score provenance；未知策略 `ValueError` fail-closed（不悄悄回退）。**TDD**：新增 `tests/test_retrieval_ablation.py`（16 个）+ `tests/test_evaluate_v211_cross_document_ablation.py`（26 个）RED→GREEN；全量 pytest 2306 passed / 8 skipped（原 2264 + 42）；回归 B0/B0.1/6A/contract/retrieval 151 个全绿。**评测脚本 `scripts/evaluate_v211_cross_document_ablation.py`（fail-closed 零产物）**：前置复算 frozen 61 项 + 6A（50 项）+ 旧 B0（64 项）+ **hardened manifest**（71 项：self-hash + inputs/frozen_outputs/phase6a_outputs/outputs 字节 SHA）任一漂移 → 零产物；同一冻结 contract 索引（`prepare_index`+snapshot，临时目录，cleaned=True）双臂对照（基线臂=既有 `bl6a.run_retrieval`，候选臂=新策略）；两次独立构建各跑双臂；cross_document 分组恰 26 case 单独聚合。**实测结果（结论与失败方向跨两次独立运行稳定；raw ranking/逐案例/部分聚合指标存在已记录的 HNSW 非确定性差异）**：基线臂 recall@5=0.6159 / MRR=0.5398 与 hardened 聚合一致（comparison_to_hardened aggregate Δ ≤ 1e-6，per-case 差异 31 case 为 HNSW 跨构建扰动）；候选臂全量 recall@5=0.5476（Δ−0.0683）、nDCG@10 Δ−0.0628、MRR Δ−0.0833、cd 分组 recall@5=0.2692（Δ−0.0256，n=26）——候选在证据 chunk 精排上**显著劣于基线**（cd source recall@5 反而 +0.0192，说明碎片 variant 找到对的 source 但挤占 top-5 的 evidence chunk）。**Gate 机械判定（6 条件，预先锁定，两次独立构建均要求满足）→ `NO_PROMOTION`**：未通过条件 cd_recall@5_gain（Δ−0.0256 < +0.03）/overall_recall@5_no_drop（Δ−0.0683 < −0.01）/overall_ndcg10_mrr_no_drop（Δ 均 < −0.01）/exceeds_recorded_noise（增益为负）；cd_source_recall@5_no_drop 与 all_checks_passed 通过——正确结果 NO_PROMOTION：保留实验结果并停止，不硬凑改进，**默认产品策略未改变**（候选仅记录于本消融产物，任何采用须经后续独立阶段决策）。**确定性（HNSW 噪声如实记录）**：基线臂跨构建 77 raw/1 metric case 差异、候选臂 225 raw/20 metric case 差异（候选多 variant 检索暴露更多深 rank 扰动）；cd recall@5 跨构建噪声 0.0（两次构建聚合逐位一致）；跨运行（RUN1↔RUN2）基线 Δ ≤ 2.6e-5、候选 Δ ≤ 5.2e-3（记录于 manifest verification.prior_run）。**产物 7 个**（manifest 自哈希 `45f40c63…` + lineage：hardened `57e3ede9…`/B0 `b3fc4b6e…` + 57 inputs/3 frozen_outputs/6 phase6a_outputs/6 phase6b0_outputs/7 hardened_outputs/6 outputs SHA 闭环 85 项零漂移）：ablation-summary.json / per-case-results-baseline.jsonl / per-case-results-candidate.jsonl / cross-document-analysis.md / selection-decision.md（决策边界：即便 EXPERIMENT_PROMISING 也不改默认策略）/ data-quality-report.json（核心 data-quality 检查通过；promotion gate 6 条件中 4 条未通过 → `NO_PROMOTION`，记录于独立 `promotion_eligibility` 段——失败 gate 是实验决策结果，不是数据质量失败，也不得混入「全过」表述（详见 Phase 6-C1.1 更正包）；`data-analytics:analyze-data-quality` 实际检查：zcode 运行环境不可用——本次会话技能列表、`~/.zcode/skills` 仅 brainstorming/test-driven-development、`~/.agents/skills` 仅 browser-skill、插件目录均无——实施等价确定性复算，不能声称所有环境均不可用）/ manifest.json。**隔离与安全**：临时 Chroma+sidecar 全部清理（cleaned=True），用户 CHROMA_DB_PATH 未触碰；冻结输入/B0/B0.1 产物 70+85 项字节复算零漂移；无 LLM/网络（强制离线）；未 stage/commit/push。**边界声明**：v2.0.11 仍是只读 CANDIDATE（activation_blocked=true、human_reviewed=false），不代表 active、人工批准或 release；not_measured：answer quality / citation faithfulness / answer-level refusal accuracy；生命周期 API 的 snapshot 不可变保护属未来 B0.2（本阶段未修改、未调用）；Phase 6-C 后续方向（如 conjunction 拆分的受控变体、variant 选择性融合）需另行决策，本阶段只提出不实施。

- **Phase 6-B0.2：snapshot 索引生命周期不可变（真实运行，`evaluation/product-baselines/v2.0.11-frozen-contract-lifecycle-hardened/`，不 stage/commit/push）** — 补上 B0.1 已确认的最后一个产品安全缺口：由受验证 snapshot 建出的索引**可读取、可由同一有效 snapshot 显式重建，但不得被生命周期 API 直接增删改**；不改默认 parser 索引与普通索引的生命周期语义，不改变 B0.1 的 `prepare_index/build_index` 重建语义（本阶段只封 mutation API）。**领域异常 `SnapshotIndexImmutableError`**（消息必含：snapshot index 是只读的；若需更新，只能以完整、重新验证通过的 snapshot 走显式 rebuild）。**Guard 覆盖的 API**（fail-closed，全部发生在任何文件解析 / model.encode / collection 读取写入 / `_commit_index_mutation` / BM25、manifest、graph sidecar 写入之前）：`add_files_to_index` / `remove_file_from_index` / `sync_sources(dry_run=False)`（入口即拒绝，先于 diff）/ `add_sources`（不能成为绕过 `add_files_to_index` 的旁路）；`compute_source_diff` 与 `sync_sources(dry_run=True)` 保持只读预览（实测零写入）。**识别机制（不依赖调用方传参）**：B0.2 build 在创建时向 collection metadata 持久化集合级 marker `mneme.snapshot_index=immutable`（保留 `hnsw:space` 与既有 metadata；sqlite 持久化、重开 client 仍在）；marker 是权威信号——marker 存在而 manifest/BM25 sidecar 缺失、损坏或与 marker 不一致时**保守拒绝**，绝不降级当作普通 parser collection；调用方提供错误 `chroma_path` 不能绕过 marker；旧 B0.1 collection（manifest `config.snapshot` 存在、尚无 marker）同样被阻断，由合法 snapshot rebuild 自动迁移/写入 marker。**Chroma 1.5.9 行为（实测确认，如实记录）**：`collection.modify(metadata=...)` 整体替换 metadata 且携带 `hnsw:space` 键即抛 ValueError（不支持修改距离函数）——旧 B0.1 迁移写入 marker 时显式排除 `hnsw:space` 键，实测抹除 metadata dict 中的 `hnsw:space` 不影响检索（HNSW 空间配置存于 collection 配置而非 metadata dict）；新建 snapshot collection 创建时即持久化 marker，`hnsw:space` 与既有 metadata 完整保留。**TDD（RED→GREEN）**：新增 `tests/test_index_lifecycle_immutability.py`（16 个：真实小型 snapshot index 四 API 拒绝且拒绝前后 count/ids/manifest bytes/BM25 bytes/graph cache 零变化、model/loader/encode/commit 未调用、dry-run/diff 只读、add_sources 非旁路、B0.1 manifest-only 阻断、marker-only/malformed/mismatch/错误 chroma_path fail-closed、parser/legacy 回归、真实冻结 1006/13 skip-guarded）+ 更新 `tests/test_index_contract.py::test_delete_and_reindex_keep_stable_identity`（删除被拒 → 合法 `prepare_index(snapshot=...)` 重建精确恢复完整 snapshot + marker 迁移断言）+ 新增 `scripts/evaluate_v211_frozen_contract_lifecycle_hardened.py` 与 `tests/test_evaluate_v211_frozen_contract_lifecycle_hardened.py`（10 个：完整流程/产物闭环/四段 fail-closed 零产物/受保护输入字节不变/临时 Chroma cleaned/main 退出码 0/2/真实 1006-chunk）。**评测脚本（fail-closed 零产物）**：前置复算 frozen 61 项 + 6A（50 项）+ 旧 B0（64 项）+ **hardened manifest（71 项：self-hash + inputs/frozen_outputs/phase6a_outputs/outputs 字节 SHA，与 C1 口径一致）** 任一漂移 → `BaselineDrift` 零产物；真实冻结 snapshot（1006 chunks / 13 sources）在一次性临时 Chroma 实测：四类 mutation 拒绝（`_EncodeForbidden` 模型证明 encode 未调用）、只读 diff/dry-run、fail-closed 矩阵（删 manifest/坏 manifest/普通 manifest mismatch/marker-only/错误 chroma_path）、旧 B0.1 形态阻断 + 合法 rebuild 迁移 marker（迁移后 cosine 检索仍可用）、普通 parser 索引 add/remove 正常——攻击后 collection count/ids 与 manifest/BM25/graph cache 字节**零漂移**（24/24 机械检查通过）。**产物 4 个**（manifest 自哈希 `17ef47d2…`，两次独立构建逐字节一致；inputs 闭环到 hardened manifest 与其已验证 lineage：lineage 段含 hardened `57e3ede9…`/B0 `b3fc4b6e…`/6A `57388f1c…` + frozen 三 manifest self-hash；outputs 3 项 SHA 闭环）：lifecycle-hardening-summary.json（guarded/readonly/rebuild API 清单 + marker 机制 + declarations：llm/network/chroma-persisted/overlay/active/split/locked/v2.1 全否，cleaned=True）/ lifecycle-immutability-report.md / data-quality-report.json（28 项 lineage+lifecycle 机械检查全过）/ manifest.json。**验证**：194 项定向+回归全绿（immutability/contract/B0/B0.1/6A/C1/C1.1/lifecycle/CLI）；两次构建 `diff -r` 逐字节一致；冻结 revision/6-A/B0/B0.1/C1/C1.1 13 项输入字节 SHA 前后零漂移；临时 Chroma 全部清理，用户 `CHROMA_DB_PATH` 未触碰；无 LLM/网络（强制离线）；未 stage/commit/push。`data-analytics:analyze-data-quality` 实际检查：zcode 运行环境不可用（本次会话技能列表、`~/.zcode/skills`、`~/.agents/skills`、插件目录均无）——实施等价确定性机械检查，不能声称所有环境均不可用。**边界声明**：本产物不是 active、release 或人工批准；v2.0.11 仍是只读 CANDIDATE（activation_blocked=true、human_reviewed=false），本阶段未解除也不改变该状态；C1/C1.1 决策仍为 `NO_PROMOTION`（本阶段未重跑检索/消融，未触碰 C1/C1.1 产物）。

- **Phase 6-B0.2.1：Snapshot Lifecycle Immutability 验收缺陷修复（独立审计复现两个阻断缺陷，TDD RED→GREEN，重建同一产物目录 `evaluation/product-baselines/v2.0.11-frozen-contract-lifecycle-hardened/`，不 stage/commit/push）** — 缺陷 ①：旧 B0.1 manifest-only snapshot collection（collection metadata 无 marker，正确目录 manifest `config.snapshot` 存在）可被错误 `chroma_path` 绕过——正确路径拒绝、错误路径 `remove_file_from_index` 返回 1 并删除 collection 数据且在错误目录生成 sidecar。根因：`_assert_mutable_collection()` 用调用方传入的 `chroma_path` 查 manifest 而未使用 collection 自身真实持久化目录。**修复**：新增特征检测 helper `src.rag._collection_persist_dir(collection)`（`collection._client._system.settings.persist_directory`，Chroma 1.5.9 实测可用、重开 client 仍正确），manifest-only 判定改用 collection **自身实际目录**，绝不信任调用方路径——错误路径与 `None` 均不可绕过（四 mutation API 全拒绝、collection count/ids 与正确目录 sidecar 字节不变、错误目录零文件、无 parse/encode/commit）；**无法推导真实位置（非本地 PersistentClient / 测试 double）时 fail-closed 保守拒绝**，绝不把「不确定」降级为「可修改」（测试 double 显式配置 persist_directory 以保持既有测试意图，`tests/test_source_lifecycle.py`/`test_source_identity.py`/`test_phase_b_manifest.py` 适配）。缺陷 ②：snapshot collection 被 `prepare_index(snapshot=None)` / `build_index(snapshot=None)` 默认 parser 路径重建时，Chroma 对既有 collection 忽略新 metadata 导致 immutable marker 残留——manifest/content 已是 parser 形态但 mutation 仍被 marker 阻断（状态不一致）。**修复（推荐严格策略）**：新增 `src.rag._assert_parser_rebuild_allowed(client, ...)`，对既有 snapshot collection（marker 或旧 B0.1 manifest `config.snapshot`）的默认 parser 重建在 **model 加载 / get_or_create / parser 解析 / collection mutation 之前** fail-closed 拒绝（`prepare_index` 与 `build_index` 各自独立防护）；`snapshot=...` 显式 rebuild 是唯一合法更新路径；新建 collection 的普通 parser 路径不受影响；错误 `chroma_path` 的 parser rebuild 按新目录语义只作用于错误目录（真实 collection 零触碰，边界如实记录）。**TDD**：`tests/test_index_lifecycle_immutability.py` 新增 Group 7（6 个：manifest-only + 错误/None chroma_path 四 API 拒绝且零写入 + 错误目录零文件、marker collection 拒绝 parser rebuild（model/parse/commit 未调）、manifest-only collection 拒绝 parser rebuild、位置不可推导 fail-closed、错误路径 rebuild 边界）+ `tests/test_index_contract.py::test_snapshot_index_not_reused_by_parser_path` 按严格策略更新为 `test_snapshot_index_rejects_parser_rebuild`（拒绝 + manifest 零写入）；**全量 pytest 2355 passed / 8 skipped**（原 2349 + 6）；py_compile / git diff --check 通过。**验证脚本扩展（33/33 机械检查全过，原 24 + 9 个 b021 检查）**：manifest-only + 错误/None chroma_path 四 API 拒绝、None 路径默认目录零残留、marker/manifest-only collection 拒绝 parser rebuild（`prepare_index` 与 `build_index` 双入口）、parser collection 默认 rebuild/复用不变、错误路径 rebuild 只作用于错误目录且真实目录零漂移。**产物重建**：仅重建 B0.2 产物目录（manifest 自哈希 `53eebc72…`，两次独立构建 `diff -r` 逐字节一致；前置复算 frozen 61 / 6A 50 / B0 64 / hardened 71 项零漂移；临时 Chroma cleaned=True；冻结 revision/6-A/B0/B0.1/C1/C1.1 输入字节零漂移；未 stage/commit/push）。**边界声明不变**：v2.0.11 仍是只读 CANDIDATE（activation_blocked=true、human_reviewed=false）；C1/C1.1 决策仍为 `NO_PROMOTION`；错误 `chroma_path` 的 rebuild 无法在 client 不可见时识别真实 collection 位置——按新目录语义仅作用于错误目录，真实 collection 零触碰（如实记录为边界，不声称「错误路径 rebuild 也拒绝」）。

- **Phase 6-B0.2.2：关闭 B0.2.1 审计发现的 persist-directory 身份绕过（独立审计复现两个阻断缺陷，TDD RED→GREEN，重建同一产物目录 `evaluation/product-baselines/v2.0.11-frozen-contract-lifecycle-hardened/`，不 stage/commit/push）** — 缺陷 ①：`chromadb.EphemeralClient()` 的 `settings.is_persistent=False`、`settings.persist_directory='./chroma'`（残留串）被 B0.2.1 的 persist-dir 特征检测当作真实位置——旧 B0.1 manifest-only collection（无 marker、真实 sidecar 在调用方 `chroma_path`）被 `remove_file_from_index` 绕过（实测返回 1、collection 1→0），违反「真实位置不可安全推导时 fail-closed」。缺陷 ②：外部以相对路径创建的 `PersistentClient(path="rel_db")` 在 Chroma 1.5.9 中原样保留相对串（实测确认）；工作目录 A 创建 collection + 旧 B0.1 snapshot manifest 后切换到目录 B 再 mutation，helper 在 B 下按新 CWD 解析 `rel_db` 查 sidecar——实测 mutation 返回 1、collection 1→0（mutation 时 abspath 已无法知道创建时真实位置）。**修复（fail-closed）**：`src.rag._collection_persist_dir()` 只接受 `settings.is_persistent is True` 的真实持久化 client **且** `persist_directory` 为稳定绝对路径——非持久化（EphemeralClient）/ remote / 测试 double / 缺失链路 / 仅剩未经记录的相对 persist path 一律返回不可验证，公开 mutation（四 API）与默认 parser rebuild 一律 `SnapshotIndexImmutableError`，绝不把「不确定」降级为「可修改」，也绝不用调用方 `chroma_path` 顶替真实位置；`src.rag._new_persistent_client()` 创建时把目标目录规范化为 `realpath(abspath(...))`，Mneme 自建 client 永远保存绝对真实位置（CWD 切换后旧 B0.1 判定仍落在真实目录，manifest 分支识别而非 fail-closed 兜底）；外部创建的真实绝对路径 PersistentClient 的普通 parser / legacy 生命周期不受影响。**TDD（RED→GREEN）**：`tests/test_index_lifecycle_immutability.py` 新增 Group 8（4 个：真实 EphemeralClient + 旧 B0.1 manifest-only 四 API 与 `build_index(snapshot=None, client=...)` 全拒绝且 collection/sidecar/错误目录零漂移、真实 PersistentClient 相对路径 + CWD 切换四 API（正确/None/错误路径）与 `prepare_index`/`build_index` 默认 parser 重建全拒绝 + 新 CWD 零残留、Mneme 自建相对 client 保存绝对路径且 CWD 切换后 manifest 分支阻断、外部绝对路径 client add/remove/sync/add_sources 正常）；修正 `test_wrong_chroma_path_rebuild_touches_only_wrong_dir` 的自比较缺陷（rebuild 前预存真实状态，rebuild 后与该预存状态比较）；既有测试 double 适配 B0.2.2 双重身份（`tests/test_source_lifecycle.py`/`test_source_identity.py`/`test_phase_b_manifest.py` 显式 `is_persistent=True`）。**验证脚本扩展（53/53 机械检查全过，原 33 + 20 个 b022 检查）**：EphemeralClient 实测特征（is_persistent=False + './chroma'）+ 四类 mutation 与 parser rebuild 拒绝 + 零漂移、外部相对 client + CWD 切换 fail-closed（四 API + None 路径 + prepare/build 双入口 + 零残留）、Mneme 相对 client 绝对化 + CWD 切换后阻断、外部绝对路径 client 生命周期正常；外部临时 client 显式 close 保证 cleaned=True；check detail 不含临时路径（保证两次构建逐字节一致）。**产物重建**：仅重建 B0.2 产物目录（manifest 自哈希 `d1e46795…`，两次独立构建 `diff -r` 逐字节一致；前置复算 frozen 61 / 6A 50 / B0 64 / hardened 71 项零漂移、inputs 42 项 mismatch=[]；frozen 三 manifest + 6A/B0/B0.1 lineage SHA 与 B0.2 记录一致；临时 Chroma cleaned=True；冻结 revision/6-A/B0/B0.1/C1/C1.1 输入零漂移；HEAD 8e3be0c 未变；未 stage/commit/push）。**全量 pytest 2359 passed / 8 skipped**（原 2355 + 4）；py_compile / git diff --check 通过（exit 0）。**边界声明不变**：v2.0.11 仍是只读 CANDIDATE（activation_blocked=true、human_reviewed=false）；C1/C1.1 决策仍为 `NO_PROMOTION`；错误 `chroma_path` 的 parser rebuild 在 client 不可见时仍按新目录语义只作用于错误目录（真实 collection 零触碰，如实记录，不声称「错误路径 rebuild 也拒绝」）。

- **Phase 6-B0.2.3：Chroma 测试/验证运行缓存隔离缺陷修复（只修测试与验证脚本的运行边界，不改产品功能、不改冻结数据，不 stage/commit/push）** — 独立复现的最小顺序 RED：`tests/test_index_lifecycle_immutability.py::test_external_relative_persistent_client_fail_closed` 之后运行 `tests/test_evaluate_v211_frozen_contract_lifecycle_hardened.py::test_lifecycle_verification_fixture_ok` 稳定失败（`b022.relative_prepare_parser_rebuild_rejected: no exception`，失败前出现模型加载输出——guard 在模型加载前未拒绝）。根因：前一个测试以 `PersistentClient(path="rel_db")` 创建的外部 client 测试结束后未释放，Chroma 1.5.9 的 `SharedSystemClient` 按 persist 标识全局缓存 system（相对标识 `rel_db` / `ephemeral` 跨测试复用错位）；验证脚本 b022 段再次以 `PersistentClient(path="rel_db")` 建 client 时复用旧测试目录的 system（collection 建在旧目录、manifest 写在脚本目录），`prepare_index(chroma_path=脚本目录)` 在该目录找不到 collection → `_assert_parser_rebuild_allowed` 的 `_collection_exists` 为 False → 放行 → 模型加载/解析/写入发生。产品 guard 逻辑本身无退化——是测试/验证运行的缓存隔离缺陷（实测对象错位）。**修复（两条腿，均不改 `src/rag.py` 生产运行路径、绝不在生产路径粗暴清空全局缓存）**：A 腿 `tests/test_index_lifecycle_immutability.py` 模块级 autouse fixture——每个测试结束调用 `tests/conftest.release_chroma_systems()`（close client → stop system → 清空 `SharedSystemClient` 缓存），同时保证 Windows 下 tmp_path 删除前文件锁已释放；B 腿验证脚本新增 `_release_shared_chroma_systems()`——`_verify_lifecycle` 入口释放一次（免疫脏缓存：测量对象绝不被复用错位）+ `run_lifecycle_verification` finally 释放一次（脚本作为 pytest 模块运行时不得向宿主进程泄漏缓存 / sqlite 文件锁，也保证临时目录删除前锁已释放）。**TDD（RED→GREEN）**：新增 `test_lifecycle_verification_immune_to_polluted_relative_cache`（先制造 `rel_db` 脏缓存且故意不释放 → 运行验证脚本必须仍全过、且结束后 `rel_db`/`ephemeral` 不在 `SharedSystemClient` 缓存）——修复前精确复现 no exception 失败（RED），修复后通过；`b022.relative_prepare_parser_rebuild_rejected` 断言**未删除未放宽**（干净环境中它仍在模型加载、解析、写入前拒绝）。**验证**：最小顺序复现 2 passed；`tests/test_index_lifecycle_immutability.py` + `tests/test_evaluate_v211_frozen_contract_lifecycle_hardened.py` 共 36 passed（25 + 11）；全量 pytest **2360 passed / 8 skipped**（原 2359 + 1 新回归测试）；py_compile / git diff --check 通过（exit 0）。**产物不变（无需重建）**：两次独立构建 `diff -r` 逐字节一致，且与 B0.2.2 产物目录逐字节一致——manifest 自哈希仍 `d1e467957c06230ab988cf057003e8084dd7442c9aece802681e27379044c914`，53/53 机械检查不变，outputs SHA 复算一致、inputs 42 项 mismatch=[]；前置复算 frozen 61 / 6A 50 / B0 64 / hardened 71 项零漂移；C1/C1.1 共 11 文件字节 SHA 复算零漂移；临时重建目录全部清理。**边界声明不变**：v2.0.11 仍是只读 CANDIDATE（activation_blocked=true、human_reviewed=false）；C1/C1.1 决策仍为 `NO_PROMOTION`；本阶段只修测试/验证运行边界——B0.2.2 安全行为未动（Ephemeral、外部相对路径、错误路径、None、四 mutation API、默认 parser rebuild 仍 fail-closed；外部绝对路径 legacy/parser 生命周期仍可用）。

- **Phase 6-B0.2.4：修复 B0.2.3 的两个验收阻断缺陷（真实双构建不确定性 + 全局缓存清理破坏其它模块 client；只修测试/验证运行边界与 B0.2 artifact 确定性，不改 `src/rag.py`、不改冻结数据、不 stage/commit/push）** — **缺陷 ①（产物不确定性）**：验证脚本把 `dict(collection.metadata)` 用未排序的 `json.dumps(..., ensure_ascii=False)` 写入持久化 check detail（`immutability.marker_persisted` / `immutability.hnsw_space_preserved` / `migration.marker_written_by_rebuild` 等 6 处）——collection.metadata 键序跨构建不确定，两次真实构建 `data-quality-report.json` 与 `manifest.json` 不一致（独立复现：未排序序列化对两个内容相同、插入顺序相反的 dict 输出不同字节；验收证据：A `d1e46795…` vs B `6d99c040…`）。**修复**：新增 `_stable_json(obj)`（`ensure_ascii=False + sort_keys=True`），6 处进入持久化产物的 detail 序列化全部改用（`marker_persisted` / `hnsw_space_preserved` / `readonly.compute_source_diff` / `readonly.sync_sources_dry_run` / `migration.marker_written_by_rebuild` / `integrity.zero_drift_after_attacks`）；审计结论：其余 `json.dumps` 为临时 sidecar 文件写入（dict 字面量键序固定）或 `BaselineDrift` 异常消息（失败即零产物），不进入产物字节；产物文件本体已用 `bl6a.canonical_json`（sort_keys）写入。**缺陷 ②（B0.2.3 全局释放破坏其它模块 client）**：B0.2.3 的 `_release_shared_chroma_systems()` 对全部 `SharedSystemClient` 执行 `system.stop()` + `clear_system_cache()`——运行前已存在的绝对路径 external PersistentClient 被 stop（独立复现：写入一条记录后调用该函数，原 collection `count()` 抛 `AttributeError: 'RustBindingsAPI' object has no attribute 'bindings'`；全量 pytest 实际 1 failed（`test_main_exit_codes`）/2359 passed/8 skipped，单测通过、跨套件顺序失败）。**修复（所有权边界）**：入口只回收已知会错位复用的相对别名 `_reclaim_relative_chroma_aliases()`（仅 pop + stop `rel_db` / `ephemeral` 两个相对标识，绝不动绝对路径 external client 的 system）；`run_lifecycle_verification` 运行前快照 `pre_rag_ids` / `pre_system_ids` 所有权边界；结束 `_release_owned_chroma()` 只关闭 / stop / 移除本次验证新建的 client 与 system（cur − pre ∪ 入口回收后重建的相对别名）——**不再调用 `rag.close_chroma_clients()`**（其关闭列表中全部 client，含非本次验证所有）与 `clear_system_cache()`（其清空全部缓存）；`tests/test_index_lifecycle_immutability.py` 的模块级 autouse fixture 同样改为 scoped cleanup（只释放本测试新建的 rag client 与 system 标识，运行前已存在的绝对路径 external client 保持可用）。`b022.relative_prepare_parser_rebuild_rejected` 断言**未删除未放宽**；B0.2.2 fail-closed 产品语义未动。**TDD（RED→GREEN）**：新增 `tests/test_evaluate_v211_frozen_contract_lifecycle_hardened.py` 3 个——`test_stable_json_metadata_order_independent`（两个内容相同、插入顺序相反的 metadata dict 生成完全相同的持久化 detail，B0.2.3 上 RED）、`test_two_independent_builds_byte_identical`（两次独立 verification 四个产物逐字节一致）、`test_external_absolute_client_survives_verification`（脚本运行前创建绝对路径 external PersistentClient + 记录，脚本运行后原 client 仍可读原记录、system 仍在缓存未被 stop——B0.2.3 上精确 RED）；已有 `test_lifecycle_verification_immune_to_polluted_relative_cache`（相对路径污染场景）保持通过。**验证（真实命令输出）**：双向最小顺序命令各 2 passed（immutability→eval 与 eval→immutability 两方向）；两文件联合 39 passed（25 + 14）；eval 单独 14 passed；全量 pytest **2363 passed / 8 skipped**（原 2360 + 3 新测试）；py_compile / git diff --check 通过（exit 0）。**产物重建（确定性修复 → canonical hash 变更，如实记录）**：真实双构建（两个独立临时输出目录）四个产物逐文件 byte SHA 对比 **diff_count=0**；随后重建 `evaluation/product-baselines/v2.0.11-frozen-contract-lifecycle-hardened/`——新 manifest 自哈希 `38482d1a68a68403f142bdeca62d442309aefa1b52a13b2160671d5e6351ad46`（复算 MATCH；旧 hash `d1e467957c06230ab988cf057003e8084dd7442c9aece802681e27379044c914` 因键排序稳定化而变更，属预期——绝不为保留旧 hash 而保留不确定性），3 outputs 字节 SHA 复算一致、42 inputs 项项匹配、53/53 机械检查不变、cleaned=True；前置复算 frozen 61 / 6A 50 / B0 64 / hardened 71 项零漂移；C1/C1.1 共 11 文件字节 SHA 复算零漂移；临时重建目录清理；HEAD 未变、未 stage/commit/push。**边界声明不变**：v2.0.11 仍是只读 CANDIDATE（activation_blocked=true、human_reviewed=false）；C1/C1.1 决策仍为 `NO_PROMOTION`；相对别名（`rel_db` / `ephemeral`）在测试/验证运行边界内必须回收、既有绝对路径 external client 必须保持可用——该所有权约定记录于脚本与 autouse fixture 的 docstring。

- **Phase 6-B0.2.5：修复 B0.2.4 的同进程顺序依赖缺陷（b022 相对 client 在 cwd_b 的真实 collection 读取 + prepare_index 检查级同目录 client 滞留；只修验证脚本运行边界，不改 `src/rag.py`、不改冻结数据、不改 B0.2.2 fail-closed 产品语义，不 stage/commit/push）** — **验收阻断证据（如实记录，非本环境复现）**：eval 文件单独实际 `1 failed, 13 passed`（失败 `test_temp_chroma_cleaned`）、两文件联合实际 `1 failed, 38 passed`（失败 `test_external_absolute_client_survives_verification`），两处堆栈均在脚本 line 680 `rel_ids_before = sorted(rag._collection_data(rel)["ids"])`——Chroma `InternalError: unable to open database file`；单测单独运行通过 → 同进程顺序缺陷（本环境多次重跑未触发，机制级缺陷确凿）。**机制**：b022 在 cwd_a 创建 `PersistentClient(path="rel_db")` 并写入后切到 cwd_b，却仍在 cwd_b 对 rel 做两次真实 collection 读取（首次 `rel_ids_before` 与末尾零漂移复读）——rel 的 system 只记录相对 persist 路径，`chromadb/api/rust.py` 以相对串 `persist_dir + "/chroma.sqlite3"` 作为 sqlite URL，连接一旦重开即按**当前 CWD** 解析（cwd_b 下无该文件 → unable to open database file）；期间 `prepare_index(chroma_path=<cwd_a>/rel_db)` 还新建/注册**同一物理目录**的绝对路径 Rag client（`_ensure_client_and_check_rebuild` 在 `_assert_parser_rebuild_allowed` 拒绝之前创建），且直至整个验证结束才释放——两个 system 同时持有同一 sqlite 文件。**修复（所有权边界 + 读取时机，不改 `src/rag.py`）**：① rel 在 cwd_a 创建/写入后**立即读取并保存** `rel_ids_before`；② 切到 cwd_b 后**先断言** `b022.relative_no_residue_in_new_cwd`（无 cwd_b/rel_db 残留），随后只做 guard 在任何 collection 读取之前就拒绝的 fail-closed 检查（四 mutation / None 路径 / prepare_index / build_index）——`b022.relative_prepare_parser_rebuild_rejected` 与 `b022.relative_build_parser_rebuild_rejected` 断言**未删除未放宽**；③ 真实 collection 零漂移（`b022.relative_zero_drift`）只在**临时切回 cwd_a 后**复读（真实读取，不用 mock 掩盖）；④ prepare_index 检查前快照 `rag._CHROMA_CLIENTS` id 与 `SharedSystemClient` 标识所有权边界，检查后 `finally` 立即 `_release_scoped_chroma()`（复用 `_release_owned_chroma(pre, pre, set())`：只关闭/stop/移除本检查新建的 client/system），rel_client 与运行前已有资源（含外部绝对路径 client）一律不动——不调用 `rag.close_chroma_clients()`、不调用 `clear_system_cache()`；⑤ 审计脚本全部相对 client/read 时机：唯一相对 persist client 是 b022 rel（修复如上）；mn client 经 `_new_persistent_client` 创建时已绝对化（abs sqlite URL 安全）；EphemeralClient 为内存 sqlite 无路径危害；其余 client 均绝对路径。**TDD（RED→GREEN，先写测试）**：新增 `tests/test_evaluate_v211_frozen_contract_lifecycle_hardened.py` 4 个——`test_relative_client_collection_reads_only_in_creation_cwd`（包装 `rag._collection_data` 记录相对 client 读取时的 CWD，断言任何读取发生时 `os.path.isdir(join(cwd, "rel_db"))` 成立——当前实现**精确 RED：violations 恰 2 次 cwd_b 读取**，对应 line 680/731 两个读取点）、`test_prepare_rejection_releases_same_dir_client_promptly`（spy `build_index` 检查时点断言 prepare 检查新建的「绝对路径 + basename rel_db」client/system 已即时释放——当前实现**精确 RED：`...\cwd_a\rel_db` 标识仍在缓存**；首版断言把相对标识 `rel_db`（rel_client 自身合法存活 system）误判为泄漏，收紧为绝对路径判定后仍对旧实现 RED；同时断言运行前外部绝对路径 client 不被关闭）、`test_consecutive_verifications_with_external_client_alive`（单测试内连续 3 次 verification（两次显式 data_dir、一次 own-temp），外部绝对路径 client 始终存活可读，own-temp cleaned=True）、`test_temp_chroma_cleaned_failure_sequence_regression`（完整复刻验收失败顺序：污染 `rel_db` 不释放 → 验证 → 建外部 client → 再两次验证，全部 status=ok + cleaned=True + 结束无相对标识残留）。**验证（真实命令输出）**：4 个新测试 4 passed；eval 文件单独 **18 passed**（14 + 4）；两文件联合 **43 passed**（25 + 18）；B0.2.3 最小顺序命令双向各 2 passed；全量 pytest **2367 passed / 8 skipped**（原 2363 + 4 新测试，exit 0，271.13s）；py_compile / git diff --check 通过（exit 0）。**产物重建（仅双构建一致后）**：真实双构建（两个独立临时输出目录）四产物逐文件 byte SHA 对比 **diff_count=0**（两构建 self-hash 均为新值）；随后重建 `evaluation/product-baselines/v2.0.11-frozen-contract-lifecycle-hardened/`——新 manifest 自哈希 `62680efdbc2d0966ef19c125673acdc2637b0ef4bfa2c3d4280ffd69e53b759d`（`bl6a.self_hash` 复算 MATCH；旧 hash `38482d1a6…` 因 b022 段检查执行顺序调整（no_residue 前置、zero_drift 移至 cwd_a 复读）而变更，属预期——绝不为保留旧 hash 而保留顺序缺陷）；3 outputs 字节 SHA 复算一致；42 inputs 项项匹配（mismatch=[]）；verification frozen/phase6a/phase6b0/phase6b01 全 True（61/50/64/71 项零漂移 fail-closed 在两构建中通过）；cleaned=True；data-quality-report 57 checks 全过；lineage phase6b01 `57e3ede9…` 不变。**C1/C1.1 零漂移**：C1（7 文件）+ C1.1（4 文件）共 11 文件字节 SHA 自闭环复算零漂移（C1 manifest self-hash MATCH + outputs mismatch=[]；C1.1 manifest self-hash MATCH + 对原 C1 文件 inputs mismatch=[]）。临时双构建目录清理；HEAD 未变、未 stage/commit/push。**边界声明不变**：v2.0.11 仍是只读 CANDIDATE（activation_blocked=true、human_reviewed=false）；C1/C1.1 决策仍为 `NO_PROMOTION`；B0.2.2 fail-closed 产品语义未动（Ephemeral / 外部相对路径 / 错误路径 / None / 四 mutation API / 默认 parser rebuild 仍拒绝，外部绝对路径 legacy/parser 生命周期仍可用）；所有权约定扩展记录于脚本与测试 docstring——相对别名（`rel_db`/`ephemeral`）在测试/验证运行边界内必须回收、既有绝对路径 external client 必须保持可用、检查级新建资源必须即时 scoped 释放。

- **Phase 6-C1.1：v2.0.11 跨文档检索消融「审计语义修正」（真实运行，`evaluation/product-baselines/v2.0.11-cross-document-ablation-audit-correction/`，不 stage/commit/push）** — 对 C1 产物的**有限报告/产物正确性修正**（只读审计：不重跑实验、不迭代测试集/语料/v2.0.11、不覆盖原 C1 目录与 7 个原文件）。**两项语义修正**：(1) **运行一致性表述**：原 C1 记录以「运行一致」概括两次独立完整运行的表述不成立——更正为：`NO_PROMOTION` 结论与 cd recall@5 失败方向在两次独立运行间稳定，但 raw ranking（跨运行 per-case 差异 baseline 34/candidate 90；运行内 build2 raw 差异 77/225）、逐案例指标（metric 差异 1/20 case）与候选整体聚合指标（运行内 build2 相对主构建 max|Δ|=0.009524：recall@5 Δ+0.0095、mrr Δ−0.0017、ndcg@10 Δ−0.0030；跨运行聚合 max|Δ|=0.005215）存在已记录的 HNSW 非确定性差异；(2) **data_quality 与 promotion_eligibility 分离**：原 data-quality-report.json `passed=true`/`error_count=0` 但 30 条 checks 中追加了 4 条 `ok=false` 的 gate 条件（追加于 error_count 计算之后）——「全部通过」表述不成立；更正为 `data_quality`（核心完整性/唯一性/指标复算/引用完整性/谱系与 manifest 闭环，21 项全过，`passed` 由核心检查重算）与 `promotion_eligibility`（6 条预先锁定 gate、4 条未通过 → `NO_PROMOTION`）分离——失败 gate 不是 data-quality 失败，`passed` 不暗示 promotion 通过。**TDD**：新增 `tests/test_evaluate_v211_cross_document_ablation_audit_correction.py`（17 个）RED→GREEN（fail-closed 漂移零输出 / 精确识别 4 条未通过 gate / 核心 checks 无 false / 失败 gate 只出现在 promotion_eligibility / 禁止措辞自检 / manifest 自哈希+inputs/outputs 闭环 / 两次构建逐字节一致 / 纯 stdlib 无重型导入 / 真实数据核验）；更新 ablation 测试的 DQ/gate 分离断言。**实现**：新增 `scripts/evaluate_v211_cross_document_ablation_audit_correction.py`（纯 stdlib，不导入 src.*/chromadb/检索/LLM 链路；fail-closed：原 C1 manifest self-hash + 6 outputs 字节 SHA 任一漂移 → 零输出、退出码 2；gate 事实交叉核验：conditions 未通过集 == failures == 原 DQ 中 false `gate.*` 集）；修正未来 runner（`scripts/evaluate_v211_cross_document_ablation.py`）报告语义：gate 条件不再追加进 data-quality checks，`promotion_eligibility` 独立成段，`passed`/`error_count` 只反映核心检查。**产物 4 个**（manifest 自哈希 `99cc8547…` + 7 项输入（原 C1 manifest + 6 outputs）字节 SHA 闭环 + lineage：原 C1 self-hash `45f40c63…` 复算一致；manifest 无时间戳 → 两次构建逐字节一致）：correction-summary.json / corrected-data-quality-report.json / CORRECTION.md / manifest.json。**验证**：原 C1 7 文件字节不变（7 项复算零漂移）；冻结 revision/6-A/B0/B0.1 manifest 与 chunks 字节不变；43 项定向测试全绿；全量 pytest 全绿；py_compile / git diff --check；未 stage/commit/push。**边界声明**：v2.0.11 仍是只读 CANDIDATE（activation_blocked=true、human_reviewed=false）；最终决策仍为 **NO_PROMOTION**（失败条件不变：cd_recall@5_gain / overall_recall@5_no_drop / overall_ndcg10_mrr_no_drop / exceeds_recorded_noise）；默认产品检索策略未改变；未测项沿用 C1（answer quality / citation faithfulness / refusal accuracy）；`data-analytics:analyze-data-quality` 实际检查：zcode 运行环境不可用（本次会话技能列表、`~/.zcode/skills`、`~/.agents/skills`、插件目录均无）——实施等价确定性复算，不能声称所有环境均不可用。

- **v2.0.11 contract-error diagnostic + evaluation freeze（Phase 5-A，真实运行：诊断 `CONTRACT_ERROR_DIAGNOSTIC_COMPLETE`、冻结 `EVALUATION_BASELINE_FROZEN`）** — 新增 `scripts/corpus_v2_v211_contract_error_diagnostic.py` 与 TDD 测试（41 个）：对 4 条持续 contract error（en-052/mixed-030/mixed-033/zh-040）做一次诊断性、盲态、Pro-only 复核，随后冻结 v2.0.11 为工程评测候选基线。**目标集交叉推导**：Phase 4 pack `persistent-contract-errors.jsonl`（4 行）== targeted review issues error 行（4 条）== pack owner 模板 contract 行（4 条）== `ERROR_CASES`；任何新增/遗漏/重复 fail-closed。**fail-closed 预检**（复用 Phase 4 `dp.preflight` + 独立 pack manifest 核验：self-hash/gate `OWNER_DECISION_PACK_OK`/counts（22/18/4/template 22）/outputs(8)/inputs(18) SHA/target_set 与磁盘一致；pack owner 模板 22 行 `owner_decision`/`owner_reviewer`/`owner_notes` 仍为空字符串；candidate 136/149 strict（covered==passed）、targeted review 22=18+4、candidate/review/pack/triage 各 manifest self-hash + inputs/outputs SHA；draft 与 v2.0.10 逐字节一致；无 forbidden 产物；任一漂移 → DiagnosticError 零输出）。**诊断（盲态、Pro-only）**：`--probe-json` 先验证身份（真实返回 `deepseek-v4-pro` ok=true）；仅 `deepseek-v4-pro` / temperature=0.0 / max_tokens=8000 / thinking disabled / 最多 3 次同模型重试 / 无 fallback；payload 保持盲态（复用冻结引擎 `build_payload`/`scan_payload`，不含 case_id/历史 verdict/rationale/owner decision/分类/治理标签）；**不因旧 contract error 预设 confirmed**；绝不调用其余 18 条（stub 对未注册 payload 抛错断言）。**关键新增：保留每一次模型尝试的原始响应**——`raw-model-attempts.jsonl`（16 行）逐尝试记录：匿名 run id（确定性哈希前缀）、attempt 序号、实际模型身份、原始响应文本、原始响应 SHA、解析结果（invalid_json/schema_error/contract_conflict/transport_error/identity_mismatch/ok）、解析错误、decision、逐 AP supported、refusal assessment、本地契约判断与具体冲突原因（`local_contract_judgement`/`contract_conflict_reason`）。**真实运行结果（16 次 deepseek-v4-pro 调用）**：4 条全部 `contract_error`（每次 4 次尝试；轨迹 15 次 contract_conflict + 1 次 invalid_json——如实记录，含原始响应）；resolved 0 / contract_error 4 / transport_blocked 0 / identity_blocked 0；`issues` 4 行；`gate=CONTRACT_ERROR_DIAGNOSTIC_COMPLETE` 且明确**不是 review acceptance、不是人工批准、不解除 `TARGETED_REVIEW_BLOCKED`**；诊断只记录事实，不自动改 reject 为 confirmed。输出 8 个文件（raw-model-attempts / results / issues / summary / report / gate-report / data-quality-report（五维全 ok）/ manifest（self-hash + 19 inputs/8 outputs SHA））。**冻结**：`evaluation-freeze/` 恰 4 个文件——`deferred-owner-decisions.jsonl` 恰 18 行（来自 Phase 4 reject 集，`owner_decision="deferred"`，注明「无 candidate 数据动作；未来仅可进入 v2.1 治理流程」，**不改 Phase 4 原始空白 owner 模板**）、`FROZEN_EVALUATION_BASELINE.md`（明确不是 active / 不是人工批准 / 不是 v2.1；后续任何语料改进仅允许新建 v2.1 不回写 v2.0.11）、`freeze-summary.json`（18 deferred + 4 diagnostic 状态 `{contract_error: 4}` + 冻结理由与不变量）、`manifest.json`（self-hash + 24 inputs/4 outputs SHA，gate `EVALUATION_BASELINE_FROZEN`）。**验证**：冻结两次构建逐字节一致（diff -r 全等）；candidate（6cab6786…）/targeted review（220ed9c2…）/Phase 4 pack（ed2b8fcc…）/diagnostic 字节 SHA 前后完全不变；两 manifest self-hash + inputs/outputs SHA 闭环；五维数据质量全 ok；无 overlay/active/split/locked/v2.1 产物；未 stage/commit/push。`data-analytics:analyze-data-quality` skill 在本环境不可用（已实际尝试，可用技能列表无此技能），已实施等价确定性五维检查。

- **v2.0.11 owner decision pack（真实构建，`OWNER_DECISION_PACK_OK`，只读确定性、无 LLM/API）** — 新增 `scripts/corpus_v2_v211_targeted_remaining22_decision_pack.py` 与 TDD 测试（42 个）：为 v2.0.11 targeted review 的 22 条非 confirmed 项（18 reject + 4 持续契约 error）生成 owner 决策包，输出 `targeted-re-review/owner-decision-pack/` 恰 8 个文件（`persistent-contract-errors.jsonl` 4 行 / `stable-reject-root-cause-triage.jsonl` 18 行 / `owner-decision-template.jsonl` 22 行（`owner_decision`/`owner_reviewer`/`owner_notes` 全为空字符串）/ `decision-pack-summary.json` / `decision-pack-report.md` / `OWNER_DECISION_GUIDE.md` / `data-quality-report.json` / `manifest.json`）。**严格边界**：不调用模型/API/网络、无 `--probe-json`；不修改 candidate draft/evidence/chunks/policy/review；不生成 overlay/active/split/locked config/v2.1；不 stage/commit/push。**fail-closed 预检**（任一漂移 → DecisionPackError，零输出）：candidate 与 targeted-review 两份 manifest 的 self-hash（`json.dumps(body_without_sha, ensure_ascii=False, indent=1, sort_keys=True) + "\n"`）、inputs、outputs SHA 与磁盘一致；candidate 136 cases/149 strict evidence（covered==passed）且 metadata 保持 CANDIDATE/activation_blocked=true/human_reviewed=false/overlay_generated=false；targeted results/issues/manifest 严格守恒 22 = 18 reject + 4 error（case_id 唯一、无 en-048、reject 的 response_sha256 与 results 对应、4 条 error 的原始 response/payload SHA 缺失为既有契约路径的预期事实，不伪造——results 中为 null、issues 中缺失，任何非空值 fail-closed）；candidate draft 与 v2.0.10 draft 逐字节一致、evidence 仅比 v2.0.10 多授权 en-048 行（148→149）；禁止产物扫描允许 `REVIEW_AND_SPLIT_REBUILD_REQUIRED.md`（说明文件，非 split 产物）；所有新写文件 LF。**机械分流**（18 条 reject 基于当前 v2.0.11 evidence raw span 与同 source chunk 原文逐答案点复算，共 27 个答案点）：case 级 exact 7 / partial 7 / translation 4 / same_source 0 / no_direct 0（答案点级 exact 7 / partial 12 / translation 8）；口径：`exact` 规范化后直接包含、`partial` 同语言 LCS ≥ max(3, 0.10×较短文本)、`same_source` 同 source 未覆盖机械候选（给出 source/chunk/Unicode [start,end)/raw span/唯一性与不重叠证明）、`translation` 仅识别跨语言关联（共享 token，不得伪装成 direct evidence）、`no_direct` 无机械可证直接支撑；v2.0.10 triage 仅作 lineage/provenance（`lineage_only=true`），不作为结论事实。**4 条契约 error**（en-052/mixed-030/mixed-033/zh-040）：`persistent_model_output_contract_inconsistency` + 原始错误文本 + `expected_decision_from_local_contract="confirmed"`（明确声明这是引擎契约推断，**不是对原 review 的改写**，`rewritten=false`）+ 原始模型响应不可用的事实（不假称能审阅）+ 可选 owner 路线（人工审计现有记录/授权新的契约聚焦盲态复核/继续保持 blocked）。**验证**：真实构建两次逐字节一致（diff -r 全等）；manifest self-hash/outputs(8)/inputs(18) SHA 闭环；五维数据质量（完整性/唯一性/引用完整性/连续性/一致性）全部 ok，`downstream_risk` 声明仅供 owner 决策、异常保持 gate blocked；candidate 与 targeted-review manifest 字节 SHA 构建前后不变（6cab6786…/220ed9c2…）；无激活性产物。`data-analytics:analyze-data-quality` skill 在本环境不可用（已实际尝试，可用技能列表无此技能），已实施等价确定性五维检查。

- **v2.0.11 targeted blind Pro-only re-review of the remaining 22 issues（真实运行，`TARGETED_REVIEW_BLOCKED`）** — 新增 `scripts/corpus_v2_v211_targeted_remaining22_review.py` 与 TDD 测试（27 个）：v2.0.11 candidate 构建成功后，对其余 22 条非 confirmed 项做一次新的、定向、盲态 Pro-only 复核。**目标集从 v2.0.10 triage 的 owner template / triage rows 推导并断言**：恰 22 条（18 reject + 4 error）、不含 en-048、恰含 en-052/mixed-030/mixed-033/zh-040、无重复无遗漏（template 23 == reject 19 ∪ error 4 且互斥）。**盲态规则**：payload 仅含 query / previous_turns（剥离身份与引用）/ should_refuse / answer_points / evidence（raw span + snippet + 来源正文）/ 统一支持判定规范（复用冻结引擎 `corpus_v2_v209_fresh_blind_automated_review` 的 `build_payload`/`scan_payload`/`validate_response`/`review_case`/`probe`，递归键白名单 + 高信号泄露词扫描）；**不把旧 review decision、rationale、issue 分类、owner 决策、case_id 或内部治理标签放入模型 payload**；4 个旧 contract error 按相同盲态规则复核，**不预设为 confirmed**。模型约束：仅 `model="deepseek-v4-pro"` / temperature=0.0 / max_tokens=8000 / `extra_body={"thinking":{"type":"disabled"}}` / 最多 3 次同模型重试，无 fallback、无 Flash；先运行不读取 case 内容的 `--probe-json` 身份探针（实际返回 `deepseek-v4-pro`，ok=true）。预检全部 fail-closed（任一漂移 → ReviewError，零输出）：v2.0.11 candidate manifest 自哈希/gate `EN048_SAME_SOURCE_REPAIR_CANDIDATE_OK`/metadata 六标志/counts（136/149/same_source_added 1）/outputs SHA/14 个 inputs SHA 与磁盘一致、draft 136 行唯一、evidence 149 行 strict covered==passed、105 answerable 全有 evidence 且 31 refusal 无、连续性无 dangling；v2.0.10 candidate/review/triage 三 manifest 自哈希 + inputs/outputs SHA 逐项核验；chunks/chunk-manifest 一致；candidate 树无 overlay/激活性产物。**真实运行结果（22 次 deepseek-v4-pro 调用）**：`gate=TARGETED_REVIEW_BLOCKED`——confirmed 0 / reject 18 / needs_followup 0 / errors 4。18 条 reject 与 v2.0.10 复审的 reject 判定一致（盲态下判定稳定：en-040/041/045/047/051、mixed-022/028/029/034、multi-012/027、zh-023/036/046/050/052/054/058）；4 条旧 contract error（en-052/mixed-030/mixed-033/zh-040）在相同盲态契约下依旧 4 次同模型重试后触发本地一致性规则 `reject/needs_followup without any disagreement`（模型 rationale 自述应判 confirmed 却输出 reject/needs_followup）→ 契约错误（schema_errors=4、identity_errors=0、transport_errors=0）。**不自动采纳模型结论**：输出只位于 v2.0.11 的 `targeted-re-review/`（6 个文件：targeted-review-results.jsonl 全 22 行含 payload/response SHA、targeted-review-issues.jsonl 恰 22 行非 confirmed、targeted-review-summary.json、targeted-review-report.md、targeted-review-gate-report.md、manifest.json 自哈希 + 17 个 inputs/6 个 outputs SHA，gate `TARGETED_REVIEW_BLOCKED`）；**未改写 full review、未生成 overlay、未修改 candidate metadata、未生成 active/split/locked/v2.1 产物**；v2.0.11 candidate 的 9 个输出文件 SHA 运行前后不变。五维数据质量全部 ok（`data-analytics:analyze-data-quality` 实际不可用已如实记录，执行等价确定性五维检查）。stub 注入两次构建逐字节一致；27 个定向测试全绿。**边界声明**：本次是用户授权的机器定向复审，不代表人工批准、不解除 `AUTOMATED_REVIEW_GATE_BLOCKED`、不改变 v2.0.11 的 activation-blocked 状态；22 条非 confirmed 仍需新的 owner 决策。未 stage/commit/push。

- **v2.0.11 owner-authorized en-048 same-source repair candidate（确定性、离线）——真实构建成功（136 cases / 149 evidence）** — 新增 `scripts/corpus_v2_v211_owner_authorized_en048_repair.py` 与 TDD 测试（31 个）：owner 授权范围内唯一数据动作——为 `en-048` 追加一条同 source、可严格重建的 raw-codepoint evidence，**候选直接读取自 v2.0.10 coherence-reject-triage 的 `reject-root-cause-triage.jsonl`（已验证唯一 same_source 候选），不得重新搜索或另选**。fail-closed 门禁（任一漂移 → RepairError，零输出、不创建输出目录）：v2.0.10 candidate manifest 自哈希/gate `COHERENCE_REMEDIATION_CANDIDATE_OK`/metadata 六标志/counts（136/148/retired 1/retired_evidence 1/duplicate_removed 1/same_source_added 6）/outputs SHA/13 个 inputs SHA（v2.0.9 文件链）全部与磁盘一致；v2.0.10 review manifest（gate `AUTOMATED_REVIEW_GATE_BLOCKED`、counts 113/19/0/4、inputs/outputs SHA）与 triage manifest（gate `COHERENCE_REJECT_TRIAGE_OK`、counts 136/113/19/0/4/23、inputs/outputs SHA）逐项核验；en-048 triage 行必须 `suggested_action=repair_candidate`、`case_classification=same_source`、same_source_candidates 恰 1 条且 AP 级 same_source 关系与 case 级候选一致；候选逐项验证：source/chunk/Unicode `[769,778)`/raw span `functions`/unique=1（chunk 内唯一出现）与 chunk 原文严格一致、snippet/snippet_sha256/chunk_text_sha256 正确、不与 en-048 现有 3 条 evidence span（chunk_16 [2,99)、chunk_8 [179,215)、chunk_14 [531,537)）重叠、anchor 不重复、候选 source 在 draft 声明的 relevant_source_ids 内；`data/v2-corpus/chunks/chunks.jsonl` 与 chunk-manifest 一致性。构建后不变量：136 cases / 149 evidence 全过 strict validator（covered==passed==149）、evidence 行级字节全唯一、anchor 全唯一、draft-after 与 v2.0.10 draft-after **逐字节一致**、evidence-after 前 148 行与 v2.0.10 逐字节一致且仅末尾追加 1 行（en-048 / 761b22915b5e_chunk_14 / `functions`）、105 answerable 全有 evidence 且 31 refusal 无 evidence、draft 引用无 dangling、输入 SHA 构建前后不变。输出恰 9 个文件：draft-before/after、evidence-before/after、added-same-source-evidence.jsonl（恰 1 行）、field-level-diff.jsonl（恰 1 行，含 `candidate_origin=v2.0.10-coherence-reject-triage` 与 via/unique/overlaps_existing provenance）、data-quality-report.json（五维全 true）、REVIEW_AND_SPLIT_REBUILD_REQUIRED.md、manifest.json（自哈希 + 14 个 inputs/8 个 outputs SHA，gate `EN048_SAME_SOURCE_REPAIR_CANDIDATE_OK`）。metadata 固定：`revision_status=CANDIDATE`、`activation_blocked=true`、`human_reviewed=false`、`overlay_generated=false`、`split_reseal_required=true`、`v2_1_entered=false`、`actor=OWNER_AUTHORIZED_V2_0_11_EN048_SAME_SOURCE_REPAIR`。真实验证：两次构建逐字节一致（9/9）、manifest 自哈希与 outputs SHA 与磁盘一致、行级 diff 恰 1 条新增、无 overlay/active/split/locked/v2.1/retired/dedup 产物。修复一处测试基建问题：`_tamper_output`/`_tamper_triage` 忽略 mutation lambda 返回值导致篡改从未生效（Phase 2 靠「重写字节变化 → review inputs SHA 漂移」碰巧捕获，本次改为取用返回值），并修正脚本 review/triage inputs 映射指向 `candidate_dir` 副本。**边界声明**：v2.0.11 仍是 CANDIDATE / activation-blocked；新增 evidence 通过 strict 校验**不等于** review 通过或激活准入；v2.0.10 全部文件不变；未 stage/commit/push。

- **v2.0.10 automated-review coherence and reject root-cause triage（只读、确定性、无 LLM）** — 新增 `scripts/corpus_v2_v210_coherence_reject_triage.py` 与 TDD 测试（41 个）：对 v2.0.10 机器复审的全部 23 条非 confirmed issue 做本地根因分流。**不修改 candidate draft/evidence/chunks/review/manifest，不调用 LLM/API、不联网、不重跑 deepseek-v4-pro，不读取或采用旧 revision 的 review decision/rationale/issues 作为事实（v2.0.9 脚本仅作实现结构参考），不生成 overlay/active/after/split/locked/v2.1，不 stage/commit/push**。预检全部 fail-closed（任一漂移 → TriageError，零输出）：candidate = 136 cases / 148 strict evidence（covered==passed==148，evidence 行字节级全唯一）；review canonical 守恒 113+19+0+4=136；issues 恰 23 行（19 reject + 4 error）且 case_id 无重复、无遗漏、error case 集合恰为 en-052/mixed-030/mixed-033/zh-040；无 overlay；candidate/review manifest 自哈希与 inputs/outputs SHA 与磁盘一致（chunks/chunk-manifest/current-draft/candidate draft/evidence/manifest 闭环）；strict validator 逐行通过（raw span 可重建）；引用完整性/连续性复算。**分流一（4 条 model-output coherence errors：en-052/mixed-030/mixed-033/zh-040）**：issue detail 明确 `reject/needs_followup without any disagreement`（本地契约校验无任何分歧 ⇒ 统一 decision 契约要求 confirmed；模型 4 次同模型重试输出自相矛盾）→ 一律归类 `model_output_contract_inconsistency`，expected decision 契约推导为 confirmed，**不得改写原 review decision、不得重跑模型、不得写回 review**，只生成诊断与后续可选 recheck 规格。**分流二（19 条 substantive reject）**：对每个 reject 的每个答案点，只基于 candidate 当前 raw evidence span 与同 source chunk 原文做确定性分类（规范化后直接包含 → `exact`；同语言最长公共连续子串 ≥ max(3, 0.10×较短文本长度) → `partial`；同 source 原文/剥代码围栏/（跨语言）最长未覆盖 ASCII token 候选——候选给出 source/chunk/Unicode `[start,end)`/raw span/唯一性且不得重叠现有 evidence span（首个命中重叠时继续扫描后续出现位置，防漏报）→ `same_source`；跨语言可识别关联（有 token 或共享数字）→ `translation`；否则 → `no_direct`；token 片段/跨 source 文本/模型解释/语义猜测一律不标为 direct evidence）。case 级分类 = 证据最弱者（severity：exact < partial < same_source < translation < no_direct）；只读建议动作：`targeted_recheck_required` / `repair_candidate` / `remove_answer_point` / `retire_case` / `keep_unresolved`，不自动应用。**真实结果**：4 error 全 `model_output_contract_inconsistency`（expected=confirmed，未改写）；19 reject 分类 = exact 7（mixed-022/028/029、multi-012、zh-023/036/054——证据逐字支撑、模型语义分歧）/ partial 11（en-040/041/045/047/051、mixed-034、multi-027、zh-046/050/052/058）/ same_source 1（en-048——PG 源 chunk 761b22915b5e_chunk_14 [769:778) token 候选 "functions"，via=token、unique=1、不重叠现有 span）；建议动作 = targeted_recheck_required 18 / repair_candidate 1。输出 8 个文件到 `automated-review/coherence-reject-triage/`：review-coherence-errors.jsonl（恰 4 行）、reject-root-cause-triage.jsonl（恰 19 行，逐答案点明细 + 候选 provenance）、owner-decision-template.jsonl（恰 23 行，owner_decision/owner_reviewer/owner_notes 均为空）、COHERENCE_AND_REMEDIATION_GUIDE.md、triage-summary.json、triage-report.md、data-quality-report.json（五维：完整性/唯一性/引用完整性/连续性/一致性）、manifest.json（自哈希 + inputs/outputs SHA，gate `COHERENCE_REJECT_TRIAGE_OK`）。`data-analytics:analyze-data-quality` 经机械探测（常见 skill 根目录扫描）实际不可用，已如实记录并执行等价确定性五维检查。两次构建逐字节一致、manifest 自校验通过、输入 SHA 任务前后不变。**边界声明**：这是用户授权的机器复审根因分流，不是人工审核、不是人工批准、不是 active 版本、不是 v2.1 准入；不解除 `AUTOMATED_REVIEW_GATE_BLOCKED`，不改变 v2.0.10 activation-blocked 状态。未 stage/commit/push。

- **v2.0.10 owner-authorized coherence remediation and fresh full blind review** — added a deterministic candidate builder, a Pro-only fresh-review wrapper, and TDD coverage. Applied only the explicitly authorized actions: six pre-verified same-source evidence additions (`en-047`, `en-048`, `multi-020`, `multi-028`, `zh-046`, `zh-052`), retirement of dependency-safe `multi-019`, and removal of one byte-identical `mixed-033` evidence row. The new candidate is `CANDIDATE` / activation-blocked with 136 cases and 148 strict evidence rows; its manifest, raw-span checks, input/output SHA closure, deterministic rebuild, and five data-quality dimensions (completeness, uniqueness, referential integrity, continuity, consistency) pass. The data-quality workflow was available and applied. A new complete blind `deepseek-v4-pro` review ran after a successful identity probe: 113 confirmed, 19 reject, 0 needs_followup, and 4 model-output contract errors (`en-052`, `mixed-030`, `mixed-033`, `zh-040`). Therefore `AUTOMATED_REVIEW_GATE_BLOCKED`; only issues, gate report, and manifest were written, with no overlay or active/split/v2.1 output. Remaining non-confirmed results were not auto-remediated; they require a new owner decision. No stage, commit, or push.

- **v2.0.9 automated-review coherence and reject root-cause triage（只读、确定性、无 LLM）** — 新增 `scripts/corpus_v2_v209_coherence_reject_triage.py` 与 TDD 测试（41 个）：对 v2.0.9 机器复审的 26 条非 confirmed issue 做本地根因分流。**不修改 candidate draft/evidence/chunks/review，不调用 LLM/API、不联网，不读取 split/dev/holdout、locked config、历史评测或 v2.0.8 之前的 review/triage/decision pack，不生成 overlay/active/after/split/v2.1，不 stage/commit/push**。预检全部 fail-closed（任一漂移 → TriageError，零输出）：candidate = 137 cases / 144 strict evidence（covered==passed==144）；review canonical 守恒 111+22+0+4=137；issues 恰 26 行（22 reject + 4 error）且 case_id 无重复、无遗漏；无 overlay；candidate/review manifest 自哈希与输入输出 SHA 均一致（chunks/chunk-manifest/current-draft/draft-after/evidence-after 闭环）；证据行级唯一性放行 mixed-033 已知字节级重复；引用完整性/连续性复算。**分流一（4 条 model-output coherence errors：en-052/mixed-030/mixed-033/multi-011）**：issue detail 明确 `reject/needs_followup without any disagreement`（本地契约校验无任何分歧 ⇒ 统一 decision 契约要求 confirmed；模型 4 次同模型重试输出自相矛盾）→ 一律归类 `model_output_contract_inconsistency`，expected decision 契约推导为 confirmed，**不得改写为 confirmed/reject、不得重跑模型、不得写回 review**，只生成诊断与后续可选 recheck 规格。**分流二（22 条 substantive reject）**：对每个 reject 的每个答案点，只基于 candidate 当前 raw evidence 与同 source chunk 原文做确定性分类（规范化 containment → exact；同语言最长公共连续子串 ≥ max(3, 0.10×较短文本长度) → partial；同 source 原文/剥代码围栏/（跨语言）最长未覆盖 ASCII token 候选（给出 chunk、Unicode [start,end)、raw span、唯一性，候选不得重叠现有 evidence span）→ same_source；跨语言有共享 → translation；否则 → no_direct；token 片段/跨 source 文本/模型解释/语义猜测一律不标为 direct evidence）。case 级分类 = 证据最弱者（severity：exact < partial < same_source < translation < no_direct）；只读建议动作：`targeted_recheck_required` / `repair_candidate` / `remove_answer_point` / `retire_case` / `keep_unresolved`。**真实结果**：4 error 全 `model_output_contract_inconsistency`（expected=confirmed，未改写）；22 reject 分类 = exact 7（mixed-022/028/029、multi-012、zh-023/036/054——证据逐字支撑、模型语义分歧）/ partial 8（en-040/041/045/051、mixed-034、multi-027、zh-050、zh-058）/ same_source 6（en-047/048、multi-020/028、zh-046/052——含 createdb/ROLLBACK/Transactions/window 等精确候选）/ no_direct 1（multi-019，建议 retire_case）；建议动作 = targeted_recheck_required 15 / repair_candidate 6 / retire_case 1。**mixed-033 重复 evidence 检查**：两条行字节级完全一致（同 chunk/同 raw range/同 raw span/同 snippet SHA/同 source），均支撑同一保留答案点；删除任意一条语义安全（144→143）但必须 owner 明确授权并同步更新 manifest 后重跑 strict 校验——只写建议，未修改数据。输出 8 个文件到 `automated-review/coherence-reject-triage/`（review-coherence-errors.jsonl、reject-root-cause-triage.jsonl、mixed-033-duplicate-evidence-check.json、owner-decision-template.jsonl（26 行，owner_decision/owner_reviewer/owner_notes 均为空）、COHERENCE_AND_REMEDIATION_GUIDE.md、triage-summary.json、triage-report.md、manifest.json（自哈希 + inputs/outputs SHA，gate `COHERENCE_REJECT_TRIAGE_OK`））。修复过程（TDD RED→GREEN）：Windows `Path.write_text` 默认 \n→\r\n 导致 outputs SHA 与磁盘不一致（改为 newline="\n"）；输入 SHA 校验先于 chunks 解析；evidence 唯一性按行级判定（放行 mixed-033 已知重复）；LCS 阈值 0.15→0.10 修正 en-045 "escape/escaping" 强改写边界（no_direct→partial，避免误建议 remove_answer_point）。两次构建逐字节一致、manifest 自校验通过、candidate/输入 SHA 任务前后不变。`data-analytics:analyze-data-quality` 实际不可用（`Skill not found`，已尝试），执行等价确定性五维检查（完整性/唯一性/引用完整性/连续性/一致性）。**边界声明**：这是用户授权的机器复审根因分流，不是人工审核、不是人工批准、不是 active 版本、不是 v2.1 准入；Gate 保持 BLOCKED，v2.0.9 保持 CANDIDATE / activation_blocked / split_reseal_required。未 stage/commit/push。

- **v2.0.9 fresh full blind automated review（全新 137-case 盲态机器复审，Pro-only）** — 新增 `scripts/corpus_v2_v209_fresh_blind_automated_review.py` 与 TDD 测试（69 个）：对 v2.0.9 candidate 全部 137 个 case 进行一次新的、完整、盲态机器复审，**不得复用 v2.0.7/v2.0.8 的任何 review decision/rationale/issues/selection/统计**。输入边界（仅）：v2.0.9 candidate（draft-after/evidence-after/manifest）、当前 chunks 与 chunk manifest、translation-equivalence policy/ledger（仅统一支持语义，不使用逐条 verdict）、raw-codepoint-v1 strict validator；内容读取有运行时白名单（`_read_text` 强制），v2.0.8 文件（含 decision packs）仅作 manifest 输入 SHA 的字节级哈希校验。预检全部 fail-closed（任一漂移 → ReviewError，零输出、零 overlay、不调用模型）：case_count=137、active raw evidence=144、strict covered==passed==144、legacy/unresolved/invalid/uncovered=0、106 answerable 全有 evidence 且 31 refusal 全无 evidence、manifest 自哈希 + 输出 SHA + 14 个输入 SHA 与磁盘一致、metadata 仍为 CANDIDATE/activation_blocked/human_reviewed=false/无 overlay、case_id/query/answer points 唯一、draft 引用无 dangling 且无指向已退役 case、chunk manifest 与 chunks 一致。**已知事实如实记录**：mixed-033 存在两条字节级完全相同的 evidence 行（candidate 自身 data-quality-report 已记录 `evidence_keys_unique=false`，继承自 v2.0.8）——作为已知事实记录不阻断（冲突性重复才 fail-closed），复审按原样纳入并如实上报。模型约束：仅 `model="deepseek-v4-pro"` / temperature=0.0 / max_tokens=8000 / `extra_body={"thinking":{"type":"disabled"}}` / 最多 3 次同模型重试，无 fallback、无 Flash、无 gpt-5.6-sol；先运行不读取任何 case 的 `--probe-json` 探针（验证实际返回模型身份 == deepseek-v4-pro，失败整体停止）。盲态 payload 仅含 query / previous_turns（剥离 case_id/chain_id/follow_up_to 及任何内部引用，白名单保留对话内容）/ should_refuse / answer_points / evidence（raw span + snippet + 来源正文）/ 对所有 case 一律相同的支持判定规范（翻译可支持仅当语义等价且无新增主张，不得因翻译政策标签默认支持）；递归键扫描 + 高信号泄露词扫描（结构化字段全词扫描，语料字段仅 case-id 引用扫描；泄露词清单已在真实语料核验零命中）。模型输出本地严格验证：decision ∈ {confirmed/reject/needs_followup}、answer_point_assessments 索引恰覆盖答案点、refusal 语义一致性（confirmed ⇒ 全 supported 且 refusal_required 与 payload 一致；非 confirmed ⇒ 必有分歧），不自动补字段/猜坐标/改答案点或 evidence。输出到 `v2.0.9-.../automated-review/`：全 confirmed（137/137）→ 9 个文件（automated-review-pack.jsonl / automated-review-evidence.jsonl / automated-review.jsonl / raw-model-responses.jsonl / automated-review-summary.json / automated-review-report.md / automated-review-gate-report.md / manifest.json / automated-overlay.json，状态 `LLM_ASSISTED_OWNER_AUTHORIZED_V2_0_9`，明确非人工审核/非人工批准/非 active/非 v2.1 准入）；任一 reject/needs_followup/错误 → gate=`AUTOMATED_REVIEW_GATE_BLOCKED`，只写 issues（+ gate report + manifest），绝不生成 overlay，并清理残留成功产物。探针结果：实际返回模型身份 == `deepseek-v4-pro`（ok=true）。**真实构建结果：`gate=AUTOMATED_REVIEW_GATE_BLOCKED`**——111 confirmed / 22 reject / 0 needs_followup / 4 errors（en-052、mixed-030、mixed-033、multi-011：模型输出自相矛盾，rationale 自述应判 confirmed 却输出 reject，4 次同模型重试后由局部一致性规则 fail-closed 记为 error）；按契约**只写 issues（26 条）+ gate report + manifest，绝不生成 overlay**（已核验无 automated-overlay.json、declarations.overlay_generated=false）。22 个 reject 均为 schema 合法、有理由的模型判定（例：multi-012 证据含带星号解包特例、en-040 证据未含"回滚"术语、mixed-029 证据仅含断言未及查询比较）。修复过程（TDD）：真实探针成功但首轮全量构建 137/137 全部 error——根因=payload 支持判定规范未含输出格式契约（模型自创 schema 且用 ```json 围栏包裹）+ refusal 子句被模型误外推到无答案点 case；修复=统一规范追加输出契约与 decision 语义定义、refusal 子句明确仅适用于 answerable case、确定性剥离单个 ```json 围栏，冒烟 16+ 真实 cases（各 id 族）后全量重建。不改变 candidate draft/evidence/chunks（SHA 逐字节未变），不生成 active metadata/split/locked config/v2.1。`data-analytics:analyze-data-quality` 实际不可用（`Skill not found`，已尝试），改用等价确定性五维检查（完整性/唯一性/引用完整性/连续性/一致性）。注入 stub 两次构建逐字节一致。未 stage/commit/push。

- **v2.0.9 owner-authorized final dependency-closed retirement candidate（确定性、离线）——真实构建成功（143 → 137）** — 新增 `scripts/corpus_v2_v209_final_dependency_closed_retirement.py` 与 TDD 测试（48 个）：所有者授权的唯一数据动作——退役最小无悬挂依赖闭包 `multi-030/multi-031/multi-032/multi-033/multi-034`（`retire_minimal_dependency_closed_cohort`）与安全隔离 case `mixed-027`（`retire_single_case_safely`），共 6 case / 7 evidence（151 → 144）。不修改 v2.0.8 或更早 revision、不调用 LLM/API、不联网、不读取 split/dev/holdout/锁配置/历史评测/早于 v2.0.7 的 review；不生成 overlay / active metadata / split / locked config / v2.1；不 stage/commit/push。fail-closed 门禁（任一漂移 → RetirementError，零输出）：v2.0.8 == 143 cases / 151 active raw evidence / strict 151/151（covered==passed）/ legacy=unresolved=0、candidate manifest 自哈希 + outputs SHA 与磁盘一致；deferred ledger 恰 1 条 multi-030（固定原因 + dependent_cases 精确）；两个 decision pack（final-blockers `FINAL_BLOCKERS_DECISION_PACK_OK` / chain-closure `CHAIN_CLOSURE_DECISION_PACK_OK`）自哈希一致且记录的 11 个 input SHA 与当前磁盘一致；chain-closure pack 中 `retire_minimal_dependency_closed_cohort` meets_criteria=true、scenario executable=0 悬挂引用、`retire_only_multi_030` 不可执行（4 条悬挂引用）；mixed-027.retire_single_case_safely=true 且 impact executable；**本脚本在**当前 draft** 上重新复算最小无悬挂闭包（不动点）必须恰等于授权 cohort**（多/少/变均为漂移 → 整体停止；覆盖新增 follow-up/chain/previous_turns/doc-target 引用、解除 multi-031.follow_up_to、mixed-027 入边等全部 fail-closed 路径）；6 个退役 case 在 v2.0.8 before→after 逐字节不变。退役后不变量（全部 fail-closed 验证）：无 dangling case 引用、无残留 chain member（chain multi-028 与 multi-030 整链退役、上游 multi-028 自身 chain_id=multi-025 不悬空）、无 orphan previous turn、无 doc-target 悬空；strict 144/144 covered==passed、legacy/unresolved/invalid/uncovered=0、106 个保留 answerable case 全有合法 strict evidence；非目标 draft/evidence 行**逐字节不变**（保留原行序列化风格）。输出恰 9 个文件到 `v2.0.9-owner-authorized-final-dependency-closed-retirement/`：draft-after.jsonl、evidence-after.jsonl、retired-cases.jsonl（保留原始行 + 固定理由 `owner_authorized_final_dependency_closed_retirement` + cohort + 依赖闭包证明 + evidence 数 + 授权标识）、retired-evidence.jsonl（7 行原始行保留）、retirement-dependency-ledger.json（闭包证明 / chain impact / mixed-027 隔离事实 / 计数 / 验证）、field-level-diff.jsonl（6 行逐字段）、data-quality-report.json（等价确定性五维检查）、REVIEW_AND_SPLIT_REBUILD_REQUIRED.md、manifest.json（自哈希 + 14 个输入 SHA 闭环 + gate `FINAL_DEPENDENCY_CLOSED_RETIREMENT_OK`）。metadata 固定：`revision_status=CANDIDATE`、`activation_blocked=true`、`human_reviewed=false`、`overlay_generated=false`、`split_reseal_required=true`、`v2_1_entered=false`、`actor=OWNER_AUTHORIZED_FINAL_DEPENDENCY_CLOSED_RETIREMENT`；严格验证通过**不构成**审阅通过或 active 准入，激活前仅能进入一次全新的 137-case 盲态复审，不得复用 v2.0.7/v2.0.8 的 review 结果。两次构建逐字节一致、manifest 自哈希与磁盘 SHA 一致（dfa17911…）、v2.0.8 candidate 全部既有文件 SHA 逐字节未变、无 overlay/active/split/locked/v2.1 产物。`data-analytics:analyze-data-quality` 实际不可用（`Skill not found`，已尝试），改用等价确定性五维检查。未 stage/commit/push。

- **v2.0.8 transitive chain-closure and mixed-027 retirement decision audit（只读、确定性、离线）——multi-030 传递链闭包与退役场景核算 + mixed-027 安全退役核验** — 新增 `scripts/corpus_v2_v208_chain_closure_decision_pack.py` 与 TDD 测试（50 个）：为 v2.0.8 剩余阻断项生成「链闭包决策包」，输出到 `v2.0.8-owner-authorized-semantic-quality-remediation/chain-closure-decision-pack/`（8 个文件：dependency-graph.json、multi-030-closure-options.json、mixed-027-retirement-check.json、chain-impact-map.json、owner-decision-template.jsonl——恰 2 行且仅 owner_decision/owner_reviewer/owner_notes 三个空字段、OWNER_DECISION_GUIDE.md、chain-closure-report.md、manifest.json 自哈希 + inputs/outputs SHA）。**不自动选择任何选项**、不修改任何 draft/evidence/chunks/candidate/review/manifest，不调用 LLM/API、不联网，不读取 split/dev/holdout/锁配置/历史评测/早于 v2.0.7 的审阅结论（本次亦不读取 targeted re-review，输入范围仅 candidate 目录 + 当前 v2 draft + chunks + chunk manifest + strict validator）。fail-closed 门禁（任一漂移 → ClosureAuditError，零输出）：v2.0.8 = 143 case / 151 active raw evidence / strict validator 151/151（covered==passed）、legacy=0、unresolved=0、manifest 自哈希、gate `REMEDIATION_CANDIDATE_OK`；已知事实**精确**：multi-031.follow_up_to=="multi-030" 且 multi-032/033/034.chain_id=="multi-030"（无其他引用）、multi-030.follow_up_to==None 且 chain_id=="multi-028"（multi-031 同链，chain multi-028 成员恰为 {multi-030,multi-031}、chain multi-030 成员恰为 {multi-032,multi-033,multi-034}）；mixed-027 完全隔离（follow_up/chain/doc_target/previous_turns 全空且无任何进出引用）；deferred ledger 恰 1 条、原因固定 `retirement_deferred_due_to_active_follow_up_chain_dependency`、dependent_cases 与图引用**完全一致**；multi-030~034 在 draft/evidence before→after 逐字节不变；图引用完整性（任何 case-id 字段引用必须指向存在的 case，否则 fail-closed）；环检测（多节点环 → fail-closed；自环仅允许 chain root 自标号 multi-011/multi-015 且 follow_up 为空时良性）；最小闭包 == {multi-030..034}（不预设范围，不动点计算）。**依赖图（143 nodes / 39 edges）**：边 = 全部 case-id 字段引用（follow_up_to 15、chain_id 24、doc_target 0、previous_turns 0——143 行 metadata 均无 previous_turns 字段，无 previous-turn 引用边），from=引用者、to=被引用者。**multi-030 传递闭包**：下游（引用者方向）= {multi-031（follow_up_to）、multi-032/033/034（chain_id），无纯传递下游}；上游（被引用方向，9 个）= {multi-028（直接，chain_id）→ multi-027/025 → multi-024/022 → multi-020 → multi-018 → multi-016 → multi-015}；follow_up 父节点 = 无；同链成员 = {multi-031}。**退役场景逐一核算（不预设 cohort）**：`retire_only_multi_030` **不可执行**（4 条悬挂引用：multi-031.follow_up_to 与 multi-032/033/034.chain_id 指向已退役 case；142 case / 150 evidence；chain multi-028 部分缺员）；`retire_multi030_to_multi034_group` **可执行**（0 悬挂引用；5 case / 5 evidence / 5 answer points；143→138、151→146；上游 chain multi-028 失去**全部**成员 multi-030/031（线程清空，case multi-028 本身属 chain multi-025 不受影响）、chain multi-030 整链退役）；`retire_minimal_dependency_closed_cohort` **可执行**（最小无悬挂闭包经不动点证明恰 == 5 组——multi-031.follow_up_to 与 multi-032/033/034.chain_id 强制其入组，multi-028 不引用组内任何 case 无需入组）。**mixed-027 安全退役核验**：依赖事实全空（无 follow-up/chain/previous_turn/doc_target/其他 case 引用，非任何 chain 成员）→ `retire_single_case_safely=true`（1 case / 2 evidence（8b191b241b93_chunk_1、c9fd20815ea8_chunk_2）/ 2 answer points；143→142、151→149，退役不造成任何链断裂）；AP0『术语表：原子化操作不可再分』与 AP1『SQLite 语法页仅列出 begin-stmt，未展开事务原子性说明』本地 strict 重验（复用 `_verify_ap`，min_span=8、覆盖≥0.75、同 source，**不放松任何规则**）：均无完整、唯一、连续、同 source 直接支持（AP0 最佳行 c9fd20815ea8_chunk_2 strict 覆盖 0.0、最长连续段『原子化操作』5 字符覆盖 0.3846 < 0.75、仅 token 片段；AP1 最佳行 8b191b241b93_chunk_1 strict 覆盖 0.2857、仅『begin-stmt』token 唯一命中但非完整 AP、full_ap_hits=0）。报告明确列出未来可授权选项（保持 multi-030 deferred / retire 经证明的最小闭包 / 仅在安全时 retire mixed-027 / 保持 mixed-027 deferred）但**不自动采纳**；任何“retire”选项均给出 retirement cohort、逐 case 理由、删除 evidence 数、链完整性验证结果与 case 数精确影响（143→138 或 143→142）。实现要点：`_build_dependency_graph`（引用完整性 + DFS 环检测 + chain 成员表 + previous_turns 事实）、`_reachability`（双向 BFS，direct/transitive 按 relation 非空分类）、`_minimal_closed_cohort`（不动点）、`_retirement_scenario`（悬挂引用/断链/缺失 chain member/orphan previous turn/doc-target 不一致 + 精确计数）；TDD 覆盖传递依赖、环检测、父/子/同链关系、单 case 退役安全性、悬挂引用 fail-closed、闭包随新引用者增长（合成 fixture）、输入 SHA 不变、两次构建逐字节一致、manifest 自校验、禁止 after/overlay/active/split/locked/v2.1 产物。修复一处测试基建问题：v2.0.8 jsonl 文件混用两种序列化（复制行 default separators / 新写行 compact+sorted），漂移测试改为按原行格式重写（`_dump_like`）保证未篡改行逐字节不变，避免 byte-identical 门禁误报；链上篡改若构成环先由环检测门禁拦截（byte-identical 门禁移至图构建之后，仍独立 fail-closed）。manifest 声明：llm_called=false、network_used=false、overlay_generated=false、split_created=false、v2_1_entered=false、recommendation_made=false、model_output_used_as_fact=false、data_modified=none、historical_verdicts_read=false。`data-analytics:analyze-data-quality` 实际不可用（`Skill not found`，已尝试），改用等价确定性五维检查（完整性/唯一性/引用完整性/连续性/一致性，并入 chain-closure-report.md）。真实构建成功：manifest 自哈希与磁盘 SHA 一致、9 个输入 SHA 闭环、两次 CLI 构建逐字节一致、50 个定向测试全绿。未 stage/commit/push。

- **v2.0.8 final blockers owner decision pack（只读、确定性）——两个阻断项（multi-030 / mixed-027）的决策选项与本地逐字证据** — 新增 `scripts/corpus_v2_v208_final_blockers_decision_pack.py` 与 TDD 测试（27 个）：为 v2.0.8 剩余两个阻断项生成面向所有者的决策选项包，**不自动选择任何选项**，不修改任何 draft/evidence/chunks/review/candidate，不调用 LLM/API、不联网、不读取 split/dev/holdout/锁配置/历史评测/早于 v2.0.8 的审阅结论；输出到 `v2.0.8-owner-authorized-semantic-quality-remediation/final-blockers-decision-pack/`（7 个文件：final-blockers-decision-pack.jsonl 恰 2 行、owner-decision-template.jsonl 恰 2 行且仅 owner_decision/owner_reviewer/owner_notes 三个空字段、chain-impact-map.json、raw-evidence-verification.json、OWNER_DECISION_GUIDE.md、final-blockers-report.md、manifest.json 自哈希 + inputs/outputs SHA）。fail-closed 门禁（任一漂移 → DecisionPackError，零输出）：v2.0.8 = 143 case / 151 active raw evidence / strict validator 151/151（covered==passed）、legacy=0、unresolved=0、manifest 自哈希、gate `REMEDIATION_CANDIDATE_OK`；multi-030 链关系**精确**（multi-031.follow_up_to=="multi-030"、multi-032/033/034.chain_id=="multi-030"，无其他引用）；deferred ledger 恰 1 条且原因固定 `retirement_deferred_due_to_active_follow_up_chain_dependency`；multi-030 与 multi-031~034 在 draft-before→after / evidence-before→after **逐字节不变**（v2.0.7→v2.0.8 未动）；mixed-027 targeted re-review 确为 `TARGETED_REVIEW_OK` / reject / AP0 directly_supported / AP1 unsupported / deepseek-v4-pro（仅事实核验，**不采纳模型结论**）。本地逐字重验（判定唯一依据，确定性可审计）：strict 口径（`_match_in_norm`，min_span=8，命中须完全落在 evidence raw span 内；exact=连续覆盖 ≥0.75，与 v2.0.7 决策包同口径）+ token 级独立交叉验证（span 内全部 ≥2 字符连续段，非贪心）+ 源内完整 AP 命中唯一性（repair 判定）；所有候选证据给出 chunk/source/Unicode raw [start,end)/原文 span/唯一性/严格重建结果，不允许语义猜测、跨 source 扩展或模型输出替代。**multi-030 选项核实**：`repair_in_place_with_direct_exact_evidence` 条件不成立（答案点『数字（把 Python 当作计算器）』为组合式文本，源内无完整逐字命中；最长连续子串『把 Python 当作计算器』出现 2 次（32c427fb50e2_chunk_2 [1824:1838) 与 chunk_3 [31:45)）**不唯一**）；`retire_entire_dependent_chain` 列出不可拆分组影响（5 case / 5 evidence / 5 answer points，组内引用 6 条、组外 0 条，上游 chain multi-028 将失去成员 multi-030/031——成员缺失影响如实列入 chain-impact-map.json，不自动判断）；`keep_deferred_and_block_fresh_review` 为现状。**mixed-027 选项核实**：`remove_unsupported_answer_point_1` 条件不成立（删除 AP1 后 AP0 仍无 strict 连续逐字支撑——span 内最长连续段『原子化操作』5 字符覆盖 0.38 < 0.75，另有『不可再分』4 字符，均为 token 级片段；不形成零答案点但 strict 条件不满足）；`repair_with_direct_exact_evidence` 条件不成立（AP1 为负向元论述『仅列出/未展开事务原子性说明』，源内仅 token『begin-stmt』[185:195) 唯一命中但非完整 AP）；`keep_deferred_and_block_fresh_review` 为现状。修复两处实现问题：`_verify_ap` 的 evidence-checks 按 chunk_id 排序（8b191b241b93 行在 c9fd20815ea8 行前），选项判定改用 `_best_evidence_check`（strict 覆盖优先取支撑性最强行）避免误用非支撑行；preflight 对缺失 candidate manifest fail-closed 包装。manifest 声明：llm_called=false、network_used=false、overlay_generated=false、split_created=false、v2_1_entered=false、recommendation_made=false、model_output_used_as_fact=false、data_modified=none、input_scope 仅 v2.0.8 candidate dir/chunks/chunk manifest/strict validator。`data-analytics:analyze-data-quality` 实际不可用（`Skill not found`，已尝试），改用等价确定性五维检查（并入 final-blockers-report.md）。未 stage/commit/push。

- **v2.0.8 owner-authorized semantic-quality remediation candidate（链安全版，确定性 + 批次 E Pro-only 定向复审）——真实构建成功（148 → 143）** — 修订 `scripts/corpus_v2_v208_semantic_quality_remediation.py` 与 TDD 测试（47 个，新增/修订：链依赖 defer、143/151 计数、drift fail-closed、deferred ledger、逐字节不变）：上一版因 `multi-030` 链依赖整体 BLOCKED，本版按任务修订将其从退役清单移除并**延后（deferred）**。fail-closed 门禁（任一漂移 → RemediationError，零输出）：v2.0.7 candidate == 148 cases、strict raw-codepoint-v1 evidence 161/161（covered==passed==161）、legacy==0、unresolved==0、automated review 126 confirmed / 22 reject / 0 needs_followup、decision pack gate `DECISION_PACK_OK` + 自哈希 + 22 条 reject 覆盖 + 五批次分布恰为 7/1/3/10/1 + 每条 recommended_action 与授权动作表逐字一致、remove case removal_targets==[0] 且 removal_zero_risk==False、retire case removal_zero_risk==True、延后 case（multi-030）仍须是 retire-eligible pack 行、无 overlay、draft 148 行唯一且与 review 集合一致、pack/draft 答案点逐字一致。**链依赖门禁（新增）**：multi-030 的依赖结构必须与授权 defer 依据**完全一致**——`multi-031.follow_up_to == "multi-030"` 且 `multi-032/033/034.chain_id == "multi-030"`（TDD 覆盖：解除引用或新增意外引用均为漂移 → 整体停止）；五条退役 case（en-044/en-050/mixed-026/zh-042/zh-045）无任何 follow-up/chain/doc_target/case 引用依赖（TDD 覆盖意外依赖 fail-closed）。已授权动作（同首版，严格按 decision pack 已验证候选）：批次 A 7 条自包含 exact raw 替换（zh-023→32c427fb50e2_chunk_10 [262:327)、mixed-028→5927c70d0f8e_chunk_0 [567:760) 等，第一个 self_contained+unique 候选，旧 token evidence 清理、新 raw-codepoint-v1 evidence）；批次 B zh-040 追加两条 TOC evidence（`OWNER_AUTHORIZED_SAME_SOURCE_EVIDENCE_SCOPE_EXPANSION`）；批次 C en-029/multi-019/zh-052 翻译等价策略 + 恰 3 条 ledger（非自动 confirmed）；批次 D 移除 en-042/en-049/en-051/mixed-033 的 AP0（预检剩余 ≥1，orphan evidence 按 raw span 内逐字支撑规则清理）；批次 D 退役 5 条（en-044/en-050/mixed-026/zh-042/zh-045，retired-cases.jsonl 5 条 / retired-evidence.jsonl 9 条，固定原因 `no_semantically_sufficient_direct_evidence_after_owner_authorized_review`）。**延后（新增输出 `deferred-chain-dependent-cases.jsonl`，恰 1 条）**：multi-030 不修改 draft/答案点/evidence/source-chunk 关系、不退役、不改 follow_up_to/chain_id 或任何子节点；延后原因 `retirement_deferred_due_to_active_follow_up_chain_dependency`，列出依赖 case 与关系（multi-031 follow_up_to；multi-032/033/034 chain_id），`not_resolved=true`、`not_confirmed=true`、`not_accepted_quality_conclusion=true`，manifest/REPAIR_REPORT/REVIEW_AND_SPLIT_REBUILD_REQUIRED 明确这不是 resolved/confirmed/已接受的质量结论。批次 E（mixed-027 定向盲态复审）：candidate 写入成功后执行，**实际调用 `deepseek-v4-pro`（temperature=0.0/max_tokens=8000/thinking disabled/max_retries=3、无 fallback、模型身份校验）**，payload 盲态（无 case_id/批次/历史/decision，治理 token 零命中）；结果 `TARGETED_REVIEW_OK`（0 次传输重试）：decision=reject、AP0 directly_supported（evidence_refs [1]）、AP1 unsupported（evidence_refs [0]）——仅作 `targeted-re-review/` 诊断（payload/raw-response/result/report/review-status/manifest 6 个文件，manifest 自哈希一致），candidate draft/evidence/manifest SHA 逐字节未变，不生成 overlay。**真实产物验收**：draft 148→143 且 case_id 唯一、evidence 161→151 全部通过 strict validator（covered==passed==151）、所有 raw span `chunk_text[start:end] == raw_evidence_span` 可重建、multi-030 与 multi-031~034 draft/evidence 逐字节不变、非目标行逐字节不变、无新增零答案点 case、retired 5/retired-evidence 9、翻译 ledger 恰 3 条、diff 17 行、两次构建逐字节一致、manifest 自哈希与磁盘 SHA 一致（2a5fa3b2…）、11 个输入 SHA 运行前后不变、无 overlay/active/split/locked/v2.1 产物、candidate 不含 review 结果；metadata 固定 `revision_status=CANDIDATE`、`activation_blocked=true`、`human_reviewed=false`、`actor=OWNER_AUTHORIZED_SEMANTIC_QUALITY_REMEDIATION_CHAIN_SAFE`、`case_count_before=148`、`case_count_after=143`、`overlay_generated=false`、`split_reseal_required=true`、`v2_1_entered=false`。顺带修正一处测试假阳性：`test_fail_closed_review_count_drift` 原先篡改 canonical 首行（en-021 本就 confirmed）实为空操作，改为篡改第一条 reject 行使其真正触发计数漂移。`data-analytics:analyze-data-quality` 实际不可用（`Skill not found`，已尝试），改用等价确定性五维检查（data-quality-report.json）。未 stage/commit/push。

- **v2.0.8 owner-authorized semantic-quality remediation candidate（确定性、离线）——真实输入按门禁整体停止（BLOCKED）** — 新增 `scripts/corpus_v2_v208_semantic_quality_remediation.py` 与 TDD 测试（43 个）：基于 v2.0.7 reject semantic-quality decision pack（用户已批准推荐策略），实现批次 A–E 全部确定性修改机制（148→142、evidence 161→150），但**真实输入的 fail-closed 门禁被触发**：批次 D 退役 case `multi-030` 存在 follow-up/chain 依赖——`multi-031.follow_up_to="multi-030"`（chain multi-028 第 2 轮），且 `multi-032/033/034.chain_id="multi-030"`——按任务门禁「retire 前 fail-closed 检查 follow-up、chain、doc_target 和 case 引用依赖；有任何依赖则整体停止」，`run()` 以 `RemediationError` 整体停止，**v2.0.8 输出目录零产物**（exit=2），mixed-027 定向盲态复审也未执行（顺序门禁：candidate 未写入成功，`review-targeted` 返回 `TARGETED_REVIEW_BLOCKED` 且不调用 LLM）。门禁（全部实现并在真实输入上通过，仅退役依赖门禁被真实数据触发）：v2.0.7 candidate == 148 cases、strict raw-codepoint-v1 evidence 161/161（covered==passed==161）、legacy==0、unresolved==0、automated review 126 confirmed / 22 reject / 0 needs_followup、decision pack gate `DECISION_PACK_OK` + 自哈希 + 22 条 reject 覆盖 + 五批次分布恰为 7/1/3/10/1 + 每条 recommended_action 与授权动作表逐字一致、remove case 的 removal_targets==[0] 且 removal_zero_risk==False（预检剩余答案点 ≥1）、retire case 的 removal_zero_risk==True、无 overlay（review manifest + 目录扫描）、draft 148 行 case_id 唯一且与 review case 集合一致、pack current_answer_points 与 draft 答案点逐字一致。固定授权动作（严格按 decision pack 已验证 exact raw candidate / answer point index / source/chunk/range，不重新选择 evidence、无模型代替选择）：批次 A（7 条 mixed-028/mixed-029/zh-023/zh-026/zh-029/zh-036/zh-054）——答案点替换为 candidate_refs 中**第一个 self_contained=True 且 unique=True** 的候选（refs 按 (chunk_id,start) 排序；如 zh-023→32c427fb50e2_chunk_10 [262:327)「生成的序列绝不会包括给定的终止值；range(10) 生成 10 个值——长度为 10 的序列的所有合法索引。」、mixed-028→5927c70d0f8e_chunk_0 [567:760) 英文完整句），新答案点逐字 == raw span（仅 CRLF→LF），旧 token evidence（state/一致/10/del/json/目录）清理，写入新 raw-codepoint-v1 evidence（chunk_text_sha256/snippet/display-whitespace-v1）；批次 B（zh-040）——答案点不变，仅追加两条已验证 TOC evidence（32c427fb50e2_chunk_1 [182:192)「- 7. 输入与输出」与 [360:370)「- 8. 错误和异常」，同 chunk 连续可重建），diff 显式记录 `OWNER_AUTHORIZED_SAME_SOURCE_EVIDENCE_SCOPE_EXPANSION`；批次 C（en-029/multi-019/zh-052）——`faithful_translation_equivalence_v1` 策略文件 + **恰 3 条** ledger（每条含中文答案点、evidence_anchors（source/chunk/raw range/raw span/snippet）、理由、授权标识、`not_confirmed=true`、`requires_blind_re_review=true`；不是自动 confirmed，不扩展其他 case，不静默修改全局 review 标准），不改变任何数据；批次 D 移除（en-042/en-049/en-051/mixed-033）——仅移除 pack 指定 AP0（移除后仍保留 AP1，预检 ≥1），orphan evidence 清理规则：evidence 行仅当**任一保留答案点在 raw span 内（匹配完全落在 span 内）仍有逐字覆盖（>0）**才保留，否则移除（en-042/en-049/en-051 各移除 1 条，mixed-033 两条重复行因仍逐字支撑 AP1 均保留），写 diff/ledger；批次 D 退役（en-044/en-050/mixed-026/multi-030/zh-042/zh-045）——draft-after 与 evidence-after 移除，写 retired-cases.jsonl（6 条）/ retired-evidence.jsonl（10 条），固定原因 `no_semantically_sufficient_direct_evidence_after_owner_authorized_review`；批次 E（mixed-027）——盲态 payload 仅含 query/previous_turns（剥离 case_id）/should_refuse/acceptable_answer_points/evidence/必要 chunk 原文（递归断言零命中 case_id/batch/decision/review 等治理 token），Pro-only 契约（`deepseek-v4-pro`/temperature=0.0/max_tokens=8000/`{"thinking":{"type":"disabled"}}`/max_retries=3、无 fallback、模型身份校验），结果仅 `targeted-re-review/` 诊断文件，无论结果如何不生成 overlay、不改变 case 数据，失败如实标 `TARGETED_REVIEW_BLOCKED`（含模型身份不符/JSON 解析失败/schema 契约违反/候选未建成四种 BLOCKED 路径，全部 TDD 覆盖）。严格验收（在解除 multi-030 引用的测试 fixture 上验证构建机制本身）：148→142 case_id 唯一、evidence 150 行全部通过 strict validator（covered==passed==150）、所有 raw span `chunk_text[start:end] == raw_evidence_span` 可重建、非目标 draft/evidence 行逐字节不变、无新增零答案点/零 evidence case（语料既有 31 条 noanswer-* 拒答 case 与 multi-029 本就为零答案点，属既有状态）、翻译 ledger 恰 3 条、退役 ledger 恰 6 条、batch_e case 数据逐字节不变、两次构建逐字节一致、manifest 自哈希与磁盘 SHA 一致、18 个输入 SHA 运行前后不变、无 overlay/active/split/locked/v2.1 产物、candidate 不含任何 review 结果（不复用 v2.0.7 审阅结论）。`data-analytics:analyze-data-quality` 实际不可用（`Skill not found`，已尝试），改用等价确定性五维检查。输出目录未创建；未 stage/commit/push。

- **v2.0.7 reject semantic-quality closure decision pack（只读、确定性、离线）** — 新增 `scripts/corpus_v2_v207_reject_semantic_quality_decision_pack.py` 与 TDD 测试（37 个）：基于 v2.0.7 reject triage 的 22 条 reject，生成面向所有者批量决策的「语义质量闭环决策包」；**不是修复**——不修改 candidate draft/evidence/chunks/review/triage，不调用 LLM/API、不联网、不生成 overlay/active metadata/split/v2.1 文件，推荐动作与五批次建议**绝不自动应用**。fail-closed 门禁（任一漂移 → DecisionPackError，零输出）：reject 集合恰 22 条；triage 集合 == reject 集合、triage 行恰 22 条唯一；triage 类别分布**恰好 8 / 5 / 6 / 2 / 1**（其余类别 0）；candidate 148 条、strict raw-codepoint-v1 evidence 161/161、无 overlay；review/candidate/triage manifest 自哈希 + outputs SHA、triage manifest inputs == 当前磁盘 SHA（18 个输入全链闭环）。逐答案点语义质量分析（纯机械、确定性）：同 source 全 chunk 归一化逐字匹配（coverage ≥ 0.75，min_span=8）→ 对每个命中扩展出**更完整**候选：`full_sentence`（句末标点结尾且排除 "4.10." 编号点误判）/ `full_paragraph` / 兜底 `heading`（# 行）/ `line_label`（TOC/列表行）；段落边界规则：空行、标题行、列表/TOC 行（`^- ` 或 `^数字.`）、真代码块（``` 且至少一侧有空行），行内代码栅栏（``json`` 式，两侧无空行）不切分句子；每个候选记录 source/chunk/raw range/raw span（全部强制 `chunk_text[start:end] == raw_span`）、coverage（全部 ≥ 0.75，**绝不把 partial/paraphrase 写成 exact**）、源内精确出现次数与唯一性、是否已被当前 evidence span 覆盖（`scope_expansion_required = 未覆盖`，候选不会跨越声明范围而不标记）。每 case 记录 `semantic_quality_insufficient`（答案点无任何自包含完整句/段候选 → 仅孤立 token/标题/短标签支撑）、`removal_zero_risk`（推荐移除/退役会清空全部答案点）、当前答案点/当前 raw evidence/模型 rationale 与 assessment（原样记录，不作为事实）。默认推荐（仅建议）：cat1（8 条）有自包含完整句候选 → `replace_answer_point_with_self_contained_exact_raw_text`，否则仅孤立 token/标题 → `retire_case`；cat4（6 条）全部答案点有逐字候选 → `expand_same_source_evidence_scope`，部分 in_evidence=none → `remove_unsupported_answer_point`，全部无证据 → `retire_case`；cat2（5 条）language_mismatch（中文答案点 + 英文源）→ `owner_approved_translation_equivalence_policy`（翻译等价**不自动判为 confirmed**），partial_coverage 无 exact 文本 → remove/retire；cat5（2 条）仅 `retire_case`/`keep_unresolved`；cat8（1 条 mixed-027）输出本地契约证明（全部答案点模型评估 directly_supported 却 reject、本地逐字事实并列），仅 `targeted_blind_re_review`/`keep_unresolved`，不因「模型似乎矛盾」自动改 confirmed；不提供「放宽 review 标准」作为默认动作。**真实决策结果（22 条，五批次守恒）**：`batch_a_replace_with_self_contained_exact_text` **7**（mixed-028——自包含句「在 React 中，随时间变化的数据被称为状态（state）。」、mixed-029/zh-054——「CPython 没有一致应用针对迭代器定义 __iter__() 的要求。」、zh-023——「生成的序列绝不会包括给定的终止值；range(10) 生成 10 个值——长度为 10 的序列的所有合法索引。」、zh-026、zh-029、zh-036）、`batch_b_expand_same_source_scope` **1**（zh-040——TOC 行 `- 6. 模块`/`- 7. 输入与输出`/`- 8. 错误和异常` 逐字候选均在 chunk_1 内但超出 evidence span [0:55)）、`batch_c_translation_policy_required` **3**（en-029、multi-019、zh-052）、`batch_d_retire_or_remove` **10**（remove_unsupported_answer_point 4：en-042、en-049、en-051、mixed-033——AP0 无证据支撑；retire_case 6：en-044、en-050、mixed-026、multi-030、zh-042、zh-045）、`batch_e_targeted_re_review` **1**（mixed-027）。124 条候选行 124/124 raw 可重建、0 条 coverage<0.75、39 条自包含完整句/段；零答案点风险 6 条（en-044、en-050、mixed-026、multi-030、zh-042、zh-045）；semantic_quality_insufficient 15 条。输出 8 个文件（semantic-quality-decision-pack.jsonl、self-contained-raw-candidates.jsonl、owner-batch-decision-template.jsonl——含每行 `recommended_action` 但 owner_decision/owner_reviewer/owner_notes 三字段留空、OWNER_SEMANTIC_QUALITY_DECISION_GUIDE.md、decision-pack-summary.json、decision-pack-report.md、data-quality-report.json、manifest.json），manifest 自哈希与磁盘 SHA 一致、18 个输入 SHA 运行前后不变、两次构建逐字节一致；`data-analytics:analyze-data-quality` 实际不可用（`Skill not found`，已尝试），改用等价确定性五维检查；未 stage/commit/push。

- **v2.0.7 automated-review reject root-cause triage（只读、确定性、离线）** — 新增 `scripts/corpus_v2_v207_review_reject_triage.py` 与 TDD 测试（30 个）：对 v2.0.7 fresh blind automated review 的全部 **22 条 reject** 做确定性、只读的证据与语义根因分流，为后续所有者决策准备依据；**不是修复**——不修改 candidate draft/evidence/chunks/review，不调用 LLM/API、不联网、不生成 overlay/active metadata/split/v2.1 文件，无 draft-after/evidence-after/修复文件。fail-closed 门禁（任一漂移 → TriageError，零输出）：canonical 恰 148 行且 confirmed=126/reject=22/needs_followup=0、case_id 唯一；issues 恰 22 行且 case_id 集合 == reject 集合、行级等于 canonical 对应行；candidate case_count=148、evidence-after 161 行全部 raw-codepoint-v1 且 strict validator covered==passed==161；无 automated overlay（目录无 overlay 文件 + review manifest overlay_generated=false）；review manifest 自哈希 + 8 个 outputs SHA、candidate manifest 自哈希 + 状态字段 + outputs SHA、当前 draft/chunks/chunk-manifest SHA == candidate manifest inputs；pack 148 行、case_id 集合一致、payload_sha256 全部可复算；31 个 refusal case 无答案点/evidence 且全部 confirmed。逐条分流（模型 rationale 不作为事实，只原样记录；分类依据本地 raw 文本事实）：归一化逐字匹配（NFKC + 空白折叠 + ASCII 小写，min_span=8，覆盖 ≥0.75 → exact；exact 仅指连续 raw text 可重建），每答案点计算 in_evidence / in_relevant / same_source / other_source 状态与 language_mismatch（CJK 阈值）；九类互斥分类优先级：字段矛盾（should_refuse vs is_refusal_turn/答案点/evidence）→ `refusal_label_or_schema_inconsistency`；全部答案点 supported 却 reject 或拒答 assessment 与 should_refuse 矛盾 → `review_contract_or_model_semantics_inconsistency`（mixed-027，部分答案点 unsupported 时模型拒绝属合理行为，由证据侧归类）；全部答案点 exact_in_evidence → `exact_evidence_present_but_review_semantic_disagrees`；语言不匹配 → `partial_or_paraphrase_only`（language_mismatch）；存在 none 答案点且同 source（相关 chunk 或同源其他 chunk）有逐字内容 → `evidence_scope_insufficient_but_same_source_candidate_exists`（记录 scope 候选，不修改 scope）；其他 source exact → `cross_source_or_cross_document_coverage_gap`；无候选且其他答案点有支持 → `answer_point_overclaims_available_evidence`；全部 none 无候选 → `no_direct_support_in_declared_source`；存在 partial（无 none）→ `partial_or_paraphrase_only`；兜底 `unresolved_requires_owner_judgment`。**真实分流结果（22 条，类别统计守恒）**：`exact_evidence_present_but_review_semantic_disagrees` **8**（mixed-028、mixed-029、multi-030、zh-023、zh-026、zh-029、zh-036、zh-054——答案点逐字在 evidence raw span 内可重建但模型以孤立词/标题语义拒绝）、`partial_or_paraphrase_only` **5**（en-029、en-044、en-050、multi-019、zh-052，其中 3 条为语言不匹配：中文答案点对英文源）、`evidence_scope_insufficient_but_same_source_candidate_exists` **6**（en-042、en-049、en-051、mixed-033、zh-040、zh-042——如 en-042 的 generic URI syntax 在 rfc3986 chunk_0/chunk_25 中但不在 evidence span 内、zh-040 的「输入与输出」「错误和异常」在 chunk_1 内但不在 evidence span 内）、`no_direct_support_in_declared_source` **2**（mixed-026、zh-045）、`review_contract_or_model_semantics_inconsistency` **1**（mixed-027，两个答案点均 directly_supported 却 reject）；`answer_point_overclaims_available_evidence`/`cross_source`/`refusal_schema`/`unresolved` 本次 0 条（类别逻辑覆盖完整）。每条记录零答案点风险（全部答案点 in_evidence=none 的 5 条：en-029、mixed-026、multi-019、zh-042、zh-045）、v2.0.5/v2.0.6 曾改动标记（7 条，不预设结论）、模型 rationale/assessment 原样记录、本地逐答案点覆盖事实、scope 候选 span（全部满足 `chunk_text[start:end] == raw_span`，119 条 span 可重建）。输出 7 个文件（review-reject-triage.jsonl、candidate-evidence-spans.jsonl、review-reject-triage-summary.json、owner-decision-template.jsonl——每行仅新增三个空字段 owner_decision/owner_reviewer/owner_notes，不可填值不可自动修复、review-reject-triage-report.md、data-quality-report.json、manifest.json），manifest 自哈希与磁盘 SHA 一致、11 个输入与 candidate 11 输出及 automated-review 9 输出 SHA 运行前后不变、两次构建逐字节一致、机械可修复 0 条/全部需所有者决策；`data-analytics:analyze-data-quality` 实际不可用（`Skill not found`，已尝试），改用等价确定性五维检查；未 stage/commit/push。

- **v2.0.7 owner-authorized fresh blind automated review（LLM 自动审阅，非人工）** — 新增 `scripts/corpus_v2_v207_fresh_automated_review.py` 与 TDD 测试（21 个）：对 v2.0.7 candidate 全部 148 条 case 重新做盲态机器审阅，替代已失效的 150 条旧 review 结果；用户明确授权使用 LLM，但审阅人身份固定为 `LLM_ASSISTED_OWNER_AUTHORIZED_V2_0_7`，绝不伪称人工审阅。模型约束：仅 `deepseek-v4-pro`、temperature=0.0、max_tokens=8000、`extra_body={"thinking": {"type": "disabled"}}`、max_retries=3、无 fallback/混用；先跑不读取 case 的最小 `--probe-json`（模型身份 + JSON 能力验证，实际通过），失败即停止。前置门禁（preflight，fail-closed）：case_count=148、active_evidence=161、strict covered/passed=161、legacy=0、unresolved=0、activation_blocked=true、v2.0.7 manifest 自哈希/输出 SHA、draft/chunks/chunk-manifest 输入 SHA 不变。盲态：模型输入只含 query / previous_turns（剥离 case_id 与链路引用，仅 `{"query"}`）/ should_refuse / acceptable_answer_points / evidence（raw span + 展示 snippet）/ 对应 chunk 原文；不含 case_id、split/dev/holdout、旧 review decision/rationale、历史 reject/blocker/remediation、评测分数或候选版本结论（测试递归扫 payload 键 + 语料零命中治理 token，148 行零泄露）。审阅契约逐 case 严格 JSON：decision（confirmed/reject/needs_followup）+ rationale + answer_point_assessments（answer_point_index/assessment/evidence_refs）+ refusal_assessment；本地严格校验 schema、枚举、模型身份、索引/引用范围，拒答/可答分别按一致性规则（可答题必须 not_applicable、confirmed 不得有空/无效引用、unsupported 不得 confirmed、拒答题必须 correct/incorrect_refusal），每条失败最多同模型纠正重试 3 次。**真实运行结果（deepseek-v4-pro，148 次调用，0 传输/解析重试）：confirmed 126 / reject 22 / needs_followup 0 → `AUTOMATED_REVIEW_GATE_BLOCKED`，未生成 automated overlay**；22 条 reject 全部进入 `automated-review-issues.jsonl` 并列出 rationale（主要为证据充分性判断，如 zh-023/zh-026/zh-029/zh-036/zh-054/mixed-029 等 v2.0.5 收窄 case 与 mixed-028 的收窄证据被判定仍不充分）。运行中发现并修复根因：模型把 `refusal_assessment` 误解为「是否未拒答」导致可答题输出 `incorrect_refusal`（en-029 首次运行 fail-closed）——系统提示明确枚举语义 + 纠正重试携带具体校验错误（TDD 覆盖）。输出 9 个文件（automated-review-pack.jsonl、automated-review-evidence.jsonl、automated-review.jsonl、raw-model-responses.jsonl、automated-review-summary.json、automated-review-report.md、automated-review-gate-report.md、automated-review-issues.jsonl、manifest.json），148 条恰好一次、稳定排序、统计守恒；仅当 148/148 confirmed 才生成 `automated-reviewed-truth-overlay.json`（状态 `AUTOMATED_REVIEWED_OWNER_AUTHORIZED`），本次未生成；即使生成 overlay 也保持 revision_status=CANDIDATE、activation_blocked=true、human_reviewed=false、split_reseal_required=true、v2_1_entered=false。复用既有 automated review 的严格 JSON/SHA/盲态/fail-closed 逻辑（canonical_sha、fence 严格解析、确定性时间戳、原子 staging），不复制第二套校验。不修改 candidate draft/evidence/chunks（11 个输出 SHA 不变），不读取 split/dev/holdout、锁配置、历史评测、旧 automated review/human review 产物；`data-analytics:analyze-data-quality` 不可用（`Skill not found`），改用离线确定性完整性/唯一性/引用完整性/连续性/一致性检查；未 stage/commit/push。

- **v2.0.7 owner-authorized redundant legacy evidence retirement candidate（确定性、离线）** — 新增 `scripts/corpus_v2_v207_legacy_evidence_retirement.py` 与 TDD 测试（17 个）：用户已授权移除 `zh-037::32c427fb50e2_chunk_33::legacy` 这一条冗余 legacy coordinate evidence（历史展示文本「内置函数 dir() 用于查找模块定义的名称。返回结果是经过排序的字符串列表」，无 `coordinate_contract`，无法按 `raw-codepoint-v1` 严格校验），evidence 162→161；只创建新 candidate revision，不覆盖 v2.0.6/active 数据。fail-closed 门禁：v2.0.6 manifest 自哈希/status/counts/输出 SHA、与 v2.0.5 的 lineage SHA（v2.0.6 before == v2.0.5 after）、当前 draft/chunks/chunk-manifest 输入 SHA 不变；v2.0.6 reconciliation 结论必须为 RECONCILIATION_BLOCKED 且唯一 blocker 恰为该 legacy 行（`non_strictly_legal_rows` 恰 1 条、失败条件恰为 covered/passed/uncovered/invalid 四条）；evidence-after 独立复算恰 162 行且 legacy 行恰 1 条（额外/缺失均 fail-closed）；successor 证明：zh-037 恰 1 条 strict raw-codepoint-v1 evidence（32c427fb50e2_chunk_32 [1921,1931)「经过排序的字符串列表」），raw span 恰等于保留答案点、自 v2.0.5 起逐字节存在、与 legacy 行同 source；legacy 行不承载唯一 source/chunk 关系（chunk_33 仅该行，退役后 zh-037 仍有合法 evidence）。固定修改：`draft-after.jsonl` 与 v2.0.6 逐字节一致（148 case、case_id 唯一）；`evidence-after.jsonl` 仅移除该唯一 legacy 行，其余 161 行逐字节不变；退役行写入 `retired-legacy-evidence.jsonl`（原始完整行逐字保留、`retirement_reason=redundant_legacy_coordinate_superseded_by_raw_codepoint_v1_evidence`、successor identity/raw range/span、`OWNER_AUTHORIZED_REDUNDANT_LEGACY_EVIDENCE_RETIREMENT` 授权标识）；legacy `char_range` 逐字携带、不做任何 raw 坐标猜测/转换/重新解释。严格验收全部成立：raw-codepoint active evidence == 161、strict validator covered == 161、passed == 161、uncovered == 0、invalid == 0、legacy coordinate evidence == 0、unresolved == 0，所有可答 case 均有严格合法 evidence，zh-037 保留原答案点与 successor raw evidence。输出 11 个文件（draft/evidence before/after、reannotation-diff、retired-legacy-evidence、coordinate-validation-report、data-quality-report、REVIEW_AND_SPLIT_REBUILD_REQUIRED、REPAIR_REPORT、manifest），metadata 固定 `revision_status=CANDIDATE`、`activation_blocked=true`、`human_reviewed=false`、`actor=OWNER_AUTHORIZED_REDUNDANT_LEGACY_EVIDENCE_RETIREMENT`、`case_count_before=148`、`case_count_after=148`、`evidence_count_before=162`、`evidence_count_after=161`、`overlay_generated=false`、`v2_1_entered=false`；两次构建逐字节一致，manifest 自哈希与磁盘 SHA 一致。不生成 overlay/active metadata/v2.1/review 结果/split/locked config；`data-analytics:analyze-data-quality` 不可用（`Skill not found`），改用离线确定性检查；未 stage/commit/push。

- **v2.0.6 candidate evidence-count reconciliation（只读、确定性、离线）** — 新增 `scripts/corpus_v2_v206_evidence_count_reconciliation.py` 与 TDD 测试（12 个）：独立复算 v2.0.6 candidate 的 evidence 数量并解释「evidence-after=162」与「strict_validate=161」差异，不改写任何 candidate 数据、不调用 LLM/API/联网/RAG 评测、不读取 split/dev/holdout/锁配置。门禁：v2.0.6 manifest status/自哈希/evidence-after SHA、v2.0.5 manifest 存在且当前 draft/chunks/chunk-manifest SHA 与 v2.0.5 manifest inputs 一致。复算结果：evidence-before=159、evidence-after=162、retired-evidence=1；算式 `159 - 5 + 8 = 162` 精确成立（数值 + 集合身份双重验证：移除 4 条目标 case 旧行 5 条、新增 raw evidence 8 条）；互斥完整分区 161 raw-codepoint-v1 active + 1 legacy coordinate（zh-037 保留的历史 legacy 行，无 coordinate_contract，按契约不在 strict validator 输入集合）+ 0 unresolved/non-active + 0 malformed；strict validator 输入集合 161、通过 161、失败 0、未覆盖 1；161 条 raw 行全部通过 `chunk_text[start:end] == raw_evidence_span` 与 source/chunk/SHA/range 边界校验；zh-035 六条 multi-span、mixed-022 一条、mixed-028 一条全部 covered 且 passed；非严格合法行恰 1 条（zh-037，chunk 32c427fb50e2_chunk_33，精确列出 identity/类别/原因）。结论 **RECONCILIATION_BLOCKED**（strict_validator_covered/passed≠162、uncovered=1、invalid=1），如实列出失败条件与 blocker，不掩盖差异、不自行修复；处置遗留 legacy 行需所有者另行决策。v2.0.6 manifest 自哈希与磁盘 SHA 一致、14 个输出 SHA 全部匹配；v2.0.5 manifest / 当前 draft / chunks / chunk manifest SHA 全部不变。输出 4 个文件（evidence-count-reconciliation.json、strict-validation-coverage.jsonl、reconciliation-report.md、manifest.json），两次构建逐字节一致；不生成 overlay/active/v2.1/review/split/locked config；未 stage/commit/push。

- **v2.0.6 owner-authorized final blocker closure candidate（确定性、离线）** — 新增 `scripts/corpus_v2_v206_final_blocker_closure.py` 与 TDD 测试（18 个）：基于 v2.0.5 candidate 关闭最后 4 条 blocker，不调用 LLM/API、不联网，动作全部为所有者固定授权、不再请求模型判断。fail-closed 门禁：v2.0.5 manifest 自哈希/status/counts、draft-after/evidence-after SHA、当前 draft/chunks/chunk-manifest 输入 SHA、decision-pack 自哈希与目标集合恰好 4 条、8 条拟写 span 全部满足 `chunk_text[start:end] == raw_evidence_span` 且与 pack 枚举/语料级完整重枚举交叉一致（zh-035 `fibo.py` 全语料枚举恰 6 条）、mixed-022「A function returning another function」[18,55) 与 mixed-028「state」[152,157) 唯一性、zh-032 退役前无 follow-up/chain/doc_target 依赖。动作：**zh-035** 保持 query/答案点，启用显式 `multi_span_exact_evidence_v1` policy，写入全部 6 个 verbatim duplicate span（declared source 内 3 个 + en 源 3 个），每个 span 独立记录 raw source/chunk/`[start,end)`/raw span SHA，跨 source scope 扩展显式记录为 `OWNER_AUTHORIZED_MULTI_SOURCE_EXACT_EVIDENCE_SCOPE_EXPANSION`（manifest + diff，无静默修改）；**zh-032** retire（原因固定 `no_directly_supported_answer_point_after_owner_authorized_review`），写入 retired-cases/retired-evidence；**mixed-022** 答案点收窄为「A function returning another function」并删除未获支持的「装饰器」答案点与 orphan evidence；**mixed-028** 删除无直接证据的答案点 0，答案点收窄为「state」，删除 orphan evidence。case 149→148，evidence 159→162（移除 5 条目标旧行、新增 8 条 raw 行，全部通过 strict validation），remaining_blockers=0、目标 case 无 legacy/unresolved 残留、148 条 case_id 唯一且所有可答 case 均有合法 evidence、非目标行逐字节不变。输出 14 个文件（draft/evidence before/after、reannotation-diff、retired-cases/evidence、multi-span-evidence-policy.md、multi-span-evidence-ledger.jsonl、coordinate-validation-report、data-quality-report、REVIEW_AND_SPLIT_REBUILD_REQUIRED、REPAIR_REPORT、manifest），metadata 固定 `revision_status=CANDIDATE`、`activation_blocked=true`、`human_reviewed=false`、`actor=OWNER_AUTHORIZED_FINAL_BLOCKER_CLOSURE`、`case_count_before=149`、`case_count_after=148`、`overlay_generated=false`、`v2_1_entered=false`；两次构建逐字节一致，manifest 自哈希与磁盘 SHA 一致。不生成 active metadata/overlay/v2.1，不复用/不生成 split 或 locked config，历史 review/split 文件不被读取；`data-analytics:analyze-data-quality` 不可用（`Skill not found`），改用离线确定性完整性/唯一性/引用完整性/连续性/一致性检查；未 stage/commit/push。

- **v2.0.5 remaining-four blocker closure decision pack（只读、确定性、离线）** — 新增 `scripts/corpus_v2_remaining_blockers_decision_pack.py` 与 TDD 测试（17 个）：不调用 LLM/API、不联网；为 v2.0.5 仍未解决的 4 条 case（zh-035、zh-032、mixed-022、mixed-028）生成仅所有者决策的最小决策包，输出到 `v2.0.5-owner-authorized-scope-repair/remaining-blockers-decision-pack/`。fail-closed 门禁：v2.0.5 manifest 自哈希/status/counts、draft-after/evidence-after SHA、draft/chunks/chunk-manifest 输入 SHA、4 条 draft 行与当前 draft 逐字节一致、evidence 行数（1/1/1/2）与 source/chunk 一致、owner-decision-pack 自哈希与 blocker 分类、rescue-audit `AUDIT_OK` 与 zh-035 `ambiguous_duplicate`。每条输出原始 answer point、当前 evidence、declared chunk 全文 + anchor catalog + 引用 chunk 原文、所有可证明 raw span（display 归一化完整枚举，`chunk_text[start:end]==raw_span` 逐条证明）、风险与动作选项，不自动选择动作。特别规则：zh-035 语料级完整枚举 6 个 `fibo.py` duplicate span（declared source 内 3 个）并稳定排序，仅允许 keep_unresolved / retain_all_exact_duplicate_spans_with_explicit_multi_span_policy（明确标记为需所有者批准的新 evidence policy，`new_evidence_policy=true`、`requires_owner_approval=true`）/ retire_case；zh-032 复核无 full/clause 级 exact 证据（仅碎片级 `异常实例`/`一起被引发`，`fragment` 标记不得误标 exact），仅允许 remove_unsupported_answer_point（删除全部未支持答案点 → 零答案点风险 true）/ retire_case / keep_unresolved；mixed-022 答案点 0 唯一 exact clause「A function returning another function」[18,55) 提供 narrow，答案点 1「装饰器」歧义（3 处）不提供；mixed-028 答案点 0 无 exact 证据，答案点 1 唯一 exact clause「state」[152,157)（react chunk，位于该 case 已有证据 scope）提供 narrow；单字元 paraphrase 碎片与歧义 full 命中不得解锁 narrow。模板仅允许 `owner_decision`/`owner_reviewer`/`owner_notes` 三个空字段。输出 7 个文件（remaining-blockers-decision-pack.jsonl、raw-source-contexts.jsonl、candidate-patch-template.jsonl、OWNER_DECISION_GUIDE.md、decision-pack-summary.json、decision-pack-report.md、manifest.json），manifest 自哈希与磁盘 SHA 一致，两次构建逐字节一致；不生成 draft-after/evidence-after/overlay/active/v2.1，不重封 split，不含 verdict/holdout/评测分数；`data-analytics:analyze-data-quality` 不可用（`Skill not found`），改用离线确定性检查；未 stage/commit/push。

- **v2.0.5 owner-authorized same-source scope repair candidate（确定性、离线）** — 新增 `scripts/corpus_v2_v205_scope_repair.py` 与 TDD 测试：不调用 LLM/API、不联网；fail-closed 校验 rescue-audit 分类（zh-037 唯一 full、7 条 clause、zh-035 ambiguous、zh-033 无候选）、输入 SHA 与 zh-033 无 chain/follow-up 依赖。动作：retire zh-033（reason 固定 `no_same_source_candidate_found_after_owner_authorized_rescue_scan`，case 150→149）；zh-037 保留原答案点并新增同 source full evidence；7 条（mixed-029、zh-023、zh-026、zh-029、zh-036、zh-054、zh-055）答案点收窄为 rescue 已验证 clause raw span 原文（zh-029 因 audit best_candidate 为 lexical 记录而采用确定性 fallback 选择），新增 `raw-codepoint-v1` evidence 并删除仅服务被替换答案点的 orphan evidence；zh-035、zh-032、mixed-022、mixed-028 保持 unresolved 并列入 `REMAINING_BLOCKERS.md`。evidence 161→159（orphan 删除 10、新增 8），新增行全部通过 strict validation。输出 13 个文件（draft/evidence before/after、reannotation-diff、retired-cases/evidence、raw-scope-additions、coordinate-validation-report、data-quality-report、REMAINING_BLOCKERS、SPLIT_RESEAL_REQUIRED、REPAIR_REPORT、manifest），manifest 固定 `revision_status=CANDIDATE`、`activation_blocked=true`、`human_reviewed=false`、`actor=OWNER_AUTHORIZED_DETERMINISTIC_SCOPE_REPAIR`。不修改 active 输入、不生成 overlay/active/v2.1、不复用历史 split/lock；`data-analytics:analyze-data-quality` 不可用（`Skill not found`），改用离线确定性检查；未 stage/commit/push。

- **v2.0.4 零答案风险 case 的同 source 证据救援扫描（只读、确定性、离线）** — 新增 `scripts/corpus_v2_same_source_rescue_audit.py` 与 TDD 测试：不调用 LLM/API、不联网；从 owner-decision-pack 动态导出 `zero_answer_point_risk=true` 的 10 条 case，校验 pack 自哈希、输入 SHA 与 case/source/chunk 一致性；只扫描 declared source 其他 chunk，跨 source 命中记录为 `out_of_scope` 不作为候选；每个候选均以 `raw-codepoint-v1` 唯一定位与 `chunk_text[start:end] == raw_span` 证明，保留 Markdown/代码/中文标点/换行。互斥分类为 full 唯一、ambiguous_duplicate、clause 唯一、lexical_related_only、无候选；建议全部 `requires_owner_authorization=true`、`auto_applicable=false`，映射为 consider_explicit_scope_expansion / consider_narrowing_after_scope_expansion / consider_retire_case / no_actionable_rescue_candidate，严禁按翻译/释义/语义相似度或关键词重合声称直接支持。输出 `same-source-rescue-results.jsonl`、`same-source-candidate-spans.jsonl`、`same-source-rescue-summary.json`、`SCOPE_RESCUE_OWNER_MATRIX.md`、`same-source-rescue-report.md`、`data-quality-report.json`、`manifest.json`（含输入/输出 SHA、自哈希、确定性重建）。本次结果：full 唯一 1 条（zh-037）、ambiguous 1 条（zh-035）、clause 唯一 7 条（mixed-029、zh-023、zh-026、zh-029、zh-036、zh-054、zh-055）、无候选 1 条（zh-033）、lexical 0 条。不扩大 scope、不修改数据、不生成 after/overlay/active 文件、不激活 candidate、不进入 v2.1；`data-analytics:analyze-data-quality` 不可用（`Skill not found`），改用离线确定性检查；未 stage/commit/push。

- **v2.0.4 十三条 evidence 内容治理决策包（只读、确定性、离线）** — 新增 `scripts/corpus_v2_owner_decision_pack.py` 与 TDD 测试：不调用 LLM/API、不联网；严格校验 v2.0.2/v2.0.3/v2.0.4 blocker 的 13 条分组与 `(case_id, chunk_id, source_id)`，程序计算原始 chunk Unicode code-point range 与 `raw-codepoint-v1` 连续性；为每条输出原 answer point、完整 scoped chunk、anchor ID/raw range、同 source 其他 chunk 的 `needs_scope_expansion` 候选（不作为当前证据）、阻断原因、六种允许动作与 `zero_answer_point_risk`。模板仅含 `owner_action`/`revised_answer_point`/`chosen_anchor_id`/`owner_note` 白名单；不生成 refusal 建议（除非原本就是 refusal）。输出 `owner-decision-pack.jsonl`、`OWNER_DECISION_GUIDE.md`、`raw-source-contexts.jsonl`、`candidate-patch-template.jsonl`、`decision-pack-summary.json`、`decision-pack-report.md`、`manifest.json`（含输入/输出 SHA、自哈希、确定性重建）。失败时清理目录；不修改任何 v2 数据、不生成 after/overlay/active 文件、不进入 v2.1；`data-analytics:analyze-data-quality` 不可用（`Skill not found`），改用离线确定性检查；未 stage/commit/push。

- **v2.0.4 Pro raw anchor 选择能力校准（只读、candidate-only）** — 新增 `scripts/corpus_v2_pro_anchor_selection_calibration.py` 与 TDD 测试：仅使用 `deepseek-v4-pro`、temperature=0.0、max_tokens=8000、thinking disabled、最多 3 次同模型重试；模型只能从本地同 scoped chunk 的 anchor catalog 选择 `anchor_id` 或报告 `no_valid_anchor`，本地严格验证 raw Unicode range、source/chunk 所属关系和 `raw-codepoint-v1` 连续性。13 条必须全部完成才原子写入校准报告；失败时清理最终目录。该诊断不生成 draft/evidence after、overlay、active metadata，不修改 v2 数据、不进入 v2.1；结果仅用于与既有 Flash BLOCKED 结果对照，未 stage/commit/push。

- **v2.0.4 owner-authorized conservative evidence/answer-point candidate** — 新增保守重标注脚本与 TDD 测试：严格校验 v2.0.2 unresolved 与 v2.0.3 blocker audit 的 13 条分组；无 scoped 证据项仅允许删除 answer point 及 orphan evidence，语义过强项和 schema-invalid 项仅允许选择本地 raw anchor，由程序生成答案点/坐标并通过 `raw-codepoint-v1` 校验。固定 `deepseek-v4-flash`、temperature=0.0、max_tokens=8000、thinking disabled；`data-analytics:analyze-data-quality` 实际不可用（`Skill not found`），改用离线确定性质量检查。任一失败 fail-closed，不写 after 文件；candidate 始终 `activation_blocked=true`、`human_reviewed=false`，不生成 overlay、不激活、不进入 v2.1，未 stage/commit/push。

- **v2.0.3 13 条重标注 blocker 根因审计（只读、确定性）** — 新增 `scripts/corpus_v2_reannotation_blocker_audit.py` 与 TDD 测试：严格校验 13 条 blocker 与 v2.0.2 unresolved 集合一致，依据 scoped raw chunk、当前 atomic anchors、答案点和本地契约错误互斥归因；输出 `blocker-audit/`，所有后续动作均 `requires_owner_authorization=true`、`auto_applicable=false`。本次归因：`scoped_chunk_evidence_absent` 2 条（zh-032、zh-033）、`answer_semantics_not_directly_supported` 8 条（mixed-022、mixed-028、mixed-029、zh-026、zh-029、zh-036、zh-054、zh-055）、`model_or_schema_action_invalid` 3 条（zh-023、zh-035、zh-037），其余类别 0；未发现可安全自动应用的范围扩展候选。未读取 split/dev/holdout，未修改输入、after 文件、overlay 或 active metadata，未 stage/commit/push。

- **v2.0.3 owner-authorized evidence 语义重标注候选（fail-closed）** — 新增 quote-free anchor 选择契约：模型仅选择本地程序从 scoped raw chunk 构造的 `anchor_id`，坐标、raw span 与 snippet 均由本地按 `raw-codepoint-v1` 计算；固定 `deepseek-v4-flash`、temperature=0.0、max_tokens=8000、thinking disabled、最多 3 次同模型重试。13 条 v2.0.2 unresolved 均进入受授权候选流程；任一 schema、模型身份、anchor、source/chunk 或 raw 重建失败则只写 blockers，不生成 `draft-after`/`evidence-after`。candidate 始终 `revision_status=CANDIDATE`、`activation_blocked=true`、`human_reviewed=false`，不生成 overlay、不激活、不进入 v2.1，未 stage/commit/push。

- **v2.0.2 quote-only Flash 建议包生成（13 条，0 条唯一 raw 锚定）** — 新增 `scripts/corpus_v2_coordinate_resolution_proposals_v2.py` 与测试：模型仅输出 `evidence_quote`/chunk 标识及语义建议，严格拒绝 `start`、`end`、`char_range` 等坐标字段；本地使用 raw Unicode code-point 唯一连续匹配计算坐标，重复、空 quote、非连续或无命中均 fail-closed 为 `keep_unresolved`。本次 13 条全部仍 unresolved，所有建议 `auto_applicable=false`、`requires_owner_authorization=true`；v2.0.2 继续 `activation_blocked=true`，未修改输入、未生成 overlay、未进入 v2.1、未 stage/commit/push。

- **v2.0.2 Flash-only 建议包 13/13 生成成功（严格 JSON + thinking 禁用，fail-closed）** — 修复根因后完整生成 13 条 unresolved 建议（`resolution-proposals/`，rule `v2.0.2-coordinate-resolution-proposals-flash-2`）：
  - **JSON 外壳问题已排除**：新增 `parse_model_json_strict()`，仅接受 BOM/外层空白、单个完整 Markdown fence 或唯一完整顶层 JSON 对象；多对象、截断、未闭合 fence、非法转义、尾随非空白与 schema/模型身份错误均抛专用 `StrictJSONParseError`，不修复内容、不猜字段、不选多候选。`--probe-json` 通过（probe 不读取 v2 case、不生成 proposal）。
  - **真正根因**：`deepseek-v4-flash` 推理模式先输出 `reasoning_content`，`max_tokens=8000`（固定）为推理+答案总预算；8/13 条 case 推理占满预算后 `finish_reason=length`、`content` 为空（响应长度 0、SHA 为空串 SHA），并非 JSON 语法错误。失败时安全诊断已记录异常类型、响应长度、响应 SHA、安全摘录与尝试次数（不含 API key/请求头）。
  - **修复**：`src/llm_gateway.llm_call` 新增 `extra_body` 可选透传（TDD：两个网关测试 + `_call` 透传测试），本脚本固定发送 `thinking: {"type": "disabled"}`（DeepSeek 官方 API 关闭推理参数，模型/温度/预算均不变）；格式错误仍同模型最多 3 次完整重试。
  - **结果**：13/13 全部通过 JSON、模型身份、schema 与 manifest 自哈希校验，0 次重试；11 条模型返回 evidence 但 start/end 沿用 legacy/display 坐标，无法在 raw chunk code-point 重建，全部 fail-closed 降级 `keep_unresolved`（`no_local_raw_evidence_case_ids` 13 条）；`root_cause_category` 从 triage 产物加载（format 2 / semantic 11）。所有建议 `LLM_ASSISTED_OWNER_DECISION_REQUIRED`、`auto_applicable=false`；v2.0.2 继续 `activation_blocked=true`，未修改任何 v2 数据/迁移产物/active 指针，未生成 overlay，未进入 v2.1，未 stage/commit/push。

- **v2.0.2 Flash-only unresolved evidence coordinate 修复建议包（fail-closed）** — 按用户授权将本任务模型固定切换为 `deepseek-v4-flash`，参数保持 `temperature=0.0`、`max_tokens=8000`，gateway 最多 3 次传输重试且不使用 fallback 或混合模型。已先执行 `--probe` 并成功校验模型身份；随后完整 13 条建议包因返回非法 JSON fail-closed 停止，最终输出目录已清理，未生成半成品。代码、manifest/report 谱系明确 Flash 批次不得与此前 Pro 结果混合比较；未修改任何 v2 数据、未生成 overlay、未激活 v2.0.2、未进入 v2.1、未 stage/commit/push。

- **v2.0.2 unresolved evidence coordinate 修复建议包（fail-closed）** — 新增 `scripts/corpus_v2_coordinate_resolution_proposals.py` 与 `tests/test_corpus_v2_coordinate_resolution_proposals.py`，实现 13 条 unresolved 的盲态、仅所有者决策建议流程：固定 `deepseek-v4-pro`、temperature=0.0、max_tokens=8000，严格校验模型身份、JSON schema 与 raw span，所有建议均 `LLM_ASSISTED_OWNER_DECISION_REQUIRED`、不可自动应用。已先执行 RED 测试并转绿；实际 gateway 调用因请求超时返回失败，按 fail-closed 规则未生成任何建议产物、manifest 或 overlay，未修改输入、未激活 v2.0.2、未进入 v2.1。\n\n- **v2.0.2 unresolved evidence coordinate 确定性可解性分流（TDD）** — 新增 `scripts/corpus_v2_evidence_unresolved_triage.py` 与 `tests/test_corpus_v2_evidence_unresolved_triage.py`，只读分析 v2.0.2 candidate 的 13 条 unresolved：`format_transform_requires_policy` 2 条（mixed-022、zh-054），`semantic_or_content_drift` 11 条（mixed-028、mixed-029、zh-023、zh-026、zh-029、zh-032、zh-033、zh-035、zh-036、zh-037、zh-055），空白可逆、重复可证明、source/chunk integrity 候选均为 0；无条目具备自动处理资格，v2.0.2 继续保持 `activation_blocked=true`。`data-analytics:analyze-data-quality` 实际加载失败（`Skill not found`），已执行等价离线完整性/唯一性/连续性/source 检查。未修改 draft、chunks、evidence、坐标迁移产物、机器审阅结果；未生成 activation metadata/overlay，未进入 v2.1，未 stage/commit/push。 — 新增 `scripts/corpus_v2_evidence_unresolved_triage.py` 与 `tests/test_corpus_v2_evidence_unresolved_triage.py`，只读分析 v2.0.2 candidate 的 13 条 unresolved：`format_transform_requires_policy` 2 条（mixed-022、zh-054），`semantic_or_content_drift` 11 条（mixed-028、mixed-029、zh-023、zh-026、zh-029、zh-032、zh-033、zh-035、zh-036、zh-037、zh-055），空白可逆、重复可证明、source/chunk integrity 候选均为 0；无条目具备自动处理资格，v2.0.2 继续保持 `activation_blocked=true`。`data-analytics:analyze-data-quality` 实际加载失败（`Skill not found`），已执行等价离线完整性/唯一性/连续性/source 检查。未修改 draft、chunks、evidence、坐标迁移产物、机器审阅结果；未生成 activation metadata/overlay，未进入 v2.1，未 stage/commit/push。

- **v2.0.2 evidence `char_range` 双轨坐标语义审计与版本化修复（TDD）** — 新增 `scripts/corpus_v2_evidence_coordinate_repair.py` 与 strict validator，并在 `evaluation/datasets/v2/revisions/v2.0.2-evidence-coordinate-repair/` 固定 `raw-codepoint-v1` 契约：原始 chunk Unicode code-point `raw_chunk_char_range` 是唯一定位锚点，`raw_evidence_span` 必须逐字重建；`snippet` 仅为保留 Markdown/代码/链接/标题/列表/标点的展示字段。旧 v2.0.1 `char_range` 仅作为 legacy 审计值，不被重新解释。data-analytics skill 实际加载失败（Skill not found），已记录原因并执行等价离线确定性质量检查；161 条中实际迁移 148 条、13 条因原 snippet 无法在原始 chunk 唯一连续回溯而 unresolved，故 v2.0.2 active 激活被 fail-closed 阻断，仅保留 candidate 版本。未修改 chunks、draft、答案点、query、case/source/chain 或机器审阅 decision；未生成 overlay、未进入 v2.1、未 stage/commit/push。

- **v2.0.1 自动审阅 37 条阻断项的确定性根因分流与修复计划（TDD：28 个新测试）** — 新增 `scripts/corpus_v2_remediation_triage.py`，以 canonical `automated-review.jsonl` 为唯一事实来源，对 37 条阻断项（20 reject + 17 needs_followup）做逐 case、逐答案点的只读确定性分流（**不调用 LLM/API、不联网、不运行检索/生成评测、不修改任何输入、不生成 overlay、不进入 v2.1**；`data-analytics:analyze-data-quality` skill 在本环境不可用，已记录原因并实施等价的确定性质量检查）：
  - **fail-closed 门禁**：canonical 统计必须恰为 113/20/17（non-confirmed=37）、issues 恰 37 条且集合严格等于 `reject ∪ needs_followup`、canonical/draft/chunks SHA 与 manifest 一致、evidence 行与 canonical evidence_summary 逐项一致且 snippet/chunk SHA 自洽——任一漂移 → `TriageError`，零输出
  - **五类互斥分流**（37 条结果）：`exact_local_evidence_available` **3**（en-031、multi-020、zh-040，机械可修复：在现有 evidence chunk 内补/扩最短逐字 span，覆盖 100%）、`partial_or_paraphrase_evidence_only` **18**（含 8 个语言不匹配答案点：中文答案点对英文源，逐字匹配不适用，需所有者核验翻译等价性）、`no_local_evidence_found` **2**（zh-045、zh-056，全部答案点无逐字证据 → 零答案点建模问题）、`refusal_label_or_schema_inconsistency` **13**（11 条 noanswer-* 的 `is_refusal_turn` 缺失/为 null、en-052 与 mixed-027 的 refusal assessment 与 `should_refuse=false` 矛盾——只列字段与值，不改标签）、`semantic_judgment_unresolved` **1**（en-034：两个答案点均已完整出现在 evidence snippet 内，阻断根因是答案点完整性——缺 L. Masinter——需语义裁决）
  - **证据规则**：归一化逐字 span（NFKC + 空白折叠 + ASCII 小写，min_span = min(8, 答案点长度)）只在相关源范围内作为修复依据，范围外命中一律 `out_of_scope_only` 且 `repair_basis=false`；`exact` 判定覆盖 ≥ 0.75；span 是否已在 evidence 内按 snippet 文本（SHA 自洽）判子串包含，不用不可靠的 char_range 切片
  - **数据质量发现**：snippet/chunk 文本 SHA 全部自洽（161/161），但 evidence `char_range` 切片与 snippet 文本完全一致仅 12/161 行（空白折叠/对齐差异），已记录为 finding 并在包含判定中规避
  - **产物**（`evaluation/datasets/v2/automated-review/remediation-triage/`）：`blocking-case-triage.jsonl`（37 行：case_id/decision/issue_id/答案点编号/类别/证据状态/候选 span/建议动作/自动修复资格/风险）、`candidate-evidence-spans.jsonl`（2791 行范围内外命中）、`remediation-summary.json`、`remediation-triage-report.md`（37 条全列、聚类、可机械修复 3 条、需所有者裁决 34 条及不得自动修复原因）、`data-quality-report.json`（完整性/唯一性/snippet 连续性/source 一致性/答案点证据覆盖）、`manifest.json`（输入输出 SHA、规则版本 v2.0.1-remediation-triage-1、确定性重建信息、声明）
  - **保证**：两次运行逐字节一致（输出路径为相对文件名，manifest 自身 SHA 为去除自引用键后的规范化序列化复算）；输入文件 SHA 不变（canonical `ea2af431…` / pack `2b888817…` / evidence `af54ff88…` / draft `3c4fd10a…` / chunks `a23d739a…`）；未读取任何历史审阅结论（源码扫描测试）；未 stage/commit/push

- **v2.0.1 自动审阅结果确定性对账与报告修正（TDD：19 个新测试）** — 新增 `scripts/corpus_v2_automated_review_reconcile.py`，以 canonical `automated-review.jsonl` 为唯一事实来源，对全部派生报告（summary / issues / gate-report / review-report / manifest）做只读确定性对账（**不调用 LLM/API、不联网、不运行检索/生成评测、不修复任何 case、不生成 overlay、不进入 v2.1**）：
  - **对账断言**：canonical 恰 150 行、case_id 唯一、每 case 恰一个合法 decision（confirmed/reject/needs_followup）、confirmed + reject + needs_followup == 150；issues JSONL case_id 集合严格等于 canonical 中 `reject ∪ needs_followup`（无重复/遗漏/额外）；summary / gate report / review report / manifest 的统计与 case 清单逐项等于 canonical 复算；报告列出的每个 case_id 属于对应 decision，不得出现"显示 17 条但列出 19 条"矛盾
  - **fail-closed**：canonical 重复 case、非法 decision、JSON 损坏或 SHA 不一致 → 立即失败且零派生产物更新；对账前后 canonical / pack / evidence SHA 必须不变；存在任意 reject / needs_followup → 严禁生成 automated overlay，gate verdict 保持阻断
  - **机械重建**：仅当 canonical 合法且 SHA 链有效时，重建派生产物（summary / issues / gate-report / review-report / manifest），只修正统计、清单和由其派生的 SHA，绝不更改任何 150 条 decision / rationale / evidence / 模型响应或审阅包内容；派生 SHA 基于实际写入后的磁盘文件（`_sha256_file`）计算，与文件字节级自洽，不因行尾符（LF/CRLF）产生漂移
  - **真实对账结果**：canonical 真值 **113 confirmed / 20 reject / 17 needs_followup**（non-confirmed = 37），**needs_followup 实为 17 条**——上一轮文字报告误列 19 条（`en-054`、`mixed-028` 在 canonical 中为 confirmed，属错误转录），仓库内全部机器可读产物与 canonical 一致；首次对账发现并修正 manifest 中 summary/report 派生 SHA 漂移（重建逻辑以磁盘文件为准重新计算，SHA 链恢复自洽）
  - **产物**（`evaluation/datasets/v2/automated-review/reconciliation/`）：`reconciliation.json`（canonical 复算计数、三类 case_id 集合、各输入 SHA、逐文件一致性）、`reconciliation-report.md`（差异说明与 canonical 真值）、`manifest.json`（输入/输出 SHA 与确定性重建信息）；两次运行逐字节一致（确定性重建）
  - **结论**：canonical 计数 113/20/17、non-confirmed=37，自动 gate 保持 **FAIL/BLOCKED**；未调用 LLM、未生成 overlay、未进入 v2.1、未 stage/commit/push（本任务规格要求）

- **v2.0.1 用户授权全量自动审阅替代人审门禁（TDD：20 个新测试）** — 新增 `scripts/corpus_v2_automated_review.py` 与 `scripts/corpus_v2_automated_review_apply.py`，以用户授权的 `LLM_ASSISTED_OWNER_AUTHORIZED` 自动审阅替代此前"必须真人审核"流程；**审阅执行者为 LLM（deepseek-v4-pro，temperature=0.0、max_tokens=8000），不代表人工审核、人工批准或生产上线批准**：
  - **治理记录**（`evaluation/datasets/v2/automated-review/AUTOMATED_REVIEW_POLICY.md`）：明确记录性质声明、授权依据、模型/参数固定值、输入边界、审阅规则、输出标识（`AUTOMATED_REVIEWED_OWNER_AUTHORIZED`）、准入门禁、数据质量等价检查、版本绑定；禁止模型 `gpt-5.6-sol`、`deepseek-v4-flash`、回退模型、联网
  - **全量独立机器审阅**：对 150 条 draft 逐条执行 deepseek-v4-pro 审阅（pack → review → verify 三阶段 CLI），输出 `automated-review-pack.jsonl`、`automated-review-evidence.jsonl`、`automated-review.jsonl`、`automated-review-summary.json`、`automated-review-report.md`、`manifest.json`；数据质量检查（`data-analytics:analyze-data-quality` skill 不可用，以确定性等价实现覆盖五维：完整性 / 唯一性 / 引用完整性 / 连续性 / 一致性）
  - **独立重新审阅五条修复 case**：`en-052`、`en-055`、`mixed-016`、`mixed-026`、`multi-014` 在本轮全量审阅中独立出现，不继承历史结论
  - **严格自动准入门禁**（`corpus_v2_automated_review_apply.py`）：150 行校验、case_id 唯一、SHA 链可复算、模型/参数/身份固定、evidence chunk 存在且连续、字符范围正确、blank human pack 未修改、产物无 `HUMAN_REVIEWED`/`HUMAN_APPROVED`/`人工审核完成`；150/150 confirmed → 生成 `automated-reviewed-truth-overlay.json` + manifest（状态 `AUTOMATED_REVIEWED_OWNER_AUTHORIZED`）；任意 reject/needs_followup → 仅生成 issues 清单和 gate report，禁止生成 overlay
  - **真实审阅结果**：113 confirmed / 20 reject / 17 needs_followup（确认率 75.3%）；37 条未通过 → **未生成 overlay**；传输重试 0、解析重试 0；五条修复 case 结论：`en-052` reject、`en-055` confirmed、`mixed-016` reject、`mixed-026` confirmed、`multi-014` confirmed
  - **fail-closed**：输入/输出 SHA 漂移、模型身份不符、非法 decision、human 标识 → 立即失败；空白 human-review pack SHA 不变且人工字段仍为空
  - **TDD 测试覆盖**：150/150 confirmed 生成 overlay、任一 reject/needs_followup 零 overlay、机器身份字段/模型/参数/SHA 漂移/证据漂移/非法 decision 均 fail-closed、原 blank human pack SHA 不变、输入不含历史 verdict/notes/cohort/split 字段、五条修复 case 在本轮出现、两次运行逐字节一致、不得出现人工审核标识

### Fixed

- **v2 持续 reject 最小证据修复（v2.0.1）+ 5 条定点机器复审（TDD：54 个新测试）** — 依据 Task 11 审计定位的候选 span，对 5 条持续 reject case（`en-052` / `en-055` / `mixed-016` / `mixed-026` / `multi-014`）实施**已批准的精确最小修复**（只改答案点及其必要的 evidence / relevant chunk 引用），并以 `deepseek-v4-pro`（temperature=0.0、max_tokens=8000，FORBIDDEN_MODELS 代码级守卫，不可用则 fail-closed 停止）对修复后 5 条做盲态机器复审；新增 `scripts/corpus_v2_persistent_reject_repair.py` 与 `scripts/corpus_v2_targeted_machine_review.py`：
  - **五条精确变换**（before → after）：`multi-014` 答案点不变，按审计定位的教程 6.4.1 / `chunk_38` 精确 span（字符 321..359「from package import specific_submodule」，snippet 覆盖「这种方式是推荐用法」，答案点覆盖 89.7%）补入本地证据与 chunk 引用；`mixed-026` 删除无本地证据的子结论「计算器、字符串、列表示例」（保留已支持的章节标题对应结论）；`en-052` 删除 unsupported 子结论「Rust: ownership rules guarantee memory safety」（保留 PostgreSQL durability，不编造替代表述）；`en-055` 收窄为证据等价的英文表述「The `&` operator creates a reference (e.g., `&s1`)」（rust `chunk_49` 字符 1424..1467「The `&s1` syntax lets us create a reference」直接支撑，删除无证据的 `&` 声称）；`mixed-016` 收窄为术语表形式「argument — 参数；parameter — 形参」并为 parameter 补入术语表 `chunk_14` 证据（字符 783..798「parameter -- 形参」）
  - **fail-closed 契约**：持续 reject 集合必须恰为目标 5 条（merged + selection-manifest 复算）；Task 11 审计 manifest 输入 SHA 漂移（merged / selection-manifest / chunks / 空白 pack）、行数/唯一性漂移、目标缺失、证据 chunk 缺失、source 不一致、snippet 不连续、core 字符范围偏移、既有证据复核失败 → 一律失败且不产出；字段守恒（case_id / chain_id / follow_up_to / query / should_refuse / language / query_type / difficulty / relevant_source_ids 与 split 归属不变）；其余 145 条草稿行**逐字节不变**（字节级重建）
  - **版本化修复目录**（`evaluation/datasets/v2/revisions/v2.0.1-persistent-reject-repair/`）：修复前字节快照 `draft-before.jsonl`（e289d1f0…）、修复后 `draft-after.jsonl`（3c4fd10a…，与草稿原位更新后 SHA 一致）、`draft-field-diff.jsonl`（5 条逐字段 before/after + 变更理由）、`evidence-verification.jsonl`（新增 3 条证据的 chunk/source/snippet SHA/字符范围/core 定位）、`pack-before.jsonl`（旧空白 pack 字节，SHA ceab0070… 与审计 manifest 交叉一致）、`data-quality-report.json`、`freeze-lock-verification.json`、`persistent-reject-repair.md`、`manifest.json`；不覆盖历史审计目录
  - **派生与封印**：空白 human-review pack 重新生成（150 行、三个人工字段仍全空、既有 pack fail-closed 校验通过、145 行与旧 pack 逐行一致）；case-freeze / split-lock 复算通过（case 集合、freeze 指纹、5 条目标的分层元数据不变，`verify_lock` 为 true，无需更新历史 lock）；chunks.jsonl、原始第三轮填写副本、历史语义仲裁/审计产物均未修改
  - **数据质量校验**（`data-analytics:analyze-data-quality` 技能在本环境不可用，按任务要求以确定性的等价实现覆盖其五维：完整性 / 唯一性 / 引用完整性 / 连续性 / 一致性）：全部答案点有证据、无重复 chunk/答案点、chunk 引用与 chunk_id 列表一致、snippet 全部连续、source 全部一致、逐 case 语义对应（multi-014 core 逐字 ∈ 答案点、en-055 `&`/reference/create 语义 token、mixed-016 两个术语在对应证据中）
  - **5 条定点机器复审**（`evaluation/datasets/v2/targeted-post-repair-machine-review/`）：盲态输入仅含 query / previous_turns（仅 query 文本）/ should_refuse / 修复后答案点 / evidence / 完整 scoped chunks，不传 case_id、历史 decision、第三轮 notes、cohort、split 或任何「持续 reject」标签与预期 verdict（代码级泄漏扫描）；复用语义仲裁 JSON 契约与 coherence validator（support index 连续唯一、verdict 映射一致）；逐条保留 prompt SHA / 响应 SHA / 原始响应 / 解析与传输重试记录；**真实结果：5/5 confirmed（0 transport retry、0 parse retry）**——含 `multi-014` 答案点 2 获 `direct_snippet`（chunk_38）支持（此前 v4 Pro 因证据截断判 unsupported）；任何一条 reject / needs_followup / 无效 JSON / coherence 违规 → 输出诊断报告并停止、不生成任何 overlay
  - **结论**：本修复为机械、确定性修改（依据审计证据），机器复审为 **MACHINE_REVIEWED_DIAGNOSTIC_ONLY** 诊断证据；**均不代表人工终审、人工批准或 v2.1 准入**；未生成任何 truth overlay；未暂存、未提交、未 push（本任务规格要求）

- **v2 持续 reject case 本地证据可修复性审计（TDD：48 个新测试）** — 新增 `scripts/corpus_v2_persistent_reject_audit.py`，对合并后 102 条中唯一 5 条**持续 reject**（第三轮 reject 且 v4 Pro reject：`en-052` / `en-055` / `mixed-016` / `mixed-026` / `multi-014`）做逐答案点**本地证据可修复性**审计；**不调用任何 LLM/API、不联网、不运行检索/生成评测、不读取 split/dev/holdout**；只读 4 个允许文件（merged-adjudications.jsonl / selection-manifest.json / human-review-pack.jsonl / chunks.jsonl），不修改任何 draft、human pack、chunks、审阅产物或生产配置，不生成 overlay：
  - **fail-closed 输入契约**：merged 行数 == selection-manifest mapping（index 连续唯一）、**merged reject 集合 == 目标 5 条**、目标 ∈ disputed（第三轮 reject 事实）、pack 行数 == 150 且覆盖目标、chunk_id 唯一、evidence chunk 存在、supports index 覆盖全部答案点；任何漂移 → 零输出
  - **机械判定规则**（确定性、无 LLM）：答案点归一化（NFKC + 空白折叠 + ASCII 小写，带原始偏移映射）后在 `relevant_source_ids` 全文 chunks 中收集互不重叠的最长逐字匹配段（贪心锚点 + 双向扩展 + 边界空白修剪）；span 覆盖 ≥ 75% → `exact_local_evidence_available`，≥ 8 字符 → `only_paraphrase_or_partial_evidence`，否则 → `no_local_evidence_found`；候选 span 带 chunk_id / source_id / chunk 内字符范围 / 最短必要原文 / match_type（full/clause/partial）；范围外文档命中单独标 `out_of_scope_only`，**不得作为修复依据**；CJK 答案点 vs 非 CJK 源文档（或反向）→ `language_mismatch`，逐字匹配不适用
  - **proposed_action 约束**（只有候选原文能直接支撑拟议后的完整答案点才允许）：exact 且不在当前 evidence snippet → `add_exact_evidence`；exact 但已在 snippet → `manual`（evidence_already_present）；partial 且至少一个完整子句逐字出现 → `narrow_answer_point`；partial 无完整子句 / 语言不匹配 / 仅范围外 → `manual_semantic_adjudication_required`；相关源内无任何逐字证据 → `remove_unsupported_answer_point`（机械建议）；已被 v4 Pro 判 supported 的答案点不属于修复范围 → `manual`（point_already_supported）
  - **真实结果**（9 个答案点，其中 v4 Pro 判 unsupported 5 个）：`multi-014` 答案点 2 **exact + add_exact_evidence**（教程 6.4 节 chunk_38 原文「使用 `from package import specific_submodule` 没有任何问题！…这种方式是推荐用法」，38/43 字符逐字，v4 Pro 因 evidence snippet 截断未覆盖 6.4 节而判 unsupported）；`en-055` 答案点 1 中文 vs 英文文档 → `language_mismatch` → manual；`mixed-026` 答案点 2 相关源内无逐字证据且范围外无命中 → `remove_unsupported_answer_point` 建议；`en-052` 答案点 2（ownership rules / memory safety 分散支撑）与 `mixed-016` 答案点 2（原文仅有条目标题 `argument -- 参数` / `parameter -- 形参` 的改写关系）→ partial → manual；4 个 supported 点均不在修复范围；汇总 1 exact / 5 partial / 3 none
  - **第三轮 reject 理由如实记录为不可用**：位于 llm-filled pack / third-pass report，不在本任务允许读取范围；第三轮 decision=reject 已由 selection-manifest.disputed 集合确认
  - **产物**（`evaluation/datasets/v2/persistent-reject-evidence-audit/`）：`persistent-reject-cases.jsonl`（5 行：query / relevant sources / current evidence / v4 Pro 理由 / 逐答案点分类与建议）、`candidate-evidence-spans.jsonl`（432 条：范围内 82 + 范围外 350）、`repair-feasibility-summary.json`、`persistent-reject-evidence-audit.md`、`manifest.json`（输入输出 SHA-256 链 + 行数 + 阈值 + fail-closed 校验记录）；确定性（两次运行逐字节一致）、无时间戳
  - **结论**：本审计是**证据可修复性分析，不代表自动修复、人工审核或 v2.1 准入**；`add_exact_evidence` / `remove_unsupported_answer_point` 等为机械建议，采纳与否须人工裁决；未暂存、未提交、未 push（本任务规格要求）

- **DeepSeek v4 Pro 盲态语义审阅一致性校验与定点重审（TDD：53 个新测试）** — 新增 `scripts/corpus_v2_llm_semantic_coherence.py`，对全部 102 条盲态仲裁输出做**只读一致性审计**并对违反契约的 case 定点重审；仅使用 `deepseek-v4-pro`（FORBIDDEN_MODELS 代码级守卫，复用 `corpus_v2_llm_semantic_adjudication.py` 的解析/比较/manifest 工具）；**不联网、不运行检索/生成评测、特征/阈值扫描，不读取 split/dev/holdout**；不修改任何 150 条标注、blank/filled pack、chunks、draft、manifest 或生产配置：
  - **纯函数 `validate_semantic_coherence(input_case, adjudication)`**（fail-closed 契约）：拒答题 no_answer / partial_topic_overlap_only → 必须 confirmed；substantive_answer_exists → 必须 reject；unclear → 必须 needs_followup；answer_point_supports 必须为空；可答题每个答案点必须恰好一条 assessment、index 连续不重复；存在 unsupported → 不得 confirmed；全部非 unsupported → 不得 reject；needs_followup 必须写明「无法判断」理由；每条必须有合法 verdict、非空 rationale、reviewer 模型名与原盲态输入 index
  - **只读审计**（`coherence-audit.json` + `coherence-report.md`）：盲包确定性重建必须与现有 `blind-input-pack.jsonl` 逐行一致、selection-manifest mapping 与复算顺序一致、仲裁 102 行 index 连续唯一，全部校验通过才写审计产物；列出全部违反 case、具体违反规则、原模型输出；**真实结果 4 条违规**（不是只有 noanswer-052）：`supports_index_not_contiguous` × 3（en-047 / mixed-028 / mixed-029，同一答案点多条 assessment）+ `refusal_assessment_mismatch` × 1（noanswer-052，no_answer 却判 reject）
  - **定点重审**（相同盲态输入、同一模型、temperature=0.0、最多 3 次；提示词显式包含 verdict 与 support/refusal 映射规则）：每次 attempt 都是完整新调用；输出须同时通过结构解析与一致性契约；**不允许代码自行把 reject 改为 confirmed**，唯一允许的代码改写是 3 次失败后按规则固定为 needs_followup（记录失败证据）；真实运行 4 个违规 case 全部第 1 次重审通过（0 transport retry、0 unparseable、fixed_needs_followup 空）
  - **合并与重算**（`coherence-recheck/`）：原始 `deepseek-v4-pro-adjudications.jsonl` 未改写（SHA 不变）；`rechecks.jsonl`（每 case attempts + raw_content 失败证据 + final）、`merged-adjudications.jsonl`（102 行，source=original/recheck，非固定行全部通过契约）、`comparison-report.md`（重算 82 条争议：**5 一致 / 77 不一致 / 0 不确定**，6.1% / 93.9%；20 对照仍 20/20 confirmed）、`manifest.json`（双 prompt SHA、输入/输出 SHA-256、重试统计、前后差异 changed 列表、provider_note 谱系限制）
  - **fail-closed**：盲包/选择清单/仲裁覆盖漂移、审计产物与复算不一致、合并行违反契约、模型身份漂移 → 立即失败且不产出合并/比较结论；SHA 链复算全部一致（4 个输出 + manifest self-sha + audit 文件）；确定性重建
  - **结论**：本任务仍是机器审阅，**不得视为人工终审、人工批准或上线批准，不构成任何 v2.1 进入决策**；未生成 overlay、未修复任何 case、未暂存/提交/push（本任务规格要求）

- **v2 第三轮审阅分歧全盲语义仲裁（DeepSeek v4 Pro，TDD：53 个新测试）** — 新增 `scripts/corpus_v2_llm_semantic_adjudication.py`，对第三轮 82 条 reject 做**盲态**机器语义仲裁：从 68 条 confirmed 中以 `sha256("v2-semantic-adjudication-v1:" + case_id)` 升序排序确定性抽取 20 条隐藏对照，与 82 条争议合并为 102 条盲态输入；仅使用 `deepseek-v4-pro`（FORBIDDEN_MODELS 代码级守卫 `gpt-5.6-sol` / `deepseek-v4-flash`；`deepseek-v4-flash` 探针被端点拒绝）；**不联网、不运行检索/生成评测、特征/阈值扫描，不读取 split/dev/holdout、旧 auto-review、repair ledger、第三轮 report、分歧审计结论**：
  - **盲态性**（fail-closed）：模型输入每条仅含 query / previous_turns（剥离链引用 case_id）/ should_refuse / acceptable_answer_points / evidence / 按需解析的本地 chunks 原文；不含 case_id、decision、reviewer、notes、repair、cohort 或任何历史结论（结构键 + 高信号子串双重扫描）；20 条对照清单只保存在审计侧 `selection-manifest.json`，绝不进入模型输入
  - **输入校验**（复用 hra 共享函数）：blank / llm-filled 各 150 行、case_id 集合一致、除三个人工字段外逐行一致、decision 分布必须 68/82/0、reviewer 必须 `LLM_ASSISTED_` 前缀、证据映射（chunk 存在 / snippet 连续 / source 一致）有效；任何漂移 → 零产物
  - **模型输出契约**：`semantic_verdict`（confirmed/reject/needs_followup）+ `verdict_rationale`；可答题逐答案点 `support_level`（direct_snippet / within_chunk_outside_snippet / faithful_paraphrase / unsupported）+ chunk_id + 最短必要原文摘录（同一答案点允许跨 chunk 多条支持；unsupported 允许空 chunk_id）；拒答题 `refusal_assessment`（no_answer / partial_topic_overlap_only / substantive_answer_exists / unclear）+ 支持 chunk 与摘录；跨分支多余字段先验证枚举/结构合法再归一化忽略；解析失败最多 2 次纠正性重试，仍失败即中止（含原始输出诊断）；模型身份漂移（resp.model ≠ 请求模型）立即失败
  - **真实运行**（102 条，temperature=0.0，max_tokens=8000）：**95 confirmed / 7 reject / 0 needs_followup**；82 条争议中 7 条一致（reject）/ 75 条不一致（confirmed）/ 0 不确定（8.5% / 91.5%）；20 条隐藏对照 **20/20 confirmed**（100% 控制组一致）；分层：答案题争议 67（一致 6 / 不一致 61）、拒答题 15（1/14）、跨文档题 28（3/25）；答案点支持级别：direct_snippet 79 / within_chunk_outside_snippet 7 / faithful_paraphrase 38 / unsupported 6（共 130 条）；拒答评估全部 no_answer（19/19）；解析重试 0 次、传输重试 1 次
  - **排障记录**：max_tokens=3000 时 `deepseek-v4-pro` 将预算全部消耗在隐藏推理（finish_reason=length、可见输出为空或 JSON 截断），提高到 8000 后全部正常（实测 8000 与 16000 同结果）
  - **产物**（`evaluation/datasets/v2/llm-semantic-adjudication/`）：`blind-input-pack.jsonl`（102 行、6 字段白名单）、`deepseek-v4-pro-adjudications.jsonl`（102 行、index 全覆盖、枚举合法、每条有理由、记录 model/retries）、`selection-manifest.json`（20 对照 + 82 争议 + index↔case_id↔role 映射，审计侧）、`comparison-report.md`（复算 + 争议/对照/分层 + 支持级别 + 谱系限制 + 结论）、`manifest.json`（reviewer_model / temperature / max_tokens / prompt_sha256 / 输入输出 SHA-256 / 选择算法与计数 / 重试统计 / provider_note）；确定性、无时间戳；5 个输出 SHA-256 复算全部一致
  - **谱系限制**（按规格记录）：本轮与此前 deepseek-chat 同属 DeepSeek 提供方；第三轮模型身份未被历史 manifest 记录；**不宣称模型或供应商独立性**
  - **结论**：本报告仅提供机器语义仲裁证据，**不得视为人工终审、人工批准或上线批准，不构成任何 v2.1 进入决策**；未修改任何 150 条标注、未生成 overlay；未暂存、未提交、未 push（本任务规格要求）

- **v2 第三轮机器审阅分歧只读根因审计（TDD：28 个新测试）** — 新增 `scripts/corpus_v2_llm_third_pass_audit.py`（audit 子命令），对 68 confirmed / 82 reject / 0 needs_followup 分歧做**只读**结构化诊断；只读取 blank pack / llm-filled pack / third-pass manifest / third-pass report / chunks.jsonl 五个文件，**不调用任何 LLM/API**、不联网、不运行检索、生成评测、特征/阈值扫描、不读取任何 split/dev/holdout 文件：
  - **复用共享校验**（不复制）：`corpus_v2_human_review_apply.py` 新增 `_blank_errors` / `_filled_errors` / `_llm_filled_extra_errors` 三个共享函数（150 行、id 集合一致、除三字段外逐行一致、decision/reviewer/notes 契约），`corpus_v2_llm_review_apply.py` 的 apply 改用之（行为不变，原 69 测试保持绿）；audit 再叠加证据映射复验与 `_llm_meta_errors`（第三轮统计与 manifest/report 必须一致，否则零输出）
  - **确定性诊断字段**（每条 reject）：`diagnostic_category`（六类）、`mechanical_evidence_integrity`（ok/broken）、`answer_point_verbatim_coverage`（答案点归一化后对 snippet 的逐字覆盖）、`refusal_reasoning_type`（keyword_overlap_only / substantive 等）、`requires_semantic_adjudication`
  - **真实根因结构**（82 条 reject）：`answer_point_not_verbatim_in_snippet` 39 条 + `cross_document_coverage_gap` 28 条 + `refusal_keyword_overlap_only` 15 条；答案题 67 条中 66 条答案点 0/n 逐字、1 条 1/3（"答案点不在 snippet"断言 67/67 机械成立）；其中 **3 条答案点存在于证据 chunk 全文但不在 snippet**（证据截取边界现象）；拒答题 15 条全部为关键词重合模板；拒答题 reject 15/31（48.4%）、跨文档题 reject 28/30（93.3%）；**82 条全部 requires_semantic_adjudication=True**（文本事实可机械确认，但任何一条的最终裁决都超出确定性文本校验）
  - **产物**（`evaluation/datasets/v2/llm-third-pass-audit/`）：`disagreement-cases.jsonl`（82 条，键白名单）、`summary.json`（复算 68/82/0 + 按 should_refuse/query_type/language 汇总 + 拒答题与跨文档题 + 机械/语义裁决统计 + 谱系限制）、`disagreement-audit.md`、`manifest.json`（输入输出 SHA-256 与行数、决定分布）；确定性（两次运行逐字节一致）、无时间戳、不含 split 身份/评测分数/上线结论
  - **谱系限制**：third-pass manifest 未声明输入/输出 SHA 字段——审计只能校验其计数与报告统计一致性，无法验证第三轮生成链完整性（已在产物中如实记录）
  - **结论**：本审计不判定第三轮或此前审阅孰对，不改动任何数据，不生成 overlay，不解除 v2.1 人工门槛；未暂存、未提交、未 push（本任务规格要求）

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
