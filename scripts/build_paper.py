"""组装论文草稿，校验引用/图片闭合，并在邮件批准后生成最终稿。"""

from __future__ import annotations

import argparse
import json
import re
import shutil
from pathlib import Path

from automm.common import ROOT, read_json, read_yaml, relative, resolve_project_path, utc_now, write_json, write_text
from automm.problems import load_problem, problem_dir, question_manifest
from automm.state import load_state

CITATION_RE = re.compile(r"\[@([A-Za-z0-9_.:-]+)\]")


def active_problem_id(value: str | None) -> str:
    problem_id = value or load_state().get("active_problem")
    if not problem_id:
        raise SystemExit("没有活动题目，请传入 --problem-id")
    return problem_id


def draft(problem_id: str, output_arg: str | None) -> Path:
    config = read_yaml(ROOT / "config" / "paper.yaml")
    problem = load_problem(problem_id)
    metadata = read_yaml(ROOT / "config" / "project.yaml").get("metadata", {})
    request = (ROOT / "request" / "problem.md").read_text(encoding="utf-8")
    sections = []
    for index, question_id in enumerate(problem["questions"], 1):
        _, manifest = question_manifest(problem_id, question_id)
        version = int(manifest.get("active_assumption_version", 0))
        summary = (
            problem_dir(problem_id) / question_id / "versions" / f"assumption_v{version:03d}" / "question_summary.md"
        )
        content = summary.read_text(encoding="utf-8") if summary.exists() else "> 待 paper-writer 根据归档产物撰写。"
        sections.append(f"## {index + 2} {question_id}\n\n{content}\n")
    citations = read_yaml(problem_dir(problem_id) / "citations.yaml", {"references": []}).get("references", [])
    reference_text = (
        "\n".join(
            f"[{item.get('id', '?')}] {item.get('authors', '')}. "
            f"{item.get('title', '')}. {item.get('source', '')}, {item.get('year', '')}."
            for item in citations
        )
        or "> 待补充并按 GB/T 7714 校验。"
    )
    title = metadata.get("competition_name") or problem_id
    text = f"""# {title}

## 摘要

> 待 paper-writer 结合全部小问结果撰写摘要、关键词与模型评价。

## 1 问题重述与符号说明

{request}

## 2 数据与建模假设

> 汇总各小问已接受假设版本；关键假设必须带 `[@引用ID]`。

{chr(10).join(sections)}
## {len(sections) + 3} 敏感性、鲁棒性与消融分析

> 汇总已执行实验以及有理由跳过的项目。

## {len(sections) + 4} 模型评价与不足

> 待撰写。

## 参考文献

{reference_text}
"""
    output = resolve_project_path(output_arg or config.get("draft_output", "reports/paper/draft_paper.md"))
    write_text(output, text)
    return output


def validate(problem_id: str, draft_path: Path, *, update_problem_status: bool = True) -> dict:
    text = draft_path.read_text(encoding="utf-8")
    errors: list[str] = []
    if "> 待" in text or "{{" in text or "}}" in text:
        errors.append("正文仍包含待写占位符")
    for heading in ("## 摘要", "## 1 问题重述与符号说明", "## 参考文献"):
        if heading not in text:
            errors.append(f"缺少章节：{heading}")
    problem = load_problem(problem_id)
    for question_id in problem["questions"]:
        if question_id not in text:
            errors.append(f"正文缺少小问：{question_id}")
    registry = read_yaml(problem_dir(problem_id) / "citations.yaml", {"references": []}).get("references", [])
    known_ids = {str(item.get("id")) for item in registry if item.get("id")}
    used_ids = set(CITATION_RE.findall(text))
    if not registry:
        errors.append("参考文献登记为空")
    if not used_ids:
        errors.append("正文没有 `[@引用ID]` 格式的引用")
    for citation_id in sorted(used_ids - known_ids):
        errors.append(f"正文引用未登记：{citation_id}")
    for item in registry:
        citation_id = str(item.get("id", ""))
        if item.get("used_by") and citation_id not in used_ids:
            errors.append(f"登记为 used_by 但正文未引用：{citation_id}")
        for required in ("id", "title", "year", "source"):
            if not item.get(required):
                errors.append(f"参考文献 {citation_id or '?'} 缺少字段 {required}")
    figures = read_yaml(problem_dir(problem_id) / "figures.yaml", {"figures": []}).get("figures", [])
    included = [item for item in figures if item.get("included_in_paper")]
    for question_id in problem["questions"]:
        if not any(item.get("question_id") == question_id for item in included):
            errors.append(f"{question_id} 没有任何图表进入论文")
    for item in included:
        path = item.get("path")
        if not path or not resolve_project_path(path).is_file():
            errors.append(f"论文图表文件不存在：{item.get('stable_id', '?')}")
        if item.get("stable_id") not in text:
            errors.append(f"论文图表未在正文按 stable_id 出现：{item.get('stable_id', '?')}")
    result = {
        "checked_at": utc_now(),
        "problem_id": problem_id,
        "draft": relative(draft_path),
        "status": "PASS" if not errors else "NEEDS_REVISION",
        "errors": errors,
        "citation_ids_used": sorted(used_ids),
        "included_figure_count": len(included),
    }
    write_json(ROOT / "reports" / "paper" / "validation.json", result)
    if result["status"] == "PASS" and update_problem_status:
        problem["paper_status"] = "draft_ready"
        write_json(problem_dir(problem_id) / "problem_state.json", problem)
    return result


def finalize(problem_id: str, draft_path: Path, approval_arg: str | None, output_arg: str | None) -> Path:
    config = read_yaml(ROOT / "config" / "paper.yaml")
    state = load_state()
    request_id = state.get("last_approved_request_id") or state.get("awaiting_request_id")
    if approval_arg:
        approval_path = resolve_project_path(approval_arg, must_exist=True)
    elif request_id:
        approval_path = ROOT / "runtime" / "email" / "approvals" / f"{request_id}.json"
    else:
        raise SystemExit("没有待确认 request_id，拒绝生成最终论文")
    approval = read_json(approval_path)
    if approval.get("command") != "APPROVE":
        raise SystemExit("批准记录不是 APPROVE，拒绝生成最终论文")
    if request_id and approval.get("request_id") != request_id:
        raise SystemExit("批准记录 request_id 与当前请求不一致")
    problem = load_problem(problem_id)
    if problem.get("paper_status") != "approved":
        raise SystemExit("problem_state.paper_status 不是 approved")
    result = validate(problem_id, draft_path, update_problem_status=False)
    if result["status"] != "PASS":
        raise SystemExit("论文校验未通过，拒绝生成最终论文")
    output = resolve_project_path(output_arg or config.get("output", "reports/paper/final_paper.md"))
    output.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(draft_path, output)
    problem["paper_status"] = "finalized"
    write_json(problem_dir(problem_id) / "problem_state.json", problem)
    return output


def main() -> None:
    if not read_yaml(ROOT / "config" / "paper.yaml").get("enabled", False):
        raise SystemExit("DISABLED: 初版本不提供论文生成，只生成 reports/final_summary.md")
    parser = argparse.ArgumentParser(description="AutoMM 论文构建")
    sub = parser.add_subparsers(dest="action", required=True)
    for name in ("draft", "validate", "final"):
        command = sub.add_parser(name)
        command.add_argument("--problem-id")
        command.add_argument("--draft")
        command.add_argument("--output")
        if name == "final":
            command.add_argument("--approval-file")
    args = parser.parse_args()
    problem_id = active_problem_id(args.problem_id)
    if args.action == "draft":
        print(relative(draft(problem_id, args.output)))
        return
    config = read_yaml(ROOT / "config" / "paper.yaml")
    draft_path = resolve_project_path(
        args.draft or config.get("draft_output", "reports/paper/draft_paper.md"), must_exist=True
    )
    if args.action == "validate":
        result = validate(problem_id, draft_path)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        raise SystemExit(0 if result["status"] == "PASS" else 2)
    print(relative(finalize(problem_id, draft_path, args.approval_file, args.output)))


if __name__ == "__main__":
    main()
