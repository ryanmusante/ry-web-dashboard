ry-web-dashboard changelog


1.5.0 (2026-04-05)

- sync: align with ry-install v3.46.0, remove stale CLI refs.
- remove: drop amdgpu-performance from monitored services.
- feat: replace Diagnose tab with Check tab (exit-code badge).
- feat: add --diff --fix support with dry-run and live modes.
- refactor: replace --logs with direct journalctl queries.
- refactor: replace --clean with direct paccache/pacman/journalctl.
- remove: drop Profile and Stress buttons.
- feat: add services list to /api/info response.
- fix: move index.html and app.js into static/ subdirectory.
- fix: Documentation URL points to ry-web-dashboard repo.
- docs: sync README with codebase.

1.4.0 (2026-04-05)

- feat: bearer token auth via RY_DASH_TOKEN env var.
- feat: SSE connection limit (max 5 concurrent).
- feat: graceful shutdown handler for SSE cleanup.
- security: add 12 sandboxing directives to systemd unit.
- security: expand CSP, add Permissions-Policy, Cache-Control.
- fix: strict allowlist for /api/logs target.
- perf: async parallel service state checks.
- perf: cache static sysfs values at startup.
- feat: add --version flag and access log format.
- fix: Fish argparse in setup, idempotent pip install.

1.3.0 (2026-02-27)

- Initial release.
- Live sysfs telemetry via SSE (2s interval).
- CSRF protection, CSP, security headers.
- Systemd user service with drop-in override.
- Dark/light theme with prefers-color-scheme.
