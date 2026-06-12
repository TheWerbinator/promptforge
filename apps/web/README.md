# promptforge-web

The **Next.js 16 frontend** for PromptForge — the UI for prompt management,
versioning, the eval engine with live SSE results, the RAG-agent chat, and the
public share pages. Dark by default. Deployed on Vercel.

**Live:** https://thewerbinator-promptforge.vercel.app · **Try the demo** (no signup) from
the landing page.

## What this demonstrates

Front-end engineering for an authed, multi-service product — not a toy SPA:

- **A backend-for-frontend (BFF), so no token ever reaches the browser.** The
  browser only ever talks to the Next origin; route handlers proxy to the API.
  The session (API access + refresh tokens + profile) is sealed as a **JWE** in
  an httpOnly, same-origin cookie — which also sidesteps the third-party-cookie
  deprecation a cross-origin refresh cookie would hit. The browser receives only
  the profile, never the tokens.
- **Two backends behind one session.** The same BFF proxies both `apps/api`
  (prompts, evals, runs) and `apps/ragent` (chat, corpora); ragent validates the
  same HS256 token, so there's one auth flow and one sealed cookie for both.
- **Real SSE in the browser** — eval batches and agent chat stream over
  `fetch` + `eventsource-parser` (not `EventSource`, which can't send an auth
  header or a POST body), piped through the BFF with buffering disabled.
- **BYOK done safely** — the provider key lives in its own sealed httpOnly
  cookie (never `localStorage`), forwarded server-side as `X-Provider-Key`.
- **App Router patterns with judgment** — static-prerendered marketing + public
  share pages (server components, no client JS), client components only where
  there's real interactivity (forms, Monaco, live streams). No TanStack Query /
  Redux — server state goes through the proxy; two small Zustand-free local
  states. Each choice is in [../../docs/DECISIONS.md](../../docs/DECISIONS.md).
- **Hermetic E2E** — Playwright drives the real built app with the upstream API
  faked **in-process by MSW** (via `instrumentation.ts`), so the actual BFF and
  session sealing run with no live backend. Six specs, deterministic in CI.

## Architecture (the BFF)

```
 Browser ──▶ Next origin (Vercel)
              │  app/api/auth/*      seal session (JWE) on login/signup/demo
              │  app/api/pf/*        ──▶ apps/api      (prompts, evals, runs)
              │  app/api/pf-ragent*  ──▶ apps/ragent   (corpora, chat SSE)
              │  app/api/byok        seal the BYOK provider key
              ▼
        httpOnly JWE cookie (tokens never sent to the browser)
```

Full reasoning: [../../docs/DECISIONS.md](../../docs/DECISIONS.md) (the web/BFF
entries). Deploy runbook: [../../docs/DEPLOY-WEB.md](../../docs/DEPLOY-WEB.md).

## Routes

| Route | What |
|---|---|
| `/` | Marketing landing + Try Demo (static) |
| `/login`, `/signup` | Auth (react-hook-form + zod) |
| `/dashboard` | KPI tiles + recent runs |
| `/prompts`, `/prompts/[id]`, `/prompts/new` | Prompt CRUD + versions (Monaco) |
| `/evals`, `/evals/[id]`, `/evals/batches/[id]` | Suites/cases + **live SSE** batch results |
| `/chat` | RAG-agent chat — streamed answers, tool chips, citations |
| `/corpora`, `/corpora/[id]`, `/corpora/new` | Corpora + document upload (ingest status) |
| `/settings` | Profile, API keys (one-time view), BYOK |
| `/share/[token]` | Public read-only prompt / eval report (no auth) |

## Stack

| Area | Choice |
|---|---|
| Framework | Next.js 16 App Router · React 19 · TypeScript (strict) |
| Styling | Tailwind CSS v4 (dark by default, no toggle) |
| Auth/session | `jose` (JWE-sealed httpOnly cookie) · BFF route handlers |
| Data | BFF proxy + a ~80-line typed fetch client; types via `openapi-typescript` |
| Forms | react-hook-form + zod |
| Editor / SSE | `@monaco-editor/react` (lazy) · `eventsource-parser` |
| Tests | Playwright + MSW (in-process upstream mock) |
| Deploy | Vercel (native Next.js) |

## Local development

The web app talks to the backends over HTTP — run them alongside it (see the
root [README](../../README.md) / [DEPLOY-WEB.md](../../docs/DEPLOY-WEB.md)):

```sh
cp .env.example .env.local   # NEXT_PUBLIC_API_URL, NEXT_PUBLIC_RAGENT_URL, WEB_SESSION_SECRET
npm install
npm run dev                  # http://localhost:3000
```

## Scripts

| Script | What |
|---|---|
| `npm run dev` | Dev server |
| `npm run build` / `npm run start` | Production build / serve |
| `npm run lint` / `npm run typecheck` | ESLint / `tsc --noEmit` |
| `npm run test:e2e` | Playwright E2E (builds + starts with MSW, no live backend) |
| `npm run gen:api` | Regenerate `lib/api/schema.ts` from the API's `/openapi.json` |

CI (`.github/workflows/web.yml`) runs lint + typecheck + build and the Playwright
suite on every change; Vercel handles deploys.
