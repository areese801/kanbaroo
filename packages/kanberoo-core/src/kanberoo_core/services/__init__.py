"""
Service layer: the boundary where every mutation is audited and where
the concurrency and soft-delete invariants are enforced.

Per ``CLAUDE.md`` and ``docs/spec.md``, audit emission lives here rather
than in the endpoint layer so new REST surfaces cannot accidentally
bypass it. Endpoints are expected to be thin wrappers: validate input,
resolve the actor, call a single service function, translate any raised
exceptions into HTTP responses.

Public submodules:

* :mod:`kanberoo_core.services.audit` exposes :func:`emit_audit`, the
  single helper every service uses to record a mutation.
* :mod:`kanberoo_core.services.exceptions` defines the domain errors
  services raise; API layers translate these into the wire error shape.
* :mod:`kanberoo_core.services.workspaces` holds CRUD for workspaces.
* :mod:`kanberoo_core.services.epics` holds CRUD plus close/reopen for
  epics.
* :mod:`kanberoo_core.services.stories` holds CRUD plus state-machine
  transition logic for stories.
* :mod:`kanberoo_core.services.tokens` holds thin wrappers around
  :mod:`kanberoo_core.auth` for use by REST handlers. Tokens are not
  audited (see ``docs/spec.md`` section 3.3).
"""

from kanberoo_core.services import (
    audit,
    epics,
    exceptions,
    stories,
    tokens,
    workspaces,
)
from kanberoo_core.services.audit import emit_audit
from kanberoo_core.services.exceptions import (
    NotFoundError,
    ValidationError,
    VersionConflictError,
)
from kanberoo_core.services.stories import InvalidStateTransitionError

__all__ = [
    "InvalidStateTransitionError",
    "NotFoundError",
    "ValidationError",
    "VersionConflictError",
    "audit",
    "emit_audit",
    "epics",
    "exceptions",
    "stories",
    "tokens",
    "workspaces",
]
