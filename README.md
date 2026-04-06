# ry-web-dashboard v1.4.0

Web dashboard for [ry-install](https://github.com/ryanmusante/ry-install) — monitor, verify, and manage your CachyOS configuration from a browser.

## Features

| Tab | Mode | Description |
|-----|------|-------------|
| **Monitor** | SSE live | CPU/GPU temps, memory, power, services, network, ntsync, ZRAM — 2s refresh via sysfs |
| **Diagnose** | `--diagnose --json` | Full system diagnostics with issue summary |
| **Config Drift** | `--diff` / `--verify-static` | Detect config file drift and verify static content |
| **Runtime** | `--verify-runtime` | Verify live kernel params, services, sysfs state |
| **Logs** | `--logs <target>` | View system, gpu, wifi, boot, audio, usb, kernel logs + analyze, last, list, all |
| **Lint** | `--lint` | Fish syntax and anti-pattern checks |
| **Actions** | `--clean`, `--all`, `--install-file`, `--test-all`, `--profile`, `--stress` | System cleanup, full install, single-file deploy, test suite, profile, stress test |
| **Changelog** | CHANGELOG.txt | Embedded version history read from ry-install directory |

The live monitor reads sysfs directly (no subprocesses) for minimal overhead. Static values (kernel version, VRAM total, ZRAM config) are cached at startup to reduce per-tick reads. Service state checks run as parallel async subprocesses. All other tabs execute `ry-install.fish` with the appropriate flags.

## Requirements

- Python 3.10+
- `aiohttp` (`pip install aiohttp --break-system-packages`)
- `ry-install.fish` accessible on the filesystem
- `fish` shell 3.0+ (for ry-install execution and setup script)

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
  --version      Print version and exit
```

### Authentication

Set the `RY_DASH_TOKEN` environment variable to enable bearer token authentication on all `/api/` endpoints. When set, clients must include `Authorization: Bearer <token>` in requests. When unset, all endpoints are open (suitable for localhost-only binding).

```fish
# Generate and store a token
set -Ux RY_DASH_TOKEN (openssl rand -hex 32)

# Or via systemd environment file (0600 perms)
echo "RY_DASH_TOKEN=your-secret-token" > ~/.config/ry-web-dashboard.env
chmod 600 ~/.config/ry-web-dashboard.env
```

Add to the systemd drop-in (`~/.config/systemd/user/ry-web-dashboard.service.d/paths.conf`):

```ini
[Service]
EnvironmentFile=%h/.config/ry-web-dashboard.env
```

### Access from LAN

Binding to `0.0.0.0` (default) exposes the dashboard on your LAN. Access from any device:

```
http://192.168.50.X:9000
```

CSRF protection validates Origin and Referer headers on POST requests. Security headers are set on all API responses:

| Header | Value |
|--------|-------|
| Content-Security-Policy | `default-src 'none'; script-src 'self'; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; font-src https://fonts.gstatic.com; connect-src 'self'; img-src 'self'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'` |
| X-Content-Type-Options | `nosniff` |
| X-Frame-Options | `DENY` |
| Referrer-Policy | `no-referrer` |
| Permissions-Policy | `camera=(), microphone=(), geolocation=(), payment=(), usb=(), interest-cohort=()` |
| Cache-Control | `no-store` (non-SSE API routes) |

SSE connections are limited to 5 concurrent clients. POST request bodies are limited to 64 KB.

To restrict to localhost only:

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

| Endpoint | Method | Auth | Description |
|----------|--------|------|-------------|
| `/api/telemetry` | GET | token | Snapshot of live system state |
| `/api/telemetry/stream` | GET | token | SSE stream (2s interval, max 5 clients) |
| `/api/diagnose` | GET | token | `--diagnose --json --force` |
| `/api/diff` | GET | token | `--diff` |
| `/api/verify/static` | GET | token | `--verify-static` |
| `/api/verify/runtime` | GET | token | `--verify-runtime` |
| `/api/lint` | GET | token | `--lint` |
| `/api/logs/{target}` | GET | token | `--logs <target>` (allowlisted targets only) |
| `/api/changelog` | GET | token | Read CHANGELOG.txt from ry-install directory |
| `/api/managed-files` | GET | token | List of managed file paths |
| `/api/info` | GET | token | Dashboard + ry-install version info |
| `/api/clean` | POST | token | `--clean --force [--dry-run]` |
| `/api/install` | POST | token | `--all [--dry-run]` |
| `/api/install-file` | POST | token | `--install-file <path> [--dry-run]` |
| `/api/test-all` | POST | token | `--test-all` |
| `/api/profile` | POST | token | `--profile` |
| `/api/stress` | POST | token | `--stress` |

POST bodies accept `{"dry_run": true}` (default: true for safety). Auth column applies only when `RY_DASH_TOKEN` is set.

## Architecture

```
Browser ──► ry-web-dashboard.py (aiohttp) ──► ry-install.fish (subprocess)
                │                              │
                ├─ /api/telemetry/stream ──► sysfs (direct read, no subprocess)
                ├─ /api/changelog ──► CHANGELOG.txt (direct read)
                └─ /static/index.html ──► SPA (vanilla JS, no build step)
                   /static/app.js
```

No build tools, no node_modules, no bundlers. One Python file, one HTML shell, one JS file. Dark/light theme toggle with `prefers-color-scheme` detection and `localStorage` persistence.

### Systemd hardening

The user service unit includes sandboxing directives: `PrivateTmp`, `ProtectKernelModules`, `ProtectKernelTunables`, `ProtectKernelLogs`, `ProtectClock`, `ProtectHostname`, `ProtectControlGroups`, `RestrictSUIDSGID`, `LockPersonality`, `RestrictRealtime`, `SystemCallArchitectures=native`. Verify with:

```fish
systemd-analyze security ry-web-dashboard.service
```

`ProtectSystem=strict`, `ProtectHome=yes`, and `NoNewPrivileges=yes` are intentionally omitted because ry-install writes to `/etc`, reads from `~/ry-install/`, and invokes `sudo`.

## Firewall

If using `firewalld`:

```fish
sudo firewall-cmd --add-port=9000/tcp --permanent
sudo firewall-cmd --reload
```

## License

MIT
