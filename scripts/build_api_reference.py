"""
Build a Markdown reference for the Kanberoo REST API.

Imports :func:`kanberoo_api.app.create_app`, pulls the OpenAPI 3.x
schema, and renders a compact Markdown document grouped by tag. Writes
the result to ``docs/api-reference.md`` at the repo root.

Run with::

    uv run python scripts/build_api_reference.py

The script is intentionally stdlib-only (plus the already-declared
FastAPI dependency it pulls via :func:`create_app`). It has to stay
reproducible for the CI and orchestrator gates: a second run on the
same code must produce a byte-identical file.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
OUTPUT_PATH = REPO_ROOT / "docs" / "api-reference.md"

HEADER = (
    "# Kanberoo REST API\n"
    "\n"
    "Generated file. Do not edit by hand. Run "
    "`uv run python scripts/build_api_reference.py` to regenerate.\n"
    "\n"
    "Source: `packages/kanberoo-api/src/kanberoo_api/` OpenAPI schema.\n"
)


def _resolve_ref(schema: dict[str, Any], ref: str) -> tuple[str, dict[str, Any]]:
    """
    Resolve a JSON-Schema ``$ref`` pointer against the OpenAPI document.

    Returns the name of the referenced schema and its body. Supports
    only the ``#/components/schemas/<Name>`` shape that FastAPI emits;
    anything else raises :class:`ValueError` so surprises surface
    loudly instead of silently falling through.
    """
    prefix = "#/components/schemas/"
    if not ref.startswith(prefix):
        raise ValueError(f"unexpected $ref shape: {ref!r}")
    name = ref[len(prefix) :]
    body = schema.get("components", {}).get("schemas", {}).get(name)
    if body is None:
        raise ValueError(f"dangling $ref: {ref!r}")
    return name, body


def _type_label(field_schema: dict[str, Any]) -> str:
    """
    Render a one-line type label for a field schema.

    Handles ``$ref``, ``anyOf``/``oneOf`` unions, enums, arrays, and
    plain scalars. Unknown shapes fall back to ``"object"`` so the
    script never crashes on a schema it has not seen before.
    """
    ref = field_schema.get("$ref")
    if ref:
        return ref.rsplit("/", 1)[-1]
    for key in ("anyOf", "oneOf"):
        branches = field_schema.get(key)
        if isinstance(branches, list) and branches:
            parts = [_type_label(branch) for branch in branches]
            return " | ".join(parts)
    enum = field_schema.get("enum")
    if enum:
        return " | ".join(repr(v) for v in enum)
    raw_type = field_schema.get("type")
    if raw_type == "array":
        items = field_schema.get("items", {})
        return f"array<{_type_label(items)}>"
    if raw_type == "null":
        return "null"
    if isinstance(raw_type, str):
        return raw_type
    if isinstance(raw_type, list):
        return " | ".join(raw_type)
    return "object"


def _escape_cell(text: str) -> str:
    """
    Escape a cell value for a Markdown table.
    """
    return text.replace("|", "\\|").replace("\n", " ")


def _render_field_rows(schema_body: dict[str, Any]) -> list[str]:
    """
    Render the table rows for a schema body's ``properties`` map.
    """
    properties = schema_body.get("properties", {})
    required = set(schema_body.get("required", []))
    rows: list[str] = []
    for name, prop in properties.items():
        type_label = _type_label(prop)
        req = "yes" if name in required else "no"
        description = prop.get("description") or prop.get("title") or ""
        rows.append(
            f"| `{name}` | `{_escape_cell(type_label)}` | {req} | "
            f"{_escape_cell(description)} |"
        )
    return rows


def _render_schema_reference(name: str, body: dict[str, Any]) -> list[str]:
    """
    Render a single schema block.

    Produces a heading, a description paragraph, and (for object
    schemas) a four-column table of fields.
    """
    lines = [f"### `{name}`", ""]
    description = body.get("description")
    if description:
        lines.append(description.strip())
        lines.append("")
    enum = body.get("enum")
    if enum:
        lines.append("Enum values: " + ", ".join(f"`{v}`" for v in enum))
        lines.append("")
        return lines
    rows = _render_field_rows(body)
    if rows:
        lines.append("| Field | Type | Required | Description |")
        lines.append("|-------|------|----------|-------------|")
        lines.extend(rows)
        lines.append("")
    return lines


def _request_body_summary(
    schema: dict[str, Any],
    operation: dict[str, Any],
) -> list[str]:
    """
    Render a request-body summary for a single operation.
    """
    request_body = operation.get("requestBody")
    if not request_body:
        return []
    content = request_body.get("content", {})
    json_media = content.get("application/json")
    if not json_media:
        return []
    body_schema = json_media.get("schema", {})
    ref = body_schema.get("$ref")
    if ref:
        name, _ = _resolve_ref(schema, ref)
        return [f"  - Request body: `{name}`"]
    label = _type_label(body_schema)
    return [f"  - Request body: `{label}`"]


def _response_summary(
    schema: dict[str, Any],
    operation: dict[str, Any],
) -> list[str]:
    """
    Render a response summary listing every documented status code.
    """
    lines: list[str] = []
    responses = operation.get("responses", {})
    for status_code in sorted(responses.keys()):
        resp = responses[status_code]
        description = resp.get("description", "")
        content = resp.get("content", {})
        json_media = content.get("application/json")
        schema_label = ""
        if json_media:
            resp_schema = json_media.get("schema", {})
            ref = resp_schema.get("$ref")
            if ref:
                name, _ = _resolve_ref(schema, ref)
                schema_label = f" -> `{name}`"
            else:
                label = _type_label(resp_schema)
                if label and label != "object":
                    schema_label = f" -> `{label}`"
        suffix = f" ({description})" if description else ""
        lines.append(f"  - Response `{status_code}`{suffix}{schema_label}")
    return lines


def _render_operation(
    schema: dict[str, Any],
    path: str,
    method: str,
    operation: dict[str, Any],
) -> list[str]:
    """
    Render a single operation (one METHOD + PATH pair).
    """
    summary = operation.get("summary", "").strip()
    description = (operation.get("description") or "").strip()
    heading = f"- `{method.upper()} {path}`"
    if summary:
        heading = f"{heading} - {summary}"
    lines = [heading]
    if description:
        for block_line in description.splitlines():
            lines.append(f"    {block_line}")
    lines.extend(_request_body_summary(schema, operation))
    lines.extend(_response_summary(schema, operation))
    lines.append("")
    return lines


def _group_paths_by_tag(
    schema: dict[str, Any],
) -> dict[str, list[tuple[str, str, dict[str, Any]]]]:
    """
    Group operations by their primary tag.

    Each value is a list of ``(path, method, operation)`` triples. Paths
    and methods are sorted deterministically so the output file is
    reproducible.
    """
    grouped: dict[str, list[tuple[str, str, dict[str, Any]]]] = {}
    for path, path_item in schema.get("paths", {}).items():
        for method, operation in path_item.items():
            if method.lower() not in {
                "get",
                "post",
                "put",
                "patch",
                "delete",
                "options",
                "head",
            }:
                continue
            tags = operation.get("tags") or ["untagged"]
            primary = tags[0]
            grouped.setdefault(primary, []).append((path, method, operation))
    for entries in grouped.values():
        entries.sort(key=lambda entry: (entry[0], entry[1]))
    return grouped


def render_markdown(schema: dict[str, Any]) -> str:
    """
    Render the full Markdown document for ``schema``.
    """
    lines: list[str] = [HEADER, ""]
    lines.append("## Endpoints")
    lines.append("")
    grouped = _group_paths_by_tag(schema)
    for tag in sorted(grouped.keys()):
        lines.append(f"### {tag}")
        lines.append("")
        for path, method, operation in grouped[tag]:
            lines.extend(_render_operation(schema, path, method, operation))
    schemas = schema.get("components", {}).get("schemas", {})
    if schemas:
        lines.append("## Schemas")
        lines.append("")
        for name in sorted(schemas.keys()):
            lines.extend(_render_schema_reference(name, schemas[name]))
    text = "\n".join(lines).rstrip() + "\n"
    return text


def build() -> Path:
    """
    Generate the Markdown reference and write it to ``OUTPUT_PATH``.

    Returns the path that was written. Raises :class:`RuntimeError` if
    the generated content is empty (sign of a schema regression that
    the acceptance gate should catch).
    """
    os.environ.setdefault("KANBEROO_DATABASE_URL", "sqlite:///:memory:")
    from kanberoo_api.app import create_app

    app = create_app()
    schema = app.openapi()
    text = render_markdown(schema)
    if not text.strip():
        raise RuntimeError("render_markdown produced empty output")
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(text, encoding="utf-8")
    return OUTPUT_PATH


def main() -> int:
    """
    Script entry point.
    """
    path = build()
    print(f"wrote {path.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
