# Deployment (plan §12)

systemd **user** units, no root services. Claude writes these files, not pi.

| unit | what |
|---|---|
| `sidereal-web.service` | `sidereal serve --host 127.0.0.1 --port 8470`, `Restart=on-failure`, enabled at login/boot |
| `sidereal-run.service` | oneshot `sidereal run --trigger timer`, `Nice=10`, `TimeoutStartSec=3h` |
| `sidereal-run-manual.service` | the same with `--trigger manual`; started by `POST /api/runs` (Runs page) |
| `sidereal-run.timer` | `00,04,08,12,16,20:00` Europe/London, `RandomizedDelaySec=300`, `Persistent=true` |
| `sidereal-backup.service` | oneshot `sidereal backup` (idle I/O, `Nice=19`, no network) |
| `sidereal-backup.timer` | `03:30` Europe/London, `Persistent=true` |

`Persistent=true` means a run (or backup) missed while the VM was off happens shortly after the
next boot. The unit files name the checkout as `%h/Projects/Sidereal`; `install.sh` rewrites that
to the checkout it lives in.

## Install (once, then after any change to `deploy/`)

Prerequisites: the venv (`python3 -m venv .venv && .venv/bin/pip install -e '.[dev]'`), the UI
build (`(cd web && ~/.local/node/bin/npm ci && ~/.local/node/bin/npm run build)`) and, if needed,
`~/.config/sidereal/sidereal.toml` (template `config/sidereal.example.toml`).

```sh
~/Projects/Sidereal/deploy/install.sh     # idempotent; never runs sudo
sudo loginctl enable-linger al            # once, only if install.sh says lingering is off
sidereal doctor
systemctl --user list-timers 'sidereal-*'
```

`install.sh` runs `sidereal init` (state dir, DB, seeds; idempotent), copies the five units into
`~/.config/systemd/user/`, runs `systemctl --user daemon-reload` and
`systemctl --user enable --now sidereal-web.service sidereal-run.timer sidereal-backup.timer`.
Without lingering the user manager (and so the timers and the web app) stops when `al` logs out.

## Day to day

- Run now: `systemctl --user start sidereal-run-manual.service` (what the Runs page's
  `POST /api/runs` does, recorded as trigger `manual`); a manual
  `sidereal run` from a shell works too (the run lock keeps them from overlapping).
- Logs: `journalctl --user -u sidereal-run.service -n 100` (`-u sidereal-run-manual.service`
  for manual runs), `-u sidereal-web.service -f`.
- Health: `sidereal doctor` (config, env file mode, web bind/exposure/https/proxies, DB, last run, sources, Ollama, web service,
  timers with last/next trigger, linger).
- Pause runs: `systemctl --user stop sidereal-run.timer` (start it again to resume).
- Uninstall: `systemctl --user disable --now sidereal-web.service sidereal-run.timer
  sidereal-backup.timer`, delete the five files from `~/.config/systemd/user/`, `daemon-reload`.

## Hardening

Each service has `NoNewPrivileges`, `PrivateTmp`, `ProtectSystem=strict`, `ProtectHome=read-only`
with `ReadWritePaths=%h/.local/share/sidereal` (the default state dir) and
`RestrictAddressFamilies` (`AF_INET AF_INET6 AF_UNIX`; backup `AF_UNIX` only). All of these work
in user units here (systemd 257, unprivileged user namespaces; checked with a transient
`systemd-run --user` unit in M22: the venv runs, a write outside the state dir is refused).
If you move the state dir (`[paths] state_dir`), change `ReadWritePaths` in the three services
and re-run `install.sh`, or every run fails with `226/NAMESPACE` / read-only errors.

## Notifications (M28)

After each run, new TOP stories (first seen in the last 48 h, not hidden) go out once per story
and channel, one message per run: title, sources, the "why" line and the link. Quiet hours
(default 22:00-07:00 local) hold them until the first run after `quiet_end`. A failed send
leaves the run `partial` ("notify failed: discord"), is logged without secrets and is retried
next run.

1. Settings in `~/.config/sidereal/sidereal.toml` (no secrets here):

   ```toml
   [notify]
   channels = ["discord", "email"]
   smtp_host = "smtp.example.net"
   smtp_port = 587            # STARTTLS; or smtp_ssl = true with 465
   smtp_user = "me@example.net"
   smtp_from = "Sidereal <me@example.net>"
   smtp_to = ["me@example.net"]
   ```

2. Secrets in `~/.config/sidereal/env`, mode 0600 (systemd reads it through
   `EnvironmentFile=`; `sidereal doctor` fails and notify refuses the file if group/other can
   read it):

   ```sh
   install -m 600 /dev/null ~/.config/sidereal/env   # only if it does not exist yet
   $EDITOR ~/.config/sidereal/env
   #   SIDEREAL_DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/<id>/<token>
   #   SIDEREAL_SMTP_PASSWORD=<app password>
   ```

   The webhook URL comes from Discord: channel settings → Integrations → Webhooks → New Webhook
   → Copy Webhook URL. Anyone holding it can post to the channel: treat it like a password
   (Discord can delete and re-create it if it leaks). Only `https://discord.com/api/webhooks/...`
   and `discordapp.com` URLs are accepted.

   Alternative: systemd credentials. Put each secret in its own 0600 file and add to
   `sidereal-run.service` / `sidereal-run-manual.service` (a drop-in via
   `systemctl --user edit`):
   `LoadCredential=discord_webhook_url:%h/.config/sidereal/discord_webhook_url` and
   `LoadCredential=smtp_password:%h/.config/sidereal/smtp_password`. Sidereal reads
   `$CREDENTIALS_DIRECTORY/<name>` when the env variable is not set.

3. Check: `~/Projects/Sidereal/.venv/bin/sidereal notify test` (every configured channel) or
   `... notify test --channel discord`. Prints `discord: sent` or the failure (never the secret).
   The services pick up env-file changes at their next start; no restart is needed for the
   timer-driven runs.

## Data lifecycle (plan §12.4, `[retention]` in the config)

- Every run ends by clearing `content_text` (enriched article text) older than `content_days`
  (30) and deleting stories that were dropped, filtered or triaged out and first seen more than
  `drop_days` (90) ago, with their items and assessments. Summaries and excerpts stay. The counts
  are in the run's stats (`retention`).
- `sidereal backup` (nightly via the timer) copies the DB with SQLite's online backup API into
  `~/.local/share/sidereal/backups/sidereal-YYYYMMDD-HHMM.db` (UTC, mode 0600), checks it with
  `PRAGMA quick_check`, then deletes all but the newest `backup_keep` (14). Other files in that
  folder are never touched.

## Restore a backup

```sh
systemctl --user stop sidereal-run.timer sidereal-web.service
cd ~/.local/share/sidereal
mv sidereal.db sidereal.db.broken; rm -f sidereal.db-wal sidereal.db-shm
cp backups/sidereal-YYYYMMDD-HHMM.db sidereal.db && chmod 600 sidereal.db
~/Projects/Sidereal/.venv/bin/sidereal init   # applies any newer migrations
systemctl --user start sidereal-web.service sidereal-run.timer
```

(Wait for a running `sidereal-run.service` to finish first: `systemctl --user status
sidereal-run.service`.)

## LAN deployment (M30, plan §11.3 stage 2)

Prepared, not enabled: the VM still serves `127.0.0.1:8470` only. The recommended shape keeps
Sidereal on loopback and puts Caddy in front with TLS from Caddy's own CA:

```
browser ──https://sidereal.lan──▶ Caddy :443 (tls internal) ──▶ 127.0.0.1:8470 sidereal serve
```

**Rule 9 since M30:** `serve` refuses to start, and `sidereal doctor` reports ❌ `web exposure`,
when the app is reachable beyond the VM without `[auth] mode = "on"` and at least one active
user. "Reachable" means any of: a non-loopback bind, `web.trusted_proxies` set, or a name in
`web.allowed_hosts` other than loopback IPs, `localhost` and `*.localhost`. So the order below
matters: user first, then auth on, then the proxy settings.

### Steps

1. **Network.** LAN clients must reach the VM: a bridged NIC, or a port forward of 80/443 on the
   host to the VM. Pick the name clients will use (`sidereal.lan` below: a DNS entry on the
   router, or `/etc/hosts` on each client) or use the VM's IP.

2. **User** (as `al`, no sudo; prompts twice, at least 12 characters):

   ```sh
   ~/Projects/Sidereal/.venv/bin/sidereal user add al
   ~/Projects/Sidereal/.venv/bin/sidereal user totp al    # optional on the LAN, required outside
   ```

3. **Config** `~/.config/sidereal/sidereal.toml` (template `config/sidereal.example.toml`):

   ```toml
   [web]
   host = "127.0.0.1"                                   # Caddy is the only listener on the LAN
   port = 8470
   allowed_hosts = ["127.0.0.1", "localhost", "sidereal.lan"]   # the Host clients send
   allowed_origins = ["https://sidereal.lan"]           # writes/login come from :443, not :8470
   https = true                                         # session cookie gets Secure
   trusted_proxies = ["127.0.0.1", "::1"]               # believe X-Forwarded-For from Caddy only

   [auth]
   mode = "on"
   require_totp = false                                 # true before any external exposure
   ```

   - `allowed_hosts`: the Host header (Caddy passes the client's). Anything else gets 400.
   - `allowed_origins`: the write guard accepts an Origin on an allowed host only with port
     `web.port`; through Caddy the browser sends `https://sidereal.lan` (port 443), so list it,
     or every POST, login included, is 403 `origin not allowed` (doctor warns: `origins`).
   - `https`: explicit on purpose (plan §11.2); with it off the cookie has no `Secure` flag
     (doctor ⚠ `https`). Never set it for a plain-HTTP bind: browsers would not send the
     cookie back and login would loop.
   - `trusted_proxies`: single IPs or CIDR networks (`"10.0.0.0/24"`, `"fd00::/64"`); an entry
     that isn't one is a config error (exit 2). Only these peers may set the client IP the
     login rate limit counts; list just the proxy (doctor ⚠ for anything wider than /24 or /64).

4. **Restart the app and check** (no sudo):

   ```sh
   systemctl --user restart sidereal-web.service
   sidereal doctor     # web exposure ✅, https ✅, origins ✅
   ```

5. **Caddy** (Debian package; the only sudo steps):

   ```sh
   sudo apt install caddy
   sudo cp ~/Projects/Sidereal/deploy/Caddyfile.example /etc/caddy/Caddyfile
   sudo $EDITOR /etc/caddy/Caddyfile                 # sidereal.lan → your name or IP
   sudo caddy validate --config /etc/caddy/Caddyfile
   sudo systemctl reload caddy
   ```

   `Caddyfile.example`: `tls internal`, `reverse_proxy 127.0.0.1:8470`, a 1 MB request body
   cap, header timeouts, and only the security headers the app doesn't send itself
   (Permissions-Policy, COOP, CORP; the app sends CSP, nosniff, Referrer-Policy,
   X-Frame-Options). Trust Caddy's root on each client once:
   `/var/lib/caddy/.local/share/caddy/pki/authorities/local/root.crt` (import it as a CA in the
   browser or OS store). HSTS stays commented out until every client trusts the cert.

6. **Firewall** (if the VM runs one; Debian has none by default): allow 80 and 443 from the LAN
   subnet only, nothing else inbound. 8470 never needs opening (loopback bind). With nftables:
   `tcp dport { 80, 443 } ip saddr 192.168.1.0/24 accept` in the input chain. Ollama
   (`192.168.221.1:11434`) is outbound from the VM and unaffected.

7. **Test from a LAN client:** `https://sidereal.lan/` → login page; log in; check the Runs
   page "Run now" (a write) works. `journalctl --user -u sidereal-web.service` shows
   `auth: login ok user_id=… ip=<the client's IP>` (not 127.0.0.1: that would mean
   `trusted_proxies` is missing).

Without Caddy (plain HTTP, not recommended): keep `https = false`, add the VM's name/IP to
`allowed_hosts`, and change the bind with `systemctl --user edit sidereal-web.service`
(`[Service]`, an empty `ExecStart=`, then `ExecStart=… sidereal serve --host 0.0.0.0 --port
8470`); doctor reads the host from the installed unit and warns that the cookie is not Secure.

Back to VM-only: remove the extra `allowed_hosts`/`allowed_origins`, empty `trusted_proxies`,
`https = false`, stop Caddy (`sudo systemctl disable --now caddy`); auth may stay on.

### Before any external exposure (stage 3, not built)

Prefer not opening a port at all: Tailscale/WireGuard to the VM, or Cloudflare Tunnel + Access
in front of the built-in login. If a port is opened anyway:

- [ ] `[auth] require_totp = true` and `sidereal user totp <name>` for every user.
- [ ] Caddy with a public certificate (a real domain instead of `tls internal`), HSTS enabled.
- [ ] fail2ban on the login failure line (the rate limit, 5 per user+IP / 20 per IP / 50 per
      user in 15 min, stays in place). The log line is
      `auth: login failed ip=<client>` in the user journal; a jail with
      `backend = systemd`, `journalmatch = _SYSTEMD_USER_UNIT=sidereal-web.service` and
      `failregex = auth: login failed ip=<HOST>$` bans at the firewall. Or Caddy `rate_limit`
      (a plugin, not in the Debian package).
- [ ] Only 443 (and 80 for the ACME challenge) open; the router forwards nothing else.
- [ ] Backups offsite: copy `~/.local/share/sidereal/backups/` (encrypted, e.g. restic) off the
      VM; a backup on the same disk doesn't survive the disk.
- [ ] `sidereal doctor` all ✅, then a `/security-review` of the deployed config before go-live.
- [ ] Keep the VM patched (`unattended-upgrades`), and `pip`/`npm` pins reviewed.
