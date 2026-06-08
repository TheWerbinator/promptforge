"""DemoUsage — per-day free-turn counter for the demo agent.

Demo visitors get a few free hosted-key agent turns before they must BYOK. Two
counters bound the hosted cost: one keyed by an HMAC of the client IP (per-IP
daily) and one global row (a reserved sentinel key) that caps *total* free turns
per day across everyone — the backstop against IP/VPN rotation, since per-IP
limits alone are trivially defeated by rotating addresses. Cross-org abuse
control, so it sits outside tenancy (no `org_id`), like apps/api's demo_usage.
The IP is stored only as an HMAC — no raw addresses at rest.
"""

from __future__ import annotations

from datetime import date

from sqlalchemy import Date, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from promptforge_ragent.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

# Reserved ip_hmac value for the global daily counter row.
GLOBAL_USAGE_KEY = "__global__"


class DemoUsage(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "ragent_demo_usage"
    __table_args__ = (UniqueConstraint("ip_hmac", "usage_day", name="uq_ragent_demo_usage_ip_day"),)

    ip_hmac: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    usage_day: Mapped[date] = mapped_column(Date, nullable=False)
    turns: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    def __repr__(self) -> str:
        return f"<DemoUsage ip_hmac={self.ip_hmac[:8]}… day={self.usage_day} turns={self.turns}>"
