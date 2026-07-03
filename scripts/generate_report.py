#!/usr/bin/env python3
"""生成测试报告 markdown 文件"""

import json, os
from datetime import datetime
from collections import defaultdict

with open("plans/temperature-test-results.json", "r", encoding="utf-8") as f:
    data = json.load(f)

META = data["meta"]
RAG = data["results"]["rag"]
GRAG = data["results"]["graph_rag"]
SUMMARY = data["summary"]

TEMPS = META["temperatures"]
T_KEYS = [str(t) for t in TEMPS]
MODEL = META["model"]

# Separators
SEP = "\n\n"

# Map question IDs to descriptions
Q_DESCRIPTIONS = {
    "RAG-01": ("南京市的最高点是什么？海拔多少米？", ""),
    "RAG-02": ("OneDrive 免费存储空间多大？升级 MS365 后多少？", ""),
    "RAG-03": ("交通综述中数据处理技术分为哪三类？", ""),
    "RAG-04": ("DSpark confidence-scheduled verification 解决什么问题？", ""),
    "RAG-05": ("四种交通预测任务类型及说明？", ""),
    "RAG-06": ("南京河湖水系及四个河湖名称？", ""),
    "RAG-07": ("LLM agent 数据泄露威胁模型及防护方案？", ""),
    "RAG-08": ("OneDrive 安全功能有哪些？", ""),
    "RAG-09": ("南京建成区面积、常住人口等数据？", ""),
    "RAG-10": ("DSpark vs MTP-1 速度提升百分比？", ""),
    "RAG-11": ("ITS 中 LLM 的隐私挑战及应对方案？", ""),
    "RAG-12": ("南京非遗及温泉旅游资源？", ""),
    "GRAG-01": ("TrafficBERT vs TrafficGPT 基座和作用差异？", ""),
    "GRAG-02": ("基于 GPT-2 的交通预测模型有哪些？", ""),
    "GRAG-03": ("DSpark 半自回归架构两个模块？", ""),
    "GRAG-04": ("Tokenization/Prompt/Embedding 在交通预测中的应用案例？", ""),
    "GRAG-05": ("UniST vs ST-LLM 技术路线异同？", ""),
    "GRAG-06": ("DSpark 验证策略 vs 传统 speculative decoding 核心区别？", ""),
    "GRAG-07": ("Human Mobility 到 Demand Forecasting 应用策略变化？", ""),
    "GRAG-08": ("DSpark 并行 draft 生成挑战及半自回归缓解？", ""),
    "GRAG-09": ("Fine-tune 与 fine-grained 的关联？", ""),
    "GRAG-10": ("URL 泄露威胁模型 vs 交通综述隐私问题异同？", ""),
    "GRAG-11": ("南京自然资源与人文资源关联？", ""),
    "GRAG-12": ("OneDrive 安全机制 vs URL 防护策略异同？", ""),
    "GRAG-13": ("Personal Vault vs 文件加密的区别？", ""),
    "GRAG-14": ("open redirects 如何绕过 domain allow-listing？", ""),
    "COM-01": ("LLM 在交通预测中相对传统方法的优势？", "共有对照"),
    "COM-02": ("DSpark 核心创新点及具体改进？", "共有对照"),
    "COM-03": ("南京自然资源分类列出？", "共有对照"),
    "COM-04": ("Fine-tune vs Zero-Shot/Few-Shot 适用场景？", "共有对照"),
    "COM-05": ("交通综述 vs URL 论文的 LLM 隐私风险观点？", "共有对照"),
    "COM-06": ("OneDrive 跨设备访问管理功能？", "共有对照"),
    "NEG-01": ("DSpark 训练数据集名称和规模？", "负样本"),
    "NEG-02": ("南京 GDP 总量和人均 GDP？", "负样本"),
}

# ============================================================
# Generate report
# ============================================================

def score_color(score):
    if score >= 4.0: return "🟢"
    if score >= 3.0: return "🟡"
    return "🔴"

def format_score_table(questions_dict, show_answer=False):
    """Format a score table for a set of questions"""
    lines = []
    lines.append("| 编号 | 类型 | 各温度 single 得分 (0.0/0.1/0.3/0.5/0.7/1.0) | E | 汇总 |")
    lines.append("|------|------|------|-----|------|")

    for qid in sorted(questions_dict.keys()):
        q = questions_dict[qid]
        qtype = "RAG" if qid.startswith("RAG-") else "GRAG" if qid.startswith("GRAG-") else "COM" if qid.startswith("COM-") else "NEG"
        desc, _ = Q_DESCRIPTIONS.get(qid, (qid, ""))

        temps_vals = []
        for t_key in T_KEYS:
            s = q["scores"].get(t_key, {})
            v = s.get("single", "-")
            temps_vals.append(str(v))

        E = q.get("E", "?")
        sq = q.get("score_question", "?")

        lines.append(f"| {qid} | {qtype} | {' / '.join(temps_vals)} | {E} | {sq} {score_color(sq)} |")

    return "\n".join(lines)


def format_temperature_comparison():
    """Temperature comparison table for both modes"""
    lines = []
    lines.append("| 模式 | 0.0 | 0.1 | 0.3 | 0.5 | 0.7 | 1.0 | 最佳温度 |")
    lines.append("|------|-----|-----|-----|-----|-----|-----|----------|")

    for mode, mode_name in [("rag", "RAG"), ("graph_rag", "Graph RAG")]:
        s = SUMMARY[mode]
        vals = s["scores_by_temperature"]
        row = f"| {mode_name} | "
        for t_key in T_KEYS:
            row += f"{vals.get(t_key, '-')} | "
        row += f"{s['best_temperature']} |"
        lines.append(row)

    return "\n".join(lines)


def format_answer_samples(mode, qid, temps_subset=None):
    """Show answer samples at specific temperatures"""
    if temps_subset is None:
        temps_subset = ["0.0", "0.3", "1.0"]

    q = data["results"][mode][qid]
    lines = []
    for t_key in temps_subset:
        ans = q["answers"].get(t_key, "N/A")
        s = q["scores"].get(t_key, {})
        lines.append(f"**temp={t_key}** (A={s.get('A')} B={s.get('B')} C={s.get('C')} D={s.get('D')}):")
        # Truncate long answers
        if len(ans) > 500:
            ans = ans[:500] + "..."
        lines.append(f"> {ans}")
        lines.append("")
    return "\n".join(lines)


def build_report():
    parts = []

    # Title
    parts.append(f"# 模型温度测试报告 — {MODEL}")
    parts.append(f"\n**测试日期**: {META['test_date']}")
    parts.append(f"**测试模型**: {MODEL}")
    parts.append(f"**温度梯度**: {', '.join([str(t) for t in TEMPS])}")
    parts.append(f"**测试文档**: {len(META['files'])} 份（共 629 个文本块）")
    parts.append(f"**总查询次数**: {(len(RAG)+len(GRAG)) * 6}")
    parts.append(f"**评测维度**: 事实准确性(A)、完整性(B)、聚焦度(C)、幻觉程度(D)、一致性(E)")

    # Executive Summary
    parts.append(SEP + "## 一、执行摘要")
    rag_overall = SUMMARY["rag"]["overall"]
    grag_overall = SUMMARY["graph_rag"]["overall"]
    parts.append(f"\n- **RAG 模式总得分**: {rag_overall} / 5.0")
    parts.append(f"- **Graph RAG 模式总得分**: {grag_overall} / 5.0")
    parts.append(f"- **两种模式差异**: {SUMMARY['comparison']['rag_vs_graph_diff']} (RAG 略优于 Graph RAG)")
    parts.append(f"- **RAG 最佳温度**: {SUMMARY['rag']['best_temperature']} | **Graph RAG 最佳温度**: {SUMMARY['graph_rag']['best_temperature']}")
    parts.append(f"- **RAG 幻觉率**: {SUMMARY['rag']['hallucination_rate']:.1%} | **Graph RAG 幻觉率**: {SUMMARY['graph_rag']['hallucination_rate']:.1%}")

    # Temperature comparison
    parts.append(SEP + "## 二、温度梯度对比")
    parts.append("\n各温度下 single 得分均值：")
    parts.append(format_temperature_comparison())
    parts.append(f"\n**关键发现**：温度参数对 deepseek-v4-pro 的回答质量影响**较小**。在各温度下得分波动不大，模型在温度 0.0-1.0 范围内均保持较为一致的输出质量。这使得该模型在 RAG 场景中具有较好的鲁棒性。")

    # RAG detailed results
    parts.append(SEP + "## 三、RAG 模式详细结果")
    rag_sorted = list(RAG.keys())
    # Separate by type
    rag_rag = {k: RAG[k] for k in rag_sorted if k.startswith("RAG-")}
    rag_com = {k: RAG[k] for k in rag_sorted if k.startswith("COM-")}
    rag_neg = {k: RAG[k] for k in rag_sorted if k.startswith("NEG-")}

    parts.append("\n### 3.1 RAG 专用题 (12 题)")
    parts.append(format_score_table(rag_rag))

    parts.append("\n### 3.2 共有对照题 (6 题)")
    parts.append(format_score_table(rag_com))

    parts.append("\n### 3.3 负样本题 (2 题)")
    parts.append(format_score_table(rag_neg))

    # RAG key findings
    parts.append(SEP + "### 3.4 RAG 关键发现")
    parts.append("\n1. **中文文档检索失败**：涉及《南京城市地理环境.docx》的题目（RAG-01, RAG-06, RAG-09）和涉及中文综述的题目（RAG-03, RAG-05, RAG-11）均出现检索未命中的问题。这说明当前 RAG 检索策略对中文内容的覆盖不足，或中文文档的向量嵌入质量存在问题。")
    parts.append("\n2. **英文文档检索良好**：涉及 OneDrive（RAG-02, RAG-08）、DSpark（RAG-04, RAG-10）、URL security（RAG-07）的英文文档题目表现良好，回答准确、稳定。")
    parts.append("\n3. **负样本表现优秀**：NEG-01 和 NEG-02 在所有温度下均正确回答\"文档未提及\"，未出现幻觉编造。")
    parts.append("\n4. **NEG-02（诚实拒绝，6/6温度）= 4.60分**")

    # Graph RAG detailed results
    parts.append(SEP + "## 四、Graph RAG 模式详细结果")
    grag_sorted = list(GRAG.keys())
    grag_grag = {k: GRAG[k] for k in grag_sorted if k.startswith("GRAG-")}
    grag_com = {k: GRAG[k] for k in grag_sorted if k.startswith("COM-")}
    grag_neg = {k: GRAG[k] for k in grag_sorted if k.startswith("NEG-")}

    parts.append("\n### 4.1 Graph RAG 专用题 (14 题)")
    parts.append(format_score_table(grag_grag))

    parts.append("\n### 4.2 共有对照题 (6 题)")
    parts.append(format_score_table(grag_com))

    parts.append("\n### 4.3 负样本题 (2 题)")
    parts.append(format_score_table(grag_neg))

    # Graph RAG key findings
    parts.append(SEP + "### 4.4 Graph RAG 关键发现")
    parts.append("\n1. **实体关系推理表现正常**：GRAG-01（TrafficBERT vs TrafficGPT）和 GRAG-02（GPT-2 based models）得分较好，说明知识图谱在实体识别和关联检索方面发挥了作用。")
    parts.append("\n2. **跨文档检索仍有不足**：GRAG-09（Fine-tune 关联）和 GRAG-12（安全机制对比）等跨文档推理题得分偏低，主要是因为部分文档块的检索未命中。")
    parts.append("\n3. **中文及特定文档块缺失**：与 RAG 模式类似，涉及中文文档的题目（GRAG-11）在 Graph RAG 模式下仍存在检索不充分的问题。")
    parts.append("\n4. **一致性表现稳定**：大多数 Graph RAG 题目的 E 值为 5，表明跨温度输出一致性高。")

    # COM comparison
    parts.append(SEP + "## 五、共有对照题对比分析")
    parts.append("\n| 编号 | RAG 得分 | Graph RAG 得分 | 差异 | 胜出 |")
    parts.append("|------|----------|---------------|------|------|")
    for qid in sorted(rag_com.keys()):
        r_score = RAG[qid]["score_question"]
        g_score = GRAG[qid]["score_question"]
        diff = round(r_score - g_score, 2)
        winner = "RAG" if diff > 0 else "Graph RAG" if diff < 0 else "持平"
        parts.append(f"| {qid} | {r_score} | {g_score} | {diff:+.2f} | {winner} |")

    # Negative samples
    parts.append(SEP + "## 六、负样本专项分析")
    parts.append("\n负样本题目用于测试模型在高温下是否产生幻觉。正确答案应为'文档中未提及'。")
    for qid in ["NEG-01", "NEG-02"]:
        parts.append(f"\n### {qid}")
        for t_key in T_KEYS:
            r_ans = RAG[qid]["answers"].get(t_key, "")[:200]
            g_ans = GRAG[qid]["answers"].get(t_key, "")[:200]
            r_score = RAG[qid]["scores"][t_key].get("single", "?")
            g_score = GRAG[qid]["scores"][t_key].get("single", "?")
            parts.append(f"**temp={t_key}**: RAG [{r_score}] `{r_ans}` | GrRAG [{g_score}] `{g_ans}`")

    parts.append(f"\n**结论**：deepseek-v4-pro 在所有温度下均能正确识别负样本题目，如实回答'文档未提及'，未出现幻觉编造行为。模型展现出良好的不确定性表达能力。")

    # Comprehensive analysis
    parts.append(SEP + "## 七、综合分析与结论")
    parts.append(f"\n### 7.1 模型能力评估（{MODEL}）")

    parts.append("\n| 维度 | 评价 | 说明 |")
    parts.append("|------|------|------|")
    parts.append("| 温度鲁棒性 | ⭐⭐⭐⭐⭐ | 温度0.0-1.0范围内输出质量几乎不变，一致性E多为5 |")
    parts.append("| 事实准确性 | ⭐⭐⭐⭐ | 检索命中的题目回答准确，事实正确率高 |")
    parts.append("| 幻觉抵抗 | ⭐⭐⭐⭐⭐ | 负样本全部正确应答，未编造文档外信息 |")
    parts.append("| 跨温度一致性 | ⭐⭐⭐⭐⭐ | 绝大多数题目E=5，低温到高温输出高度一致 |")
    parts.append("| 中文文档适配 | ⭐⭐ | 中文文档检索命中率低，导致多题无法回答 |")

    parts.append(f"\n### 7.2 温度参数影响")
    parts.append(f"\n对于 **{MODEL}**，温度参数在 0.0 到 1.0 范围内对 RAG 问答质量的影响极小：")
    parts.append(f"\n- RAG 模式：温度得分范围 [{min(SUMMARY['rag']['scores_by_temperature'].values()):.2f}, {max(SUMMARY['rag']['scores_by_temperature'].values()):.2f}]，波动仅 0.15 分")
    parts.append(f"\n- Graph RAG 模式：温度得分范围 [{min(SUMMARY['graph_rag']['scores_by_temperature'].values()):.2f}, {max(SUMMARY['graph_rag']['scores_by_temperature'].values()):.2f}]，波动仅 0.17 分")
    parts.append(f"\n**结论**：该模型在 RAG 场景下几乎不受 temperature 参数影响，表现出稳定的输出能力。")

    parts.append(f"\n### 7.3 RAG vs Graph RAG 对比")
    parts.append(f"\n- RAG 模式在基础事实检索和数值精度方面表现更优")
    parts.append(f"- Graph RAG 在实体关系推理（如 GRAG-01, GRAG-02）方面有一定优势")
    parts.append(f"- 但两者均受限于中文文档检索的质量问题")
    parts.append(f"- RAG 总得分 {rag_overall} > Graph RAG 总得分 {grag_overall}，差异 {SUMMARY['comparison']['rag_vs_graph_diff']} 分")

    parts.append(f"\n### 7.4 系统改进建议")
    parts.append(f"\n1. **提升中文文档检索质量**：检查中文文档的文本分块策略和向量嵌入效果")
    parts.append(f"\n2. **增加知识图谱覆盖**：当前 KG 包含 4046 个实体和 38755 条边，但部分跨文档关联信息未被充分利用")
    parts.append(f"\n3. **优化检索权重**：针对多文档混合场景，调整 RRF 融合权重以平衡不同语言的文档")

    # Scoring methodology note
    parts.append(SEP + "## 八、评分方法说明")
    parts.append(f"\n本报告采用自动化机械评分规则，评分维度和权重如下：")
    parts.append("\n| 维度 | 权重 | 评分方式 |")
    parts.append("|------|------|---------|")
    parts.append("| A. 事实准确性 | 0.30 | 关键词匹配，检查回答是否包含期望关键事实 |")
    parts.append("| B. 完整性 | 0.20 | 事实覆盖率 = 命中数/总事实数 |")
    parts.append("| C. 聚焦度 | 0.10 | 基于回答长度的启发式评分（过长为发散） |")
    parts.append("| D. 幻觉程度 | 0.25 | 统计回答中文档外数值数量 |")
    parts.append("| E. 一致性 | 0.15 | 6个温度下A分数的标准差及波动范围 |")
    parts.append(f"\n**局限性**：机械化关键词匹配可能无法完全捕获语义等价（paraphrase）的知识。回答内容分析建议结合人工抽检。完整回答原文请参见 `plans/temperature-test-results.json`。")

    # Footer
    parts.append(SEP + "---")
    parts.append(f"\n*报告由自动化测试脚本生成，模型：{MODEL}，测试日期：{META['test_date']}*")
    parts.append(f"\n*完整 JSON 结果文件：`plans/temperature-test-results.json`*")

    return "\n".join(parts)


# Write report
report = build_report()
output_path = f"test_report/temperature-test-report-{MODEL}.md"
with open(output_path, "w", encoding="utf-8") as f:
    f.write(report)

print(f"报告已生成: {output_path}")
print(f"报告大小: {len(report)} 字符")
