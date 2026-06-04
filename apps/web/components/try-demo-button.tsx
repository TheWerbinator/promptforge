"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

import { useAuth } from "@/lib/auth-context";

export function TryDemoButton({ className }: { className?: string }) {
  const { tryDemo } = useAuth();
  const router = useRouter();
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  return (
    <div className="flex flex-col items-center gap-1">
      <button
        disabled={loading}
        className={className}
        onClick={async () => {
          setLoading(true);
          setError(null);
          const res = await tryDemo();
          if (!res.ok) {
            setError(res.error ?? "Demo is unavailable");
            setLoading(false);
            return;
          }
          router.push("/dashboard");
          router.refresh();
        }}
      >
        {loading ? "Starting demo…" : "Try the demo"}
      </button>
      {error && <span className="text-xs text-red-400">{error}</span>}
    </div>
  );
}
