# CLI 速查

所有命令从项目根目录、已激活的 `.venv` 中运行。下列示例使用相对路径；具体参数以 `--help` 和当前脚本实现为准。

## 项目与状态

```text
python scripts/harness.py validate-config
python scripts/harness.py init-problem --problem-id demo --questions 4
python scripts/harness.py status
python scripts/harness.py next-action
python scripts/harness.py reconcile
```

`validate-config` 用于启动前检查；`init-problem` 只执行一次；`status` 展示机器状态；`next-action` 只看策略；`reconcile` 对账控制 flag、任务和 stale。

## Orchestrator

```text
python scripts/orchestrator_runner.py
python scripts/orchestrator_daemon.py
```

Runner 是单步入口，适合 smoke 和排错。daemon 持续唤醒 Runner。测试前确认不存在另一个 daemon，避免误判 pending wakeup。

## 任务与资源

```text
python scripts/compute_dispatcher.py list
python scripts/task_monitor.py
python scripts/resource_probe.py
```

创建任务的参数较多，应由 Agent 或明确的测试 fixture 生成；不要手填错误版本绕过预检。monitor 只对账，不判断研究合理性。

## 文献、图表和总结

```text
python scripts/research_manager.py status --problem-id demo --question-id prob01
python scripts/generate_visualizations.py check-style
python scripts/build_final_summary.py --problem-id demo
python scripts/archive_artifacts.py --problem-id demo
```

最终摘要命令当前承担归档索引构建。只有小问总结和跨问审查闭合后才执行。

## 邮件和控制

```text
python scripts/notify_email.py poll
python scripts/notify_email.py send --kind question-complete --message "测试" --problem-id demo --question-id prob01
```

真实发送前核对收件人和测试内容。控制邮件由 poll 解析，不能执行任意邮件正文。

## 受控状态命令

Agent 通常通过 JSON commands 请求以下操作：登记产物、sanity、可选阶段、结论、版本决策、图表复核、清除 stale、追加 ledger、跨问审查和迁移阶段。人工调试时可查看 `python scripts/harness.py --help` 获取精确参数。

不要直接编辑 `runtime/workflow_state.json` 代替这些命令。命令失败时保留 stdout/stderr 和事务日志，再修复输入。

## 清理与同步

```text
python scripts/cleanup_manager.py list
python scripts/sync_github.py --help
python scripts/sync_remote.py --help
```

清理执行属于可能影响文件的操作，先列出精确目标。GitHub/SSH/Kaggle adapter 在真实 smoke 前只按帮助信息和实现状态判断，不把占位返回当成功。

## 建议的诊断顺序

```text
validate-config
→ status / next-action
→ transactions 与 events
→ action stdout/stderr/response
→ task status/log
→ manifest 与产物路径
→ reconcile
```

先定位最早失败点，再修复；不要从最终状态反向猜测。
