"""
Config resolution tests.

The config loader is deliberately fussy about the order it tries
sources; these tests pin that ordering so future refactoring can't
silently swap, say, $KANBAROO_TOKEN ahead of --token.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from kanbaroo_mcp.config import ConfigError, resolve_config


def test_resolve_config_prefers_cli_flags(tmp_path: Path) -> None:
    """
    ``--token`` and ``--api-url`` beat every other source.
    """
    (tmp_path / "config.toml").write_text(
        'api_url = "http://configtoml.invalid"\ntoken = "from-file"\n',
        encoding="utf-8",
    )
    cfg = resolve_config(
        cli_api_url="http://flag.invalid",
        cli_token="from-flag",
        cli_token_env=None,
        env={"KANBAROO_API_URL": "http://env.invalid", "KANBAROO_TOKEN": "from-env"},
        config_path=tmp_path / "config.toml",
    )
    assert cfg.api_url == "http://flag.invalid"
    assert cfg.token == "from-flag"
    assert cfg.token_source == "--token"


def test_resolve_config_uses_token_env_indirection(tmp_path: Path) -> None:
    """
    ``--token-env NAME`` reads the token from the named env var.
    """
    cfg = resolve_config(
        cli_api_url="http://flag.invalid",
        cli_token=None,
        cli_token_env="KANBAROO_MCP_TOKEN",
        env={"KANBAROO_MCP_TOKEN": "claude-token"},
        config_path=tmp_path / "missing.toml",
    )
    assert cfg.token == "claude-token"
    assert cfg.token_source == "$KANBAROO_MCP_TOKEN"


def test_resolve_config_token_env_missing(tmp_path: Path) -> None:
    """
    ``--token-env`` pointing at an unset variable is a hard error.
    """
    with pytest.raises(ConfigError) as excinfo:
        resolve_config(
            cli_api_url="http://flag.invalid",
            cli_token=None,
            cli_token_env="NO_SUCH_VAR",
            env={},
            config_path=tmp_path / "missing.toml",
        )
    assert "NO_SUCH_VAR" in str(excinfo.value)


def test_resolve_config_falls_back_to_shared_cli_token(tmp_path: Path) -> None:
    """
    When nothing else is provided the loader falls back to
    ``$KANBAROO_TOKEN`` (the CLI's shared token env var).
    """
    cfg = resolve_config(
        cli_api_url=None,
        cli_token=None,
        cli_token_env=None,
        env={
            "KANBAROO_API_URL": "http://env.invalid",
            "KANBAROO_TOKEN": "human-cli-token",
        },
        config_path=tmp_path / "missing.toml",
    )
    assert cfg.api_url == "http://env.invalid"
    assert cfg.token == "human-cli-token"
    assert cfg.token_source == "$KANBAROO_TOKEN"


def test_resolve_config_falls_back_to_config_toml(tmp_path: Path) -> None:
    """
    With no flags or env vars, values come from config.toml.
    """
    path = tmp_path / "config.toml"
    path.write_text(
        'api_url = "http://file.invalid"\ntoken = "from-file"\n',
        encoding="utf-8",
    )
    cfg = resolve_config(
        cli_api_url=None,
        cli_token=None,
        cli_token_env=None,
        env={},
        config_path=path,
    )
    assert cfg.api_url == "http://file.invalid"
    assert cfg.token == "from-file"
    assert cfg.token_source.endswith(":token")


def test_resolve_config_missing_token_is_fatal(tmp_path: Path) -> None:
    """
    Exhausting every source raises a :class:`ConfigError` listing the
    resolution order so the user knows what to fix.
    """
    with pytest.raises(ConfigError) as excinfo:
        resolve_config(
            cli_api_url="http://flag.invalid",
            cli_token=None,
            cli_token_env=None,
            env={},
            config_path=tmp_path / "missing.toml",
        )
    message = str(excinfo.value)
    assert "--token" in message
    assert "KANBAROO_MCP_TOKEN" in message
    assert "KANBAROO_TOKEN" in message


def test_resolve_config_missing_api_url_is_fatal(tmp_path: Path) -> None:
    """
    A token alone is not enough; the API URL is also required.
    """
    with pytest.raises(ConfigError) as excinfo:
        resolve_config(
            cli_api_url=None,
            cli_token="t",
            cli_token_env=None,
            env={},
            config_path=tmp_path / "missing.toml",
        )
    assert "API URL" in str(excinfo.value)
