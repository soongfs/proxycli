"""Fetch, parse, and apply proxy subscription data."""

from __future__ import annotations

import base64
import json
import logging
import time
from pathlib import Path
from typing import Any

import httpx

from proxycli.config import app_dir, default_config_path, rule_set_dir, generate_config
from proxycli.parser import parse_subscription_content

logger = logging.getLogger(__name__)

STATE_PATH = app_dir() / "state.json"

_RULE_SET_FILES = {
    "geoip-cn": "https://cdn.jsdelivr.net/gh/SagerNet/sing-geoip@rule-set/geoip-cn.srs",
    "geosite-cn": "https://cdn.jsdelivr.net/gh/SagerNet/sing-geosite@rule-set/geosite-cn.srs",
}


def _decode_base64_subscription(raw_text: str) -> str:
    """Decode subscription text if it is base64 encoded, otherwise return it unchanged."""
    compact = "".join(raw_text.strip().split())
    if not compact:
        return ""

    if "://" in raw_text:
        return raw_text

    padded = compact + "=" * (-len(compact) % 4)
    try:
        decoded = base64.urlsafe_b64decode(padded.encode("utf-8")).decode("utf-8")
    except Exception:
        return raw_text

    return decoded if "://" in decoded else raw_text


def _read_state(path: Path | None = None) -> dict[str, Any]:
    """Read CLI state from disk, returning an empty state for missing files."""
    expanded = (path or STATE_PATH).expanduser()
    if not expanded.exists():
        return {}
    with expanded.open("r", encoding="utf-8") as file:
        data = json.load(file)
    return data if isinstance(data, dict) else {}


def _write_state(state: dict[str, Any], path: Path | None = None) -> None:
    """Write CLI state to disk."""
    expanded = (path or STATE_PATH).expanduser()
    expanded.parent.mkdir(parents=True, exist_ok=True)
    expanded.write_text(json.dumps(state, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def fetch_subscription(url: str, proxy: str | None = None) -> str:
    """Fetch subscription content over HTTP with a small retry budget.

    When *proxy* is set, routes the request through an HTTP proxy
    (e.g. ``http://127.0.0.1:7890``).
    """
    client_kwargs: dict[str, Any] = {"timeout": 15.0, "follow_redirects": True}
    if proxy:
        client_kwargs["proxy"] = proxy

    last_error: Exception | None = None
    for attempt in range(1, 4):
        try:
            with httpx.Client(**client_kwargs) as client:
                response = client.get(url)
                response.raise_for_status()
                return response.text
        except httpx.HTTPError as exc:
            last_error = exc
            logger.warning("Subscription fetch attempt %s failed: %s", attempt, exc)
            if attempt < 3:
                time.sleep(0.5 * attempt)

    raise RuntimeError(f"failed to fetch subscription after 3 attempts: {last_error}")


def parse_subscription(raw_text: str) -> list[dict[str, Any]]:
    """Decode and parse subscription text into sing-box outbounds."""
    decoded = _decode_base64_subscription(raw_text)
    return parse_subscription_content(decoded)


def update_config(
    nodes: list[dict[str, Any]],
    template_path: Path | None = None,
    output_path: Path | None = None,
) -> None:
    """Generate a sing-box config from nodes and write update metadata.

    ``template_path`` is accepted for API compatibility with custom-template
    flows. The current implementation uses the packaged default template.
    """
    del template_path
    if output_path is None:
        output_path = default_config_path()
    generate_config(nodes, output_path)
    state = _read_state()
    state["last_fetch_at"] = int(time.time())
    _write_state(state)


def update_from_url(
    url: str,
    output_path: Path | None = None,
    proxy: str | None = None,
) -> list[dict[str, Any]]:
    """Fetch a subscription URL, parse nodes, write config, and persist URL state.

    When *proxy* is set, routes HTTP requests through an HTTP proxy.
    """
    if output_path is None:
        output_path = default_config_path()
    raw_text = fetch_subscription(url, proxy=proxy)
    nodes = parse_subscription(raw_text)
    if not nodes:
        raise ValueError("subscription did not contain any supported nodes")

    download_rule_sets(proxy=proxy)
    generate_config(nodes, output_path)
    state = _read_state()
    state.update({"subscription_url": url, "last_fetch_at": int(time.time())})
    _write_state(state)
    return nodes


def download_rule_sets(proxy: str | None = None) -> dict[str, bool]:
    """Download geoip/geosite rule-set files from jsDelivr CDN.

    Returns a dict mapping tag to download success.
    Skips files that already exist unless they are older than 24 hours.
    """
    rd = rule_set_dir()
    rd.mkdir(parents=True, exist_ok=True)
    fresh_threshold = time.time() - 86400  # 24 hours

    client_kwargs: dict[str, Any] = {"timeout": 30.0, "follow_redirects": True}
    if proxy:
        client_kwargs["proxy"] = proxy

    results: dict[str, bool] = {}
    with httpx.Client(**client_kwargs) as client:
        for tag, url in _RULE_SET_FILES.items():
            dest = rd / f"{tag}.srs"
            if dest.exists() and dest.stat().st_mtime > fresh_threshold:
                logger.info("Rule-set %s is fresh, skipping download.", tag)
                results[tag] = True
                continue

            try:
                response = client.get(url)
                response.raise_for_status()
                dest.write_bytes(response.content)
                logger.info("Downloaded rule-set %s (%d bytes).", tag, len(response.content))
                results[tag] = True
            except httpx.HTTPError as exc:
                logger.warning("Failed to download rule-set %s: %s", tag, exc)
                results[tag] = False

    return results


def get_state(path: Path | None = None) -> dict[str, Any]:
    """Return persisted proxycli state."""
    return _read_state(path)
