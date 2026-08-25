---
name: artifact-archiver
description: 归档数学建模小问的假设、公式、代码、结果、图表、日志和检查报告。
---

# Artifact Archiver

## 归档单位

每个假设版本独立归档。shared 资料与版本产物分开。manifest 记录相对路径、SHA-256、字节数、task ID、输入、配置、版本、种子、环境和时间。

## 规则

- 历史假设版本、结果、日志和 manifest 不覆盖。
- 同一版本工作代码可以更新，但归档时记录新 hash。
- 失败结果也归档。
- 清理只允许缓存、临时转换和可重建中间物；先移动到 `.trash/`，保留 7 天并写日志。

运行 `python scripts/archive_artifacts.py --question-dir <相对路径>` 生成 manifest。路径必须位于项目内。
