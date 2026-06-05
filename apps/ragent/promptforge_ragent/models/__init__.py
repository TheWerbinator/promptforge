"""ragent ORM models.

Importing this package registers every model on `Base.metadata`. ragent does NOT
migrate — the tables are created by apps/api's single migration history. This
metadata is used for runtime ORM queries and to build the schema in integration
tests (where the api-owned parent tables are stubbed). See docs/DECISIONS.md.
"""

from promptforge_ragent.models.base import Base
from promptforge_ragent.models.chunk import Chunk
from promptforge_ragent.models.conversation import Conversation
from promptforge_ragent.models.corpus import Corpus, EmbeddingModel
from promptforge_ragent.models.document import Document, DocumentContentType, DocumentStatus
from promptforge_ragent.models.message import Message, MessageRole

__all__ = [
    "Base",
    "Chunk",
    "Conversation",
    "Corpus",
    "Document",
    "DocumentContentType",
    "DocumentStatus",
    "EmbeddingModel",
    "Message",
    "MessageRole",
]
