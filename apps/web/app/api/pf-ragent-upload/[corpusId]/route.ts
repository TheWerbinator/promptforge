import { NextResponse } from "next/server";

import { RAGENT_URL } from "@/lib/api/config";
import { apiFetch } from "@/lib/api/server";

/**
 * Multipart upload proxy to ragent. Forwards the raw request body + its
 * multipart content-type (boundary preserved) with the session token attached —
 * the generic JSON proxy can't do this (it forces application/json and reads the
 * body as text, corrupting binary uploads like PDFs).
 */
export async function POST(
  req: Request,
  ctx: { params: Promise<{ corpusId: string }> },
): Promise<NextResponse> {
  const { corpusId } = await ctx.params;
  const body = await req.arrayBuffer();
  const contentType = req.headers.get("content-type") ?? "application/octet-stream";

  const result = await apiFetch<unknown>(
    `/api/v1/corpora/${corpusId}/documents`,
    { method: "POST", body, headers: { "content-type": contentType } },
    RAGENT_URL,
  );

  if (!result.ok) return NextResponse.json({ error: result.error }, { status: result.status });
  return NextResponse.json(result.data, { status: result.status });
}
