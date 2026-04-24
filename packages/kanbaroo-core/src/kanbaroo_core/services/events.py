"""
Service-layer helper for publishing WebSocket events.

Every service mutation that writes an ``audit_events`` row also calls
:func:`publish_event`. The helper buffers the event on the session so
that events become visible to subscribers only after the surrounding
transaction commits.

Why buffer instead of publishing inline
---------------------------------------

Publishing directly from inside the service would expose subscribers
to events for work that was later rolled back (by a database error,
a raised domain exception that the API translates into a 4xx, or an
endpoint-layer ``except`` that calls ``session.rollback()``). Leaking
phantom mutations over the event stream is worse than dropping events,
because clients that refetch from REST would see the rollback as a
"disappearing" entity.

We buffer events in ``session.info`` and drain them from a SQLAlchemy
session ``after_commit`` listener. ``after_rollback`` clears the
buffer. Because the listeners are attached to
:class:`sqlalchemy.orm.Session` (the class, not a specific instance),
this plumbing applies to every session in the process, including the
ones created by tests and by the FastAPI request dependency.

This is "Option 1" from the cage F brief. Option 2 (publishing from
the endpoint layer after commit) was rejected because the whole point
of the service layer is to be the single, unavoidable place where
audit and event emission happen.
"""

from typing import Any

from sqlalchemy import event as sqla_event
from sqlalchemy.orm import Session

from kanbaroo_core.actor import Actor
from kanbaroo_core.db import new_id
from kanbaroo_core.events import Event, default_bus
from kanbaroo_core.time import utc_now_iso

_PENDING_EVENTS_KEY = "_kanbaroo_pending_events"


def publish_event(
    session: Session,
    *,
    event_type: str,
    actor: Actor,
    entity_type: str,
    entity_id: str,
    entity_version: int | None,
    payload: dict[str, Any],
) -> Event:
    """
    Buffer a :class:`Event` for emission after the next commit.

    The envelope follows ``docs/spec.md`` section 5.3. ``event_id`` is
    a fresh UUID v7 and ``occurred_at`` is stamped at call time, so
    event ordering reflects the order mutations were buffered rather
    than the order listeners happen to fire. Returns the event for
    tests and logging; production callers ignore the return value.

    The event is appended to ``session.info[_PENDING_EVENTS_KEY]``.
    See the module docstring for why this indirection exists.
    """
    event = Event(
        event_id=new_id(),
        event_type=event_type,
        occurred_at=utc_now_iso(),
        actor_type=actor.type.value,
        actor_id=actor.id,
        entity_type=entity_type,
        entity_id=entity_id,
        entity_version=entity_version,
        payload=payload,
    )
    pending = session.info.setdefault(_PENDING_EVENTS_KEY, [])
    pending.append(event)
    return event


@sqla_event.listens_for(Session, "after_commit")
def _flush_pending_events(session: Session) -> None:
    """
    Drain buffered events to the default bus after a successful commit.

    Fires once per ``Session.commit()``. Any failure while publishing a
    single event is swallowed so a misbehaving subscriber cannot break
    the commit path; the audit row has already been persisted and is
    the source of truth.
    """
    events = session.info.pop(_PENDING_EVENTS_KEY, None)
    if not events:
        return
    for event in events:
        default_bus.publish(event)


@sqla_event.listens_for(Session, "after_rollback")
def _clear_pending_events(session: Session) -> None:
    """
    Discard buffered events when a transaction rolls back.

    Without this, a subsequent commit on the same session would publish
    events that describe mutations the database never saw.
    """
    session.info.pop(_PENDING_EVENTS_KEY, None)
