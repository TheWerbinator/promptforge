"""Prompt + PromptVersion.

Prompts hold metadata (name, description, tags, visibility). Their `body` and
`variables` live on PromptVersion rows, which are append-only — editing a prompt
body creates a new version, never mutates the old one. This is the audit story
for prompt iteration: every run can point at the exact bytes it executed.
"""

from enum import StrEnum
from typing import TYPE_CHECKING, Any
from uuid import UUID

from sqlalchemy import Enum as SqlEnum
from sqlalchemy import ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from promptforge_api.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    pass


class PromptVisibility(StrEnum):
    PRIVATE = "private"
    ORG = "org"
    PUBLIC = "public"


class Prompt(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "prompts"
    __table_args__ = (UniqueConstraint("org_id", "name", name="uq_prompts_org_name"),)

    org_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("orgs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    tags: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    visibility: Mapped[PromptVisibility] = mapped_column(
        SqlEnum(
            PromptVisibility,
            name="prompt_visibility",
            native_enum=True,
            values_callable=lambda e: [m.value for m in e],
        ),
        nullable=False,
        default=PromptVisibility.ORG,
    )
    created_by: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    versions: Mapped[list["PromptVersion"]] = relationship(
        back_populates="prompt",
        cascade="all, delete-orphan",
        order_by="PromptVersion.version",
        lazy="selectin",
    )

    def __repr__(self) -> str:
        return f"<Prompt id={self.id} org_id={self.org_id} name={self.name!r}>"


class PromptVersion(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "prompt_versions"
    __table_args__ = (
        UniqueConstraint("prompt_id", "version", name="uq_prompt_versions_prompt_version"),
    )

    prompt_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("prompts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    # Validation of the variables-schema shape lives in core/prompts.py (next phase).
    # Stored shape: list[{"name": str, "type": "str"|"int"|"float"|"bool", "required": bool,
    #                     "default": Any, "choices": list[Any]|None, "description": str|None}]
    variables: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False, default=list)
    created_by: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    prompt: Mapped[Prompt] = relationship(back_populates="versions")

    def __repr__(self) -> str:
        return f"<PromptVersion prompt_id={self.prompt_id} v{self.version}>"
