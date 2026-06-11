"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { Skeleton } from "@/components/ui/skeleton";
import { api } from "@/lib/api/client";
import type { EvalSuite, PromptList, Run, RunList } from "@/lib/api/models";

function Tile({ label, value }: { label: string; value: number | string | null }) {
  return (
    <div className="rounded-lg border border-neutral-800 bg-neutral-900/40 p-4">
      <div className="text-sm text-neutral-400">{label}</div>
      {value === null ? (
        <Skeleton className="mt-2 h-8 w-12" />
      ) : (
        <div className="mt-2 text-2xl font-semibold">{value}</div>
      )}
    </div>
  );
}

function cost(value: Run["cost_usd"]): string {
  if (value === null || value === undefined) return "—";
  return `$${Number(value).toFixed(4)}`;
}

export default function DashboardPage() {
  const [prompts, setPrompts] = useState<number | null>(null);
  const [suites, setSuites] = useState<number | null>(null);
  const [runs, setRuns] = useState<RunList | null>(null);

  useEffect(() => {
    let active = true;
    Promise.all([
      api.get<PromptList>("api/v1/prompts?page_size=1"),
      api.get<EvalSuite[]>("api/v1/eval-suites"),
      api.get<RunList>("api/v1/runs?page_size=8"),
    ]).then(([p, s, r]) => {
      if (!active) return;
      if (p.ok && p.data) setPrompts(p.data.total);
      if (s.ok && s.data) setSuites(s.data.length);
      if (r.ok && r.data) setRuns(r.data);
    });
    return () => {
      active = false;
    };
  }, []);

  return (
    <div className="flex flex-col gap-6">
      <h1 className="text-xl font-semibold">Dashboard</h1>

      <div className="grid gap-4 sm:grid-cols-3">
        <Tile label="Prompts" value={prompts} />
        <Tile label="Eval suites" value={suites} />
        <Tile label="Runs" value={runs ? runs.total : null} />
      </div>

      <section className="flex flex-col gap-2">
        <div className="flex items-center justify-between">
          <h2 className="text-sm font-medium text-neutral-300">Recent runs</h2>
          <Link href="/prompts" className="text-xs text-neutral-500 hover:text-neutral-300">
            Prompts →
          </Link>
        </div>
        <div className="overflow-hidden rounded-lg border border-neutral-800">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-neutral-800 text-left text-xs text-neutral-500">
                <th className="px-4 py-2 font-medium">Model</th>
                <th className="px-4 py-2 font-medium">Cost</th>
                <th className="px-4 py-2 font-medium">Latency</th>
                <th className="px-4 py-2 font-medium">Status</th>
                <th className="px-4 py-2 font-medium">When</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-neutral-800">
              {runs === null &&
                Array.from({ length: 3 }).map((_, i) => (
                  <tr key={`sk-${i}`}>
                    {Array.from({ length: 5 }).map((__, j) => (
                      <td key={j} className="px-4 py-2.5">
                        <Skeleton className="h-4 w-16" />
                      </td>
                    ))}
                  </tr>
                ))}
              {runs?.items.map((run) => (
                <tr key={run.id}>
                  <td className="px-4 py-2 font-mono text-xs">{run.model}</td>
                  <td className="px-4 py-2 text-neutral-400">{cost(run.cost_usd)}</td>
                  <td className="px-4 py-2 text-neutral-400">{run.latency_ms} ms</td>
                  <td className="px-4 py-2">
                    <span className={run.error ? "text-red-400" : "text-emerald-400"}>
                      {run.error ? "error" : "ok"}
                    </span>
                  </td>
                  <td className="px-4 py-2 text-xs text-neutral-500">
                    {new Date(run.created_at).toLocaleString()}
                  </td>
                </tr>
              ))}
              {runs && runs.items.length === 0 && (
                <tr>
                  <td colSpan={5} className="px-4 py-3 text-neutral-500">
                    No runs yet.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  );
}
