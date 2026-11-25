#!/usr/bin/env bash
# Install the Sidereal systemd user units (plan §12.1). Idempotent: safe to re-run after a
# `git pull` to pick up changed units. Never uses sudo; prints the one sudo command needed
# (lingering) when it is off.
#
#   deploy/install.sh            install, daemon-reload, enable --now web + timers
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo="$(dirname "$here")"
bin="$repo/.venv/bin/sidereal"
unit_dir="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
user="$(id -un)"
units=(sidereal-web.service sidereal-run.service sidereal-run.timer
       sidereal-backup.service sidereal-backup.timer)
enable=(sidereal-web.service sidereal-run.timer sidereal-backup.timer)

if [ ! -x "$bin" ]; then
    echo "error: $bin missing; create the venv first:" >&2
    echo "  (cd $repo && python3 -m venv .venv && .venv/bin/pip install -e '.[dev]')" >&2
    exit 1
fi
if [ ! -f "$repo/web/dist/index.html" ]; then
    echo "warning: web/dist not built; the web app shows 'UI not built' until you run:" >&2
    echo "  (cd $repo/web && ~/.local/node/bin/npm ci && ~/.local/node/bin/npm run build)" >&2
fi

# State dir + DB + seeds (idempotent). The units' ReadWritePaths needs the dir to exist.
"$bin" init

mkdir -p "$unit_dir"
for u in "${units[@]}"; do
    # The units name the checkout as %h/Projects/Sidereal; point them at this one.
    tmp="$unit_dir/.$u.tmp"
    sed "s|%h/Projects/Sidereal|$repo|g" "$here/$u" > "$tmp"
    chmod 0644 "$tmp"
    mv -f "$tmp" "$unit_dir/$u"
    echo "installed $unit_dir/$u"
done

systemctl --user daemon-reload
systemctl --user enable --now "${enable[@]}"
systemctl --user list-timers 'sidereal-*' --no-pager || true

linger="$(loginctl show-user "$user" --property=Linger --value 2>/dev/null || true)"
if [ "$linger" != "yes" ]; then
    echo
    echo "Lingering is off: the timers and the web app stop when $user logs out. Run once:"
    echo "  sudo loginctl enable-linger $user"
    echo "then check: loginctl show-user $user --property=Linger   (expect Linger=yes)"
fi
echo
echo "Done. Check with: $bin doctor"
