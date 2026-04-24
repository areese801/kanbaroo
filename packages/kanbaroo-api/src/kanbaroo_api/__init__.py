"""
Kanbaroo API server: FastAPI REST + WebSocket endpoints.

The package entry point for application code is :func:`create_app` in
:mod:`kanbaroo_api.app`. The console script entry point is
:func:`run` in :mod:`kanbaroo_api.server`.
"""

from kanbaroo_api.app import create_app
from kanbaroo_api.server import run

__version__ = "0.1.0"

__all__ = ["__version__", "create_app", "run"]
