---
name: mathmodeling-monitor
description: 查看题目、小问、阶段、任务和本地/远端算力状态。
---

# Math Modeling Monitor

## 执行

运行 `python scripts/harness.py reconcile`，再运行 `python scripts/task_monitor.py`。

## 本地检查

- 工作流控制状态和 orchestrator 锁；
- 当前题目、小问、假设版本和阶段；
- queued/running/succeeded/failed/timed_out 数量；
- running PID 是否存活；
- 相同 task ID 是否重复；
- 输出锁、最近日志、返回码和未消费结果；
- stale/unresolved/needs_revision 状态。

## 输出

固定报告控制状态、当前小问、当前阶段、并发槽位、任务表、阻塞项、下一动作和下一唤醒。Monitor 只对账，不改变假设、公式或阶段。
