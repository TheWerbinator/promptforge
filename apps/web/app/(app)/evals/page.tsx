"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { api } from "@/lib/api/client";
import type { EvalSuite } from "@/lib/api/models";

export default function EvalsPage() {
  const [suites, setSuites] = useState<EvalSuite[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    api.get<EvalSuite[]>("api/v1/eval-suites").then((r) => {
      if (!active) return;
      if (r.ok && r.data) setSuites(r.data);
      else setError(r.error ?? "Failed to load suites");
    });
    return () => {
      active = false;
    };
  }, []);

  return (
    <div className="flex flex-col gap-6">
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-semibold">Eval suites</h1>
        <Link
          href="/evals/new"
          className="rounded-md bg-neutral-100 px-3 py-1.5 text-sm font-medium text-neutral-900 hover:bg-white"
        >
          New suite
        </Link>
      </div>

      {error && <p className="text-sm text-red-400">{error}</p>}
      {suites === null && !error && <p className="text-sm text-neutral-500">Loading…</p>}
      {suites && suites.length === 0 && (
        <p className="text-sm text-neutral-500">No eval suites yet. Create one to start testing prompts.</p>
      )}

      {suites && suites.length > 0 && (
        <div className="flex flex-col divide-y divide-neutral-800 overflow-hidden rounded-lg border border-neutral-800">
          {suites.map((s) => (
            <Link
              key={s.id}
              href={`/evals/${s.id}`}
              className="flex items-center justify-between px-4 py-3 transition-colors hover:bg-neutral-900"
            >
              <div className="min-w-0">
                <div className="text-sm font-medium">{s.name}</div>
                {s.description && <div className="truncate text-xs text-neutral-500">{s.description}</div>}
              </div>
              <span className="ml-3 shrink-0 rounded-full border border-neutral-700 px-2 py-0.5 text-xs text-neutral-400">
                {s.judge_default}
              </span>
            </Link>
          ))}
        </div>
      )}
    </div>
  );
}
