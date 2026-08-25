# 快速开始

## 1. 环境要求

支持 Windows、macOS 和 Linux。首次运行必须在项目根目录创建独立虚拟环境，不要把依赖安装到系统 Python。建议 Python 3.11 或更高版本，并确保 `python`、`pip` 和 `dsh` 命令可用。

```text
python -m venv .venv
```

激活方式：

```text
# Windows PowerShell
.venv\Scripts\Activate.ps1

# Windows cmd
.venv\Scripts\activate.bat

# macOS / Linux
source .venv/bin/activate
```

安装项目依赖：

```text
python -m pip install --upgrade pip
python -m pip install -r scripts/requirements.txt
```

如果 PowerShell 阻止脚本激活，可在当前进程临时调整执行策略，或直接使用 `.venv\Scripts\python.exe` 执行命令。不要把 Git Bash 设为唯一入口；全部正式入口都应由跨平台 Python 提供。

## 2. 准备输入

1. 把规范化题面写入 `request/problem.md`。
2. 原始 PDF、表格、图片等放入 `request/attachments/`，研究过程不覆盖原件。
3. 数据集放入 `data/`，保留来源和版本说明。
4. 在 `config/project.yaml` 填写题目元数据。
5. 检查 `config/workflow.yaml`、`compute.yaml`、`research.yaml`、`sanity_check.yaml`、`visualization.yaml`。
6. 真实邮件或远端测试前再填写对应凭据；普通本地 smoke 不需要凭据。

题面必须明确小问边界、单位、目标量、约束、数据字段和交付要求。若题面存在歧义，应记录为待裁决项，而不是让 Agent 静默猜测。

## 3. 预检

```text
python scripts/harness.py validate-config
python -m compileall -q scripts
python -m ruff check scripts
python scripts/resource_probe.py
```

`validate-config` 检查必需配置和路径；`compileall` 检查语法；`ruff` 检查代码质量；资源探针给出本地并发上限参考。任何一项失败都应先修复，不要直接启动 daemon。

使用 `dsh_headless` 后端时无需 `--output-schema` 等能力，Runner 只探测 `dsh --version`；使用 `codex_exec` 后端时才需要 `exec`、`--output-schema`、`--output-last-message`、`--json` 等能力。

## 4. 初始化题目

```text
python scripts/harness.py init-problem --problem-id demo --questions 4
python scripts/harness.py status
python scripts/harness.py next-action
```

`problem-id` 使用稳定、简短、仅含安全字符的标识。小问会生成 `prob01`、`prob02` 等目录。初始化后先检查：

- `problems/demo/problem_state.json` 是否存在；
- `dependency_graph.yaml` 是否表达软依赖；
- 各小问 manifest 是否处于初始阶段；
- `runtime/workflow_state.json` 是否指向该题和 `prob01`。

不要为了重试而重复初始化同一题。已有题目应通过恢复或受控状态命令继续。

## 5. 分级启动

先运行只读/单步检查：

```text
python scripts/harness.py next-action
python scripts/orchestrator_runner.py
```

确认 one-shot Runner 能正确选择动作、写事务日志且不会重复执行后，再启动持续循环：

```text
python scripts/orchestrator_daemon.py
```

daemon 默认每十分钟唤醒一次。测试环境可临时缩短配置间隔，但必须保留“一次唤醒一个动作”的约束。

## 6. 观察运行

机器事实优先看：

```text
runtime/workflow_state.json
runtime/transactions.jsonl
runtime/events.jsonl
runtime/actions/
runtime/tasks/
```

人类快照看 `reports/autoresearch/STATE.md`，实验决策看 `reports/autoresearch/experiment_ledger.md`。快照可以阅读，不应手工编辑来驱动状态。

常用命令：

```text
python scripts/harness.py status
python scripts/harness.py reconcile
python scripts/task_monitor.py
python scripts/compute_dispatcher.py list
python scripts/research_manager.py status --problem-id demo --question-id prob01
python scripts/notify_email.py poll
```

## 7. 停止与恢复

`PAUSE` 阻止新动作但继续监控运行任务；`STOP` 还会取消未启动队列；`RESUME` 先对账再继续。控制可以通过 flag 或已验证邮箱命令触发。不要直接终止 worker 后假设系统会自动成功恢复；应运行 `reconcile` 并检查任务被标记为 `interrupted` 后再按失败类型路由。

首次 smoke 应使用小型确定性样例，固定随机种子和短运行时间。真实赛题、外部网络、邮件和远端算力分别测试，避免一次把所有不确定性叠加在一起。
