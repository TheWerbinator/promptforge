"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

import { CodeEditor } from "@/components/code-editor";
import { btnCls, Field, inputCls } from "@/components/form";
import { VariablesEditor } from "@/components/prompts/variables-editor";
import { api } from "@/lib/api/client";
import { VISIBILITIES, type PromptDetail, type PromptVar, type PromptVisibility } from "@/lib/api/models";

export default function NewPromptPage() {
  const router = useRouter();
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [visibility, setVisibility] = useState<PromptVisibility>("org");
  const [body, setBody] = useState("");
  const [variables, setVariables] = useState<PromptVar[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setSaving(true);
    const r = await api.post<PromptDetail>("api/v1/prompts", {
      name,
      description: description || null,
      visibility,
      body,
      variables,
      tags: [],
    });
    if (!r.ok || !r.data) {
      setError(r.error ?? "Failed to create prompt");
      setSaving(false);
      return;
    }
    router.push(`/prompts/${r.data.id}`);
  };

  return (
    <form onSubmit={submit} className="flex max-w-2xl flex-col gap-5">
      <h1 className="text-xl font-semibold">New prompt</h1>

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
      <Field label="Visibility">
        <select
          className={inputCls}
          value={visibility}
          onChange={(e) => setVisibility(e.target.value as PromptVisibility)}
        >
          {VISIBILITIES.map((v) => (
            <option key={v} value={v}>
              {v}
            </option>
          ))}
        </select>
      </Field>

      <div className="flex flex-col gap-1.5 text-sm">
        <span className="text-neutral-300">Body</span>
        <CodeEditor value={body} onChange={setBody} />
        <span className="text-xs text-neutral-500">
          Use {"{{variable}}"} placeholders; declare each below.
        </span>
      </div>

      <div className="flex flex-col gap-1.5 text-sm">
        <span className="text-neutral-300">Variables</span>
        <VariablesEditor value={variables} onChange={setVariables} />
      </div>

      {error && <p className="text-sm text-red-400">{error}</p>}
      <div className="flex gap-3">
        <button type="submit" disabled={saving} className={btnCls}>
          {saving ? "Creating…" : "Create prompt"}
        </button>
      </div>
    </form>
  );
}
