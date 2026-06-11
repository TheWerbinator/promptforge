"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

import { SITE } from "@/lib/site";

const NAV = [
  { href: "/dashboard", label: "Dashboard" },
  { href: "/prompts", label: "Prompts" },
  { href: "/evals", label: "Evals" },
  { href: "/corpora", label: "Corpora" },
  { href: "/chat", label: "Chat" },
  { href: "/settings", label: "Settings" },
];

export function Sidebar() {
  const pathname = usePathname();
  return (
    <aside className="flex w-56 shrink-0 flex-col border-r border-neutral-800 bg-neutral-950">
      <Link
        href="/dashboard"
        className="flex h-14 items-center border-b border-neutral-800 px-5 text-sm font-semibold tracking-tight transition-colors hover:text-white"
      >
        PromptForge
      </Link>
      <nav className="flex flex-col gap-1 p-3">
        {NAV.map((item) => {
          const active = pathname === item.href || pathname.startsWith(`${item.href}/`);
          return (
            <Link
              key={item.href}
              href={item.href}
              className={`rounded-md px-3 py-2 text-sm transition-colors ${
                active
                  ? "bg-neutral-800 text-white"
                  : "text-neutral-400 hover:bg-neutral-900 hover:text-neutral-200"
              }`}
            >
              {item.label}
            </Link>
          );
        })}
      </nav>
      <a
        href={SITE.repo}
        target="_blank"
        rel="noreferrer"
        className="mt-auto border-t border-neutral-800 px-5 py-3 text-xs text-neutral-500 transition-colors hover:text-neutral-300"
      >
        Source on GitHub →
      </a>
    </aside>
  );
}
