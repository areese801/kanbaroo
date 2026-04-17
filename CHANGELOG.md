# Changelog

All notable changes to Kanberoo are recorded here. This project follows [Semantic Versioning](https://semver.org/) and [Keep a Changelog](https://keepachangelog.com/).

## [Unreleased]

### Added
- Initial repo scaffold: uv workspace with five packages (`kanberoo-core`, `kanberoo-api`, `kanberoo-tui`, `kanberoo-cli`, `kanberoo-mcp`) and a top-level `kanberoo` meta-package with an `[all]` extra.
- Dockerfile and docker-compose.yml for local development.
- Ruff, mypy, and pytest configuration at the workspace root.
- Design docs: `docs/spec.md` and `docs/future-skill-draft.md`.
- Branch protection on `main`.
- `kanberoo-core` data layer: SQLAlchemy 2.x ORM models for every entity in spec section 3.3 (workspaces, workspace_repos, epics, stories, linkages, comments, tags, story_tags, audit_events, api_tokens) with UUID v7 primary keys, ISO 8601 UTC timestamps, soft delete, and SQLAlchemy `version_id_col` optimistic concurrency.
- Pydantic v2 Create/Update/Read schemas for every mutable entity, plus Read-only schemas for `audit_events` and `api_tokens`.
- Atomic `generate_human_id` helper that bumps `workspaces.next_issue_num` under `SELECT ... FOR UPDATE` and returns the next `{KEY}-{N}` identifier (shared across stories and epics).
- Initial Alembic migration (`0001_initial`) producing the full spec section 3.3 schema, with partial indexes on soft-delete columns and CHECK constraints on every fixed-domain enum column.
