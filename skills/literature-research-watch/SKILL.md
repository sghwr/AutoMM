---
name: literature-research-watch
description: 在研究方向不足、关键假设缺少依据或题目需要新方法时触发文献检索。
---

# Literature Research Watch

## 触发判定

首次进入 literature_review、formulation 失败且 pool dry、连续 3 个版本被拒绝或人工研究触发时调用。已有方向未 dry 时不主动搜索。

## Dry

25 篇、30 分钟、所有候选已 used/rejected、连续一轮无新假设族，任一成立即 dry。flag 必须包含原因和文献池统计。

## 执行

读取当前小问、文献池、已拒绝版本和引用登记；调用一个 literature-researcher；核验新增来源和引用字段；更新 pool/backlog；不得直接修改 accepted 假设。关键来源只发现摘要而没有正文核验时标记 unverified，不能支撑关键假设。

## 完成

报告新增来源、来源级别、新假设族、重复/拒绝项、pool 是否 dry 和下一建议。所有路径使用相对路径。
