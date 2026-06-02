"""Manage the sing-box daemon process for proxycli."""

from __future__ import annotations

import os
import json
import re
import signal
import subprocess
import time
from pathlib import Path

from proxycli.config import app_dir, default_config_path

PID_PATH = app_dir() / "daemon.pid"
LOG_PATH = app_dir() / "sing-box.log"
HEALTH_CHECK_WAIT_SECONDS = 5.0
LOG_ERROR_PATTERN = re.compile(r"\b(?:FATAL|ERROR)\b")


def _is_root() -> bool:
    """Return whether the current process has root privileges."""
    geteuid = getattr(os, "geteuid", None)
    return geteuid is None or geteuid() == 0


def _config_has_tun_inbound(config_path: Path) -> bool:
    """Return whether a sing-box config contains a TUN inbound."""
    expanded = config_path.expanduser()
    if not expanded.exists():
        raise RuntimeError(f"config file not found: {expanded}")

    try:
        data = json.loads(expanded.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"invalid JSON config file {expanded}: {exc}") from exc

    if not isinstance(data, dict):
        raise RuntimeError(f"config file must contain a JSON object: {expanded}")

    inbounds = data.get("inbounds", [])
    return any(
        isinstance(inbound, dict) and inbound.get("type") == "tun"
        for inbound in inbounds
    )


def _require_root_for_tun(config_path: Path, action: str) -> None:
    """Raise when the config needs TUN privileges and the process is not root."""
    if _is_root() or not _config_has_tun_inbound(config_path):
        return

    raise RuntimeError(
        f"sudo is required to {action} sing-box because the config contains a "
        f"TUN inbound. Run: sudo uv run proxycli daemon {action}"
    )


def _read_pid(path: Path | None = None) -> int | None:
    """Read a PID file and return the stored process id."""
    expanded = (path or PID_PATH).expanduser()
    if not expanded.exists():
        return None
    try:
        return int(expanded.read_text(encoding="utf-8").strip())
    except ValueError:
        return None


def _is_running(pid: int) -> bool:
    """Return whether a process id currently exists."""
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _process_is_alive(process: subprocess.Popen[bytes]) -> bool:
    """Return whether a Popen process still appears to be running."""
    if process.poll() is not None:
        return False
    return _is_running(process.pid)


def _read_log_file() -> str:
    """Return the full sing-box log content."""
    if not LOG_PATH.exists():
        return ""
    return LOG_PATH.read_text(encoding="utf-8", errors="replace")


def _find_error_lines(log_content: str) -> list[str]:
    """Return startup log lines that indicate sing-box reported an error."""
    return [
        line for line in log_content.splitlines()
        if LOG_ERROR_PATTERN.search(line)
    ]


def _cleanup_failed_start(process: subprocess.Popen[bytes]) -> None:
    """Remove failed startup state and terminate any still-running process."""
    if _process_is_alive(process):
        stop_daemon(process)
    else:
        PID_PATH.unlink(missing_ok=True)


def check_startup_health(
    process: subprocess.Popen[bytes],
    wait_seconds: float = HEALTH_CHECK_WAIT_SECONDS,
) -> None:
    """Wait for sing-box startup and raise with logs if it exits or logs errors."""
    time.sleep(wait_seconds)
    log_content = _read_log_file()
    error_lines = _find_error_lines(log_content)
    if error_lines:
        _cleanup_failed_start(process)
        raise RuntimeError(
            "sing-box reported errors during startup. Check logs:\n"
            f"{log_content}"
        )

    if not _process_is_alive(process):
        PID_PATH.unlink(missing_ok=True)
        log_tail = get_logs(80)
        raise RuntimeError(
            f"sing-box exited during startup (PID {process.pid}). Check logs:\n"
            f"{log_tail}"
        )


def start_daemon(config_path: Path | None = None, check_health: bool = True) -> subprocess.Popen[bytes]:
    """Start sing-box in the background and store its PID.

    When *check_health* is True (the default), waits briefly after start
    and raises RuntimeError with log output if sing-box exits immediately.
    """
    if config_path is None:
        config_path = default_config_path()
    existing_pid = _read_pid()
    if existing_pid and _is_running(existing_pid):
        raise RuntimeError(f"sing-box is already running with PID {existing_pid}")

    app_dir().mkdir(parents=True, exist_ok=True)
    config_path = config_path.expanduser()
    _require_root_for_tun(config_path, "start")

    # Truncate log on fresh start
    LOG_PATH.write_text("", encoding="utf-8")
    log_file = LOG_PATH.open("ab")
    process = subprocess.Popen(
        ["sing-box", "run", "-c", str(config_path)],
        stdout=log_file,
        stderr=subprocess.STDOUT,
        start_new_session=True,
        env={
            **os.environ,
            "ENABLE_DEPRECATED_LEGACY_DNS_SERVERS": "true",
            "ENABLE_DEPRECATED_LEGACY_DNS_FAKEIP_OPTIONS": "true",
        },
    )
    PID_PATH.write_text(f"{process.pid}\n", encoding="utf-8")

    if check_health:
        check_startup_health(process)

    return process


def stop_daemon(process: subprocess.Popen[bytes] | None = None) -> None:
    """Stop sing-box by terminating a provided process or the PID file process."""
    pid = process.pid if process is not None else _read_pid()
    if pid is None:
        return

    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        pass

    if process is not None:
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
    else:
        deadline = time.time() + 10
        while time.time() < deadline and _is_running(pid):
            time.sleep(0.1)

    if PID_PATH.exists():
        PID_PATH.unlink()


def restart_daemon(
    config_path: Path | None = None,
    check_health: bool = True,
) -> subprocess.Popen[bytes]:
    """Restart sing-box using the provided config path."""
    if config_path is None:
        config_path = default_config_path()
    _require_root_for_tun(config_path.expanduser(), "restart")
    stop_daemon()
    return start_daemon(config_path, check_health=check_health)


def status_daemon() -> bool:
    """Return whether the PID-file sing-box process appears to be running."""
    pid = _read_pid()
    return bool(pid and _is_running(pid))


def reload_daemon(use_sudo: bool = False) -> None:
    """Send SIGHUP to sing-box to trigger a graceful config reload.

    Set *use_sudo* to True when running in a CLI context where password
    prompts are acceptable. In TUI/automated contexts, leave it False
    and handle the PermissionError yourself.
    """
    pid = _read_pid()
    if pid is None or not _is_running(pid):
        raise RuntimeError("sing-box is not running")

    try:
        os.kill(pid, signal.SIGHUP)
    except PermissionError:
        if use_sudo:
            try:
                subprocess.run(
                    ["sudo", "kill", "-HUP", str(pid)],
                    check=True, capture_output=True, text=True,
                )
            except subprocess.CalledProcessError as exc:
                raise RuntimeError(
                    f"failed to reload sing-box (PID {pid}): {exc.stderr.strip()}"
                ) from exc
        else:
            raise


def get_logs(lines: int = 100) -> str:
    """Return the last N lines of the sing-box log file."""
    content = _read_log_file().splitlines()
    return "\n".join(content[-lines:])
