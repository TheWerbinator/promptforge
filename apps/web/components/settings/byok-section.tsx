"use client";

import { useEffect, useState } from "react";

import { btnCls, inputCls } from "@/components/form";

interface ByokStatus {
  configured: boolean;
  masked: string | null;
}

export function ByokSection() {
  const [status, setStatus] = useState<ByokStatus | null>(null);
  const [key, setKey] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [refresh, setRefresh] = useState(0);

  useEffect(() => {
    let active = true;
    fetch("/api/byok")
      .then((r) => r.json() as Promise<ByokStatus>)
      .then((s) => {
        if (active) setStatus(s);
      })
      .catch(() => {
        if (active) setError("Failed to load BYOK status");
      });
    return () => {
      active = false;
    };
  }, [refresh]);

  const save = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setBusy(true);
    const res = await fetch("/api/byok", {
      method: "PUT",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ key }),
    });
    setBusy(false);
    if (!res.ok) {
      const j = (await res.json().catch(() => ({}))) as { error?: string };
      setError(j.error ?? "Failed to save key");
      return;
    }
    setKey("");
    setRefresh((n) => n + 1);
  };

  const remove = async () => {
    setError(null);
    setBusy(true);
    const res = await fetch("/api/byok", { method: "DELETE" });
    setBusy(false);
    if (!res.ok) {
      setError("Failed to remove key");
      return;
    }
    setRefresh((n) => n + 1);
  };

  return (
    <section className="flex flex-col gap-4 rounded-lg border border-neutral-800 p-5">
      <div>
        <h2 className="text-sm font-semibold">Provider key (BYOK)</h2>
        <p className="text-xs text-neutral-500">
          Bring your own OpenAI/Anthropic key to run the agent on your own quota instead of the
          shared demo key. It&apos;s stored server-side in a sealed, httpOnly cookie — never in your
          browser&apos;s storage and never sent back to the page.
        </p>
      </div>

      {status?.configured && (
        <div className="flex items-center justify-between rounded-md border border-neutral-800 bg-neutral-900 px-3 py-2 text-sm">
          <span>
            Key configured <span className="font-mono text-xs text-neutral-400">{status.masked}</span>
          </span>
          <button
            type="button"
            onClick={remove}
            disabled={busy}
            className="text-xs text-red-400 hover:text-red-300 disabled:opacity-50"
          >
            Remove
          </button>
        </div>
      )}

      <form onSubmit={save} className="flex items-end gap-2">
        <label className="flex flex-1 flex-col gap-1.5 text-sm">
          <span className="text-neutral-300">{status?.configured ? "Replace key" : "Provider key"}</span>
          <input
            type="password"
            autoComplete="off"
            className={inputCls}
            value={key}
            onChange={(e) => setKey(e.target.value)}
            placeholder="sk-…"
            required
          />
        </label>
        <button type="submit" disabled={busy} className={btnCls}>
          {busy ? "Saving…" : "Save key"}
        </button>
      </form>

      {error && <p className="text-sm text-red-400">{error}</p>}
    </section>
  );
}
