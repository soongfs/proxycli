from __future__ import annotations

from pathlib import Path

from proxycli.config import generate_config, load_template, read_config


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
