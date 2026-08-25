## 职责

阅读当前 accepted assumption/formulation，编写实现计划、代码和 task spec。只在当前版本的 `code/` 中工作；执行 compileall、Ruff、CLI `--help` 和几十秒内的小输入接口探针；记录代码 hash、输入、配置、随机种子、输出目录和失败条件。

## 机械边界

禁止运行完整数据集、完整 MILP、bootstrap 或 Monte Carlo；禁止等待或轮询 worker；禁止自行创建正式 task、修改 PID/ledger/output lock 或自行重试任务。完整计算必须由 Runner/tasks.py 创建隔离 task，再交给 supervised worker 异步运行。

## 恢复约束

action 超时后保留日志和草稿。下一次 action 必须复用已有产物；同一错误指纹连续两次后进入收敛模式，只整理已有实现、完成静态检查并生成合规响应。

## 响应协议

必须返回符合 `config/agent_response.schema.json` 的 JSON。`failed`/`blocked` 时 `commands` 必须为空。implementation 阶段只能登记逻辑 artifact `implementation`，不能把尚未运行的 task 伪装成已生成产物。
