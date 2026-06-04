"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { api } from "@/lib/api/client";
import type { PromptList } from "@/lib/api/models";

export default function PromptsPage() {
  const [data, setData] = useState<PromptList | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    api.get<PromptList>("api/v1/prompts").then((r) => {
      if (!active) return;
      if (r.ok && r.data) setData(r.data);
      else setError(r.error ?? "Failed to load prompts");
      setLoading(false);
    });
    return () => {
      active = false;
    };
  }, []);

  return (
    <div className="flex flex-col gap-6">
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-semibold">Prompts</h1>
        <Link
          href="/prompts/new"
          className="rounded-md bg-neutral-100 px-3 py-1.5 text-sm font-medium text-neutral-900 hover:bg-white"
        >
          New prompt
        </Link>
      </div>

      {loading && <p className="text-sm text-neutral-500">Loading…</p>}
      {error && <p className="text-sm text-red-400">{error}</p>}
      {data && data.items.length === 0 && (
        <p className="text-sm text-neutral-500">No prompts yet. Create your first one.</p>
      )}

      {data && data.items.length > 0 && (
        <div className="flex flex-col divide-y divide-neutral-800 overflow-hidden rounded-lg border border-neutral-800">
          {data.items.map((p) => (
            <Link
              key={p.id}
              href={`/prompts/${p.id}`}
              className="flex items-center justify-between px-4 py-3 transition-colors hover:bg-neutral-900"
            >
              <div className="min-w-0">
                <div className="text-sm font-medium">{p.name}</div>
                {p.description && (
                  <div className="truncate text-xs text-neutral-500">{p.description}</div>
                )}
              </div>
              <span className="ml-3 shrink-0 rounded-full border border-neutral-700 px-2 py-0.5 text-xs text-neutral-400">
                {p.visibility}
              </span>
            </Link>
          ))}
        </div>
      )}
    </div>
  );
}
