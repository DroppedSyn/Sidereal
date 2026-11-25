"""Notification basics (M28, plan §12.3, §16 M28): the ``Notice`` a channel sends, the error
type, and the secrets loader.

Secrets (``SIDEREAL_SMTP_PASSWORD``, ``SIDEREAL_DISCORD_WEBHOOK_URL``) are looked up, in order:
the process environment (systemd ``EnvironmentFile=``), ``$CREDENTIALS_DIRECTORY/<name>``
(systemd ``LoadCredential=``, files ``smtp_password`` / ``discord_webhook_url``), then
``~/.config/sidereal/env`` read directly (so ``sidereal notify test`` works from a shell); that
file is refused when group/other can read it. They are never stored, logged or shown: the
dataclass hides them from ``repr`` and ``scrub`` removes them from error texts.
"""

from __future__ import annotations

import os
import stat
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

from sidereal import paths

SMTP_PASSWORD_ENV = "SIDEREAL_SMTP_PASSWORD"
DISCORD_WEBHOOK_ENV = "SIDEREAL_DISCORD_WEBHOOK_URL"
CREDENTIAL_FILES = {SMTP_PASSWORD_ENV: "smtp_password", DISCORD_WEBHOOK_ENV: "discord_webhook_url"}
MAX_ERROR_CHARS = 200


class NotifyError(Exception):
    """A channel could not send (message safe to log: never holds a secret)."""


class SecretsFileError(NotifyError):
    """The env file exists but is readable by group/other (or unreadable)."""


@dataclass(frozen=True)
class Notice:
    story_id: int
    title: str
    url: str  # http(s) link from items.url, "" if none
    sources: tuple[str, ...] = ()
    why: str = ""


@dataclass(frozen=True)
class Secrets:
    smtp_password: str = field(default="", repr=False)
    discord_webhook_url: str = field(default="", repr=False)

    def values(self) -> list[str]:
        """Every secret string, longest first; the webhook's token (last path part) too."""
        out = [v for v in (self.smtp_password, self.discord_webhook_url) if v]
        token = self.discord_webhook_url.rstrip("/").rsplit("/", 1)[-1]
        if len(token) >= 8 and token != self.discord_webhook_url:
            out.append(token)
        return sorted(out, key=len, reverse=True)


def _parse_env_file(text: str) -> dict[str, str]:
    """``KEY=value`` lines (systemd EnvironmentFile subset): ``#`` comments, optional
    ``export``, one pair of surrounding quotes stripped."""
    out: dict[str, str] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith(("#", ";")) or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.removeprefix("export ").strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        out[key] = value
    return out


def _env_file_values(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    try:
        if path.stat().st_mode & (stat.S_IRWXG | stat.S_IRWXO):
            raise SecretsFileError(f"{path} is readable by group/other: chmod 600 it")
        return _parse_env_file(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise SecretsFileError(f"{path}: {type(exc).__name__}") from exc


def load_secrets(env: Mapping[str, str] | None = None) -> Secrets:
    env = os.environ if env is None else env
    found: dict[str, str] = {}
    cred_dir = env.get("CREDENTIALS_DIRECTORY", "")
    file_values: dict[str, str] | None = None
    for name, cred in CREDENTIAL_FILES.items():
        value = env.get(name, "").strip()
        if not value and cred_dir:
            p = Path(cred_dir) / cred
            if p.is_file():
                value = p.read_text(encoding="utf-8").strip()
        if not value:
            if file_values is None:
                file_values = _env_file_values(paths.config_dir(env) / "env")
            value = file_values.get(name, "").strip()
        found[name] = value
    return Secrets(smtp_password=found[SMTP_PASSWORD_ENV],
                   discord_webhook_url=found[DISCORD_WEBHOOK_ENV])


def scrub(text: str, secrets: Secrets) -> str:
    """``text`` with every secret value replaced by ``[redacted]``, cut to 200 chars."""
    for value in secrets.values():
        text = text.replace(value, "[redacted]")
    return text[:MAX_ERROR_CHARS]


def error_text(exc: BaseException, secrets: Secrets) -> str:
    return scrub(f"{type(exc).__name__}: {exc}", secrets)
