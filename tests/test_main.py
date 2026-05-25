from __future__ import annotations

import json
from pathlib import Path

import pytest

from proxycli import main


def test_switch_node_via_config_updates_config_when_daemon_stopped(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps(
            {
                "outbounds": [
                    {
                        "type": "selector",
                        "tag": "proxy",
                        "outbounds": ["node-a", "node-b"],
                    }
                ],
                "route": {"final": "proxy"},
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(main.daemon_module, "status_daemon", lambda: False)
    monkeypatch.setattr(
        main.daemon_module,
        "restart_daemon",
        lambda path: pytest.fail("restart should not be used when daemon is stopped"),
    )
    monkeypatch.setattr(
        main.daemon_module,
        "reload_daemon",
        lambda: pytest.fail("reload should not be used when daemon is stopped"),
    )

    switch_method = main._switch_node_via_config(config_path, "node-b")

    data = json.loads(config_path.read_text(encoding="utf-8"))
    assert data["outbounds"][0]["default"] == "node-b"
    assert data["route"]["final"] == "node-b"
    assert switch_method == (
        "config update; daemon is stopped, run sudo uv run proxycli daemon start"
    )
