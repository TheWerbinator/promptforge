import { NextResponse } from "next/server";

import { RAGENT_URL } from "@/lib/api/config";
import { apiFetch } from "@/lib/api/server";

/**
 * Authenticated proxy to the ragent service (separate origin, shared HS256
 * token). Same shape as /api/pf but targets RAGENT_URL. Used for corpora list/
 * create + document upload/list. Chat (SSE) goes through /api/pf-ragent-chat.
 */
async function handle(req: Request, params: Promise<{ path: string[] }>): Promise<NextResponse> {
  const { path } = await params;
  const apiPath = `/${path.join("/")}${new URL(req.url).search}`;
  if (!apiPath.startsWith("/api/v1/")) {
    return NextResponse.json({ error: "forbidden path" }, { status: 403 });
  }

  const init: RequestInit = { method: req.method };
  if (req.method !== "GET" && req.method !== "DELETE") {
    const body = await req.text();
    if (body) init.body = body;
  }

  const result = await apiFetch<unknown>(apiPath, init, RAGENT_URL);
  if (result.status === 204) return new NextResponse(null, { status: 204 });
  if (!result.ok) return NextResponse.json({ error: result.error }, { status: result.status });
  return NextResponse.json(result.data, { status: result.status });
}

type Ctx = { params: Promise<{ path: string[] }> };

export const GET = (req: Request, ctx: Ctx) => handle(req, ctx.params);
export const POST = (req: Request, ctx: Ctx) => handle(req, ctx.params);
export const DELETE = (req: Request, ctx: Ctx) => handle(req, ctx.params);
