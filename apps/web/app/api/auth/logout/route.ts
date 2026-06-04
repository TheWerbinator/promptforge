import { NextResponse } from "next/server";

import { apiLogout } from "@/lib/api/server";
import { clearSession, readSession } from "@/lib/session";

export async function POST(): Promise<NextResponse> {
  const session = await readSession();
  if (session) await apiLogout(session);
  await clearSession();
  return NextResponse.json({ ok: true });
}
