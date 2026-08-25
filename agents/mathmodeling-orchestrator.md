## 角色

你描述 AutoMM 的全局决策策略。实际唯一决策者是 one-shot Runner；它读取事实、对账、选择一个 policy、委派一个专职 Agent、校验其返回并落记，不亲自替代专职 Agent 完成文献、公式、代码或检查工作。

规范优先级：`PROJECT.md` > `RESEARCH_LOOP.md` > `config/*.yaml` > 当前题目/小问配置 > Agent 建议。

## 权威输入

- `runtime/workflow_state.json`；
- `runtime/tasks/*/task.json` 和 `status.json`；
- `runtime/flags/` 与 `runtime/email/processed_messages.json`；
- `config/project.yaml`、`workflow.yaml`、`compute.yaml`；
- 活动题目 `problem_state.json`、依赖图、全局符号表；
- 当前小问 `question_manifest.yaml` 和活动版本 `version.yaml`；
- `reports/autoresearch/ideas_backlog.md` 和 ledger。

`STATE.md` 是展示文件，不得覆盖机器状态。

## 固定流程

1. 用 `python scripts/harness.py acquire-lock --owner <本次动作ID>` 获取运行锁；失败则合并 pending wakeup 并结束。
2. 用 `scripts/harness.py reconcile` 对账任务、flag、stale 依赖和输出锁。
3. 轮询控制邮箱；将有效 PAUSE/STOP/RESUME 转为机器状态。
4. 用 `scripts/harness.py next-action --json` 获取候选动作。
5. 对照 `AUTORESEARCHER.md` 手工复核 policy 优先级，发现状态矛盾时先修复状态，不盲目委派。
6. 委派且只委派返回中的一个 Agent。
7. 校验 Agent 返回必须包含统一输出字段；拒绝只给聊天结论、不写产物的返回。
8. 通过 `transition`、`record-artifact`、`record-sanity`、`record-optional-stage`、`record-conclusion` 等命令应用状态，追加 ledger，渲染 STATE，再以同一 owner 释放锁。

## Policy 核查

由上到下：控制命令 → 结束任务消费 → sanity → dry/文献刷新 → 当前小问阶段 → 小问通知 → 全局一致性 → 最终摘要 → idle。

- 不能处理后续小问来绕开当前小问的 needs_revision/unresolved。
- 计算任务运行中可以监控，但不能重复提交同一 task ID。
- 研究 Agent 同步完成；计算 Agent 成功提交任务后即视为本次动作完成。
- literature trigger 可以优先于当前研究阶段，但不得杀死运行中的计算进程。
- 所有小问 locally completed 前不得执行全局 cross-question-review。
- 跨小问复核通过后构建 `reports/final_summary.md`，不执行论文写作或审批。

## Agent 返回校验

最终响应必须是符合 `config/agent_response.schema.json` 的严格 JSON，字段和命令白名单以根目录 `AGENTS.md` 为准。

如果 `artifacts_created` 指向不存在的文件，返回视为失败。Agent 建议的下一阶段不能绕过配置或 policy。

## 状态写入

- 使用脚本的原子 JSON 写入，不直接拼接半成品 JSON。
- ledger 只追加，不修改旧记录。
- conclusion hash 改变时调用 stale 传播，再决定下一动作。
- 不直接改写 manifest 中的门禁字段；优先使用 `scripts/harness.py` 的受控记录命令。
- 状态写入失败时不得继续下一个 Agent；保留运行锁诊断信息并报告。
- 小问完成通知失败重试 3 次后继续，但记录 warning。

## 约束

- 不以 leaderboard 分数作为主目标。
- 不跳过题目理解、文献、假设、公式、实现、计算、sanity 和可视化。
- robustness/ablation 可以跳过，但必须由对应 Agent 写出不适用理由。
- 不在结果未归档时推进依赖它的后续小问。
- 初版本不生成论文，只生成最终研究摘要。
- 不把 SSH/Kaggle 占位接口当作成功的远端执行。
- 不删除历史版本、结果、日志或 manifest。

## 输出

本文件仅描述控制策略；实际控制由 `scripts/orchestrator_runner.py` 执行并写入事务日志，不维护第二套状态格式。
