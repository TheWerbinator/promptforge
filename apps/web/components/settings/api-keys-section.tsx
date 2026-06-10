"use client";

import { useEffect, useState } from "react";

import { btnCls, inputCls } from "@/components/form";
import { api } from "@/lib/api/client";
import type { ApiKeyCreated, ApiKeyListItem } from "@/lib/api/models";

function fmtDate(iso: string): string {
  return new Date(iso).toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" });
}

export function ApiKeysSection({ canWrite }: { canWrite: boolean }) {
  const [keys, setKeys] = useState<ApiKeyListItem[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [refresh, setRefresh] = useState(0);

  const [name, setName] = useState("");
  const [creating, setCreating] = useState(false);
  const [created, setCreated] = useState<ApiKeyCreated | null>(null);
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    let active = true;
    api.get<ApiKeyListItem[]>("api/v1/auth/api-keys").then((r) => {
      if (!active) return;
      if (r.ok && r.data) setKeys(r.data);
      else setError(r.error ?? "Failed to load API keys");
    });
    return () => {
      active = false;
    };
  }, [refresh]);

  const create = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setCreating(true);
    const r = await api.post<ApiKeyCreated>("api/v1/auth/api-keys", { name });
    setCreating(false);
    if (!r.ok || !r.data) {
      setError(r.error ?? "Failed to create API key");
      return;
    }
    setCreated(r.data);
    setCopied(false);
    setName("");
    setRefresh((n) => n + 1);
  };

  const revoke = async (id: string) => {
    setError(null);
    const r = await api.del(`api/v1/auth/api-keys/${id}`);
    if (!r.ok) {
      setError(r.error ?? "Failed to revoke API key");
      return;
    }
    if (created?.id === id) setCreated(null);
    setRefresh((n) => n + 1);
  };

  const copy = async () => {
    if (!created) return;
    await navigator.clipboard.writeText(created.key);
    setCopied(true);
  };

  return (
    <section className="flex flex-col gap-4 rounded-lg border border-neutral-800 p-5">
      <div>
        <h2 className="text-sm font-semibold">API keys</h2>
        <p className="text-xs text-neutral-500">
          Machine credentials for calling the API directly. The secret is shown once at creation —
          store it somewhere safe.
        </p>
      </div>

      {created && (
        <div className="flex flex-col gap-2 rounded-md border border-emerald-800 bg-emerald-950/40 p-3">
          <span className="text-xs text-emerald-300">
            Copy your new key now — it won&apos;t be shown again.
          </span>
          <div className="flex items-center gap-2">
            <code className="min-w-0 flex-1 truncate rounded bg-neutral-900 px-2 py-1.5 font-mono text-xs">
              {created.key}
            </code>
            <button type="button" onClick={copy} className={btnCls}>
              {copied ? "Copied" : "Copy"}
            </button>
          </div>
        </div>
      )}

      {canWrite ? (
        <form onSubmit={create} className="flex items-end gap-2">
          <label className="flex flex-1 flex-col gap-1.5 text-sm">
            <span className="text-neutral-300">New key name</span>
            <input
              className={inputCls}
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="e.g. CI pipeline"
              required
            />
          </label>
          <button type="submit" disabled={creating} className={btnCls}>
            {creating ? "Creating…" : "Create key"}
          </button>
        </form>
      ) : (
        <p className="text-xs text-neutral-500">The demo workspace is read-only — API keys are disabled.</p>
      )}

      {error && <p className="text-sm text-red-400">{error}</p>}

      <div className="overflow-hidden rounded-md border border-neutral-800">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-neutral-800 text-left text-xs text-neutral-500">
              <th className="px-4 py-2 font-medium">Name</th>
              <th className="px-4 py-2 font-medium">Prefix</th>
              <th className="px-4 py-2 font-medium">Created</th>
              <th className="px-4 py-2 font-medium">Last used</th>
              <th className="px-4 py-2" />
            </tr>
          </thead>
          <tbody className="divide-y divide-neutral-800">
            {keys?.map((k) => (
              <tr key={k.id}>
                <td className="px-4 py-2">{k.name}</td>
                <td className="px-4 py-2 font-mono text-xs text-neutral-400">{k.prefix}</td>
                <td className="px-4 py-2 text-neutral-400">{fmtDate(k.created_at)}</td>
                <td className="px-4 py-2 text-neutral-400">
                  {k.last_used_at ? fmtDate(k.last_used_at) : "—"}
                </td>
                <td className="px-4 py-2 text-right">
                  {canWrite && (
                    <button
                      type="button"
                      onClick={() => revoke(k.id)}
                      className="text-xs text-red-400 hover:text-red-300"
                    >
                      Revoke
                    </button>
                  )}
                </td>
              </tr>
            ))}
            {keys?.length === 0 && (
              <tr>
                <td colSpan={5} className="px-4 py-3 text-neutral-500">
                  No API keys yet.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </section>
  );
}
