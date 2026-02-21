# ry-web-dashboard v1.2.0

Web dashboard for [ry-install](https://github.com/ryanmusante/ry-install) — monitor, verify, and manage your CachyOS configuration from a browser.

## Features

| Tab | Mode | Description |
|-----|------|-------------|
| **Monitor** | SSE live | CPU/GPU temps, memory, power, services, network, ntsync, ZRAM — 2s refresh via sysfs |
| **Diagnose** | `--diagnose --json` | Full system diagnostics with issue summary |
| **Config Drift** | `--diff` / `--verify-static` | Detect config file drift and verify static content |
| **Runtime** | `--verify-runtime` | Verify live kernel params, services, sysfs state |
| **Logs** | `--logs <target>` | View system, gpu, wifi, boot, audio, usb, kernel logs |
| **Lint** | `--lint` | Fish syntax and anti-pattern checks |
| **Actions** | `--clean`, `--all`, `--install-file`, `--test-all` | System cleanup, full install, single-file deploy, test suite |
| **Changelog** | `--changelog` | Embedded version history |

The live monitor reads sysfs directly (no subprocesses) for minimal overhead. All other tabs execute `ry-install.fish` with the appropriate flags.

## Requirements

- Python 3.10+
- `aiohttp` (`pip install aiohttp --break-system-packages`)
- `ry-install.fish` accessible on the filesystem
- `fish` shell (for ry-install execution)

## Install

```fish
# 1. Clone or copy to ~/ry-web-dashboard/
mkdir -p ~/ry-web-dashboard
cp -r ry-web-dashboard.py static/ ry-web-dashboard.service setup.fish ~/ry-web-dashboard/

# 2. Automated setup (installs aiohttp, configures systemd service)
fish ~/ry-web-dashboard/setup.fish --script ~/ry-install/ry-install.fish

# 3. Open browser
xdg-open http://localhost:9000
```

Or manually:

```fish
pip install aiohttp --break-system-packages
ln -s ~/ry-install/ry-install.fish ~/ry-web-dashboard/ry-install.fish
python3 ~/ry-web-dashboard/ry-web-dashboard.py --port 9000
```

## Usage

```
python3 ry-web-dashboard.py [OPTIONS]

  --host HOST    Bind address (default: 0.0.0.0)
  --port PORT    Port (default: 9000)
  --script PATH  Path to ry-install.fish
```

### Access from LAN

Binding to `0.0.0.0` (default) exposes the dashboard on your LAN. Access from any device:

```
http://192.168.50.X:9000
```

There is no authentication — the dashboard has full access to ry-install operations including `--clean` and `--all`. CSRF protection blocks cross-origin POST requests. Security headers (CSP, X-Content-Type-Options, X-Frame-Options) are set on all API responses. To restrict to localhost only:

```fish
python3 ry-web-dashboard.py --host 127.0.0.1
```

### Sudoers for unattended operation

Several ry-install modes require sudo (diagnose, install, clean, logs). For the systemd service to work without a TTY, configure passwordless sudo for ry-install:

```fish
# /etc/sudoers.d/ry-install
ryan ALL=(ALL) NOPASSWD: /usr/bin/dmesg, /usr/bin/nvme, /usr/bin/cat /etc/kernel/cmdline, /usr/bin/cat /boot/*
```

Or more permissively (if this is a personal workstation):

```fish
ryan ALL=(ALL) NOPASSWD: ALL
```

## API Reference

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/telemetry` | GET | Snapshot of live system state |
| `/api/telemetry/stream` | GET | SSE stream (2s interval) |
| `/api/diagnose` | GET | `--diagnose --json --force` |
| `/api/diff` | GET | `--diff` |
| `/api/verify/static` | GET | `--verify-static` |
| `/api/verify/runtime` | GET | `--verify-runtime` |
| `/api/lint` | GET | `--lint` |
| `/api/logs/{target}` | GET | `--logs <target>` |
| `/api/changelog` | GET | `--changelog` |
| `/api/managed-files` | GET | List of managed file paths |
| `/api/info` | GET | Dashboard + ry-install version info |
| `/api/clean` | POST | `--clean --force [--dry-run]` |
| `/api/install` | POST | `--all [--dry-run]` |
| `/api/install-file` | POST | `--install-file <path> [--dry-run]` |
| `/api/test-all` | POST | `--test-all` |

POST bodies accept `{"dry_run": true}` (default: true for safety).

## Architecture

```
Browser ──► ry-web-dashboard.py (aiohttp) ──► ry-install.fish (subprocess)
                │                              │
                ├─ /api/telemetry/stream ──► sysfs (direct read, no subprocess)
                └─ /static/index.html ──► SPA (vanilla JS, no build step)
                   /static/app.js
```

No build tools, no node_modules, no bundlers. One Python file, one HTML shell, one JS file. Dark/light theme toggle with `prefers-color-scheme` detection and `localStorage` persistence.

## Firewall

If using `firewalld`:

```fish
sudo firewall-cmd --add-port=9000/tcp --permanent
sudo firewall-cmd --reload
```

## License

MIT
