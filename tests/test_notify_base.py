"""notify/base.py (M28): secrets loading, hiding and scrubbing."""

from __future__ import annotations

import pytest

from sidereal import paths
from sidereal.notify.base import (
    Secrets,
    SecretsFileError,
    error_text,
    load_secrets,
    scrub,
)
from tests.notify_helpers import PASSWORD, TOKEN, WEBHOOK


def _env_file(env, text: str, mode: int = 0o600):
    path = paths.config_dir(env) / "env"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    path.chmod(mode)
    return path


def test_env_vars_win(isolated_env):
    env = {"HOME": str(isolated_env), "SIDEREAL_SMTP_PASSWORD": PASSWORD,
           "SIDEREAL_DISCORD_WEBHOOK_URL": WEBHOOK}
    _env_file(env, "SIDEREAL_SMTP_PASSWORD=other\n")
    s = load_secrets(env)
    assert (s.smtp_password, s.discord_webhook_url) == (PASSWORD, WEBHOOK)


def test_env_file_is_read_when_private(isolated_env):
    import os
    env = dict(os.environ)
    _env_file(env, f"# secrets\nexport SIDEREAL_SMTP_PASSWORD='{PASSWORD}'\n"
                   f"SIDEREAL_DISCORD_WEBHOOK_URL=\"{WEBHOOK}\"\n")
    s = load_secrets(env)
    assert (s.smtp_password, s.discord_webhook_url) == (PASSWORD, WEBHOOK)


def test_env_file_readable_by_others_is_refused(isolated_env):
    import os
    env = dict(os.environ)
    path = _env_file(env, f"SIDEREAL_SMTP_PASSWORD={PASSWORD}\n", mode=0o644)
    with pytest.raises(SecretsFileError, match="chmod 600") as info:
        load_secrets(env)
    assert str(path) in str(info.value) and PASSWORD not in str(info.value)


def test_systemd_credentials_directory(isolated_env, tmp_path):
    creds = tmp_path / "creds"
    creds.mkdir()
    (creds / "discord_webhook_url").write_text(WEBHOOK + "\n")
    (creds / "smtp_password").write_text(PASSWORD)
    s = load_secrets({"HOME": str(isolated_env), "CREDENTIALS_DIRECTORY": str(creds)})
    assert (s.smtp_password, s.discord_webhook_url) == (PASSWORD, WEBHOOK)


def test_missing_everywhere_is_empty(isolated_env):
    s = load_secrets({"HOME": str(isolated_env)})
    assert (s.smtp_password, s.discord_webhook_url) == ("", "")


def test_repr_hides_secrets():
    s = Secrets(smtp_password=PASSWORD, discord_webhook_url=WEBHOOK)
    assert PASSWORD not in repr(s) and TOKEN not in repr(s)


def test_scrub_and_error_text():
    s = Secrets(smtp_password=PASSWORD, discord_webhook_url=WEBHOOK)
    text = scrub(f"failed posting to {WEBHOOK} with {PASSWORD}", s)
    assert TOKEN not in text and PASSWORD not in text and "[redacted]" in text
    assert error_text(RuntimeError(f"x {PASSWORD}"), s) == "RuntimeError: x [redacted]"
    assert len(scrub("y" * 500, s)) == 200


def test_scrub_removes_a_bare_webhook_token():
    s = Secrets(discord_webhook_url=WEBHOOK)
    assert TOKEN not in scrub(f"path /api/webhooks/123456/{TOKEN} refused", s)
