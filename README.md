# ry-web-dashboard

![version](https://img.shields.io/badge/version-1.6.1-blue)
![license](https://img.shields.io/badge/license-MIT-green)
![python](https://img.shields.io/badge/python-3.10%2B-orange)

Web dashboard for [ry-install](https://github.com/ryanmusante/ry-install) — monitor, verify, and manage your CachyOS configuration from a browser.

[changelog](CHANGELOG.md)

## Table of Contents

- [Features](#features)
- [Project layout](#project-layout)
- [Requirements](#requirements)
- [Install](#install)
- [Usage](#usage)
- [Authentication](#authentication)
- [API Reference](#api-reference)
- [Architecture](#architecture)
- [Firewall](#firewall)
- [License](#license)

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
├── ry-web-dashboard.py        # aiohttp async server
├── ry-web-dashboard.service   # systemd user unit with sandboxing
├── setup.fish                 # automated install (aiohttp, symlink, service)
├── static/
│   ├── index.html             # SPA shell
│   ├── style.css              # dark/light theme stylesheet
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

  --host HOST    Bind address (default: 127.0.0.1)
  --port PORT    Port (default: 9000)
  --script PATH  Path to ry-install.fish
  --version      Print version and exit
```

The server **refuses to start** when `--host` is not loopback (`127.0.0.1`, `::1`, `localhost`) unless `RY_DASH_TOKEN` is set in the environment. This is fail-closed: there is no way to expose the dashboard on the LAN without authentication.

### Authentication

`/api/*` endpoints are gated on bearer token authentication. Set `RY_DASH_TOKEN` to enable access; with no token set, all `/api/*` requests return `503 Server has no RY_DASH_TOKEN configured`. The static SPA shell remains reachable on loopback so the UI can render before a token is provisioned.

A non-loopback bind (`--host 0.0.0.0`, etc.) **requires** `RY_DASH_TOKEN`; the server exits with code 2 otherwise.

```fish
# Generate and store a token
set -Ux RY_DASH_TOKEN (openssl rand -hex 32)

# Or via systemd EnvironmentFile (0600 perms — already wired in the unit)
echo "RY_DASH_TOKEN="(openssl rand -hex 32) > ~/.config/ry-web-dashboard.env
chmod 600 ~/.config/ry-web-dashboard.env
systemctl --user restart ry-web-dashboard.service
```

The shipped unit declares `EnvironmentFile=-%h/.config/ry-web-dashboard.env`, so creating that file and restarting is sufficient — no drop-in needed.

#### Browser sign-in

The dashboard uses an HttpOnly session cookie because `EventSource` (used by the live monitor SSE stream) cannot send `Authorization` headers. The flow:

1. The browser loads the SPA shell on loopback (no auth required for static assets).
2. The first `/api/*` call returns `401`; the frontend shows a sign-in dialog.
3. The user pastes the token; the frontend POSTs `/api/login` which validates with `hmac.compare_digest` and sets an `HttpOnly; SameSite=Strict` cookie.
4. All subsequent fetches (including SSE) carry the cookie automatically.

`POST /api/logout` clears the cookie. Programmatic clients can still use `Authorization: Bearer $RY_DASH_TOKEN` instead of the cookie — the middleware accepts either.

### Access from LAN

The default bind is `127.0.0.1`. To expose on your LAN, you must (1) set `RY_DASH_TOKEN`, (2) override `--host`, and (3) restrict port 9000 at the firewall (see [Firewall](#firewall)).

```fish
echo "RY_DASH_TOKEN="(openssl rand -hex 32) > ~/.config/ry-web-dashboard.env
chmod 600 ~/.config/ry-web-dashboard.env
# then edit the unit / drop-in to change --host 127.0.0.1 → --host 0.0.0.0
```

Then access from any LAN device:

```
http://192.168.50.X:9000
```

CSRF protection requires every POST to carry an `Origin` or `Referer` whose host matches the dashboard's `Host:` header — requests with neither header are refused (`403 Origin or Referer header required`). Security headers are set on all responses (including the SPA shell):

| Header | Value |
|--------|-------|
| Content-Security-Policy | `default-src 'none'; script-src 'self'; style-src 'self'; font-src 'self'; connect-src 'self'; img-src 'self'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'` |
| X-Content-Type-Options | `nosniff` |
| X-Frame-Options | `DENY` |
| Referrer-Policy | `no-referrer` |
| Permissions-Policy | `camera=(), microphone=(), geolocation=(), payment=(), usb=(), interest-cohort=()` |
| Cache-Control | `no-store` (non-SSE API routes), `no-cache` (SPA shell) |

The SPA uses a system-font stack (`ui-monospace`, `ui-sans-serif`) — no external font CDN, no third-party requests from any LAN client that loads the dashboard.

SSE connections are limited to 5 concurrent clients. Concurrent `/api/logs/{target}` requests are limited to 2 (semaphore-gated). POST request bodies are limited to 64 KB. Telemetry uses a dedicated 2-thread executor so SSE fan-out cannot starve aiohttp's default I/O pool.

### Sudoers for unattended operation

Several ry-install modes require sudo (install, diff --fix, verify-runtime). System cleanup (`/api/clean`) uses sudo for `paccache`, `pacman -Rns`, and `journalctl --vacuum-size`. The narrow sudoers entry below covers `/api/clean` only:

```fish
# /etc/sudoers.d/ry-web-dashboard-clean
ryan ALL=(ALL) NOPASSWD: /usr/bin/paccache, /usr/bin/pacman, /usr/bin/journalctl
```

Full ry-install deployment also needs `cp`, `install`, `mkdir`, `chmod`, `chown`, `ln`, `sysctl`, `systemctl`, `mkinitcpio`, `bootctl`, `sdboot-manage`, and possibly more depending on your profile. For a personal workstation the simplest path is permissive sudo:

```fish
# /etc/sudoers.d/ry-install
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
| `/api/login` | POST | none | Exchange `{"token": "..."}` for an HttpOnly session cookie |
| `/api/logout` | POST | none | Clear the session cookie |
| `/api/clean` | POST | token | paccache, orphan removal, journal vacuum `[dry_run]` |
| `/api/install` | POST | token | `--all [--dry-run]` |
| `/api/install-file` | POST | token | `--install-file <path> [--dry-run]` |
| `/api/test-all` | POST | token | `--test-all` |
| `/api/diff-fix` | POST | token | `--diff --fix --force [--dry-run]` |

POST bodies accept `{"dry_run": true}` (default: true for safety). All `/api/*` endpoints **require** `Authorization: Bearer $RY_DASH_TOKEN`; with no token configured, every `/api/*` request returns `503`.

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

The user service unit includes 21 sandboxing directives: `PrivateTmp`, `ProtectSystem=full`, `ProtectControlGroups`, `ProtectKernelModules`, `ProtectKernelTunables`, `ProtectKernelLogs`, `ProtectClock`, `ProtectHostname`, `ProtectProc=invisible`, `ProcSubset=pid`, `RestrictSUIDSGID`, `RestrictNamespaces`, `RestrictAddressFamilies=AF_UNIX AF_INET AF_INET6 AF_NETLINK`, `LockPersonality`, `RestrictRealtime`, `MemoryDenyWriteExecute`, `SystemCallArchitectures=native`, `SystemCallFilter=@system-service ~@privileged @resources`, `UMask=0077`, `NoNewPrivileges=no`. Verify with:

```fish
systemd-analyze security ry-web-dashboard.service
```

`ProtectSystem=full` makes `/usr`, `/boot`, and `/efi` read-only while leaving `/etc` writable for ry-install. `ProtectSystem=strict` and `ProtectHome=yes` are intentionally omitted because ry-install writes to `/etc` and reads from `~/ry-install/`. `NoNewPrivileges` is explicitly set to `no` because ry-install invokes `sudo`.

## Firewall

When binding to a non-loopback address, restrict port 9000 to the LAN at the firewall.

**nftables:**

```fish
sudo nft add rule inet filter input tcp dport 9000 ip saddr != 192.168.50.0/24 drop
sudo nft add rule inet filter input tcp dport 9000 ip saddr 192.168.50.0/24 accept
```

**ufw:**

```fish
sudo ufw allow from 192.168.50.0/24 to any port 9000 proto tcp
sudo ufw deny 9000/tcp
```

**firewalld:**

```fish
sudo firewall-cmd --permanent --zone=internal --add-port=9000/tcp
sudo firewall-cmd --permanent --zone=public  --remove-port=9000/tcp
sudo firewall-cmd --reload
```

Replace `192.168.50.0/24` with your actual LAN range.

## License

[MIT](LICENSE)
