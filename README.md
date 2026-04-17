# Kanberoo

A kanban-style issue tracker with a TUI, REST + WebSocket API, CLI, and MCP server. Designed to be useful standalone, and to integrate with [trusty-cage](https://pypi.org/project/trusty-cage/) for AI-driven workflows.

**Status:** Phase 1 in progress. The canonical design lives in [`docs/spec.md`](docs/spec.md).

## Quickstart

Requires Python 3.12+ and [uv](https://docs.astral.sh/uv/).

```bash
# Install everything in dev mode
uv sync --all-packages --dev

# Run tests
uv run pytest

# Format and lint
uv run ruff format .
uv run ruff check --fix .

# Type check
uv run mypy packages/
```

Server, CLI, and TUI entry points come online in later phase 1 milestones (see `docs/spec.md` section 9.1).

## Packages

Kanberoo is a uv workspace with five packages:

- **`kanberoo-core`** — models, Pydantic schemas, business logic, migrations
- **`kanberoo-api`** — FastAPI server (REST + WebSocket)
- **`kanberoo-tui`** — Textual terminal UI
- **`kanberoo-cli`** — Typer command-line interface (provides the `kanberoo` and `kb` commands)
- **`kanberoo-mcp`** — MCP server for AI agent integration

## Docs

- [`docs/spec.md`](docs/spec.md) — authoritative design intent
- [`docs/future-skill-draft.md`](docs/future-skill-draft.md) — draft workflow skill for AI agents using Kanberoo via MCP (revisit after phase 1 completes)
- [`CLAUDE.md`](CLAUDE.md) — guidance for Claude Code when working in this repo
- [`CHANGELOG.md`](CHANGELOG.md)

## License

MIT.
