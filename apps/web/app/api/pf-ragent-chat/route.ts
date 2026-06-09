import { RAGENT_URL } from "@/lib/api/config";
import { apiStream } from "@/lib/api/server";

/**
 * Chat proxy: POST the chat request to ragent's SSE endpoint with the session
 * token attached, and pipe the event stream back to the browser. Non-2xx
 * (e.g. 402 demo-exhausted, 401) is forwarded as-is before the stream opens.
 */
export async function POST(req: Request): Promise<Response> {
  const body = await req.text();
  const upstream = await apiStream("/api/v1/chat", { base: RAGENT_URL, method: "POST", body });

  if (!upstream.ok || !upstream.body) {
    const text = await upstream.text().catch(() => "");
    return new Response(text || upstream.statusText, {
      status: upstream.status,
      headers: { "content-type": upstream.headers.get("content-type") ?? "text/plain" },
    });
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
