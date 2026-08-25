# 题目目录

一个 harness 同时只激活一个 `problems/<problem_id>/`。目录由 `python scripts/harness.py init-problem` 创建。

```text
problem_state.json
problem_understanding.md
dependency_graph.yaml
global_symbols.yaml
citations.yaml
figures.yaml
prob01/
  question_manifest.yaml
  shared/
    problem_understanding.md
    literature.md
    literature_pool.yaml
  versions/
    assumption_v001/
      version.yaml
      assumptions.md
      formulation.md
      formula_validation.md
      implementation.md
      code/
      results/
      figures/
      robustness/
      ablations/
      sanity_report.md
      question_summary.md
      archive_manifest.json
```

`shared/` 保存小问级不随假设版本改变的资料；`versions/` 保存不可覆盖的假设版本。结果、日志和归档按 task ID 保留。同一版本内工作代码可以更新。
