"use client";

import { inputCls } from "@/components/form";
import { VARIABLE_TYPES, type PromptVar } from "@/lib/api/models";

export function VariablesEditor({
  value,
  onChange,
}: {
  value: PromptVar[];
  onChange: (next: PromptVar[]) => void;
}) {
  const update = (i: number, patch: Partial<PromptVar>) =>
    onChange(value.map((v, idx) => (idx === i ? { ...v, ...patch } : v)));

  return (
    <div className="flex flex-col gap-2">
      {value.map((v, i) => (
        <div key={i} className="flex gap-2">
          <input
            className={`${inputCls} flex-1`}
            placeholder="variable name"
            value={v.name}
            onChange={(e) => update(i, { name: e.target.value })}
          />
          <select
            className={inputCls}
            value={v.type}
            onChange={(e) => update(i, { type: e.target.value })}
          >
            {VARIABLE_TYPES.map((t) => (
              <option key={t} value={t}>
                {t}
              </option>
            ))}
          </select>
          <button
            type="button"
            onClick={() => onChange(value.filter((_, idx) => idx !== i))}
            className="rounded-md border border-neutral-700 px-3 text-sm text-neutral-400 hover:bg-neutral-900"
            aria-label="Remove variable"
          >
            ✕
          </button>
        </div>
      ))}
      <button
        type="button"
        onClick={() => onChange([...value, { name: "", type: "str" }])}
        className="self-start text-sm text-neutral-400 hover:text-neutral-200"
      >
        + Add variable
      </button>
    </div>
  );
}
