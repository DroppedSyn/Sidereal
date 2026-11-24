"""Filesystem locations: XDG config/state dirs and the project's own folders.

Overrides (tests and odd setups):
- ``SIDEREAL_CONFIG``: path of the TOML settings file.
- ``[paths] state_dir`` in that file, or ``SIDEREAL_PATHS__STATE_DIR``: the state directory.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from pathlib import Path

APP = "sidereal"


def _xdg(env: Mapping[str, str], var: str, fallback: str) -> Path:
    value = env.get(var, "")
    if value and Path(value).is_absolute():
        return Path(value)
    return Path(env.get("HOME") or Path.home()) / fallback


def config_dir(env: Mapping[str, str] = os.environ) -> Path:
    """``$XDG_CONFIG_HOME/sidereal`` or ``~/.config/sidereal``."""
    return _xdg(env, "XDG_CONFIG_HOME", ".config") / APP


def config_file(env: Mapping[str, str] = os.environ) -> Path:
    """The settings file: ``$SIDEREAL_CONFIG`` or ``config_dir()/sidereal.toml``."""
    override = env.get("SIDEREAL_CONFIG", "")
    if override:
        return Path(override).expanduser()
    return config_dir(env) / "sidereal.toml"


def default_state_dir(env: Mapping[str, str] = os.environ) -> Path:
    """``$XDG_DATA_HOME/sidereal`` or ``~/.local/share/sidereal``."""
    return _xdg(env, "XDG_DATA_HOME", ".local/share") / APP


def project_root() -> Path:
    """The source checkout (the app runs from an editable install in ``~/Projects/Sidereal``)."""
    return Path(__file__).resolve().parents[2]


def defaults_dir() -> Path:
    """Seed TOMLs for ``sidereal init``."""
    return project_root() / "config" / "defaults"


def prompts_dir() -> Path:
    return project_root() / "prompts"


def web_dist_dir() -> Path:
    return project_root() / "web" / "dist"
