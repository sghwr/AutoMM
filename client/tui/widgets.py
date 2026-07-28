from __future__ import annotations

from rich.panel import Panel
from rich.table import Table
from textual.widgets import Static


def gauge(progress: int | None, status: str) -> str:
    if progress is None:
        return "   ◜ ◝\n    ◉\n   ◟ ◞"
    progress = max(0, min(100, int(progress)))
    filled = int(progress / 10)
    bar = "█" * filled + "░" * (10 - filled)
    needle = min(9, int(progress / 10))
    pointer = " " * needle + "▲"
    return f" {progress:3d}%\n◜{bar}◝\n {pointer}"


class SessionCard(Static):
    def update_session(self, session: dict) -> None:
        session_id = session.get("session_id")
        backend = str(session.get("backend") or "").upper()
        status = str(session.get("status") or "UNKNOWN")
        accelerator = session.get("accelerator")
        gpu_label = session.get("gpu_label")
        display_id = session.get("display_id") or "-"
        progress = session.get("progress")
        last_line = session.get("last_output_line") or ""
        badge = f"[{backend}]"
        if accelerator == "gpu":
            badge += f"[GPU {gpu_label or 'requested'}]"
        body = (
            f"{badge} {status} {display_id}\n"
            f"{gauge(progress, status)}\n"
            f"last: {last_line[-90:]}"
        )
        self.update(Panel(body, title=f"Session {session_id}", border_style=self._style_for(status)))

    def _style_for(self, status: str) -> str:
        return {
            "IDLE": "dim",
            "DONE": "green",
            "FAILED": "red",
            "INVALID": "red",
            "RUNNING": "cyan",
            "PUSHING": "blue",
            "QUEUED": "yellow",
            "RETURNING": "magenta",
        }.get(status, "white")


class ReadyQueuePanel(Static):
    def update_queue(self, items: list[dict], selected: str | None) -> None:
        table = Table.grid(expand=True)
        table.add_column(ratio=1)
        if not items:
            table.add_row("no ready experiments")
        for item in items:
            marker = ">" if item.get("display_id") == selected else " "
            table.add_row(
                f"{marker} {item.get('display_id')}  {item.get('kind')}  "
                f"{item.get('competition')}  {item.get('status')}  {item.get('title')}"
            )
        self.update(Panel(table, title="Ready Queue", border_style="green"))


class CommandHistoryPanel(Static):
    def update_history(self, history: list[str]) -> None:
        body = "\n".join(history[-30:]) if history else "no commands yet"
        self.update(Panel(body, title="Command History", border_style="blue"))

