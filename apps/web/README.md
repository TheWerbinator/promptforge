# promptforge-web

Next.js 16 (App Router) frontend for PromptForge. Dark by default.

> In progress. The backend ([../api](../api)) is feature-complete and deployed.

## Stack

Next.js 16 · React 19 · TypeScript (strict) · Tailwind CSS v4 · ESLint.
API types are generated from the backend's OpenAPI schema via `openapi-typescript`.

## Local development

The web app talks to the API over HTTP, so run the backend alongside it:

```sh
# terminal 1 — the API (from repo root)
cd apps/api && uv run uvicorn promptforge_api.main:app --reload --port 8000

# terminal 2 — the web app (from this directory)
cp .env.example .env.local        # NEXT_PUBLIC_API_URL=http://localhost:8000
npm install
npm run dev                       # http://localhost:3000
```

## Scripts

| Script | What |
|---|---|
| `npm run dev` | Dev server (http://localhost:3000) |
| `npm run build` | Production build |
| `npm run start` | Serve the production build |
| `npm run lint` | ESLint |
| `npm run typecheck` | `tsc --noEmit` |
| `npm run gen:api` | Regenerate `lib/api/schema.ts` from the API's `/openapi.json` (API must be running locally) |

## Deploy

Vercel (native Next.js support). Set `NEXT_PUBLIC_API_URL` to the deployed API
origin in the Vercel project's environment variables.
