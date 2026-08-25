# 检索拒答阈值离线扫描报告（只读，零 LLM）

> 性质：**只读离线分析** — 不调用 LLM/API，不修改任何生产配置、
> 阈值与历史产物；结论不构成阈值批准。
> baseline 阈值：`0.03`；候选阈值：
> 0.00, 0.01, 0.02, 0.03。
> 结论：**AUTOMATED_DIAGNOSTIC_NO_GO**

## dev（95 例，answerable 73 / should_refuse 22）

### baseline 拒答清单

| case_id | 分组 | max score |
|---|---|---|
| cross-010 | 前哨 FR | 0.02988 |
| en-013 | 前哨 FR | 0.02837 |
| meta-006 | 前哨 FR | 0.02830 |
| meta-008 | 前哨 FR | 0.02601 |
| noanswer-006 | 正确拒答 | 0.02649 |
| noanswer-008 | 正确拒答 | 0.02490 |
| noanswer-012 | 正确拒答 | 0.02938 |
| noanswer-020 | 正确拒答 | 0.02353 |
| noanswer-022 | 正确拒答 | 0.02210 |
| noanswer-024 | 正确拒答 | 0.02649 |

### 候选阈值扫描（新放行）

| 阈值 | 新放行总数 | 放行前哨 FR | 放行 should_refuse |
|---|---|---|---|
| 0.00 | 10 | 4 (cross-010, en-013, meta-006, meta-008) | 6 (noanswer-006, noanswer-008, noanswer-012, noanswer-020, noanswer-022, noanswer-024) |
| 0.01 | 10 | 4 (cross-010, en-013, meta-006, meta-008) | 6 (noanswer-006, noanswer-008, noanswer-012, noanswer-020, noanswer-022, noanswer-024) |
| 0.02 | 10 | 4 (cross-010, en-013, meta-006, meta-008) | 6 (noanswer-006, noanswer-008, noanswer-012, noanswer-020, noanswer-022, noanswer-024) |
| 0.03 | 0 | 0 (-) | 0 (-) |

### G2 门槛判定

| 阈值 | 新放行 SR | 主口径容许量（10% × 22） | 主口径 | 敏感性 (refused_total=10 / refused_SR=6 / all_SR=22) |
|---|---|---|---|---|
| 0.00 | 6 | 2.20 | FAIL | refused_total=False（≤1.0）, refused_should_refuse=False（≤0.6）, all_should_refuse=False（≤2.2） |
| 0.01 | 6 | 2.20 | FAIL | refused_total=False（≤1.0）, refused_should_refuse=False（≤0.6）, all_should_refuse=False（≤2.2） |
| 0.02 | 6 | 2.20 | FAIL | refused_total=False（≤1.0）, refused_should_refuse=False（≤0.6）, all_should_refuse=False（≤2.2） |
| 0.03 | 0 | 2.20 | PASS | refused_total=True（≤1.0）, refused_should_refuse=True（≤0.6）, all_should_refuse=True（≤2.2） |

### 分数带交织诊断

- 前哨 FR 分数带：0.02601 ~ 0.02988
- 正确拒答分数带：0.02210 ~ 0.02938
- 交织：是；放行全部 FR 时最少放行的正确拒答 = 3；存在分离阈值：否

## holdout（15 例，answerable 12 / should_refuse 3）

### baseline 拒答清单

| case_id | 分组 | max score |
|---|---|---|
| meta-002 | 前哨 FR | 0.02857 |
| noanswer-010 | 正确拒答 | 0.02184 |

### 候选阈值扫描（新放行）

| 阈值 | 新放行总数 | 放行前哨 FR | 放行 should_refuse |
|---|---|---|---|
| 0.00 | 2 | 1 (meta-002) | 1 (noanswer-010) |
| 0.01 | 2 | 1 (meta-002) | 1 (noanswer-010) |
| 0.02 | 2 | 1 (meta-002) | 1 (noanswer-010) |
| 0.03 | 0 | 0 (-) | 0 (-) |

### G2 门槛判定

| 阈值 | 新放行 SR | 主口径容许量（10% × 3） | 主口径 | 敏感性 (refused_total=2 / refused_SR=1 / all_SR=3) |
|---|---|---|---|---|
| 0.00 | 1 | 0.30 | FAIL | refused_total=False（≤0.2）, refused_should_refuse=False（≤0.1）, all_should_refuse=False（≤0.3） |
| 0.01 | 1 | 0.30 | FAIL | refused_total=False（≤0.2）, refused_should_refuse=False（≤0.1）, all_should_refuse=False（≤0.3） |
| 0.02 | 1 | 0.30 | FAIL | refused_total=False（≤0.2）, refused_should_refuse=False（≤0.1）, all_should_refuse=False（≤0.3） |
| 0.03 | 0 | 0.30 | PASS | refused_total=True（≤0.2）, refused_should_refuse=True（≤0.1）, all_should_refuse=True（≤0.3） |

### 分数带交织诊断

- 前哨 FR 分数带：0.02857 ~ 0.02857
- 正确拒答分数带：0.02184 ~ 0.02184
- 交织：否；放行全部 FR 时最少放行的正确拒答 = 0；存在分离阈值：是

## 结论

- 预注册门槛：G1（前哨 FR 放行 ≥ 4）= PASS；G2（各 split 新放行 should_refuse ≤ 10% × 全部 should_refuse）= FAIL。
- 合格候选阈值：无 → **AUTOMATED_DIAGNOSTIC_NO_GO**。
- 当前分数无法分离“可回答但前哨误拒”与“应拒答”两类 case；
- 生产 `DEFAULT_REFUSAL_THRESHOLD=0.03` **保持不变**；
- 不切换生产默认、不批准 guardrail、不进入 LLM 评测。

*本报告由 evaluation/threshold_scan.py 生成（可复现）；未调用 LLM；未修改任何生产配置、阈值与历史产物。*
