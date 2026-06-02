"""Command-line interface for proxycli."""

from __future__ import annotations

import json
import logging
import socket
import subprocess
import time
from pathlib import Path
from typing import Any

import click
from rich.console import Console
from rich.table import Table

from proxycli import __version__
from proxycli import config as config_module
from proxycli import daemon as daemon_module
from proxycli import subscription as subscription_module

console = Console()


class ProxyContext:
    """Shared click context for global options."""

    def __init__(self, config_path: Path | None, verbose: bool) -> None:
        """Initialize the CLI context."""
        self.config_path = (
            config_path.expanduser() if config_path
            else config_module.default_config_path()
        )
        self.verbose = verbose


def _configure_logging(verbose: bool) -> None:
    """Configure Python logging for CLI execution."""
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(levelname)s: %(message)s",
    )


def _ctx(ctx: click.Context) -> ProxyContext:
    """Return the typed click object."""
    return ctx.ensure_object(ProxyContext)


@click.group()
@click.option(
    "--config",
    "-c",
    "config_path",
    type=click.Path(path_type=Path, dir_okay=False),
    default=None,
    show_default=True,
    help="Path to sing-box config JSON.",
)
@click.option("--verbose", "-v", is_flag=True, help="Enable verbose logging.")
@click.version_option(__version__)
@click.pass_context
def cli(ctx: click.Context, config_path: Path, verbose: bool) -> None:
    """Manage sing-box subscriptions, nodes, config, and daemon lifecycle."""
    _configure_logging(verbose)
    ctx.obj = ProxyContext(config_path=config_path, verbose=verbose)


@cli.command()
@click.option(
    "--config",
    "-c",
    "config_path",
    type=click.Path(path_type=Path, dir_okay=False),
    default=None,
    help="Path to sing-box config JSON.",
)
def tui(config_path: Path | None) -> None:
    """Launch the interactive terminal UI."""
    from proxycli.tui import run_node_selector

    if run_node_selector(config_path=config_path):
        print(
            "\n⚠  Config updated. Apply changes:\n"
            "   sudo ~/.local/bin/proxycli daemon restart\n"
        )


@cli.group()
def sub() -> None:
    """Manage proxy subscriptions."""


@sub.command("update")
@click.argument("url", required=False)
@click.option("--proxy", "-p", default=None, help="HTTP proxy for subscription fetch (e.g. http://127.0.0.1:7890).")
@click.pass_context
def sub_update(ctx: click.Context, url: str | None, proxy: str | None) -> None:
    """Fetch a subscription and generate the sing-box config."""
    proxy_ctx = _ctx(ctx)
    if url is None:
        state = subscription_module.get_state()
        url = state.get("subscription_url")
    if not url:
        raise click.ClickException("subscription URL required on first update")

    try:
        nodes = subscription_module.update_from_url(url, proxy_ctx.config_path, proxy=proxy)
    except Exception as exc:
        raise click.ClickException(str(exc)) from exc

    console.print(f"Imported {len(nodes)} nodes into {proxy_ctx.config_path}")


@sub.command("show")
def sub_show() -> None:
    """Show saved subscription state."""
    state = subscription_module.get_state()
    if not state:
        console.print("No subscription state found.")
        return

    table = Table("Key", "Value")
    for key, value in state.items():
        table.add_row(str(key), str(value))
    console.print(table)


@cli.group()
def node() -> None:
    """Inspect and switch sing-box selector nodes."""


def _node_tags(config_data: dict[str, Any]) -> list[str]:
    """Extract selector node tags from a sing-box config dictionary."""
    for outbound in config_data.get("outbounds", []):
        if outbound.get("type") == "selector" and outbound.get("tag") == "proxy":
            return [str(tag) for tag in outbound.get("outbounds", [])]
    return []


def _get_selector_default(config_data: dict[str, Any]) -> str | None:
    """Return the current default tag of the proxy selector outbound."""
    for outbound in config_data.get("outbounds", []):
        if outbound.get("type") == "selector" and outbound.get("tag") == "proxy":
            return outbound.get("default")
    return None


def _switch_node_via_config(config_path: Path, tag: str) -> str:
    """Switch proxy node by rewriting config and sending SIGHUP.

    Edits the route.final to point directly at the target node
    (bypassing selector), then reloads or restarts the daemon.
    """
    if not config_path.exists():
        raise click.ClickException(f"config file not found: {config_path}")

    data = json.loads(config_path.read_text(encoding="utf-8"))
    found = False
    for outbound in data.get("outbounds", []):
        if outbound.get("type") == "selector" and outbound.get("tag") == "proxy":
            if tag not in outbound.get("outbounds", []):
                available = ", ".join(outbound.get("outbounds", []))
                raise click.ClickException(
                    f"node '{tag}' not in selector outbounds. "
                    f"Available: {available}"
                )
            outbound["default"] = tag
            found = True
            break

    if not found:
        raise click.ClickException("no 'proxy' selector outbound found in config")

    # Bypass selector in routing: point route.final directly to the node tag.
    # This ensures SIGHUP takes effect even if sing-box preserves selector state.
    data.setdefault("route", {})["final"] = tag

    # Bypass selector in DNS detours too: replace "proxy" detour with node tag.
    # DNS servers that use detour:"proxy" also go through the selector, which
    # may still point to a dead node after SIGHUP.
    for server in data.get("dns", {}).get("servers", []):
        if server.get("detour") == "proxy":
            server["detour"] = tag

    config_path.write_text(
        json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )

    if not daemon_module.status_daemon():
        return "config update; daemon is stopped, run sudo uv run proxycli daemon start"

    daemon_module.reload_daemon(use_sudo=True)
    return "config reload"


def _tcp_ping(host: str, port: int, timeout: float) -> float | None:
    """Measure TCP connection latency in milliseconds. Returns None on failure."""
    try:
        start = time.monotonic()
        with socket.create_connection((host, port), timeout=timeout):
            elapsed = (time.monotonic() - start) * 1000
        return elapsed
    except (socket.timeout, ConnectionRefusedError, OSError):
        return None


@node.command("list")
@click.pass_context
def node_list(ctx: click.Context) -> None:
    """List node tags from the generated selector outbound."""
    proxy_ctx = _ctx(ctx)
    try:
        config_data = config_module.read_config(proxy_ctx.config_path)
    except Exception as exc:
        raise click.ClickException(str(exc)) from exc

    tags = _node_tags(config_data)
    current = _get_selector_default(config_data)
    table = Table("#", "Node", "Status")
    for idx, tag in enumerate(tags, start=1):
        status = "[green]● active[/green]" if tag == current else ""
        table.add_row(str(idx), tag, status)
    console.print(table)


@node.command("use")
@click.argument("tag_or_index")
@click.pass_context
def node_use(ctx: click.Context, tag_or_index: str) -> None:
    """Switch the sing-box proxy selector to a node.

    Accepts either a node tag (name) or a numeric index from 'node list'.

    Tries the sing-box selector CLI first (v1.8+). Falls back to
    editing the config default and sending SIGHUP for older versions.
    """
    proxy_ctx = _ctx(ctx)

    # Resolve numeric index to tag
    tag = tag_or_index
    if tag_or_index.isdigit():
        try:
            config_data = config_module.read_config(proxy_ctx.config_path)
        except Exception as exc:
            raise click.ClickException(str(exc)) from exc
        tags = _node_tags(config_data)
        idx = int(tag_or_index) - 1
        if idx < 0 or idx >= len(tags):
            raise click.ClickException(
                f"index {tag_or_index} out of range (1-{len(tags)})"
            )
        tag = tags[idx]

    # Try selector CLI first (sing-box >= 1.8)
    try:
        result = subprocess.run(
            ["sing-box", "selector", "set", "proxy", tag],
            capture_output=True, text=True,
        )
        if result.returncode == 0:
            console.print(f"Switched proxy selector to {tag}")
            return
    except FileNotFoundError:
        pass

    # Fallback: edit config default + SIGHUP
    switch_method = _switch_node_via_config(proxy_ctx.config_path, tag)
    console.print(f"Switched proxy selector to {tag} (via {switch_method})")


@node.command("current")
def node_current() -> None:
    """Show the current active proxy node."""
    try:
        config_data = config_module.read_config()
    except Exception as exc:
        raise click.ClickException(str(exc)) from exc

    current = _get_selector_default(config_data)
    if current:
        console.print(f"Current node: {current}")
    else:
        console.print("No default node set in selector")


@node.command("test")
@click.option("--timeout", "-t", type=float, default=3.0, show_default=True,
              help="TCP connection timeout in seconds.")
@click.option("--top", "-n", type=int, default=0,
              help="Show only top N results (0 = all).")
@click.pass_context
def node_test(ctx: click.Context, timeout: float, top: int) -> None:
    """Measure TCP latency to each node's server."""
    proxy_ctx = _ctx(ctx)
    try:
        config_data = config_module.read_config(proxy_ctx.config_path)
    except Exception as exc:
        raise click.ClickException(str(exc)) from exc

    outbounds = config_data.get("outbounds", [])
    nodes = [
        o for o in outbounds
        if o.get("tag") and o.get("server") and o.get("server_port")
        and o.get("type") not in ("selector", "direct", "dns", "block")
    ]

    if not nodes:
        console.print("No testable nodes found in config.")
        return

    results: list[tuple[str, float | None]] = []
    with console.status("Testing node latency..."):
        for node in nodes:
            latency = _tcp_ping(
                str(node["server"]), int(node["server_port"]), timeout,
            )
            results.append((str(node["tag"]), latency))

    if top > 0:
        results = results[:top]

    table = Table("#", "Node", "Latency")
    for idx, (tag, latency) in enumerate(results, start=1):
        if latency is None:
            table.add_row(str(idx), tag, "[red]timeout[/red]")
        elif latency < 200:
            table.add_row(str(idx), tag, f"[green]{latency:.0f}ms[/green]")
        elif latency < 500:
            table.add_row(str(idx), tag, f"[yellow]{latency:.0f}ms[/yellow]")
        else:
            table.add_row(str(idx), tag, f"[red]{latency:.0f}ms[/red]")
    console.print(table)


@cli.group()
def daemon() -> None:
    """Manage the sing-box daemon process."""


@daemon.command("start")
@click.pass_context
def daemon_start(ctx: click.Context) -> None:
    """Start sing-box in the background."""
    proxy_ctx = _ctx(ctx)
    try:
        process = daemon_module.start_daemon(proxy_ctx.config_path, check_health=False)
    except Exception as exc:
        raise click.ClickException(str(exc)) from exc
    console.print(f"Started sing-box with PID {process.pid}")
    try:
        daemon_module.check_startup_health(process)
    except Exception as exc:
        raise click.ClickException(str(exc)) from exc
    console.print("sing-box is running")


@daemon.command("stop")
def daemon_stop() -> None:
    """Stop the sing-box daemon."""
    daemon_module.stop_daemon()
    console.print("Stopped sing-box")


@daemon.command("restart")
@click.pass_context
def daemon_restart(ctx: click.Context) -> None:
    """Restart the sing-box daemon."""
    proxy_ctx = _ctx(ctx)
    try:
        process = daemon_module.restart_daemon(
            proxy_ctx.config_path,
            check_health=False,
        )
    except Exception as exc:
        raise click.ClickException(str(exc)) from exc
    console.print(f"Restarted sing-box with PID {process.pid}")
    try:
        daemon_module.check_startup_health(process)
    except Exception as exc:
        raise click.ClickException(str(exc)) from exc
    console.print("sing-box is running")


@daemon.command("status")
def daemon_status() -> None:
    """Show whether sing-box appears to be running."""
    console.print("running" if daemon_module.status_daemon() else "stopped")


@daemon.command("logs")
@click.option("--lines", "-n", type=int, default=100, show_default=True)
def daemon_logs(lines: int) -> None:
    """Print the last lines from the sing-box log."""
    logs = daemon_module.get_logs(lines)
    console.print(logs or "No logs found.")


@cli.group(name="config")
def config_group() -> None:
    """Manage generated sing-box configuration."""


@config_group.command("generate")
@click.argument("input_file", type=click.Path(path_type=Path, exists=True, dir_okay=False))
@click.pass_context
def config_generate(ctx: click.Context, input_file: Path) -> None:
    """Generate config from a local subscription content file."""
    proxy_ctx = _ctx(ctx)
    raw_text = input_file.read_text(encoding="utf-8")
    nodes = subscription_module.parse_subscription(raw_text)
    if not nodes:
        raise click.ClickException("input file did not contain any supported nodes")
    config_module.generate_config(nodes, proxy_ctx.config_path)
    console.print(f"Wrote {proxy_ctx.config_path} with {len(nodes)} nodes")


@config_group.command("show")
@click.pass_context
def config_show(ctx: click.Context) -> None:
    """Print the generated config JSON."""
    proxy_ctx = _ctx(ctx)
    try:
        config_data = config_module.read_config(proxy_ctx.config_path)
    except Exception as exc:
        raise click.ClickException(str(exc)) from exc
    console.print_json(data=config_data)


@config_group.group("direct-domains")
def direct_domains_group() -> None:
    """Manage direct-routing domain suffixes."""


@direct_domains_group.command("list")
def direct_domains_list() -> None:
    """List all direct-routing domain suffixes."""
    domains = config_module.load_direct_domains()
    if not domains:
        console.print("No direct domains configured.")
        return
    for d in domains:
        console.print(d)


@direct_domains_group.command("add")
@click.argument("domain")
def direct_domains_add(domain: str) -> None:
    """Add a domain suffix to direct routing."""
    if config_module.add_direct_domain(domain):
        console.print(f"Added {domain} to direct domains.")
    else:
        console.print(f"{domain} already in direct domains.")


@direct_domains_group.command("remove")
@click.argument("domain")
def direct_domains_remove(domain: str) -> None:
    """Remove a domain suffix from direct routing."""
    if config_module.remove_direct_domain(domain):
        console.print(f"Removed {domain} from direct domains.")
    else:
        console.print(f"{domain} not found in direct domains.")


@direct_domains_group.command("reset")
def direct_domains_reset() -> None:
    """Reset direct domains to defaults."""
    config_module.save_direct_domains(config_module._DEFAULT_DIRECT_DOMAINS)
    console.print("Reset direct domains to defaults.")
