"""RefreshToken — opaque, single-use, rotated; replay triggers chain revocation.

TODO(deferred): add user_agent and ip_address columns for session forensics + a
"sign me out everywhere" feature. Currently we revoke per-chain, not per-device.
Deferred past phase-13 — not needed for demo mode; revisit if real users land.
"""

from datetime import datetime
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from promptforge_api.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class RefreshToken(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "refresh_tokens"

    user_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    org_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("orgs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    chain_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    token_hmac: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    parent_id: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("refresh_tokens.id", ondelete="SET NULL"),
        nullable=True,
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    replaced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    def __repr__(self) -> str:
        return f"<RefreshToken id={self.id} chain_id={self.chain_id} user_id={self.user_id}>"
