# AutoMM 0.0.4-dsh 配置教程

> 面向 Windows + PowerShell。从「刚 clone 仓库」走到「全部配置完成 + 拿到启动 prompt」。
> 全程不需要改任何 harness 源码；ssh密钥/题目/数据都由你手动放置。
> 本教程默认模式选择为ssh，local模式同理
---

## 0. 准备&环境说明

| 需要 | 说明 / 如何确认 |
|---|---|
| Windows + PowerShell | 本机 |
| Python 3.11+ | `python --version`（3.13 已实测） |
| uv（推荐，可选） | `uv --version`；没有也能用 `python -m venv` + `pip` |
| Node.js + npm | `node --version`（装 dsh 用） |
| DeepSeek API 凭据 | DSH 调用模型用，见第 2 步 |
| 一台 Linux SSH 服务器 | 可 SSH + SFTP，装好 Python 3.11+ 与 numpy/pandas/scipy/openpyxl |
| QQ 邮箱 + 授权码 | 可选，用于通知；授权码 ≠ 登录密码 |
| 题目 + 数据文件 | 仓库里**不含**真实数据，需你自备，见第 3 步 |

---

## 1. 克隆仓库

```powershell
git clone <repo-url> AutoMM
cd AutoMM
```

> 之后所有命令都在这个目录下执行（注意启动项目文件下的venv）。

---

## 2. 安装并初始化 DSH（模型后端）

DSH 是 Node 命令，与 Python venv 无关。

```powershell
npm i -g @deepseek-ai/dsh
dsh --version                    # 应打印版本号（如 0.1.1-rc.2）
dsh --profile headless --help    # 首次会自动初始化 headless profile
```

确认模型能通（这一步会消耗一点点 token）：

```powershell
dsh --profile headless "只输出 JSON 对象 {\"status\":\"ok\"}，不要解释"
```

预期：stdout 打印 `{"status": "ok"}`，退出码 0。

> 模型与凭据：默认模型在 `$env:DSH_HOME\settings.yaml`（`agent-default-model`），
> API 凭据在 `$env:DSH_HOME\.credentials.yaml`（`refs.DEEPSEEK_API_KEY`）。
> 若还没配置，先跑一次 `dsh web` 登录，或手动填这两个文件。

### 2.1 安装 ds-godmod 预设（headless 0-let-me 需要）

本仓库通过 submodule 引用 `echo-xianyu/dsh-godmod`：`extern/dsh-godmod`。
克隆后需初始化 submodule，并把预设安装到 DSH 用户目录：

```powershell
git submodule update --init --recursive
New-Item -ItemType Directory -Force $env:DSH_HOME\.agent-presets | Out-Null
Copy-Item extern\dsh-godmod $env:DSH_HOME\.agent-presets\ds-godmod -Recurse -Force
```

同时确认 `headless-godmod` profile 的 `cordis.patch.yml` 已注册
`@deepseek-ai/dsh-agent-presets`（`default: ds-godmod`），否则
`ctx.get("agentPresets")` 为 undefined，runner 的 `presets.mount()` 会被静默跳过，
godmod 预设不会生效。AutoMM 的 `config/agent_runtime.yaml` 使用 `profile: headless-godmod`。

---

## 3. 放置题目与数据

仓库按 provenance 约定不含真实比赛数据，需要你手动放入：（以2023年国赛C题为例）

```text
request/problem.md                  # 题面
request/attachments/C题.pdf         # 官方附件
data/附件1.xlsx                     # 数据
data/附件2.xlsx                     # 数据
data/附件3/result1_1.xlsx           # 提交模板
data/附件3/result1_2.xlsx           # 提交模板
data/附件3/result2.xlsx             # 提交模板
```

---

## 4. 创建 Python venv 并装依赖

用 uv（速度较快）：

```powershell
uv venv
.\.venv\Scripts\Activate.ps1
uv pip install -r scripts\requirements.txt
```

不用 uv：

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r scripts\requirements.txt
```

激活成功后命令行前缀会变成 `(.venv)`。验证：

```powershell
python -c "import numpy, pandas, scipy, paramiko, jsonschema, psutil; print('deps ok')"
```

> 注意：之后所有 harness 命令都必须用 venv 的 python（激活后直接 `python`，或用
> `.\.venv\Scripts\python.exe`）。用系统 python 会报 `ModuleNotFoundError`。

---

## 5. 一键配置：SSH + 邮箱 + 计算模式

```powershell
python scripts\configure_remote.py
```

脚本会**在开头先让你选计算模式**：

```text
请先选择计算模式：
  local  —— 所有计算在本地跑（本地压力大）
  remote —— 重计算走远端 SSH，本地只做编排 + 轻量 smoke（推荐用于全量）
计算模式 (local/remote) [local]:
```

- 选 `remote` → 接着填 SSH（host/端口/用户名/密码/远端目录），`default_backend` 自动写 `ssh`。
- 选 `local` → 跳过 SSH，`default_backend` 写 `local`。

接着填 QQ 邮箱（SMTP/IMAP/授权码/收发件人/allowed_senders），最后它会问是否探测连接。
> 本项目强制依赖qq邮箱异步确认，所以强烈建议新建一个qq邮箱账号用来发送通知并接受指令。

**只读查看当前配置** ：

```powershell
python scripts\configure_remote.py show
```

> 脚本只写三个 config（`ssh.yaml` / `notifications.yaml` / `compute.yaml`），写前自动备份，
> 不碰任何 `scripts/automm` 逻辑。可反复运行（当前值作为默认）。

### 5.1 邮箱配置

```yaml
smtp_host: smtp.qq.com      
imap_host: imap.qq.com      
password: "<16位授权码>"     # 授权码，不是 QQ 登录密码，具体可以在qq邮箱网页端-设置-账号与安全-安全设置中，找到POP3/IMAP/SMTP/Exchange/CardDAV 服务开启后自行配置
```

---

## 6. 初始化题目

```powershell
python scripts\harness.py init-problem --problem-id <你自己的具体题目> --questions <题目的具体小问数量>
```

预期输出 `problems/题目名称`，并在其下生成 `probxx`。

---

## 7. 逐项顺序自检

```powershell
# 1) 配置校验
python scripts\harness.py validate-config

# 2) SSH 连通 + 远端 Python
python scripts\sync_remote.py --backend ssh probe

# 3) 发一封测试邮件
python scripts\notify_email.py send --kind problem-complete --message "AutoMM 测试邮件"

# 4) 收件测试（会读收件箱，旧控制邮件可能被当作 PAUSE/RESUME 执行，属正常）
python scripts\notify_email.py poll

# 5) 模型往返（已在第 2 步验证过）
```

预期：① 全 `PASS`；② `"status": "ok"` 且 `host_key_sha256` 与配置一致；③ 打印含 `request_id` 的 JSON；④ 打印消息列表。

---

## 8. 启动harness

先单步跑一个动作，确认 dsh headless 真实调用 OK：

```powershell
python scripts\orchestrator_runner.py
```

无报错后，后台持续推进（或 `--once` 逐步）：

```powershell
python scripts\orchestrator_daemon.py
```

然后把文末「附」的**标准化 prompt** 开新 session 贴进去，让它做「调度 + 监控 + 汇报」。

---

## 9. 启动实时 Dashboard（只读监测台，强烈推荐）

full smoke 跑起来后，**另开一个终端**起 dashboard，实时看状态/任务/事件/日志，不用反复敲命令查：

```powershell
.\.venv\Scripts\Activate.ps1
python monitor\monitor.py
```

看到 `AutoMM monitor running at http://127.0.0.1:8765` 后，浏览器打开 **http://127.0.0.1:8765** 即可。

要点：
- **只读、独立进程**：不写文件、不抢锁、不 import automm，可随时启停（Ctrl+C），不影响正在跑的 harness。
- **监测哪个目录**：读它自己所在的目录；想从别处指向另一份 harness，先 `$env:AUTOMM_ROOT = "<目标目录>"` 再启动。
- 页面功能：运行状态徽标、小问/阶段两个滚动窗口、资产树 + markdown/公式查看器、TASKS/EVENTS/DAEMON LOG 三栏。

---
## 附：启动 harness 的标准化 Prompt

```text
你是 AutoMM 全自动数学建模 harness 的调度操作员，负责把一次真实数模竞赛题目完整跑通并汇报结果。

## 一、本次题目（每轮替换此段即可复用）
- 竞赛：2024 高教社杯全国大学生数学建模竞赛 C 题「农作物的种植策略」。
- problem_id：crop_2024；共 3 个小问（prob01/prob02/prob03）。
- 题面：request/problem.md；附件：request/attachments/C题.pdf。
- 数据：data/附件1.xlsx、data/附件2.xlsx、data/附件3/result1_1.xlsx、result1_2.xlsx、result2.xlsx。

## 二、环境与前置状态
- 工作目录：本仓库根目录（用 venv 的 python：.\.venv\Scripts\python.exe）。
- 已配置：LLM=dsh_headless；计算=remote SSH；邮件=QQ；default_backend=ssh。
- 当前：active_problem=crop_2024，current_stage=problem_understanding。

## 三、角色与硬约束
1. 只做「调度 + 监控 + 汇报」，不亲自做建模判断。
2. 绝不直接编辑 runtime/workflow_state.json 或小问 manifest 门禁字段；状态变更只能经 harness commands。
3. 计算必须走隔离 task 且 backend=ssh（本地不跑完整 computation）。
4. 失败按 failure_class 路由：agent_transport/infrastructure_transient→重试；code_runtime→修订；harness_invariant→严格失败并上报；仅凭据/远端不可用/输入缺失才允许人工阻塞。
5. 不覆盖假设、公式、结果、日志、结论历史。

## 四、启动与推进
1. 单步验证：python scripts\orchestrator_runner.py
2. 持续推进：python scripts\orchestrator_daemon.py（或 --once 逐步）

## 五、监控要点
- 阶段：Get-Content runtime\workflow_state.json
- 可读状态：Get-Content reports\autoresearch\STATE.md
- 任务：python scripts\compute_dispatcher.py list --json
- 远端：python scripts\sync_remote.py --backend ssh status --task-id <task_id>
- 日志：Get-Content runtime\daemon\daemon.log -Tail 30
- 动作证据：runtime\actions\<action_id>\

## 六、结束与交付
- 结束条件：current_stage=completed 且 3 小问都过 sanity + 跨小问审查，或 daemon 进入 blocked/idle。
- 汇报：① 每题结论与 result1_1/result1_2/result2.xlsx 路径；② 各阶段 sanity 结论；③ 失败/降级及原因；④ 全程耗时。
- blocked 处置规程（遇到 recovery_status=human_blocked 时）
1. 定位：读 runtime/actions/<action_id>/stdout.log，grep "action_id"，
   比对 Agent 返回的 action_id 与预期 action_id。
2. 若是「action_id 幻觉」（返回了形如 act-cqr-xxx 的自造 ID，且 problem_id/question_id 正确）
   → 复位后继续：
     - python 改 workflow_state.json：recovery_status="normal"、failure_class=null、
       blocking=[]、recovery 重置；
     - 写 runtime/flags/pending_wakeup.flag 唤醒 daemon。
3. 若是「真 harness_invariant」（schema 校验失败 / problem_id 不匹配 / 命令批回滚）则不做变化

## 七、本次属于 full_smoke
- 首次端到端实跑，目标是暴露并修复问题；报错优先带回「阶段 + failure_class + 日志」，不要反复重试同一命令。
```
