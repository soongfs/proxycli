# proxycli

A CLI tool for managing a [sing-box](https://sing-box.sagernet.org/) proxy
on macOS and Linux. Import subscriptions, auto-download routing rule-sets,
switch nodes at runtime, and manage the daemon — all from the terminal.

## Requirements

- Python 3.11+
- [sing-box](https://sing-box.sagernet.org/) 1.12+
- [uv](https://docs.astral.sh/uv/) (for installation)

## Installation

```bash
git clone https://github.com/soongfs/proxycli.git
cd proxycli
uv tool install .
```

This installs `proxycli` globally to `~/.local/bin/`. Make sure it's in
your `PATH` (`uv` handles this automatically).

## Quick start

```bash
# Import subscription (fetches nodes + downloads CN routing rule-sets)
proxycli sub update https://your-subscription-url

# Start the daemon (TUN needs root; use full path under sudo)
sudo ~/.local/bin/proxycli daemon start

# List nodes
proxycli node list

# Switch to node #71
proxycli node use 71

# Verify
curl https://ipinfo.io
```

## Commands

### `proxycli sub`

| Command              | Description                                      |
|----------------------|--------------------------------------------------|
| `sub update [url]`   | Fetch subscription, generate config              |
| `sub update --proxy` | Fetch through HTTP proxy (`http://127.0.0.1:7890`) |
| `sub show`           | Show subscription state (URL, last update)       |

### `proxycli node`

| Command         | Description                                |
|-----------------|--------------------------------------------|
| `node list`     | List all nodes with index + active status   |
| `node use <N>`  | Switch to node by index or tag              |
| `node current`  | Show current active node                    |
| `node test`     | TCP latency test for all nodes              |

### `proxycli daemon`

| Command           | Description              |
|-------------------|--------------------------|
| `daemon start`    | Start sing-box in background |
| `daemon stop`     | Stop sing-box            |
| `daemon restart`  | Restart sing-box         |
| `daemon status`   | Check if running         |
| `daemon logs [-n]`| View recent log lines    |

### `proxycli config`

| Command                           | Description                       |
|-----------------------------------|-----------------------------------|
| `config show`                     | Print current config.json         |
| `config generate <file>`          | Generate config from local file   |
| `config direct-domains list`      | List manual direct-routing domains |
| `config direct-domains add <d>`   | Add domain to direct routing       |
| `config direct-domains remove <d>`| Remove domain                      |
| `config direct-domains reset`     | Reset to defaults                  |

## How routing works

CN traffic is routed directly using rule-sets (`geoip-cn.srs`,
`geosite-cn.srs`) auto-downloaded from jsDelivr CDN on every
`sub update`. Everything else goes through the proxy.

To add custom domains to direct routing:

```bash
proxycli config direct-domains add openai.com
proxycli sub update
sudo proxycli daemon restart
```

## Data directory

All state is stored under `~/.config/proxycli/`:

```
~/.config/proxycli/
├── config.json           # Generated sing-box config
├── state.json            # Subscription URL, last update time
├── direct-domains.json   # Manual direct-routing domains
├── daemon.pid            # sing-box process PID
├── sing-box.log          # sing-box output
└── rule-sets/
    ├── geoip-cn.srs      # Auto-downloaded
    └── geosite-cn.srs    # Auto-downloaded
```

## License

MIT
