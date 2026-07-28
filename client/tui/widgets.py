from __future__ import annotations

import math
from typing import Any

from rich.console import Group
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from textual import events
from textual.widgets import Log, Static


STATUS_STYLES = {
    "IDLE": "dim",
    "STARTING": "bright_blue",
    "PUSHING": "blue",
    "QUEUED": "yellow",
    "RUNNING": "cyan",
    "RETURNING": "magenta",
    "DONE": "green",
    "FAILED": "red",
    "STOPPED": "bright_black",
    "INVALID": "red",
}


def gauge(progress: int | None, status: str) -> Group:
    style = STATUS_STYLES.get(status, "white")
    if progress is None:
        return Group(
            Text("      .-----.      ", style=style),
            Text("   .-'  ...  '-.   ", style=style),
            Text("  /   scanning  \\  ", style=style),
            Text("  \\      |      /  ", style=style),
            Text("   '-._____.-'     ", style=style),
        )

    progress = max(0, min(100, int(progress)))
    angle = math.radians(210 + progress * 1.2)
    needle = _needle_for(angle)
    filled = int(progress / 5)
    arc = "#" * filled + "." * (20 - filled)
    return Group(
        Text("      .-----.      ", style=style),
        Text(f"   .-' {progress:3d}% '-.   ", style=style),
        Text(f"  / {arc[:10]} \\  ", style=style),
        Text(f"  \\ {arc[10:]} /  ", style=style),
        Text(f"   '-.__{needle}__.-'     ", style=style),
    )


def _needle_for(angle: float) -> str:
    value = math.sin(angle)
    if value < -0.45:
        return "\\"
    if value > 0.45:
        return "/"
    return "|"


class SessionCard(Static):
    can_focus = True

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.session_id: int | None = None
        self.session: dict[str, Any] = {}

    def update_session(self, session: dict[str, Any]) -> None:
        self.session = session
        self.session_id = int(session.get("session_id", 0))
        backend = str(session.get("backend") or "").upper()
        status = str(session.get("status") or "UNKNOWN")
        accelerator = session.get("accelerator")
        gpu_label = session.get("gpu_label")
        display_id = session.get("display_id") or "-"
        progress = session.get("progress")
        last_line = str(session.get("last_output_line") or "")[-90:]
        badge = f"[{backend}]"
        if accelerator == "gpu":
            badge += f"[GPU {gpu_label or 'requested'}]"

        body = Group(
            Text(f"{badge} {status} {display_id}", style=self._style_for(status)),
            gauge(progress, status),
            Text(f"last: {last_line}", style="white"),
            Text("mouse: drop here or click to run selected", style="dim"),
        )
        self.update(Panel(body, title=f"Session {self.session_id}", border_style=self._style_for(status)))

    def on_click(self, event: events.Click) -> None:
        if self.session_id is not None:
            self.app.run_selected_on_session(self.session_id)
            event.stop()

    def _style_for(self, status: str) -> str:
        return STATUS_STYLES.get(status, "white")


class ReadyQueuePanel(Static):
    can_focus = True

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.items: list[dict[str, Any]] = []
        self.selected: str | None = None
        self.row_display_ids: list[str] = []

    def update_queue(self, items: list[dict[str, Any]], selected: str | None) -> None:
        self.items = items
        self.selected = selected
        self.row_display_ids = []
        table = Table.grid(expand=True)
        table.add_column(ratio=1)
        if not items:
            table.add_row("no ready experiments")
        for item in items:
            display_id = str(item.get("display_id"))
            self.row_display_ids.append(display_id)
            marker = ">" if display_id == selected else " "
            style = "reverse green" if display_id == selected else "white"
            table.add_row(
                Text(
                    f"{marker} {display_id}  {item.get('kind')}  "
                    f"{item.get('competition')}  {item.get('status')}  {item.get('title')}",
                    style=style,
                )
            )
        self.update(Panel(table, title="Ready Queue", subtitle="click or drag to a session", border_style="green"))

    def on_mouse_down(self, event: events.MouseDown) -> None:
        display_id = self._display_id_at_y(event.y)
        if display_id:
            self.app.start_drag_experiment(display_id)
            event.stop()

    def on_mouse_up(self, event: events.MouseUp) -> None:
        if event.screen_x is None or event.screen_y is None:
            return
        self.app.drop_experiment_at(int(event.screen_x), int(event.screen_y))
        event.stop()

    def on_click(self, event: events.Click) -> None:
        display_id = self._display_id_at_y(event.y)
        if display_id:
            self.app.select_experiment_from_mouse(display_id)
            event.stop()

    def _display_id_at_y(self, y: float) -> str | None:
        index = max(0, int(y) - 1)
        if 0 <= index < len(self.row_display_ids):
            return self.row_display_ids[index]
        return None


class CommandHistoryPanel(Log):
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.border_title = "Command History"
        self.border_subtitle = "scroll"

    def update_history(self, history: list[str]) -> None:
        self.clear()
        if not history:
            self.write_line("no commands yet")
            return
        for line in history:
            self.write_line(line)
        self.scroll_end(animate=False)
