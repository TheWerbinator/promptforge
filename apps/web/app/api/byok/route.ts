import { NextResponse } from "next/server";

import { clearProviderKey, maskKey, readProviderKey, writeProviderKey } from "@/lib/byok";
import { readSession } from "@/lib/session";

/**
 * BYOK provider-key management. The key lives in a sealed httpOnly cookie set
 * here (server-side); the browser only ever learns whether one is configured and
 * a masked preview — never the key itself. Available to any signed-in visitor,
 * including demo (paste your own key to keep chatting past the free quota).
 */

async function requireSession(): Promise<boolean> {
  return (await readSession()) !== null;
}

export async function GET(): Promise<NextResponse> {
  if (!(await requireSession())) {
    return NextResponse.json({ error: "not authenticated" }, { status: 401 });
  }
  const key = await readProviderKey();
  return NextResponse.json({ configured: key !== null, masked: key ? maskKey(key) : null });
}

export async function PUT(req: Request): Promise<NextResponse> {
  if (!(await requireSession())) {
    return NextResponse.json({ error: "not authenticated" }, { status: 401 });
  }
  const body = (await req.json().catch(() => ({}))) as { key?: unknown };
  const key = typeof body.key === "string" ? body.key.trim() : "";
  if (!key) {
    return NextResponse.json({ error: "provider key is required" }, { status: 400 });
  }
  await writeProviderKey(key);
  return NextResponse.json({ configured: true, masked: maskKey(key) });
}

export async function DELETE(): Promise<NextResponse> {
  if (!(await requireSession())) {
    return NextResponse.json({ error: "not authenticated" }, { status: 401 });
  }
  await clearProviderKey();
  return NextResponse.json({ configured: false, masked: null });
}
