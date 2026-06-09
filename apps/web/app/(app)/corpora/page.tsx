"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { ragent } from "@/lib/api/client";
import type { Corpus } from "@/lib/api/models";

export default function CorporaPage() {
  const [corpora, setCorpora] = useState<Corpus[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    ragent.get<Corpus[]>("api/v1/corpora").then((r) => {
      if (!active) return;
      if (r.ok && r.data) setCorpora(r.data);
      else setError(r.error ?? "Failed to load corpora");
    });
    return () => {
      active = false;
    };
  }, []);

  return (
    <div className="flex flex-col gap-6">
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-semibold">Corpora</h1>
        <Link
          href="/corpora/new"
          className="rounded-md bg-neutral-100 px-3 py-1.5 text-sm font-medium text-neutral-900 hover:bg-white"
        >
          New corpus
        </Link>
      </div>

      {error && <p className="text-sm text-red-400">{error}</p>}
      {corpora === null && !error && <p className="text-sm text-neutral-500">Loading…</p>}
      {corpora && corpora.length === 0 && (
        <p className="text-sm text-neutral-500">No corpora yet. Create one and upload documents.</p>
      )}

      {corpora && corpora.length > 0 && (
        <div className="flex flex-col divide-y divide-neutral-800 overflow-hidden rounded-lg border border-neutral-800">
          {corpora.map((c) => (
            <Link
              key={c.id}
              href={`/corpora/${c.id}`}
              className="flex items-center justify-between px-4 py-3 transition-colors hover:bg-neutral-900"
            >
              <div className="min-w-0">
                <div className="text-sm font-medium">{c.name}</div>
                <div className="truncate text-xs text-neutral-500">
                  {c.slug} · {c.embedding_model}
                </div>
              </div>
              <span className="ml-3 shrink-0 text-xs text-neutral-500">
                {c.document_count} doc{c.document_count === 1 ? "" : "s"}
              </span>
            </Link>
          ))}
        </div>
      )}
    </div>
  );
}
