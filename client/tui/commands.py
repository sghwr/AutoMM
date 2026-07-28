from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ParsedCommand:
    name: str
    args: tuple[str, ...] = ()
    gpu: bool = False


class CommandParseError(ValueError):
    pass


def parse_command(raw: str) -> ParsedCommand:
    text = raw.strip()
    if not text:
        raise CommandParseError("empty command")
    parts = text.split()
    name = parts[0]
    if not name.startswith("/"):
        raise CommandParseError("commands must start with /")
    if name not in {
        "/help",
        "/return",
        "/select",
        "/run",
        "/status",
        "/log",
        "/session",
        "/stop",
        "/clear",
        "/exit",
    }:
        raise CommandParseError(f"unknown command: {name}")
    gpu = "--gpu" in parts[1:]
    args = tuple(part for part in parts[1:] if part != "--gpu")
    return ParsedCommand(name=name, args=args, gpu=gpu)


def require_arg(command: ParsedCommand, index: int, label: str) -> str:
    try:
        return command.args[index]
    except IndexError as exc:
        raise CommandParseError(f"missing {label}") from exc


HELP_TEXT = """\
/help                 show help
/return               scan experiments and refresh
/select exp001        select ready experiment
/run 0                run selected experiment on local session
/run 1                run selected experiment on kaggle cpu session
/run 1 --gpu          run selected experiment on kaggle gpu session
/status 2             open full status screen
/log 2                open full log screen
/session 2            open session detail screen
/stop 2               stop a running session after confirmation
/clear 2              clear a terminal session after confirmation
/exit                 exit TUI
"""

