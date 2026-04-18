"""
Config loader for the Kanberoo MCP server.

The MCP server is launched as a subprocess by the client (Claude
Desktop or equivalent) via a block like::

    {
      "mcpServers": {
        "kanberoo": {
          "command": "kanberoo-mcp",
          "args": ["--api-url", "http://localhost:8080",
                   "--token-env", "KANBEROO_MCP_TOKEN"]
        }
      }
    }

Token resolution order (first hit wins):

1. ``--token <TOKEN>`` on the command line (handy for local testing;
   discouraged in real use because the plaintext ends up in the
   client's config file).
2. ``--token-env <NAME>``: pull the plaintext from the named env
   variable. This is the recommended pattern.
3. ``$KANBEROO_MCP_TOKEN`` directly.
4. ``$KANBEROO_TOKEN`` (shared with the CLI).
5. ``$KANBEROO_CONFIG_DIR/config.toml`` or ``~/.kanberoo/config.toml``:
   the ``token`` field from the CLI's config file. This is usually a
   human token, so using it triggers an ``actor_type`` warning at
   startup.

API URL resolution order:

1. ``--api-url <URL>`` on the command line.
2. ``$KANBEROO_API_URL``.
3. ``api_url`` field in ``config.toml``.

Missing config is fatal: :func:`resolve_config` raises
:class:`ConfigError` and the entry point exits 1 with a clear stderr
message listing the resolution order the caller tried.
"""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass
from pathlib import Path


class ConfigError(Exception):
    """
    Raised when the MCP server cannot resolve a required setting.

    The server's entry point catches this and prints the message to
    stderr before exiting 1.
    """


@dataclass(frozen=True)
class McpConfig:
    """
    Fully-resolved configuration for the MCP server process.

    ``token_source`` is a human-readable string (e.g. ``"--token"`` or
    ``"$KANBEROO_MCP_TOKEN"``) describing where the token came from;
    the server logs it at startup so operators can confirm the right
    credential is in play.
    """

    api_url: str
    token: str
    token_source: str


def _default_config_dir() -> Path:
    """
    Resolve the config directory from ``$KANBEROO_CONFIG_DIR`` or fall
    back to ``$HOME/.kanberoo``. Mirrors the CLI's helper.
    """
    override = os.environ.get("KANBEROO_CONFIG_DIR")
    if override:
        return Path(override)
    return Path.home() / ".kanberoo"


def _default_config_path() -> Path:
    """
    Canonical ``config.toml`` location.
    """
    return _default_config_dir() / "config.toml"


def _load_config_toml(path: Path) -> dict[str, object]:
    """
    Read ``config.toml`` and return its top-level table.

    Missing file returns an empty dict so the caller can continue to
    try other resolution paths (env var, CLI flag). A malformed TOML
    file is fatal: we surface the parse error verbatim.
    """
    if not path.exists():
        return {}
    with path.open("rb") as fh:
        return tomllib.load(fh)


def resolve_config(
    *,
    cli_api_url: str | None,
    cli_token: str | None,
    cli_token_env: str | None,
    env: dict[str, str] | None = None,
    config_path: Path | None = None,
) -> McpConfig:
    """
    Resolve the final :class:`McpConfig` from CLI flags, env vars, and
    ``config.toml`` in that order.

    Raises :class:`ConfigError` if either ``api_url`` or ``token``
    cannot be resolved from any source.

    ``env`` and ``config_path`` are injected for testability; production
    code leaves them defaulted so the real ``os.environ`` and
    ``$KANBEROO_CONFIG_DIR`` are consulted.
    """
    actual_env = env if env is not None else dict(os.environ)
    path = config_path or _default_config_path()
    toml_data = _load_config_toml(path)

    token, token_source = _resolve_token(
        cli_token=cli_token,
        cli_token_env=cli_token_env,
        env=actual_env,
        toml_data=toml_data,
        config_path=path,
    )
    api_url = _resolve_api_url(
        cli_api_url=cli_api_url,
        env=actual_env,
        toml_data=toml_data,
    )
    return McpConfig(api_url=api_url, token=token, token_source=token_source)


def _resolve_token(
    *,
    cli_token: str | None,
    cli_token_env: str | None,
    env: dict[str, str],
    toml_data: dict[str, object],
    config_path: Path,
) -> tuple[str, str]:
    """
    Return ``(token, source)`` or raise :class:`ConfigError`.
    """
    if cli_token:
        return cli_token, "--token"

    if cli_token_env:
        value = env.get(cli_token_env)
        if not value:
            raise ConfigError(
                f"--token-env was set to {cli_token_env!r} but that "
                "environment variable is empty or unset."
            )
        return value, f"${cli_token_env}"

    direct = env.get("KANBEROO_MCP_TOKEN")
    if direct:
        return direct, "$KANBEROO_MCP_TOKEN"

    shared = env.get("KANBEROO_TOKEN")
    if shared:
        return shared, "$KANBEROO_TOKEN"

    raw = toml_data.get("token")
    if isinstance(raw, str) and raw:
        return raw, f"{config_path}:token"

    raise ConfigError(
        "could not resolve a Kanberoo API token. Tried, in order: "
        "--token, --token-env, $KANBEROO_MCP_TOKEN, $KANBEROO_TOKEN, "
        f"and the 'token' field in {config_path}."
    )


def _resolve_api_url(
    *,
    cli_api_url: str | None,
    env: dict[str, str],
    toml_data: dict[str, object],
) -> str:
    """
    Return the resolved API URL or raise :class:`ConfigError`.
    """
    if cli_api_url:
        return cli_api_url
    env_url = env.get("KANBEROO_API_URL")
    if env_url:
        return env_url
    raw = toml_data.get("api_url")
    if isinstance(raw, str) and raw:
        return raw
    raise ConfigError(
        "could not resolve the Kanberoo API URL. Tried, in order: "
        "--api-url, $KANBEROO_API_URL, and the 'api_url' field in "
        "config.toml."
    )
