"""Idempotent demo-data seed.

Populates the demo workspace so `POST /demo/login` lands on something worth
looking at: a few realistic prompts (with version history), a spread of runs
(including a failed one), and a finished eval batch with a pass/fail mix. Also
mints two stable public share links so the README can point at a live prompt and
a live eval report.

Idempotent by construction — every section is get-or-create keyed on a natural
identifier, so it's safe to run on every deploy. Logic lives in `seed_demo()`
(takes a session, returns counts) so tests can drive it directly; `main()` is the
`python -m promptforge_api.seed` entrypoint.
"""

from __future__ import annotations

import asyncio
import secrets
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from promptforge_api.core.config import Settings, get_settings
from promptforge_api.core.db import get_session_factory
from promptforge_api.core.security import hash_password, hmac_token
from promptforge_api.models import (
    EvalBatch,
    EvalBatchStatus,
    EvalCase,
    EvalResult,
    EvalSuite,
    JudgeKind,
    Membership,
    Org,
    OrgRole,
    Prompt,
    PromptVersion,
    Run,
    ShareResourceType,
    ShareToken,
    User,
)

DEMO_ORG_SLUG = "demo-corp"
DEMO_ORG_NAME = "Demo Corp"

# apps/ragent resolves its system prompt by this name in the demo org. Kept here
# (apps/api owns prompts) so the agent consumes a platform-managed prompt.
RAGENT_SYSTEM_PROMPT_NAME = "RAG Agent System Prompt"

# Stable plaintext share tokens (public by design) so the README can link live
# examples. Stored hashed like any other share token.
DEMO_PROMPT_SHARE_TOKEN = "demo-prompt-support-reply"  # noqa: S105  # public share token, not a secret
DEMO_EVAL_SHARE_TOKEN = "demo-eval-support-quality"  # noqa: S105  # public share token, not a secret


def _var(name: str, vtype: str = "str") -> dict[str, Any]:
    return {"name": name, "type": vtype}


# (name, description, [ (body, [vars]) per version in order ])
_PROMPT_SPECS: list[tuple[str, str, list[tuple[str, list[dict[str, Any]]]]]] = [
    (
        "Support Reply Drafter",
        "Drafts a customer-support reply in a chosen tone.",
        [
            (
                "You are a support agent. Reply to the customer:\n\n{{customer_message}}",
                [_var("customer_message")],
            ),
            (
                "You are a friendly support agent. Write a {{tone}} reply to:\n\n"
                "{{customer_message}}",
                [_var("customer_message"), _var("tone")],
            ),
        ],
    ),
    (
        "SQL Explainer",
        "Explains a SQL query in plain English.",
        [("Explain what this SQL query does, step by step:\n\n{{query}}", [_var("query")])],
    ),
    (
        "Release Notes Writer",
        "Turns a commit log into customer-facing release notes.",
        [("Summarize these commits into concise release notes:\n\n{{commits}}", [_var("commits")])],
    ),
    # The RAG agent (apps/ragent) fetches this prompt by name at runtime as its
    # system prompt — editing it here changes the agent's behavior on the next
    # cache miss. No template variables: it's a system prompt, not a templated one.
    (
        RAGENT_SYSTEM_PROMPT_NAME,
        "System prompt consumed by the PromptForge RAG agent (apps/ragent).",
        [
            (
                "You are PromptForge's documentation assistant. Answer the user's question "
                "using only the knowledge base, which you reach through your tools. Search "
                "before you answer, fetch a full passage when a snippet is truncated, and "
                "call cite_sources with the chunk_ids you relied on before giving your final "
                "answer. If the answer isn't in the corpus, say so plainly instead of "
                "guessing. Keep answers concise and grounded in the cited sources.",
                [],
            )
        ],
    ),
]


async def seed_demo(session: AsyncSession, settings: Settings | None = None) -> dict[str, int]:
    """Get-or-create the full demo dataset. Returns a count summary."""
    settings = settings or get_settings()

    user = await _get_or_create_demo_user(session, settings.demo_email)
    org = await _get_or_create_org(session)
    await _ensure_membership(session, user_id=user.id, org_id=org.id)
    await session.flush()

    prompts = await _seed_prompts(session, org_id=org.id, created_by=user.id)
    support = prompts["Support Reply Drafter"]
    support_latest = (
        await session.execute(
            select(PromptVersion)
            .where(PromptVersion.prompt_id == support.id)
            .order_by(PromptVersion.version.desc())
            .limit(1)
        )
    ).scalar_one()

    await _seed_runs(session, org_id=org.id, version=support_latest, created_by=user.id)
    suite, batch = await _seed_evals(
        session, org_id=org.id, version=support_latest, created_by=user.id
    )

    await _ensure_share(
        session,
        org_id=org.id,
        created_by=user.id,
        resource_type=ShareResourceType.PROMPT,
        resource_id=support.id,
        plain=DEMO_PROMPT_SHARE_TOKEN,
    )
    await _ensure_share(
        session,
        org_id=org.id,
        created_by=user.id,
        resource_type=ShareResourceType.EVAL_BATCH,
        resource_id=batch.id,
        plain=DEMO_EVAL_SHARE_TOKEN,
    )
    await session.flush()

    return {
        "prompts": len(prompts),
        "runs": await _count(session, Run, Run.org_id == org.id),
        "eval_cases": await _count(session, EvalCase, EvalCase.suite_id == suite.id),
        "eval_results": await _count(session, EvalResult, EvalResult.batch_id == batch.id),
    }


async def _count(session: AsyncSession, model: Any, where: Any) -> int:
    stmt = select(func.count()).select_from(model).where(where)
    return int((await session.execute(stmt)).scalar_one())


async def _get_or_create_demo_user(session: AsyncSession, email: str) -> User:
    user = (await session.execute(select(User).where(User.email == email))).scalar_one_or_none()
    if user is not None:
        return user
    # Unusable password: the demo account is reachable only via /demo/login,
    # never /auth/login.
    user = User(
        email=email,
        password_hash=hash_password(secrets.token_urlsafe(32)),
        display_name="Demo User",
        is_active=True,
    )
    session.add(user)
    await session.flush()
    return user


async def _get_or_create_org(session: AsyncSession) -> Org:
    org = (await session.execute(select(Org).where(Org.slug == DEMO_ORG_SLUG))).scalar_one_or_none()
    if org is not None:
        return org
    org = Org(name=DEMO_ORG_NAME, slug=DEMO_ORG_SLUG)
    session.add(org)
    await session.flush()
    return org


async def _ensure_membership(session: AsyncSession, *, user_id: Any, org_id: Any) -> None:
    existing = (
        await session.execute(
            select(Membership).where(Membership.user_id == user_id, Membership.org_id == org_id)
        )
    ).scalar_one_or_none()
    if existing is None:
        session.add(Membership(user_id=user_id, org_id=org_id, role=OrgRole.DEMO))


async def _seed_prompts(
    session: AsyncSession, *, org_id: Any, created_by: Any
) -> dict[str, Prompt]:
    out: dict[str, Prompt] = {}
    for name, description, versions in _PROMPT_SPECS:
        prompt = (
            await session.execute(
                select(Prompt).where(Prompt.org_id == org_id, Prompt.name == name)
            )
        ).scalar_one_or_none()
        if prompt is None:
            prompt = Prompt(
                org_id=org_id, name=name, description=description, created_by=created_by
            )
            session.add(prompt)
            await session.flush()
        # Query version numbers directly rather than touching the lazy
        # `prompt.versions` relationship (avoids a sync lazy-load in async code).
        existing_numbers = set(
            (
                await session.execute(
                    select(PromptVersion.version).where(PromptVersion.prompt_id == prompt.id)
                )
            ).scalars()
        )
        for i, (body, variables) in enumerate(versions, start=1):
            if i not in existing_numbers:
                session.add(
                    PromptVersion(
                        prompt_id=prompt.id,
                        version=i,
                        body=body,
                        variables=variables,
                        created_by=created_by,
                    )
                )
        await session.flush()
        out[name] = prompt
    return out


_DEMO_RUNS: list[dict[str, Any]] = [
    {
        "inputs": {"customer_message": "Where is my order?", "tone": "apologetic"},
        "output": "So sorry it's late — it's in transit and should arrive in 3 business days.",
        "input_tokens": 48,
        "output_tokens": 39,
        "cost_usd": Decimal("0.000041"),
        "latency_ms": 812,
        "error": None,
    },
    {
        "inputs": {"customer_message": "I'd like a refund please.", "tone": "professional"},
        "output": "Thanks! Your refund is on its way and will post in 5-7 business days.",
        "input_tokens": 41,
        "output_tokens": 44,
        "cost_usd": Decimal("0.000045"),
        "latency_ms": 905,
        "error": None,
    },
    {
        "inputs": {"customer_message": "Your product is fantastic!", "tone": "friendly"},
        "output": "That made our day — thank you so much! So glad you're enjoying it.",
        "input_tokens": 33,
        "output_tokens": 24,
        "cost_usd": Decimal("0.000028"),
        "latency_ms": 640,
        "error": None,
    },
    {
        "inputs": {"customer_message": "This is the worst service ever.", "tone": "apologetic"},
        "output": None,
        "input_tokens": 0,
        "output_tokens": 0,
        "cost_usd": None,
        "latency_ms": 0,
        "error": "LLMCallError: upstream provider returned 503 (service unavailable)",
    },
]


async def _seed_runs(
    session: AsyncSession, *, org_id: Any, version: PromptVersion, created_by: Any
) -> None:
    if await _count(session, Run, Run.org_id == org_id) > 0:
        return  # already seeded
    for spec in _DEMO_RUNS:
        session.add(
            Run(
                org_id=org_id,
                version_id=version.id,
                model="openai/gpt-4o-mini",
                inputs=spec["inputs"],
                output=spec["output"],
                input_tokens=spec["input_tokens"],
                output_tokens=spec["output_tokens"],
                cost_usd=spec["cost_usd"],
                latency_ms=spec["latency_ms"],
                error=spec["error"],
                created_by=created_by,
            )
        )
    await session.flush()


# (inputs, expected_value, passed, score, reasoning)
_EVAL_CASES: list[tuple[dict[str, Any], str, bool, float, str]] = [
    (
        {"customer_message": "Where is my order?", "tone": "apologetic"},
        "sorry",
        True,
        1.0,
        "Reply contains an apology.",
    ),
    (
        {"customer_message": "I want a refund.", "tone": "professional"},
        "refund",
        True,
        1.0,
        "Reply confirms the refund.",
    ),
    (
        {"customer_message": "Your product is great!", "tone": "friendly"},
        "discount",
        False,
        0.0,
        "Expected 'discount' not present in reply.",
    ),
]


async def _seed_evals(
    session: AsyncSession, *, org_id: Any, version: PromptVersion, created_by: Any
) -> tuple[EvalSuite, EvalBatch]:
    suite = (
        await session.execute(
            select(EvalSuite).where(
                EvalSuite.org_id == org_id, EvalSuite.name == "Support Reply Quality"
            )
        )
    ).scalar_one_or_none()
    if suite is None:
        suite = EvalSuite(
            org_id=org_id,
            name="Support Reply Quality",
            description="Checks that drafted replies hit the key points.",
            judge_default=JudgeKind.CONTAINS,
            created_by=created_by,
        )
        session.add(suite)
        await session.flush()

    cases = list(
        (await session.execute(select(EvalCase).where(EvalCase.suite_id == suite.id))).scalars()
    )
    if not cases:
        cases = []
        for inputs, expected_value, *_ in _EVAL_CASES:
            case = EvalCase(suite_id=suite.id, inputs=inputs, expected={"value": expected_value})
            session.add(case)
            cases.append(case)
        await session.flush()

    batch = (
        await session.execute(select(EvalBatch).where(EvalBatch.suite_id == suite.id))
    ).scalar_one_or_none()
    if batch is None:
        batch = EvalBatch(
            org_id=org_id,
            suite_id=suite.id,
            version_ids=[str(version.id)],
            status=EvalBatchStatus.DONE,
            total_jobs=len(cases),
            completed_jobs=len(cases),
            created_by=created_by,
        )
        session.add(batch)
        await session.flush()
        # Results, matched to cases by order.
        for case, (_, _, passed, score, reasoning) in zip(cases, _EVAL_CASES, strict=True):
            session.add(
                EvalResult(
                    batch_id=batch.id,
                    version_id=version.id,
                    case_id=case.id,
                    score=score,
                    passed=passed,
                    judge_reasoning=reasoning,
                )
            )
        await session.flush()
    return suite, batch


async def _ensure_share(
    session: AsyncSession,
    *,
    org_id: Any,
    created_by: Any,
    resource_type: ShareResourceType,
    resource_id: Any,
    plain: str,
) -> None:
    token_hmac = hmac_token(plain)
    existing = (
        await session.execute(select(ShareToken).where(ShareToken.token_hmac == token_hmac))
    ).scalar_one_or_none()
    if existing is None:
        session.add(
            ShareToken(
                org_id=org_id,
                resource_type=resource_type,
                resource_id=resource_id,
                token_hmac=token_hmac,
                created_by=created_by,
            )
        )


async def main() -> None:
    factory = get_session_factory()
    async with factory() as session:
        counts = await seed_demo(session)
        await session.commit()
    # Plain print: this is a CLI entrypoint, not request-path logging.
    print(f"demo seed complete: {counts}")  # noqa: T201


if __name__ == "__main__":
    asyncio.run(main())
