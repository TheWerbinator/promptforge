import Link from "next/link";

import { TryDemoButton } from "@/components/try-demo-button";
import { SITE } from "@/lib/site";

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

const FEATURES = [
  {
    icon: "⎇",
    title: "Versioned prompts",
    body: "Prompts are append-only versioned — every run is reproducible, and you can see exactly what changed and when.",
  },
  {
    icon: "⚖",
    title: "Eval suites, four judges",
    body: "Author test cases and grade with exact, contains, regex, or LLM-as-judge. Re-run on any version to get a pass rate.",
  },
  {
    icon: "⚡",
    title: "Live result streaming",
    body: "Batch evals run on a queue-backed worker and stream back case-by-case over SSE as each one finishes.",
  },
  {
    icon: "❝",
    title: "RAG agent with citations",
    body: "A ReAct agent answers over your corpora with hybrid retrieval and inline source citations, streamed live.",
  },
  {
    icon: "⛨",
    title: "Multi-tenant by design",
    body: "Every resource is org-scoped; cross-tenant access 404s. Refresh-token rotation with chain-revocation replay defense.",
  },
  {
    icon: "◑",
    title: "Demo, no signup",
    body: "Browse a seeded workspace read-only with a few free real runs — then bring your own key to keep going.",
  },
];

export default function Home() {
  return (
    <main className="flex flex-1 flex-col">
      <header className="flex items-center justify-between px-6 py-4">
        <span className="text-sm font-semibold tracking-tight">PromptForge</span>
        <nav className="flex items-center gap-4 text-sm">
          <a
            href={SITE.repo}
            target="_blank"
            rel="noreferrer"
            className="text-neutral-400 transition-colors hover:text-neutral-200"
          >
            GitHub
          </a>
          <Link
            href="/login"
            className="text-neutral-400 transition-colors hover:text-neutral-200"
          >
            Log in
          </Link>
        </nav>
      </header>

      {/* Hero with a subtle radial backdrop (CSS only — keeps the page light). */}
      <section className="relative flex flex-col items-center gap-6 px-6 pt-24 pb-20 text-center">
        <div className="pointer-events-none absolute inset-0 -z-10 bg-[radial-gradient(60%_50%_at_50%_0%,rgba(96,96,140,0.18),transparent_70%)]" />
        <span className="rounded-full border border-neutral-800 bg-neutral-900/60 px-3 py-1 text-xs text-neutral-400">
          Prompt management · evals · RAG agent
        </span>
        <h1 className="text-4xl font-semibold tracking-tight sm:text-6xl">PromptForge</h1>
        <p className="max-w-2xl text-lg text-neutral-400 sm:text-xl">
          Manage and evaluate LLM prompts like code — versioned prompts, regression-tested with
          eval suites, results streamed live.
        </p>
        <div className="flex flex-wrap items-start justify-center gap-3">
          <TryDemoButton className="rounded-md bg-neutral-100 px-5 py-2.5 text-sm font-medium text-neutral-900 transition-colors hover:bg-white disabled:opacity-50" />
          <Link
            href="/signup"
            className="rounded-md border border-neutral-700 px-5 py-2.5 text-sm transition-colors hover:bg-neutral-900"
          >
            Sign up
          </Link>
          <Link
            href="/login"
            className="rounded-md px-5 py-2.5 text-sm text-neutral-400 transition-colors hover:text-neutral-200"
          >
            Log in
          </Link>
        </div>
        <p className="text-xs text-neutral-500">
          The demo is read-only and needs no signup — it includes a few free real runs.
        </p>
      </section>

      <section className="mx-auto grid w-full max-w-5xl gap-4 px-6 pb-16 sm:grid-cols-2 lg:grid-cols-3">
        {FEATURES.map((feature) => (
          <div
            key={feature.title}
            className="rounded-lg border border-neutral-800 bg-neutral-900/40 p-5 text-left transition-colors hover:border-neutral-700"
          >
            <div className="mb-3 flex h-9 w-9 items-center justify-center rounded-md border border-neutral-800 bg-neutral-950 text-neutral-300">
              {feature.icon}
            </div>
            <h2 className="text-sm font-semibold text-neutral-200">{feature.title}</h2>
            <p className="mt-2 text-sm leading-relaxed text-neutral-400">{feature.body}</p>
          </div>
        ))}
      </section>

      <section className="flex flex-col items-center gap-2 px-6 pb-20 text-center text-sm text-neutral-500">
        <p>See it without an account:</p>
        <div className="flex flex-wrap justify-center gap-4">
          <a
            href={`${API_URL}/api/v1/public/share/demo-eval-support-quality`}
            className="text-neutral-300 underline underline-offset-4 hover:text-white"
          >
            a live eval report
          </a>
          <a
            href={`${API_URL}/docs`}
            className="text-neutral-300 underline underline-offset-4 hover:text-white"
          >
            the API docs
          </a>
        </div>
      </section>

      <footer className="mt-auto border-t border-neutral-800 px-6 py-6 text-xs text-neutral-500">
        <div className="mx-auto flex max-w-5xl flex-wrap items-center justify-between gap-3">
          <span>PromptForge — FastAPI · Next.js · Postgres + pgvector · Fly + Vercel</span>
          <a href={SITE.repo} target="_blank" rel="noreferrer" className="hover:text-neutral-300">
            Source on GitHub →
          </a>
        </div>
      </footer>
    </main>
  );
}
