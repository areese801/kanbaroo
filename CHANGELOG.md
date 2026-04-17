# Changelog

All notable changes to Kanberoo are recorded here. This project follows [Semantic Versioning](https://semver.org/) and [Keep a Changelog](https://keepachangelog.com/).

## [Unreleased]

### Added
- `kanberoo-core` service layer (`kanberoo_core.services`): `services.audit.emit_audit` writes an immutable `audit_events` row inside the caller's transaction with a full `{"before": ..., "after": ...}` diff; `services.workspaces` covers workspace CRUD (create, list with opaque cursor pagination, get, patch, soft delete); `services.tokens` wraps the auth helpers for use by REST handlers. Service-level domain exceptions (`NotFoundError`, `VersionConflictError`, `ValidationError`) decouple services from transport.
- `ApiTokenCreate` and `ApiTokenCreatedRead` Pydantic schemas for the token surface. `ApiTokenCreatedRead` carries the plaintext in the create response only; subsequent reads return the masked `ApiTokenRead`.
- `kanberoo-api` FastAPI application: `create_app` factory, `kanberoo-api` console script entry point (uvicorn), request-scoped session dependency that owns transaction boundaries, bearer-token auth dependency that resolves to an `Actor`, and `If-Match` / `ETag` helpers.
- REST endpoints for milestone 4 (spec section 4.2): `GET/POST /api/v1/workspaces`, `GET/PATCH/DELETE /api/v1/workspaces/{id}`, `GET/POST /api/v1/tokens`, `DELETE /api/v1/tokens/{id}`. Every mutating endpoint requires `If-Match` and returns `ETag`; create responses also return `Location`.
- Canonical error envelope (`{"error": {"code", "message", "details"}}`) wired across 400, 401, 404, 412, and 500 via FastAPI exception handlers. Domain errors raised by services translate directly into this shape.
- Audit coverage invariant: every workspace mutation (create, update, soft delete) writes exactly one attributed `audit_events` row from the service layer. Token operations are deliberately excluded (per spec section 3.3) and covered by a negative test.
- Integration test suite for the REST surface (`packages/kanberoo-api/tests/`): workspace CRUD with ETag/If-Match/412 semantics, cursor pagination across 150 rows, soft-delete visibility, token plaintext-once contract, revoked-token auth rejection, the canonical error shape on every status class, and the no-audit-on-tokens invariant.
- Ruff `extend-immutable-calls` for `fastapi.Depends/Query/Path/Header/Body/Form/Cookie` and `typer.Option/Argument`, so B008 does not flag standard FastAPI/Typer dependency-injection idioms.
- Initial repo scaffold: uv workspace with five packages (`kanberoo-core`, `kanberoo-api`, `kanberoo-tui`, `kanberoo-cli`, `kanberoo-mcp`) and a top-level `kanberoo` meta-package with an `[all]` extra.
- Dockerfile and docker-compose.yml for local development.
- Ruff, mypy, and pytest configuration at the workspace root.
- Design docs: `docs/spec.md` and `docs/future-skill-draft.md`.
- Branch protection on `main`.
- `kanberoo-core` data layer: SQLAlchemy 2.x ORM models for every entity in spec section 3.3 (workspaces, workspace_repos, epics, stories, linkages, comments, tags, story_tags, audit_events, api_tokens) with UUID v7 primary keys, ISO 8601 UTC timestamps, soft delete, and SQLAlchemy `version_id_col` optimistic concurrency.
- Pydantic v2 Create/Update/Read schemas for every mutable entity, plus Read-only schemas for `audit_events` and `api_tokens`.
- Atomic `generate_human_id` helper that bumps `workspaces.next_issue_num` under `SELECT ... FOR UPDATE` and returns the next `{KEY}-{N}` identifier (shared across stories and epics).
- Initial Alembic migration (`0001_initial`) producing the full spec section 3.3 schema, with partial indexes on soft-delete columns and CHECK constraints on every fixed-domain enum column.
- `kanberoo-core` auth layer: frozen `Actor` dataclass plus `hash_token`, `generate_token_plaintext`, `create_token`, `validate_token`, and `revoke_token` helpers, with SHA-256 hashing and a `kbr_` plaintext prefix. Plaintext tokens are never persisted; only the hash is stored.
- `kanberoo-core` exposes `migrations.upgrade_to_head` so the CLI can run Alembic programmatically without depending on `alembic.ini` location; the `alembic/` directory is also force-included into the wheel.
- `kanberoo-cli` Typer scaffold with `kanberoo` and `kb` entry points, plus a `kb init` command that creates `$KANBEROO_CONFIG_DIR` (default `~/.kanberoo`), applies migrations to a fresh SQLite database, issues the first human API token, writes `config.toml`, and prints the plaintext exactly once.

### Fixed
- Model `Enum` columns now store the lowercase `.value` (e.g. `human`) via a shared `enum_values` helper, matching the spec and the Alembic migration CHECK constraints. Before this fix, SQLAlchemy defaulted to the enum `name` (e.g. `HUMAN`), which diverged from the migration-created schema and would reject inserts on a freshly-migrated database.
