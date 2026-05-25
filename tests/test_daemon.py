from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

import pytest

from proxycli import daemon


class FakePopen:
    def __init__(
        self,
        args: list[str],
        stdout: object,
        stderr: object,
        start_new_session: bool,
        env: dict[str, str],
    ) -> None:
        self.args = args
        self.stdout = stdout
        self.stderr = stderr
        self.start_new_session = start_new_session
        self.env = env
        self.pid = 4321
        self.killed = False
        self.returncode: int | None = None

    def wait(self, timeout: int | None = None) -> int:
        return 0

    def poll(self) -> int | None:
        return self.returncode

    def kill(self) -> None:
        self.killed = True


def test_start_daemon_writes_pid_and_uses_config(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pid_path = tmp_path / "daemon.pid"
    log_path = tmp_path / "sing-box.log"
    config_path = tmp_path / "config.json"
    config_path.write_text("{}", encoding="utf-8")
    created: dict[str, FakePopen] = {}

    def fake_popen(*args: object, **kwargs: object) -> FakePopen:
        process = FakePopen(*args, **kwargs)  # type: ignore[arg-type]
        created["process"] = process
        return process

    monkeypatch.setattr(daemon, "app_dir", lambda: tmp_path)
    monkeypatch.setattr(daemon, "PID_PATH", pid_path)
    monkeypatch.setattr(daemon, "LOG_PATH", log_path)
    monkeypatch.setattr(daemon, "_is_root", lambda: True)
    monkeypatch.setattr(daemon, "_is_running", lambda pid: True)
    sleep_calls: list[float] = []
    monkeypatch.setattr(daemon.time, "sleep", sleep_calls.append)
    monkeypatch.setattr(subprocess, "Popen", fake_popen)

    process = daemon.start_daemon(config_path)

    assert process.pid == 4321
    assert sleep_calls == [5.0]
    assert pid_path.read_text(encoding="utf-8").strip() == "4321"
    assert created["process"].args == ["sing-box", "run", "-c", str(config_path)]
    assert created["process"].stderr == subprocess.STDOUT
    assert created["process"].start_new_session is True
    assert created["process"].env["ENABLE_DEPRECATED_LEGACY_DNS_SERVERS"] == "true"
    assert (
        created["process"].env["ENABLE_DEPRECATED_LEGACY_DNS_FAKEIP_OPTIONS"]
        == "true"
    )


def test_start_daemon_rejects_existing_running_pid(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pid_path = tmp_path / "daemon.pid"
    pid_path.write_text("123\n", encoding="utf-8")
    monkeypatch.setattr(daemon, "PID_PATH", pid_path)
    monkeypatch.setattr(daemon, "_is_running", lambda pid: True)

    with pytest.raises(RuntimeError, match="already running"):
        daemon.start_daemon(tmp_path / "config.json")


def test_stop_daemon_sends_sigterm_and_removes_pid(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pid_path = tmp_path / "daemon.pid"
    pid_path.write_text("123\n", encoding="utf-8")
    calls: list[tuple[int, int]] = []

    def fake_kill(pid: int, sig: int) -> None:
        calls.append((pid, sig))

    monkeypatch.setattr(daemon, "PID_PATH", pid_path)
    monkeypatch.setattr(daemon.os, "kill", fake_kill)
    monkeypatch.setattr(daemon, "_is_running", lambda pid: False)

    daemon.stop_daemon()

    assert calls == [(123, daemon.signal.SIGTERM)]
    assert not pid_path.exists()


def test_status_daemon(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pid_path = tmp_path / "daemon.pid"
    pid_path.write_text("123\n", encoding="utf-8")
    monkeypatch.setattr(daemon, "PID_PATH", pid_path)
    monkeypatch.setattr(daemon, "_is_running", lambda pid: pid == 123)

    assert daemon.status_daemon() is True


def test_get_logs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    log_path = tmp_path / "sing-box.log"
    log_path.write_text("a\nb\nc\n", encoding="utf-8")
    monkeypatch.setattr(daemon, "LOG_PATH", log_path)

    assert daemon.get_logs(2) == "b\nc"


def test_start_daemon_rejects_non_root_tun_config(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pid_path = tmp_path / "daemon.pid"
    config_path = tmp_path / "config.json"
    config_path.write_text(
        '{"inbounds": [{"type": "tun", "tag": "tun-in"}]}',
        encoding="utf-8",
    )

    monkeypatch.setattr(daemon, "app_dir", lambda: tmp_path)
    monkeypatch.setattr(daemon, "PID_PATH", pid_path)
    monkeypatch.setattr(daemon, "_is_root", lambda: False)

    with pytest.raises(RuntimeError, match="sudo is required to start sing-box"):
        daemon.start_daemon(config_path)

    assert not pid_path.exists()


def test_start_daemon_allows_non_root_non_tun_config(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pid_path = tmp_path / "daemon.pid"
    log_path = tmp_path / "sing-box.log"
    config_path = tmp_path / "config.json"
    config_path.write_text(
        '{"inbounds": [{"type": "mixed", "tag": "mixed-in"}]}',
        encoding="utf-8",
    )
    created: dict[str, FakePopen] = {}

    def fake_popen(*args: Any, **kwargs: Any) -> FakePopen:
        process = FakePopen(*args, **kwargs)
        created["process"] = process
        return process

    monkeypatch.setattr(daemon, "app_dir", lambda: tmp_path)
    monkeypatch.setattr(daemon, "PID_PATH", pid_path)
    monkeypatch.setattr(daemon, "LOG_PATH", log_path)
    monkeypatch.setattr(daemon, "_is_root", lambda: False)
    monkeypatch.setattr(daemon, "_is_running", lambda pid: True)
    monkeypatch.setattr(daemon.time, "sleep", lambda seconds: None)
    monkeypatch.setattr(subprocess, "Popen", fake_popen)

    process = daemon.start_daemon(config_path)

    assert process is created["process"]


def test_start_daemon_fails_when_log_contains_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pid_path = tmp_path / "daemon.pid"
    log_path = tmp_path / "sing-box.log"
    config_path = tmp_path / "config.json"
    config_path.write_text("{}", encoding="utf-8")
    created: dict[str, FakePopen] = {}

    def fake_popen(*args: Any, **kwargs: Any) -> FakePopen:
        process = FakePopen(*args, **kwargs)
        created["process"] = process
        log_path.write_text(
            "INFO network: updated default interface en1\n"
            "FATAL start service: bad dns config\n",
            encoding="utf-8",
        )
        return process

    monkeypatch.setattr(daemon, "app_dir", lambda: tmp_path)
    monkeypatch.setattr(daemon, "PID_PATH", pid_path)
    monkeypatch.setattr(daemon, "LOG_PATH", log_path)
    monkeypatch.setattr(daemon, "_is_root", lambda: True)
    monkeypatch.setattr(daemon, "_is_running", lambda pid: True)
    monkeypatch.setattr(daemon.os, "kill", lambda pid, sig: None)
    monkeypatch.setattr(daemon.time, "sleep", lambda seconds: None)
    monkeypatch.setattr(subprocess, "Popen", fake_popen)

    with pytest.raises(RuntimeError, match="sing-box reported errors"):
        daemon.start_daemon(config_path)

    assert not pid_path.exists()
    assert created["process"].killed is False
