"""Bundled content for the three seeded demo corpora.

Small on purpose — enough for the chat demo to retrieve and cite real passages
without a large embedding bill on each fresh deploy. `promptforge-docs` is
self-referential (the agent can answer "what is PromptForge?"), the other two are
short stand-ins for external docs and ML abstracts.
"""

from __future__ import annotations

from dataclasses import dataclass

from promptforge_ragent.models import DocumentContentType


@dataclass(frozen=True)
class SeedDocument:
    title: str
    content_type: DocumentContentType
    content: str


@dataclass(frozen=True)
class SeedCorpus:
    slug: str
    name: str
    description: str
    documents: list[SeedDocument]


SEED_CORPORA: list[SeedCorpus] = [
    SeedCorpus(
        slug="promptforge-docs",
        name="PromptForge Docs",
        description="Self-referential docs about the PromptForge platform.",
        documents=[
            SeedDocument(
                title="What is PromptForge?",
                content_type=DocumentContentType.MARKDOWN,
                content=(
                    "# What is PromptForge?\n\n"
                    "PromptForge is a multi-tenant platform for managing and evaluating LLM "
                    "prompts. Teams store prompts with version history, run them against "
                    "different models with cost and latency tracking, and grade outputs with "
                    "evaluation suites. A separate RAG agent service answers questions over "
                    "document corpora and cites its sources.\n\n"
                    "Every prompt is org-scoped, and a read-only demo workspace lets visitors "
                    "explore seeded content without signing up."
                ),
            ),
            SeedDocument(
                title="Prompts and versions",
                content_type=DocumentContentType.MARKDOWN,
                content=(
                    "# Prompts and versions\n\n"
                    "A prompt holds metadata (name, description, tags) while its body lives on "
                    "append-only PromptVersion rows. Editing a prompt creates a new version "
                    "rather than mutating the old one, so every run stays reproducible against "
                    "the exact bytes that produced it. Versions are numbered sequentially per "
                    "prompt, and runs and eval batches always reference a specific version."
                ),
            ),
            SeedDocument(
                title="Evaluation suites",
                content_type=DocumentContentType.MARKDOWN,
                content=(
                    "# Evaluation suites\n\n"
                    "An eval suite is a set of cases graded by one of four judges: exact match, "
                    "contains, regex, or an LLM judge with a rubric and threshold. Running a "
                    "suite enqueues a job per case, a worker executes them off a Postgres queue, "
                    "and results stream back over server-sent events with a live pass-rate."
                ),
            ),
        ],
    ),
    SeedCorpus(
        slug="fastapi-docs",
        name="FastAPI Docs (excerpts)",
        description="Short excerpts from FastAPI documentation.",
        documents=[
            SeedDocument(
                title="Path operations",
                content_type=DocumentContentType.MARKDOWN,
                content=(
                    "# Path operations\n\n"
                    "In FastAPI you declare a path operation by decorating a function with an "
                    "HTTP method decorator such as @app.get or @app.post. Path parameters are "
                    "declared in the path string and as function arguments with type hints, and "
                    "FastAPI validates and converts them automatically. Query parameters are "
                    "function arguments that are not part of the path."
                ),
            ),
            SeedDocument(
                title="Dependencies",
                content_type=DocumentContentType.MARKDOWN,
                content=(
                    "# Dependencies\n\n"
                    "FastAPI's dependency injection lets a path operation declare what it needs "
                    "via Depends(). A dependency is any callable returning a value; FastAPI runs "
                    "it per request and injects the result. Dependencies can themselves have "
                    "dependencies, forming a tree, and are commonly used for authentication, "
                    "database sessions, and shared parameters."
                ),
            ),
        ],
    ),
    SeedCorpus(
        slug="arxiv-ml-abstracts",
        name="arXiv ML Abstracts (sample)",
        description="A small sample of machine-learning paper abstracts.",
        documents=[
            SeedDocument(
                title="Attention is all you need",
                content_type=DocumentContentType.TEXT,
                content=(
                    "The dominant sequence transduction models are based on recurrent or "
                    "convolutional networks. We propose the Transformer, a model architecture "
                    "relying entirely on self-attention to draw global dependencies between "
                    "input and output, dispensing with recurrence and convolutions entirely. "
                    "Experiments show these models are superior in quality while being more "
                    "parallelizable and requiring significantly less time to train."
                ),
            ),
            SeedDocument(
                title="Retrieval-augmented generation",
                content_type=DocumentContentType.TEXT,
                content=(
                    "Large pre-trained language models store factual knowledge in their "
                    "parameters but struggle to access and manipulate it precisely. We explore "
                    "retrieval-augmented generation, where a parametric model is combined with a "
                    "non-parametric memory of documents retrieved at inference time. This hybrid "
                    "approach improves factual accuracy and lets knowledge be updated without "
                    "retraining the model."
                ),
            ),
        ],
    ),
]
