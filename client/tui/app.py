from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical
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
                self.history.append(f"{item.get('ts', '')[-14:-6]} {item.get('command')} {status} {item.get('message')}")
            except json.JSONDecodeError:
                continue


def main() -> None:
    AutoMMTui().run()


if __name__ == "__main__":
    main()
