"""Seed the three demo corpora into the shared Demo Corp workspace.

Idempotent by construction — corpora are get-or-create by (org, slug), documents
by (corpus, title), and a document is only ingested if it has no chunks yet — so
it's safe to re-run on every deploy. Ingestion is real (parse → chunk → embed),
so running this needs the hosted embedding key; tests mock the embedder.

apps/api owns the demo org and seeds it, so this resolves the org + a user from
the shared DB by natural key (see `services.platform`); if Demo Corp doesn't
exist yet, it no-ops and tells you to seed apps/api first. The agent's system
prompt is seeded by apps/api (it owns prompts), not here.

Entry: `python -m promptforge_ragent.seed`
"""

from __future__ import annotations

import asyncio
from uuid import UUID

import structlog
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from promptforge_ragent.core.config import get_settings
from promptforge_ragent.core.db import get_session_factory
from promptforge_ragent.models import Chunk, Corpus, Document, DocumentStatus
from promptforge_ragent.seed_data import SEED_CORPORA, SeedCorpus, SeedDocument
from promptforge_ragent.services.ingest import ingest_document
from promptforge_ragent.services.platform import resolve_demo_principal

log = structlog.get_logger("promptforge.ragent.seed")


async def _get_or_create_corpus(
    session: AsyncSession, org_id: UUID, created_by: UUID, spec: SeedCorpus
) -> Corpus:
    corpus = (
        await session.execute(
            select(Corpus).where(Corpus.org_id == org_id, Corpus.slug == spec.slug)
        )
    ).scalar_one_or_none()
    if corpus is None:
        corpus = Corpus(
            org_id=org_id,
            slug=spec.slug,
            name=spec.name,
            description=spec.description,
            created_by=created_by,
        )
        session.add(corpus)
        await session.flush()
    return corpus


async def _get_or_create_document(
    session: AsyncSession, corpus: Corpus, org_id: UUID, spec: SeedDocument
) -> Document:
    document = (
        await session.execute(
            select(Document).where(Document.corpus_id == corpus.id, Document.title == spec.title)
        )
    ).scalar_one_or_none()
    if document is None:
        data = spec.content.encode("utf-8")
        document = Document(
            corpus_id=corpus.id,
            org_id=org_id,
            title=spec.title,
            content_type=spec.content_type,
            byte_size=len(data),
            status=DocumentStatus.PENDING,
            raw_content=data,
        )
        session.add(document)
        await session.flush()
    return document


async def _chunk_count(session: AsyncSession, document_id: UUID) -> int:
    return int(
        (
            await session.execute(
                select(func.count()).select_from(Chunk).where(Chunk.document_id == document_id)
            )
        ).scalar_one()
    )


async def seed_corpora(session: AsyncSession, *, org_id: UUID, created_by: UUID) -> dict[str, int]:
    """Get-or-create the demo corpora + ingest their documents. Returns counts."""
    counts = {"corpora": 0, "documents": 0, "ingested": 0}
    for spec in SEED_CORPORA:
        corpus = await _get_or_create_corpus(session, org_id, created_by, spec)
        counts["corpora"] += 1
        for doc_spec in spec.documents:
            document = await _get_or_create_document(session, corpus, org_id, doc_spec)
            counts["documents"] += 1
            if await _chunk_count(session, document.id) == 0:
                assert document.raw_content is not None
                await ingest_document(session, document, document.raw_content)
                counts["ingested"] += 1
    return counts


async def main() -> None:
    settings = get_settings()
    factory = get_session_factory()
    async with factory() as session:
        principal = await resolve_demo_principal(session, settings.demo_org_slug)
        if principal is None:
            print(  # noqa: T201 — CLI entrypoint
                f"demo org '{settings.demo_org_slug}' not found; run the apps/api seed first"
            )
            return
        counts = await seed_corpora(session, org_id=principal.org_id, created_by=principal.user_id)
        await session.commit()
    print(f"ragent corpora seed complete: {counts}")  # noqa: T201


if __name__ == "__main__":
    asyncio.run(main())
