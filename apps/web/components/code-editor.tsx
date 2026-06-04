"use client";

import Editor from "@monaco-editor/react";

/** Lazy Monaco editor for prompt bodies. Plain-text; {{variables}} are just text. */
export function CodeEditor({
  value,
  onChange,
  readOnly = false,
  height = 240,
}: {
  value: string;
  onChange?: (value: string) => void;
  readOnly?: boolean;
  height?: number;
}) {
  return (
    <div className="overflow-hidden rounded-md border border-neutral-700">
      <Editor
        height={height}
        defaultLanguage="plaintext"
        theme="vs-dark"
        value={value}
        onChange={(next) => onChange?.(next ?? "")}
        loading={<div className="p-3 text-sm text-neutral-500">Loading editor…</div>}
        options={{
          readOnly,
          minimap: { enabled: false },
          fontSize: 13,
          lineNumbers: "off",
          scrollBeyondLastLine: false,
          wordWrap: "on",
          padding: { top: 10, bottom: 10 },
        }}
      />
    </div>
  );
}
