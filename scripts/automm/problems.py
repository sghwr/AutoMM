"""活动题目、小问和版本目录初始化。"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from .common import ROOT, config_section, hash_json, hash_path, read_yaml, utc_now, write_json, write_text, write_yaml
from .state import load_state, save_state

QUESTION_RE = re.compile(r"^prob\d{2,}$")


def problem_dir(problem_id: str) -> Path:
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]*", problem_id):
        raise ValueError("problem_id 只能包含字母、数字、下划线和连字符")
    return ROOT / "problems" / problem_id


def init_problem(problem_id: str, question_count: int) -> Path:
    if question_count < 1:
        raise ValueError("小问数量至少为 1")
    request = ROOT / "request" / "problem.md"
    if not request.exists():
        raise FileNotFoundError("缺少 request/problem.md")
    request_text = request.read_text(encoding="utf-8").strip()
    if "在此粘贴规范化后的 Markdown 题面" in request_text:
        raise ValueError("request/problem.md 仍是占位内容")
    existing_state = load_state()
    if existing_state.get("active_problem"):
        active = load_problem(existing_state["active_problem"])
        if active.get("status") != "completed" or active.get("summary_status") != "built":
            raise RuntimeError(f"已有未关闭的活动题目：{existing_state['active_problem']}")
    target = problem_dir(problem_id)
    if target.exists():
        raise FileExistsError(f"题目目录已经存在，拒绝覆盖: {target.relative_to(ROOT)}")
    target.mkdir(parents=True, exist_ok=True)
    question_ids = [f"prob{index:02d}" for index in range(1, question_count + 1)]
    problem_state = {
        "problem_id": problem_id,
        "created_at": utc_now(),
        "status": "active",
        "questions": question_ids,
        "current_question": question_ids[0],
        "cross_question_review": "pending",
        "summary_status": "not_started",
        "completion_notification": "pending",
        "completion_notification_attempts": 0,
    }
    write_json(target / "problem_state.json", problem_state)
    write_text(target / "problem_understanding.md", "# 题目理解\n\n待 problem-decomposer 填写。\n")
    write_yaml(target / "global_symbols.yaml", {"symbols": []})
    edges = [
        {
            "from": question_ids[index - 1],
            "to": question_ids[index],
            "type": "soft_conclusion_dependency",
            "conclusion_id": "",
            "version": 0,
            "content_hash": "",
        }
        for index in range(1, len(question_ids))
    ]
    write_yaml(target / "dependency_graph.yaml", {"questions": question_ids, "edges": edges})
    write_yaml(target / "citations.yaml", {"references": []})
    write_yaml(target / "figures.yaml", {"figures": []})
    template = read_yaml(ROOT / "templates" / "question_manifest.yaml")
    for question_id in question_ids:
        qdir = target / question_id
        (qdir / "shared").mkdir(parents=True, exist_ok=True)
        (qdir / "versions").mkdir(parents=True, exist_ok=True)
        manifest = dict(template)
        manifest["problem_id"] = problem_id
        manifest["question_id"] = question_id
        manifest["status"] = "not_started"
        manifest["stage"] = "problem_understanding"
        write_yaml(qdir / "question_manifest.yaml", manifest)
        write_text(qdir / "shared" / "problem_understanding.md", f"# {question_id} 题目理解\n\n待填写。\n")
        write_text(qdir / "shared" / "literature.md", f"# {question_id} 文献研究\n\n待填写。\n")
        write_yaml(qdir / "shared" / "literature_pool.yaml", {"question_id": question_id, "dry": False, "items": []})
    state = existing_state
    state.update(
        {
            "active_problem": problem_id,
            "current_question": question_ids[0],
            "current_stage": "problem_understanding",
            "last_action": f"初始化题目 {problem_id}，共 {question_count} 个小问",
            "blocking": [],
        }
    )
    save_state(state, event="problem_initialized", details={"problem_id": problem_id, "questions": question_ids})
    return target


def load_problem(problem_id: str) -> dict[str, Any]:
    from .common import read_json

    path = problem_dir(problem_id) / "problem_state.json"
    if not path.exists():
        raise FileNotFoundError(f"题目未初始化: {problem_id}")
    return read_json(path)


def question_manifest(problem_id: str, question_id: str) -> tuple[Path, dict[str, Any]]:
    if not QUESTION_RE.fullmatch(question_id):
        raise ValueError(f"小问 ID 格式错误: {question_id}")
    path = problem_dir(problem_id) / question_id / "question_manifest.yaml"
    if not path.exists():
        raise FileNotFoundError(f"小问不存在: {question_id}")
    return path, read_yaml(path)


def update_question(problem_id: str, question_id: str, patch: dict[str, Any]) -> dict[str, Any]:
    path, manifest = question_manifest(problem_id, question_id)
    manifest.update(patch)
    write_yaml(path, manifest)
    return manifest


def create_assumption_version(problem_id: str, question_id: str) -> Path:
    state = load_state()
    if state.get("active_problem") != problem_id:
        raise RuntimeError(f"题目不是当前活动题目：{problem_id}")
    path, manifest = question_manifest(problem_id, question_id)
    current = int(manifest.get("active_assumption_version", 0))
    workflow = config_section("workflow", problem_id, question_id)
    maximum = int(workflow.get("max_assumption_versions", 5))
    if current >= maximum:
        raise RuntimeError(f"{question_id} 已达到假设版本上限 {maximum}")
    number = current + 1
    name = f"assumption_v{number:03d}"
    version_dir = problem_dir(problem_id) / question_id / "versions" / name
    version_dir.mkdir(parents=True, exist_ok=False)
    for subdir in ("code", "results", "figures", "robustness", "ablations", "formulations"):
        (version_dir / subdir).mkdir()
    template = read_yaml(ROOT / "templates" / "assumption_version.yaml")
    template["version"] = name
    template["created_at"] = utc_now()
    template["parent_version"] = f"assumption_v{current:03d}" if current else None
    write_yaml(version_dir / "version.yaml", template)
    for filename, title in (
        ("assumptions.md", "建模假设"),
        ("formulation.md", "数学模型"),
        ("formula_validation.md", "公式验证"),
        ("implementation.md", "实现计划"),
        ("sanity_report.md", "Sanity Check Report"),
        ("question_summary.md", "小问总结"),
    ):
        write_text(version_dir / filename, f"# {title}\n\n待填写。\n")
    manifest["active_assumption_version"] = number
    manifest["active_formulation_version"] = 0
    manifest["accepted_formulation_version"] = 0
    manifest["status"] = "active"
    manifest["stage"] = "assumption_definition"
    write_yaml(path, manifest)
    state["active_problem"] = problem_id
    state["current_question"] = question_id
    state["current_stage"] = "assumption_definition"
    state["last_action"] = f"创建 {question_id}/{name}"
    save_state(
        state,
        event="assumption_version_created",
        details={"problem_id": problem_id, "question_id": question_id, "version": name},
    )
    return version_dir


def create_formulation_version(problem_id: str, question_id: str) -> Path:
    state = load_state()
    if state.get("active_problem") != problem_id:
        raise RuntimeError(f"题目不是当前活动题目：{problem_id}")
    manifest_path, manifest = question_manifest(problem_id, question_id)
    assumption_number = int(manifest.get("active_assumption_version", 0))
    if assumption_number < 1:
        raise RuntimeError("必须先创建假设版本")
    formulation_number = int(manifest.get("active_formulation_version", 0)) + 1
    assumption_name = f"assumption_v{assumption_number:03d}"
    formulation_name = f"formulation_v{formulation_number:03d}"
    assumption_dir = problem_dir(problem_id) / question_id / "versions" / assumption_name
    target = assumption_dir / "formulations" / formulation_name
    target.mkdir(parents=True, exist_ok=False)
    write_text(target / "formulation.md", "# 数学模型\n\n待 mathematical-formulator 填写。\n")
    write_text(target / "formula_validation.md", "# 公式验证\n\n待填写量纲、边界、极限和可解性检查。\n")
    write_yaml(target / "parameters.yaml", {"parameters": []})
    formulation = read_yaml(ROOT / "templates" / "formulation_version.yaml")
    formulation.update(
        {
            "version": formulation_name,
            "created_at": utc_now(),
            "parent_version": f"formulation_v{formulation_number - 1:03d}" if formulation_number > 1 else None,
            "assumption_version": assumption_name,
        }
    )
    write_yaml(target / "formulation.yaml", formulation)
    version_path = assumption_dir / "version.yaml"
    version = read_yaml(version_path)
    version.setdefault("formulation_versions", []).append(formulation_name)
    version["active_formulation"] = formulation_name
    write_yaml(version_path, version)
    manifest["active_formulation_version"] = formulation_number
    manifest["stage"] = "mathematical_formulation"
    write_yaml(manifest_path, manifest)
    state["current_question"] = question_id
    state["current_stage"] = "mathematical_formulation"
    state["last_action"] = f"创建 {question_id}/{assumption_name}/{formulation_name}"
    save_state(
        state,
        event="formulation_version_created",
        details={
            "problem_id": problem_id,
            "question_id": question_id,
            "assumption": assumption_name,
            "formulation": formulation_name,
        },
    )
    return target


def _formulation_content_hash(directory: Path) -> str:
    files = ("formulation.md", "formula_validation.md", "parameters.yaml")
    return hash_json({name: hash_path(directory / name) for name in files})


def decide_formulation_version(
    problem_id: str,
    question_id: str,
    decision: str,
    reason: str,
) -> dict[str, Any]:
    """接受或拒绝当前公式版本；历史版本和决策不可覆盖。"""
    if not reason.strip():
        raise ValueError("公式版本决策必须说明理由")
    manifest_path, manifest = question_manifest(problem_id, question_id)
    assumption_number = int(manifest.get("active_assumption_version", 0))
    formulation_number = int(manifest.get("active_formulation_version", 0))
    if assumption_number < 1 or formulation_number < 1:
        raise RuntimeError("当前小问没有活动公式版本")
    assumption_name = f"assumption_v{assumption_number:03d}"
    formulation_name = f"formulation_v{formulation_number:03d}"
    directory = problem_dir(problem_id) / question_id / "versions" / assumption_name / "formulations" / formulation_name
    formulation_path = directory / "formulation.yaml"
    formulation = read_yaml(formulation_path)
    if formulation.get("status") != "candidate":
        raise RuntimeError(f"公式版本已经完成决策：{formulation.get('status')}")
    normalized = decision.upper()
    if normalized not in {"ACCEPT", "REJECT"}:
        raise ValueError("decision 只能是 ACCEPT 或 REJECT")
    formulation.update(
        {
            "status": "accepted" if normalized == "ACCEPT" else "rejected",
            "content_hash": _formulation_content_hash(directory),
            "decision_reason": reason,
            "decided_at": utc_now(),
        }
    )
    write_yaml(formulation_path, formulation)
    assumption_path = directory.parents[1] / "version.yaml"
    assumption = read_yaml(assumption_path)
    if normalized == "ACCEPT":
        manifest["accepted_formulation_version"] = formulation_number
        assumption["accepted_formulation"] = formulation_name
    else:
        manifest["stage"] = "mathematical_formulation"
    write_yaml(assumption_path, assumption)
    write_yaml(manifest_path, manifest)
    if normalized == "ACCEPT":
        from .workflow import transition

        transition(
            target_stage="implementation",
            problem_id=problem_id,
            question_id=question_id,
            reason=f"接受公式版本 {formulation_name}",
        )
    return formulation


def decide_assumption_version(
    problem_id: str,
    question_id: str,
    decision: str,
    reason: str,
) -> dict[str, Any]:
    """接受或拒绝活动假设版本，并执行三连拒刷新与五版本停止策略。"""
    path, manifest = question_manifest(problem_id, question_id)
    number = int(manifest.get("active_assumption_version", 0))
    if number < 1:
        raise RuntimeError("当前小问没有活动假设版本")
    version_path = problem_dir(problem_id) / question_id / "versions" / f"assumption_v{number:03d}" / "version.yaml"
    version = read_yaml(version_path)
    decision = decision.upper()
    if decision not in {"ACCEPT", "REJECT"}:
        raise ValueError("decision 只能是 ACCEPT 或 REJECT")
    if decision == "ACCEPT":
        from .research import check_key_assumptions

        citation_gate = check_key_assumptions(problem_id, question_id)
        if not citation_gate["passed"]:
            raise RuntimeError("关键假设文献门禁未通过：" + "；".join(citation_gate["errors"]))
    version["status"] = "accepted" if decision == "ACCEPT" else "rejected"
    version["decision_reason"] = reason
    version["decided_at"] = utc_now()
    write_yaml(version_path, version)
    if decision == "ACCEPT":
        manifest["consecutive_rejections"] = 0
        manifest["literature_refresh_required"] = False
        manifest["accepted_assumption_version"] = number
        write_yaml(path, manifest)
        from .workflow import transition

        transition(
            target_stage="mathematical_formulation",
            problem_id=problem_id,
            question_id=question_id,
            reason=f"接受假设版本 assumption_v{number:03d}",
        )
        return manifest

    workflow = config_section("workflow", problem_id, question_id)
    maximum = int(workflow.get("max_assumption_versions", 5))
    threshold = int(workflow.get("rejected_versions_before_research_refresh", 3))
    manifest["consecutive_rejections"] = int(manifest.get("consecutive_rejections", 0)) + 1
    if number >= maximum:
        manifest["status"] = "unresolved"
        manifest["stage"] = "assumption_definition"
        write_yaml(path, manifest)
        problem = load_problem(problem_id)
        problem["status"] = "unresolved"
        problem["unresolved_question"] = question_id
        write_json(problem_dir(problem_id) / "problem_state.json", problem)
        state = load_state()
        state["control"] = "stopped"
        state["blocking"] = [f"{question_id} 已拒绝 {maximum} 个假设版本，整题停止"]
        save_state(state, event="problem_unresolved", details={"problem_id": problem_id, "question_id": question_id})
    elif manifest["consecutive_rejections"] >= threshold:
        manifest["literature_refresh_required"] = True
        manifest["literature_refreshes"] = int(manifest.get("literature_refreshes", 0)) + 1
        manifest["consecutive_rejections"] = 0
        manifest["stage"] = "literature_review"
        write_yaml(path, manifest)
        state = load_state()
        state["current_stage"] = "literature_review"
        state["last_action"] = f"{question_id} 连续拒绝达到阈值，刷新文献池"
        save_state(state, event="literature_refresh_required", details={"question_id": question_id, "version": number})
    else:
        manifest["stage"] = "assumption_definition"
        write_yaml(path, manifest)
        state = load_state()
        state["current_question"] = question_id
        state["current_stage"] = "assumption_definition"
        state["last_action"] = f"拒绝 {question_id}/assumption_v{number:03d}，返回假设定义"
        save_state(state, event="assumption_version_rejected", details={"question_id": question_id, "version": number})
    return manifest
