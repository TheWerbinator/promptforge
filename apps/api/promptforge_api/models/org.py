"""Org + Membership — tenancy boundary for every other resource."""

from enum import StrEnum
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import Enum as SqlEnum
from sqlalchemy import ForeignKey, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from promptforge_api.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from promptforge_api.models.user import User


class OrgRole(StrEnum):
    OWNER = "owner"
    MEMBER = "member"
    DEMO = "demo"


class Org(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "orgs"

    name: Mapped[str] = mapped_column(String(120), nullable=False)
    slug: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)

    memberships: Mapped[list["Membership"]] = relationship(
        back_populates="org",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    def __repr__(self) -> str:
        return f"<Org id={self.id} slug={self.slug!r}>"


class Membership(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "memberships"
    __table_args__ = (UniqueConstraint("user_id", "org_id", name="uq_memberships_user_org"),)

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
    role: Mapped[OrgRole] = mapped_column(
        SqlEnum(
            OrgRole,
            name="org_role",
            native_enum=True,
            values_callable=lambda enum_cls: [m.value for m in enum_cls],
        ),
        nullable=False,
        default=OrgRole.MEMBER,
    )

    user: Mapped["User"] = relationship(back_populates="memberships", lazy="joined")
    org: Mapped[Org] = relationship(back_populates="memberships", lazy="joined")

    def __repr__(self) -> str:
        return f"<Membership user_id={self.user_id} org_id={self.org_id} role={self.role}>"
