#!/usr/bin/env bash
# Sidereal installer. Run from anywhere; safe to re-run (after a `git pull`, too).
#
#   ./install.sh               set everything up and start Sidereal
#   ./install.sh --uninstall   stop Sidereal and remove its services (your data is kept)
#   ./install.sh --help
#
# What it does: Python venv + package, web UI build, database (`sidereal init`),
# `sidereal` command on PATH (~/.local/bin), systemd user services (web app, 4-hourly scan
# timer, nightly backup), lingering (asks before using sudo), then `sidereal doctor`.
set -euo pipefail

repo="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
deploy="$repo/deploy"
venv="$repo/.venv"
bin="$venv/bin/sidereal"
unit_dir="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
link_dir="$HOME/.local/bin"
user="$(id -un)"
url="http://127.0.0.1:8470"
units=(sidereal-web.service sidereal-run.service sidereal-run-manual.service sidereal-run.timer
       sidereal-backup.service sidereal-backup.timer)
enable=(sidereal-web.service sidereal-run.timer sidereal-backup.timer)

build=1 doctor=1 action=install
usage() {
    sed -n '2,10p' "$0" | sed 's/^# \{0,1\}//'
    echo "Advanced: --no-build skips the venv and UI steps, --no-doctor skips the final check."
}
for arg in "$@"; do
    case "$arg" in
        --uninstall) action=uninstall ;;
        --no-build) build=0 ;;
        --no-doctor) doctor=0 ;;
        -h|--help) usage; exit 0 ;;
        *) echo "unknown option: $arg (see --help)" >&2; exit 2 ;;
    esac
done

step() { printf '\n==> %s\n' "$*"; }
ok() { printf '    %s\n' "$*"; }
warn() { printf '    warning: %s\n' "$*" >&2; }
die() { printf '\nerror: %s\n' "$*" >&2; exit 1; }

uninstall() {
    step "Stopping and removing the Sidereal services"
    systemctl --user disable --now "${enable[@]}" 2>/dev/null || true
    for u in "${units[@]}"; do
        if [ -e "$unit_dir/$u" ]; then rm -f "$unit_dir/$u"; ok "removed $unit_dir/$u"; fi
    done
    systemctl --user daemon-reload || true
    if [ -L "$link_dir/sidereal" ] && [ "$(readlink "$link_dir/sidereal")" = "$bin" ]; then
        rm -f "$link_dir/sidereal"; ok "removed $link_dir/sidereal"
    fi
    echo
    echo "Sidereal is stopped. Your data is untouched in ~/.local/share/sidereal"
    echo "and your settings in ~/.config/sidereal. Run ./install.sh to set it up again."
}

python_env() {
    step "Python environment"
    if [ ! -x "$venv/bin/python" ]; then
        command -v python3 >/dev/null || die "python3 not found; install Python 3.11+ first"
        python3 -m venv "$venv" || die "could not create $venv (on Debian: sudo apt install python3-venv)"
        ok "created $venv"
    fi
    stamp="$venv/.sidereal-installed"
    want="$(sha256sum "$repo/pyproject.toml" | cut -d' ' -f1)"
    if [ ! -x "$bin" ] || [ "$(cat "$stamp" 2>/dev/null)" != "$want" ]; then
        ok "installing Python packages (needs the network)..."
        "$venv/bin/pip" install --quiet --upgrade pip
        "$venv/bin/pip" install --quiet -e "$repo"
        echo "$want" > "$stamp"
        ok "packages installed"
    else
        ok "up to date"
    fi
}

web_ui() {
    step "Web UI"
    npm=""
    if [ -x "$HOME/.local/node/bin/npm" ]; then npm="$HOME/.local/node/bin/npm"
    elif command -v npm >/dev/null; then npm="$(command -v npm)"; fi
    if [ -z "$npm" ]; then
        if [ -f "$repo/web/dist/index.html" ]; then
            warn "npm not found; keeping the existing build in web/dist"
        else
            warn "npm not found and web/dist is missing: the app will say 'UI not built'."
            warn "Install Node.js 20+, then re-run ./install.sh"
        fi
        return
    fi
    log="$(mktemp)"
    if [ ! -d "$repo/web/node_modules" ]; then
        ok "installing UI packages (needs the network)..."
        (cd "$repo/web" && PATH="$(dirname "$npm"):$PATH" "$npm" ci) >"$log" 2>&1 \
            || { cat "$log" >&2; rm -f "$log"; die "npm ci failed"; }
    fi
    ok "building..."
    (cd "$repo/web" && PATH="$(dirname "$npm"):$PATH" "$npm" run build) >"$log" 2>&1 \
        || { cat "$log" >&2; rm -f "$log"; die "UI build failed"; }
    rm -f "$log"
    ok "built web/dist"
}

install() {
    if [ "$build" = 1 ]; then
        python_env
        web_ui
    fi
    [ -x "$bin" ] || die "$bin missing; run ./install.sh without --no-build"

    step "Database and settings"
    "$bin" init | sed 's/^/    /'

    step "The 'sidereal' command"
    mkdir -p "$link_dir"
    if [ -e "$link_dir/sidereal" ] && [ ! -L "$link_dir/sidereal" ]; then
        warn "$link_dir/sidereal exists and is not a symlink; left unchanged"
    else
        ln -sfn "$bin" "$link_dir/sidereal"
        ok "linked $link_dir/sidereal -> $bin"
    fi
    case ":$PATH:" in
        *":$link_dir:"*) ;;
        *) warn "$link_dir is not on your PATH; add it to use 'sidereal' directly" ;;
    esac

    step "Services (web app, scan timer, backup timer)"
    mkdir -p "$unit_dir"
    for u in "${units[@]}"; do
        # The units name the checkout as %h/Projects/Sidereal; point them at this one.
        tmp="$unit_dir/.$u.tmp"
        sed "s|%h/Projects/Sidereal|$repo|g" "$deploy/$u" > "$tmp"
        chmod 0644 "$tmp"
        mv -f "$tmp" "$unit_dir/$u"
    done
    ok "installed ${#units[@]} units in $unit_dir"
    systemctl --user daemon-reload
    systemctl --user enable --now "${enable[@]}"
    systemctl --user try-restart sidereal-web.service  # pick up new code on a re-install
    ok "web app running, scans every 4 hours (00/04/08/12/16/20 London), backup at 03:30"

    step "Keep running after logout (lingering)"
    linger="$(loginctl show-user "$user" --property=Linger --value 2>/dev/null || true)"
    if [ "$linger" = "yes" ]; then
        ok "already on"
    elif [ -t 0 ] && command -v sudo >/dev/null; then
        read -r -p "    Turn it on now? Needs your sudo password. [Y/n] " answer
        if [ "${answer:-y}" != "n" ] && [ "${answer:-y}" != "N" ]; then
            sudo loginctl enable-linger "$user" && ok "turned on"
        else
            warn "skipped: Sidereal stops when $user logs out. Later: sudo loginctl enable-linger $user"
        fi
    else
        warn "off: Sidereal stops when $user logs out. Run once:"
        echo "      sudo loginctl enable-linger $user"
    fi

    if [ "$doctor" = 1 ]; then
        step "Health check (sidereal doctor)"
        "$bin" doctor | sed 's/^/    /' || true
    fi

    echo
    echo "Done. Open $url"
    echo "Check health any time with: sidereal doctor"
}

"$action"
