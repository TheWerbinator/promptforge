"""DemoUsage — per-IP daily counter for free hosted-key demo runs.

Not tenant-scoped: this is abuse/cost-control infrastructure, not org data, so it
deliberately sits outside TenantRepository. The IP is stored hashed (HMAC, via
core.security.hmac_token) rather than raw — enough to count distinct visitors and
rate them, without keeping raw client IPs at rest.
"""

from datetime import date

from sqlalchemy import Date, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from promptforge_api.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class DemoUsage(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "demo_usage"
    __table_args__ = (UniqueConstraint("ip_hash", "day", name="uq_demo_usage_ip_hash_day"),)

    # sha256 hex digest of the client IP — fixed 64 chars.
    ip_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    day: Mapped[date] = mapped_column(Date, nullable=False)
    run_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    def __repr__(self) -> str:
        return f"<DemoUsage ip_hash={self.ip_hash[:8]}… day={self.day} n={self.run_count}>"
