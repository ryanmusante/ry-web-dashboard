# Changelog

All notable changes to this project will be documented in this file.
The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.6.1] - 2026-04-06

### Security

- **CSP applied unconditionally** — `security_middleware` no longer skips
  `Content-Security-Policy` on `FileResponse`, so the SPA shell and every
  `/static/*` asset now ship the full CSP.
- **Constant-time token compare** — bearer token comparison switched from
  `!=` to `hmac.compare_digest`.
- **`/api/login` cookie flow** — `EventSource` cannot send `Authorization`
  headers, so the dashboard now exchanges a token for an `HttpOnly;
  SameSite=Strict` session cookie via `POST /api/login`. The middleware
  accepts either the bearer header or the cookie; programmatic clients are
  unaffected. The frontend auto-prompts for the token on the first 401.
- **CSP tightened** — dropped `fonts.googleapis.com` and `fonts.gstatic.com`
  (already unused) and `'unsafe-inline'` from `style-src`. All inline
  `style="..."` attributes refactored to classes in `static/style.css`.
- **`extract_managed_files` injection fix** — `--script` value is now passed
  to `fish -c` via the `RY_SCRIPT` env var instead of f-string interpolation,
  closing a local code-injection vector through path metacharacters.
- **Sandbox hardening** — added 8 directives to the systemd unit:
  `ProtectProc=invisible`, `ProcSubset=pid`, `RestrictNamespaces=yes`,
  `RestrictAddressFamilies=AF_UNIX AF_INET AF_INET6 AF_NETLINK`,
  `MemoryDenyWriteExecute=yes`,
  `SystemCallFilter=@system-service ~@privileged @resources`, `UMask=0077`.
  Total now 21 directives.

### Fixed

- `run_cmd` no longer masks `NameError` if `create_subprocess_exec` raises
  before `proc` is bound; nested `try` ensures the timeout handler only sees
  a defined `proc`. Bare `except` replaced with
  `(ProcessLookupError, OSError)`.
- `run_cmd` returncode no longer collapses `None` → `0`; unknown state is
  reported as `-1`.
- `_body` returns `400 Malformed JSON` instead of silently falling back to
  `{}` and proceeding with default `dry_run=True`.
- `h_clean` tracks per-step `worst_rc` and returns the maximum non-zero exit
  code; previously every cleanup result reported `rc=0` regardless of
  sub-command failure. `pacman -Qtdq` exit `1` (no orphans) is now treated
  as success.
- `h_clean` orphan removal batched in chunks of 100 to stay below `ARG_MAX`
  on pathologically dirty systems.
- `h_logs` dead-code fast-fail branch removed (was reaching into the
  semaphore's private `_value`).
- LOOPBACK detection switched to `ipaddress.ip_address(...).is_loopback`,
  correctly recognising the entire `127.0.0.0/8` range and `::1`.
- `h_index` sets `Cache-Control: no-cache` so the SPA shell revalidates
  after `app.js` updates.
- `static/app.js` SSE reconnect now uses exponential backoff
  (5 → 10 → 20 → 40 → 60 s) instead of a fixed 5 s loop.
- `static/app.js` JSON parse failures in the SSE stream are now logged via
  `console.warn` instead of silently swallowed.
- `static/app.js` managed-files list reloads on every Actions tab visit
  (was: latched to first load).
- `setup.fish` prefers `pacman -S --needed python-aiohttp` on systems with
  pacman, falls back to pip; both `2>/dev/null` redirects removed so real
  failure causes are visible.

### Docs

- README adds **Browser sign-in** subsection documenting the `/api/login`
  cookie flow.
- README adds **Authentication** entry to the table of contents.
- README sudoers section split into narrow (`/api/clean` only) and
  permissive variants; `cat` removed (not used).
- README CSP table updated to match the tightened code (no fonts, no
  `'unsafe-inline'`).
- README systemd hardening section lists all 21 directives.
- README project layout drops stale "(747 lines)" annotation and lists the
  new `static/style.css` file.
- CHANGELOG restructured to GitHub-flavoured Markdown / Keep-a-Changelog
  format.

## [1.6.0] - 2026-04-06

### Security

- `auth_middleware` is fail-closed: `/api/*` returns `503` when
  `RY_DASH_TOKEN` is unset (was: open).
- `DEFAULT_HOST` changed from `0.0.0.0` to `127.0.0.1`.
- Server refuses to start on a non-loopback bind without `RY_DASH_TOKEN`
  (exits with code 2).
- CSRF middleware refuses POST when neither `Origin` nor `Referer` is
  present (was: allowed).
- systemd unit binds `127.0.0.1`, declares `EnvironmentFile` for the token,
  adds `ProtectSystem=full`.
- `setup.fish` drop-in binds `127.0.0.1`.
- `index.html` drops `fonts.googleapis.com` / `fonts.gstatic.com` — system
  font stack only, no third-party requests. *(Note: CSP string was not
  updated in 1.6.0; corrected in 1.6.1.)*

### Fixed

- `h_install_file` resolves the canonical path before the managed-files
  membership check (defeats symlink / relative-path bypass).
- `extract_managed_files` invokes `fish -c` to expand `$SYSTEM_DESTINATIONS`
  et al. instead of regex-parsing the source.
- `h_changelog` pinned to `SCRIPT_DIR/CHANGELOG.md` (was: derived from
  `--script` parent, attacker-controllable).
- `_hwmon_temp` / `_gpu_temp` iterate `temp*_label` for `Tdie`/`Tctl`/
  `edge`/`junction`; fall back to `temp1_input`.
- `/proc/meminfo` opened with `encoding="utf-8"`.
- `setup.fish` pip install adds `--user`.

### Performance

- Dedicated `ThreadPoolExecutor(max_workers=2)` for telemetry — SSE fan-out
  can no longer starve aiohttp's default I/O pool.
- `h_logs` gated on `asyncio.Semaphore(2)` to bound concurrent `journalctl`
  spawns.

### Docs

- README firewall section adds `nft` / `ufw` / `firewalld` LAN-restriction
  examples.
- README systemd hardening lists 13 directives, explains
  `ProtectSystem=full` rationale.
- README authentication section reflects fail-closed semantics; LAN access
  requires a token.

## [1.5.0] - 2026-04-05

### Added

- `/api/info` response now includes the monitored services list.

### Changed

- Sync with ry-install v3.46.0; stale CLI references removed.
- Diagnose tab replaced with **Check** tab (exit-code badge).
- `--diff --fix` support added with both dry-run and live modes.
- `--logs` invocation replaced with direct `journalctl` queries.
- `--clean` invocation replaced with direct `paccache` / `pacman` /
  `journalctl`.

### Removed

- `amdgpu-performance` dropped from monitored services.
- Profile and Stress buttons removed.

### Fixed

- `index.html` and `app.js` moved into `static/` subdirectory.
- Documentation URL points to the ry-web-dashboard repo.

## [1.4.0] - 2026-04-05

### Added

- Bearer token auth via `RY_DASH_TOKEN` env var.
- SSE connection limit (max 5 concurrent).
- Graceful shutdown handler for SSE cleanup.
- 12 sandboxing directives on the systemd unit.
- Expanded CSP, `Permissions-Policy`, `Cache-Control` headers.
- `--version` flag and access-log format.

### Fixed

- Strict allowlist for `/api/logs` target.
- Async parallel service-state checks.
- Static sysfs values cached at startup.
- Fish `argparse` in `setup.fish`; idempotent pip install.

## [1.3.0] - 2026-02-27

### Added

- Initial release.
- Live sysfs telemetry via SSE (2 s interval).
- CSRF protection, CSP, security headers.
- systemd user service with drop-in override.
- Dark / light theme with `prefers-color-scheme`.
