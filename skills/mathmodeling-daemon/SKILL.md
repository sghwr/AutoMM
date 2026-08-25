---
name: mathmodeling-daemon
description: 启动、查询和停止 AutoMM 全自动研究循环。
---

# Math Modeling Daemon

## 用途

用 Python daemon 启动、查询、暂停、恢复或停止全自动循环。它不执行具体建模工作。

## 启动前检查

1. `python scripts/harness.py validate-config` 通过。
2. `request/problem.md` 存在且不是占位内容。
3. `config/project.yaml.active_problem` 已设置，或先运行 `init-problem`。
4. `runtime/workflow_state.json` 可解析。
5. 不存在有效的另一个 orchestrator 锁。

## 启动

使用 `python scripts/orchestrator_daemon.py`；调试单步使用 `python scripts/orchestrator_daemon.py --once`。

## 控制

- 暂停：`python scripts/harness.py control PAUSE`。
- 停止：`python scripts/harness.py control STOP`。
- 恢复：`python scripts/harness.py control RESUME`。
- 状态：`python scripts/harness.py status`。

PAUSE/STOP 不杀运行任务。STOP 取消 queued；RESUME 必须先 reconcile。

## 异常恢复

锁超时不能直接删除：先检查锁持有 PID、任务 PID 和最后更新时间。恢复后从机器状态中第一个不满足完成条件的阶段继续，不从头重跑。

## 输出

报告 loop 是否启动、活动题目、控制状态、锁状态、运行/排队任务、当前小问/阶段和下次唤醒。
