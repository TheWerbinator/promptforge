"""ShareToken — opaque, revocable, optionally-expiring public read-only link.

Polymorphic by design: one token type points at any shareable resource via
(resource_type, resource_id). resource_id has no FK because the target table
varies; the public endpoint resolves it per type and 404s if the row is gone.

The token is stored hashed (HMAC, like RefreshToken) so a DB leak doesn't hand
out live share URLs. The plaintext is returned exactly once, at creation; the
public endpoint hashes the incoming token and looks up by the digest.
"""

from datetime import datetime
from enum import StrEnum
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy import Enum as SqlEnum
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from promptforge_api.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class ShareResourceType(StrEnum):
    PROMPT = "prompt"
    EVAL_BATCH = "eval_batch"


class ShareToken(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "share_tokens"

    org_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("orgs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    resource_type: Mapped[ShareResourceType] = mapped_column(
        SqlEnum(
            ShareResourceType,
            name="share_resource_type",
            native_enum=True,
            values_callable=lambda e: [m.value for m in e],
        ),
        nullable=False,
    )
    resource_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    token_hmac: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    created_by: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    def __repr__(self) -> str:
        return f"<ShareToken id={self.id} {self.resource_type}={self.resource_id}>"
