---
name: paper-writing
description: 在全局检查通过且人类确认后生成最终 Markdown 论文。
---

# Paper Writing

本 Skill 在初版本中禁用。当前终态只构建 `reports/final_summary.md`，不创建 draft/final 论文，
也不等待 APPROVE/REJECT/REVISE。以下内容仅保留为后续版本设计草案。

## Draft Gate

所有小问 locally completed；最终 sanity 为 PASS/WARN；条件性阶段完成或有跳过理由；Level 5 通过；引用双向闭合；图表清单完整。

## Draft

读取模板、风格样本和接受版本材料，生成 `draft_paper.md`。统一符号、公式和图表编号；按 GB/T 7714 组织引用；关键文献加 `[待人工复核]`。同时生成论文检查报告。

## 授权

发送带唯一 request ID 的邮件。只接受允许发件人、同一线程、未处理 message ID 的 APPROVE/REJECT/REVISE。等待期间暂停其他研究动作。

## Final

APPROVE 后才写 final；REVISE 回论文修订；REJECT 保留 draft 和材料。final 生成失败必须保留 draft，不伪装完成。
