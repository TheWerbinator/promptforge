# DEPLOY — apps/ragent on Fly.io

> Production runbook for the RAG-agent service. Gets `apps/ragent` (web +
> ingest-worker) live on Fly.io against the **same Neon Postgres + shared JWT
> secret** as apps/api, with the demo corpora seeded and the agent's system
> prompt resolving live from apps/api. **Shawn runs all of these commands.**
>
> Deploy order matters: **apps/api must be deployed + seeded first** — it owns the
> shared DB schema (migrations), creates Demo Corp, and creates the agent's system
> prompt. ragent discovers those from the shared DB.

Day-to-day: `git push` to `main` → CI (`.github/workflows/ragent.yml`) runs lint +
the full suite, then the `deploy` job ships it. Below is the one-time setup + the
manual seed + smoke.

## Topology

- **Fly app** `promptforge-ragent`, region `ord`, two processes (`web` +
  `ingest-worker`) from one image. No `release_command` — ragent never migrates
  (apps/api owns the single migration history) and the corpora seed is a manual
  one-time step (it runs real embeddings; keeping it out of the release means a
  transient OpenAI blip can't block a deploy).
- **Database** the *same* Neon Postgres 17 + pgvector as apps/api (shared schema).
- **Shared HS256 secret** `PF_JWT_SECRET` must be **identical** to apps/api's — a
  platform-issued token is validated here directly, and ragent mints a service
  token with it to fetch the system prompt.

## One-time setup

### 1. Secrets

```sh
fly secrets set --app promptforge-ragent \
  PF_DATABASE_URL="postgresql://<user>:<pwd>@<neon-direct-host>/<db>?sslmode=require" \
  PF_JWT_SECRET="<exact same value as apps/api>" \
  PF_API_BASE_URL="https://promptforge-api.fly.dev" \
  PF_OPENAI_API_KEY="sk-..." \
  PF_CORS_ORIGINS='["https://promptforge.vercel.app"]'
```

- `PF_DATABASE_URL` — Neon **direct** (session-mode) endpoint, same DB as apps/api.
- `PF_JWT_SECRET` — **must match apps/api exactly** (shared-secret auth).
- `PF_API_BASE_URL` — where ragent fetches the system-prompt body.
- `PF_OPENAI_API_KEY` — hosted key for query embeddings (always) + demo free agent
  turns. Without it, retrieval over OpenAI corpora fails and demo chat can't run on
  the hosted key (visitors must BYOK).

Optional demo tuning (defaults shown): `PF_DEMO_FREE_TURNS_PER_IP=3`,
`PF_DEMO_FREE_TURNS_GLOBAL=200`. The global cap is the backstop against IP/VPN
rotation — see DECISIONS "Why a global daily cap, not VPN detection".

Optional local models (off by default; only for a machine sized for torch):
`PF_RERANK_ENABLED=true` (needs the `rerank` extra) and corpora pinned to
`bge_small_en_v1_5` (needs the `local-embeddings` extra).

### 2. CI deploy token

```sh
fly tokens create deploy --app promptforge-ragent   # → set as the FLY_API_TOKEN repo secret
```

## Deploy

```sh
# After apps/api is live + seeded:
cd apps/ragent && fly deploy --remote-only      # or just push to main
```

### Seed the demo corpora (one-time per fresh DB)

Runs real ingestion (parse → chunk → embed on the hosted key); idempotent, so safe
to re-run. Skips with a message if Demo Corp doesn't exist yet (deploy apps/api
first).

```sh
fly ssh console --app promptforge-ragent -C "python -m promptforge_ragent.seed"
```

### Worker scaling

```sh
fly scale count ingest-worker=1 --app promptforge-ragent   # up for user uploads
fly scale count ingest-worker=0 --app promptforge-ragent   # down when idle (cost)
```

## Smoke checklist

```sh
RAGENT=https://promptforge-ragent.fly.dev

# 1. Health + structured logging (X-Request-ID echoed)
curl -i $RAGENT/health                                    # 200 {"status":"ok",...}

# 2. Auth required
curl -s -o /dev/null -w '%{http_code}\n' -X POST $RAGENT/api/v1/chat \
  -H 'content-type: application/json' -d '{"message":"hi","corpus_slug":"promptforge-docs"}'
                                                          # 401

# With a member token (mint via apps/api login, or use the web app):
TOKEN=...   # a platform access token

# 3. Corpora seeded
curl -s $RAGENT/api/v1/corpora -H "authorization: Bearer $TOKEN"   # lists 3 corpora

# 4. Chat streams + cites (SSE)
curl -N -X POST $RAGENT/api/v1/chat -H "authorization: Bearer $TOKEN" \
  -H 'content-type: application/json' \
  -d '{"message":"What is PromptForge?","corpus_slug":"promptforge-docs"}'
  # → event: conversation … tool_call(search_docs) … answer (with citations) … done
```

Demo-mode checks (use a demo token from apps/api `/demo/login`): without
`X-Provider-Key`, the agent runs on free turns and then returns **402** once the
per-IP/global caps are hit; with `X-Provider-Key`, it always runs. A document
uploaded via `POST /corpora/{id}/documents` goes `pending` → `ready` once the
ingest-worker drains it.
