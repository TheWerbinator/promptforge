const TILES = ["Prompts", "Runs", "Eval suites", "Pass rate"];

export default function DashboardPage() {
  return (
    <div className="flex flex-col gap-6">
      <h1 className="text-xl font-semibold">Dashboard</h1>
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        {TILES.map((tile) => (
          <div key={tile} className="rounded-lg border border-neutral-800 bg-neutral-900/40 p-4">
            <div className="text-sm text-neutral-400">{tile}</div>
            <div className="mt-2 text-2xl font-semibold text-neutral-600">—</div>
          </div>
        ))}
      </div>
      <p className="text-sm text-neutral-500">
        Live metrics wire up once the prompts and evals pages land.
      </p>
    </div>
  );
}
