from __future__ import annotations

import base64
import stat
from pathlib import Path

import httpx
import pytest

from proxycli import subscription


def b64(value: str) -> str:
    return base64.urlsafe_b64encode(value.encode("utf-8")).decode("utf-8").rstrip("=")


def test_fetch_subscription_with_mock(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeResponse:
        text = "subscription-body"

        def raise_for_status(self) -> None:
            return None

    class FakeClient:
        def __init__(self, timeout: float, follow_redirects: bool) -> None:
            assert timeout == 15.0
            assert follow_redirects is True

        def __enter__(self) -> FakeClient:
            return self

        def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
            return None

        def get(self, url: str) -> FakeResponse:
            assert url == "https://example.com/sub"
            return FakeResponse()

    monkeypatch.setattr(httpx, "Client", FakeClient)

    assert subscription.fetch_subscription("https://example.com/sub") == "subscription-body"


def test_parse_subscription_decodes_base64_without_padding() -> None:
    raw = b64("ss://YWVzLTI1Ni1nY206cGFzcw@ss.example.com:8388#decoded")

    nodes = subscription.parse_subscription(raw)

    assert len(nodes) == 1
    assert nodes[0]["tag"] == "decoded"
    assert nodes[0]["server"] == "ss.example.com"


def test_parse_subscription_plain_text() -> None:
    raw = "ss://YWVzLTI1Ni1nY206cGFzcw@ss.example.com:8388#plain"

    nodes = subscription.parse_subscription(raw)

    assert nodes[0]["tag"] == "plain"


def test_update_from_url_writes_state_and_config(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state_path = tmp_path / "state.json"
    output_path = tmp_path / "config.json"
    raw = "ss://YWVzLTI1Ni1nY206cGFzcw@ss.example.com:8388#node"

    monkeypatch.setattr(subscription, "STATE_PATH", state_path)
    monkeypatch.setattr(subscription, "fetch_subscription", lambda url, **kw: raw)
    monkeypatch.setattr(subscription, "download_rule_sets", lambda **kw: {})

    nodes = subscription.update_from_url("https://example.com/sub", output_path)

    assert [node["tag"] for node in nodes] == ["node"]
    assert output_path.exists()
    state = subscription.get_state(state_path)
    assert state["subscription_url"] == "https://example.com/sub"
    assert isinstance(state["last_fetch_at"], int)


def test_update_from_url_rejects_empty_subscription(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(subscription, "fetch_subscription", lambda url, **kw: "# empty")
    monkeypatch.setattr(subscription, "download_rule_sets", lambda **kw: {})

    with pytest.raises(ValueError, match="did not contain any supported nodes"):
        subscription.update_from_url("https://example.com/sub", tmp_path / "config.json")


def test_update_from_url_rejects_missing_rule_sets(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state_path = tmp_path / "state.json"
    output_path = tmp_path / "config.json"
    raw = "ss://YWVzLTI1Ni1nY206cGFzcw@ss.example.com:8388#node"

    monkeypatch.setattr(subscription, "STATE_PATH", state_path)
    monkeypatch.setattr(subscription, "rule_set_dir", lambda: tmp_path / "rule-sets")
    monkeypatch.setattr(subscription, "fetch_subscription", lambda url, **kw: raw)
    monkeypatch.setattr(subscription, "download_rule_sets", lambda **kw: {"geoip-cn": False})

    with pytest.raises(RuntimeError, match="failed to download required rule-set files"):
        subscription.update_from_url("https://example.com/sub", output_path)

    assert not output_path.exists()
    assert not state_path.exists()


def test_update_from_url_accepts_failed_download_when_cached_rule_set_exists(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rule_set_dir = tmp_path / "rule-sets"
    rule_set_dir.mkdir()
    (rule_set_dir / "geoip-cn.srs").write_bytes(b"cached")
    raw = "ss://YWVzLTI1Ni1nY206cGFzcw@ss.example.com:8388#node"

    monkeypatch.setattr(subscription, "STATE_PATH", tmp_path / "state.json")
    monkeypatch.setattr(subscription, "rule_set_dir", lambda: rule_set_dir)
    monkeypatch.setattr(subscription, "fetch_subscription", lambda url, **kw: raw)
    monkeypatch.setattr(subscription, "download_rule_sets", lambda **kw: {"geoip-cn": False})

    nodes = subscription.update_from_url("https://example.com/sub", tmp_path / "config.json")

    assert [node["tag"] for node in nodes] == ["node"]


def test_state_file_is_owner_only_and_mask_url_redacts_query_secrets(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state_path = tmp_path / "state.json"
    output_path = tmp_path / "config.json"
    raw = "ss://YWVzLTI1Ni1nY206cGFzcw@ss.example.com:8388#node"

    monkeypatch.setattr(subscription, "STATE_PATH", state_path)
    monkeypatch.setattr(subscription, "fetch_subscription", lambda url, **kw: raw)
    monkeypatch.setattr(subscription, "download_rule_sets", lambda **kw: {})

    subscription.update_from_url("https://example.com/sub?token=secret-token&foo=abcdefghijklmnopqrstuvwxyz", output_path)

    assert stat.S_IMODE(state_path.stat().st_mode) == 0o600
    masked = subscription.mask_url("https://example.com/sub?token=secret-token&foo=abcdefghijklmnopqrstuvwxyz")
    assert "secret-token" not in masked
    assert "abcdefghijklmnopqrstuvwxyz" not in masked
    assert "token=%2A%2A%2A" in masked
