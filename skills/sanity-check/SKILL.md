---
name: sanity-check
description: 对数学模型和结果执行合理性、可行性、引用和跨小问检查。
---

# Sanity Check

## 触发

- 主 computation 结束：Level 1–4；
- robustness 完成：Level 6；
- 所有小问 locally completed：Level 5；
- 最终摘要前：引用和产物完整性复核。

## 执行

1. 确认 problem/question/assumption/formulation/task ID 明确。
2. 读取配置和所有证据，不从聊天上下文补缺失数据。
3. 对可自动检查项运行 `scripts/run_sanity_check.py`；对边界、极限、常识和文献由 sanity-checker 给出论证。
4. 每层分别给状态和证据，最后生成 overall。
5. 写 `sanity_report.md` 和 machine-readable summary。
6. 返回 failure_type 和唯一 return_to_stage。

## 硬门禁

关键假设来源、物理/经济常识、题目硬约束和跨小问一致性。硬失败不能用平均分抵消。

## 状态

- PASS：推进。
- PASS_WITH_WARNING：推进并记录技术债。
- NEEDS_REVISION：当前版本可修复。
- VERSION_REJECTED：拒绝当前版本，创建下一版本。

## 禁止

不得修改模型或代码；不得以 fancy、拟合好或图表好看为理由放宽门禁；不得输出没有失败类型的笼统 FAIL。
