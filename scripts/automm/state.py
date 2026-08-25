"""工作流状态、事件和人类可读快照。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .common import ROOT, RUNTIME_DIR, append_jsonl, read_json, read_yaml, utc_now, write_json, write_text


STATE_PATH = RUNTIME_DIR / "workflow_state.json"
EVENTS_PATH = RUNTIME_DIR / "events.jsonl"
STATE_MD_PATH = ROOT / "reports" / "autoresearch" / "STATE.md"
LEDGER_PATH = ROOT / "reports" / "autoresearch" / "experiment_ledger.md"
FLAGS_DIR = RUNTIME_DIR / "flags"


def request_pending_wakeup(*, source: str) -> Path:
    path = ROOT / read_yaml(ROOT / "config" / "workflow.yaml").get("flags", {}).get("pending_wakeup", "runtime/flags/pending_wakeup.flag")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"source={source}\nat={utc_now()}\n", encoding="utf-8")
    return path


def default_state() -> dict[str, Any]:
    return {
        "version": 2,
        "updated_at": utc_now(),
        "control": "running",
        "mode": "full_auto",
        "active_problem": None,
        "current_question": None,
        "current_stage": "idle",
        "last_action": None,
        "next_wake": None,
        "warnings": [],
        "blocking": [],
        "failure_class": None,
        "recovery_status": "normal",
        "recovery": {
            "total_rounds": 0,
            "productive_rounds": 0,
            "same_fingerprint_streak": 0,
            "mode": "normal",
        },
    }


def load_state() -> dict[str, Any]:
    if not STATE_PATH.exists():
        state = default_state()
        save_state(state, event="state_initialized")
        return state
    state = read_json(STATE_PATH)
    changed = False
    defaults = default_state()
    for key, value in defaults.items():
        if key not in state:
            state[key] = value
            changed = True
    if state.get("version", 1) < 2:
        state["version"] = 2
        changed = True
    if changed:
        save_state(state, event="state_migrated", details={"target_version": 2})
    return state


def save_state(state: dict[str, Any], *, event: str, details: dict[str, Any] | None = None) -> None:
    state["updated_at"] = utc_now()
    write_json(STATE_PATH, state)
    append_jsonl(EVENTS_PATH, {"at": state["updated_at"], "event": event, "details": details or {}})
    render_state(state)


def render_state(state: dict[str, Any]) -> None:
    from .tasks import task_counts

    counts = task_counts()
    task_text = " | ".join(f"{key}={value}" for key, value in sorted(counts.items())) or "无任务"
    warnings = "\n".join(f"- {item}" for item in state.get("warnings", [])) or "- 无"
    blocking = "\n".join(f"- {item}" for item in state.get("blocking", [])) or "- 无"
    text = f"""# AutoMM STATE

> 本文件由 `runtime/workflow_state.json` 渲染，请勿以手工修改本文件的方式驱动状态。

## 基本状态

- 更新时间：{state.get('updated_at')}
- 控制状态：{state.get('control')}
- 活动题目：{state.get('active_problem') or '未设置'}
- 当前小问：{state.get('current_question') or '未设置'}
- 当前阶段：{state.get('current_stage')}

## 任务

{task_text}

## 最近动作

{state.get('last_action') or '无'}

## 警告

{warnings}

## 阻塞项

{blocking}

## 下次唤醒

{state.get('next_wake') or '按 workflow 配置'}
"""
    write_text(STATE_MD_PATH, text)


def apply_control(command: str, *, source: str = "cli") -> dict[str, Any]:
    command = command.upper()
    if command not in {"PAUSE", "STOP", "RESUME"}:
        raise ValueError(f"未知控制命令: {command}")
    FLAGS_DIR.mkdir(parents=True, exist_ok=True)
    for name in ("pause", "stop", "resume"):
        flag = FLAGS_DIR / f"{name}.flag"
        if flag.exists():
            flag.unlink()
    (FLAGS_DIR / f"{command.lower()}.flag").write_text(
        f"command={command}\nsource={source}\nat={utc_now()}\n", encoding="utf-8"
    )
    state = load_state()
    state["control"] = {"PAUSE": "paused", "STOP": "stopped", "RESUME": "running"}[command]
    state["last_action"] = f"控制命令 {command}，来源 {source}"
    if command == "STOP":
        from .tasks import cancel_queued

        cancelled = cancel_queued()
        state["last_action"] += f"；已取消 {len(cancelled)} 个排队任务"
    elif command == "RESUME":
        from .tasks import reconcile_tasks

        reconciled = reconcile_tasks()
        state["blocking"] = []
        state["last_action"] += f"；已对账 {len(reconciled)} 个异常任务"
    save_state(state, event="control_command", details={"command": command, "source": source})
    if command == "RESUME":
        request_pending_wakeup(source=source)
    return state


def reconcile_control_flags() -> dict[str, Any]:
    """把外部写入的 STOP/PAUSE/RESUME flag 对账为机器状态。"""
    existing: list[str] = []
    for name in ("stop", "pause", "resume"):
        path = FLAGS_DIR / f"{name}.flag"
        if path.exists():
            existing.append(name.upper())
    if not existing:
        return load_state()
    command = next(name for name in ("STOP", "PAUSE", "RESUME") if name in existing)
    state = load_state()
    expected = {"PAUSE": "paused", "STOP": "stopped", "RESUME": "running"}[command]
    if state.get("control") == expected:
        return state
    return apply_control(command, source="flag-reconcile")


def append_ledger(entry: dict[str, Any]) -> None:
    """以单行 Markdown 表格追加实验记录；调用方必须持有 orchestrator 锁。"""
    lock_path = ROOT / read_yaml(ROOT / "config" / "workflow.yaml").get("lock", {}).get("path", "runtime/locks/orchestrator.lock")
    if not lock_path.exists():
        raise RuntimeError("追加 ledger 前必须持有 orchestrator 锁")
    fields = ("at", "question", "stage", "hypothesis", "setup", "result", "sanity", "conclusion", "next")
    values = [str(entry.get(field, "")).replace("|", "\\|").replace("\n", "<br>") for field in fields]
    existing = LEDGER_PATH.read_text(encoding="utf-8") if LEDGER_PATH.exists() else (
        "# 建模实验账本\n\n| 日期 | question | stage | hypothesis | setup | result | sanity | conclusion | next |\n"
        "|---|---|---|---|---|---|---|---|---|\n"
    )
    write_text(LEDGER_PATH, existing.rstrip() + "\n| " + " | ".join(values) + " |\n")
