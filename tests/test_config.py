from __future__ import annotations

import json
from pathlib import Path

import pytest

from proxycli import config as config_module
from proxycli.config import (
    add_direct_domain,
    generate_config,
    load_direct_domains,
    load_template,
    read_config,
    remove_direct_domain,
)


def sample_nodes() -> list[dict[str, object]]:
    return [
        {
            "type": "vmess",
            "tag": "node-a",
            "server": "a.example.com",
            "server_port": 443,
            "uuid": "00000000-0000-0000-0000-000000000001",
            "security": "auto",
            "alter_id": 0,
        },
        {
            "type": "vmess",
            "tag": "node-b",
            "server": "b.example.com",
            "server_port": 443,
            "uuid": "00000000-0000-0000-0000-000000000002",
            "security": "auto",
            "alter_id": 0,
        },
    ]


def test_load_template() -> None:
    template = load_template()
    assert template.name == "config.json.j2"


def test_generate_config_and_read_round_trip(tmp_path: Path) -> None:
    output_path = tmp_path / "config.json"
    generate_config(sample_nodes(), output_path)
    data = read_config(output_path)

    assert data["log"]["level"] == "info"
    assert data["inbounds"][0]["type"] == "mixed"
    assert data["inbounds"][1]["type"] == "tun"
    assert data["inbounds"][1]["auto_route"] is True
    assert data["route"]["final"] == "proxy"
    assert data["route"]["auto_detect_interface"] is True


def test_generated_config_uses_rule_sets(tmp_path: Path) -> None:
    output_path = tmp_path / "config.json"
    generate_config(sample_nodes(), output_path)
    data = read_config(output_path)

    servers = {s["tag"]: s for s in data["dns"]["servers"]}
    assert servers["local_local"]["type"] == "udp"
    assert servers["remote_dns"]["detour"] == "proxy"

    # Rule sets are local files
    rule_sets = {rs["tag"]: rs for rs in data["route"]["rule_set"]}
    assert rule_sets["geoip-cn"]["type"] == "local"
    assert rule_sets["geoip-cn"]["format"] == "binary"
    assert "geosite-cn" in rule_sets

    # Route rules use rule_set
    rule_set_rules = [r for r in data["route"]["rules"] if "rule_set" in r]
    assert len(rule_set_rules) >= 2  # geoip-cn + geosite-cn

    # domain_suffix fallback still present
    domain_rules = [r for r in data["route"]["rules"] if "domain_suffix" in r]
    assert len(domain_rules) >= 1


def test_selector_contains_node_tags_and_direct(tmp_path: Path) -> None:
    output_path = tmp_path / "config.json"
    generate_config(sample_nodes(), output_path)
    data = read_config(output_path)

    selector = data["outbounds"][1]
    assert selector["type"] == "selector"
    assert selector["tag"] == "proxy"
    assert selector["outbounds"] == ["node-a", "node-b"]
    assert data["outbounds"][0] == {"type": "direct", "tag": "direct"}


def test_generate_config_with_default_node(tmp_path: Path) -> None:
    output_path = tmp_path / "config.json"
    nodes = [sample_nodes()[0]]
    generate_config(nodes, output_path)
    data = read_config(output_path)

    assert data["outbounds"][1]["outbounds"] == ["node-a"]
    assert data["outbounds"][2]["tag"] == "node-a"


def test_generated_config_routes_private_networks_direct(tmp_path: Path) -> None:
    output_path = tmp_path / "config.json"
    generate_config(sample_nodes(), output_path)
    data = read_config(output_path)

    direct_ip_cidrs = {
        cidr
        for rule in data["route"]["rules"]
        if rule.get("outbound") == "direct" and "ip_cidr" in rule
        for cidr in rule["ip_cidr"]
    }

    assert "10.0.0.0/8" in direct_ip_cidrs
    assert "172.16.0.0/12" in direct_ip_cidrs
    assert "192.168.0.0/16" in direct_ip_cidrs
    assert "100.64.0.0/10" in direct_ip_cidrs
    assert "127.0.0.0/8" in direct_ip_cidrs
    assert "169.254.0.0/16" in direct_ip_cidrs
    assert "fc00::/7" in direct_ip_cidrs
    assert "fe80::/10" in direct_ip_cidrs


def test_direct_domain_inputs_are_normalized_and_deduplicated(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    direct_path = tmp_path / "direct-domains.json"
    direct_path.write_text(json.dumps(["example.com"]), encoding="utf-8")
    monkeypatch.setattr(config_module, "direct_domains_path", lambda: direct_path)

    assert add_direct_domain(" HTTPS://API.EXAMPLE.COM/path ") is True
    assert add_direct_domain("api.example.com") is False
    assert load_direct_domains() == ["api.example.com", "example.com"]
    assert remove_direct_domain("https://api.example.com/foo") is True
    assert load_direct_domains() == ["example.com"]


def test_direct_domain_rejects_invalid_input() -> None:
    with pytest.raises(ValueError, match="invalid domain suffix"):
        add_direct_domain("example.com/path")
