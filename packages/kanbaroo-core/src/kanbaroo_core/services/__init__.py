"""
Service layer: the boundary where every mutation is audited and where
the concurrency and soft-delete invariants are enforced.

Per ``CLAUDE.md`` and ``docs/spec.md``, audit emission lives here rather
than in the endpoint layer so new REST surfaces cannot accidentally
bypass it. Endpoints are expected to be thin wrappers: validate input,
resolve the actor, call a single service function, translate any raised
exceptions into HTTP responses.

Public submodules:

* :mod:`kanbaroo_core.services.audit` exposes :func:`emit_audit`, the
  single helper every service uses to record a mutation.
* :mod:`kanbaroo_core.services.events` exposes :func:`publish_event`,
  the companion helper that buffers a WebSocket notification event
  for emission after the caller's transaction commits.
* :mod:`kanbaroo_core.services.exceptions` defines the domain errors
  services raise; API layers translate these into the wire error shape.
* :mod:`kanbaroo_core.services.workspaces` holds CRUD for workspaces.
* :mod:`kanbaroo_core.services.epics` holds CRUD plus close/reopen for
  epics.
* :mod:`kanbaroo_core.services.stories` holds CRUD plus state-machine
  transition logic for stories.
* :mod:`kanbaroo_core.services.tokens` holds thin wrappers around
  :mod:`kanbaroo_core.auth` for use by REST handlers. Tokens are not
  audited (see ``docs/spec.md`` section 3.3).
"""

from kanbaroo_core.services import (
    audit,
    comments,
    epics,
    events,
    exceptions,
    linkages,
    stories,
    tags,
    tokens,
    workspaces,
)
from kanbaroo_core.services.audit import emit_audit
from kanbaroo_core.services.events import publish_event
from kanbaroo_core.services.exceptions import (
    NotFoundError,
    ValidationError,
    VersionConflictError,
)
from kanbaroo_core.services.stories import InvalidStateTransitionError

__all__ = [
    "InvalidStateTransitionError",
    "NotFoundError",
    "ValidationError",
    "VersionConflictError",
    "audit",
    "comments",
    "emit_audit",
    "epics",
    "events",
    "exceptions",
    "linkages",
    "publish_event",
    "stories",
    "tags",
    "tokens",
    "workspaces",
]
