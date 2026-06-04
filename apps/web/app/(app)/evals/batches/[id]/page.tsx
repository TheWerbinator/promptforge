"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";

import { api } from "@/lib/api/client";
import type { BatchProgressEvent, EvalBatchDetail } from "@/lib/api/models";
import { streamSse } from "@/lib/api/sse";

function upsert(list: BatchProgressEvent[], ev: BatchProgressEvent): BatchProgressEvent[] {
  const key = (e: BatchProgressEvent) => `${e.case_id}:${e.version_id}`;
  return [...list.filter((x) => key(x) !== key(ev)), ev];
}

function shortId(id: string): string {
  return id.slice(0, 8);
}

export default function BatchDetailPage() {
  const { id } = useParams<{ id: string }>();

  const [detail, setDetail] = useState<EvalBatchDetail | null>(null);
  const [status, setStatus] = useState<string>("");
  const [progress, setProgress] = useState({ completed: 0, total: 0 });
  const [live, setLive] = useState<BatchProgressEvent[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    let abort: (() => void) | undefined;

    api.get<EvalBatchDetail>(`api/v1/eval-batches/${id}`).then((r) => {
      if (!active) return;
      if (!r.ok || !r.data) {
        setError(r.error ?? "Failed to load batch");
        return;
      }
      setDetail(r.data);
      setStatus(r.data.status);
      setProgress({ completed: r.data.completed_jobs, total: r.data.total_jobs });

      if (r.data.status !== "done" && r.data.status !== "failed") {
        abort = streamSse(`api/v1/eval-batches/${id}/stream`, {
          onEvent: (event, data) => {
            if (event === "result") {
              try {
                const ev = JSON.parse(data) as BatchProgressEvent;
                setProgress({ completed: ev.completed, total: ev.total });
                setLive((prev) => upsert(prev, ev));
              } catch {
                /* ignore malformed event */
              }
            } else if (event === "done") {
              setStatus("done");
              api.get<EvalBatchDetail>(`api/v1/eval-batches/${id}`).then((d) => {
                if (d.ok && d.data) {
                  setDetail(d.data);
                  setProgress({ completed: d.data.completed_jobs, total: d.data.total_jobs });
                }
              });
            }
          },
          onError: (err) => setError(String(err)),
        });
      }
    });

    return () => {
      active = false;
      abort?.();
    };
  }, [id]);

  const pct = progress.total > 0 ? Math.round((progress.completed / progress.total) * 100) : 0;
  const results = detail?.results ?? [];
  const passRate =
    results.length > 0
      ? Math.round((results.filter((r) => r.passed).length / results.length) * 100)
      : null;

  return (
    <div className="flex flex-col gap-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-semibold">Eval batch</h1>
          <div className="mt-1 flex items-center gap-2 text-xs text-neutral-500">
            <span className="rounded-full border border-neutral-700 px-2 py-0.5">{status || "…"}</span>
            {passRate !== null && status === "done" && <span>pass rate {passRate}%</span>}
          </div>
        </div>
        <Link href="/evals" className="text-sm text-neutral-400 hover:text-neutral-200">
          ← Suites
        </Link>
      </div>

      {error && <p className="text-sm text-red-400">{error}</p>}

      {/* Progress */}
      <div className="flex flex-col gap-1.5">
        <div className="flex justify-between text-xs text-neutral-400">
          <span>
            {progress.completed} / {progress.total} cases
          </span>
          <span>{pct}%</span>
        </div>
        <div className="h-2 overflow-hidden rounded-full bg-neutral-800">
          <div className="h-full bg-neutral-200 transition-all" style={{ width: `${pct}%` }} />
        </div>
      </div>

      {/* Final results (with reasoning) once available, else live progress */}
      {results.length > 0 ? (
        <div className="flex flex-col divide-y divide-neutral-800 overflow-hidden rounded-lg border border-neutral-800">
          {results.map((r) => (
            <div key={r.id} className="flex items-start justify-between gap-4 px-4 py-3 text-sm">
              <div className="min-w-0">
                <span className="font-mono text-xs text-neutral-500">case {shortId(r.case_id)}</span>
                {r.judge_reasoning && (
                  <div className="mt-1 text-xs text-neutral-400">{r.judge_reasoning}</div>
                )}
              </div>
              <div className="flex shrink-0 items-center gap-3">
                <span className="text-xs text-neutral-500">score {r.score.toFixed(2)}</span>
                <span className={r.passed ? "text-emerald-400" : "text-red-400"}>
                  {r.passed ? "pass" : "fail"}
                </span>
              </div>
            </div>
          ))}
        </div>
      ) : (
        <div className="flex flex-col divide-y divide-neutral-800 overflow-hidden rounded-lg border border-neutral-800">
          {live.length === 0 && (
            <div className="px-4 py-3 text-sm text-neutral-500">Waiting for results…</div>
          )}
          {live.map((ev) => (
            <div
              key={`${ev.case_id}:${ev.version_id}`}
              className="flex items-center justify-between px-4 py-2 text-sm"
            >
              <span className="font-mono text-xs text-neutral-500">case {shortId(ev.case_id)}</span>
              <div className="flex items-center gap-3">
                <span className="text-xs text-neutral-500">score {ev.score.toFixed(2)}</span>
                <span className={ev.passed ? "text-emerald-400" : "text-red-400"}>
                  {ev.passed ? "pass" : "fail"}
                </span>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
