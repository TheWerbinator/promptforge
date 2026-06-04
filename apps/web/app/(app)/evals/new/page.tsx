"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

import { btnCls, Field, inputCls } from "@/components/form";
import { api } from "@/lib/api/client";
import { JUDGE_KINDS, type EvalSuite, type JudgeKind } from "@/lib/api/models";

export default function NewSuitePage() {
  const router = useRouter();
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [judgeDefault, setJudgeDefault] = useState<JudgeKind>("contains");
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setSaving(true);
    const r = await api.post<EvalSuite>("api/v1/eval-suites", {
      name,
      description: description || null,
      judge_default: judgeDefault,
    });
    if (!r.ok || !r.data) {
      setError(r.error ?? "Failed to create suite");
      setSaving(false);
      return;
    }
    router.push(`/evals/${r.data.id}`);
  };

  return (
    <form onSubmit={submit} className="flex max-w-xl flex-col gap-5">
      <h1 className="text-xl font-semibold">New eval suite</h1>
      <Field label="Name">
        <input className={inputCls} value={name} onChange={(e) => setName(e.target.value)} required />
      </Field>
      <Field label="Description (optional)">
        <input
          className={inputCls}
          value={description}
          onChange={(e) => setDescription(e.target.value)}
        />
      </Field>
      <Field label="Default judge">
        <select
          className={inputCls}
          value={judgeDefault}
          onChange={(e) => setJudgeDefault(e.target.value as JudgeKind)}
        >
          {JUDGE_KINDS.map((j) => (
            <option key={j} value={j}>
              {j}
            </option>
          ))}
        </select>
      </Field>
      {error && <p className="text-sm text-red-400">{error}</p>}
      <button type="submit" disabled={saving} className={`${btnCls} self-start`}>
        {saving ? "Creating…" : "Create suite"}
      </button>
    </form>
  );
}
