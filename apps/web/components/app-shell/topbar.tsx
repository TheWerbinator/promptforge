"use client";

import { useRouter } from "next/navigation";

import { useAuth } from "@/lib/auth-context";

export function Topbar() {
  const { profile, logout } = useAuth();
  const router = useRouter();

  return (
    <header className="flex h-14 shrink-0 items-center justify-end gap-4 border-b border-neutral-800 px-6">
      <div className="flex items-center gap-3 text-sm">
        <span className="text-neutral-400">{profile?.orgSlug}</span>
        <span className="text-neutral-700">·</span>
        <span className="text-neutral-300">{profile?.email}</span>
        <span className="rounded-full border border-neutral-700 px-2 py-0.5 text-xs text-neutral-400">
          {profile?.role}
        </span>
      </div>
      <button
        onClick={async () => {
          await logout();
          router.push("/login");
          router.refresh();
        }}
        className="rounded-md border border-neutral-700 px-3 py-1.5 text-sm transition-colors hover:bg-neutral-900"
      >
        Log out
      </button>
    </header>
  );
}
