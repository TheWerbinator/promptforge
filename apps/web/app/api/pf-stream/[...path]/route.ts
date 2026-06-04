import { apiStream } from "@/lib/api/server";

/**
 * Authenticated SSE proxy. The browser opens `/api/pf-stream/<api-path>` (no way
 * to set an Authorization header on a stream from the client), and this attaches
 * the session token server-side and pipes the upstream event stream straight
 * through. Used for the eval-batch live results.
 */
type Ctx = { params: Promise<{ path: string[] }> };

export async function GET(req: Request, ctx: Ctx): Promise<Response> {
  const { path } = await ctx.params;
  const search = new URL(req.url).search;
  const apiPath = `/${path.join("/")}${search}`;
  if (!apiPath.startsWith("/api/v1/")) {
    return new Response("forbidden path", { status: 403 });
  }

  const upstream = await apiStream(apiPath);
  if (!upstream.ok || !upstream.body) {
    return new Response(upstream.statusText || "stream error", { status: upstream.status });
  }

  return new Response(upstream.body, {
    status: 200,
    headers: {
      "content-type": "text/event-stream",
      "cache-control": "no-cache, no-transform",
      connection: "keep-alive",
      "x-accel-buffering": "no",
    },
  });
}
