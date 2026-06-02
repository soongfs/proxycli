"""prompt_toolkit TUI for interactive node selection."""

from __future__ import annotations

import asyncio
import json
import socket
import time
from pathlib import Path
from typing import Any

from prompt_toolkit import Application
from prompt_toolkit.formatted_text import FormattedText
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.keys import Keys
from prompt_toolkit.layout import Layout, Window, FormattedTextControl
from prompt_toolkit.layout.containers import HSplit
from prompt_toolkit.styles import Style
from wcwidth import wcswidth

from proxycli.config import default_config_path, read_config
from proxycli.daemon import reload_daemon, status_daemon

Node = dict[str, Any]
Chunks = list[tuple[str, str]]


def _str(value: Any) -> str:
    return "" if value is None else str(value)


def _display_width(text: str) -> int:
    """Terminal display column width, handling CJK and emoji (2 wide each)."""
    return wcswidth(text) or 0


def _fit(value: Any, width: int) -> str:
    """Fit text to exactly *width* terminal display columns, truncating with ~."""
    text = _str(value).replace("\n", " ")
    dw = _display_width(text)
    if dw <= width:
        return text + " " * (width - dw)
    # Truncate character by character until display width fits width - 1 (+1 for ~)
    result = ""
    for ch in text:
        if _display_width(result + ch) > width - 1:
            break
        result += ch
    result += "~"
    # Pad to exactly width columns
    remaining = width - _display_width(result)
    if remaining > 0:
        result += " " * remaining
    return result


def _tag_cell(tag: str, active: bool) -> str:
    """Format tag cell: active node gets ' *' suffix, total display width = 30."""
    label = f"{tag} *" if active else tag
    return _fit(label, 30)


def _proxy_selector(config: dict[str, Any]) -> dict[str, Any] | None:
    for outbound in config.get("outbounds", []):
        if (
            isinstance(outbound, dict)
            and outbound.get("type") == "selector"
            and outbound.get("tag") == "proxy"
        ):
            return outbound
    return None


def _load_nodes(config_path: Path) -> tuple[list[Node], str, str]:
    try:
        config = read_config(config_path)
    except FileNotFoundError:
        return [], "", f"config file not found: {config_path}"
    except Exception as exc:
        return [], "", f"error reading config: {exc}"

    selector = _proxy_selector(config)
    if selector is None:
        return [], "", "no proxy selector outbound found"

    outbounds = config.get("outbounds", [])
    by_tag = {
        str(outbound.get("tag")): outbound
        for outbound in outbounds
        if isinstance(outbound, dict) and outbound.get("tag")
    }
    nodes: list[Node] = []
    for tag_value in selector.get("outbounds", []):
        tag = str(tag_value)
        outbound = by_tag.get(tag, {})
        nodes.append(
            {
                "tag": tag,
                "type": _str(outbound.get("type")),
                "server": _str(outbound.get("server")),
                "server_port": outbound.get("server_port"),
            }
        )
    return nodes, _str(selector.get("default")), "" if nodes else "no nodes in proxy selector"


def _switch_node(config_path: Path, tag: str) -> str:
    config = read_config(config_path)
    selector = _proxy_selector(config)
    if selector is None:
        raise ValueError("no proxy selector outbound found")
    if tag not in [str(value) for value in selector.get("outbounds", [])]:
        raise ValueError(f"node not in proxy selector: {tag}")

    selector["default"] = tag
    config.setdefault("route", {})["final"] = tag
    dns = config.get("dns", {})
    if isinstance(dns, dict):
        for server in dns.get("servers", []):
            if isinstance(server, dict) and server.get("detour") == "proxy":
                server["detour"] = tag

    config_path.write_text(
        json.dumps(config, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    if not status_daemon():
        return f"switched to {tag}; daemon stopped"

    try:
        reload_daemon()
    except PermissionError:
        return f"switched to {tag}; reload needs permission"
    except Exception as exc:
        return f"switched to {tag}; reload failed: {exc}"
    return f"switched to {tag}; daemon reloaded"


def _tcp_ping(host: str, port: int, timeout: float = 3.0) -> float | None:
    try:
        start = time.monotonic()
        with socket.create_connection((host, port), timeout=timeout):
            return (time.monotonic() - start) * 1000
    except (socket.timeout, ConnectionRefusedError, OSError):
        return None


def _daemon_status() -> str:
    try:
        return "running" if status_daemon() else "stopped"
    except Exception:
        return "unknown"


def run_node_selector(config_path: Path | None = None) -> bool:
    """Run the interactive selector. Return True when a node was switched."""
    path = (config_path or default_config_path()).expanduser()
    nodes: list[Node] = []
    visible: list[int] = []
    cursor = 0
    filter_text = ""
    needs_restart = False
    current_tag = ""
    message = ""
    latency: dict[str, str] = {}

    def highlighted_tag() -> str | None:
        return str(nodes[visible[cursor]]["tag"]) if visible else None

    def rebuild_visible(preferred: str | None = None) -> None:
        nonlocal visible, cursor
        selected = preferred or highlighted_tag()
        needle = filter_text.casefold()
        visible = [i for i, node in enumerate(nodes) if needle in str(node["tag"]).casefold()]
        if not visible:
            cursor = 0
            return
        if selected:
            for pos, index in enumerate(visible):
                if str(nodes[index]["tag"]) == selected:
                    cursor = pos
                    return
        cursor = min(cursor, len(visible) - 1)

    def load(preferred: str | None = None) -> None:
        nonlocal nodes, current_tag, message
        nodes, current_tag, message = _load_nodes(path)
        rebuild_visible(preferred)

    def selected_node() -> Node | None:
        return nodes[visible[cursor]] if visible else None

    def move(delta: int) -> None:
        nonlocal cursor
        if visible:
            cursor = (cursor + delta) % len(visible)
            app.invalidate()

    def body_rows() -> int:
        try:
            return max(1, app.output.get_size().rows - 3)
        except Exception:
            return 20

    def address(node: Node) -> str:
        server = _str(node.get("server"))
        port = _str(node.get("server_port"))
        return f"{server}:{port}" if server and port else server or port

    def render_header() -> FormattedText:
        current = current_tag or "none"
        return FormattedText(
            [("class:header", f" daemon: {_daemon_status()} | current: {current} | nodes: {len(nodes)}")]
        )

    def render_body() -> FormattedText:
        parts: Chunks = [
            ("class:table.header", f"  {'#':>3}  {'Tag':30} {'Type':8} {'Address:Port':30} {'Latency':8}\n")
        ]
        if message and not nodes:
            parts.append(("", f"  {message}\n"))
            return FormattedText(parts)
        if not nodes:
            parts.append(("", "  no nodes loaded\n"))
            return FormattedText(parts)
        if not visible:
            parts.append(("", "  no matching nodes\n"))
            return FormattedText(parts)

        data_rows = max(1, body_rows() - 1)
        start = max(0, cursor - data_rows + 1)
        for pos, index in enumerate(visible[start : start + data_rows], start=start):
            node = nodes[index]
            tag = str(node["tag"])
            prefix = ">" if pos == cursor else " "
            parts.append(
                (
                    "",
                    f"{prefix}{index + 1:>3}  {_tag_cell(tag, tag == current_tag)} "
                    f"{_fit(node.get('type'), 8)} {_fit(address(node), 30)} "
                    f"{_fit(latency.get(tag, ''), 8)}\n",
                )
            )
        return FormattedText(parts)

    def render_footer() -> FormattedText:
        current_filter = filter_text if filter_text else "<none>"
        notice = f"{message} | " if message and nodes else ""
        hints = "j/down k/up enter switch t test esc clear q quit"
        return FormattedText([("class:footer", f" {notice}filter: {current_filter} | {hints}")])

    async def ping_task(tag: str, server: str, port: int) -> None:
        result = await asyncio.to_thread(_tcp_ping, server, port, 3.0)
        latency[tag] = f"{result:.0f}ms" if result is not None else "timeout"
        app.invalidate()

    def switch_selected() -> None:
        nonlocal needs_restart, current_tag, message
        node = selected_node()
        if node is None:
            return
        tag = str(node["tag"])
        try:
            switch_message = _switch_node(path, tag)
        except Exception as exc:
            message = f"error: {exc}"
        else:
            needs_restart = True
            current_tag = tag
            load(preferred=tag)
            message = switch_message
        app.invalidate()

    def test_selected() -> None:
        nonlocal message
        node = selected_node()
        if node is None:
            return
        tag = str(node["tag"])
        server = _str(node.get("server"))
        try:
            port = int(node.get("server_port"))
        except (TypeError, ValueError):
            latency[tag] = "n/a"
            message = f"missing server port for {tag}"
            app.invalidate()
            return
        if not server:
            latency[tag] = "n/a"
            message = f"missing server for {tag}"
            app.invalidate()
            return
        latency[tag] = "..."
        app.invalidate()
        app.create_background_task(ping_task(tag, server, port))

    kb = KeyBindings()

    @kb.add("j")
    @kb.add("down")
    def _(event: Any) -> None:
        move(1)

    @kb.add("k")
    @kb.add("up")
    def _(event: Any) -> None:
        move(-1)

    @kb.add("enter")
    def _(event: Any) -> None:
        switch_selected()

    @kb.add("t")
    def _(event: Any) -> None:
        test_selected()

    @kb.add("q")
    def _(event: Any) -> None:
        event.app.exit()

    @kb.add("backspace")
    @kb.add("c-h")
    def _(event: Any) -> None:
        nonlocal filter_text
        if filter_text:
            filter_text = filter_text[:-1]
            rebuild_visible()
            app.invalidate()

    @kb.add("escape")
    def _(event: Any) -> None:
        nonlocal filter_text
        if filter_text:
            filter_text = ""
            rebuild_visible()
            app.invalidate()

    @kb.add(Keys.Any)
    def _(event: Any) -> None:
        nonlocal filter_text
        if event.data and event.data.isprintable():
            filter_text += event.data
            rebuild_visible()
            app.invalidate()

    root = HSplit(
        [
            Window(FormattedTextControl(render_header), height=1),
            Window(FormattedTextControl(render_body), wrap_lines=False),
            Window(FormattedTextControl(render_footer), height=1),
        ]
    )
    app: Application = Application(
        layout=Layout(root),
        key_bindings=kb,
        style=Style.from_dict({"header": "bold", "footer": "fg:#888888", "table.header": "bold"}),
        full_screen=True,
    )
    load()
    app.run()
    return needs_restart
