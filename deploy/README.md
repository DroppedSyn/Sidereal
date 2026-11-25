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
~/Projects/Sidereal/.venv/bin/sidereal doctor
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
- Health: `sidereal doctor` (config, env file mode, DB, last run, sources, Ollama, web service,
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

## Later

`Caddyfile.example` and the LAN stage arrive in M30 (plan §11.3).
