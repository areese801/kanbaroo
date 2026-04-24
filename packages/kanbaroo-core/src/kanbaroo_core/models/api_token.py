"""
API token model.

This milestone only defines the table. Token issuance, hashing, and
validation live in milestone 3 (the auth layer); the spec calls for
``token_hash`` to store a SHA-256 of the plaintext token, with the
plaintext shown to the caller exactly once.
"""

from sqlalchemy import Enum, String
from sqlalchemy.orm import Mapped, mapped_column

from kanbaroo_core.db import Base, new_id
from kanbaroo_core.enums import ActorType, enum_values
from kanbaroo_core.time import utc_now_iso


class ApiToken(Base):
    """
    A bearer token. ``token_hash`` is the SHA-256 of the plaintext token
    value; the plaintext is never persisted.
    """

    __tablename__ = "api_tokens"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=new_id)
    token_hash: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    actor_type: Mapped[ActorType] = mapped_column(
        Enum(
            ActorType,
            native_enum=False,
            name="api_token_actor_type",
            create_constraint=True,
            values_callable=enum_values,
        ),
        nullable=False,
    )
    actor_id: Mapped[str] = mapped_column(String, nullable=False)
    name: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[str] = mapped_column(String, nullable=False, default=utc_now_iso)
    last_used_at: Mapped[str | None] = mapped_column(String, nullable=True)
    revoked_at: Mapped[str | None] = mapped_column(String, nullable=True)
