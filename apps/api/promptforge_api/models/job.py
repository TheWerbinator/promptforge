"""Job — Postgres-backed queue row.

Not org-scoped at the model level. Job payloads usually carry an org_id field so
workers can scope downstream work, but the queue itself is process-global —
workers across orgs share a single jobs table.

Uses BigInteger (BIGSERIAL) primary key, not UUID, because:
- Queue ordering wants a cheap monotonic key for FIFO-ish pulls.
- BIGSERIAL + (status, run_after) partial index gives us a fast claim query.
- UUIDs would add bytes and randomness with no benefit for an internal queue.
"""

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import BigInteger, DateTime, Index, Integer, String, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from promptforge_api.models.base import Base, TimestampMixin


class Job(TimestampMixin, Base):
    __tablename__ = "jobs"
    __table_args__ = (
        # Partial index makes the claim query (status='queued' AND run_after <= now())
        # walk only pending rows. Done/failed rows don't bloat the index.
        Index(
            "ix_jobs_pull",
            "kind",
            "run_after",
            postgresql_where=text("status = 'queued'"),
        ),
        Index("ix_jobs_batch", "batch_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    kind: Mapped[str] = mapped_column(String(64), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    batch_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default="queued")
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default="3")
    run_after: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error: Mapped[str | None] = mapped_column(String, nullable=True)

    def __repr__(self) -> str:
        return f"<Job id={self.id} kind={self.kind!r} status={self.status}>"
