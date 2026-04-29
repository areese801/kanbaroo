"""
Tests for :class:`kanbaroo_core.actor.Actor` behavior.

The ``Actor`` dataclass is a small value type but it is threaded through
the whole service layer, so its invariants (frozen, hashable, value
equality) are worth pinning explicitly.
"""

from dataclasses import FrozenInstanceError

import pytest

from kanbaroo_core import Actor, ActorType


def test_actor_value_equality() -> None:
    """
    Two actors with the same type and id compare equal.
    """
    a = Actor(type=ActorType.HUMAN, id="adam")
    b = Actor(type=ActorType.HUMAN, id="adam")
    assert a == b


def test_actor_inequality_on_type() -> None:
    """
    Different actor types are not equal even with the same id.
    """
    human = Actor(type=ActorType.HUMAN, id="adam")
    claude = Actor(type=ActorType.CLAUDE, id="adam")
    assert human != claude


def test_actor_is_hashable() -> None:
    """
    Actors are hashable so they can be used as dict keys or in sets.
    """
    a = Actor(type=ActorType.HUMAN, id="adam")
    b = Actor(type=ActorType.HUMAN, id="adam")
    c = Actor(type=ActorType.CLAUDE, id="outer-claude")
    assert {a, b, c} == {a, c}


def test_actor_is_frozen() -> None:
    """
    Actors are immutable; attribute assignment raises.
    """
    actor = Actor(type=ActorType.HUMAN, id="adam")
    with pytest.raises(FrozenInstanceError):
        actor.id = "not-adam"  # type: ignore[misc]
