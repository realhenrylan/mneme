#!/usr/bin/env python3
"""修正评分逻辑并重新生成结果 JSON"""

import json, re
from collections import defaultdict

# ============================================================
# 更完善的关键事实定义（使用正则匹配或关键词列表）
# ============================================================

EXPECTED_FACTS = {
    "RAG-01": {
        "keywords": [["紫金山"], ["448.9", "448"]],
        "desc": "紫金山, 448.9米"
    },
    "RAG-02": {
        "keywords": [["5 GB", "5GB", "5 gb"], ["1 TB", "1TB", "1 tb"]],
        "desc": "5 GB, 1 TB"
    },
    "RAG-03": {
        "keywords": [["tokenization", "分词", "标记化"], ["prompt", "提示"], ["embedding", "嵌入", "编码"]],
        "desc": "Tokenization, Prompt, Embedding"
    },
    "RAG-04": {
        "keywords": [["verification waste", "浪费", "不必要的验证", "拒绝风险", "rejection", "throughput", "吞吐", "batch capacity", "验证"]],
        "desc": "减少verification waste/提高throughput"
    },
    "RAG-05": {
        "keywords": [
            ["traffic forecasting", "交通预测", "traffic flow", "speed", "congestion"],
            ["human mobility", "人类移动", "个体", "人群", "移动行为"],
            ["demand forecasting", "需求预测", "需求", "crowd", "vehicle count"],
            ["missing data imputation", "缺失数据", "填补", "imputation"]
        ],
        "desc": "Traffic/Human Mobility/Demand Forecasting, Missing Data Imputation"
    },
    "RAG-06": {
        "keywords": [
            ["长江水系", "长江"],
            ["秦淮河"],
            ["玄武湖"],
            ["莫愁湖"],
            ["汤山", "珍珠泉"]
        ],
        "desc": "长江水系, 长江/秦淮河/玄武湖/莫愁湖等"
    },
    "RAG-07": {
        "keywords": [
            ["prompt injection", "注入", "构造"],
            ["URL", "链接"],
            ["敏感数据", "private", "泄露", "exfil"],
            ["allow-list", "白名单", "dynamic policy", "dynamic", "search index", "索引"]
        ],
        "desc": "prompt injection构造URL,动态allow-list方案"
    },
    "RAG-08": {
        "keywords": [
            ["personal vault", "个人保管库", "保管库"],
            ["ransomware", "勒索软件", "勒索"],
            ["file encryption", "加密", "encryption"]
        ],
        "desc": "Personal Vault, 勒索软件检测, 文件加密"
    },
    "RAG-09": {
        "keywords": [
            ["868"],
            ["954"],
            ["832"],
            ["87.2", "87"]
        ],
        "desc": "868.28km², 954.70万人, 832.49万人, 87.2%"
    },
    "RAG-10": {
        "keywords": [["60", "85"], ["加速", "提升", "faster", "speedup"]],
        "desc": "60%-85%"
    },
    "RAG-11": {
        "keywords": [
            ["secret key", "密钥", "key"],
            ["记忆", "memoriz"],
            ["推断", "infer"],
            ["interaction", "交互", "暴露"],
            ["differential privacy", "差分隐私", "dp-sgd"],
            ["homomorphic encryption", "同态加密"],
            ["federated learning", "联邦学习"],
            ["blockchain", "区块链"]
        ],
        "desc": "隐私挑战+应对方案"
    },
    "RAG-12": {
        "keywords": [["云锦"], ["汤山温泉", "汤山"], ["珍珠泉"]],
        "desc": "云锦, 汤山温泉, 珍珠泉"
    },
    "GRAG-01": {
        "keywords": [
            ["bert"],
            ["gpt-3.5", "gpt3.5", "chatglm"],
            ["traffic forecasting", "交通预测", "traffic flow"],
            ["orchestration", "编排", "deductive", "推理"]
        ],
        "desc": "BERT vs GPT-3.5, 不同作用"
    },
    "GRAG-02": {
        "keywords": [
            ["llm4ts"],
            ["stg-llm"],
            ["tpllm"],
            ["gpt-2"]
        ],
        "desc": "LLM4TS, STG-LLM, TPLLM; GPT-2"
    },
    "GRAG-03": {
        "keywords": [
            ["parallel backbone", "并行", "parallel"],
            ["sequential", "序列", "sequential"],
            ["suffix decay", "衰减", "decay"]
        ],
        "desc": "parallel backbone + lightweight sequential module"
    },
    "GRAG-04": {
        "keywords": [
            ["auxmoblcast"],
            ["llmlight"],
            ["gt-tdi"]
        ],
        "desc": "AuxMobLCast, LLMLight, GT-TDI"
    },
    "GRAG-05": {
        "keywords": [
            ["unist"],
            ["st-llm"],
            ["pre-training", "预训练"],
            ["spatial-temporal", "时空"]
        ],
        "desc": "UniST vs ST-LLM"
    },
    "GRAG-06": {
        "keywords": [
            ["固定长度", "fixed"],
            ["survival probability", "生存概率", "survival"],
            ["dynamic", "动态"],
            ["throughput", "吞吐"]
        ],
        "desc": "固定vs动态验证"
    },
    "GRAG-07": {
        "keywords": [
            ["prompt engineering", "提示工程"],
            ["fine-tune", "微调"],
            ["mobilitygpt"],
            ["st-llm"]
        ],
        "desc": "从prompt engineering到fine-tune"
    },
    "GRAG-08": {
        "keywords": [
            ["inter-token", "token间"],
            ["acceptance decay", "通过率下降", "decay", "衰减"],
            ["semi-autoregressive", "半自回归"],
            ["parallel backbone"],
            ["sequential"]
        ],
        "desc": "inter-token dependency, acceptance decay, semi-autoregressive"
    },
    "GRAG-09": {
        "keywords": [
            ["pre-train", "预训练"],
            ["参数"],
            ["downstream", "下游"],
            ["speculative", "推测"]
        ],
        "desc": "Fine-tune关联分析"
    },
    "GRAG-10": {
        "keywords": [
            ["prompt injection"],
            ["exfiltration", "泄露"],
            ["memoriz", "记忆"],
            ["differential privacy", "差分隐私"],
            ["allow-list", "白名单"]
        ],
        "desc": "隐私风险异同"
    },
    "GRAG-11": {
        "keywords": [
            ["长江"],
            ["秦淮河"],
            ["六朝古都", "古都", "十朝"],
            ["紫金山"],
            ["中山陵"]
        ],
        "desc": "地理历史关联"
    },
    "GRAG-12": {
        "keywords": [
            ["限制访问", "访问控制", "allow"],
            ["静态", "存储"],
            ["动态", "运行时"]
        ],
        "desc": "安全机制对比"
    },
    "GRAG-13": {
        "keywords": [
            ["身份验证", "验证", "authentication"],
            ["加密", "encrypt"],
            ["访问控制"],
            ["窃取", "传输"]
        ],
        "desc": "Personal Vault vs 文件加密"
    },
    "GRAG-14": {
        "keywords": [
            ["redirect", "重定向"],
            ["google", "允许列表"],
            ["trust-by-association", "关联信任"],
            ["url", "索引"]
        ],
        "desc": "open redirects绕过"
    },
    "COM-01": {
        "keywords": [
            ["推理", "reasoning"],
            ["迁移学习", "transfer"],
            ["可扩展", "scalab"],
            ["多模态", "multi-modal", "multimodal"],
            ["可解释", "interpretab", "explainab"]
        ],
        "desc": "LLM优势"
    },
    "COM-02": {
        "keywords": [
            ["semi-autoregressive", "半自回归"],
            ["confidence-scheduled", "confidence"],
            ["60", "85"],
            ["pareto", "前沿"]
        ],
        "desc": "核心创新: semi-autoregressive + confidence-scheduled"
    },
    "COM-03": {
        "keywords": [
            ["长江"],
            ["秦淮河"],
            ["玄武湖"],
            ["林木覆盖率", "26.4"],
            ["2530"],
            ["72"]
        ],
        "desc": "水资源/林木/生物"
    },
    "COM-04": {
        "keywords": [
            ["fine-tune", "微调", "fine tune"],
            ["zero-shot", "few-shot"],
            ["计算成本", "训练"],
            ["数据稀缺", "无需训练"]
        ],
        "desc": "Fine-tune vs Zero/Few-Shot"
    },
    "COM-05": {
        "keywords": [
            ["its", "智能交通"],
            ["secret key", "密钥"],
            ["memoriz", "记忆"],
            ["differential privacy"],
            ["prompt injection"],
            ["allow-list", "白名单"]
        ],
        "desc": "两篇论文隐私观点"
    },
    "COM-06": {
        "keywords": [
            ["onedrive.com", "网页"],
            ["移动应用", "mobile"],
            ["备份", "backup"],
            ["共享", "share"]
        ],
        "desc": "跨设备访问功能"
    },
}


def check_keyword(answer_lower, keyword_list):
    """检查回答是否包含关键词列表中的至少一个"""
    if not answer_lower:
        return False
    for kw in keyword_list:
        if kw.lower() in answer_lower:
            return True
    return False


def is_refusal_answer(answer):
    """检测回答是否是拒绝/不知道类型的诚实回答"""
    answer_lower = answer.lower()
    refusal_phrases = [
        "未提及", "没有提到", "不包含", "未包含", "没有提供", "未提供",
        "无法确定", "不知道", "找不到", "无法找到", "没有找到", "没有关于",
        "无法回答", "没有相关", "不包含相关", "文档中未", "文档内未",
        "根据提供的文档内容，无法", "根据文档内容，无法",
        "not found", "no information", "cannot answer",
    ]
    for phrase in refusal_phrases:
        if phrase.lower() in answer_lower:
            return True
    return False


def is_empty_or_error(answer):
    """检查是否为空回答或错误回答"""
    if not answer or len(answer.strip()) < 5:
        return True
    if answer.startswith("[错误"):
        return True
    return False


def count_fabricated_numbers(answer, expected_keyword_groups):
    """数一下回答中可能在文档外的数字"""
    answer_lower = answer.lower()
    numbers = re.findall(r'\b\d+\.?\d*\b', answer)

    # Collect all expected numbers
    expected_nums = set()
    for group in expected_keyword_groups:
        for kw in group:
            for n in re.findall(r'\d+\.?\d*', str(kw)):
                if len(n) >= 2:
                    expected_nums.add(n)

    fabricated = 0
    for n in numbers:
        if n in expected_nums:
            continue
        # Skip common non-material numbers
        if len(n) == 4 and (n.startswith('20') or n.startswith('19')):
            continue
        if len(n) <= 1:
            continue
        if n in ['0', '1', '2', '3', '4', '5', '6', '7', '8', '9']:
            continue
        fabricated += 1
    return fabricated


def score_single(answer, fact_config, is_neg=False):
    """评分单个回答"""
    notes = []
    answer_lower = answer.lower().strip() if answer else ""

    # Empty/error check
    if is_empty_or_error(answer):
        return {"A": 0, "B": 1, "C": 1, "D": 5,
                "single": round(0*0.30 + 1*0.20 + 1*0.10 + 5*0.25, 2)}, ["空或错误回答"]

    is_refusal = is_refusal_answer(answer)

    # NEG question handling
    if is_neg:
        if is_refusal:
            return {"A": 5, "B": 3, "C": 5, "D": 5,
                    "single": round(5*0.30 + 3*0.20 + 5*0.10 + 5*0.25, 2)}, ["诚实回答：文档未提及"]
        else:
            # Check if answer provides specific data
            has_concrete_data = False
            numbers = re.findall(r'\b\d+\.?\d*\b', answer)
            if len(numbers) >= 1:
                has_concrete_data = True

            if has_concrete_data:
                return {"A": 1, "B": 3, "C": 3, "D": 1,
                        "single": round(1*0.30 + 3*0.20 + 3*0.10 + 1*0.25, 2)}, ["编造了具体数值！"]
            elif len(answer) > 200:
                return {"A": 2, "B": 3, "C": 3, "D": 2,
                        "single": round(2*0.30 + 3*0.20 + 3*0.10 + 2*0.25, 2)}, ["可能编造"]
            else:
                return {"A": 3, "B": 3, "C": 4, "D": 4,
                        "single": round(3*0.30 + 3*0.20 + 4*0.10 + 4*0.25, 2)}, ["回答简短，未明显编造"]

    keyword_groups = fact_config.get("keywords", [])
    if not keyword_groups:
        return {"A": 3, "B": 3, "C": 3, "D": 5,
                "single": round(3*0.30 + 3*0.20 + 3*0.10 + 5*0.25, 2)}, ["无评分基准"]

    # Count hits
    hit_count = 0
    for group in keyword_groups:
        if check_keyword(answer_lower, group):
            hit_count += 1

    total_groups = len(keyword_groups)

    # Count fabricated numbers
    fabricated = count_fabricated_numbers(answer, keyword_groups)

    # A: 事实准确性
    if is_refusal:
        A = 1  # refusal means no facts found
    elif total_groups == 0:
        A = 3
    else:
        hit_ratio = hit_count / total_groups
        if hit_ratio >= 1.0: A = 5
        elif hit_ratio >= 0.8: A = 4
        elif hit_ratio >= 0.6: A = 3
        elif hit_ratio >= 0.3: A = 2
        else: A = 1

    # B: 完整性
    if total_groups == 0:
        B = 3
    else:
        coverage = hit_count / total_groups
        B = round(coverage * 4 + 1)
        B = max(1, min(5, B))

    # C: 聚焦度
    answer_len = len(answer)
    if is_refusal:
        C = 5
    elif answer_len < 80:
        C = 5
    elif answer_len < 250:
        C = 4
    elif answer_len < 600:
        C = 3
    elif answer_len < 1200:
        C = 2
    else:
        C = 1

    # D: 幻觉程度
    if fabricated == 0:
        D = 5
    elif fabricated <= 1:
        D = 4
    elif fabricated <= 3:
        D = 3
    elif fabricated <= 6:
        D = 2
    else:
        D = 1

    single = round(A*0.30 + B*0.20 + C*0.10 + D*0.25, 2)

    score_notes = []
    if is_refusal:
        score_notes.append(f"模型拒绝回答（检索未命中相关文档块）")
    if fabricated > 0:
        score_notes.append(f"编造了 {fabricated} 个文档外数值")
    if hit_count < total_groups * 0.5 and not is_refusal:
        score_notes.append(f"关键词命中率 {hit_count}/{total_groups}")

    return {"A": A, "B": B, "C": C, "D": D, "single": single}, score_notes[:3]


def score_consistency(scores_dict):
    """计算E（一致性）"""
    a_scores = []
    for t_key in scores_dict:
        a_scores.append(scores_dict[t_key].get("A", 0))

    if not a_scores:
        return 3

    mean_a = sum(a_scores) / len(a_scores)
    variance = sum((a - mean_a) ** 2 for a in a_scores) / len(a_scores)
    std = variance ** 0.5
    hit_range = max(a_scores) - min(a_scores)

    if std <= 0.50 and hit_range <= 1:
        return 5
    elif std <= 0.80 and hit_range <= 2:
        return 4
    elif hit_range > 2 and max(a_scores[:3]) - min(a_scores[:3]) <= 1:
        return 3
    elif hit_range > 2:
        return 2
    else:
        return 1


# ============================================================
# Main rescoring
# ============================================================

def main():
    with open("plans/temperature-test-results.json", "r", encoding="utf-8") as f:
        data = json.load(f)

    TEMPERATURES = data["meta"]["temperatures"]
    t_keys = [str(t) for t in TEMPERATURES]

    all_mode_results = {
        "rag": {},
        "graph_rag": {},
    }

    for mode in ["rag", "graph_rag"]:
        for qid in data["results"][mode]:
            is_neg = qid.startswith("NEG-")
            facts = EXPECTED_FACTS.get(qid, {"keywords": []})

            scores = {}
            a_scores_list = []
            all_notes = []

            for t_key in t_keys:
                answer = data["results"][mode][qid]["answers"].get(t_key, "")
                score, notes = score_single(answer, facts, is_neg)
                scores[t_key] = score
                a_scores_list.append(score)
                all_notes.extend(notes)

            E = score_consistency(scores)

            # Calculate question score
            A_mean = sum(s["A"] for s in a_scores_list) / len(a_scores_list)
            B_mean = sum(s["B"] for s in a_scores_list) / len(a_scores_list)
            C_mean = sum(s["C"] for s in a_scores_list) / len(a_scores_list)
            D_mean = sum(s["D"] for s in a_scores_list) / len(a_scores_list)
            score_q = round(A_mean*0.30 + B_mean*0.20 + C_mean*0.10 + D_mean*0.25 + E*0.15, 2)

            data["results"][mode][qid]["scores"] = scores
            data["results"][mode][qid]["E"] = E
            data["results"][mode][qid]["score_question"] = score_q
            data["results"][mode][qid]["notes"] = list(set(all_notes))[:5]

            all_mode_results[mode][qid] = {
                "scores": scores,
                "E": E,
                "score_question": score_q,
                "notes": list(set(all_notes))[:5],
            }

    # Recalculate summaries
    for mode in ["rag", "graph_rag"]:
        mode_data = data["results"][mode]
        all_qs = list(mode_data.keys())

        scores_by_temp = defaultdict(list)
        for qid in all_qs:
            for t_key in t_keys:
                s = mode_data[qid]["scores"].get(t_key, {})
                scores_by_temp[t_key].append(s.get("single", 0))

        temp_means = {}
        for t_key in t_keys:
            vals = scores_by_temp[t_key]
            temp_means[t_key] = round(sum(vals)/len(vals), 2) if vals else 0

        overall = round(sum(mode_data[q]["score_question"] for q in all_qs) / len(all_qs), 2)

        total_scores = len(all_qs) * 6
        halluc_count = sum(1 for q in all_qs for s in mode_data[q]["scores"].values() if s.get("D", 5) < 4)
        refuse_count = sum(1 for q in all_qs for s in mode_data[q]["scores"].values() if s.get("A", 0) == 0 and s.get("D", 5) == 5)

        data["summary"][mode] = {
            "scores_by_temperature": temp_means,
            "overall": overall,
            "best_temperature": float(min(temp_means, key=lambda k: -temp_means[k])) if temp_means else 0.0,
            "hallucination_rate": round(halluc_count / max(1, total_scores), 3),
            "refuse_rate": round(refuse_count / max(1, total_scores), 3),
        }

    data["summary"]["comparison"]["rag_vs_graph_diff"] = round(
        data["summary"]["rag"]["overall"] - data["summary"]["graph_rag"]["overall"], 2
    )

    # Save
    with open("plans/temperature-test-results.json", "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    print("重新评分完成，已更新 plans/temperature-test-results.json")

    # Print updated summary
    print("\n=== 更新后摘要 ===")
    for mode in ["rag", "graph_rag"]:
        s = data["summary"][mode]
        print(f"\n{mode}:")
        print(f"  总得分: {s['overall']}")
        print(f"  最佳温度: {s['best_temperature']}")
        print(f"  各温度得分: {s['scores_by_temperature']}")
        print(f"  幻觉率: {s['hallucination_rate']}")
        print(f"  拒绝率: {s['refuse_rate']}")

    print(f"\nRAG vs Graph RAG 差异: {data['summary']['comparison']['rag_vs_graph_diff']}")


if __name__ == "__main__":
    main()
