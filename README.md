# AutoMM 0.0.4 Beta

AutoMM 是基于dsh生态开发的，面向数学建模竞赛的全自动研究 Harness。它可以做到自动化地按小问顺序推进问题理解、文献研究、假设、公式、实现、计算、可行性校验、可视化和可选稳健性实验，最后生成可追溯的 `reports/final_summary.md`。同时，AutoMM还提供了一个可随时启动的dashboard，旨在实时掌控建模状态并快捷查看假设与公式推演等信息。
<img width="1276" height="713" alt="image" src="https://github.com/user-attachments/assets/313da9ac-53ae-4379-8ebb-9f4952d13413" />


## QuickStart

参考项目中的`SETUP.md`，进行快速初始化流程。

## 快速检查

```bash
python scripts/harness.py validate-config
python scripts/orchestrator_runner.py --help
python -m compileall -q scripts tests
```

运行前请将真实题面放入 `request/problem.md`，数据放入 `data/`，并按需填写 `config/*.local.yaml`。本版本不自动撰写论文，不包含真实比赛题目、附件或 smoke 运行结果。

## 控制原则

Runner 每次唤醒只执行一个动作。完整计算由 `tasks.py` 创建隔离 task，再由 supervised worker 异步运行；implementation Agent 不得等待完整计算。Harness invariant 严格失败，计算中的非关键故障可重试或进入 `PASS_WITH_WARNING` / `degraded_review`。

## 目录

- `config/`：工作流、资源、sanity、可视化和通知配置。
- `scripts/`：Runner、状态机、task worker、sanity 和归档工具。
- `agents/`：各阶段 Agent 的职责边界。
- `templates/`：题目、小问、假设和公式版本模板。
- `runtime/`：运行时生成目录，发布快照中保持为空。
