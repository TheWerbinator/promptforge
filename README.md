# PromptForge

Multi-tenant LLM prompt management and evaluation platform with a RAG-agent sample app that consumes the platform's own prompts.

> **Status:** in active development. See [PLAN.md](../PLAN.md) for the full plan.

## Live demos

- **Web:** `https://promptforge.vercel.app` _(coming soon)_
- **API:** `https://promptforge-api.fly.dev` _(coming soon)_
- **ragent:** `https://promptforge-ragent.fly.dev` _(coming soon)_

## What's inside

```
apps/
├── api/       FastAPI backend — prompts, versions, evals, jobs queue, auth
├── web/       Next.js 15 frontend — App Router, shadcn/ui, dark by default
└── ragent/    RAG-agent service — 4 corpora, hybrid retrieval, ReAct loop
```

## Architecture

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for the system diagram and component breakdown.

For the reasoning behind every architectural choice, see [docs/INTERVIEW-NOTES.md](docs/INTERVIEW-NOTES.md).

## Local development

```sh
docker compose -f infra/compose.yml up --wait
```

Brings up Postgres + apps/api (web + worker) + apps/ragent (web + ingest-worker) + apps/web on:

- Web: http://localhost:3000
- API: http://localhost:8000  (docs at `/docs`)
- ragent: http://localhost:8001

## License

MIT — see [LICENSE](LICENSE).
