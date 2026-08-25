# AutoMM Agent 规则

> 完整项目指南见 `PROJECT.md`；自动研究循环见 `RESEARCH_LOOP.md`。两者是本文档的补充规范，冲突时以更具体的阶段/响应约束为准。

- 使用简体中文；公式、代码标识符和参考文献标题可保留原文。
- 先读取题面、配置和已有产物，再修改当前阶段的文件。
- 不直接编辑 `runtime/workflow_state.json` 或受保护的 manifest 字段，状态变更必须通过响应 `commands`。
- 不覆盖假设、公式、结果、日志和结论历史；当前假设版本内的工作代码可以更新。
- implementation Agent 只做静态检查和小型探针，不运行完整数据集或等待 worker。
- 计算必须使用隔离 task、独立输出目录和 supervised worker。
- 任何 Harness invariant 都必须严格失败；模型计算的非关键故障应按 failure class 恢复或降级审查。
- 最终响应必须是符合 `config/agent_response.schema.json` 的 JSON。