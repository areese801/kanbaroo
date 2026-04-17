"""
Query helpers shared across the codebase.

The most important of these is :func:`live`, which filters out soft-deleted
rows. Soft delete is a load-bearing invariant in Kanberoo (see
``docs/spec.md`` section 3.4) and any list query that should hide deleted
rows must apply this filter.
"""

from typing import Any

from sqlalchemy import Select

from kanberoo_core.models.base import SoftDeleteMixin


def live(stmt: Select[Any], *models: type[SoftDeleteMixin]) -> Select[Any]:
    """
    Restrict a SELECT statement to rows where ``deleted_at IS NULL``.

    Pass each soft-deletable model whose rows should be filtered. The
    helper is variadic so a single call can scope a join across multiple
    tables (e.g. ``live(stmt, Story, Epic)``).
    """
    for model in models:
        stmt = stmt.where(model.deleted_at.is_(None))
    return stmt
