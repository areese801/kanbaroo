"""
Tests for the CLI's config loader.

The CLI's resolution order is intentionally narrower than the MCP
server's (no ``--token`` / ``--token-env`` CLI flags, no
``$KANBAROO_MCP_TOKEN``) but still has to honor the same precedence
between ``$KANBAROO_TOKEN``, the new ``token_file`` field, and the
deprecated ``token`` field. These tests pin that order so future
refactoring cannot quietly swap it.
"""

from __future__ import annotations

import warnings
from pathlib import Path

import pytest

from kanbaroo_cli.config import (
    ConfigMalformedError,
    load_config_api_only,
)


def _write_config(path: Path, body: str) -> Path:
    """
    Helper: write ``body`` to ``path / "config.toml"`` and return the
    resulting path.
    """
    config_path = path / "config.toml"
    config_path.write_text(body, encoding="utf-8")
    return config_path


def test_env_token_beats_token_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    ``$KANBAROO_TOKEN`` outranks ``token_file`` in ``config.toml``.
    """
    monkeypatch.setenv("KANBAROO_TOKEN", "kbr_env")
    monkeypatch.delenv("KANBAROO_API_URL", raising=False)
    monkeypatch.delenv("KANBAROO_DATABASE_URL", raising=False)
    token_path = tmp_path / "token"
    token_path.write_text("kbr_file\n", encoding="utf-8")
    config_path = _write_config(
        tmp_path,
        f'api_url = "http://t.invalid"\ntoken_file = "{token_path}"\n',
    )
    cfg = load_config_api_only(config_path)
    assert cfg.token == "kbr_env"


def test_token_file_beats_legacy_token(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    With no env var, ``token_file`` wins over the deprecated
    ``token`` value and no deprecation warning fires.
    """
    monkeypatch.delenv("KANBAROO_TOKEN", raising=False)
    monkeypatch.delenv("KANBAROO_API_URL", raising=False)
    monkeypatch.delenv("KANBAROO_DATABASE_URL", raising=False)
    token_path = tmp_path / "token"
    token_path.write_text("kbr_file\n", encoding="utf-8")
    config_path = _write_config(
        tmp_path,
        'api_url = "http://t.invalid"\n'
        f'token_file = "{token_path}"\n'
        'token = "kbr_legacy"\n',
    )
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        cfg = load_config_api_only(config_path)
    assert cfg.token == "kbr_file"
    assert not any(issubclass(w.category, DeprecationWarning) for w in caught)


def test_token_file_strips_trailing_whitespace(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    Trailing newlines and spaces in the referenced file are stripped so
    the bearer token is not corrupted.
    """
    monkeypatch.delenv("KANBAROO_TOKEN", raising=False)
    monkeypatch.delenv("KANBAROO_API_URL", raising=False)
    monkeypatch.delenv("KANBAROO_DATABASE_URL", raising=False)
    token_path = tmp_path / "token"
    token_path.write_text("kbr_file   \n  \n", encoding="utf-8")
    config_path = _write_config(
        tmp_path,
        f'api_url = "http://t.invalid"\ntoken_file = "{token_path}"\n',
    )
    cfg = load_config_api_only(config_path)
    assert cfg.token == "kbr_file"


def test_token_file_expands_tilde(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    A leading ``~`` in ``token_file`` is expanded against ``HOME``.
    """
    monkeypatch.delenv("KANBAROO_TOKEN", raising=False)
    monkeypatch.delenv("KANBAROO_API_URL", raising=False)
    monkeypatch.delenv("KANBAROO_DATABASE_URL", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    token_path = tmp_path / "token"
    token_path.write_text("kbr_tilde\n", encoding="utf-8")
    config_path = _write_config(
        tmp_path,
        'api_url = "http://t.invalid"\ntoken_file = "~/token"\n',
    )
    cfg = load_config_api_only(config_path)
    assert cfg.token == "kbr_tilde"


def test_token_file_missing_raises_malformed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    A ``token_file`` pointing at a nonexistent path raises the same
    error class the legacy missing-``token`` branch does.
    """
    monkeypatch.delenv("KANBAROO_TOKEN", raising=False)
    monkeypatch.delenv("KANBAROO_API_URL", raising=False)
    monkeypatch.delenv("KANBAROO_DATABASE_URL", raising=False)
    config_path = _write_config(
        tmp_path,
        f'api_url = "http://t.invalid"\ntoken_file = "{tmp_path / "nope"}"\n',
    )
    with pytest.raises(ConfigMalformedError) as excinfo:
        load_config_api_only(config_path)
    assert "does not exist" in str(excinfo.value)


def test_token_file_empty_raises_malformed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    A whitespace-only ``token_file`` raises
    :class:`ConfigMalformedError`.
    """
    monkeypatch.delenv("KANBAROO_TOKEN", raising=False)
    monkeypatch.delenv("KANBAROO_API_URL", raising=False)
    monkeypatch.delenv("KANBAROO_DATABASE_URL", raising=False)
    token_path = tmp_path / "token"
    token_path.write_text("\n   \n", encoding="utf-8")
    config_path = _write_config(
        tmp_path,
        f'api_url = "http://t.invalid"\ntoken_file = "{token_path}"\n',
    )
    with pytest.raises(ConfigMalformedError) as excinfo:
        load_config_api_only(config_path)
    assert "is empty" in str(excinfo.value)


def test_legacy_token_emits_deprecation_warning(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    Falling back to the deprecated ``token`` field emits a
    :class:`DeprecationWarning` and still loads successfully.
    """
    monkeypatch.delenv("KANBAROO_TOKEN", raising=False)
    monkeypatch.delenv("KANBAROO_API_URL", raising=False)
    monkeypatch.delenv("KANBAROO_DATABASE_URL", raising=False)
    config_path = _write_config(
        tmp_path,
        'api_url = "http://t.invalid"\ntoken = "kbr_legacy"\n',
    )
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        cfg = load_config_api_only(config_path)
    assert cfg.token == "kbr_legacy"
    assert any(issubclass(w.category, DeprecationWarning) for w in caught)
