"""一次唤醒只执行一个动作的 Orchestrator Runner。"""

from __future__ import annotations

import json
import subprocess
import sys
import traceback
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import psutil

from .agent_runtime import apply_agent_commands, invoke_agent, new_action_id
from .common import CONFIG_DIR, ROOT, RUNTIME_DIR, FileLock, append_jsonl, read_json, read_yaml, relative, utc_now, write_json, write_yaml
from .failure_policy import AgentTimeoutError, classify_exception, note_recovery
from .problems import create_assumption_version, create_formulation_version, load_problem, problem_dir, question_manifest
from .state import load_state, reconcile_control_flags, save_state
from .summary import build_final_summary
from .tasks import GROUP_ROOT, TASK_ROOT, reconcile_tasks
from .workflow import next_action, transition


def config() -> dict[str, Any]:
    return read_yaml(CONFIG_DIR / "orchestrator.yaml")


def lock() -> FileLock:
    item = read_yaml(CONFIG_DIR / "workflow.yaml").get("lock", {})
    return FileLock(ROOT / item.get("path", "runtime/locks/orchestrator.lock"), int(item.get("stale_after_minutes", 60)) * 60)


def _owner_alive(info: dict[str, Any]) -> bool:
    try:
        return psutil.Process(int(info["pid"])).is_running()
    except (KeyError, ValueError, TypeError, psutil.Error):
        return False


def acquire_runner_lock(action_id: str) -> tuple[FileLock, bool]:
    item = lock()
    if item.acquire(action_id):
        return item, True
    info = item.info()
    if item.is_stale() and not _owner_alive(info):
        append_jsonl(RUNTIME_DIR / "lock_recovery.jsonl", {"at": utc_now(), "lock": relative(item.path), "old": info})
        item.release()
        if item.acquire(action_id):
            return item, True
    pending = ROOT / read_yaml(CONFIG_DIR / "workflow.yaml").get("flags", {}).get("pending_wakeup", "runtime/flags/pending_wakeup.flag")
    pending.parent.mkdir(parents=True, exist_ok=True)
    pending.write_text(f"coalesced_by={action_id}\nat={utc_now()}\n", encoding="utf-8")
    return item, False


def _set_next_wake(state: dict[str, Any]) -> None:
    minutes = int(read_yaml(CONFIG_DIR / "workflow.yaml").get("wake_interval_minutes", 10))
    state["next_wake"] = (datetime.now(timezone.utc) + timedelta(minutes=minutes)).isoformat()


def _run_mail_poll() -> None:
    if not read_yaml(CONFIG_DIR / "notifications.yaml").get("enabled"):
        return
    result = subprocess.run([sys.executable, str(ROOT / "scripts" / "notify_email.py"), "poll"], cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace", shell=False, check=False)
    append_jsonl(RUNTIME_DIR / "email" / "polls.jsonl", {"at": utc_now(), "returncode": result.returncode, "stdout": result.stdout[-4000:], "stderr": result.stderr[-4000:]})


def _notify(kind: str, problem_id: str, question_id: str | None = None) -> dict[str, Any]:
    message = f"AutoMM {kind}: problem={problem_id} question={question_id or '-'}"
    command = [sys.executable, str(ROOT / "scripts" / "notify_email.py"), "send", "--kind", kind, "--message", message, "--problem-id", problem_id]
    if question_id:
        command.extend(["--question-id", question_id])
    result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace", shell=False, check=False)
    stdout = result.stdout.strip()
    return {"returncode": result.returncode, "stdout": stdout, "stderr": result.stderr.strip(), "status": "skipped_disabled" if "SKIPPED_DISABLED" in stdout else "sent" if result.returncode == 0 else "failed"}


def recover_incomplete_transactions(journal: Path) -> list[str]:
    if not journal.exists():
        return []
    latest: dict[str, str] = {}
    for line in journal.read_text(encoding="utf-8").splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if event.get("action_id") and event.get("phase"):
            latest[str(event["action_id"])] = str(event["phase"])
    incomplete = sorted(action_id for action_id, phase in latest.items() if phase not in {"committed", "failed", "recovered_incomplete", "retrying"})
    for action_id in incomplete:
        append_jsonl(journal, {"at": utc_now(), "action_id": action_id, "phase": "recovered_incomplete", "policy": "reconcile_without_replay"})
    return incomplete


def _mark_task_consumed(task_id: str) -> None:
    path = TASK_ROOT / task_id / "status.json"
    status = read_json(path)
    status["consumed"] = True
    status["consumed_at"] = utc_now()
    write_json(path, status)
    write_json(TASK_ROOT / task_id / f"attempt-{int(status.get('attempt', 1)):03d}-status.json", status)


def _mark_group_consumed(group_id: str) -> None:
    path = GROUP_ROOT / group_id / "group.json"
    group = read_json(path)
    group["consumed"] = True
    group["consumed_at"] = utc_now()
    write_json(path, group)
    for task_id in group.get("task_ids", []):
        _mark_task_consumed(task_id)


def execute_non_agent(action: dict[str, Any]) -> dict[str, Any]:
    name = action["action"]
    if name in {"idle", "await_problem_initialization", "wait_for_compute", "poll_email", "blocked", "start_queued_compute"}:
        return {"handled": name, "changed": False}
    if name == "advance_stage":
        return {"handled": name, "state": transition(target_stage=action["stage"], problem_id=action["problem_id"], question_id=action["question_id"], reason=action["reason"])}
    if name == "create_assumption_candidate":
        return {"handled": name, "path": relative(create_assumption_version(action["problem_id"], action["question_id"]))}
    if name == "create_formulation_candidate":
        return {"handled": name, "path": relative(create_formulation_version(action["problem_id"], action["question_id"]))}
    if name == "advance_question":
        return {"handled": name, "state": transition(target_stage="problem_understanding", problem_id=action["problem_id"], question_id=action["question_id"], reason=action["reason"])}
    if name == "advance_global_review":
        return {"handled": name, "state": transition(target_stage="cross_question_review", problem_id=action["problem_id"], reason=action["reason"])}
    if name == "send_question_notification":
        result = _notify("question-complete", action["problem_id"], action["question_id"])
        path, manifest = question_manifest(action["problem_id"], action["question_id"])
        notification = manifest.setdefault("notification", {})
        notification["attempts"] = int(notification.get("attempts", 0)) + 1
        notification["status"] = result["status"]
        notification["sent"] = result["status"] in {"sent", "skipped_disabled"}
        write_yaml(path, manifest)
        if result["status"] == "failed" and notification["attempts"] >= 3:
            state = load_state()
            warning = f"{action['question_id']} 完成通知连续失败，研究流程继续"
            if warning not in state.setdefault("warnings", []):
                state["warnings"].append(warning)
            save_state(state, event="question_notification_failed_final", details=action)
        return {"handled": name, "notification": result}
    if name == "build_final_summary":
        return {"handled": name, "summary": build_final_summary(action["problem_id"])}
    if name == "send_problem_notification":
        result = _notify("problem-complete", action["problem_id"])
        problem = load_problem(action["problem_id"])
        attempts = int(problem.get("completion_notification_attempts", 0)) + 1
        problem["completion_notification_attempts"] = attempts
        problem["completion_notification"] = result["status"] if result["status"] in {"sent", "skipped_disabled"} else "failed_final" if attempts >= 3 else "failed"
        write_json(problem_dir(action["problem_id"]) / "problem_state.json", problem)
        return {"handled": name, "notification": result}
    raise RuntimeError(f"没有非 Agent action handler：{name}")


def run_once() -> dict[str, Any]:
    action_id = new_action_id()
    runner_lock, acquired = acquire_runner_lock(action_id)
    if not acquired:
        return {"action_id": action_id, "status": "pending_coalesced"}
    journal = ROOT / config().get("transaction_journal", "runtime/transactions.jsonl")
    recovered = recover_incomplete_transactions(journal)
    append_jsonl(journal, {"at": utc_now(), "action_id": action_id, "phase": "started"})
    try:
        reconcile_control_flags()
        task_recovery = reconcile_tasks()
        if recovered:
            append_jsonl(RUNTIME_DIR / "recovery.jsonl", {"at": utc_now(), "actions": recovered, "task_changes": [item.get("task_id") for item in task_recovery]})
        if config().get("mail_poll_before_action", True):
            _run_mail_poll()
        action = next_action()
        append_jsonl(journal, {"at": utc_now(), "action_id": action_id, "phase": "decided", "action": action})
        agent_response: dict[str, Any] | None = None
        if action["action"] in {"run_agent", "inspect_compute_result", "route_compute_failure"}:
            try:
                response, meta = invoke_agent(action["agent"], action, action_id)
            except AgentTimeoutError as exc:
                state = load_state()
                note_recovery(state, failure_class="agent_transport", error=str(exc), progress={"productive": False, "stage": action.get("stage")}, problem_id=action.get("problem_id"), question_id=action.get("question_id"))
                state["blocking"] = []
                state["last_action"] = f"{action_id}: agent_timeout_retry"
                _set_next_wake(state)
                save_state(state, event="agent_timeout_retry", details={"action_id": action_id, "stage": action.get("stage")})
                append_jsonl(journal, {"at": utc_now(), "action_id": action_id, "phase": "retrying", "failure_class": "agent_transport", "error": str(exc)})
                return {"action_id": action_id, "status": "retrying", "action": action, "error": str(exc)}
            agent_response = response
            computation_needs_sanity = (
                action.get("stage") == "computation"
                and response.get("status") in {"success", "warning"}
                and any(command.get("name") == "record_sanity" for command in response.get("commands", []))
            )
            applied = apply_agent_commands(response, action)
            # 命令批次成功后再由 Runner 确定性切入 sanity，避免批次回滚后留下孤立的阶段迁移。
            if computation_needs_sanity and load_state().get("current_stage") == "computation":
                transition(
                    target_stage="sanity_check",
                    problem_id=action["problem_id"],
                    question_id=action["question_id"],
                    reason="计算结果已由 Runner 交给 sanity-checker 验收",
                )
            routed_stage = None
            if (
                action.get("stage") == "cross_question_review"
                and response.get("status") in {"success", "warning"}
                and response.get("recommended_next_stage") == "final_summary"
                and any(
                    command.get("name") == "mark_cross_question_review"
                    and command.get("arguments", {}).get("status") == "passed"
                    for command in response.get("commands", [])
                )
            ):
                transition(target_stage="completed", problem_id=action["problem_id"], reason="跨小问审查通过，进入最终总结归档")
            if action.get("task_id") and response["status"] in {"success", "warning"}:
                _mark_task_consumed(action["task_id"])
            if action.get("group_id") and response["status"] in {"success", "warning"}:
                _mark_group_consumed(action["group_id"])
            result = {"agent": action["agent"], "response": response, "applied": applied, "meta": meta}
        else:
            result = execute_non_agent(action)
        state = load_state()
        state["last_action"] = f"{action_id}: {action['action']}"
        if agent_response and agent_response["status"] in {"success", "warning"}:
            state["recovery_status"] = "normal"
            state["failure_class"] = "quality_warning" if agent_response["status"] == "warning" else None
        if agent_response and agent_response["status"] in {"failed", "blocked"}:
            reasons = agent_response.get("blocking_reasons") or [f"Agent {action['agent']} 返回 {agent_response['status']}"]
            failure_class = str(agent_response.get("failure_class") or "code_runtime")
            note_recovery(state, failure_class=failure_class, error="; ".join(str(item) for item in reasons), progress={"productive": False, "stage": action.get("stage")}, problem_id=action.get("problem_id"), question_id=action.get("question_id"))
            state["blocking"] = reasons if state.get("recovery_status") in {"human_blocked", "harness_invariant_error"} else []
            # 非人工故障使用 Agent 给出的建议阶段，但必须再次通过严格状态机门禁。
            recommended = agent_response.get("recommended_next_stage")
            current_stage = state.get("current_stage")
            if (
                recommended
                and recommended != current_stage
                and action.get("problem_id")
                and action.get("question_id")
                and state.get("recovery_status") not in {"human_blocked", "harness_invariant_error"}
            ):
                try:
                    transition(
                        target_stage=str(recommended),
                        problem_id=action["problem_id"],
                        question_id=action["question_id"],
                        reason=f"{action['agent']} {agent_response['status']}：{'；'.join(reasons)}",
                    )
                    state = load_state()
                    state["blocking"] = []
                    for reason in reasons:
                        warning = f"已自动路由的阶段故障：{reason}"
                        if warning not in state.setdefault("warnings", []):
                            state["warnings"].append(warning)
                except (RuntimeError, ValueError) as route_error:
                    state.setdefault("warnings", []).append(f"建议路由未执行：{route_error}")
        elif action["action"] == "blocked":
            state["failure_class"] = "external_human_required"
            state["recovery_status"] = "human_blocked"
            state["blocking"] = [action["reason"]]
        elif action["action"] not in {"poll_email", "wait_for_compute"}:
            state["blocking"] = []
        if agent_response:
            for warning in agent_response.get("warnings", []):
                if warning not in state.setdefault("warnings", []):
                    state["warnings"].append(warning)
        _set_next_wake(state)
        save_state(state, event="runner_action_complete", details={"action_id": action_id, "action": action["action"]})
        append_jsonl(journal, {"at": utc_now(), "action_id": action_id, "phase": "committed", "result": result})
        return {"action_id": action_id, "status": "completed", "action": action, "result": result}
    except Exception as exc:
        state = load_state()
        failure_class = classify_exception(exc)
        note_recovery(state, failure_class=failure_class, error=str(exc), progress={"productive": False, "stage": action.get("stage") if "action" in locals() else None}, problem_id=action.get("problem_id") if "action" in locals() else None, question_id=action.get("question_id") if "action" in locals() else None)
        state["blocking"] = [f"Runner {action_id} 失败：{exc}"] if failure_class in {"harness_invariant", "external_human_required"} else []
        state["last_action"] = f"{action_id}: {state.get('recovery_status', 'failed')}"
        _set_next_wake(state)
        save_state(state, event="runner_action_recovery", details={"action_id": action_id, "error": str(exc), "failure_class": failure_class})
        append_jsonl(journal, {"at": utc_now(), "action_id": action_id, "phase": state.get("recovery_status", "failed"), "failure_class": failure_class, "error": str(exc), "traceback": traceback.format_exc()})
        return {"action_id": action_id, "status": state.get("recovery_status", "failed"), "error": str(exc), "failure_class": failure_class}
    finally:
        runner_lock.release()
