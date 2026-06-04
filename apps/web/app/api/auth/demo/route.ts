import { NextResponse } from "next/server";

import { authenticateDemo } from "@/lib/api/server";
import { toProfile, writeSession } from "@/lib/session";

export async function POST(): Promise<NextResponse> {
  const result = await authenticateDemo();
  if (!result.ok || !result.data) {
    return NextResponse.json(
      { error: result.error ?? "demo is unavailable" },
      { status: result.status },
    );
  }
  await writeSession(result.data);
  return NextResponse.json({ profile: toProfile(result.data) });
}
