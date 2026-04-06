#!/usr/bin/env python3
"""
ry-web-dashboard v1.5.0 — Web dashboard for ry-install
2026-04-05 | MIT License

Async HTTP server wrapping ry-install.fish with live sysfs telemetry via SSE.

Usage: python3 ry-web-dashboard.py [--host 0.0.0.0] [--port 9000] [--script PATH]
"""

from __future__ import annotations

import argparse
import asyncio
import glob
import json
import logging
import os
import re
import sys
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from aiohttp import web

# ── Configuration ──────────────────────────────────────────────────────────

SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_PORT = 9000
DEFAULT_HOST = "0.0.0.0"
DEFAULT_SCRIPT = str(SCRIPT_DIR / "ry-install.fish")
STATIC_DIR = SCRIPT_DIR / "static"

VERSION = "1.5.0"
SSE_INTERVAL = 2
COMMAND_TIMEOUT = 120
LOG_TARGETS = frozenset((
    "system", "gpu", "wifi", "boot", "audio", "usb", "kernel",
    "analyze", "last", "all",
))
# journalctl filters for log targets (ry-install has no --logs flag)
_LOG_CMDS: dict[str, list[str]] = {
    "system":  ["journalctl", "-b", "--priority=warning", "--no-pager", "-n", "200"],
    "gpu":     ["journalctl", "-b", "-k", "--grep=amdgpu|drm|gpu", "--no-pager", "-n", "200"],
    "wifi":    ["journalctl", "-b", "-u", "iwd", "-u", "NetworkManager", "-u", "wpa_supplicant", "--no-pager", "-n", "200"],
    "boot":    ["journalctl", "-b", "-o", "short-monotonic", "--no-pager", "-n", "200"],
    "audio":   ["journalctl", "-b", "-u", "pipewire", "-u", "wireplumber", "--no-pager", "-n", "200"],
    "usb":     ["journalctl", "-b", "-k", "--grep=usb", "--no-pager", "-n", "200"],
    "kernel":  ["journalctl", "-b", "-k", "--no-pager", "-n", "200"],
    "analyze": ["systemd-analyze", "blame"],
    "last":    ["journalctl", "-b", "-1", "--priority=warning", "--no-pager", "-n", "200"],
    "all":     ["journalctl", "-b", "--no-pager", "-n", "500"],
}
SERVICES = ("cpupower-epp", "fstrim.timer", "NetworkManager")
MAX_SSE_CLIENTS = 5
_sse_count = 0
_static_cache: dict[str, Any] = {}

AUTH_TOKEN = os.environ.get("RY_DASH_TOKEN", "")

# Env vars safe to pass to subprocesses
_SAFE_ENV_KEYS = frozenset((
    "PATH", "HOME", "USER", "LOGNAME", "LANG", "LC_ALL", "LC_CTYPE",
    "XDG_RUNTIME_DIR", "XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_CACHE_HOME",
    "SHELL", "DBUS_SESSION_BUS_ADDRESS",
))

CSP = (
    "default-src 'none'; "
    "script-src 'self'; "
    "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
    "font-src https://fonts.gstatic.com; "
    "connect-src 'self'; "
    "img-src 'self'; "
    "base-uri 'none'; "
    "form-action 'none'; "
    "frame-ancestors 'none'"
)

log = logging.getLogger("ry-web-dashboard")


# ── Middleware ─────────────────────────────────────────────────────────────

@web.middleware
async def auth_middleware(request: web.Request, handler: Any) -> web.StreamResponse:
    """Bearer token authentication for API endpoints."""
    if not AUTH_TOKEN:
        return await handler(request)
    if request.path.startswith("/api/"):
        token = request.headers.get("Authorization", "").removeprefix("Bearer ")
        if token != AUTH_TOKEN:
            return web.json_response({"error": "Unauthorized"}, status=401)
    return await handler(request)


@web.middleware
async def security_middleware(request: web.Request, handler: Any) -> web.StreamResponse:
    """CSRF check on POST + security headers on all responses."""
    if request.method == "POST":
        origin = request.headers.get("Origin")
        referer = request.headers.get("Referer")
        if origin:
            parsed = urlparse(origin)
            host_hdr = request.headers.get("Host", "")
            expected = f"{parsed.hostname}:{parsed.port}" if parsed.port else parsed.hostname
            if host_hdr not in (expected, f"{parsed.hostname}:{request.url.port}"):
                log.warning("action=csrf_block origin=%s host=%s", origin, host_hdr)
                return web.json_response({"error": "Origin mismatch"}, status=403)
        elif referer:
            parsed = urlparse(referer)
            host_hdr = request.headers.get("Host", "")
            expected = f"{parsed.hostname}:{parsed.port}" if parsed.port else parsed.hostname
            if host_hdr not in (expected, f"{parsed.hostname}:{request.url.port}"):
                log.warning("action=csrf_block referer=%s host=%s", referer, host_hdr)
                return web.json_response({"error": "Referer mismatch"}, status=403)

    resp = await handler(request)

    if isinstance(resp, web.StreamResponse) and not isinstance(resp, web.FileResponse):
        resp.headers["Content-Security-Policy"] = CSP
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["X-Frame-Options"] = "DENY"
    resp.headers["Referrer-Policy"] = "no-referrer"
    resp.headers["Permissions-Policy"] = (
        "camera=(), microphone=(), geolocation=(), "
        "payment=(), usb=(), interest-cohort=()"
    )
    if request.path.startswith("/api/") and "/stream" not in request.path:
        resp.headers["Cache-Control"] = "no-store"

    return resp


# ── sysfs readers ──────────────────────────────────────────────────────────

def _sysfs(path: str, fallback: str = "") -> str:
    try:
        return Path(path).read_text().strip()
    except (OSError, ValueError):
        return fallback


def _sysfs_int(path: str, fallback: int = 0) -> int:
    try:
        return int(_sysfs(path))
    except (ValueError, TypeError):
        return fallback


def _glob_read(pattern: str, fallback: str = "") -> str:
    for p in sorted(glob.glob(pattern)):
        try:
            return Path(p).read_text().strip()
        except OSError:
            continue
    return fallback


def _glob_int(pattern: str, fallback: int = 0) -> int:
    try:
        return int(_glob_read(pattern))
    except (ValueError, TypeError):
        return fallback


def _hwmon_temp(chip: str) -> float | None:
    for hwmon in sorted(glob.glob("/sys/class/hwmon/hwmon*")):
        try:
            if Path(f"{hwmon}/name").read_text().strip() != chip:
                continue
            return int(Path(f"{hwmon}/temp1_input").read_text().strip()) / 1000.0
        except (OSError, ValueError):
            pass
    return None


def _gpu_temp() -> float | None:
    for hwmon in sorted(glob.glob("/sys/class/drm/card*/device/hwmon/hwmon*")):
        try:
            return int(Path(f"{hwmon}/temp1_input").read_text().strip()) / 1000.0
        except (OSError, ValueError):
            pass
    return None


def _power_watts(pattern: str) -> float | None:
    for p in sorted(glob.glob(pattern)):
        try:
            return int(Path(p).read_text().strip()) / 1_000_000.0
        except (OSError, ValueError):
            continue
    return None


def _net_interfaces() -> list[dict[str, Any]]:
    base = Path("/sys/class/net")
    if not base.exists():
        return []
    out = []
    for d in sorted(base.iterdir()):
        if d.name == "lo":
            continue
        speed_raw = _sysfs(str(d / "speed"))
        speed = None
        try:
            s = int(speed_raw)
            if s > 0:
                speed = s
        except (ValueError, TypeError):
            pass
        out.append({
            "name": d.name,
            "state": _sysfs(str(d / "operstate"), "unknown"),
            "wireless": (d / "wireless").is_dir(),
            "speed_mbps": speed,
        })
    return out


async def _service_states() -> dict[str, str]:
    """Check systemd service states in parallel."""
    async def _check(svc: str) -> tuple[str, str]:
        try:
            proc = await asyncio.create_subprocess_exec(
                "systemctl", "is-active", svc,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
                env=_filtered_env(),
            )
            out, _ = await asyncio.wait_for(proc.communicate(), timeout=5)
            return svc, out.decode().strip() or "unknown"
        except Exception:
            return svc, "unknown"
    results = await asyncio.gather(*[_check(s) for s in SERVICES])
    return dict(results)


def _zram_info() -> dict[str, Any]:
    disksize = _sysfs_int("/sys/block/zram0/disksize")
    if disksize <= 0:
        return {"active": False, "algo": None, "size_gb": 0}
    algo_raw = _sysfs("/sys/block/zram0/comp_algorithm")
    m = re.search(r"\[(\w+)]", algo_raw)
    return {"active": True, "algo": m.group(1) if m else algo_raw, "size_gb": round(disksize / 1_073_741_824, 1)}


def _disk_pct() -> int | None:
    try:
        st = os.statvfs("/")
        total = st.f_blocks * st.f_frsize
        avail = st.f_bavail * st.f_frsize
        return round((1 - avail / total) * 100) if total else None
    except OSError:
        return None


def gather_telemetry() -> dict[str, Any]:
    """Full system telemetry from sysfs — zero subprocesses."""
    # Cache values that don't change at runtime
    if not _static_cache:
        _static_cache["kernel"] = _sysfs("/proc/sys/kernel/osrelease")
        _static_cache["vram_total"] = _glob_int("/sys/class/drm/card*/device/mem_info_vram_total") // 1_048_576
        _static_cache["zram"] = _zram_info()

    cpu_t = _hwmon_temp("k10temp") or _hwmon_temp("zenpower")
    gpu_t = _gpu_temp()
    pkg_w = _power_watts("/sys/class/hwmon/hwmon*/power1_average")
    gpu_w = _power_watts("/sys/class/drm/card*/device/hwmon/hwmon*/power1_average")
    cpu_freq = _sysfs_int("/sys/devices/system/cpu/cpu0/cpufreq/scaling_cur_freq")

    mem: dict[str, int] = {}
    try:
        with open("/proc/meminfo") as f:
            for line in f:
                parts = line.split()
                if len(parts) >= 2:
                    key = parts[0].rstrip(":")
                    if key in ("MemTotal", "MemAvailable", "SwapTotal", "SwapFree"):
                        mem[key] = int(parts[1])
    except OSError:
        pass

    mt = mem.get("MemTotal", 0) // 1024
    ma = mem.get("MemAvailable", 0) // 1024
    st = mem.get("SwapTotal", 0) // 1024
    sf = mem.get("SwapFree", 0) // 1024

    return {
        "ts": time.time(),
        "cpu": {
            "gov": _sysfs("/sys/devices/system/cpu/cpu0/cpufreq/scaling_governor"),
            "epp": _sysfs("/sys/devices/system/cpu/cpu0/cpufreq/energy_performance_preference"),
            "temp": round(cpu_t, 1) if cpu_t is not None else None,
            "freq": cpu_freq // 1000 if cpu_freq else None,
        },
        "gpu": {
            "perf": _glob_read("/sys/class/drm/card*/device/power_dpm_force_performance_level"),
            "busy": _glob_int("/sys/class/drm/card*/device/gpu_busy_percent"),
            "temp": round(gpu_t, 1) if gpu_t is not None else None,
            "vram_used": _glob_int("/sys/class/drm/card*/device/mem_info_vram_used") // 1_048_576,
            "vram_total": _static_cache.get("vram_total", 0),
        },
        "mem": {"total": mt, "used": mt - ma, "avail": ma},
        "swap": {"total": st, "used": st - sf},
        "power": {"pkg": round(pkg_w, 1) if pkg_w else None, "gpu": round(gpu_w, 1) if gpu_w else None},
        "disk": _disk_pct(),
        "net": _net_interfaces(),
        "ntsync": Path("/dev/ntsync").is_char_device(),
        "zram": _static_cache.get("zram", {"active": False, "algo": None, "size_gb": 0}),
        "load": _sysfs("/proc/loadavg").split()[:3],
        "kernel": _static_cache.get("kernel", ""),
    }


# ── Subprocess runner ──────────────────────────────────────────────────────

def _filtered_env() -> dict[str, str]:
    """Return only safe env vars + overrides for ry-install."""
    env = {k: v for k, v in os.environ.items() if k in _SAFE_ENV_KEYS}
    env["NO_COLOR"] = "1"
    env["TERM"] = "dumb"
    return env


async def run_cmd(app: web.Application, *args: str, timeout: int = COMMAND_TIMEOUT) -> tuple[int, str, str]:
    script = app["script"]
    try:
        proc = await asyncio.create_subprocess_exec(
            "fish", script, *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=_filtered_env(),
        )
        out, err = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        rc = proc.returncode or 0
        log.debug("action=run_cmd args=%s rc=%d", args, rc)
        return rc, out.decode(errors="replace"), err.decode(errors="replace")
    except asyncio.TimeoutError:
        try:
            proc.kill()  # type: ignore[union-attr]
            await proc.wait()  # type: ignore[union-attr]
        except Exception:
            pass
        log.warning("action=run_cmd_timeout args=%s timeout=%d", args, timeout)
        return 124, "", f"Timed out after {timeout}s"
    except FileNotFoundError:
        log.error("action=run_cmd_notfound script=%s", script)
        return 127, "", f"Not found: {script}"
    except Exception as e:
        log.error("action=run_cmd_error args=%s err=%s", args, e)
        return 1, "", str(e)


# ── Handlers ───────────────────────────────────────────────────────────────

def _resp(rc: int, stdout: str, stderr: str, **kw: Any) -> web.Response:
    return web.json_response({"output": stdout, "stderr": stderr, "rc": rc, **kw})


async def h_telemetry(req: web.Request) -> web.Response:
    loop = asyncio.get_event_loop()
    data = await loop.run_in_executor(None, gather_telemetry)
    data["svc"] = await _service_states()
    return web.json_response(data)


async def h_sse(req: web.Request) -> web.StreamResponse:
    global _sse_count
    if _sse_count >= MAX_SSE_CLIENTS:
        return web.json_response({"error": "Too many SSE clients"}, status=503)
    _sse_count += 1
    try:
        resp = web.StreamResponse(headers={
            "Content-Type": "text/event-stream",
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        })
        await resp.prepare(req)
        loop = asyncio.get_event_loop()
        svc_cache: dict[str, str] = {}
        svc_ts = 0.0
        log.info("action=sse_connect client=%s count=%d", req.remote, _sse_count)
        while not req.app.get("shutting_down"):
            data = await loop.run_in_executor(None, gather_telemetry)
            now = time.time()
            if now - svc_ts > 10:
                svc_cache = await _service_states()
                svc_ts = now
            data["svc"] = svc_cache
            await resp.write(f"data: {json.dumps(data)}\n\n".encode())
            await asyncio.sleep(SSE_INTERVAL)
    except (ConnectionResetError, ConnectionAbortedError, asyncio.CancelledError):
        pass
    finally:
        _sse_count -= 1
        log.info("action=sse_disconnect client=%s count=%d", req.remote, _sse_count)
    return resp


async def h_check(req: web.Request) -> web.Response:
    rc, out, err = await run_cmd(req.app, "--check", "--force")
    # --check exit codes: 0=clean, 3=prereq fail, 10=drift
    status_map = {0: "clean", 3: "prereq_fail", 10: "drift"}
    return web.json_response({
        "output": out,
        "stderr": err,
        "rc": rc,
        "status": status_map.get(rc, "error"),
    })


async def h_diff(req: web.Request) -> web.Response:
    return _resp(*await run_cmd(req.app, "--diff"))

async def h_verify_static(req: web.Request) -> web.Response:
    return _resp(*await run_cmd(req.app, "--verify-static"))

async def h_verify_runtime(req: web.Request) -> web.Response:
    return _resp(*await run_cmd(req.app, "--verify-runtime"))

async def h_lint(req: web.Request) -> web.Response:
    return _resp(*await run_cmd(req.app, "--lint"))

async def h_changelog(req: web.Request) -> web.Response:
    script_path = Path(req.app["script"])
    changelog = script_path.parent / "CHANGELOG.md"
    try:
        content = changelog.read_text()
        return _resp(0, content, "")
    except OSError:
        return _resp(1, "", f"CHANGELOG.md not found at {changelog}")


async def h_logs(req: web.Request) -> web.Response:
    target = req.match_info["target"]
    if target not in LOG_TARGETS:
        return web.json_response({"error": f"Invalid target: {target}"}, status=400)
    cmd = _LOG_CMDS.get(target)
    if not cmd:
        return web.json_response({"error": f"No command for target: {target}"}, status=400)
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=_filtered_env(),
        )
        out, err = await asyncio.wait_for(proc.communicate(), timeout=30)
        rc = proc.returncode or 0
        return _resp(rc, out.decode(errors="replace"), err.decode(errors="replace"), target=target)
    except asyncio.TimeoutError:
        return _resp(124, "", f"Timed out fetching {target} logs")
    except Exception as e:
        return _resp(1, "", str(e))


async def _body(req: web.Request) -> dict[str, Any]:
    if req.content_type == "application/json" and req.can_read_body:
        try:
            return await req.json()
        except (json.JSONDecodeError, ValueError):
            pass
    return {}


async def h_clean(req: web.Request) -> web.Response:
    async with req.app["lock"]:
        b = await _body(req)
        dry = b.get("dry_run", True)
        log.info("action=clean dry_run=%s", dry)
        parts: list[str] = []
        env = _filtered_env()

        async def _run(label: str, *cmd: str) -> None:
            try:
                proc = await asyncio.create_subprocess_exec(
                    *cmd,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    env=env,
                )
                out, err = await asyncio.wait_for(proc.communicate(), timeout=60)
                parts.append(f"── {label} ──\n{out.decode(errors='replace').strip()}")
                if err.decode(errors='replace').strip():
                    parts.append(err.decode(errors='replace').strip())
            except Exception as e:
                parts.append(f"── {label} ──\n[ERR] {e}")

        if dry:
            await _run("Package cache (dry)", "paccache", "-dvk2")
            # Check for orphans
            await _run("Orphans", "pacman", "-Qtdq")
            await _run("Journal size", "journalctl", "--disk-usage")
        else:
            await _run("Package cache", "sudo", "-n", "paccache", "-rvk2")
            # Remove orphans if any
            try:
                proc = await asyncio.create_subprocess_exec(
                    "pacman", "-Qtdq",
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.DEVNULL,
                    env=env,
                )
                out, _ = await asyncio.wait_for(proc.communicate(), timeout=10)
                orphans = out.decode().strip()
                if orphans:
                    await _run("Remove orphans", "sudo", "-n", "pacman", "-Rns", "--noconfirm",
                               *orphans.splitlines())
                else:
                    parts.append("── Orphans ──\nNo orphans found")
            except Exception:
                parts.append("── Orphans ──\nNo orphans found")
            await _run("Journal vacuum", "sudo", "-n", "journalctl", "--vacuum-size=100M")

        return _resp(0, "\n\n".join(parts), "", dry_run=dry)


async def h_install(req: web.Request) -> web.Response:
    async with req.app["lock"]:
        b = await _body(req)
        dry = b.get("dry_run", True)
        args = ["--all"] + (["--dry-run"] if dry else [])
        log.info("action=install dry_run=%s", dry)
        return _resp(*await run_cmd(req.app, *args, timeout=300), dry_run=dry)


async def h_install_file(req: web.Request) -> web.Response:
    async with req.app["lock"]:
        b = await _body(req)
        fp = b.get("path", "")
        dry = b.get("dry_run", True)
        if not fp or fp not in req.app["managed_files"]:
            return web.json_response({"error": f"Not a managed file: {fp}"}, status=400)
        args = ["--install-file", fp] + (["--dry-run"] if dry else [])
        log.info("action=install_file path=%s dry_run=%s", fp, dry)
        return _resp(*await run_cmd(req.app, *args), dry_run=dry, path=fp)


async def h_test_all(req: web.Request) -> web.Response:
    async with req.app["lock"]:
        log.info("action=test_all")
        return _resp(*await run_cmd(req.app, "--test-all", timeout=300))


async def h_diff_fix(req: web.Request) -> web.Response:
    async with req.app["lock"]:
        b = await _body(req)
        dry = b.get("dry_run", True)
        args = ["--diff", "--fix", "--force"] + (["--dry-run"] if dry else [])
        log.info("action=diff_fix dry_run=%s", dry)
        return _resp(*await run_cmd(req.app, *args, timeout=180), dry_run=dry)


async def h_managed(req: web.Request) -> web.Response:
    return web.json_response({"files": req.app["managed_files"]})


async def h_info(req: web.Request) -> web.Response:
    _, out, _ = await run_cmd(req.app, "--version")
    return web.json_response({
        "dashboard": VERSION,
        "ry_install": out.strip(),
        "log_targets": sorted(LOG_TARGETS),
        "services": list(SERVICES),
        "managed_files_count": len(req.app["managed_files"]),
    })


async def h_index(req: web.Request) -> web.FileResponse:
    return web.FileResponse(STATIC_DIR / "index.html")


# ── App factory ────────────────────────────────────────────────────────────

def extract_managed_files(path: str) -> list[str]:
    try:
        content = Path(path).read_text()
    except OSError:
        return []
    files: list[str] = []
    for var in ("SYSTEM_DESTINATIONS", "USER_DESTINATIONS", "SERVICE_DESTINATIONS"):
        in_block = False
        for line in content.splitlines():
            if f"set -g {var}" in line:
                in_block = True
            if in_block:
                # Capture quoted paths: "/etc/kernel/cmdline"
                files.extend(m.group(1) for m in re.finditer(r'"([^"]+)"', line))
                # Capture unquoted paths: /etc/kernel/cmdline (bare tokens starting with /)
                stripped = line.strip().rstrip("\\").strip()
                if stripped.startswith("/") and '"' not in stripped:
                    files.append(stripped)
                if "\\" not in line:
                    in_block = False
    return files


def create_app(script: str) -> web.Application:
    app = web.Application(
        middlewares=[auth_middleware, security_middleware],
        client_max_size=1024 * 64,
    )
    app["script"] = script
    app["lock"] = asyncio.Lock()

    async def on_shutdown(a: web.Application) -> None:
        a["shutting_down"] = True

    app.on_shutdown.append(on_shutdown)

    r = app.router
    r.add_get("/api/telemetry", h_telemetry)
    r.add_get("/api/telemetry/stream", h_sse)
    r.add_get("/api/check", h_check)
    r.add_get("/api/diff", h_diff)
    r.add_get("/api/verify/static", h_verify_static)
    r.add_get("/api/verify/runtime", h_verify_runtime)
    r.add_get("/api/lint", h_lint)
    r.add_get("/api/logs/{target}", h_logs)
    r.add_get("/api/changelog", h_changelog)
    r.add_get("/api/managed-files", h_managed)
    r.add_get("/api/info", h_info)
    r.add_post("/api/clean", h_clean)
    r.add_post("/api/install", h_install)
    r.add_post("/api/install-file", h_install_file)
    r.add_post("/api/test-all", h_test_all)
    r.add_post("/api/diff-fix", h_diff_fix)
    if STATIC_DIR.exists():
        # NOTE: add_static() is for development only per aiohttp docs.
        # Past CVEs (GHSA-5h86-8mv2-jq9f) only affected add_static users.
        # Acceptable risk for LAN-only personal workstation dashboard.
        r.add_static("/static", STATIC_DIR, show_index=False)
    r.add_get("/", h_index)
    r.add_get("/{tail:(?!api/).*}", h_index)
    return app


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s level=%(levelname)s %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
        stream=sys.stderr,
    )
    p = argparse.ArgumentParser(description="ry-web-dashboard — web UI for ry-install")
    p.add_argument("--host", default=DEFAULT_HOST)
    p.add_argument("--port", type=int, default=DEFAULT_PORT)
    p.add_argument("--script", default=DEFAULT_SCRIPT)
    p.add_argument("--version", action="version", version=f"ry-web-dashboard {VERSION}")
    a = p.parse_args()
    if not Path(a.script).exists():
        log.error("action=startup err=script_not_found path=%s", a.script)
        sys.exit(1)
    app = create_app(a.script)
    app["managed_files"] = extract_managed_files(a.script)
    if a.host != "127.0.0.1":
        log.warning("action=startup bind=%s note=LAN-accessible%s", a.host,
                     ",no-auth" if not AUTH_TOKEN else "")
    log.info("action=startup version=%s host=%s port=%d managed_files=%d",
             VERSION, a.host, a.port, len(app["managed_files"]))
    web.run_app(app, host=a.host, port=a.port, print=None,
                access_log_format='%a %t "%r" %s %b %Tf')


if __name__ == "__main__":
    main()
