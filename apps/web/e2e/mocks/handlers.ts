import { http, HttpResponse } from "msw";

/**
 * In-process mock of apps/api + apps/ragent for the hermetic E2E suite. MSW
 * intercepts the server-side fetch the BFF (and the share server component)
 * makes to the upstream URLs — so the REAL Next BFF, session sealing, and pages
 * run; only the backend is faked. Matched against the absolute upstream URLs the
 * server issues (NEXT_PUBLIC_API_URL / NEXT_PUBLIC_RAGENT_URL).
 *
 * State is a small accumulating in-memory store so create→list→detail flows are
 * coherent within a run. Assertions are presence-based (not exact totals), and
 * Playwright runs single-worker, so accumulation across specs is harmless.
 */

const API = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
const RAGENT = process.env.NEXT_PUBLIC_RAGENT_URL ?? "http://localhost:8001";

type Json = Record<string, unknown>;

function uuid(): string {
  return crypto.randomUUID();
}

function now(): string {
  return new Date().toISOString();
}

interface VersionRow {
  id: string;
  prompt_id: string;
  version: number;
  body: string;
  variables: Json[];
  created_by: string;
  created_at: string;
}

interface PromptRow {
  id: string;
  org_id: string;
  name: string;
  description: string | null;
  tags: string[];
  visibility: string;
  created_by: string;
  created_at: string;
  updated_at: string;
  latest_version: VersionRow;
}

interface SuiteRow {
  id: string;
  name: string;
  description: string | null;
  judge_default: string;
  created_by: string;
  created_at: string;
}

interface CaseRow {
  id: string;
  suite_id: string;
  inputs: Json;
  expected: Json;
  judge: string | null;
  judge_config: Json | null;
  created_at: string;
}

interface BatchRow {
  id: string;
  org_id: string;
  suite_id: string;
  version_ids: string[];
  status: string;
  total_jobs: number;
  completed_jobs: number;
  created_at: string;
}

const ORG_ID = "00000000-0000-0000-0000-000000000001";
const USER_ID = "00000000-0000-0000-0000-000000000002";

const prompts = new Map<string, PromptRow>();
const versions = new Map<string, VersionRow[]>();
const suites = new Map<string, SuiteRow>();
const cases = new Map<string, CaseRow[]>();
const batches = new Map<string, BatchRow>();

function makeVersion(promptId: string, body: string, vars: Json[], version: number): VersionRow {
  return {
    id: uuid(),
    prompt_id: promptId,
    version,
    body,
    variables: vars,
    created_by: USER_ID,
    created_at: now(),
  };
}

// Seed one prompt so /prompts and the eval run picker are never empty.
(() => {
  const id = uuid();
  const v = makeVersion(id, "Summarize {{topic}}.", [{ name: "topic", type: "str" }], 1);
  prompts.set(id, {
    id,
    org_id: ORG_ID,
    name: "Seed Prompt",
    description: "Pre-seeded for E2E",
    tags: [],
    visibility: "org",
    created_by: USER_ID,
    created_at: now(),
    updated_at: now(),
    latest_version: v,
  });
  versions.set(id, [v]);
})();

function authBody(role: string, slug: string): Json {
  return {
    access_token: "mock-access-token",
    token_type: "bearer",
    user: { id: USER_ID, email: "e2e@example.com", display_name: "E2E User" },
    org: { id: ORG_ID, slug, name: "E2E Workspace" },
    role,
  };
}

/** Auth response with the refresh cookie the BFF extracts server-side. */
function authResponse(role: string, slug: string, status = 200) {
  return HttpResponse.json(authBody(role, slug), {
    status,
    headers: { "set-cookie": "pf_refresh=mock-refresh-token; Path=/api/v1/auth; HttpOnly" },
  });
}

function sse(events: { event: string; data: Json }[]) {
  const encoder = new TextEncoder();
  const stream = new ReadableStream<Uint8Array>({
    start(controller) {
      for (const e of events) {
        controller.enqueue(encoder.encode(`event: ${e.event}\ndata: ${JSON.stringify(e.data)}\n\n`));
      }
      controller.close();
    },
  });
  return new HttpResponse(stream, {
    headers: { "content-type": "text/event-stream", "cache-control": "no-cache" },
  });
}

export const handlers = [
  // ---- auth ----
  http.post(`${API}/api/v1/auth/signup`, () => authResponse("owner", "e2e-workspace", 201)),
  http.post(`${API}/api/v1/auth/login`, () => authResponse("owner", "e2e-workspace")),
  http.post(`${API}/api/v1/demo/login`, () => authResponse("demo", "demo-corp")),
  http.post(`${API}/api/v1/auth/refresh`, () =>
    HttpResponse.json(
      { access_token: "mock-access-token-2" },
      { headers: { "set-cookie": "pf_refresh=mock-refresh-token-2; Path=/api/v1/auth; HttpOnly" } },
    ),
  ),
  http.post(`${API}/api/v1/auth/logout`, () => new HttpResponse(null, { status: 204 })),

  // ---- prompts ----
  http.get(`${API}/api/v1/prompts`, () => {
    const items = [...prompts.values()].map((p) => ({
      id: p.id,
      name: p.name,
      description: p.description,
      tags: p.tags,
      visibility: p.visibility,
      created_at: p.created_at,
      updated_at: p.updated_at,
    }));
    return HttpResponse.json({
      items,
      total: items.length,
      page: 1,
      page_size: 50,
      has_more: false,
    });
  }),
  http.post(`${API}/api/v1/prompts`, async ({ request }) => {
    const b = (await request.json()) as Json;
    const id = uuid();
    const v = makeVersion(id, String(b.body ?? ""), (b.variables as Json[]) ?? [], 1);
    const row: PromptRow = {
      id,
      org_id: ORG_ID,
      name: String(b.name ?? "Untitled"),
      description: (b.description as string | null) ?? null,
      tags: (b.tags as string[]) ?? [],
      visibility: String(b.visibility ?? "org"),
      created_by: USER_ID,
      created_at: now(),
      updated_at: now(),
      latest_version: v,
    };
    prompts.set(id, row);
    versions.set(id, [v]);
    return HttpResponse.json(row, { status: 201 });
  }),
  http.get(`${API}/api/v1/prompts/:id/versions`, ({ params }) => {
    const list = versions.get(String(params.id)) ?? [];
    return HttpResponse.json([...list].reverse());
  }),
  http.post(`${API}/api/v1/prompts/:id/versions`, async ({ params, request }) => {
    const id = String(params.id);
    const prompt = prompts.get(id);
    if (!prompt) return HttpResponse.json({ detail: "prompt not found" }, { status: 404 });
    const b = (await request.json()) as Json;
    const list = versions.get(id) ?? [];
    const v = makeVersion(id, String(b.body ?? ""), (b.variables as Json[]) ?? [], list.length + 1);
    list.push(v);
    versions.set(id, list);
    prompt.latest_version = v;
    prompt.updated_at = now();
    return HttpResponse.json(v, { status: 201 });
  }),
  http.get(`${API}/api/v1/prompts/:id`, ({ params }) => {
    const p = prompts.get(String(params.id));
    if (!p) return HttpResponse.json({ detail: "prompt not found" }, { status: 404 });
    return HttpResponse.json(p);
  }),
  http.delete(`${API}/api/v1/prompts/:id`, ({ params }) => {
    prompts.delete(String(params.id));
    versions.delete(String(params.id));
    return new HttpResponse(null, { status: 204 });
  }),

  // ---- eval suites / cases / batches ----
  http.get(`${API}/api/v1/eval-suites`, () => HttpResponse.json([...suites.values()])),
  http.post(`${API}/api/v1/eval-suites`, async ({ request }) => {
    const b = (await request.json()) as Json;
    const row: SuiteRow = {
      id: uuid(),
      name: String(b.name ?? "Suite"),
      description: (b.description as string | null) ?? null,
      judge_default: String(b.judge_default ?? "contains"),
      created_by: USER_ID,
      created_at: now(),
    };
    suites.set(row.id, row);
    cases.set(row.id, []);
    return HttpResponse.json(row, { status: 201 });
  }),
  http.get(`${API}/api/v1/eval-suites/:id/cases`, ({ params }) =>
    HttpResponse.json(cases.get(String(params.id)) ?? []),
  ),
  http.post(`${API}/api/v1/eval-suites/:id/cases`, async ({ params, request }) => {
    const b = (await request.json()) as Json;
    const row: CaseRow = {
      id: uuid(),
      suite_id: String(params.id),
      inputs: (b.inputs as Json) ?? {},
      expected: (b.expected as Json) ?? {},
      judge: (b.judge as string | null) ?? null,
      judge_config: (b.judge_config as Json | null) ?? null,
      created_at: now(),
    };
    const list = cases.get(String(params.id)) ?? [];
    list.push(row);
    cases.set(String(params.id), list);
    return HttpResponse.json(row, { status: 201 });
  }),
  http.post(`${API}/api/v1/eval-suites/:id/run`, async ({ params, request }) => {
    const b = (await request.json()) as Json;
    const versionIds = (b.version_ids as string[]) ?? [];
    const caseList = cases.get(String(params.id)) ?? [];
    const row: BatchRow = {
      id: uuid(),
      org_id: ORG_ID,
      suite_id: String(params.id),
      version_ids: versionIds,
      status: "queued",
      total_jobs: Math.max(1, caseList.length * Math.max(1, versionIds.length)),
      completed_jobs: 0,
      created_at: now(),
    };
    batches.set(row.id, row);
    return HttpResponse.json(row, { status: 201 });
  }),
  // Stream first (more specific path), then the detail GET.
  http.get(`${API}/api/v1/eval-batches/:id/stream`, ({ params }) => {
    const id = String(params.id);
    const batch = batches.get(id);
    const caseList = batch ? (cases.get(batch.suite_id) ?? []) : [];
    const caseId = caseList[0]?.id ?? uuid();
    const versionId = batch?.version_ids[0] ?? uuid();
    const total = batch?.total_jobs ?? 1;
    // Mark the batch done so the page's post-`done` refetch sees final results.
    if (batch) {
      batch.status = "done";
      batch.completed_jobs = total;
    }
    return sse([
      { event: "open", data: {} },
      {
        event: "result",
        data: {
          kind: "result",
          case_id: caseId,
          version_id: versionId,
          score: 1,
          passed: true,
          completed: total,
          total,
        },
      },
      { event: "done", data: {} },
    ]);
  }),
  http.get(`${API}/api/v1/eval-batches/:id`, ({ params }) => {
    const id = String(params.id);
    const batch = batches.get(id);
    if (!batch) return HttpResponse.json({ detail: "batch not found" }, { status: 404 });
    const caseList = cases.get(batch.suite_id) ?? [];
    const results =
      batch.status === "done"
        ? [
            {
              id: uuid(),
              batch_id: id,
              case_id: caseList[0]?.id ?? uuid(),
              version_id: batch.version_ids[0] ?? uuid(),
              score: 1,
              passed: true,
              judge_reasoning: "Output contains the expected value.",
            },
          ]
        : [];
    return HttpResponse.json({ ...batch, results });
  }),

  // ---- runs (dashboard) ----
  http.get(`${API}/api/v1/runs`, () =>
    HttpResponse.json({
      items: [
        {
          id: uuid(),
          model: "gpt-4o-mini",
          cost_usd: 0.0002,
          latency_ms: 812,
          error: null,
          created_at: now(),
        },
        {
          id: uuid(),
          model: "gpt-4o-mini",
          cost_usd: null,
          latency_ms: 0,
          error: "provider timeout",
          created_at: now(),
        },
      ],
      total: 2,
      page: 1,
      page_size: 8,
      has_more: false,
    }),
  ),

  // ---- ragent: corpora + chat ----
  http.get(`${RAGENT}/api/v1/corpora`, () =>
    HttpResponse.json([
      {
        id: uuid(),
        slug: "promptforge-docs",
        name: "PromptForge Docs",
        description: "Self-referential docs",
        embedding_model: "text_embedding_3_small",
        document_count: 3,
      },
    ]),
  ),
  http.post(`${RAGENT}/api/v1/chat`, () =>
    sse([
      { event: "conversation", data: { conversation_id: uuid() } },
      { event: "tool_call", data: { tool: "search_docs" } },
      { event: "tool_result", data: { tool: "search_docs", count: 2 } },
      {
        event: "answer",
        data: {
          content: "PromptForge versions prompts append-only so every run is reproducible.",
          citations: [
            {
              document_title: "PromptForge Docs",
              ordinal: 1,
              snippet: "Prompts are append-only versioned.",
            },
          ],
        },
      },
      { event: "done", data: {} },
    ]),
  ),

  // ---- public share (no auth; server component fetch) ----
  http.get(`${API}/api/v1/public/share/:token`, ({ params }) => {
    const token = String(params.token);
    if (token === "prompt-demo") {
      return HttpResponse.json({
        resource_type: "prompt",
        prompt: {
          name: "Support Reply Drafter",
          description: "Drafts a support reply",
          latest_version: {
            version: 2,
            body: "Draft a reply to {{ticket}}.",
            variables: [{ name: "ticket", type: "str" }],
          },
          updated_at: now(),
        },
        eval_batch: null,
      });
    }
    if (token === "eval-demo") {
      return HttpResponse.json({
        resource_type: "eval_batch",
        prompt: null,
        eval_batch: {
          suite_name: "Support Reply Quality",
          status: "done",
          total_jobs: 3,
          completed_jobs: 3,
          pass_rate: 0.6667,
          results: [
            {
              version_id: uuid(),
              inputs: { ticket: "refund" },
              expected: { value: "sorry" },
              score: 1,
              passed: true,
              judge_reasoning: "Mentions an apology.",
            },
          ],
        },
      });
    }
    return HttpResponse.json({ detail: "share link not found or expired" }, { status: 404 });
  }),
];
