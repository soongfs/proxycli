"""Textual TUI for proxycli — interactive node browsing and switching."""

from __future__ import annotations

import json
import socket
import time
from pathlib import Path

from textual import work
from textual.app import App, ComposeResult
from textual.coordinate import Coordinate
from textual.widgets import DataTable, Footer, Header

from proxycli import __version__
from proxycli.config import default_config_path, read_config
from proxycli.daemon import reload_daemon, status_daemon


class ProxyTuiApp(App):
    """Interactive terminal UI for proxycli."""

    CSS = ""

    BINDINGS = [
        ("j", "cursor_down", "Down"),
        ("k", "cursor_up", "Up"),
        ("enter", "select_node", "Switch"),
        ("r", "refresh", "Refresh"),
        ("t", "test_latency", "Test"),
        ("q", "quit", "Quit"),
    ]

    def run(
        self,
        *,
        headless: bool = False,
        size: tuple[int, int] | None = None,
    ) -> None:
        """Prevent os._exit() so main.py can print after TUI exits."""
        try:
            super().run(headless=headless, size=size)
        except SystemExit:
            pass

    def __init__(self, config_path: Path | None = None):
        super().__init__()
        self._config_path = config_path or default_config_path()
        self._outbounds: list[dict] = []
        self._tags: list[str] = []
        self._tag_to_index: dict[str, int] = {}
        self._current_tag: str | None = None
        self._latency_results: dict[str, str] = {}
        self.needs_restart: bool = False
        self.title = f"proxycli {__version__}"

    def compose(self) -> ComposeResult:
        yield Header(show_clock=False)
        yield DataTable(cursor_type="row")
        yield Footer()

    def on_mount(self) -> None:
        table = self.query_one(DataTable)
        table.add_column("#", width=4)
        table.add_column("Node", width=40)
        table.add_column("Latency", width=10)
        table.fixed_columns = 1
        self._refresh_data()

    def _read_config(self) -> dict:
        try:
            return read_config(self._config_path)
        except Exception:
            return {}

    def _refresh_data(self) -> None:
        config = self._read_config()
        self._tags = self._extract_node_tags(config)
        self._tag_to_index = {tag: i for i, tag in enumerate(self._tags)}
        self._current_tag = self._extract_current_node(config)

        outbounds = config.get("outbounds", [])
        self._outbounds = [
            o for o in outbounds
            if o.get("tag") in self._tags
            and o.get("server")
            and o.get("server_port")
        ]

        table = self.query_one(DataTable)
        table.clear()
        for i, tag in enumerate(self._tags):
            table.add_row(
                str(i + 1),
                tag,
                self._latency_results.get(tag, ""),
                key=tag,
            )

        self._update_status()

    def _extract_node_tags(self, config: dict) -> list[str]:
        for ob in config.get("outbounds", []):
            if ob.get("type") == "selector" and ob.get("tag") == "proxy":
                return [str(t) for t in ob.get("outbounds", [])]
        return []

    def _extract_current_node(self, config: dict) -> str | None:
        for ob in config.get("outbounds", []):
            if ob.get("type") == "selector" and ob.get("tag") == "proxy":
                return ob.get("default")
        return None

    def _update_status(self) -> None:
        daemon = "running" if status_daemon() else "stopped"
        current = self._current_tag or "none"
        self.sub_title = (
            f"daemon: {daemon} | node: {current} | nodes: {len(self._tags)}"
        )

    def action_cursor_down(self) -> None:
        table = self.query_one(DataTable)
        table.action_cursor_down()

    def action_cursor_up(self) -> None:
        table = self.query_one(DataTable)
        table.action_cursor_up()

    def action_select_node(self) -> None:
        table = self.query_one(DataTable)
        if table.row_count == 0:
            return

        table.action_select_cursor()

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        tag = str(event.row_key.value)
        if not tag or tag not in self._tags:
            return

        try:
            self._switch_node(tag)
            self._current_tag = tag
            self.needs_restart = True
            self._refresh_data()
        except Exception as exc:
            self.notify(f"Error: {exc}", severity="error")

    def _switch_node(self, tag: str) -> None:
        """Rewrite config to use the given node, then reload daemon."""
        config = self._read_config()
        found = False
        for ob in config.get("outbounds", []):
            if ob.get("type") == "selector" and ob.get("tag") == "proxy":
                if tag not in ob.get("outbounds", []):
                    raise ValueError(f"node {tag} not in selector")
                ob["default"] = tag
                found = True
                break
        if not found:
            raise ValueError("no proxy selector in config")

        config.setdefault("route", {})["final"] = tag
        for server in config.get("dns", {}).get("servers", []):
            if server.get("detour") == "proxy":
                server["detour"] = tag

        self._config_path.write_text(
            json.dumps(config, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )

        if status_daemon():
            try:
                reload_daemon()
            except PermissionError:
                self.notify(
                    "Config written. Restart daemon to apply: "
                    "sudo ~/.local/bin/proxycli daemon restart",
                    severity="warning",
                )

    def action_quit(self) -> None:
        self.exit()

    def action_refresh(self) -> None:
        self._refresh_data()
        self.notify("Refreshed")

    @work(thread=True)
    def action_test_latency(self) -> None:
        for node in list(self._outbounds):
            tag = str(node.get("tag", ""))
            if not tag:
                continue

            try:
                latency = self._tcp_ping(
                    str(node["server"]),
                    int(node["server_port"]),
                    timeout=3.0,
                )
                label = f"{latency:.0f}ms" if latency is not None else "timeout"
            except Exception:
                label = "err"

            self.call_from_thread(self._update_latency_cell, tag, label)

        self.call_from_thread(self.notify, "Latency test complete")

    def _update_latency_cell(self, tag: str, label: str) -> None:
        self._latency_results[tag] = label
        row = self._tag_to_index.get(tag)
        if row is None:
            return

        table = self.query_one(DataTable)
        try:
            if table.get_cell_at(Coordinate(row=row, column=1)) != tag:
                return
            table.update_cell_at(Coordinate(row=row, column=2), label)
        except Exception:
            return

    @staticmethod
    def _tcp_ping(host: str, port: int, timeout: float) -> float | None:
        try:
            start = time.monotonic()
            with socket.create_connection((host, port), timeout=timeout):
                elapsed = (time.monotonic() - start) * 1000
            return elapsed
        except (socket.timeout, ConnectionRefusedError, OSError):
            return None
