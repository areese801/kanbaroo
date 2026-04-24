"""
Uvicorn entry point for ``kanbaroo-api``.

Reads ``$KANBAROO_API_HOST`` and ``$KANBAROO_API_PORT`` for bind
configuration (defaults: ``0.0.0.0:8080``) and ``$KANBAROO_DATABASE_URL``
for the database. The database URL is consumed inside
:func:`kanbaroo_api.app.create_app`; the server module only owns
network binding.
"""

import os

import uvicorn

from kanbaroo_api.app import create_app

DEFAULT_HOST = "0.0.0.0"
DEFAULT_PORT = 8080


def run() -> None:
    """
    Start the Kanbaroo API server in the foreground.

    Registered as the ``kanbaroo-api`` console script in
    ``pyproject.toml``. Returns when the server shuts down.
    """
    host = os.environ.get("KANBAROO_API_HOST", DEFAULT_HOST)
    port = int(os.environ.get("KANBAROO_API_PORT", str(DEFAULT_PORT)))
    app = create_app()
    uvicorn.run(app, host=host, port=port, log_level="info")


if __name__ == "__main__":
    run()
