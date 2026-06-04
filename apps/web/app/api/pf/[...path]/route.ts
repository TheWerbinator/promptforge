import { NextResponse } from "next/server";

import { apiFetch } from "@/lib/api/server";

/**
 * Generic authenticated proxy: the browser calls `/api/pf/<api-path>` and this
 * forwards to the API with the session's access token attached (refresh handled
 * in apiFetch). Restricted to `/api/v1/*`; the API enforces tenancy/authz.
 */
async function handle(req: Request, params: Promise<{ path: string[] }>): Promise<NextResponse> {
  const { path } = await params;
  const search = new URL(req.url).search;
  const apiPath = `/${path.join("/")}${search}`;
  if (!apiPath.startsWith("/api/v1/")) {
    return NextResponse.json({ error: "forbidden path" }, { status: 403 });
  }

  const init: RequestInit = { method: req.method };
  if (req.method !== "GET" && req.method !== "DELETE") {
    const body = await req.text();
    if (body) init.body = body;
  }

  const result = await apiFetch<unknown>(apiPath, init);
  if (result.status === 204) return new NextResponse(null, { status: 204 });
  if (!result.ok) return NextResponse.json({ error: result.error }, { status: result.status });
  return NextResponse.json(result.data, { status: result.status });
}

type Ctx = { params: Promise<{ path: string[] }> };

export const GET = (req: Request, ctx: Ctx) => handle(req, ctx.params);
export const POST = (req: Request, ctx: Ctx) => handle(req, ctx.params);
export const PATCH = (req: Request, ctx: Ctx) => handle(req, ctx.params);
export const DELETE = (req: Request, ctx: Ctx) => handle(req, ctx.params);
