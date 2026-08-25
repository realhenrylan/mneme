# REVIEW_AND_SPLIT_REBUILD_REQUIRED

本 v2.0.6 candidate 关闭了 v2.0.5 的全部 blocker，但：

- 历史 split / lock 配置一律不复用，也不得被本 candidate 读取或修改；
- 本 candidate 未经人工审核（human_reviewed=false），激活前必须完成新的 review / split 重建流程；
- 激活前必须先通过全部剩余门禁（activation_blocked=true、overlay_generated=false、v2_1_entered=false）；
- 不生成 overlay、active metadata、v2.1 指针。
