/** Pulsing placeholder for loading states — replaces bare "Loading…" text. */
export function Skeleton({ className = "" }: { className?: string }) {
  return <div className={`animate-pulse rounded-md bg-neutral-800/70 ${className}`} />;
}

/** A stack of skeleton rows shaped like a bordered list. */
export function SkeletonRows({ rows = 4 }: { rows?: number }) {
  return (
    <div className="flex flex-col divide-y divide-neutral-800 overflow-hidden rounded-lg border border-neutral-800">
      {Array.from({ length: rows }).map((_, i) => (
        <div key={i} className="flex items-center justify-between px-4 py-3">
          <Skeleton className="h-4 w-48" />
          <Skeleton className="h-4 w-16" />
        </div>
      ))}
    </div>
  );
}
