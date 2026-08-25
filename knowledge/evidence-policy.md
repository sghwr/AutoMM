---
id: foundation-evidence-policy
title: 证据与引用政策
tags: [evidence, citation, literature]
status: reviewed
evidence_level: policy
last_reviewed: 2026-08-21
---

# 证据与引用政策

## 四类陈述

`literature_fact` 是来源明确支持的事实；`project_assumption` 是为当前题建立且需验证边界的假设；`agent_inference` 是根据数据或模型得到的推断；`team_decision` 是阈值、权重或风险偏好的选择。四者不能互相伪装。

“成本与距离线性”若只有建模便利而无证据，是 project assumption；参数来自校准，是 agent inference；风险权重通常是 team decision。每类对应不同验证方式。

## 关键性与等级

一个假设若改变会显著影响模型结构、可行域、主要结论或后问输入，则为关键假设，必须绑定当前题 verified + used 文献或题面硬约束。A/B/C/D 等级用于权威性筛选，还要检查对象、地域、时间、尺度、样本和方法是否可迁移。

## 核验流程

```text
发现候选 → 核对标题/作者/年份/DOI → Crossref/OpenAlex 元数据核验
→ 阅读支持位置 → 记录主张与边界 → used/rejected → 绑定假设或公式
```

摘要可筛选但不能单独支撑关键主张。元数据一致不等于内容支持。无法访问全文时应降低主张强度、寻找替代来源或保持 pending。

## 参数与冲突

外部参数记录原值、单位、场景、换算、采用值和区间，区分直接采用、插值、外推、校准和专家设定。文献冲突时比较定义和场景，形成条件化参数或情景，不用简单平均掩盖差异。无法裁决时让 robustness 量化影响。

## 禁止事项

- 伪造作者、DOI、URL、页码或结论；
- 把 Knowledge、搜索摘要或 LLM 记忆当当前题引用；
- 只登记列表，不说明支持哪条主张；
- 将相关性写成因果；
- 在总结中出现引用表没有的编号。

## 检索词

`systematic review`、`mechanistic model`、`empirical range`、`assumption validity`、`external validity`、`model discrepancy`，配合对象、单位、地域和时间。
