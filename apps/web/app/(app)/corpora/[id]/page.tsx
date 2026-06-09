"use client";

import { useParams } from "next/navigation";
import { useEffect, useRef, useState } from "react";

import { ragent } from "@/lib/api/client";
import type { Corpus, RagentDocument } from "@/lib/api/models";

const TERMINAL = new Set(["ready", "failed"]);

function statusClass(status: string): string {
  if (status === "ready") return "text-emerald-400";
  if (status === "failed") return "text-red-400";
  return "text-amber-400 animate-pulse";
}

function kb(bytes: number): string {
  return `${(bytes / 1024).toFixed(1)} KB`;
}

export default function CorpusDetailPage() {
  const { id } = useParams<{ id: string }>();
  const [corpus, setCorpus] = useState<Corpus | null>(null);
  const [docs, setDocs] = useState<RagentDocument[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [uploading, setUploading] = useState(false);
  const [refresh, setRefresh] = useState(0);
  const fileRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    let active = true;
    let timer: ReturnType<typeof setTimeout> | undefined;
    Promise.all([
      ragent.get<Corpus[]>("api/v1/corpora"),
      ragent.get<RagentDocument[]>(`api/v1/corpora/${id}/documents`),
    ]).then(([c, d]) => {
      if (!active) return;
      if (c.ok && c.data) setCorpus(c.data.find((x) => x.id === id) ?? null);
      if (d.ok && d.data) {
        setDocs(d.data);
        // Poll while anything is still ingesting.
        if (d.data.some((doc) => !TERMINAL.has(doc.status))) {
          timer = setTimeout(() => setRefresh((n) => n + 1), 3000);
        }
      } else if (!d.ok) {
        setError(d.error ?? "Failed to load documents");
      }
    });
    return () => {
      active = false;
      if (timer) clearTimeout(timer);
    };
  }, [id, refresh]);

  const onUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    setUploading(true);
    setError(null);
    const fd = new FormData();
    fd.append("file", file);
    const res = await fetch(`/api/pf-ragent-upload/${id}`, { method: "POST", body: fd });
    setUploading(false);
    if (fileRef.current) fileRef.current.value = "";
    if (!res.ok) {
      const j = (await res.json().catch(() => ({}))) as { error?: string };
      setError(j.error ?? `Upload failed (${res.status})`);
      return;
    }
    setRefresh((n) => n + 1);
  };

  return (
    <div className="flex flex-col gap-6">
      <div className="flex items-start justify-between gap-4">
        <div className="min-w-0">
          <h1 className="text-xl font-semibold">{corpus?.name ?? "Corpus"}</h1>
          {corpus && (
            <div className="text-xs text-neutral-500">
              {corpus.slug} · {corpus.embedding_model}
            </div>
          )}
        </div>
        <label className="shrink-0 cursor-pointer rounded-md bg-neutral-100 px-3 py-1.5 text-sm font-medium text-neutral-900 hover:bg-white">
          {uploading ? "Uploading…" : "Upload document"}
          <input
            ref={fileRef}
            type="file"
            accept=".md,.markdown,.pdf,.html,.htm,.txt"
            className="hidden"
            disabled={uploading}
            onChange={onUpload}
          />
        </label>
      </div>

      {error && <p className="text-sm text-red-400">{error}</p>}

      <div className="overflow-hidden rounded-lg border border-neutral-800">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-neutral-800 text-left text-xs text-neutral-500">
              <th className="px-4 py-2 font-medium">Title</th>
              <th className="px-4 py-2 font-medium">Type</th>
              <th className="px-4 py-2 font-medium">Size</th>
              <th className="px-4 py-2 font-medium">Status</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-neutral-800">
            {docs.map((d) => (
              <tr key={d.id}>
                <td className="px-4 py-2">{d.title}</td>
                <td className="px-4 py-2 text-neutral-400">{d.content_type}</td>
                <td className="px-4 py-2 text-neutral-400">{kb(d.byte_size)}</td>
                <td className="px-4 py-2">
                  <span className={statusClass(d.status)}>{d.status}</span>
                  {d.error && <span className="ml-2 text-xs text-red-400">{d.error}</span>}
                </td>
              </tr>
            ))}
            {docs.length === 0 && (
              <tr>
                <td colSpan={4} className="px-4 py-3 text-neutral-500">
                  No documents yet. Upload a .md, .pdf, .html, or .txt file.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
      <p className="text-xs text-neutral-500">
        Uploads ingest asynchronously (parse → chunk → embed); status updates here as the worker
        processes them.
      </p>
    </div>
  );
}
