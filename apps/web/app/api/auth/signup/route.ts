import { NextResponse } from "next/server";

import { authenticate } from "@/lib/api/server";
import { toProfile, writeSession } from "@/lib/session";

export async function POST(req: Request): Promise<NextResponse> {
  let body: { email?: string; password?: string; displayName?: string; orgName?: string };
  try {
    body = await req.json();
  } catch {
    return NextResponse.json({ error: "invalid request body" }, { status: 400 });
  }
  if (!body.email || !body.password) {
    return NextResponse.json({ error: "email and password are required" }, { status: 400 });
  }

  const result = await authenticate("/api/v1/auth/signup", {
    email: body.email,
    password: body.password,
    display_name: body.displayName || null,
    org_name: body.orgName || null,
  });
  if (!result.ok || !result.data) {
    return NextResponse.json({ error: result.error ?? "signup failed" }, { status: result.status });
  }

  await writeSession(result.data);
  return NextResponse.json({ profile: toProfile(result.data) });
}
