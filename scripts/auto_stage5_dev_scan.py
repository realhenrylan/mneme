"""阶段5：development retrieval alpha 网格自动选 alpha + locked-config。

使用方法（需先准备：自动 overlay + prepare_index 完成的运行）::
    python scripts/auto_stage5_dev_scan.py <RUN_ROOT>
其中 RUN_ROOT 为 ../results/graph-gate/auto-run-<ts>，已包含 auto-reviewed-truth
目录。

步骤：
1. 调 compare main(--phase retrieval, --split development, alpha-grid=6 值,
   A/B/C, --reviewed-truth overlay) 生成 dev 扫描结果。
2. 读取 summary.json per-arm（graph_rerank 在 graph_target 切片下 context_recall）
   按 §4.4 决策：α* = max graph_target recall；差距 <1pp → 更高 α；
   候选相对 B context_precision 降低 >2pp → 淘汰。仅保留 / 唯一入选 α。
3. 用 build_locked_config 与 index/kG 指纹生成 locked-config.json（--lock 路径）。
   指纹在 prepare_index 后实测，不读 holdout。
4. 输出 alpha-selection.json + locked-config.json + 失肘证据日志。

由于阶段4的 smoke 已经做完 prepare_index，本阶段调 main（分别跑 retrieval 网格）。
为节省 LLM 调用（QueryPlan 缓存对每 case 仅 1 次），main 会按需重跑 query plan 估计。
本脚本只做编排与决策。
"""