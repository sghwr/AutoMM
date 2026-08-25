---
name: mathmodeling-pipeline
description: 推进数学建模小问的文献、假设、公式、实现、计算、验证和归档阶段。
---

# Math Modeling Pipeline

## 目标

把一个固定的小问按阶段契约推进到 locally completed。主控每次只调用一个阶段 Agent，本 Skill 不允许一次跑完整条链。

## 阶段顺序

```text
problem_understanding
→ literature_review
→ assumption_definition
→ mathematical_formulation
→ implementation
→ computation
→ sanity_check Level 1-4
→ visualization
→ robustness（条件性）
→ sanity_check Level 6（条件性）
→ ablation（条件性）
→ locally_completed
```

所有小问 locally completed 后，另行执行 cross_question_review，不能由单问 pipeline 提前完成。

## 通用阶段协议

进入阶段前检查 `entry_conditions` 和所需文件；调用专职 Agent；校验统一返回字段和产物存在；成功后更新 question manifest；失败时应用明确 failure route；追加 ledger；不在同一次调用继续下一阶段。

## 阶段路由

- 题目理解：problem-decomposer，只在整题初始化阶段执行一次，并为每问生成 shared 资料。
- 文献：literature-researcher。关键假设无来源或 pool dry 时不能伪造完成。
- 假设：assumption-manager，创建不可覆盖的 `assumption_vNNN`。
- 公式：mathematical-formulator，可创建多个 formulation 候选并预注册比较标准。
- 实现：implementation-agent，静态检查通过才提交任务。
- 计算：resource-manager 异步提交；阶段保持 computation/running，等待后续唤醒消费。
- sanity：sanity-checker。PASS/WARN 才进入 visualization。
- 可视化：visualization-agent，最终版本至少五张图。
- robustness/ablation：由各 Agent 判断适用性；跳过要记录理由。
- locally completed：检查最小产物，发送单向通知。

## 版本失败

NEEDS_REVISION 在当前版本内按类型回退。VERSION_REJECTED 关闭当前版本，创建下一版本。连续 3 次拒绝刷新文献池；达到 5 个版本仍失败则 unresolved，停止整题推进。

## stale 传播

前问 conclusion hash 变化后，Orchestrator 标记受影响后问 stale。Pipeline 从最早依赖阶段恢复，不机械重跑未受影响任务。

## 禁止

不跨小问并行推进主阶段；不覆盖历史版本；不跳过 mandatory stage；不将聊天回答视为产物；不把远端占位接口当作执行成功。
