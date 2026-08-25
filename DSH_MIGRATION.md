# AutoMM 0.0.4-dsh：DeepSeek Harness 适配说明

本版本以 `ver_0.0.2_beta`（最成熟版本）为基底，通过 **LLM Provider 抽象** 把模型调用从
Codex CLI 迁移到 DeepSeek Harness（DSH）的 headless 模式。状态机、事务回滚、失败分类、
计算 task 隔离、sanity/可视化/论文构建等全部 0.0.2 成熟逻辑保持不变。

## 一、改了什么

| 层 | 改动 |
|---|---|
| 模型调用 | 新增 `scripts/automm/llm/`（`base.py`/`dsh.py`/`codex.py`/`__init__.py`）；`agent_runtime.py` 改为通过工厂取 provider，不再硬编码 `codex exec` |
| 配置 | `config/agent_runtime.yaml` 默认 `provider: dsh_headless`，保留 `codex_exec` 作回归/降级后端 |
| 指令文件 | `.codex/agents/` → `agents/`，`.codex/skills/` → `skills/`；剥离所有 agent 的 codex frontmatter（`tools:`/`model:`） |
| 规范文件 | `CODEX.md` → `PROJECT.md`，`AUTORESEARCHER.md` → `RESEARCH_LOOP.md`；`AGENTS.md` 增补指向这两个文件（DSH 会自动加载 `AGENTS.md`） |
| 测试 | `conftest.py`/`test_runner_integration.py`/`test_agent_runtime.py` 迁移；新增 `test_dsh_provider_smoke.py` |

## 二、Provider 抽象

`agent_runtime.py` 的唯一模型耦合点被抽象成 `LLMProvider`：

- `probe()`：探测可执行文件与能力；
- `prepare(prompt, output_path) -> Invocation`：构造命令、stdin、环境、结构化输出位置；
- `extract_response(...) -> dict`：从运行产物提取并解析 JSON。

`config/agent_runtime.yaml` 的 `provider` 字段选择后端：

- `dsh_headless`（默认）：`dsh --profile headless "<task>"`；
- `codex_exec`：0.0.2 原始实现，保留用于回归对比。

## 三、DSH headless 契约（0.1.1-rc.2，已核实源码）

- 任务文本是**唯一位置参数**：`dsh --profile headless "<task>"`，多词自动用空格连接。
- **无** `--model`/`--workspace`/`--cd`/`--output-schema`/`--output-last-message`/`--json`/`--sandbox`/`--approve-for-me`。
- 调用目录即 workspace 根，自动加载该目录的 `AGENTS.md`。
- 默认模型来自 `$DSH_HOME/settings.yaml`（`agent-default-model`），无 CLI 覆盖。
- 工具呈现由环境变量 `DSH_TOOLS_MODE` 决定（`native`/`code`/`both`）；本 harness 用 `native`（read/write/edit/bash/pwsh）。
- 进程把**最后一条非空 assistant 文本**写到 stdout 后退出；`turn/end` 为 `completed` 时退出码 0，否则 1；错误以 `dsh: <code>: <message>` 写 stderr。

因此结构化输出改为：prompt 要求“最终只输出 JSON”→ Python 端 `_parse_json_text`（剥 ``` 围栏 → 取 `{...}` 区间 → `json.loads`）→ `jsonschema` 校验 → `action_id`/上下文校验。

## 四、前置条件（一次性）

1. 安装 DSH：`npm i -g @deepseek-ai/dsh`（确保 `dsh` 在 PATH 上，`dsh --version` 可用）。
2. 首次使用会**自动初始化 headless profile**，写入 `$DSH_HOME/profiles/headless`：
   在普通终端（非 DSH 沙箱）执行一次 `dsh --profile headless --help` 即可。
3. 凭据与默认模型在 `$DSH_HOME/.credentials.yaml` / `$DSH_HOME/settings.yaml`。

> 注意：若整个 harness 是在 DSH 会话内（受 `workspace-write` 沙箱）启动，`dsh --profile headless`
> 初始化会写 `$DSH_HOME`（工作区外）而被拦（`EPERM`）。请先在沙箱外完成第 2/3 步，或把
> `DSH_HOME` 指到项目内并同步凭据。

## 五、真实往返验证（需真实模型 token，人工执行）

```bash
cd ver_0.0.4_dsh
python scripts/harness.py validate-config     # 应全 PASS
dsh --profile headless --help                  # 初始化 headless profile
python scripts/orchestrator_runner.py          # 一次唤醒；Agent 动作会调 dsh headless
```

单个 Agent 的最小验证（用 template-agent，最便宜）：

```bash
python -c "import sys; sys.path.insert(0,'scripts'); from automm.agent_runtime import invoke_agent, new_action_id; from automm.agent_runtime import runtime_config; print(runtime_config()['provider'])"
```

## 六、0.0.3 remote SSH 的关系

0.0.2 基底**已经包含** SSH/Kaggle 计算适配器（`scripts/automm/remote/ssh.py` + `bundle.py`），
与 LLM provider 完全解耦，本版本直接继承，`compute.default_backend: local` 默认、`ssh` 按需启用。
0.0.3-beta 的“本地只做轻量 smoke、计算全走 remote SSH”是独立的计算策略重构（`execution.mode`、
`allow_local_full_compute`、`bootstrap_macos.py`），与本 DSH 适配正交，未并入本版本；若需要可后续合入。
`smoke_runs/remote_dummy_smoke_001` 显示该 SSH 链路本身已通过 dummy 验证。

## 七、测试状态

在含完整依赖的 venv 下（并把 `TMP`/`TEMP` 指到工作区内以通过 DSH 沙箱）：

- 全套件：**71 通过 / 0 失败**。

原先 0.0.2 基线里的 3 个失败已一并修复：

| 失败 | 根因 | 修复 |
|---|---|---|
| `test_remote_adapters.py::test_github_relay_local_bare_repository_roundtrip` | git 在“不记录所有权的文件系统”（E: 盘）上触发 dubious-ownership 保护，`git clone/push` 报 128 | `scripts/automm/remote/github.py` 的 git 命令统一加 `safe.directory=*`；并执行一次性 `git config --global --add safe.directory '*'`（push 会派生 `receive-pack` 子进程，`-c`/env 均不生效，需全局配置） |
| `test_research_visualization.py::test_sanity_numeric_check_warns_for_csv_missing_but_rejects_infinity` | `inspect_numeric_file` 未区分 CSV 空单元格（缺失）与 ±Inf（非法） | `scripts/run_sanity_check.py` 重写：新增 `missing_numeric_count`/`infinite_numeric_count`，CSV 空值按缺失只警告，±Inf 才判 `finite=False` |
| `test_tasks.py::test_task_command_output_must_match_declared_directory` | 断言消息中英文漂移 | `scripts/automm/tasks.py` 的 `--output` 校验消息改为中文，与测试一致 |

## 八、已知限制

- 真实 `dsh --profile headless` 往返尚未在本环境跑通（受 DSH 沙箱 + token 成本约束），需在沙箱外按第五节执行。
- `dsh` 默认模型来自 `settings.yaml`，若需按题目切模型，要改 `settings.yaml` 或用 `dsh` 的 `--patch` 覆盖层。
- `agents/*.md` 的 codex frontmatter 已剥离，但原 `tools:` 声明（如 WebSearch/Glob/Grep/Agent）未映射到 DSH 工具；headless 后端默认挂载 native 工具集，能力以 DSH profile 实际挂载为准。