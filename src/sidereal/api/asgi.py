"""ASGI entry for ``sidereal serve --reload`` (uvicorn needs an import string to reload)."""

from sidereal.api.app import create_app
from sidereal.config import load_settings

app = create_app(load_settings())
