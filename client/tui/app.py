from __future__ import annotations

import json
import time
from datetime import datetime
from pathlib import Path
from typing import cast

from textual import events
from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widget import Widget
from textual.widgets import Footer, Header, Input

from client.api.server_client import ServerClient, load_client_config
from client.tui.commands import CommandParseError, parse_command, require_arg
from client.tui.screens import HelpScreen, LogScreen, SessionScreen, StatusScreen
from client.tui.widgets import CommandHistoryPanel, ReadyQueuePanel, SessionCard


ROOT = Path(__file__).resolve().parents[2]


class AutoMMTui(App):
    CSS_PATH = "styles.tcss"
    BINDINGS = [("ctrl+c", "request_exit", "Exit")]

    def __init__(self) -> None:
        super().__init__()
        self.config = load_client_config()
        self.client = ServerClient(self.config)
        self.history: list[str] = []
        self.selected: str | None = None
        self.drag_display_id: str | None = None
        self.suppress_session_click_until = 0.0
        self.command_history_path = ROOT / "client" / "state" / "command_history.jsonl"

    def compose(self) -> ComposeResult:
        yield Header()
        with Horizontal(id="main"):
            with Vertical(id="sessions"):
                for session_id in range(6):
                    yield SessionCard(id=f"session-{session_id}")
            with Vertical(id="side"):
                yield ReadyQueuePanel(id="queue")
                yield CommandHistoryPanel(id="history")
        yield Input(placeholder="> /help", id="input")
        yield Footer()

    def on_mount(self) -> None:
        self._load_history()
        self.set_interval(self.config.refresh_interval_seconds, self.refresh_dashboard)
        self.refresh_dashboard()

    def on_unmount(self) -> None:
        self.client.close()

    def action_request_exit(self) -> None:
        self.exit()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        command_text = event.value.strip()
        event.input.value = ""
        if not command_text:
            return
        self.run_command(command_text)

    def on_mouse_up(self, event: events.MouseUp) -> None:
        if self.drag_display_id is None or event.screen_x is None or event.screen_y is None:
            return
        self.drop_experiment_at(int(event.screen_x), int(event.screen_y))

    def run_command(self, command_text: str) -> None:
        try:
            command = parse_command(command_text)
            if command.name == "/help":
                self._record_command(command_text, True, "help")
                self.push_screen(HelpScreen())
            elif command.name == "/return":
                scan = self.client.scan()
                state = self.client.dashboard_state()
                self._record_command(command_text, scan.ok and state.ok, scan.message or state.message)
                self.refresh_dashboard()
            elif command.name == "/select":
                display_id = require_arg(command, 0, "display_id")
                result = self.client.select(display_id)
                if result.ok:
                    self.selected = display_id
                self._record_command(command_text, result.ok, result.message)
                self.refresh_dashboard()
            elif command.name == "/run":
                session_id = int(require_arg(command, 0, "session_id"))
                accelerator = "gpu" if command.gpu else "none"
                result = self.client.run(session_id, self.selected, accelerator)
                self._record_command(command_text, result.ok, result.message)
                self.refresh_dashboard()
            elif command.name == "/status":
                session_id = int(require_arg(command, 0, "session_id"))
                self._record_command(command_text, True, "open status")
                self.push_screen(StatusScreen("status", self.client, session_id))
            elif command.name == "/log":
                session_id = int(require_arg(command, 0, "session_id"))
                self._record_command(command_text, True, "open log")
                self.push_screen(LogScreen("log", self.client, session_id))
            elif command.name == "/session":
                session_id = int(require_arg(command, 0, "session_id"))
                self._record_command(command_text, True, "open session")
                self.push_screen(SessionScreen("session", self.client, session_id))
            elif command.name == "/stop":
                session_id = int(require_arg(command, 0, "session_id"))
                result = self.client.stop(session_id)
                self._record_command(command_text, result.ok, result.message)
                self.refresh_dashboard()
            elif command.name == "/clear":
                session_id = int(require_arg(command, 0, "session_id"))
                result = self.client.clear(session_id)
                self._record_command(command_text, result.ok, result.message)
                self.refresh_dashboard()
            elif command.name == "/exit":
                self._record_command(command_text, True, "exit")
                self.exit()
        except (CommandParseError, ValueError) as exc:
            self._record_command(command_text, False, str(exc))
            self.refresh_history()

    def select_experiment_from_mouse(self, display_id: str) -> None:
        result = self.client.select(display_id)
        if result.ok:
            self.selected = display_id
        self._record_command(f"[mouse] select {display_id}", result.ok, result.message)
        self.refresh_dashboard()

    def start_drag_experiment(self, display_id: str) -> None:
        self.drag_display_id = display_id
        result = self.client.select(display_id)
        if result.ok:
            self.selected = display_id
        self._record_command(f"[drag] pick {display_id}", result.ok, result.message)
        self.refresh_dashboard()

    def drop_experiment_at(self, screen_x: int, screen_y: int) -> None:
        if self.drag_display_id is None:
            return
        session = self._session_card_at(screen_x, screen_y)
        display_id = self.drag_display_id
        self.drag_display_id = None
        if session is None or session.session_id is None:
            self._record_command(f"[drag] cancel {display_id}", False, "drop target is not a session")
            return
        self.suppress_session_click_until = time.monotonic() + 0.5
        self._run_session(session.session_id, display_id, "none", f"[drag] drop {display_id} -> {session.session_id}")

    def run_selected_on_session(self, session_id: int) -> None:
        if time.monotonic() < self.suppress_session_click_until:
            return
        if not self.selected:
            self._record_command(f"[mouse] run {session_id}", False, "no experiment selected")
            self.refresh_history()
            return
        self._run_session(session_id, self.selected, "none", f"[mouse] run {self.selected} -> {session_id}")

    def _run_session(self, session_id: int, display_id: str | None, accelerator: str, history_label: str) -> None:
        result = self.client.run(session_id, display_id, accelerator)
        self._record_command(history_label, result.ok, result.message)
        self.refresh_dashboard()

    def refresh_dashboard(self) -> None:
        result = self.client.dashboard_state()
        if not result.ok:
            self._record_command("[auto-refresh]", False, result.message)
            self.refresh_history()
            return
        data = result.data or {}
        self.selected = data.get("selected") or self.selected
        for session in data.get("sessions", []):
            widget = self.query_one(f"#session-{session['session_id']}", SessionCard)
            widget.update_session(session)
        self.query_one("#queue", ReadyQueuePanel).update_queue(data.get("ready_queue", []), data.get("selected"))
        self.refresh_history()

    def refresh_history(self) -> None:
        self.query_one("#history", CommandHistoryPanel).update_history(self.history)

    def _record_command(self, command: str, ok: bool, message: str) -> None:
        line = f"{datetime.now().strftime('%H:%M:%S')} {command} {'OK' if ok else 'ERR'} {message}"
        self.history.append(line)
        self.command_history_path.parent.mkdir(parents=True, exist_ok=True)
        with self.command_history_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps({"ts": datetime.now().astimezone().isoformat(), "command": command, "ok": ok, "message": message}, ensure_ascii=False) + "\n")
        self.refresh_history()

    def _load_history(self) -> None:
        if not self.command_history_path.exists():
            return
        lines = self.command_history_path.read_text(encoding="utf-8", errors="replace").splitlines()[-30:]
        for line in lines:
            try:
                item = json.loads(line)
                status = "OK" if item.get("ok") else "ERR"
                ts = self._format_ts(str(item.get("ts", "")))
                self.history.append(f"{ts} {item.get('command')} {status} {item.get('message')}")
            except json.JSONDecodeError:
                continue

    def _session_card_at(self, screen_x: int, screen_y: int) -> SessionCard | None:
        widget, _region = self.get_widget_at(screen_x, screen_y)
        current: Widget | None = widget
        while current is not None:
            if isinstance(current, SessionCard):
                return cast(SessionCard, current)
            current = current.parent
        return None

    def _format_ts(self, value: str) -> str:
        try:
            return datetime.fromisoformat(value).strftime("%H:%M:%S")
        except ValueError:
            return value[-8:] if len(value) >= 8 else value


def main() -> None:
    AutoMMTui().run()


if __name__ == "__main__":
    main()
