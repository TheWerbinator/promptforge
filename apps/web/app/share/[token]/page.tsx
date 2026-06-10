import Link from "next/link";

import { API_URL } from "@/lib/api/config";
import type { PublicEvalBatchShare, PublicPromptShare, PublicShare } from "@/lib/api/models";

export const metadata = {
  title: "Shared on PromptForge",
};

/**
 * Public, unauthenticated read-only view of a shared prompt or eval report. This
 * is the one page a cold visitor can land on with no account, so it fetches the
 * API's public endpoint directly server-side (no session, no BFF auth) and is
 * deliberately outside the gated (app) group. Not cached: a revoked/expired link
 * must stop resolving immediately.
 */

async function fetchShare(token: string): Promise<PublicShare | null> {
  try {
    const res = await fetch(`${API_URL}/api/v1/public/share/${encodeURIComponent(token)}`, {
      cache: "no-store",
    });
    if (!res.ok) return null;
    return (await res.json()) as PublicShare;
  } catch {
    return null;
  }
}

export default async function SharePage({ params }: { params: Promise<{ token: string }> }) {
  const { token } = await params;
  const share = await fetchShare(token);

  return (
    <div className="flex min-h-full flex-col">
      <header className="border-b border-neutral-800">
        <div className="mx-auto flex max-w-3xl items-center justify-between px-6 py-4">
          <Link href="/" className="text-sm font-semibold">
            PromptForge
          </Link>
          <span className="rounded-full border border-neutral-700 px-2 py-0.5 text-xs text-neutral-400">
            shared · read-only
          </span>
        </div>
      </header>

      <main className="mx-auto w-full max-w-3xl flex-1 px-6 py-10">
        {share === null && <Unavailable />}
        {share?.prompt && <PromptView prompt={share.prompt} />}
        {share?.eval_batch && <EvalBatchView batch={share.eval_batch} />}
      </main>

      <footer className="border-t border-neutral-800">
        <div className="mx-auto flex max-w-3xl items-center gap-4 px-6 py-4 text-xs text-neutral-500">
          <span>Made with PromptForge</span>
          <Link href="/" className="hover:text-neutral-300">
            Try the demo →
          </Link>
        </div>
      </footer>
    </div>
  );
}

function Unavailable() {
  return (
    <div className="rounded-lg border border-neutral-800 p-8 text-center">
      <h1 className="text-lg font-semibold">This share link is no longer available</h1>
      <p className="mt-2 text-sm text-neutral-500">
        It may have been revoked, expired, or never existed.
      </p>
    </div>
  );
}

function varName(v: unknown): { name: string; type: string } {
  const o = (v ?? {}) as { name?: unknown; type?: unknown };
  return {
    name: typeof o.name === "string" ? o.name : "?",
    type: typeof o.type === "string" ? o.type : "str",
  };
}

function PromptView({ prompt }: { prompt: PublicPromptShare }) {
  const vars = prompt.latest_version?.variables ?? [];
  return (
    <article className="flex flex-col gap-6">
      <div>
        <span className="text-xs uppercase tracking-wide text-neutral-500">Shared prompt</span>
        <h1 className="mt-1 text-2xl font-semibold">{prompt.name}</h1>
        {prompt.description && <p className="mt-1 text-sm text-neutral-400">{prompt.description}</p>}
      </div>

      {prompt.latest_version ? (
        <div className="flex flex-col gap-3">
          <div className="flex items-center gap-2 text-sm text-neutral-400">
            <span className="rounded-full border border-neutral-700 px-2 py-0.5 text-xs">
              v{prompt.latest_version.version}
            </span>
            <span className="text-xs">latest version</span>
          </div>
          <pre className="overflow-x-auto rounded-lg border border-neutral-800 bg-neutral-950 p-4 font-mono text-sm whitespace-pre-wrap">
            {prompt.latest_version.body}
          </pre>
          {vars.length > 0 && (
            <div className="flex flex-wrap gap-2">
              {vars.map((v, i) => {
                const { name, type } = varName(v);
                return (
                  <span
                    key={i}
                    className="rounded-md border border-neutral-700 px-2 py-0.5 font-mono text-xs text-neutral-300"
                  >
                    {name}: {type}
                  </span>
                );
              })}
            </div>
          )}
        </div>
      ) : (
        <p className="text-sm text-neutral-500">This prompt has no versions yet.</p>
      )}
    </article>
  );
}

function pct(n: number): string {
  return `${Math.round(n * 100)}%`;
}

function compact(obj: Record<string, unknown>): string {
  const entries = Object.entries(obj);
  if (entries.length === 0) return "—";
  return entries.map(([k, v]) => `${k}=${typeof v === "string" ? v : JSON.stringify(v)}`).join(", ");
}

function EvalBatchView({ batch }: { batch: PublicEvalBatchShare }) {
  return (
    <article className="flex flex-col gap-6">
      <div>
        <span className="text-xs uppercase tracking-wide text-neutral-500">Shared eval report</span>
        <h1 className="mt-1 text-2xl font-semibold">{batch.suite_name}</h1>
      </div>

      <div className="grid grid-cols-3 gap-3">
        <Stat label="Pass rate" value={pct(batch.pass_rate)} />
        <Stat label="Status" value={batch.status} />
        <Stat label="Cases" value={`${batch.completed_jobs}/${batch.total_jobs}`} />
      </div>

      <div className="overflow-hidden rounded-lg border border-neutral-800">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-neutral-800 text-left text-xs text-neutral-500">
              <th className="px-4 py-2 font-medium">Inputs</th>
              <th className="px-4 py-2 font-medium">Expected</th>
              <th className="px-4 py-2 font-medium">Score</th>
              <th className="px-4 py-2 font-medium">Result</th>
              <th className="px-4 py-2 font-medium">Judge reasoning</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-neutral-800 align-top">
            {batch.results.map((r, i) => (
              <tr key={i}>
                <td className="px-4 py-2 font-mono text-xs text-neutral-400">{compact(r.inputs)}</td>
                <td className="px-4 py-2 font-mono text-xs text-neutral-400">
                  {compact(r.expected)}
                </td>
                <td className="px-4 py-2 text-neutral-300">{r.score.toFixed(2)}</td>
                <td className="px-4 py-2">
                  <span className={r.passed ? "text-emerald-400" : "text-red-400"}>
                    {r.passed ? "pass" : "fail"}
                  </span>
                </td>
                <td className="px-4 py-2 text-xs text-neutral-400">{r.judge_reasoning ?? "—"}</td>
              </tr>
            ))}
            {batch.results.length === 0 && (
              <tr>
                <td colSpan={5} className="px-4 py-3 text-neutral-500">
                  No results yet.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </article>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg border border-neutral-800 p-4">
      <div className="text-xs text-neutral-500">{label}</div>
      <div className="mt-1 text-lg font-semibold">{value}</div>
    </div>
  );
}
