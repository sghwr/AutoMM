"""统一的故障分类、恢复预算和阶段级超时策略。

该模块只处理 Harness 控制语义，不判断具体数学模型是否优雅。
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from .common import ROOT, config_section, read_yaml, utc_now


FAILURE_CLASSES = {
    "harness_invariant",
    "agent_transport",
    "infrastructure_transient",
    "code_runtime",
    "model_infeasible",
    "quality_warning",
    "external_human_required",
}

HUMAN_BLOCK_CLASSES = {"external_human_required", "harness_invariant"}


class HarnessInvariantError(RuntimeError):
    """表示状态、事务、schema 或追踪链被破坏。"""


class AgentTimeoutError(TimeoutError):
    """表示单次 Agent action 超时，不等同于人工阻塞。"""


class AgentTransportError(RuntimeError):
    """表示 Agent 进程、能力探针或传输层失败。"""


def stage_timeout_seconds(stage: str | None, *, fallback: int = 1800) -> int:
    config = read_yaml(ROOT / "config" / "agent_runtime.yaml")
    mapping = config.get("stage_timeout_seconds", {})
    value = mapping.get(stage or "", mapping.get("default", config.get("timeout_seconds", fallback)))
    return max(0, int(value))


def classify_exception(exc: BaseException) -> str:
    if isinstance(exc, HarnessInvariantError):
        return "harness_invariant"
    if isinstance(exc, AgentTimeoutError):
        return "agent_transport"
    if isinstance(exc, AgentTransportError):
        return "agent_transport"
    if isinstance(exc, (TimeoutError, ConnectionError, OSError)):
        return "infrastructure_transient"
    return "code_runtime"


def error_fingerprint(*, failure_class: str, error: str, context: dict[str, Any] | None = None) -> str:
    normalized = " ".join(str(error).split())[:2000]
    payload = {"failure_class": failure_class, "error": normalized, "context": context or {}}
    return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()[:20]


def recovery_limits(problem_id: str | None = None, question_id: str | None = None) -> dict[str, int]:
    config = read_yaml(ROOT / "config" / "orchestrator.yaml")
    if problem_id and question_id:
        config = {**config, **config_section("workflow", problem_id, question_id).get("recovery", {})}
    config = config.get("recovery", config)
    return {
        "max_productive_rounds": int(config.get("max_productive_rounds", 10)),
        "same_fingerprint_limit": int(config.get("same_fingerprint_limit", 2)),
        "infrastructure_retries": int(config.get("infrastructure_retries", 3)),
    }


def note_recovery(
    state: dict[str, Any],
    *,
    failure_class: str,
    error: str,
    progress: dict[str, Any] | None = None,
    problem_id: str | None = None,
    question_id: str | None = None,
) -> dict[str, Any]:
    """更新恢复计数；同一指纹无进展两轮后切换收敛模式。"""
    progress = progress or {}
    recovery = dict(state.get("recovery") or {})
    limits = recovery_limits(problem_id, question_id)
    fingerprint = error_fingerprint(failure_class=failure_class, error=error, context=progress)
    previous = recovery.get("last_fingerprint")
    productive = bool(progress.get("productive"))
    recovery["total_rounds"] = int(recovery.get("total_rounds", 0)) + 1
    recovery["productive_rounds"] = int(recovery.get("productive_rounds", 0)) + int(productive)
    recovery["same_fingerprint_streak"] = int(recovery.get("same_fingerprint_streak", 0)) + 1 if previous == fingerprint else 1
    recovery.update({
        "last_fingerprint": fingerprint,
        "last_failure_class": failure_class,
        "last_error": error[:2000],
        "last_progress": progress,
        "updated_at": utc_now(),
    })
    if recovery["same_fingerprint_streak"] >= limits["same_fingerprint_limit"]:
        recovery["mode"] = "convergence"
    if recovery["productive_rounds"] >= limits["max_productive_rounds"]:
        recovery["mode"] = "degraded_review"
    state["recovery"] = recovery
    state["failure_class"] = failure_class
    if recovery.get("mode") == "degraded_review":
        state["recovery_status"] = "degraded_review"
    elif failure_class in HUMAN_BLOCK_CLASSES:
        state["recovery_status"] = "human_blocked"
    elif failure_class == "harness_invariant":
        state["recovery_status"] = "harness_invariant_error"
    elif failure_class == "quality_warning":
        state["recovery_status"] = "degraded_review"
    else:
        state["recovery_status"] = "retrying"
    return state


def can_human_block(failure_class: str) -> bool:
    return failure_class in HUMAN_BLOCK_CLASSES


def is_productive_progress(before: dict[str, Any], after: dict[str, Any]) -> bool:
    keys = ("code_hash", "error_fingerprint", "feasibility", "strategy", "formulation_version")
    return any(before.get(key) != after.get(key) and after.get(key) not in (None, "") for key in keys)
