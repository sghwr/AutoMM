"""Agent 调用（Provider 抽象）、响应校验和受控命令事务。"""

from __future__ import annotations

import json
import os
import subprocess
import uuid
from pathlib import Path
from typing import Any

import jsonschema
import psutil

from .common import ROOT, RUNTIME_DIR, append_jsonl, read_json, read_yaml, relative, resolve_project_path, utc_now, write_json
from .failure_policy import AgentCommandError, AgentTimeoutError, AgentTransportError, HarnessInvariantError, stage_timeout_seconds
from .llm import ProviderError, get_provider
from .problems import decide_assumption_version, decide_formulation_version, problem_dir, question_manifest
from .state import append_ledger
from .visualization import record_figure_review
from .workflow import clear_stale, mark_cross_question_review, record_artifact, record_conclusion, record_optional_stage, record_sanity, transition


class AgentRuntimeError(AgentTransportError):
    """Agent 传输层或运行时错误。"""


def _terminate_process_tree(process: subprocess.Popen, grace_seconds: float = 5.0) -> None:
    try:
        parent = psutil.Process(process.pid)
        targets = [*parent.children(recursive=True), parent]
    except psutil.Error:
        targets = []
    for target in reversed(targets):
        try:
            target.terminate()
        except psutil.Error:
            pass
    _, alive = psutil.wait_procs(targets, timeout=grace_seconds)
    for target in alive:
        try:
            target.kill()
        except psutil.Error:
            pass


def runtime_config() -> dict[str, Any]:
    return read_yaml(ROOT / "config" / "agent_runtime.yaml")


def registry() -> dict[str, Any]:
    path = resolve_project_path(runtime_config()["registry"], must_exist=True)
    return read_yaml(path).get("agents", {})


def _agent_prompt(agent: str, action: dict[str, Any], action_id: str) -> str:
    entry = registry().get(agent)
    if not entry or entry.get("enabled") is False:
        raise AgentRuntimeError(f"Agent 未注册或已禁用：{agent}")
    prompt_path = resolve_project_path(entry["prompt"], must_exist=True)
    instructions = prompt_path.read_text(encoding="utf-8")
    recovery_mode = (action.get("recovery") or {}).get("mode")
    recovery_hint = ""
    if recovery_mode == "convergence":
        recovery_hint = "\n注意：当前处于「收敛模式」（同一失败已连续发生多次）。请复用已有产物，只做最小静态检查并生成合规响应，不要再重复之前失败的操作。\n"
    elif recovery_mode == "degraded_review":
        recovery_hint = "\n注意：当前处于「降级审查模式」。请基于已有产物给出结论性响应，不要再发起新计算。\n"
    return f"""你正在作为 AutoMM 专职 Agent `{agent}` 执行一次同步动作。
必须遵守项目根目录 AGENTS.md 中的 AutoMM Agent 规则，并参考 PROJECT.md（项目指南）与 RESEARCH_LOOP.md（研究循环）。专职说明如下：

<agent_instructions>
{instructions}
</agent_instructions>

本次动作（机器事实）：
```json
{json.dumps(action, ensure_ascii=False, indent=2)}
```
{recovery_hint}
必须原样返回 action_id `{action_id}`。先读取相关机器状态和产物，再完成当前阶段工作。
最终响应只能是符合 `config/agent_response.schema.json` 的 JSON，不要使用 Markdown 代码块。
状态只能通过 `commands` 白名单请求修改；不要直接编辑 runtime/workflow_state.json 或小问 manifest 的受保护字段。
每个 command 的 arguments 只填写该命令自身参数，不要重复 problem_id 或 question_id；Runner 会从动作上下文补齐。
"""


def invoke_agent(agent: str, action: dict[str, Any], action_id: str) -> tuple[dict[str, Any], dict[str, Any]]:
    config = runtime_config()
    provider = get_provider(config)
    try:
        if config.get("capability_probe_on_start", True):
            provider.probe()
    except ProviderError as exc:
        raise AgentTransportError(str(exc)) from exc
    run_dir = RUNTIME_DIR / "actions" / action_id
    run_dir.mkdir(parents=True, exist_ok=False)
    output_path = run_dir / "response.json"
    events_path = run_dir / "agent_events.jsonl"
    stdout_path, stderr_path = run_dir / "stdout.log", run_dir / "stderr.log"
    schema_path = resolve_project_path(config["output_schema"], must_exist=True)
    prompt = _agent_prompt(agent, action, action_id)
    invocation = provider.prepare(prompt, output_path)
    timeout_seconds = stage_timeout_seconds(str(action.get("stage") or ""))
    process: subprocess.Popen | None = None
    try:
        flags = subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
        process = subprocess.Popen(
            invocation.command,
            cwd=ROOT,
            stdin=subprocess.PIPE if invocation.stdin is not None else subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            shell=False,
            start_new_session=os.name != "nt",
            creationflags=flags,
            env=invocation.env,
        )
        stdout, stderr = process.communicate(input=invocation.stdin, timeout=timeout_seconds or None)
    except subprocess.TimeoutExpired as exc:
        if process is not None:
            _terminate_process_tree(process)
            try:
                stdout, stderr = process.communicate(timeout=10)
            except subprocess.TimeoutExpired:
                stdout, stderr = "", "Agent 进程终止后仍未退出"
        else:
            stdout, stderr = "", "Agent 进程尚未启动"
        stdout_path.write_text(stdout or "", encoding="utf-8")
        stderr_path.write_text(stderr or "", encoding="utf-8")
        events_path.write_text(stdout or "", encoding="utf-8")
        write_json(run_dir / "status.json", {"action_id": action_id, "status": "timed_out", "execution_status": "timed_out", "failure_class": "agent_transport", "timeout_seconds": timeout_seconds, "at": utc_now()})
        raise AgentTimeoutError(f"Agent {agent} 超时（{timeout_seconds} 秒）") from exc
    except (OSError, subprocess.SubprocessError) as exc:
        write_json(run_dir / "status.json", {"action_id": action_id, "status": "transport_failed", "failure_class": "agent_transport", "at": utc_now()})
        raise AgentTransportError(f"Agent {agent} 传输失败：{exc}") from exc
    stdout_path.write_text(stdout, encoding="utf-8")
    stderr_path.write_text(stderr, encoding="utf-8")
    events_path.write_text(stdout, encoding="utf-8")
    try:
        response = provider.extract_response(invocation, stdout, stderr, process.returncode)
    except ProviderError as exc:
        raise AgentTransportError(f"Agent {agent} 响应提取失败：{exc}") from exc
    raw_size = output_path.stat().st_size if output_path.exists() else len(stdout or "")
    if raw_size > int(config.get("max_output_chars", 200000)) * 4:
        raise AgentRuntimeError("Agent 最终响应超过配置大小上限")
    schema = read_json(schema_path)
    try:
        jsonschema.validate(response, schema)
    except jsonschema.ValidationError as exc:
        raise AgentCommandError(f"Agent response schema 校验失败：{exc.message}") from exc
    if response["action_id"] != action_id:
        # action_id 未回显属 LLM 瞬时错误，重试即可；不应上升为 harness_invariant 硬阻塞。
        raise AgentTransportError("Agent 响应 action_id 不匹配")
    _validate_response_context(response, action)
    meta = {"command": invocation.command, "provider": provider.backend, "run_directory": relative(run_dir), "returncode": process.returncode}
    write_json(run_dir / "status.json", {"action_id": action_id, "status": "validated", "at": utc_now(), **meta})
    return response, meta


def _validate_response_context(response: dict[str, Any], action: dict[str, Any]) -> None:
    for key in ("problem_id", "question_id"):
        expected = action.get(key)
        if expected is not None and response.get(key) != expected:
            raise AgentCommandError(f"Agent 响应 {key} 不匹配")
    for value in [*response["artifacts_created"], *response["artifacts_updated"]]:
        text = str(value)
        # 区分「文件路径」与「逻辑键」：逻辑键（无路径分隔符且无扩展名）不强制文件存在，
        # 避免 Agent 误填逻辑键（如 "formulation"）时被误判为路径缺失。
        if "/" in text or "\\" in text or Path(text).suffix:
            resolve_project_path(text, must_exist=True)
    if response["status"] in {"failed", "blocked"} and response["commands"]:
        raise AgentCommandError("failed/blocked 响应不得携带状态变更命令")
    for command in response["commands"]:
        for key in ("problem_id", "question_id"):
            if key in command["arguments"] and action.get(key) is not None and command["arguments"][key] != action[key]:
                raise AgentCommandError(f"Agent 命令 {command['name']} 的 {key} 越出本次动作上下文")


_ALLOWED_COMMANDS = {"record_artifact", "record_optional_stage", "record_conclusion", "clear_stale", "append_ledger", "record_figure_review", "record_sanity", "decide_assumption_version", "decide_formulation_version", "mark_cross_question_review", "transition"}
_COMMAND_PRIORITY = {"record_artifact": 10, "record_optional_stage": 10, "record_conclusion": 10, "clear_stale": 10, "append_ledger": 10, "record_figure_review": 10, "record_sanity": 20, "decide_assumption_version": 20, "decide_formulation_version": 20, "mark_cross_question_review": 20, "transition": 30}


def _transaction_paths(problem_id: str | None) -> list[Path]:
    paths = [RUNTIME_DIR / "workflow_state.json", RUNTIME_DIR / "events.jsonl", RUNTIME_DIR / "agent_commands.jsonl", ROOT / "reports" / "autoresearch" / "STATE.md", ROOT / "reports" / "autoresearch" / "experiment_ledger.md"]
    if problem_id:
        root = problem_dir(problem_id)
        if root.exists():
            paths.extend(path for path in root.rglob("*") if path.is_file() and (path.name in {"manifest.yaml", "problem_state.json", "dependency_graph.yaml", "figures.yaml"} or path.suffix == ".yaml"))
    return list(dict.fromkeys(paths))


def _snapshot(paths: list[Path]) -> dict[Path, bytes | None]:
    return {path: path.read_bytes() if path.exists() else None for path in paths}


def _restore(snapshot: dict[Path, bytes | None]) -> None:
    for path, data in snapshot.items():
        if data is None:
            if path.exists():
                path.unlink()
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)


def _apply_one(name: str, args: dict[str, Any]) -> Any:
    if name == "transition":
        return transition(target_stage=args.pop("target_stage"), reason=args.pop("reason"), **args)
    if name == "record_artifact":
        return record_artifact(**args)
    if name == "record_sanity":
        return record_sanity(**args)
    if name == "record_optional_stage":
        return record_optional_stage(**args)
    if name == "record_conclusion":
        return record_conclusion(**args)
    if name == "clear_stale":
        return clear_stale(**args)
    if name == "append_ledger":
        args.pop("problem_id", None)
        args.pop("question_id", None)
        args.setdefault("at", utc_now())
        append_ledger(args)
        return {"appended": True}
    if name == "decide_assumption_version":
        return decide_assumption_version(**args)
    if name == "decide_formulation_version":
        return decide_formulation_version(**args)
    if name == "mark_cross_question_review":
        mark_cross_question_review(**args)
        return {"recorded": True}
    if name == "record_figure_review":
        return record_figure_review(**args)
    raise AgentCommandError(f"不支持的 Agent 命令：{name}")


def apply_agent_commands(response: dict[str, Any], action: dict[str, Any]) -> list[dict[str, Any]]:
    """预验证后原子应用命令批次；任意失败都会恢复批次前快照。"""
    commands = response.get("commands", [])
    if any(command.get("name") not in _ALLOWED_COMMANDS for command in commands):
        raise AgentCommandError("Agent command 不在白名单内")
    problem_id, question_id = action.get("problem_id"), action.get("question_id")
    if problem_id and question_id:
        _, manifest = question_manifest(problem_id, question_id)
        valid_artifacts = set(manifest.get("artifacts", {}))
        for command in commands:
            if command["name"] == "record_artifact" and command["arguments"]["name"] not in valid_artifacts:
                raise AgentCommandError(f"未知逻辑 artifact key：{command['arguments']['name']}")
    # 局部完成门禁依赖 conclusion；任何 transition 到 locally_completed 的批次
    # 必须先在同一批次里调用 record_conclusion，否则在应用命令前直接拒绝，
    # 避免先写入部分状态再回滚的 blocked 循环。
    if any(
        command.get("name") == "transition"
        and str(command.get("arguments", {}).get("target_stage", "")) == "locally_completed"
        for command in commands
    ) and not any(command.get("name") == "record_conclusion" for command in commands):
        raise AgentCommandError(
            "Agent command batch 缺少 record_conclusion：transition 到 locally_completed 前"
            "必须先在同一个批次记录结论（conclusion_id/content）"
        )
    ordered = sorted(enumerate(commands), key=lambda item: (_COMMAND_PRIORITY[item[1]["name"]], item[0]))
    snapshot = _snapshot(_transaction_paths(problem_id))
    append_jsonl(RUNTIME_DIR / "agent_command_transactions.jsonl", {"at": utc_now(), "action_id": response["action_id"], "phase": "started", "count": len(commands)})
    applied: list[dict[str, Any]] = []
    try:
        for index, command in ordered:
            name, args = command["name"], dict(command["arguments"])
            args.setdefault("problem_id", problem_id)
            if name not in {"mark_cross_question_review", "record_figure_review"}:
                args.setdefault("question_id", question_id)
            value = _apply_one(name, args)
            record = {"index": index, "name": name, "result": value}
            applied.append(record)
            append_jsonl(RUNTIME_DIR / "agent_commands.jsonl", {"at": utc_now(), "action_id": response["action_id"], **record})
    except Exception as exc:
        _restore(snapshot)
        append_jsonl(RUNTIME_DIR / "agent_command_transactions.jsonl", {"at": utc_now(), "action_id": response["action_id"], "phase": "invariant_error", "error": str(exc), "applied": applied})
        raise AgentCommandError(f"Agent command batch 未能完整应用，已回滚：{exc}") from exc
    append_jsonl(RUNTIME_DIR / "agent_command_transactions.jsonl", {"at": utc_now(), "action_id": response["action_id"], "phase": "committed", "applied": applied})
    return applied


def new_action_id() -> str:
    return f"act-{uuid.uuid4().hex[:16]}"