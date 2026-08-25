"""AutoMM 全自动控制层命令入口。"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from automm.common import CONFIG_DIR, ROOT, FileLock, read_yaml, write_text
from automm.problems import (
    create_assumption_version,
    create_formulation_version,
    decide_assumption_version,
    decide_formulation_version,
    init_problem,
)
from automm.state import append_ledger, apply_control, load_state
from automm.tasks import reconcile_tasks
from automm.workflow import (
    clear_stale,
    mark_cross_question_review,
    next_action,
    record_artifact,
    record_conclusion,
    record_optional_stage,
    record_sanity,
    transition,
)

REQUIRED_CONFIGS = (
    "project.yaml",
    "paths.yaml",
    "workflow.yaml",
    "compute.yaml",
    "ssh.yaml",
    "kaggle.yaml",
    "sanity_check.yaml",
    "visualization.yaml",
    "paper.yaml",
    "notifications.yaml",
    "agent_runtime.yaml",
    "agent_registry.yaml",
    "orchestrator.yaml",
    "research.yaml",
    "gates.yaml",
    "summary.yaml",
)


def validate_config() -> None:
    errors: list[str] = []
    loaded = {}
    for name in REQUIRED_CONFIGS:
        path = CONFIG_DIR / name
        if not path.exists():
            errors.append(f"缺少 {path.relative_to(ROOT).as_posix()}")
            continue
        try:
            loaded[name] = read_yaml(path)
            print(f"PASS {path.relative_to(ROOT).as_posix()}")
        except Exception as exc:
            errors.append(f"{name}: {exc}")
    required_stages = {
        "problem_understanding",
        "literature_review",
        "assumption_definition",
        "mathematical_formulation",
        "implementation",
        "computation",
        "sanity_check",
        "visualization",
        "locally_completed",
        "cross_question_review",
        "completed",
    }
    workflow = loaded.get("workflow.yaml", {})
    missing = required_stages - set(workflow.get("stages", []))
    if missing:
        errors.append(f"workflow 缺少阶段：{', '.join(sorted(missing))}")
    if workflow.get("allow_parallel_questions") is not False:
        errors.append("全自动模式必须禁止小问间并行")
    notifications = loaded.get("notifications.yaml", {})
    if notifications.get("enabled"):
        for field in ("smtp_host", "imap_host", "username", "from", "to"):
            if not notifications.get(field):
                errors.append(f"notifications.{field} 在启用邮件时不能为空")
        if not notifications.get("allowed_senders"):
            errors.append("notifications.allowed_senders 在启用邮件时不能为空")
    for name, value in loaded.get("paths.yaml", {}).items():
        if Path(str(value)).is_absolute():
            errors.append(f"paths.{name} 必须是相对路径")
    path_fields = {
        "project.yaml": ("request_file", "paths_file"),
        "paper.yaml": ("template", "style_sample", "citation_registry", "figure_manifest", "output", "draft_output"),
        "ssh.yaml": ("private_key_path",),
        "notifications.yaml": ("processed_messages_file",),
        "agent_runtime.yaml": ("registry", "output_schema"),
        "orchestrator.yaml": ("transaction_journal", "action_runs_directory"),
        "research.yaml": ("metadata_verification.cache_directory",),
        "summary.yaml": ("output",),
    }
    for filename, fields in path_fields.items():
        for field in fields:
            value: object = loaded.get(filename, {})
            for part in field.split("."):
                value = value.get(part) if isinstance(value, dict) else None
            if value and Path(str(value)).is_absolute():
                errors.append(f"{filename}:{field} 必须是相对路径")
    registry = loaded.get("agent_registry.yaml", {}).get("agents", {})
    for agent, item in registry.items():
        prompt = item.get("prompt")
        if item.get("enabled", True) and (not prompt or not (ROOT / prompt).is_file()):
            errors.append(f"Agent {agent} 的 prompt 不存在：{prompt}")
    runtime = loaded.get("agent_runtime.yaml", {})
    for field in ("registry", "output_schema"):
        value = runtime.get(field)
        if not value or not (ROOT / value).is_file():
            errors.append(f"agent_runtime.{field} 文件不存在：{value}")
    if errors:
        for error in errors:
            print(f"FAIL {error}")
        raise SystemExit(2)
    print("配置校验完成")


def show_status(as_json: bool) -> None:
    state = load_state()
    if as_json:
        print(json.dumps(state, ensure_ascii=False, indent=2))
        return
    rendered = ROOT / "reports" / "autoresearch" / "STATE.md"
    print(rendered.read_text(encoding="utf-8"))


def emit(value: object) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2, default=str))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="AutoMM 全自动控制入口")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("validate-config")
    status = sub.add_parser("status")
    status.add_argument("--json", action="store_true")
    initialize = sub.add_parser("init-problem")
    initialize.add_argument("--problem-id", required=True)
    initialize.add_argument("--questions", required=True, type=int)
    action = sub.add_parser("next-action")
    action.add_argument("--json", action="store_true")
    sub.add_parser("reconcile")
    control = sub.add_parser("control")
    control.add_argument("value", choices=("PAUSE", "STOP", "RESUME"))
    control.add_argument("--source", default="cli")
    move = sub.add_parser("transition")
    move.add_argument("--stage", required=True)
    move.add_argument("--problem-id")
    move.add_argument("--question-id")
    move.add_argument("--reason", required=True)
    version = sub.add_parser("create-assumption-version")
    version.add_argument("--problem-id", required=True)
    version.add_argument("--question-id", required=True)
    formulation = sub.add_parser("create-formulation-version")
    formulation.add_argument("--problem-id", required=True)
    formulation.add_argument("--question-id", required=True)
    decision = sub.add_parser("decide-assumption-version")
    decision.add_argument("--problem-id", required=True)
    decision.add_argument("--question-id", required=True)
    decision.add_argument("--decision", choices=("ACCEPT", "REJECT"), required=True)
    decision.add_argument("--reason", required=True)
    formulation_decision = sub.add_parser("decide-formulation-version")
    formulation_decision.add_argument("--problem-id", required=True)
    formulation_decision.add_argument("--question-id", required=True)
    formulation_decision.add_argument("--decision", choices=("ACCEPT", "REJECT"), required=True)
    formulation_decision.add_argument("--reason", required=True)
    review = sub.add_parser("cross-review")
    review.add_argument("--problem-id", required=True)
    review.add_argument("--status", choices=("passed", "needs_revision"), required=True)
    review.add_argument("--reason", required=True)
    artifact = sub.add_parser("record-artifact")
    artifact.add_argument("--problem-id", required=True)
    artifact.add_argument("--question-id", required=True)
    artifact.add_argument("--name", required=True)
    artifact.add_argument("--completed", choices=("true", "false"), default="true")
    optional = sub.add_parser("record-optional-stage")
    optional.add_argument("--problem-id", required=True)
    optional.add_argument("--question-id", required=True)
    optional.add_argument("--stage", choices=("robustness", "ablation"), required=True)
    optional.add_argument("--decision", choices=("completed", "skipped"), required=True)
    optional.add_argument("--reason", required=True)
    conclusion = sub.add_parser("record-conclusion")
    conclusion.add_argument("--problem-id", required=True)
    conclusion.add_argument("--question-id", required=True)
    conclusion.add_argument("--conclusion-id", required=True)
    conclusion.add_argument("--content", required=True)
    stale = sub.add_parser("clear-stale")
    stale.add_argument("--problem-id", required=True)
    stale.add_argument("--question-id", required=True)
    stale.add_argument("--reason", required=True)
    sanity = sub.add_parser("record-sanity")
    sanity.add_argument("--problem-id", required=True)
    sanity.add_argument("--question-id", required=True)
    sanity.add_argument("--level", choices=("level_1_4", "level_5", "level_6"), required=True)
    sanity.add_argument(
        "--status", choices=("PASS", "PASS_WITH_WARNING", "NEEDS_REVISION", "VERSION_REJECTED"), required=True
    )
    sanity.add_argument("--reason", required=True)
    sanity.add_argument("--failure-type")
    sanity.add_argument("--return-stage")
    ledger = sub.add_parser("append-ledger")
    ledger.add_argument("--question", required=True)
    ledger.add_argument("--stage", required=True)
    ledger.add_argument("--hypothesis", required=True)
    ledger.add_argument("--setup", required=True)
    ledger.add_argument("--result", required=True)
    ledger.add_argument("--sanity", required=True)
    ledger.add_argument("--conclusion", required=True)
    ledger.add_argument("--next", required=True)
    acquire = sub.add_parser("acquire-lock")
    acquire.add_argument("--owner", required=True)
    release = sub.add_parser("release-lock")
    release.add_argument("--owner", required=True)
    return parser


def orchestrator_lock() -> FileLock:
    config = read_yaml(CONFIG_DIR / "workflow.yaml").get("lock", {})
    return FileLock(
        ROOT / config.get("path", "runtime/locks/orchestrator.lock"),
        int(config.get("stale_after_minutes", 60)) * 60,
    )


def main() -> None:
    args = build_parser().parse_args()
    if args.command == "validate-config":
        validate_config()
    elif args.command == "status":
        show_status(args.json)
    elif args.command == "init-problem":
        print(init_problem(args.problem_id, args.questions).relative_to(ROOT).as_posix())
    elif args.command == "next-action":
        emit(next_action())
    elif args.command == "reconcile":
        emit(reconcile_tasks())
    elif args.command == "control":
        emit(apply_control(args.value, source=args.source))
    elif args.command == "transition":
        emit(
            transition(
                target_stage=args.stage, problem_id=args.problem_id, question_id=args.question_id, reason=args.reason
            )
        )
    elif args.command == "create-assumption-version":
        path = create_assumption_version(args.problem_id, args.question_id)
        print(path.relative_to(ROOT).as_posix())
    elif args.command == "create-formulation-version":
        path = create_formulation_version(args.problem_id, args.question_id)
        print(path.relative_to(ROOT).as_posix())
    elif args.command == "decide-assumption-version":
        emit(decide_assumption_version(args.problem_id, args.question_id, args.decision, args.reason))
    elif args.command == "decide-formulation-version":
        emit(decide_formulation_version(args.problem_id, args.question_id, args.decision, args.reason))
    elif args.command == "cross-review":
        mark_cross_question_review(args.problem_id, args.status, args.reason)
        print(f"cross_question_review={args.status}")
    elif args.command == "record-artifact":
        emit(record_artifact(args.problem_id, args.question_id, args.name, args.completed == "true"))
    elif args.command == "record-optional-stage":
        emit(record_optional_stage(args.problem_id, args.question_id, args.stage, args.decision, args.reason))
    elif args.command == "record-conclusion":
        emit(record_conclusion(args.problem_id, args.question_id, args.conclusion_id, args.content))
    elif args.command == "clear-stale":
        emit(clear_stale(args.problem_id, args.question_id, args.reason))
    elif args.command == "record-sanity":
        emit(
            record_sanity(
                args.problem_id,
                args.question_id,
                args.level,
                args.status,
                args.reason,
                args.failure_type,
                args.return_stage,
            )
        )
    elif args.command == "append-ledger":
        from automm.common import utc_now

        append_ledger(
            {
                "at": utc_now(),
                "question": args.question,
                "stage": args.stage,
                "hypothesis": args.hypothesis,
                "setup": args.setup,
                "result": args.result,
                "sanity": args.sanity,
                "conclusion": args.conclusion,
                "next": args.next,
            }
        )
        print("LEDGER_APPENDED")
    elif args.command == "acquire-lock":
        lock = orchestrator_lock()
        if not lock.acquire(args.owner):
            pending = ROOT / read_yaml(CONFIG_DIR / "workflow.yaml").get("flags", {}).get(
                "pending_wakeup", "runtime/flags/pending_wakeup.flag"
            )
            write_text(pending, f"coalesced_by={args.owner}\n")
            suffix = "（锁已过期，确认无活跃进程后再释放）" if lock.is_stale() else ""
            raise SystemExit(f"LOCK_BUSY_PENDING_COALESCED：{lock.info()}{suffix}")
        print("LOCK_ACQUIRED")
    elif args.command == "release-lock":
        lock = orchestrator_lock()
        info = lock.info()
        if info and info.get("owner") != args.owner:
            raise SystemExit(f"锁属于 {info.get('owner')}，拒绝释放")
        lock.release()
        pending = ROOT / read_yaml(CONFIG_DIR / "workflow.yaml").get("flags", {}).get(
            "pending_wakeup", "runtime/flags/pending_wakeup.flag"
        )
        if pending.exists():
            pending.unlink()
            print("LOCK_RELEASED_PENDING_WAKEUP_REQUIRED")
        else:
            print("LOCK_RELEASED")


if __name__ == "__main__":
    main()
