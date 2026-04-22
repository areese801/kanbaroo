# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**Kanberoo** is a kanban-style issue tracker with a TUI, REST + WebSocket API, CLI, and MCP server. It is designed to be useful standalone and to integrate with trusty-cage for AI-driven workflows. Full design documented in `docs/spec.md`.

The canonical source of design intent is `docs/spec.md`. When in doubt, consult it before making architectural decisions.

## Core Principles (non-negotiable)

These principles are load-bearing. Violating them requires an explicit discussion and a spec update, not a unilateral implementation decision.

- **Data portability is a feature.** The SQLite or Postgres schema is public. External tools (DuckDB, Snowflake, GitHub Actions) read it directly. Never add application-layer magic that breaks this contract.
- **Audit everything.** Every mutation is logged with actor attribution (`human`, `claude`, or `system`). Audit emission lives in the service layer, not the endpoint layer, so new endpoints can't accidentally bypass it.
- **Soft delete everywhere.** Hard deletes are not a supported operation. If you find yourself needing one, stop and ask the user.
- **Optimistic concurrency.** Every mutable entity has a `version`. Every mutation requires `If-Match`. No exceptions.
- **REST is the source of truth; WebSocket is a notification layer.** Clients treat WebSocket events as hints to refetch, not as authoritative state.
- **Keep design docs in sync with code.** `docs/spec.md`, this `CLAUDE.md`, and any workflow skills (see `docs/future-skill-draft.md` until phase 1 is complete) form an interlocking set. When a change in one invalidates wording in another, update both in the same PR. Drifting docs are worse than no docs. See "Documentation Sync Responsibilities" below.

## Build & Development

This is a uv workspace monorepo. Install everything in dev mode:

```bash
# Install everything in dev mode via uv
uv sync --all-packages --dev

# Run the server (local dev)
uv run kanberoo server start

# Lint & format
uv run ruff format .
uv run ruff check --fix .

# Type check
uv run mypy packages/

# Tests
uv run pytest                                    # All tests
uv run pytest packages/kanberoo-core/tests       # Single package
uv run pytest -k test_story_transition           # Single test pattern

# Migrations
uv run alembic -c packages/kanberoo-core/alembic.ini upgrade head
uv run alembic -c packages/kanberoo-core/alembic.ini revision --autogenerate -m "description"

# Docker dev loop
docker compose up -d
docker compose logs -f kanberoo-api
```

### Web UI development

The `kanberoo-web` package ships a Vite + React SPA under `packages/kanberoo-web/frontend/`. The production build lives at `packages/kanberoo-web/src/kanberoo_web/dist/` and is committed so the wheel picks it up; only the built output, not the sources, needs to be in the wheel.

```bash
# Install Node deps + build the SPA into src/kanberoo_web/dist/
make web-build

# Run the Vite dev server (proxies /api and /api/v1/events to :8080)
make web-dev

# Run the frontend test suite (vitest, single-shot)
make web-test
```

Node 20+ is required at build time. `make publish` does not yet rebuild the frontend automatically; that wiring lands in milestone M6.

## Repo Structure

```
kanberoo/
├── docs/
│   ├── spec.md                  # Authoritative design doc
│   └── ...                      # Additional design docs
├── packages/
│   ├── kanberoo-core/           # Models, schemas, business logic, migrations
│   ├── kanberoo-api/            # FastAPI server (REST + WebSocket)
│   ├── kanberoo-tui/            # Textual TUI
│   ├── kanberoo-cli/            # Typer CLI (also the `kanberoo` entry point)
│   └── kanberoo-mcp/            # MCP server
├── tests/                       # Cross-package integration tests
├── docker-compose.yml
├── Dockerfile
└── pyproject.toml               # uv workspace root
```

**Which package does this code belong in?**

- Database models, Pydantic schemas, state machine logic, audit emission → `kanberoo-core`
- HTTP endpoints, WebSocket handlers, auth middleware → `kanberoo-api`
- Textual widgets, screens, and TUI app logic → `kanberoo-tui`
- Typer commands and Rich formatting → `kanberoo-cli`
- MCP tool definitions (thin wrappers over the REST API) → `kanberoo-mcp`

When in doubt, business logic belongs in core. API packages should be thin.

## Code Conventions

### General

- All imports at the top of the file. No inline or lazy imports.
- Type hints on every function signature.
- Docstrings on public functions, classes, and modules. Skip them on obvious private helpers.
- Prefer composition over inheritance. Use protocols for interfaces.

### SQLAlchemy & Pydantic

- SQLAlchemy 2.x declarative style with `Mapped[]` type annotations.
- Pydantic v2 for all request and response schemas.
- Never expose SQLAlchemy models directly through the API; always convert to Pydantic.
- `kanberoo-core` defines both the ORM models and the Pydantic schemas. API packages import from core.
- Use SQLAlchemy sessions via dependency injection in FastAPI endpoints; never instantiate sessions in business logic.
- **UUIDs are v7**, generated via the `uuid-utils` library (Rust-backed, fast). Do not use `uuid.uuid4()` from the stdlib for primary keys; v7 is required for insert locality and sortability. The library name is unfortunately generic; the version is what matters.

### FastAPI

- Endpoints are thin: validate input, call a service function, return the response.
- Business logic lives in `kanberoo_core.services.*`.
- Every mutating endpoint requires `If-Match` and returns `ETag`.
- Error responses use the standard shape defined in `kanberoo_core.errors`.

### Testing

- Unit tests live next to the code they test: `packages/<name>/tests/`.
- Integration tests that cross package boundaries live in the top-level `tests/`.
- Use fixtures for database setup; each test gets a clean SQLite in-memory DB.
- Aim for meaningful coverage, not percentage targets. Invariant tests (state machine transitions, audit emission, concurrency) are more valuable than line coverage.

### Before committing

1. `uv run ruff format .`
2. `uv run ruff check --fix .`
3. `uv run mypy packages/`
4. `uv run pytest`
5. Manual smoke test of any changed surface (TUI, CLI, or API) against a real running server.

## Key Architectural Patterns

### Actor Attribution

Every mutation records who did it. The pattern:

1. Auth middleware resolves the API token to an `Actor` (a dataclass with `type` and `id`).
2. The `Actor` is attached to the request state and available via FastAPI dependency.
3. Service functions accept `actor: Actor` as a parameter and pass it to audit emission.
4. The audit log row stamps `actor_type` and `actor_id`.

Never call a service function without an actor. There's no "anonymous" mutation path.

### Audit Emission

Every mutation emits an audit event. The pattern lives in `kanberoo_core.services.audit`:

```python
def emit_audit(session, actor, entity_type, entity_id, action, before, after):
    # Computes diff, inserts into audit_events, emits WebSocket event
```

Services call this after every successful mutation, within the same transaction. Never emit from the endpoint layer; services are the boundary.

### Optimistic Concurrency

Every mutable entity has a `version` column. The pattern:

1. Read returns `ETag: <version>` header.
2. Write requires `If-Match: <version>` header.
3. Service function compares, rejects with 412 if mismatched.
4. On success, increments `version` atomically with the update.

If you're adding a new mutable entity, follow this pattern. If you're adding a new mutation, verify the If-Match check is in place.

### WebSocket Event Emission

Events are published to an in-process pub-sub bus in `kanberoo_core.events`. The API's WebSocket layer subscribes and forwards to connected clients.

Services call `publish_event(...)` after a successful mutation, within the same transaction boundary (but after commit, so clients don't see events for rolled-back writes).

## Git Workflow

- Work happens on feature branches off `main`.
- Merges to `main` are done via PR on GitHub. Never merge locally.
- Before opening a PR, update `CHANGELOG.md` with an entry under the upcoming release.
- User-facing changes must appear in the changelog.

## Release Workflow

### Publishing to PyPI

All six packages are published together from a single `make publish` at the repo root. The Makefile drives `uv build --all-packages` into `dist/`, then `uv publish` uploads everything, then a `v<version>` git tag is pushed.

```bash
git checkout main && git pull
source set_creds.sh            # exports UV_PUBLISH_TOKEN
make publish                   # builds, uploads, tags
```

- `set_creds.sh` sits at the repo root and is gitignored via the `set_creds*.sh` pattern. It exports `UV_PUBLISH_TOKEN` before `make publish` runs `uv publish`. Do not commit it or quote it in chat.
- Always merge to `main` via PR before publishing. Never publish from an unmerged branch (the `tag` step pushes against the current `HEAD`).
- Each package has its own version in its own `pyproject.toml`. The top-level meta-package version tracks the overall release and is what `make tag` reads.
- The initial PyPI release was `0.1.0` on 2026-04-19 and covers `kanberoo`, `kanberoo-core`, `kanberoo-api`, `kanberoo-cli`, `kanberoo-tui`, `kanberoo-mcp`. `kanberoo-web` is reserved at `0.0.1` as a placeholder for phase 2.

### Per-package READMEs are required

Every sub-package (`packages/kanberoo-*`) MUST have its own `README.md` next to its `pyproject.toml`, and the `pyproject.toml` `readme` field MUST point at that local file (`readme = "README.md"`).

Do NOT use `readme = "../../README.md"` to reference the root README: `uv build --all-packages` builds each sub-package's sdist first and then the wheel from the sdist, and the sdist does not include files from the parent directory. The wheel build fails with `OSError: Readme file does not exist: ../../README.md`. This is a build-system constraint, not a policy choice.

### Local install for Claude Desktop / other end users

```bash
pipx install --include-deps 'kanberoo[all]'
```

`--include-deps` is load-bearing: without it, pipx only exposes the meta-package's apps (none), so `kb`, `kanberoo-mcp`, `kanberoo-tui`, `kanberoo-api`, and `kanberoo` all stay hidden in the isolated venv.

## Versioning

This project follows [Semantic Versioning](https://semver.org/).

- **MAJOR**: breaking changes to the REST API schema, WebSocket event shapes, or database schema migrations that require manual intervention.
- **MINOR**: new features, backwards-compatible.
- **PATCH**: bug fixes, docs-only changes.

Database migrations should always be backwards-compatible within a minor version. Breaking migrations bump the major version.

## Working with the Spec

`docs/spec.md` is the source of truth for design intent. When implementing a feature:

1. Re-read the relevant section of the spec before starting.
2. If the spec is ambiguous or silent, raise it with the user rather than inferring.
3. If you need to deviate from the spec, propose the change and update the spec in the same PR as the implementation.

The open questions section of the spec (section 10) lists decisions we've explicitly punted. Don't resolve them unilaterally; bring them up.

## Documentation Sync Responsibilities

Kanberoo has multiple interlocking documents. When you change one, check whether the others need updates in the same PR:

- **`docs/spec.md`** — authoritative design intent. Update when: architecture changes, new entities or endpoints are added, open questions are resolved, or phase scope changes.
- **`CLAUDE.md`** (this file) — guidance for Claude Code working in the repo. Update when: code conventions change, new non-negotiable principles emerge, the build or test workflow changes, or new architectural patterns are introduced.
- **`docs/future-skill-draft.md`** (until phase 1 completes, then promoted to a real skill) — guidance for the outer Claude using Kanberoo via MCP. Update when: MCP tool names or shapes change, new workflows emerge, or attribution semantics shift.
- **`README.md`** — user-facing introduction. Update when: installation steps change, the feature list changes meaningfully, or the quickstart no longer works.
- **`CHANGELOG.md`** — always updated for user-facing changes, per the Git Workflow section.

**Before committing any PR, run through this checklist:**

1. Did I change something the spec describes? → Update `docs/spec.md`.
2. Did I change a code convention, build step, or architectural pattern? → Update this `CLAUDE.md`.
3. Did I change an MCP tool name, signature, or intended workflow? → Update the workflow skill draft.
4. Did I add or remove user-facing functionality? → Update `README.md` and `CHANGELOG.md`.
5. Did I resolve an open question from spec section 10? → Remove it from the open questions list and fold the resolution into the main text.

If you notice existing docs are already out of sync (from prior work or spec drift), flag it to the user. Don't silently fix or silently ignore. Drift is a signal worth surfacing.

## Kanberoo uses Kanberoo

Once phase 1 is sufficiently functional, Kanberoo's own work tracking moves into Kanberoo itself. This will be delightfully recursive and is the first real-world test of the tool.

## Things NOT to do

- Don't add hard-delete endpoints.
- Don't add custom issue types, custom fields, or custom workflow states. The schema is what it is.
- Don't add attachments or file uploads (deferred to a later phase).
- Don't add outbound webhooks (WebSocket and DB reads are the integration surface).
- Don't bypass the audit log, not even for "internal" operations.
- Don't skip `If-Match` on mutations.
- Don't write business logic in endpoints or TUI widgets.
- Don't import SQLAlchemy session from anywhere but the FastAPI dependency system.
- Don't use em-dashes in user-facing strings or docs. (Project convention.)
