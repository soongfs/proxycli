"""Smoke tests for the TUI module."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest


def test_tui_app_can_be_instantiated() -> None:
    from proxycli.tui import ProxyTuiApp
    app = ProxyTuiApp()
    assert app is not None
    assert app._config_path is not None


def test_tui_app_accepts_custom_config_path() -> None:
    from proxycli.tui import ProxyTuiApp
    custom = Path("/tmp/test-config.json")
    app = ProxyTuiApp(config_path=custom)
    assert app._config_path == custom


def test_tcp_ping_timeout() -> None:
    from proxycli.tui import ProxyTuiApp
    # Connect to a non-listening port on localhost — should time out
    result = ProxyTuiApp._tcp_ping("127.0.0.1", 1, timeout=0.5)
    assert result is None


def test_tcp_ping_localhost() -> None:
    import socket
    import threading
    import time

    from proxycli.tui import ProxyTuiApp

    # Start a listener on a random port
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.bind(("127.0.0.1", 0))
    port = listener.getsockname()[1]
    listener.listen(1)

    def accept_and_close():
        try:
            conn, _ = listener.accept()
        except OSError:
            return
        with conn:
            time.sleep(0.01)

    t = threading.Thread(target=accept_and_close, daemon=True)
    t.start()

    try:
        result = ProxyTuiApp._tcp_ping("127.0.0.1", port, timeout=1.0)
        assert result is not None
        assert result > 0
    finally:
        listener.close()
        t.join(timeout=1.0)


def test_select_then_quit_prints_restart_hint_after_shutdown(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from proxycli import tui as tui_module

    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps(
            {
                "outbounds": [
                    {
                        "type": "selector",
                        "tag": "proxy",
                        "outbounds": ["node-a", "node-b"],
                        "default": "node-a",
                    },
                    {
                        "tag": "node-a",
                        "server": "node-a.example.com",
                        "server_port": 443,
                    },
                    {
                        "tag": "node-b",
                        "server": "node-b.example.com",
                        "server_port": 443,
                    },
                ],
                "route": {"final": "proxy"},
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(tui_module, "status_daemon", lambda: False)

    app = tui_module.ProxyTuiApp(config_path=config_path)

    async def drive_app() -> None:
        async with app.run_test() as pilot:
            await pilot.press("enter")
            await pilot.pause()
            await pilot.press("q")
            await pilot.pause()

    asyncio.run(drive_app())

    assert app.needs_restart is True
