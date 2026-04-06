ry-web-dashboard changelog


1.5.0 (2026-04-05)

- sync: align dashboard with ry-install v3.46.0. Remove all
    references to non-existent ry-install CLI flags.
- remove(services): drop amdgpu-performance from monitored
    services (removed from ry-install in v3.38). Current set:
    cpupower-epp, fstrim.timer, NetworkManager.
- feat(check): replace Diagnose tab with Check tab. Calls
    --check --force, displays exit-code badge (0=clean,
    3=prereq fail, 10=drift).
- feat(drift): add --diff --fix support with dry-run and
    live modes. Confirm dialog guards destructive action.
- refactor(logs): replace --logs (non-existent) with direct
    journalctl queries per target. Targets: system, gpu, wifi,
    boot, audio, usb, kernel, analyze, last, all.
- refactor(clean): replace --clean (non-existent) with direct
    paccache -rvk2, pacman -Rns orphans, journalctl
    --vacuum-size=100M.
- remove(actions): drop Profile and Stress buttons (no
    ry-install --profile or --stress flags).
- remove(backend): drop unused _extract_json_suffix helper.
- feat(info): add services list to /api/info response.
- fix(layout): move index.html and app.js into static/
    subdirectory to match STATIC_DIR = SCRIPT_DIR / "static".
- fix(service): Documentation URL now points to
    ry-web-dashboard repo, not ry-install.
- docs: sync README with codebase — add project layout,
    monitored services list, log targets, git clone install.
    Architecture diagram updated for static/ directory.

1.4.0 (2026-04-05)

- feat(auth): add bearer token auth via RY_DASH_TOKEN env var.
- feat(sse): add SSE connection limit (max 5 concurrent).
- feat(lifecycle): add graceful shutdown handler for SSE cleanup.
- security(systemd): add 12 sandboxing directives to service
    unit. Add After=network-online.target.
- security(csp): expand CSP with base-uri, form-action,
    frame-ancestors.
- security(headers): add Permissions-Policy, Cache-Control.
- security(csrf): add Referer fallback when Origin absent.
- security(post): set client_max_size=64KB on POST bodies.
- fix(logs): strict allowlist for /api/logs target.
- perf(services): convert _service_states to async parallel
    via asyncio.gather.
- perf(telemetry): cache static sysfs values (kernel,
    vram_total, zram) at startup.
- refactor: move MANAGED_FILES global to app dict.
- fix(diagnose): fix h_diagnose JSON index mismatch and
    dead code.
- feat(cli): add --version flag.
- feat(logging): add access log format.
- docs: add add_static risk acceptance comment.
- refactor: remove unused subprocess import.
- fix(setup): use Fish argparse, idempotent pip install.
- perf(frontend): reuse spark DOM elements in app.js.

1.3.0 (2026-02-27)

- Initial release.
- feat: live sysfs telemetry via SSE (2s interval).
- security: CSRF protection, CSP, security headers.
- security: filtered subprocess environment.
- feat: systemd user service with drop-in override.
- feat: dark/light theme with prefers-color-scheme.
- feat: Fish setup script.
