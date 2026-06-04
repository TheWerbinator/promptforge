import Link from "next/link";

import { TryDemoButton } from "@/components/try-demo-button";

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

const FEATURES = [
  {
    title: "Versioned prompts",
    body: "Prompts are append-only versioned — every run is reproducible, and you can see exactly what changed and when.",
  },
  {
    title: "Eval suites, four judges",
    body: "Author test cases and grade with exact, contains, regex, or LLM-as-judge. Re-run on any version to get a pass rate.",
  },
  {
    title: "Live result streaming",
    body: "Batch evals run on a queue-backed worker and stream back case-by-case over SSE as each one finishes.",
  },
];

export default function Home() {
  return (
    <main className="flex flex-1 flex-col">
      <section className="flex flex-col items-center gap-6 px-6 pt-24 pb-16 text-center">
        <h1 className="text-4xl font-semibold tracking-tight sm:text-6xl">PromptForge</h1>
        <p className="max-w-2xl text-lg text-neutral-400 sm:text-xl">
          Manage and evaluate LLM prompts like code — versioned prompts, regression-tested
          with eval suites, results streamed live.
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

      <section className="mx-auto grid w-full max-w-5xl gap-4 px-6 pb-16 sm:grid-cols-3">
        {FEATURES.map((feature) => (
          <div
            key={feature.title}
            className="rounded-lg border border-neutral-800 bg-neutral-900/40 p-5 text-left"
          >
            <h2 className="text-sm font-semibold text-neutral-200">{feature.title}</h2>
            <p className="mt-2 text-sm leading-relaxed text-neutral-400">{feature.body}</p>
          </div>
        ))}
      </section>

      <section className="flex flex-col items-center gap-2 px-6 pb-24 text-center text-sm text-neutral-500">
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
    </main>
  );
}
