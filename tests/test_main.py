from __future__ import annotations

import json
from pathlib import Path

import pytest
import click.testing

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


def _config_for_nodes() -> dict[str, object]:
    return {
        "outbounds": [
            {
                "type": "selector",
                "tag": "proxy",
                "outbounds": ["node-a", "node-b", "node-c"],
                "default": "node-a",
            },
            {"type": "vmess", "tag": "node-a", "server": "a.example.com", "server_port": 443},
            {"type": "vmess", "tag": "node-b", "server": "b.example.com", "server_port": 443},
            {"type": "vmess", "tag": "node-c", "server": "c.example.com", "server_port": 443},
        ],
        "route": {"final": "node-b"},
    }


def test_effective_node_prefers_route_final_when_it_is_a_node() -> None:
    assert main._get_effective_node(_config_for_nodes()) == "node-b"


def test_effective_node_falls_back_to_selector_default() -> None:
    data = _config_for_nodes()
    data["route"] = {"final": "proxy"}

    assert main._get_effective_node(data) == "node-a"


def test_node_test_top_returns_fastest_nodes_with_original_indices(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps(_config_for_nodes()), encoding="utf-8")
    latencies = {"a.example.com": 300.0, "b.example.com": 20.0, "c.example.com": None}

    monkeypatch.setattr(
        main,
        "_tcp_ping",
        lambda host, port, timeout: latencies[host],
    )

    runner = click.testing.CliRunner()
    result = runner.invoke(
        main.cli,
        ["--config", str(config_path), "node", "test", "--top", "2"],
    )

    assert result.exit_code == 0
    assert "node-b" in result.output
    assert "node-a" in result.output
    assert "node-c" not in result.output
    assert "2" in result.output
    assert "1" in result.output
