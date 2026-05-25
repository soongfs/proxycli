from __future__ import annotations

import base64
import json

import pytest

from proxycli.parser import parse_node, parse_subscription_content


def b64(value: str) -> str:
    return base64.urlsafe_b64encode(value.encode("utf-8")).decode("utf-8").rstrip("=")


def test_parse_vmess() -> None:
    payload = {
        "v": "2",
        "ps": "vmess-node",
        "add": "vmess.example.com",
        "port": "443",
        "id": "00000000-0000-0000-0000-000000000001",
        "aid": "0",
        "scy": "auto",
        "net": "ws",
        "type": "none",
        "host": "cdn.example.com",
        "path": "/ws",
        "tls": "tls",
        "sni": "vmess.example.com",
    }

    node = parse_node(f"vmess://{b64(json.dumps(payload))}")

    assert node["type"] == "vmess"
    assert node["tag"] == "vmess-node"
    assert node["server"] == "vmess.example.com"
    assert node["server_port"] == 443
    assert node["uuid"] == payload["id"]
    assert node["security"] == "auto"
    assert node["alter_id"] == 0
    assert node["transport"]["type"] == "ws"
    assert node["transport"]["headers"]["Host"] == "cdn.example.com"
    assert node["tls"]["server_name"] == "vmess.example.com"


def test_parse_legacy_shadowsocks() -> None:
    uri = f"ss://{b64('aes-256-gcm:secret@ss.example.com:8388')}#legacy"

    node = parse_node(uri)

    assert node == {
        "type": "shadowsocks",
        "tag": "legacy",
        "server": "ss.example.com",
        "server_port": 8388,
        "method": "aes-256-gcm",
        "password": "secret",
    }


def test_parse_sip002_shadowsocks() -> None:
    uri = f"ss://{b64('chacha20-ietf-poly1305:pass')}@sip.example.com:443#sip"

    node = parse_node(uri)

    assert node["type"] == "shadowsocks"
    assert node["tag"] == "sip"
    assert node["server"] == "sip.example.com"
    assert node["server_port"] == 443
    assert node["method"] == "chacha20-ietf-poly1305"
    assert node["password"] == "pass"


def test_parse_trojan() -> None:
    uri = "trojan://secret@trojan.example.com:443?security=tls&sni=edge.example.com#trojan"

    node = parse_node(uri)

    assert node["type"] == "trojan"
    assert node["tag"] == "trojan"
    assert node["password"] == "secret"
    assert node["tls"]["enabled"] is True
    assert node["tls"]["server_name"] == "edge.example.com"


def test_parse_vless_ws_tls() -> None:
    uri = (
        "vless://00000000-0000-0000-0000-000000000002@vless.example.com:443"
        "?encryption=none&security=tls&sni=vless.example.com&type=ws&path=%2Fws#vless"
    )

    node = parse_node(uri)

    assert node["type"] == "vless"
    assert node["tag"] == "vless"
    assert node["uuid"] == "00000000-0000-0000-0000-000000000002"
    assert node["flow"] == ""
    assert node["tls"]["server_name"] == "vless.example.com"
    assert node["transport"]["type"] == "ws"
    assert node["transport"]["path"] == "/ws"


def test_parse_hysteria2_and_hy2() -> None:
    for scheme in ("hysteria2", "hy2"):
        node = parse_node(f"{scheme}://secret@hy.example.com:8443?sni=hy.example.com&insecure=0#hy")

        assert node["type"] == "hysteria2"
        assert node["tag"] == "hy"
        assert node["password"] == "secret"
        assert node["tls"]["server_name"] == "hy.example.com"
        assert node["tls"]["insecure"] is False


def test_parse_tuic() -> None:
    uri = (
        "tuic://00000000-0000-0000-0000-000000000003:secret@tuic.example.com:443"
        "?sni=tuic.example.com&congestion_control=bbr#tuic"
    )

    node = parse_node(uri)

    assert node["type"] == "tuic"
    assert node["tag"] == "tuic"
    assert node["uuid"] == "00000000-0000-0000-0000-000000000003"
    assert node["password"] == "secret"
    assert node["congestion_control"] == "bbr"
    assert node["tls"]["server_name"] == "tuic.example.com"


def test_parse_subscription_content_skips_comments_and_invalid(caplog: pytest.LogCaptureFixture) -> None:
    content = "\n# comment\ninvalid://node\n" f"ss://{b64('aes-128-gcm:p@host.example:8388')}#ok\n"

    nodes = parse_subscription_content(content)

    assert [node["tag"] for node in nodes] == ["ok"]
    assert "Skipping invalid subscription node" in caplog.text


def test_parse_node_rejects_unsupported_scheme() -> None:
    with pytest.raises(ValueError, match="unsupported proxy scheme"):
        parse_node("http://example.com")


def test_parse_node_rejects_bad_port() -> None:
    with pytest.raises(ValueError, match="invalid port|Port could not be cast"):
        parse_node("trojan://pass@example.com:notaport#bad")
