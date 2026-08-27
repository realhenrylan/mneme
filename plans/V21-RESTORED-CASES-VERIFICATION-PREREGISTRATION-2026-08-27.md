# v2.1 待验证集——恢复案例验证轮预注册（阈值与判定规则先行锁定）

> 登记日期：2026-08-27
> 上游：`evaluation/datasets/v2/revisions/v2.1-owner-rulings-batch1/rulings-ledger.jsonl`
> （disposition=`restored_pending_verification` 的行）
> 状态：**运行任何复核调用之前签署**。§三判定映射自此锁死，不得在看到
> 结果后调整。争议性质是「targeted-review 驳回是否成立」，owner 已基于机械
> 包含证据推翻该轮驳回；本验证轮采用与其既有授权路线（zh-040 契约聚焦
> 盲审）同级的独立密封复核作为权威裁决器——即「盲审结果为准」。

---

## 一、样本与来源

- 目标集 = rulings 账本中 disposition 为 `restored_pending_verification` 的
  case，程序化推导，预期恰为 `{zh-023, multi-012, mixed-022}`；
- 复核输入 = v2.0.11 冻结 candidate 的 draft/evidence/chunks（SHA 链门禁，
  与既往 sealed 流程完全一致）；任何一方数据不做改动。

## 二、流程纪律

- **双向盲态**：payload 不含 case_id、旧驳回结论、owner 推翻信息或
  「预期 confirmed」暗示；复用基座 scan_payload 全量泄露扫描；
- Pro-only 引擎契约不变（temperature=0.0 / thinking disabled / 同模型
  重试上限 / 无 fallback / probe 身份核验）；
- 每案最多 3 次同模型重试；耗尽按 error 记录（不伪造响应）；
- 结果零改写：不产出 overlay/active/draft/truth 改动；审计产物含
  rewritten=false 标记。

## 三、判定映射（预先登记）

- **RESTORED_VERIFICATION_OK**：当且仅当全部样本的密封复核 decision 均
  为 `confirmed` 且通过严格 schema 验证。语义：三案的「支持判定」获得
  新鲜独立复核背书，从 pending 升级为 verified-active 候选，记入账本
  附录产物；是否正式并入 v2.1 ground truth 池仍由后续治理批次决定。
- **RESTORED_VERIFICATION_BLOCKED**：任一样本出现 reject / needs_followup /
  error。语义：该案回到仲裁待决状态（owner 裁决），其余案的 confirmed
  结果照常记录但整体 gate 降级；**不允许**部分采纳混入 OK 口径。
- error 类失败响应原文不予持久化（沿用 base 局限），以异常消息+重试
  计数留痕。
- 两个方向的门限都不做数据相关调参；本轮之后若需扩样，属新一轮预注册。

## 四、范围与限制

- 本轮只解决「模型级支持判定」的复核权威性，**不是**生成质量评测：
  它不改写、不宣称、也不充当任何 promotion 依据（分离原则延续）；
- 机械包含证据（exact 关系）已在批一入档，本结果与之并列披露，两套
  证据线互不覆盖。
