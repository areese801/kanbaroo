"""
Shared Pydantic configuration for read schemas.

Read schemas inherit from :class:`ReadModel` so they can be built directly
from SQLAlchemy ORM instances (``from_attributes=True``) and so enum
fields are serialised by their string value rather than their Python
identity (``use_enum_values=True``).
"""

from pydantic import BaseModel, ConfigDict


class ReadModel(BaseModel):
    """
    Base for read schemas. ``from_attributes`` enables ORM-mode
    construction; ``use_enum_values`` keeps API output stable across
    Python enum class changes.
    """

    model_config = ConfigDict(from_attributes=True, use_enum_values=True)


class WriteModel(BaseModel):
    """
    Base for create/update schemas. ``use_enum_values`` ensures payloads
    serialise enum fields as their string value when round-tripped.
    """

    model_config = ConfigDict(use_enum_values=True)
