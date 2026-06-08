"""Corpora + document-upload REST.

List/create corpora and upload documents into them. Uploads land as a `Document`
row with the source bytes in `raw_content` and an `ingest_document` job enqueued
onto the shared queue (the worker does parse→chunk→embed asynchronously, so the
request returns immediately with status=pending). Reads are open to any
authenticated principal (demo included); writes (create corpus, upload) are
gated to writer roles — demo browses + chats the seeded corpora but can't run up
embedding cost by uploading. Per-file (5 MB) and per-corpus (50 MB) caps bound
storage and ingest cost.
"""

from __future__ import annotations

import os
from uuid import UUID

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from promptforge_ragent.core.config import get_settings
from promptforge_ragent.core.db import get_session, get_session_factory
from promptforge_ragent.core.deps import Principal, get_principal
from promptforge_ragent.core.queue import Queue
from promptforge_ragent.models import (
    Corpus,
    Document,
    DocumentContentType,
    DocumentStatus,
    EmbeddingModel,
)
from promptforge_ragent.workers.ingest_worker import enqueue_ingest

router = APIRouter(tags=["corpora"])

_WRITER_ROLES = {"owner", "member"}
_EXT_TO_TYPE = {
    ".md": DocumentContentType.MARKDOWN,
    ".markdown": DocumentContentType.MARKDOWN,
    ".pdf": DocumentContentType.PDF,
    ".html": DocumentContentType.HTML,
    ".htm": DocumentContentType.HTML,
    ".txt": DocumentContentType.TEXT,
}


def _require_writer(principal: Principal) -> None:
    if principal.role not in _WRITER_ROLES:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "read-only role cannot modify corpora")


def _detect_content_type(filename: str | None) -> DocumentContentType | None:
    ext = os.path.splitext(filename or "")[1].lower()
    return _EXT_TO_TYPE.get(ext)


class CorpusCreate(BaseModel):
    slug: str = Field(min_length=1, max_length=120, pattern=r"^[a-z0-9][a-z0-9-]*$")
    name: str = Field(min_length=1, max_length=200)
    description: str | None = None
    embedding_model: EmbeddingModel = EmbeddingModel.OPENAI_3_SMALL


class CorpusOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    slug: str
    name: str
    description: str | None
    embedding_model: EmbeddingModel
    document_count: int


class DocumentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    title: str
    content_type: DocumentContentType
    status: DocumentStatus
    byte_size: int
    error: str | None


@router.get("/corpora")
async def list_corpora(
    principal: Principal = Depends(get_principal),
    session: AsyncSession = Depends(get_session),
) -> list[CorpusOut]:
    rows = (
        await session.execute(
            select(Corpus, func.count(Document.id))
            .outerjoin(Document, Document.corpus_id == Corpus.id)
            .where(Corpus.org_id == principal.org_id)
            .group_by(Corpus.id)
            .order_by(Corpus.created_at)
        )
    ).all()
    return [
        CorpusOut(
            id=corpus.id,
            slug=corpus.slug,
            name=corpus.name,
            description=corpus.description,
            embedding_model=corpus.embedding_model,
            document_count=count,
        )
        for corpus, count in rows
    ]


@router.post("/corpora", status_code=status.HTTP_201_CREATED)
async def create_corpus(
    body: CorpusCreate,
    principal: Principal = Depends(get_principal),
    session: AsyncSession = Depends(get_session),
) -> CorpusOut:
    _require_writer(principal)
    corpus = Corpus(
        org_id=principal.org_id,
        slug=body.slug,
        name=body.name,
        description=body.description,
        embedding_model=body.embedding_model,
        created_by=principal.user_id,
    )
    session.add(corpus)
    try:
        await session.flush()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(
            status.HTTP_409_CONFLICT, "a corpus with that slug already exists"
        ) from exc
    await session.commit()
    return CorpusOut(
        id=corpus.id,
        slug=corpus.slug,
        name=corpus.name,
        description=corpus.description,
        embedding_model=corpus.embedding_model,
        document_count=0,
    )


async def _get_corpus(session: AsyncSession, org_id: UUID, corpus_id: UUID) -> Corpus:
    corpus = await session.get(Corpus, corpus_id)
    if corpus is None or corpus.org_id != org_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "corpus not found")
    return corpus


@router.get("/corpora/{corpus_id}/documents")
async def list_documents(
    corpus_id: UUID,
    principal: Principal = Depends(get_principal),
    session: AsyncSession = Depends(get_session),
) -> list[DocumentOut]:
    await _get_corpus(session, principal.org_id, corpus_id)
    rows = (
        (
            await session.execute(
                select(Document)
                .where(Document.corpus_id == corpus_id)
                .order_by(Document.created_at)
            )
        )
        .scalars()
        .all()
    )
    return [DocumentOut.model_validate(doc) for doc in rows]


@router.post("/corpora/{corpus_id}/documents", status_code=status.HTTP_201_CREATED)
async def upload_document(
    corpus_id: UUID,
    file: UploadFile = File(...),
    principal: Principal = Depends(get_principal),
    session: AsyncSession = Depends(get_session),
) -> DocumentOut:
    _require_writer(principal)
    settings = get_settings()
    corpus = await _get_corpus(session, principal.org_id, corpus_id)

    content_type = _detect_content_type(file.filename)
    if content_type is None:
        raise HTTPException(
            status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            "unsupported file type (allowed: .md, .pdf, .html, .txt)",
        )

    data = await file.read()
    if len(data) > settings.max_file_bytes:
        raise HTTPException(
            status.HTTP_413_CONTENT_TOO_LARGE,
            f"file exceeds the {settings.max_file_bytes} byte per-file limit",
        )

    used = (
        await session.execute(
            select(func.coalesce(func.sum(Document.byte_size), 0)).where(
                Document.corpus_id == corpus_id
            )
        )
    ).scalar_one()
    if used + len(data) > settings.max_corpus_bytes:
        raise HTTPException(
            status.HTTP_413_CONTENT_TOO_LARGE,
            f"corpus would exceed the {settings.max_corpus_bytes} byte limit",
        )

    document = Document(
        corpus_id=corpus.id,
        org_id=principal.org_id,
        title=file.filename or "untitled",
        content_type=content_type,
        byte_size=len(data),
        status=DocumentStatus.PENDING,
        raw_content=data,
    )
    session.add(document)
    await session.flush()
    document_id = document.id
    await session.commit()

    # Enqueue ingest on the shared queue (its own session) after the row is durable.
    await enqueue_ingest(Queue(get_session_factory()), document_id)

    return DocumentOut.model_validate(document)
