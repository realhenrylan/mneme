"""M2 报告三形态拒答分类器测试（操作化定义见模块 docstring）。

M1 教训：noanswer 探针的输出形态是「语料未覆盖/没有介绍 X」的中性语义
陈述（非拒答消息形态），refusal indicator 不命中 → correctly_refused=False
是真实产品信号。M2 报告按三形态分列：
①前哨拒答 = context 零证据快速路径拒绝；
②生成后拒答 = context 非空 + 拒答消息形态；
③语义式陈述 = 输出实质表示语料未覆盖，但非拒答消息形态（indicator 未命中）。
"""

from evaluation.answer_level_report import classify_refusal_form


class TestClassifyRefusalForm:
    def test_sentinel_refusal_when_zero_context_and_refusal_message(self):
        assert classify_refusal_form(
            should_refuse=True,
            answer="未找到足够可靠的文档依据，暂时无法回答该问题。",
            context="",
        ) == "sentinel_refusal"

    def test_post_generation_refusal_when_context_nonempty_and_refusal_message(self):
        assert classify_refusal_form(
            should_refuse=True,
            answer="根据提供的文档，无法回答该问题。",
            context="[S1] doc.md (chunk_id=abc123_chunk_0): 内容",
        ) == "post_generation_refusal"

    def test_semantic_statement_when_indicator_not_hit(self):
        assert classify_refusal_form(
            should_refuse=True,
            answer="根据提供的文档内容，Python 教程中没有介绍 pandas 库。",
            context="[S1] doc.md (chunk_id=abc123_chunk_0): 内容",
        ) == "semantic_statement"

    def test_answered_case_with_no_refusal_form_is_not_refusal(self):
        assert classify_refusal_form(
            should_refuse=False,
            answer="答案是 42。",
            context="[S1] doc.md (chunk_id=abc123_chunk_0): 内容",
        ) == "not_refusal"

    def test_mixed_context_length_classification_is_deterministic(self):
        # 拒答消息 + context 非空 → 生成后拒答（前哨以 context 长度 0 为唯一判据）
        assert classify_refusal_form(
            should_refuse=True,
            answer="抱歉，我无法回答。",
            context="x",
        ) == "post_generation_refusal"
