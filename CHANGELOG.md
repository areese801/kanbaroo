# Changelog

All notable changes to Kanberoo are recorded here. This project follows [Semantic Versioning](https://semver.org/) and [Keep a Changelog](https://keepachangelog.com/).

## [Unreleased]

### Added
- Initial repo scaffold: uv workspace with five packages (`kanberoo-core`, `kanberoo-api`, `kanberoo-tui`, `kanberoo-cli`, `kanberoo-mcp`) and a top-level `kanberoo` meta-package with an `[all]` extra.
- Dockerfile and docker-compose.yml for local development.
- Ruff, mypy, and pytest configuration at the workspace root.
- Design docs: `docs/spec.md` and `docs/future-skill-draft.md`.
- Branch protection on `main`.
