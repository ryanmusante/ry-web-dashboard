# ry-web-dashboard

![version](https://img.shields.io/badge/version-1.5.0-blue)
![license](https://img.shields.io/badge/license-MIT-green)
![python](https://img.shields.io/badge/python-3.10%2B-orange)

Web dashboard for [ry-install](https://github.com/ryanmusante/ry-install) — monitor, verify, and manage your CachyOS configuration from a browser.

[changelog](CHANGELOG.md)

## Features

| Tab | Mode | Description |
|-----|------|-------------|
| **Monitor** | SSE live | CPU/GPU temps, memory, power, services, network, ntsync, ZRAM — 2s refresh via sysfs |
| **Check** | `--check` | Silent idempotency probe (exit 0 = clean, 3 = prereq fail, 10 = drift) |
| **Config Drift** | `--diff` / `--verify-static` / `--diff --fix` | Detect config file drift, verify static content, auto-fix drifted files |
| **Runtime** | `--verify-runtime` | Verify live kernel params, services, sysfs state |
| **Logs** | `journalctl` | View system, gpu, wifi, boot, audio, usb, kernel logs + analyze, last, all |
| **Lint** | `--lint` | Fish syntax and anti-pattern checks |
| **Actions** | `--all`, `--install-file`, `--test-all`, cleanup | Full install, single-file deploy, test suite, system cleanup (paccache/journal vacuum) |
| **Changelog** | CHANGELOG.md | Embedded version history read from ry-install directory |

The live monitor reads sysfs directly (no subprocesses) for minimal overhead. Static values (kernel version, VRAM total, ZRAM config) are cached at startup to reduce per-tick reads. Service state checks run as parallel async subprocesses. Check, Drift, Runtime, Lint, and Actions tabs invoke `ry-install.fish` with the appropriate flags. Logs and cleanup use direct system commands.

### Monitored services

`cpupower-epp`, `fstrim.timer`, `NetworkManager`

### Log targets

`system`, `gpu`, `wifi`, `boot`, `audio`, `usb`, `kernel`, `analyze`, `last`, `all`

## Project layout

```
ry-web-dashboard/
├── ry-web-dashboard.py        # aiohttp async server (670 lines)
├── ry-web-dashboard.service   # systemd user unit with sandboxing
├── setup.fish                 # automated install (aiohttp, symlink, service)
├── static/
│   ├── index.html             # SPA shell — dark/light theme, CSS
│   └── app.js                 # vanilla JS frontend — SSE, tabs, API calls
├── README.md
├── CHANGELOG.md
└── LICENSE                    # MIT
```

## Requirements

- Python 3.10+
- `aiohttp` (`pip install aiohttp --break-system-packages`)
- `ry-install.fish` accessible on the filesystem
- `fish` shell 3.4+ (for ry-install execution and setup script)

## Install

```fish
# 1. Clone
git clone https://github.com/ryanmusante/ry-web-dashboard.git ~/ry-web-dashboard

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

Several ry-install modes require sudo (install, diff --fix, verify-runtime). System cleanup also uses sudo for paccache and journalctl vacuum. For the systemd service to work without a TTY, configure passwordless sudo for ry-install:

```fish
# /etc/sudoers.d/ry-install
ryan ALL=(ALL) NOPASSWD: /usr/bin/cat, /usr/bin/paccache, /usr/bin/pacman, /usr/bin/journalctl
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
| `/api/check` | GET | token | `--check --force` (exit 0=clean, 3=prereq, 10=drift) |
| `/api/diff` | GET | token | `--diff` |
| `/api/verify/static` | GET | token | `--verify-static` |
| `/api/verify/runtime` | GET | token | `--verify-runtime` |
| `/api/lint` | GET | token | `--lint` |
| `/api/logs/{target}` | GET | token | journalctl queries (system, gpu, wifi, boot, audio, usb, kernel, analyze, last, all) |
| `/api/changelog` | GET | token | Read CHANGELOG.md from ry-install directory |
| `/api/managed-files` | GET | token | List of managed file paths |
| `/api/info` | GET | token | Dashboard + ry-install version info |
| `/api/clean` | POST | token | paccache, orphan removal, journal vacuum `[dry_run]` |
| `/api/install` | POST | token | `--all [--dry-run]` |
| `/api/install-file` | POST | token | `--install-file <path> [--dry-run]` |
| `/api/test-all` | POST | token | `--test-all` |
| `/api/diff-fix` | POST | token | `--diff --fix --force [--dry-run]` |

POST bodies accept `{"dry_run": true}` (default: true for safety). Auth column applies only when `RY_DASH_TOKEN` is set.

## Architecture

```
Browser ──► ry-web-dashboard.py (aiohttp) ──► ry-install.fish (subprocess)
                │                              │
                ├─ /api/telemetry/stream ──► sysfs (direct read, no subprocess)
                ├─ /api/logs/{target} ──► journalctl / systemd-analyze (direct)
                ├─ /api/clean ──► paccache / pacman / journalctl (direct)
                ├─ /api/changelog ──► CHANGELOG.md (direct read)
                └─ static/
                   ├── index.html ──► SPA shell (dark/light theme, CSS)
                   └── app.js ──► vanilla JS (SSE, tabs, API calls)
```

No build tools, no node_modules, no bundlers. One Python file, one HTML shell, one JS file. Logs and cleanup use direct system commands (`journalctl`, `paccache`, `pacman`); all other operations invoke `ry-install.fish` as a subprocess. Dark/light theme toggle with `prefers-color-scheme` detection and `localStorage` persistence.

### Systemd hardening

The user service unit includes 12 sandboxing directives: `PrivateTmp`, `ProtectKernelModules`, `ProtectKernelTunables`, `ProtectKernelLogs`, `ProtectClock`, `ProtectHostname`, `ProtectControlGroups`, `RestrictSUIDSGID`, `LockPersonality`, `RestrictRealtime`, `SystemCallArchitectures=native`, `NoNewPrivileges=no`. Verify with:

```fish
systemd-analyze security ry-web-dashboard.service
```

`ProtectSystem=strict` and `ProtectHome=yes` are intentionally omitted because ry-install writes to `/etc` and reads from `~/ry-install/`. `NoNewPrivileges` is explicitly set to `no` because ry-install invokes `sudo`.

## Firewall

If using `firewalld`:

```fish
sudo firewall-cmd --add-port=9000/tcp --permanent
sudo firewall-cmd --reload
```

## License

[MIT](LICENSE)
