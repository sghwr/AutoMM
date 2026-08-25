# AutoMM 0.0.4-dsh 来源说明

本版本以 `ver_0.0.2_beta`（最成熟版本）为基底，完成 DeepSeek Harness（DSH）适配，并落地「本地编排 + 远端 SSH 计算」。

## 主要变更

1. **LLM 后端 Provider 抽象**：新增 `scripts/automm/llm/`（base/dsh/codex），`agent_runtime.yaml` 默认 `provider: dsh_headless`，`codex_exec` 保留为回归后端。
2. **远端计算自动路由**：`compute.default_backend` 为唯一权威来源；`start_queued`/`reconcile_tasks` 对 ssh/kaggle 走 `submit_remote`/`reconcile_remote`，local 走 `task_worker.py`（已合入 full smoke 验证过的 hot-fix）。
3. **指令/配置迁移**：`.codex/agents`→`agents/`、`.codex/skills`→`skills/`；`CODEX.md`→`PROJECT.md`、`AUTORESEARCHER.md`→`RESEARCH_LOOP.md`。
4. **一键配置脚本**：`scripts/configure_remote.py`（非侵入式，交互配置 SSH / QQ 邮箱 / 计算模式）。
5. **实时监测台**：`monitor/`（只读 localhost dashboard，黑色 control-panel 风）。
6. **完整配置文档**：`SETUP.md`（从零 clone 到启动 full smoke 的 step-by-step）。

本目录不含真实比赛题目、附件、账号、attempt、smoke 日志、归档运行结果或远端凭据；`runtime/` 仅保留空目录结构，测试只使用合成 fixture。

版本：`0.0.4-dsh`