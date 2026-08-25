---
name: visualization-manager
description: 根据阶段触发条件和统一样式生成并归档数学建模图表。
---

# Visualization Manager

## 前置

主结果 sanity Level 1–4 必须为 PASS/WARN。失败版本不生成最终图。

## 流程

1. 读取统一样式配置并自动探测中文字体。
2. visualization-agent 根据数据、模型语义和摘要叙事自主选择图型。第三维具有明确语义时鼓励采用三维曲面、轨迹、散点、空间结构或优化景观；不得仅为装饰增加伪三维效果。
3. 每张图使用稳定 ID，保存 PNG 和生成脚本。
4. 自动检查标题、坐标、单位、图例、重叠、裁切和颜色区分；三维图还需视觉检查视角、遮挡、透视失真和深度可辨性，投影不明确时补充二维投影、切片或等高线；失败则重新生成。
5. 更新题目 figure manifest。
6. 最终接受版本每问至少五张图；robustness/ablation 图可计数。

未收录图可以保留，但未登记图不能进入最终摘要。图表生成失败阻止 locally completed。
