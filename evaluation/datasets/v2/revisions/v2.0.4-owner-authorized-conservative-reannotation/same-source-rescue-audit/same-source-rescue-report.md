# v2.0.4 同 source 证据救援扫描

本扫描只读、确定性、离线，不调用 LLM/API、不修改任何 v2 数据、不生成 after/overlay/active 文件、不进入 v2.1。

- 目标：10 条 zero_answer_point_risk=true 的 case
- 分类计数：{'verbatim_full_answer_point_found': 1, 'ambiguous_duplicate': 1, 'verbatim_clause_only_found': 7, 'lexical_related_only': 0, 'no_same_source_candidate_found': 1}
- 建议均要求所有者授权，auto_applicable=false。
