"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

import { btnCls, Field, inputCls } from "@/components/form";
import { ragent } from "@/lib/api/client";
import type { Corpus } from "@/lib/api/models";

export default function NewCorpusPage() {
  const router = useRouter();
  const [slug, setSlug] = useState("");
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setSaving(true);
    const r = await ragent.post<Corpus>("api/v1/corpora", {
      slug,
      name,
      description: description || null,
    });
    if (!r.ok || !r.data) {
      setError(r.error ?? "Failed to create corpus");
      setSaving(false);
      return;
    }
    router.push(`/corpora/${r.data.id}`);
  };

  return (
    <form onSubmit={submit} className="flex max-w-xl flex-col gap-5">
      <h1 className="text-xl font-semibold">New corpus</h1>
      <Field label="Slug">
        <input
          className={inputCls}
          value={slug}
          onChange={(e) => setSlug(e.target.value)}
          placeholder="my-docs"
          pattern="^[a-z0-9][a-z0-9-]*$"
          title="lowercase letters, digits, and hyphens"
          required
        />
      </Field>
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
      <p className="text-xs text-neutral-500">
        Embeds with OpenAI text-embedding-3-small. Upload documents after creating.
      </p>
      {error && <p className="text-sm text-red-400">{error}</p>}
      <button type="submit" disabled={saving} className={`${btnCls} self-start`}>
        {saving ? "Creating…" : "Create corpus"}
      </button>
    </form>
  );
}
