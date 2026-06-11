"use client";

import { useParams, useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { CodeEditor } from "@/components/code-editor";
import { btnCls } from "@/components/form";
import { VariablesEditor } from "@/components/prompts/variables-editor";
import { Skeleton } from "@/components/ui/skeleton";
import { api } from "@/lib/api/client";
import type { PromptDetail, PromptVar, PromptVersion } from "@/lib/api/models";

export default function PromptDetailPage() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();

  const [prompt, setPrompt] = useState<PromptDetail | null>(null);
  const [versions, setVersions] = useState<PromptVersion[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [adding, setAdding] = useState(false);
  const [newBody, setNewBody] = useState("");
  const [newVars, setNewVars] = useState<PromptVar[]>([]);
  const [addError, setAddError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  const [refresh, setRefresh] = useState(0);

  useEffect(() => {
    let active = true;
    Promise.all([
      api.get<PromptDetail>(`api/v1/prompts/${id}`),
      api.get<PromptVersion[]>(`api/v1/prompts/${id}/versions`),
    ]).then(([detail, vers]) => {
      if (!active) return;
      if (detail.ok && detail.data) setPrompt(detail.data);
      else setError(detail.error ?? "Failed to load prompt");
      if (vers.ok && vers.data) setVersions(vers.data);
      setLoading(false);
    });
    return () => {
      active = false;
    };
  }, [id, refresh]);

  const addVersion = async (e: React.FormEvent) => {
    e.preventDefault();
    setAddError(null);
    setSaving(true);
    const r = await api.post<PromptVersion>(`api/v1/prompts/${id}/versions`, {
      body: newBody,
      variables: newVars,
    });
    if (!r.ok) {
      setAddError(r.error ?? "Failed to add version");
      setSaving(false);
      return;
    }
    setNewBody("");
    setNewVars([]);
    setAdding(false);
    setSaving(false);
    setRefresh((n) => n + 1);
  };

  const remove = async () => {
    if (!window.confirm("Delete this prompt and all its versions?")) return;
    const r = await api.del(`api/v1/prompts/${id}`);
    if (r.ok) {
      router.push("/prompts");
      router.refresh();
    } else {
      setError(r.error ?? "Delete failed");
    }
  };

  if (loading) {
    return (
      <div className="flex flex-col gap-4">
        <Skeleton className="h-7 w-64" />
        <Skeleton className="h-4 w-40" />
        <Skeleton className="h-48 w-full" />
      </div>
    );
  }
  if (!prompt) return <p className="text-sm text-red-400">{error ?? "Not found"}</p>;

  const latest = prompt.latest_version;
  const latestVars = (latest?.variables as unknown as PromptVar[]) ?? [];

  return (
    <div className="flex flex-col gap-6">
      <div className="flex items-start justify-between gap-4">
        <div className="min-w-0">
          <h1 className="text-xl font-semibold">{prompt.name}</h1>
          {prompt.description && <p className="text-sm text-neutral-500">{prompt.description}</p>}
          <div className="mt-1 flex items-center gap-2 text-xs text-neutral-500">
            <span className="rounded-full border border-neutral-700 px-2 py-0.5">{prompt.visibility}</span>
            <span>
              {versions.length} version{versions.length === 1 ? "" : "s"}
            </span>
          </div>
        </div>
        <button
          onClick={remove}
          className="shrink-0 rounded-md border border-red-900/60 px-3 py-1.5 text-sm text-red-400 transition-colors hover:bg-red-950/40"
        >
          Delete
        </button>
      </div>

      {latest && (
        <section className="flex flex-col gap-2">
          <h2 className="text-sm font-medium text-neutral-300">Latest version (v{latest.version})</h2>
          <CodeEditor value={latest.body} readOnly height={200} />
          {latestVars.length > 0 && (
            <div className="flex flex-wrap gap-2 text-xs text-neutral-400">
              {latestVars.map((v, i) => (
                <span key={i} className="rounded border border-neutral-700 px-2 py-0.5">
                  {v.name}: {v.type}
                </span>
              ))}
            </div>
          )}
        </section>
      )}

      <section className="flex flex-col gap-2">
        <h2 className="text-sm font-medium text-neutral-300">Version history</h2>
        <div className="flex flex-col divide-y divide-neutral-800 rounded-lg border border-neutral-800">
          {versions.map((v) => (
            <div key={v.id} className="flex items-center justify-between px-4 py-2 text-sm">
              <span>v{v.version}</span>
              <span className="text-xs text-neutral-500">
                {new Date(v.created_at).toLocaleString()}
              </span>
            </div>
          ))}
        </div>
      </section>

      <section className="flex flex-col gap-2">
        {!adding ? (
          <button
            onClick={() => {
              setNewBody(latest?.body ?? "");
              setNewVars(latestVars);
              setAdding(true);
            }}
            className={`${btnCls} self-start`}
          >
            Add new version
          </button>
        ) : (
          <form onSubmit={addVersion} className="flex flex-col gap-3 rounded-lg border border-neutral-800 p-4">
            <h2 className="text-sm font-medium text-neutral-300">New version</h2>
            <CodeEditor value={newBody} onChange={setNewBody} />
            <VariablesEditor value={newVars} onChange={setNewVars} />
            {addError && <p className="text-sm text-red-400">{addError}</p>}
            <div className="flex gap-2">
              <button type="submit" disabled={saving} className={btnCls}>
                {saving ? "Saving…" : "Save version"}
              </button>
              <button
                type="button"
                onClick={() => setAdding(false)}
                className="rounded-md border border-neutral-700 px-4 py-2 text-sm hover:bg-neutral-900"
              >
                Cancel
              </button>
            </div>
          </form>
        )}
      </section>
    </div>
  );
}
