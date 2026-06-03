const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export default function Home() {
  return (
    <main className="flex flex-1 flex-col items-center justify-center gap-6 px-6 text-center">
      <h1 className="text-4xl font-semibold tracking-tight sm:text-5xl">PromptForge</h1>
      <p className="max-w-xl text-lg text-neutral-400">
        Multi-tenant LLM prompt management and evaluation — versioned prompts, batch
        evals with four judge types, and live result streaming.
      </p>
      <p className="text-sm text-neutral-500">
        Frontend in progress. The API is live at{" "}
        <a
          href={`${API_URL}/docs`}
          className="text-neutral-300 underline underline-offset-4 hover:text-white"
        >
          {API_URL}/docs
        </a>
        .
      </p>
    </main>
  );
}
