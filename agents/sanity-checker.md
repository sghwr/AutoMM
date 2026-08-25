## 检查层级

- Level 1：输入、task、代码、配置、日志、输出和追踪 hash。
- Level 2：数值有限性、范围、边界和约束残差。
- Level 3：量纲、公式、符号与实现一致性。
- Level 4：关键假设的文献支持、常识和极端行为。
- Level 5：跨小问变量、单位、版本、结论方向和数量级。
- Level 6：按题目需要执行 robustness/ablation；可以记录明确理由后跳过。

## 判定

`PASS` 表示硬门禁通过；`PASS_WITH_WARNING` 表示存在技术债但仍有可行、可追踪结果；`NEEDS_REVISION` 表示当前实现可修复；`VERSION_REJECTED` 表示当前假设或模型版本被拒绝。

有可行 incumbent 但未证明全局最优、`mip_gap` 缺失、达到时间上限、Monte Carlo 次数不足或非关键实验失败时，可以 `PASS_WITH_WARNING`，并记录 solver status、约束残差和完整追踪信息。

没有有效结果、关键结果为 NaN/Inf、硬约束违反、单位或维度错误、formulation 与实现不一致、原始数据被修改或追踪链缺失时，必须失败。

Agent action 超时、worker 被回收、SMTP 失败和附加图表失败不属于人工阻塞；应由 Runner 恢复或降级审查。`failed`/`blocked` 响应的 `commands` 必须为空，sanity 产物使用逻辑 key `sanity_check`。
