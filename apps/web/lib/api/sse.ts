"use client";

import { createParser, type EventSourceMessage } from "eventsource-parser";

/**
 * Consume an authenticated SSE stream through the BFF proxy
 * (`/api/pf-stream/<api-path>`). EventSource can't set an Authorization header,
 * so we read the stream via fetch + eventsource-parser instead. Returns an
 * abort function.
 */
export interface SseHandlers {
  onEvent: (event: string, data: string) => void;
  onError?: (error: unknown) => void;
  onClose?: () => void;
}

/**
 * POST a chat request to the ragent chat proxy and consume the SSE response.
 * (A POST body rules out EventSource entirely.) Returns an abort function.
 */
export function streamChat(body: unknown, handlers: SseHandlers): () => void {
  const controller = new AbortController();

  void (async () => {
    try {
      const res = await fetch("/api/pf-ragent-chat", {
        method: "POST",
        headers: { "content-type": "application/json", accept: "text/event-stream" },
        body: JSON.stringify(body),
        signal: controller.signal,
      });
      if (!res.ok || !res.body) {
        let message = `chat failed: ${res.status}`;
        try {
          const j = (await res.json()) as { detail?: string; error?: string };
          message = j.detail ?? j.error ?? message;
        } catch {
          /* non-JSON body */
        }
        handlers.onError?.(new Error(message));
        return;
      }
      const parser = createParser({
        onEvent: (event: EventSourceMessage) => handlers.onEvent(event.event ?? "message", event.data),
      });
      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      for (;;) {
        const { done, value } = await reader.read();
        if (done) break;
        parser.feed(decoder.decode(value, { stream: true }));
      }
      handlers.onClose?.();
    } catch (error) {
      if ((error as Error)?.name !== "AbortError") handlers.onError?.(error);
    }
  })();

  return () => controller.abort();
}

export function streamSse(path: string, handlers: SseHandlers): () => void {
  const controller = new AbortController();

  void (async () => {
    try {
      const res = await fetch(`/api/pf-stream/${path}`, {
        headers: { accept: "text/event-stream" },
        signal: controller.signal,
      });
      if (!res.ok || !res.body) {
        handlers.onError?.(new Error(`stream failed: ${res.status}`));
        return;
      }

      const parser = createParser({
        onEvent: (event: EventSourceMessage) => handlers.onEvent(event.event ?? "message", event.data),
      });
      const reader = res.body.getReader();
      const decoder = new TextDecoder();

      for (;;) {
        const { done, value } = await reader.read();
        if (done) break;
        parser.feed(decoder.decode(value, { stream: true }));
      }
      handlers.onClose?.();
    } catch (error) {
      if ((error as Error)?.name !== "AbortError") handlers.onError?.(error);
    }
  })();

  return () => controller.abort();
}
