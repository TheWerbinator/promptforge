"""Message — one turn in a conversation.

Assistant turns carry `citations` (the chunk ids the answer drew on, for the
source drawer) and `tool_calls` (the ReAct steps, for the tool-call chips) as
JSONB — small, display-oriented metadata that doesn't warrant its own tables.
`org_id` is denormalized off the conversation for direct tenant scoping.
"""

from enum import StrEnum
from typing import TYPE_CHECKING, Any
from uuid import UUID

from sqlalchemy import Enum as SqlEnum
from sqlalchemy import ForeignKey, Integer, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from promptforge_ragent.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from promptforge_ragent.models.conversation import Conversation


class MessageRole(StrEnum):
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"
    SYSTEM = "system"


class Message(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "messages"

    conversation_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("conversations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    org_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("orgs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    role: Mapped[MessageRole] = mapped_column(
        SqlEnum(
            MessageRole,
            name="message_role",
            native_enum=True,
            values_callable=lambda e: [m.value for m in e],
        ),
        nullable=False,
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)
    # [{chunk_id, document_title, score, snippet}, ...] on assistant turns.
    citations: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB, nullable=True)
    # [{tool, args, result_summary}, ...] capturing the ReAct steps.
    tool_calls: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB, nullable=True)
    token_count: Mapped[int | None] = mapped_column(Integer, nullable=True)

    conversation: Mapped["Conversation"] = relationship(back_populates="messages")

    def __repr__(self) -> str:
        return f"<Message id={self.id} conversation_id={self.conversation_id} role={self.role}>"
