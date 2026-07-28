from __future__ import annotations

from rich.panel import Panel
from rich.pretty import Pretty
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.screen import Screen
from textual.widgets import Footer, Header, Static

from client.api.server_client import ServerClient
from client.tui.commands import HELP_TEXT


class ReadOnlyScreen(Screen):
    BINDINGS = [("q", "app.pop_screen", "Back")]

    def __init__(self, title: str, client: ServerClient, session_id: int | None = None) -> None:
        super().__init__()
        self.title_text = title
        self.client = client
        self.session_id = session_id
        self.content = Static()

    def compose(self) -> ComposeResult:
        yield Header()
        with Vertical(id="readonly"):
            yield self.content
        yield Footer()


class HelpScreen(Screen):
    BINDINGS = [("q", "app.pop_screen", "Back")]

    def compose(self) -> ComposeResult:
        yield Header()
        yield Static(Panel(HELP_TEXT, title="Help"))
        yield Footer()


class StatusScreen(ReadOnlyScreen):
    def on_mount(self) -> None:
        self.set_interval(1, self.refresh_content)
        self.refresh_content()

    def refresh_content(self) -> None:
        assert self.session_id is not None
        result = self.client.status(self.session_id)
        self.content.update(Panel(Pretty(result.data), title=f"Status {self.session_id}"))


class LogScreen(ReadOnlyScreen):
    def on_mount(self) -> None:
        self.set_interval(1, self.refresh_content)
        self.refresh_content()

    def refresh_content(self) -> None:
        assert self.session_id is not None
        result = self.client.log(self.session_id, tail=None)
        data = result.data or {}
        self.content.update(Panel(data.get("content", ""), title=f"Log {self.session_id}"))


class SessionScreen(ReadOnlyScreen):
    def on_mount(self) -> None:
        self.set_interval(1, self.refresh_content)
        self.refresh_content()

    def refresh_content(self) -> None:
        assert self.session_id is not None
        result = self.client.session(self.session_id)
        self.content.update(Panel(Pretty(result.data), title=f"Session {self.session_id}"))

