"use client";

import { useRouter } from "next/navigation";

import { useAuth } from "@/lib/auth-context";

export default function DashboardPage() {
  const { profile, logout } = useAuth();
  const router = useRouter();

  return (
    <main className="flex flex-1 flex-col items-center justify-center gap-4 px-6 text-center">
      <h1 className="text-2xl font-semibold">Dashboard</h1>
      <p className="text-neutral-400">
        Signed in as <span className="text-neutral-200">{profile?.email ?? "—"}</span> · workspace{" "}
        <span className="text-neutral-200">{profile?.orgSlug ?? "—"}</span> · role{" "}
        <span className="text-neutral-200">{profile?.role ?? "—"}</span>
      </p>
      <p className="text-sm text-neutral-500">
        Prompts, runs, and evals land in the next phases.
      </p>
      <button
        onClick={async () => {
          await logout();
          router.push("/login");
          router.refresh();
        }}
        className="rounded-md border border-neutral-700 px-4 py-2 text-sm transition-colors hover:bg-neutral-900"
      >
        Log out
      </button>
    </main>
  );
}
