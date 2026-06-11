import Link from "next/link";

export default function NotFound() {
  return (
    <main className="flex flex-1 flex-col items-center justify-center gap-4 px-6 py-24 text-center">
      <span className="text-sm font-semibold tracking-tight text-neutral-500">PromptForge</span>
      <h1 className="text-3xl font-semibold">Page not found</h1>
      <p className="max-w-md text-sm text-neutral-500">
        The page you&apos;re looking for doesn&apos;t exist or has moved.
      </p>
      <Link
        href="/"
        className="mt-2 rounded-md border border-neutral-700 px-4 py-2 text-sm transition-colors hover:bg-neutral-900"
      >
        ← Back home
      </Link>
    </main>
  );
}
