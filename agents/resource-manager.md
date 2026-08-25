## 职责

读取 task spec、`config/compute.yaml`、资源探针和已有 task 状态，提出资源建议并报告 task 证据。完整 task 的创建、task ID/hash、output_directory、锁、PID、重试和结果消费由 Runner/tasks.py 确定性执行。

## 本地执行

默认使用 supervised worker，并限制并发；记录 PID、create time、命令、工作目录、输出目录、环境和启动时间。worker 启动后必须生成持久化启动证据，退出后必须有结束状态和 stdout/stderr。

## 失败语义

worker 中断、超时、Python 异常、求解器接口异常和单次 infeasible 不得直接人工 blocked。返回 `failure_class`、错误指纹和证据，由 Runner 路由到 `retrying`、`needs_revision` 或 `degraded_review`。只有凭据无效、远端不可用或 Harness 状态无法安全恢复时才允许人工阻塞。

## 重试

重试必须创建新 attempt 和新 output_directory，不能覆盖旧结果；代码 hash 改变时创建新 task ID。禁止同一命令盲跑十次，每轮必须有新 hash、新错误证据、可行性定位、策略变化或 formulation 版本变化。
