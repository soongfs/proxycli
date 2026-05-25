# Architecture

`proxycli` is a small src-layout Python package with one command entry point:
`proxycli.main:cli`. The CLI delegates work to focused modules so runtime
commands remain thin and testable.

## Module Topology

- `proxycli.main` owns Click command registration, global options, terminal
  formatting, and subprocess calls for selector switching.
- `proxycli.subscription` fetches subscription URLs, decodes common base64
  subscription bodies, parses node lines, writes generated config, and persists
  subscription metadata in `~/.config/proxycli/state.json`.
- `proxycli.parser` converts individual proxy URIs into sing-box outbound
  dictionaries. It handles `vmess`, `ss`, `trojan`, `vless`, `hysteria2`,
  `hy2`, and `tuic`.
- `proxycli.config` loads the packaged Jinja2 template, renders sing-box JSON,
  writes config files, and reads config back for commands such as `node list`.
- `proxycli.daemon` starts, stops, restarts, checks, and tails the sing-box
  process using a PID file and log file under `~/.config/proxycli/`.

## Data Flow

1. `proxycli sub update URL` calls `fetch_subscription`.
2. Raw response text is decoded if it is a base64 subscription payload.
3. Each non-empty, non-comment line is parsed into a sing-box outbound.
4. The config template receives `nodes` and `node_tags`.
5. The rendered JSON is validated by loading it with `json.loads`.
6. Metadata is written to `state.json`.
7. `proxycli daemon start` launches `sing-box run -c <config>`.

## Technology Decisions

- Click is used because its command groups and context object map directly to
  `sub`, `node`, `daemon`, and `config`.
- httpx is used for HTTP with redirects, timeout, and explicit retry handling.
- Jinja2 keeps the sing-box JSON structure readable while still allowing dynamic
  outbounds.
- Rich is used only for terminal presentation, not business logic.
- The Python logging module is configured once by the CLI and used in parser and
  subscription code for recoverable warnings.

## Storage

All runtime files are stored under `~/.config/proxycli/`:

- `config.json`: generated sing-box config.
- `state.json`: subscription URL and last fetch timestamp.
- `daemon.pid`: active sing-box PID.
- `sing-box.log`: combined stdout and stderr from sing-box.
