"use client";

import { useEffect, useRef, useState } from "react";

import { ragent } from "@/lib/api/client";
import type { ChatMessage, Citation, Corpus } from "@/lib/api/models";
import { streamChat } from "@/lib/api/sse";

export default function ChatPage() {
  const [corpora, setCorpora] = useState<Corpus[] | null>(null);
  const [corpusId, setCorpusId] = useState("");
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [streaming, setStreaming] = useState(false);
  const [tools, setTools] = useState<string[]>([]);
  const [conversationId, setConversationId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const endRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    let active = true;
    ragent.get<Corpus[]>("api/v1/corpora").then((r) => {
      if (!active) return;
      if (r.ok && r.data) {
        setCorpora(r.data);
        if (r.data.length > 0) setCorpusId(r.data[0].id);
      } else {
        setError(r.error ?? "Failed to load corpora");
      }
    });
    return () => {
      active = false;
    };
  }, []);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, tools]);

  const send = () => {
    const text = input.trim();
    if (!text || !corpusId || streaming) return;
    setError(null);
    setMessages((prev) => [...prev, { role: "user", content: text }]);
    setInput("");
    setStreaming(true);
    setTools([]);

    streamChat(
      { message: text, corpus_id: corpusId, conversation_id: conversationId ?? undefined },
      {
        onEvent: (event, data) => {
          let payload: Record<string, unknown> = {};
          try {
            payload = JSON.parse(data);
          } catch {
            return;
          }
          if (event === "conversation") setConversationId(String(payload.conversation_id));
          else if (event === "tool_call") setTools((prev) => [...prev, String(payload.tool)]);
          else if (event === "answer")
            setMessages((prev) => [
              ...prev,
              {
                role: "assistant",
                content: String(payload.content ?? ""),
                citations: (payload.citations as Citation[]) ?? undefined,
              },
            ]);
          else if (event === "error") setError(String(payload.error));
        },
        onClose: () => {
          setStreaming(false);
          setTools([]);
        },
        onError: (err) => {
          setError(err instanceof Error ? err.message : String(err));
          setStreaming(false);
          setTools([]);
        },
      },
    );
  };

  return (
    <div className="flex h-full flex-col gap-4">
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-semibold">Chat</h1>
        <select
          className="rounded-md border border-neutral-700 bg-neutral-900 px-3 py-1.5 text-sm outline-none"
          value={corpusId}
          onChange={(e) => {
            setCorpusId(e.target.value);
            setConversationId(null);
            setMessages([]);
          }}
        >
          {corpora === null && <option>Loading corpora…</option>}
          {corpora?.length === 0 && <option value="">No corpora</option>}
          {corpora?.map((c) => (
            <option key={c.id} value={c.id}>
              {c.name} ({c.document_count})
            </option>
          ))}
        </select>
      </div>

      <div className="flex flex-1 flex-col gap-4 overflow-auto rounded-lg border border-neutral-800 p-4">
        {messages.length === 0 && !streaming && (
          <p className="m-auto text-sm text-neutral-500">
            Ask a question about the selected corpus. The agent retrieves and cites sources.
          </p>
        )}
        {messages.map((m, i) => (
          <div key={i} className={m.role === "user" ? "self-end max-w-[80%]" : "max-w-[85%]"}>
            <div
              className={`rounded-lg px-3 py-2 text-sm ${
                m.role === "user" ? "bg-neutral-800" : "bg-neutral-900/60 border border-neutral-800"
              }`}
            >
              <div className="whitespace-pre-wrap">{m.content}</div>
            </div>
            {m.citations && m.citations.length > 0 && (
              <div className="mt-1.5 flex flex-col gap-1">
                <span className="text-xs text-neutral-500">Sources</span>
                {m.citations.map((c, j) => (
                  <div key={j} className="rounded border border-neutral-800 px-2 py-1 text-xs text-neutral-400">
                    <span className="text-neutral-300">
                      {c.document_title ?? c.chunk_id ?? "source"}
                      {c.ordinal !== undefined ? ` · #${c.ordinal}` : ""}
                    </span>
                    {c.snippet && <div className="mt-0.5 text-neutral-500">{c.snippet}</div>}
                  </div>
                ))}
              </div>
            )}
          </div>
        ))}
        {streaming && (
          <div className="flex items-center gap-2 text-xs text-neutral-500">
            <span className="animate-pulse">thinking…</span>
            {tools.map((t, i) => (
              <span key={i} className="rounded-full border border-neutral-700 px-2 py-0.5">
                🔧 {t}
              </span>
            ))}
          </div>
        )}
        <div ref={endRef} />
      </div>

      {error && <p className="text-sm text-red-400">{error}</p>}

      <form
        onSubmit={(e) => {
          e.preventDefault();
          send();
        }}
        className="flex gap-2"
      >
        <input
          className="flex-1 rounded-md border border-neutral-700 bg-neutral-900 px-3 py-2 text-sm outline-none focus:border-neutral-500"
          placeholder={corpusId ? "Ask about this corpus…" : "Create a corpus first"}
          value={input}
          onChange={(e) => setInput(e.target.value)}
          disabled={streaming || !corpusId}
        />
        <button
          type="submit"
          disabled={streaming || !corpusId || !input.trim()}
          className="rounded-md bg-neutral-100 px-4 py-2 text-sm font-medium text-neutral-900 hover:bg-white disabled:opacity-50"
        >
          Send
        </button>
      </form>
    </div>
  );
}
