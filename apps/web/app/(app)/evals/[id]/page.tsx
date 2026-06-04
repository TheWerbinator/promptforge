"use client";

import { useParams, useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { btnCls, Field, inputCls } from "@/components/form";
import { api } from "@/lib/api/client";
import type { EvalBatch, EvalCase, EvalSuite, PromptDetail, PromptList } from "@/lib/api/models";

type InputRow = { key: string; value: string };
const CASE_JUDGES = ["", "exact", "contains", "regex"]; // "" = use suite default

export default function SuiteDetailPage() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();

  const [suite, setSuite] = useState<EvalSuite | null>(null);
  const [cases, setCases] = useState<EvalCase[]>([]);
  const [prompts, setPrompts] = useState<PromptList["items"]>([]);
  const [error, setError] = useState<string | null>(null);
  const [refresh, setRefresh] = useState(0);

  // add-case form
  const [rows, setRows] = useState<InputRow[]>([{ key: "", value: "" }]);
  const [expected, setExpected] = useState("");
  const [judge, setJudge] = useState("");
  const [addError, setAddError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  // run
  const [promptId, setPromptId] = useState("");
  const [runError, setRunError] = useState<string | null>(null);
  const [running, setRunning] = useState(false);

  useEffect(() => {
    let active = true;
    Promise.all([
      api.get<EvalSuite[]>("api/v1/eval-suites"),
      api.get<EvalCase[]>(`api/v1/eval-suites/${id}/cases`),
      api.get<PromptList>("api/v1/prompts"),
    ]).then(([s, c, p]) => {
      if (!active) return;
      if (s.ok && s.data) setSuite(s.data.find((x) => x.id === id) ?? null);
      if (c.ok && c.data) setCases(c.data);
      else if (!c.ok) setError(c.error ?? "Failed to load cases");
      if (p.ok && p.data) setPrompts(p.data.items);
    });
    return () => {
      active = false;
    };
  }, [id, refresh]);

  const addCase = async (e: React.FormEvent) => {
    e.preventDefault();
    setAddError(null);
    setSaving(true);
    const inputs: Record<string, string> = {};
    for (const row of rows) if (row.key.trim()) inputs[row.key.trim()] = row.value;
    const r = await api.post<EvalCase>(`api/v1/eval-suites/${id}/cases`, {
      inputs,
      expected: { value: expected },
      judge: judge || null,
    });
    if (!r.ok) {
      setAddError(r.error ?? "Failed to add case");
      setSaving(false);
      return;
    }
    setRows([{ key: "", value: "" }]);
    setExpected("");
    setJudge("");
    setSaving(false);
    setRefresh((n) => n + 1);
  };

  const run = async () => {
    setRunError(null);
    setRunning(true);
    const detail = await api.get<PromptDetail>(`api/v1/prompts/${promptId}`);
    const versionId = detail.data?.latest_version?.id;
    if (!detail.ok || !versionId) {
      setRunError("Could not resolve a version for that prompt");
      setRunning(false);
      return;
    }
    const r = await api.post<EvalBatch>(`api/v1/eval-suites/${id}/run`, {
      version_ids: [versionId],
    });
    if (!r.ok || !r.data) {
      setRunError(r.error ?? "Failed to start batch");
      setRunning(false);
      return;
    }
    router.push(`/evals/batches/${r.data.id}`);
  };

  return (
    <div className="flex flex-col gap-6">
      <div>
        <h1 className="text-xl font-semibold">{suite?.name ?? "Eval suite"}</h1>
        {suite?.description && <p className="text-sm text-neutral-500">{suite.description}</p>}
        {suite && (
          <span className="mt-1 inline-block rounded-full border border-neutral-700 px-2 py-0.5 text-xs text-neutral-400">
            default judge: {suite.judge_default}
          </span>
        )}
      </div>
      {error && <p className="text-sm text-red-400">{error}</p>}

      {/* Run */}
      <section className="flex flex-col gap-3 rounded-lg border border-neutral-800 p-4">
        <h2 className="text-sm font-medium text-neutral-300">Run this suite</h2>
        <div className="flex flex-wrap items-end gap-3">
          <label className="flex flex-col gap-1.5 text-sm">
            <span className="text-neutral-400">Prompt (latest version)</span>
            <select
              className={inputCls}
              value={promptId}
              onChange={(e) => setPromptId(e.target.value)}
            >
              <option value="">Select a prompt…</option>
              {prompts.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.name}
                </option>
              ))}
            </select>
          </label>
          <button
            onClick={run}
            disabled={running || !promptId || cases.length === 0}
            className={btnCls}
          >
            {running ? "Starting…" : "Run batch"}
          </button>
        </div>
        {cases.length === 0 && (
          <p className="text-xs text-neutral-500">Add at least one case before running.</p>
        )}
        {runError && <p className="text-sm text-red-400">{runError}</p>}
      </section>

      {/* Cases */}
      <section className="flex flex-col gap-3">
        <h2 className="text-sm font-medium text-neutral-300">Cases ({cases.length})</h2>
        <div className="flex flex-col divide-y divide-neutral-800 rounded-lg border border-neutral-800">
          {cases.map((c) => (
            <div key={c.id} className="px-4 py-3 text-sm">
              <div className="font-mono text-xs text-neutral-400">{JSON.stringify(c.inputs)}</div>
              <div className="mt-1 text-xs text-neutral-500">
                expected: {JSON.stringify(c.expected)} · judge: {c.judge ?? suite?.judge_default ?? "—"}
              </div>
            </div>
          ))}
          {cases.length === 0 && <div className="px-4 py-3 text-sm text-neutral-500">No cases yet.</div>}
        </div>
      </section>

      {/* Add case */}
      <form onSubmit={addCase} className="flex flex-col gap-3 rounded-lg border border-neutral-800 p-4">
        <h2 className="text-sm font-medium text-neutral-300">Add a case</h2>
        <div className="flex flex-col gap-2">
          <span className="text-xs text-neutral-400">Inputs (variable → value)</span>
          {rows.map((row, i) => (
            <div key={i} className="flex gap-2">
              <input
                className={`${inputCls} flex-1`}
                placeholder="variable"
                value={row.key}
                onChange={(e) =>
                  setRows(rows.map((r, idx) => (idx === i ? { ...r, key: e.target.value } : r)))
                }
              />
              <input
                className={`${inputCls} flex-1`}
                placeholder="value"
                value={row.value}
                onChange={(e) =>
                  setRows(rows.map((r, idx) => (idx === i ? { ...r, value: e.target.value } : r)))
                }
              />
              <button
                type="button"
                onClick={() => setRows(rows.filter((_, idx) => idx !== i))}
                className="rounded-md border border-neutral-700 px-3 text-sm text-neutral-400 hover:bg-neutral-900"
              >
                ✕
              </button>
            </div>
          ))}
          <button
            type="button"
            onClick={() => setRows([...rows, { key: "", value: "" }])}
            className="self-start text-sm text-neutral-400 hover:text-neutral-200"
          >
            + Add input
          </button>
        </div>
        <Field label="Expected value">
          <input className={inputCls} value={expected} onChange={(e) => setExpected(e.target.value)} />
        </Field>
        <Field label="Judge (blank = suite default)">
          <select className={inputCls} value={judge} onChange={(e) => setJudge(e.target.value)}>
            {CASE_JUDGES.map((j) => (
              <option key={j} value={j}>
                {j || "suite default"}
              </option>
            ))}
          </select>
        </Field>
        {addError && <p className="text-sm text-red-400">{addError}</p>}
        <button type="submit" disabled={saving} className={`${btnCls} self-start`}>
          {saving ? "Adding…" : "Add case"}
        </button>
      </form>
    </div>
  );
}
