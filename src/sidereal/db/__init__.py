"""SQLite access. All SQL in the project lives in this package (cardinal rule 5)."""

from sqlite3 import Connection

__all__ = ["Connection"]  # the connection type, for annotations outside db/ (no sqlite3 there)
