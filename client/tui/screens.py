from __future__ import annotations

from rich.panel import Panel
from rich.pretty import Pretty
from textual.app import ComposeResult
from textual.containers import VerticalScroll
from textual.screen import Screen
from textual.widgets import Footer, Header, Log, RichLog, Static

from client.api.server_client import ServerClient
from client.tui.commands import HELP_TEXT


class ReadOnlyScreen(Screen):
    BINDINGS = [("q", "app.pop_screen", "Back")]

    def __init__(self, title: str, client: ServerClient, session_id: int | None = None) -> None:
        super().__init__()
        self.title_text = title
        self.client = client
        self.session_id = session_id
        self.content = RichLog(markup=False, wrap=True)

    def compose(self) -> ComposeResult:
        yield Header()
        with VerticalScroll(id="readonly"):
            yield self.content
        yield Footer()


class HelpScreen(Screen):
    BINDINGS = [("q", "app.pop_screen", "Back")]

    def compose(self) -> ComposeResult:
        yield Header()
        with VerticalScroll(id="readonly"):
            yield Static(Panel(HELP_TEXT, title="Help"))
        yield Footer()


class StatusScreen(ReadOnlyScreen):
    def on_mount(self) -> None:
        self.set_interval(1, self.refresh_content)
        self.refresh_content()

    def refresh_content(self) -> None:
        assert self.session_id is not None
        result = self.client.status(self.session_id)
        self.content.clear()
        self.content.border_title = f"Status {self.session_id}"
        self.content.write(Pretty(result.data), scroll_end=False)


class LogScreen(ReadOnlyScreen):
    def __init__(self, title: str, client: ServerClient, session_id: int | None = None) -> None:
        super().__init__(title, client, session_id)
        self.content = Log(highlight=True)

    def on_mount(self) -> None:
        self.set_interval(1, self.refresh_content)
        self.refresh_content()

    def refresh_content(self) -> None:
        assert self.session_id is not None
        result = self.client.log(self.session_id, tail=None)
        data = result.data or {}
        self.content.clear()
        self.content.border_title = f"Log {self.session_id}"
        content = data.get("content", "")
        if not content:
            self.content.write_line("no log content")
            return
        for line in str(content).splitlines():
            self.content.write_line(line)
        self.content.scroll_end(animate=False)


class SessionScreen(ReadOnlyScreen):
    def on_mount(self) -> None:
        self.set_interval(1, self.refresh_content)
        self.refresh_content()

    def refresh_content(self) -> None:
        assert self.session_id is not None
        result = self.client.session(self.session_id)
        self.content.clear()
        self.content.border_title = f"Session {self.session_id}"
        self.content.write(Pretty(result.data), scroll_end=False)
