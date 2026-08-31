"""全自动工作流的单次唤醒决策与阶段迁移。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .common import ROOT, config_section, hash_json, read_json, read_yaml, utc_now, write_json, write_text, write_yaml
from .problems import decide_assumption_version, load_problem, problem_dir, question_manifest, update_question
from .state import load_state, save_state
from .tasks import TERMINAL, list_task_groups, list_tasks, reconcile_tasks, start_queued


AGENT_BY_STAGE = {
    "problem_understanding": "problem-decomposer",
    "literature_review": "literature-researcher",
    "assumption_definition": "assumption-manager",
    "mathematical_formulation": "mathematical-formulator",
    "implementation": "implementation-agent",
    "computation": "resource-manager",
    "sanity_check": "sanity-checker",
    "visualization": "visualization-agent",
    "robustness": "robustness-analyst",
    "ablation": "ablation-analyst",
    "cross_question_review": "cross-question-reviewer",
}


def stages(problem_id: str | None = None, question_id: str | None = None) -> list[str]:
    return list(config_section("workflow", problem_id, question_id).get("stages", []))


def _action(policy: str, action: str, reason: str, **fields: Any) -> dict[str, Any]:
    return {"policy": policy, "action": action, "reason": reason, **fields}


def _question_tasks(problem_id: str, question_id: str) -> list[dict[str, Any]]:
    return [
        task
        for task in list_tasks()
        if task.get("problem_id") == problem_id and task.get("question_id") == question_id
    ]


def question_summary_path(problem_id: str, question_id: str) -> Path:
    """返回当前接受假设版本的小问总结路径。"""
    _, manifest = question_manifest(problem_id, question_id)
    accepted = int(manifest.get("accepted_assumption_version", 0))
    if accepted < 1:
        raise ValueError(f"{question_id} 没有已接受的假设版本，无法定位 question_summary.md")
    return problem_dir(problem_id) / question_id / "versions" / f"assumption_v{accepted:03d}" / "question_summary.md"


def _summary_has_substance(text: str) -> bool:
    stripped = text.strip()
    if not stripped or "待填写" in stripped:
        return False
    # 只有标题没有实质内容的占位文件也视为未填写。
    body_lines = [
        line.strip()
        for line in stripped.splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]
    return bool(body_lines)


def ensure_question_summary(problem_id: str, question_id: str) -> Path:
    """确定性地生成/补全小问总结，补齐缺失的 question_summary.md 机制。

    Agent 可以在版本目录直接写 question_summary.md；若门禁执行时仍为占位或缺失，
    Runner 会依据 manifest 中的结论/sanity/产物/任务记录生成可追溯的确定性初稿。
    """
    from .tasks import list_tasks as _list_tasks

    path = question_summary_path(problem_id, question_id)
    if path.exists() and _summary_has_substance(path.read_text(encoding="utf-8")):
        return path
    _, manifest = question_manifest(problem_id, question_id)
    accepted = int(manifest.get("accepted_assumption_version", 0))
    formulation = int(manifest.get("accepted_formulation_version", 0))
    conclusion = manifest.get("conclusion", {})
    sanity = manifest.get("sanity", {})
    optional = manifest.get("optional_stages", {})
    artifacts = manifest.get("artifacts", {})
    tasks = [
        item
        for item in _list_tasks()
        if item.get("problem_id") == problem_id and item.get("question_id") == question_id
    ]
    task_lines = "\n".join(
        f"- `{item.get('task_id')}`：{item.get('status')}，阶段 `{item.get('stage')}`" for item in tasks
    ) or "- 无登记计算任务"
    artifact_lines = "\n".join(f"- `{key}`：{value}" for key, value in sorted(artifacts.items())) or "- 无"
    content = f"""# {question_id} 小问总结

> 本文件由 Runner 在 locally_completed 门禁前依据 manifest 机器事实自动生成；
> Agent 可随后补充人工结论，但不得清空或恢复为占位内容。

## 结论

- conclusion_id：{conclusion.get('conclusion_id', '')}
- version：{conclusion.get('version', '')}
- content_hash：{conclusion.get('content_hash', '')}
- 更新时间：{conclusion.get('updated_at', '')}

## 版本

- 接受假设版本：`assumption_v{accepted:03d}`
- 接受公式版本：`formulation_v{formulation:03d}`

## Sanity

- L1-L4：{sanity.get('level_1_4', 'pending')}
- L5：{sanity.get('level_5', 'pending')}
- L6：{sanity.get('level_6', 'pending')}

## 可选阶段

- robustness：{optional.get('robustness', {})}
- ablation：{optional.get('ablation', {})}

## 产物

{artifact_lines}

## 计算任务

{task_lines}
"""
    path.parent.mkdir(parents=True, exist_ok=True)
    write_text(path, content)
    return path


def next_action() -> dict[str, Any]:
    """根据持久化状态返回本次唤醒唯一允许执行的动作。"""
    reconcile_tasks()
    state = load_state()
    if state.get("control") == "stopped":
        return _action("P0", "poll_email", "收到 STOP；禁止创建新工作，仅轮询控制邮箱")
    if state.get("control") == "paused":
        return _action("P0", "poll_email", "处于 PAUSE；仅轮询控制邮箱")

    problem_id = state.get("active_problem")
    if not problem_id:
        return _action("P9", "await_problem_initialization", "尚未初始化活动题目")

    problem = load_problem(problem_id)
    question_id = state.get("current_question") or problem.get("current_question")
    stage = state.get("current_stage", "problem_understanding")
    recovery_status = state.get("recovery_status", "normal")
    blocking = [str(reason) for reason in state.get("blocking", []) if str(reason).strip()]
    if recovery_status == "human_blocked":
        return _action("P0", "blocked", "当前故障需要人工处理", blocking_reasons=state.get("blocking", []))
    if recovery_status == "harness_invariant_error":
        return _action("P0", "blocked", "Harness invariant 错误，必须先完成对账", blocking_reasons=state.get("blocking", []))
    if blocking:
        return _action("P0", "blocked", "工作流存在需要人工解除的阻塞", blocking_reasons=blocking)

    all_tasks = list_tasks()
    running = [task for task in all_tasks if task.get("status") == "running"]
    if running:
        return _action(
            "P2",
            "wait_for_compute",
            "存在运行中的异步计算；本次唤醒不再调用 Agent",
            task_ids=[task["task_id"] for task in running],
        )
    queued = [task for task in all_tasks if task.get("status") == "queued"]
    if queued:
        started = start_queued()
        return _action(
            "P2",
            "start_queued_compute",
            "已按本地并发上限启动排队任务",
            task_ids=[task["task_id"] for task in started],
        )

    if recovery_status in {"retrying", "needs_revision"} and question_id and stage not in {"idle", "completed", "locally_completed"}:
        agent = AGENT_BY_STAGE.get(stage)
        if agent:
            return _action(
                "P2",
                "run_agent",
                "按恢复策略重新唤醒当前阶段并复用已有产物",
                agent=agent,
                problem_id=problem_id,
                question_id=question_id,
                stage=stage,
                recovery=state.get("recovery", {}),
                resume=True,
            )

    if stage == "completed":
        if problem.get("summary_status") != "built":
            return _action("P8", "build_final_summary", "研究阶段结束，生成整题最终摘要", problem_id=problem_id)
        if problem.get("completion_notification") not in {"sent", "skipped_disabled", "failed_final"}:
            return _action("P8", "send_problem_notification", "最终摘要已生成，发送整题完成通知", problem_id=problem_id)
        return _action("P9", "idle", "最终研究摘要已生成并完成通知")

    if stage == "cross_question_review":
        if problem.get("cross_question_review") == "passed":
            if problem.get("summary_status") != "built":
                return _action(
                    "P8",
                    "build_final_summary",
                    "跨小问审查已通过，最终摘要尚未生成",
                    problem_id=problem_id,
                )
            return _action(
                "P8",
                "transition_to_completed",
                "最终摘要已生成，写入 completed 终态",
                problem_id=problem_id,
            )
        return _action(
            "P7",
            "run_agent",
            "全部小问已局部完成，执行跨小问一致性审查",
            agent=AGENT_BY_STAGE[stage],
            problem_id=problem_id,
            stage=stage,
        )

    if not question_id:
        return _action("P1", "blocked", "活动题目未指定当前小问")
    _, manifest = question_manifest(problem_id, question_id)

    if stage == "assumption_definition":
        number = int(manifest.get("active_assumption_version", 0))
        version = {}
        if number:
            version = read_yaml(problem_dir(problem_id) / question_id / "versions" / f"assumption_v{number:03d}" / "version.yaml")
        if not number or version.get("status") in {"accepted", "rejected", "deprecated"}:
            return _action(
                "P5", "create_assumption_candidate", "当前阶段没有可编辑的 candidate 假设版本",
                problem_id=problem_id, question_id=question_id,
            )

    if stage == "mathematical_formulation":
        assumption_number = int(manifest.get("active_assumption_version", 0))
        formulation_number = int(manifest.get("active_formulation_version", 0))
        formulation = {}
        if assumption_number and formulation_number:
            formulation = read_yaml(
                problem_dir(problem_id) / question_id / "versions" / f"assumption_v{assumption_number:03d}"
                / "formulations" / f"formulation_v{formulation_number:03d}" / "formulation.yaml"
            )
        if not formulation_number or formulation.get("status") in {"accepted", "rejected", "deprecated"}:
            return _action(
                "P5", "create_formulation_candidate", "当前阶段没有可编辑的 candidate 公式版本",
                problem_id=problem_id, question_id=question_id,
            )

    if manifest.get("stale", {}).get("value"):
        return _action(
            "P5",
            "run_agent",
            "上游结论变化，当前小问产物已标记 stale",
            agent=AGENT_BY_STAGE["assumption_definition"],
            problem_id=problem_id,
            question_id=question_id,
            stage="assumption_definition",
            stale_causes=manifest.get("stale", {}).get("caused_by", []),
        )

    if stage == "computation":
        tasks = _question_tasks(problem_id, question_id)
        groups = list_task_groups(problem_id, question_id)
        ready_groups = [group for group in groups if group.get("ready") and not group.get("consumed")]
        if ready_groups:
            group = ready_groups[0]
            statuses = group["task_statuses"]
            succeeded = all(status == "succeeded" for status in statuses)
            return _action(
                "P2", "inspect_compute_result" if succeeded else "route_compute_failure",
                "实验批次全部达到终态，需要统一分析", agent="sanity-checker" if succeeded else "implementation-agent",
                problem_id=problem_id, question_id=question_id, stage=stage,
                group_id=group["group_id"], task_ids=group["task_ids"], task_statuses=statuses,
            )
        finished = [
            task
            for task in tasks
            if task.get("status") in TERMINAL and not task.get("consumed") and not task.get("group_id")
        ]
        if finished:
            task = sorted(finished, key=lambda item: item.get("updated_at", ""))[0]
            action = "inspect_compute_result" if task["status"] == "succeeded" else "route_compute_failure"
            return _action(
                "P2",
                action,
                "异步计算已结束，需要检查结果并决定阶段迁移",
                agent="implementation-agent" if task["status"] != "succeeded" else "sanity-checker",
                problem_id=problem_id,
                question_id=question_id,
                stage=stage,
                task_id=task["task_id"],
                task_status=task["status"],
                failure_type=task.get("failure_type"),
            )

    if stage == "locally_completed":
        notification = manifest.get("notification", {})
        if (
            not notification.get("sent")
            and notification.get("status") != "skipped_disabled"
            and int(notification.get("attempts", 0)) < 3
        ):
            return _action(
                "P6", "send_question_notification", "小问首次局部完成，需要发送单向回执",
                problem_id=problem_id, question_id=question_id,
            )
        questions = problem["questions"]
        index = questions.index(question_id)
        if index + 1 < len(questions):
            next_question = questions[index + 1]
            return _action(
                "P5",
                "advance_question",
                "当前小问已局部完成，下一小问尚未开始",
                problem_id=problem_id,
                question_id=next_question,
                stage="problem_understanding",
            )
        return _action(
            "P7",
            "advance_global_review",
            "所有小问均已局部完成",
            problem_id=problem_id,
            stage="cross_question_review",
        )

    if stage == "sanity_check":
        level_1_4 = str(manifest.get("sanity", {}).get("level_1_4", "pending")).upper()
        level_6 = str(manifest.get("sanity", {}).get("level_6", "pending")).upper()
        robustness = manifest.get("optional_stages", {}).get("robustness", {})
        history = manifest.get("sanity_history", [])
        latest_l1_4 = max((i for i, item in enumerate(history) if item.get("level") == "level_1_4"), default=-1)
        latest_l6 = max((i for i, item in enumerate(history) if item.get("level") == "level_6"), default=-1)
        if robustness.get("decision") == "completed" and level_1_4 in {"PASS", "PASS_WITH_WARNING"} and level_6 not in {"PASS", "PASS_WITH_WARNING"} and latest_l1_4 > latest_l6:
            return _action("P3", "run_agent", "robustness 已完成，执行 Level 6 sanity", agent="sanity-checker", problem_id=problem_id, question_id=question_id, stage=stage, level="level_6")

    if stage == "visualization":
        robustness = manifest.get("optional_stages", {}).get("robustness", {})
        if manifest.get("artifacts", {}).get("visualization") and robustness.get("decision") == "completed":
            return _action("P5", "advance_stage", "可视化已归档且 robustness 已完成，进入 Level 6 sanity", problem_id=problem_id, question_id=question_id, stage="sanity_check")

    if stage == "robustness" and manifest.get("optional_stages", {}).get("robustness", {}).get("decision") == "completed":
        return _action("P5", "advance_stage", "robustness 已完成，进入 Level 6 sanity", problem_id=problem_id, question_id=question_id, stage="sanity_check")

    optional = manifest.get("optional_stages", {}).get(stage)
    if optional and optional.get("decision") in {"skip", "skipped"}:
        return _action(
            "P5",
            "advance_stage",
            f"可选阶段 {stage} 已记录跳过理由",
            problem_id=problem_id,
            question_id=question_id,
            stage=next_stage(stage),
        )

    agent = AGENT_BY_STAGE.get(stage)
    if not agent:
        return _action("P9", "blocked", f"阶段没有 Agent 映射：{stage}")
    policy = "P3" if stage == "sanity_check" else "P4" if stage == "literature_review" else "P5"
    return _action(
        policy,
        "run_agent",
        "当前阶段需要同步 Agent 处理；计算阶段 Agent 只允许提交异步任务",
        agent=agent,
        problem_id=problem_id,
        question_id=question_id,
        stage=stage,
    )


def next_stage(current: str) -> str:
    order = stages()
    if current not in order:
        raise ValueError(f"未知阶段：{current}")
    index = order.index(current)
    if index + 1 >= len(order):
        return current
    return order[index + 1]


def transition(
    *,
    target_stage: str,
    problem_id: str | None = None,
    question_id: str | None = None,
    reason: str,
) -> dict[str, Any]:
    """执行显式阶段迁移；不自动宣称 Agent 工作已完成。"""
    state = load_state()
    problem_id = problem_id or state.get("active_problem")
    if not problem_id:
        raise ValueError("没有活动题目")
    if target_stage not in stages(problem_id, question_id):
        raise ValueError(f"未知目标阶段：{target_stage}")
    problem = load_problem(problem_id)
    gates = config_section("gates", problem_id, question_id)
    if gates.get("strict_stage_transitions", True):
        current = str(state.get("current_stage", "idle"))
        allowed = gates.get("allowed_transitions", {}).get(current, [])
        if target_stage != current and target_stage not in allowed:
            raise RuntimeError(f"非法阶段迁移：{current} -> {target_stage}")

    if question_id and target_stage not in {"cross_question_review", "completed"}:
        _, entry_manifest = question_manifest(problem_id, question_id)
        if target_stage == "mathematical_formulation" and int(entry_manifest.get("accepted_assumption_version", 0)) < 1:
            raise RuntimeError("没有已接受的假设版本，不能进入 mathematical_formulation")
        if target_stage == "implementation" and int(entry_manifest.get("accepted_formulation_version", 0)) < 1:
            raise RuntimeError("没有已接受的公式版本，不能进入 implementation")
        if target_stage == "visualization":
            sanity = str(entry_manifest.get("sanity", {}).get("level_1_4", "pending")).upper()
            if sanity not in {"PASS", "PASS_WITH_WARNING"}:
                raise RuntimeError("L1-L4 sanity 未通过，不能进入 visualization")

    if target_stage == "cross_question_review":
        incomplete = []
        for qid in problem["questions"]:
            _, item = question_manifest(problem_id, qid)
            if item.get("stage") != "locally_completed" and item.get("status") != "degraded_review":
                incomplete.append(qid)
        if incomplete:
            raise RuntimeError(f"以下小问尚未局部完成：{', '.join(incomplete)}")
        problem["cross_question_review"] = "in_progress"
        write_json(problem_dir(problem_id) / "problem_state.json", problem)
        question_id = None
    elif target_stage == "completed":
        if problem.get("cross_question_review") != "passed":
            raise RuntimeError("跨小问审查未通过，不能进入 completed")
        if problem.get("summary_status") != "built":
            raise RuntimeError("最终摘要未生成，不能进入 completed")
        problem["status"] = "completed"
        write_json(problem_dir(problem_id) / "problem_state.json", problem)
        question_id = None
    else:
        question_id = question_id or state.get("current_question")
        if not question_id:
            raise ValueError("目标阶段需要 question_id")
        if target_stage == "locally_completed":
            ensure_question_summary(problem_id, question_id)
            validate_local_completion(problem_id, question_id)
        update_question(
            problem_id,
            question_id,
            {"stage": target_stage, "status": "locally_completed" if target_stage == "locally_completed" else "active"},
        )
        problem["current_question"] = question_id
        write_json(problem_dir(problem_id) / "problem_state.json", problem)

    state.update(
        {
            "active_problem": problem_id,
            "current_question": question_id,
            "current_stage": target_stage,
            "last_action": f"阶段迁移至 {target_stage}：{reason}",
        }
    )
    save_state(
        state,
        event="stage_transition",
        details={"problem_id": problem_id, "question_id": question_id, "target": target_stage, "reason": reason},
    )
    return state


def mark_cross_question_review(problem_id: str, status: str, reason: str) -> None:
    if status not in {"passed", "needs_revision"}:
        raise ValueError("cross-question status 只能是 passed 或 needs_revision")
    problem = load_problem(problem_id)
    problem["cross_question_review"] = status
    problem["cross_question_review_reason"] = reason
    write_json(problem_dir(problem_id) / "problem_state.json", problem)
    if status == "passed":
        for question_id in problem["questions"]:
            path, manifest = question_manifest(problem_id, question_id)
            manifest.setdefault("sanity", {})["level_5"] = "PASS"
            write_yaml(path, manifest)


def validate_local_completion(problem_id: str, question_id: str) -> None:
    """阻止不完整小问绕过局部完成门禁。"""
    _, manifest = question_manifest(problem_id, question_id)
    errors: list[str] = []
    accepted = int(manifest.get("accepted_assumption_version", 0))
    if accepted < 1:
        errors.append("没有已接受的假设版本")
    from .research import check_key_assumptions

    citation_gate = check_key_assumptions(problem_id, question_id)
    if not citation_gate["passed"]:
        errors.extend(citation_gate["errors"])
    accepted_formulation = int(manifest.get("accepted_formulation_version", 0))
    if accepted_formulation < 1:
        errors.append("没有已接受的公式版本")
    conclusion = manifest.get("conclusion", {})
    for field in ("conclusion_id", "version", "content_hash"):
        if not str(conclusion.get(field, "")).strip():
            errors.append(f"结论缺少 {field}")
    summary_path = question_summary_path(problem_id, question_id)
    if not summary_path.is_file():
        errors.append(f"{question_id} 缺少 question_summary.md")
    else:
        summary_text = summary_path.read_text(encoding="utf-8").strip()
        if not summary_text or "待填写" in summary_text:
            errors.append(f"{question_id} 的 question_summary.md 仍为空或待填写")
    sanity = str(manifest.get("sanity", {}).get("level_1_4", "pending")).upper()
    if sanity not in {"PASS", "PASS_WITH_WARNING"}:
        errors.append(f"L1-L4 sanity 状态不可接受：{sanity}")
    for stage in ("robustness", "ablation"):
        item = manifest.get("optional_stages", {}).get(stage, {})
        decision = item.get("decision")
        if decision not in {"complete", "completed", "skip", "skipped"}:
            errors.append(f"{stage} 尚未完成或跳过")
        if decision in {"skip", "skipped"} and not str(item.get("reason", "")).strip():
            errors.append(f"{stage} 跳过但未记录理由")
    required_artifacts = tuple(config_section("gates", problem_id, question_id).get("required_artifacts_for_local_completion", []))
    missing = [name for name in required_artifacts if not manifest.get("artifacts", {}).get(name)]
    if missing:
        errors.append(f"核心产物未完成：{', '.join(missing)}")
    figures = read_yaml(problem_dir(problem_id) / "figures.yaml", {"figures": []}).get("figures", [])
    accepted_name = f"assumption_v{accepted:03d}"
    visualization = config_section("visualization", problem_id, question_id)
    quality = visualization.get("quality", {})
    accepted_figures = [
        item for item in figures
        if item.get("question_id") == question_id and item.get("assumption_version") == accepted_name
        and str(item.get("path", "")).lower().endswith(".png")
    ]
    count = sum(
        1 for item in accepted_figures
        if (not quality.get("require_automated_pass", True) or item.get("quality_status") == "passed")
        and (not quality.get("require_visual_review", True) or item.get("visual_review", {}).get("status") == "passed")
    )
    minimum = int(visualization.get("minimum_figures_per_question", 5))
    if count < minimum:
        errors.append(f"已接受版本只有 {count} 张通过自动质检和视觉复核的 PNG，至少需要 {minimum} 张")
    if manifest.get("stale", {}).get("value"):
        errors.append("小问仍处于 stale 状态")
    if errors:
        raise RuntimeError("局部完成门禁未通过：" + "；".join(errors))


def mark_downstream_stale(problem_id: str, source_question: str, conclusion_hash: str) -> list[str]:
    """上游结论发生变化时，将所有后续小问标记为 stale。"""
    problem = load_problem(problem_id)
    questions = problem["questions"]
    source_index = questions.index(source_question)
    changed: list[str] = []
    for question_id in questions[source_index + 1 :]:
        path, manifest = question_manifest(problem_id, question_id)
        stale = manifest.setdefault("stale", {"value": False, "caused_by": []})
        cause = {"question_id": source_question, "conclusion_hash": conclusion_hash}
        if cause not in stale["caused_by"]:
            stale["caused_by"].append(cause)
        stale["value"] = True
        manifest["stage"] = "assumption_definition"
        write_yaml(path, manifest)
        changed.append(question_id)
    return changed


def record_artifact(problem_id: str, question_id: str, name: str, completed: bool) -> dict[str, Any]:
    path, manifest = question_manifest(problem_id, question_id)
    artifacts = manifest.setdefault("artifacts", {})
    if name not in artifacts:
        raise ValueError(f"未知产物名称：{name}")
    artifacts[name] = completed
    write_yaml(path, manifest)
    return manifest


def record_optional_stage(problem_id: str, question_id: str, stage: str, decision: str, reason: str) -> dict[str, Any]:
    if stage not in {"robustness", "ablation"}:
        raise ValueError("可选阶段只能是 robustness 或 ablation")
    if decision not in {"completed", "skipped"}:
        raise ValueError("decision 只能是 completed 或 skipped")
    if decision == "skipped" and not reason.strip():
        raise ValueError("跳过可选阶段必须说明理由")
    path, manifest = question_manifest(problem_id, question_id)
    manifest.setdefault("optional_stages", {})[stage] = {"decision": decision, "reason": reason}
    manifest.setdefault("artifacts", {})[stage] = decision == "completed"
    write_yaml(path, manifest)
    return manifest


def record_conclusion(problem_id: str, question_id: str, conclusion_id: str, content: str) -> dict[str, Any]:
    if not conclusion_id.strip() or not content.strip():
        raise ValueError("conclusion_id 和 content 不能为空")
    path, manifest = question_manifest(problem_id, question_id)
    old = manifest.get("conclusion", {})
    content_hash = hash_json({"content": content})
    version = int(old.get("version", 0)) + (1 if old.get("content_hash") != content_hash else 0)
    manifest["conclusion"] = {
        "conclusion_id": conclusion_id,
        "version": version,
        "content_hash": content_hash,
        "updated_at": utc_now(),
    }
    write_yaml(path, manifest)
    graph_path = problem_dir(problem_id) / "dependency_graph.yaml"
    graph = read_yaml(graph_path, {"questions": [], "edges": []})
    for edge in graph.get("edges", []):
        if edge.get("from") == question_id:
            edge.update({"conclusion_id": conclusion_id, "version": version, "content_hash": content_hash})
    write_yaml(graph_path, graph)
    stale = []
    if old.get("content_hash") and old.get("content_hash") != content_hash:
        stale = mark_downstream_stale(problem_id, question_id, content_hash)
    return {"conclusion": manifest["conclusion"], "stale_questions": stale}


def clear_stale(problem_id: str, question_id: str, reason: str) -> dict[str, Any]:
    if not reason.strip():
        raise ValueError("清除 stale 必须记录复核理由")
    path, manifest = question_manifest(problem_id, question_id)
    stale = manifest.setdefault("stale", {"value": False, "caused_by": []})
    manifest.setdefault("stale_history", []).append(
        {"cleared_at": utc_now(), "reason": reason, "caused_by": list(stale.get("caused_by", []))}
    )
    stale["value"] = False
    stale["caused_by"] = []
    write_yaml(path, manifest)
    return manifest


def record_sanity(
    problem_id: str,
    question_id: str,
    level: str,
    status: str,
    reason: str,
    failure_type: str | None = None,
    return_stage: str | None = None,
) -> dict[str, Any]:
    sanity_config = config_section("sanity_check", problem_id, question_id)
    status = status.upper()
    if status not in set(sanity_config.get("statuses", [])):
        raise ValueError(f"未知 sanity 状态：{status}")
    if level not in {"level_1_4", "level_5", "level_6"}:
        raise ValueError(f"未知 sanity level：{level}")
    routes = sanity_config.get("failure_routes", {})
    if status == "NEEDS_REVISION" and failure_type not in routes and not return_stage:
        raise ValueError("NEEDS_REVISION 必须提供已配置的 failure_type 或 return_stage")
    target = return_stage or routes.get(failure_type or "")
    if status == "NEEDS_REVISION" and target == "earliest_conflicting_stage":
        raise ValueError("跨小问冲突必须显式提供 return_stage")
    path, manifest = question_manifest(problem_id, question_id)
    manifest.setdefault("sanity", {})[level] = status
    manifest.setdefault("sanity_history", []).append(
        {"at": utc_now(), "level": level, "status": status, "reason": reason, "failure_type": failure_type}
    )
    write_yaml(path, manifest)
    if status == "VERSION_REJECTED":
        decided = decide_assumption_version(problem_id, question_id, "REJECT", reason)
        return {"status": status, "routed_to": decided.get("stage"), "version_rejected": True}
    if status == "NEEDS_REVISION":
        assert target is not None
        transition(target_stage=target, problem_id=problem_id, question_id=question_id, reason=f"sanity 路由：{reason}")
        return {"status": status, "routed_to": target}
    state = load_state()
    if status == "PASS_WITH_WARNING":
        state.setdefault("warnings", []).append(f"{question_id} {level}: {reason}")
        save_state(state, event="sanity_warning", details={"question_id": question_id, "level": level, "reason": reason})
    return {"status": status, "routed_to": None}
