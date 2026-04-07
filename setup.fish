#!/usr/bin/env fish
# ry-web-dashboard setup — installs dependencies and configures systemd user service
# Usage: fish setup.fish [--script /path/to/ry-install.fish]

argparse 'script=' 'h/help' -- $argv
or begin
    echo "Usage: fish setup.fish [--script /path/to/ry-install.fish]" >&2
    exit 2
end
if set -q _flag_help
    echo "Usage: fish setup.fish [--script /path/to/ry-install.fish]"
    exit 0
end
set -l script_path "$_flag_script"

set -l dash_dir (status dirname)
set -l svc_dir "$HOME/.config/systemd/user"

echo "ry-web-dashboard setup"
echo "────────────────────"

# 1. Install aiohttp (prefer distro package on Arch/CachyOS, fall back to pip)
if not python3 -c "import aiohttp" 2>/dev/null
    if command -q pacman
        echo "Installing python-aiohttp via pacman..."
        sudo pacman -S --needed --noconfirm python-aiohttp
        or begin
            echo "Error: pacman install failed; falling back to pip" >&2
            pip install aiohttp --user --break-system-packages --quiet
            or begin
                echo "Error: pip install failed" >&2
                exit 1
            end
        end
    else
        echo "Installing aiohttp via pip..."
        pip install aiohttp --user --break-system-packages --quiet
        or begin
            echo "Error: pip install failed" >&2
            exit 1
        end
    end
end
echo "  ✓ aiohttp installed"

# 2. Locate ry-install.fish
if test -z "$script_path"
    if test -f "$dash_dir/ry-install.fish"
        set script_path "$dash_dir/ry-install.fish"
    else if test -f "$HOME/ry-install/ry-install.fish"
        set script_path "$HOME/ry-install/ry-install.fish"
    else
        echo "Error: ry-install.fish not found" >&2
        echo "  Pass --script /path/to/ry-install.fish or place it in ~/ry-install/" >&2
        exit 1
    end
end
echo "  ✓ ry-install.fish: $script_path"

# 3. Create symlink if needed
if not test -f "$dash_dir/ry-install.fish"
    ln -sf "$script_path" "$dash_dir/ry-install.fish"
    echo "  ✓ symlinked ry-install.fish"
end

# 4. Install systemd service using environment override
# Keep %h specifiers in the unit file intact — write an environment
# file with concrete paths so the unit stays portable.
mkdir -p "$svc_dir"

# Copy unit file as-is (preserves %h specifiers)
cp "$dash_dir/ry-web-dashboard.service" "$svc_dir/ry-web-dashboard.service"

# Write drop-in override with concrete paths
set -l dropin_dir "$svc_dir/ry-web-dashboard.service.d"
mkdir -p "$dropin_dir"
printf '[Service]\nExecStart=\nExecStart=/usr/bin/python3 %s/ry-web-dashboard.py --host 127.0.0.1 --port 9000 --script %s\nWorkingDirectory=%s\n' \
    "$dash_dir" "$script_path" "$dash_dir" > "$dropin_dir/paths.conf"

systemctl --user daemon-reload
echo "  ✓ service installed: $svc_dir/ry-web-dashboard.service"
echo "  ✓ override: $dropin_dir/paths.conf"

# 5. Enable and start
systemctl --user enable --now ry-web-dashboard.service
or begin
    echo "Error: systemctl enable failed" >&2
    echo "Check: journalctl --user -u ry-web-dashboard.service" >&2
    exit 1
end
set -l svc_status (systemctl --user is-active ry-web-dashboard.service)
if test "$svc_status" = active
    echo "  ✓ service running"
else
    echo "  ⚠ service status: $svc_status"
    echo "  Check: journalctl --user -u ry-web-dashboard.service"
end

echo ""
echo "Dashboard: http://localhost:9000"
set -l lan_ip (ip -4 -o addr show scope global 2>/dev/null | awk '{print $4}' | cut -d/ -f1 | head -1)
if test -n "$lan_ip"
    echo "LAN:       http://$lan_ip:9000"
end
