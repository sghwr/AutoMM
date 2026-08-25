"""构建整题最终研究摘要，不承担论文写作。"""

from __future__ import annotations

from typing import Any

from .common import (
    config_section,
    read_yaml,
    relative,
    resolve_project_path,
    utc_now,
    write_json,
    write_text,
)
from .problems import load_problem, problem_dir, question_manifest
from .tasks import list_tasks


def build_final_summary(problem_id: str) -> dict[str, Any]:
    config = config_section("summary", problem_id)
    problem = load_problem(problem_id)
    if config.get("require_cross_question_review", True) and problem.get("cross_question_review") != "passed":
        raise RuntimeError("跨小问审查未通过，不能生成最终摘要")
    sections = []
    errors: list[str] = []
    tasks = list_tasks()
    figures = read_yaml(problem_dir(problem_id) / "figures.yaml", {"figures": []}).get("figures", [])
    citations = read_yaml(problem_dir(problem_id) / "citations.yaml", {"references": []}).get("references", [])
    for question_id in problem["questions"]:
        _, manifest = question_manifest(problem_id, question_id)
        if manifest.get("stage") != "locally_completed":
            errors.append(f"{question_id} 尚未 locally_completed")
            continue
        accepted = int(manifest.get("accepted_assumption_version", 0))
        version_name = f"assumption_v{accepted:03d}"
        version_dir = problem_dir(problem_id) / question_id / "versions" / version_name
        summary_path = version_dir / "question_summary.md"
        if not summary_path.is_file():
            errors.append(f"{question_id} 缺少 question_summary.md")
            continue
        text = summary_path.read_text(encoding="utf-8").strip()
        if not text or "待填写" in text:
            errors.append(f"{question_id} 的 question_summary.md 仍为空")
        question_tasks = [
            item for item in tasks if item.get("problem_id") == problem_id and item.get("question_id") == question_id
        ]
        question_figures = [
            item
            for item in figures
            if item.get("question_id") == question_id
            and item.get("assumption_version") == version_name
            and item.get("included_in_summary", True)
        ]
        task_lines = "- 配置为不收录任务追踪"
        if config.get("include_task_trace", True):
            task_lines = (
                "\n".join(
                    f"- `{item.get('task_id')}`：{item.get('status')}，阶段 `{item.get('stage')}`"
                    for item in question_tasks
                )
                or "- 无登记计算任务"
            )
        figure_lines = "- 配置为不收录图表索引"
        if config.get("include_figures", True):
            figure_lines = (
                "\n".join(
                    f"- `{item.get('stable_id')}`：{item.get('title')}，`{item.get('path')}`"
                    for item in question_figures
                )
                or "- 无登记图表"
            )
        optional = manifest.get("optional_stages", {})
        sections.append(f"""## {question_id}

- 接受假设版本：`{version_name}`
- 接受公式版本：`formulation_v{int(manifest.get("accepted_formulation_version", 0)):03d}`
- L1-L4 sanity：{manifest.get("sanity", {}).get("level_1_4")}
- L5 sanity：{manifest.get("sanity", {}).get("level_5")}
- 鲁棒性：{optional.get("robustness", {})}
- 消融：{optional.get("ablation", {})}

### 小问总结

{text}

### 任务追踪

{task_lines}

### 图表索引

{figure_lines}
""")
    if errors:
        raise RuntimeError("最终摘要门禁未通过：" + "；".join(errors))
    citation_lines = "- 配置为不收录文献索引"
    if config.get("include_citations", True):
        citation_lines = (
            "\n".join(
                f"- `{item.get('id', '?')}`：{item.get('title', '')}，"
                f"{item.get('source', '')}（{item.get('year', '')}）"
                for item in citations
            )
            or "- 无登记文献"
        )
    output = resolve_project_path(config.get("output", "reports/final_summary.md"))
    content = f"""# {problem_id} 最终研究摘要

- 生成时间：{utc_now()}
- 小问数量：{len(problem["questions"])}
- 跨小问审查：{problem.get("cross_question_review")}
- 本文件是研究结果归档，不是比赛论文。

{chr(10).join(sections)}

## 跨小问一致性

{problem.get("cross_question_review_reason", "已通过，未记录补充说明。")}

## 文献索引

{citation_lines}
"""
    archive = resolve_project_path(
        str(config.get("archive_output_template", "reports/problems/{problem_id}/final_summary.md")).format(
            problem_id=problem_id
        )
    )
    if archive.exists():
        content = archive.read_text(encoding="utf-8")
    else:
        write_text(archive, content)
    write_text(output, content)
    problem["summary_status"] = "built"
    problem["summary_path"] = relative(output)
    problem["summary_archive_path"] = relative(archive)
    problem["summary_built_at"] = utc_now()
    write_json(problem_dir(problem_id) / "problem_state.json", problem)
    return {
        "problem_id": problem_id,
        "summary": relative(output),
        "archive": relative(archive),
        "questions": len(problem["questions"]),
    }
