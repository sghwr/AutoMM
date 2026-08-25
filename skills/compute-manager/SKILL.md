---
name: compute-manager
description: 透明管理本地、Kaggle 和 SSH 任务，负责同步、轮询和去重。
---

# Compute Manager

## 输入任务描述

必须包含 problem_id、question_id、stage、command 数组、working_directory、output_directory、code/config/input hash、assumption_version、formulation_version、随机种子和超时。

## Task ID

按规范化 JSON 计算 SHA-256 短 ID。任一代码、输入、配置或版本变化都会产生新 ID。相同 ID 的 running/succeeded 默认阻止；`--force` 必须同时提供 `--force-reason`，遵守失败类型的重试上限，并改用新输出目录，原 attempt 和结果不覆盖。

## 本地并发

有效槽位为配置上限、CPU 核数减一和可用内存槽位的最小值。没有槽位则 queued。强制并发必须记录原因。

## 提交

1. 通过 `python scripts/compute_dispatcher.py submit ... -- <命令数组>` 提交；校验任务描述和路径均在项目内。
2. 提交器强制对 Python 代码执行 `compileall` 和 `ruff`，并要求输出目录位于指定假设版本内。
3. 原子创建任务目录与输出锁。
4. 写 task.json/status.json。
5. 由 dispatcher 启动独立 worker，记录 PID。
6. stdout/stderr 写任务目录，不混入其他任务。
7. 异步返回 task ID，不等待完成。

## 监控和消费

`python scripts/task_monitor.py` 检查 PID、返回码和输出锁；`python scripts/compute_dispatcher.py reconcile` 可只做任务对账。成功任务由 Orchestrator 消费并归档；监控器不能自行推进小问阶段。

## 失败

代码错误修复一次；超时调整资源后两次；中断保留日志和 attempt。不得静默覆盖失败结果。

## 远端

`ssh` 和 `kaggle` 配置保留，但本版本适配器未实现。请求远端时返回 `NOT_IMPLEMENTED` 和所需配置，不得打印假成功。
