"""Generate and read sing-box configuration files."""

from __future__ import annotations

import json
import os
import platform
import sys
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, Template, select_autoescape


def app_dir() -> Path:
    """Return the proxycli config directory, respecting SUDO_USER."""
    sudo_user = os.environ.get("SUDO_USER")
    if sudo_user:
        return Path(f"/home/{sudo_user}") / ".config" / "proxycli"
    return Path.home() / ".config" / "proxycli"


def default_config_path() -> Path:
    return app_dir() / "config.json"


def direct_domains_path() -> Path:
    return app_dir() / "direct-domains.json"


def rule_set_dir() -> Path:
    return app_dir() / "rule-sets"


TEMPLATE_NAME = "config.json.j2"


def _template_dir() -> Path:
    """Return the templates directory, supporting PyInstaller bundles."""
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS) / "proxycli" / "templates"  # type: ignore[attr-defined]
    return Path(__file__).parent / "templates"

_DEFAULT_DIRECT_DOMAINS: list[str] = [
    "deepseek.com",
    "dashscope.aliyuncs.com",
    "bigmodel.cn",
    "volces.com",
    "moonshot.cn",
    "aliyuncs.com",
    ".cn",
    "alidns.com",
    "doh.pub",
    "dot.pub",
]


def load_template() -> Template:
    """Load the default sing-box configuration Jinja2 template."""
    environment = Environment(
        loader=FileSystemLoader(_template_dir()),
        autoescape=select_autoescape(enabled_extensions=()),
        trim_blocks=True,
        lstrip_blocks=True,
    )
    return environment.get_template(TEMPLATE_NAME)


def generate_config(
    nodes: list[dict[str, Any]],
    output_path: Path | None = None,
) -> None:
    """Render a sing-box config for the provided nodes and write it to disk."""
    if output_path is None:
        output_path = default_config_path()
    output_path = output_path.expanduser()
    output_path.parent.mkdir(parents=True, exist_ok=True)

    node_tags = [str(node["tag"]) for node in nodes if node.get("tag")]
    direct_domains = load_direct_domains()
    rd = rule_set_dir()
    rule_set_paths = {
        "geoip-cn": str(rd / "geoip-cn.srs"),
        "geosite-cn": str(rd / "geosite-cn.srs"),
    }

    is_macos = platform.system() == "Darwin"
    tun = {
        "interface_name": "utun8" if is_macos else "tun0",
        "stack": "system" if is_macos else "mixed",
    }

    rendered = load_template().render(
        nodes=nodes,
        node_tags=node_tags,
        direct_domains=direct_domains,
        rule_set_paths=rule_set_paths,
        tun=tun,
    )

    parsed = json.loads(rendered)
    output_path.write_text(json.dumps(parsed, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def read_config(path: Path | None = None) -> dict[str, Any]:
    """Read a JSON sing-box config file into a dictionary."""
    if path is None:
        path = default_config_path()
    expanded = path.expanduser()
    with expanded.open("r", encoding="utf-8") as file:
        data = json.load(file)
    if not isinstance(data, dict):
        raise ValueError(f"config file must contain a JSON object: {expanded}")
    return data


def load_direct_domains() -> list[str]:
    """Return the current direct-domain list, creating defaults if missing."""
    ddp = direct_domains_path()
    if ddp.exists():
        data = json.loads(ddp.read_text(encoding="utf-8"))
        if isinstance(data, list):
            return [str(d) for d in data]
    save_direct_domains(_DEFAULT_DIRECT_DOMAINS)
    return list(_DEFAULT_DIRECT_DOMAINS)


def save_direct_domains(domains: list[str]) -> None:
    """Persist the direct-domain list to disk."""
    ddp = direct_domains_path()
    ddp.parent.mkdir(parents=True, exist_ok=True)
    ddp.write_text(
        json.dumps(domains, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def add_direct_domain(domain: str) -> bool:
    """Add a domain suffix to the direct list. Returns True if new."""
    domains = load_direct_domains()
    if domain in domains:
        return False
    domains.append(domain)
    save_direct_domains(domains)
    return True


def remove_direct_domain(domain: str) -> bool:
    """Remove a domain suffix from the direct list. Returns True if found."""
    domains = load_direct_domains()
    if domain not in domains:
        return False
    domains.remove(domain)
    save_direct_domains(domains)
    return True
