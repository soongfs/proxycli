"""Smoke tests for the TUI module."""

from __future__ import annotations

from pathlib import Path


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
        conn, _ = listener.accept()
        time.sleep(0.01)
        conn.close()

    t = threading.Thread(target=accept_and_close, daemon=True)
    t.start()

    try:
        result = ProxyTuiApp._tcp_ping("127.0.0.1", port, timeout=1.0)
        assert result is not None
        assert result > 0
    finally:
        listener.close()
