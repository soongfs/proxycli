# Daemon Module

`proxycli.daemon` manages the local sing-box process using standard subprocess
and signal operations.

## Process Lifecycle

`start_daemon(config_path)` launches:

```bash
sing-box run -c <config_path>
```

It starts the process in a new session, appends stdout and stderr to
`~/.config/proxycli/sing-box.log`, and writes the PID to
`~/.config/proxycli/daemon.pid`.

`stop_daemon(process)` accepts an optional `subprocess.Popen` instance. If no
process is passed, it reads the PID file and sends `SIGTERM`.

`restart_daemon(config_path)` stops any PID-file process and starts a new one.

`status_daemon()` returns true when the PID-file process exists.

## Log Capture

The daemon redirects stderr into stdout and appends both streams to
`sing-box.log`. `get_logs(lines)` returns the last N lines without requiring the
process to be active.

## Log Rotation

The current implementation appends to one log file. A future rotation policy can
truncate by size before start or keep timestamped log archives. Rotation is not
enabled by default to keep daemon startup deterministic.

## Health Check

The health check is PID-based. It answers whether a process with the stored PID
exists, not whether sing-box has fully initialized the TUN interface. A stricter
health check could inspect logs or call sing-box APIs if configured.

## macOS Notes

TUN mode and `auto_route` may require elevated privileges depending on the
sing-box installation and macOS network permissions. `proxycli` does not call
`sudo` itself; users should run it in an environment where sing-box can create
the TUN interface.
