"""Parse proxy subscription node URIs into sing-box outbound dictionaries."""

from __future__ import annotations

import base64
import json
import logging
from typing import Any
from urllib.parse import parse_qs, unquote, urlsplit

logger = logging.getLogger(__name__)


def _decode_base64(value: str) -> str:
    """Decode a standard or URL-safe base64 string with optional missing padding."""
    compact = "".join(value.strip().split())
    if not compact:
        raise ValueError("empty base64 payload")

    padded = compact + "=" * (-len(compact) % 4)
    try:
        return base64.urlsafe_b64decode(padded.encode("utf-8")).decode("utf-8")
    except Exception as exc:
        try:
            return base64.b64decode(padded.encode("utf-8")).decode("utf-8")
        except Exception as fallback_exc:
            raise ValueError(f"invalid base64 payload: {fallback_exc}") from exc


def _query_params(query: str) -> dict[str, str]:
    """Return URL query parameters using the last value for each key."""
    parsed = parse_qs(query, keep_blank_values=True)
    return {key: values[-1] if values else "" for key, values in parsed.items()}


def _tag(fragment: str, fallback: str) -> str:
    """Build a usable sing-box outbound tag from URI fragment or fallback text."""
    name = unquote(fragment).strip()
    if name:
        return name
    return fallback.strip() or "proxy-node"


def _require(value: str | None, field: str, scheme: str) -> str:
    """Return a non-empty value or raise a descriptive parser error."""
    if value is None or value == "":
        raise ValueError(f"{scheme} node missing required field: {field}")
    return value


def _port(value: int | str | None, scheme: str) -> int:
    """Validate and return a TCP/UDP port number."""
    if value is None or value == "":
        raise ValueError(f"{scheme} node missing required field: port")
    try:
        port = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{scheme} node has invalid port: {value}") from exc
    if port < 1 or port > 65535:
        raise ValueError(f"{scheme} node port out of range: {port}")
    return port


def _bool_param(value: str | None) -> bool:
    """Parse common URL boolean values."""
    return str(value or "").lower() in {"1", "true", "yes", "on"}


def _tls_from_params(params: dict[str, str], security: str | None = None) -> dict[str, Any] | None:
    """Build a sing-box TLS block from URL query parameters."""
    enabled = security in {"tls", "reality"} or any(
        key in params for key in ("sni", "insecure", "allowInsecure", "alpn")
    )
    if not enabled:
        return None

    tls: dict[str, Any] = {"enabled": True}
    server_name = params.get("sni") or params.get("peer") or params.get("host")
    if server_name:
        tls["server_name"] = unquote(server_name)

    insecure_value = params.get("insecure") or params.get("allowInsecure")
    if insecure_value is not None:
        tls["insecure"] = _bool_param(insecure_value)

    alpn = params.get("alpn")
    if alpn:
        tls["alpn"] = [unquote(item) for item in alpn.split(",") if item]

    if security == "reality":
        reality: dict[str, Any] = {"enabled": True}
        public_key = params.get("pbk") or params.get("public_key")
        short_id = params.get("sid") or params.get("short_id")
        if public_key:
            reality["public_key"] = unquote(public_key)
        if short_id:
            reality["short_id"] = unquote(short_id)
        tls["reality"] = reality

    return tls


def _transport_from_params(params: dict[str, str]) -> dict[str, Any] | None:
    """Build a sing-box transport block from URL query parameters."""
    transport_type = params.get("type") or params.get("network") or params.get("net")
    if not transport_type or transport_type == "tcp":
        return None

    transport: dict[str, Any] = {"type": transport_type}
    if transport_type == "ws":
        path = params.get("path")
        host = params.get("host")
        if path:
            transport["path"] = unquote(path)
        if host:
            transport["headers"] = {"Host": unquote(host)}
    elif transport_type == "grpc":
        service_name = params.get("serviceName") or params.get("service_name")
        if service_name:
            transport["service_name"] = unquote(service_name)
    elif transport_type == "http":
        host = params.get("host")
        path = params.get("path")
        if host:
            transport["host"] = [unquote(host)]
        if path:
            transport["path"] = unquote(path)
    elif transport_type == "quic":
        pass

    return transport


def parse_vmess(uri: str) -> dict[str, Any]:
    """Parse a vmess://base64(json) URI into a sing-box outbound dictionary."""
    payload = uri.removeprefix("vmess://")
    try:
        data = json.loads(_decode_base64(payload))
    except json.JSONDecodeError as exc:
        raise ValueError(f"vmess node has invalid JSON payload: {exc}") from exc

    if not isinstance(data, dict):
        raise ValueError("vmess node payload must be a JSON object")

    server = _require(str(data.get("add") or data.get("server") or ""), "server", "vmess")
    port = _port(data.get("port"), "vmess")
    uuid = _require(str(data.get("id") or data.get("uuid") or ""), "uuid", "vmess")
    security = str(data.get("scy") or data.get("security") or "auto")

    outbound: dict[str, Any] = {
        "type": "vmess",
        "tag": _tag(str(data.get("ps") or data.get("tag") or ""), f"{server}:{port}"),
        "server": server,
        "server_port": port,
        "uuid": uuid,
        "security": security,
        "alter_id": int(data.get("aid") or data.get("alterId") or 0),
    }

    params = {
        "type": str(data.get("net") or data.get("type") or ""),
        "path": str(data.get("path") or ""),
        "host": str(data.get("host") or ""),
        "serviceName": str(data.get("serviceName") or ""),
    }
    transport = _transport_from_params({key: value for key, value in params.items() if value})
    if transport:
        outbound["transport"] = transport

    tls = _tls_from_params(
        {
            "sni": str(data.get("sni") or data.get("host") or ""),
            "alpn": str(data.get("alpn") or ""),
        },
        str(data.get("tls") or ""),
    )
    if tls:
        outbound["tls"] = tls

    return outbound


def parse_shadowsocks(uri: str) -> dict[str, Any]:
    """Parse legacy and SIP002 ss:// URIs into a sing-box shadowsocks outbound."""
    split = urlsplit(uri)
    if split.scheme != "ss":
        raise ValueError("shadowsocks URI must start with ss://")

    tag = _tag(split.fragment, split.hostname or "shadowsocks")

    if split.hostname and split.username:
        method_password_encoded = split.username
        method_password = _decode_base64(unquote(method_password_encoded))
        if ":" not in method_password:
            raise ValueError("shadowsocks SIP002 userinfo must decode to method:password")
        method, password = method_password.split(":", 1)
        server = _require(split.hostname, "server", "shadowsocks")
        port = _port(split.port, "shadowsocks")
    else:
        decoded = _decode_base64(uri.removeprefix("ss://").split("#", 1)[0])
        if "@" not in decoded:
            raise ValueError("legacy shadowsocks payload must contain method:password@server:port")
        userinfo, serverinfo = decoded.rsplit("@", 1)
        if ":" not in userinfo:
            raise ValueError("legacy shadowsocks userinfo must contain method:password")
        method, password = userinfo.split(":", 1)
        server, port_text = _split_host_port(serverinfo, "shadowsocks")
        port = _port(port_text, "shadowsocks")

    method = _require(unquote(method), "method", "shadowsocks")
    password = _require(unquote(password), "password", "shadowsocks")

    return {
        "type": "shadowsocks",
        "tag": tag,
        "server": server,
        "server_port": port,
        "method": method,
        "password": password,
    }


def _split_host_port(value: str, scheme: str) -> tuple[str, str]:
    """Split a host:port string while keeping IPv6 literals usable."""
    if value.startswith("["):
        host, sep, rest = value[1:].partition("]")
        if not sep or not rest.startswith(":"):
            raise ValueError(f"{scheme} node has invalid host:port")
        return host, rest[1:]

    host, sep, port = value.rpartition(":")
    if not sep:
        raise ValueError(f"{scheme} node missing port")
    return host, port


def parse_trojan(uri: str) -> dict[str, Any]:
    """Parse a trojan:// URI into a sing-box outbound dictionary."""
    split = urlsplit(uri)
    params = _query_params(split.query)
    server = _require(split.hostname, "server", "trojan")
    port = _port(split.port, "trojan")
    security = params.get("security") or "tls"

    outbound: dict[str, Any] = {
        "type": "trojan",
        "tag": _tag(split.fragment, f"{server}:{port}"),
        "server": server,
        "server_port": port,
        "password": _require(unquote(split.username or ""), "password", "trojan"),
    }

    tls = _tls_from_params(params, security)
    if tls:
        outbound["tls"] = tls

    transport = _transport_from_params(params)
    if transport:
        outbound["transport"] = transport

    return outbound


def parse_vless(uri: str) -> dict[str, Any]:
    """Parse a vless:// URI into a sing-box outbound dictionary."""
    split = urlsplit(uri)
    params = _query_params(split.query)
    server = _require(split.hostname, "server", "vless")
    port = _port(split.port, "vless")
    security = params.get("security")

    outbound: dict[str, Any] = {
        "type": "vless",
        "tag": _tag(split.fragment, f"{server}:{port}"),
        "server": server,
        "server_port": port,
        "uuid": _require(unquote(split.username or ""), "uuid", "vless"),
        "flow": params.get("flow", ""),
    }

    tls = _tls_from_params(params, security)
    if tls:
        outbound["tls"] = tls

    transport = _transport_from_params(params)
    if transport:
        outbound["transport"] = transport

    return outbound


def parse_hysteria2(uri: str) -> dict[str, Any]:
    """Parse a hysteria2:// or hy2:// URI into a sing-box outbound dictionary."""
    split = urlsplit(uri)
    params = _query_params(split.query)
    server = _require(split.hostname, "server", "hysteria2")
    port = _port(split.port, "hysteria2")

    outbound: dict[str, Any] = {
        "type": "hysteria2",
        "tag": _tag(split.fragment, f"{server}:{port}"),
        "server": server,
        "server_port": port,
        "password": _require(unquote(split.username or ""), "password", "hysteria2"),
    }

    tls = _tls_from_params(params, "tls")
    if tls:
        outbound["tls"] = tls

    return outbound


def parse_tuic(uri: str) -> dict[str, Any]:
    """Parse a tuic:// URI into a sing-box outbound dictionary."""
    split = urlsplit(uri)
    params = _query_params(split.query)
    server = _require(split.hostname, "server", "tuic")
    port = _port(split.port, "tuic")
    username = unquote(split.username or "")
    password = unquote(split.password or "")

    outbound: dict[str, Any] = {
        "type": "tuic",
        "tag": _tag(split.fragment, f"{server}:{port}"),
        "server": server,
        "server_port": port,
        "uuid": _require(username, "uuid", "tuic"),
        "password": _require(password, "password", "tuic"),
    }

    congestion_control = params.get("congestion_control")
    if congestion_control:
        outbound["congestion_control"] = congestion_control

    tls = _tls_from_params(params, "tls")
    if tls:
        outbound["tls"] = tls

    return outbound


def parse_node(uri: str) -> dict[str, Any]:
    """Dispatch a proxy URI to the matching parser and return a sing-box outbound."""
    stripped = uri.strip()
    if not stripped:
        raise ValueError("empty node URI")

    scheme = stripped.split(":", 1)[0].lower()
    if scheme == "vmess":
        return parse_vmess(stripped)
    if scheme == "ss":
        return parse_shadowsocks(stripped)
    if scheme == "trojan":
        return parse_trojan(stripped)
    if scheme == "vless":
        return parse_vless(stripped)
    if scheme in {"hysteria2", "hy2"}:
        return parse_hysteria2(stripped)
    if scheme == "tuic":
        return parse_tuic(stripped)

    raise ValueError(f"unsupported proxy scheme: {scheme or '<missing>'}")


def parse_subscription_content(text: str) -> list[dict[str, Any]]:
    """Parse newline-separated subscription content into sing-box outbound dictionaries.

    Blank lines and lines beginning with ``#`` are ignored. Invalid entries are
    logged and skipped so one bad subscription item does not discard the rest.
    """
    nodes: list[dict[str, Any]] = []
    for line_number, line in enumerate(text.splitlines(), start=1):
        uri = line.strip()
        if not uri or uri.startswith("#"):
            continue
        try:
            nodes.append(parse_node(uri))
        except ValueError as exc:
            logger.warning("Skipping invalid subscription node on line %s: %s", line_number, exc)
    return nodes
