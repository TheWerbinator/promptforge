"use client";

import { createContext, useCallback, useContext, useState, type ReactNode } from "react";

import type { SessionProfile } from "./types";

interface SignupInput {
  email: string;
  password: string;
  displayName?: string;
  orgName?: string;
}

interface AuthResult {
  ok: boolean;
  error?: string;
}

interface AuthState {
  profile: SessionProfile | null;
  login: (email: string, password: string) => Promise<AuthResult>;
  signup: (input: SignupInput) => Promise<AuthResult>;
  tryDemo: () => Promise<AuthResult>;
  logout: () => Promise<void>;
}

const AuthContext = createContext<AuthState | null>(null);

async function postJson(path: string, body: unknown): Promise<AuthResult & { profile?: SessionProfile }> {
  const res = await fetch(path, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body),
  });
  const data = (await res.json().catch(() => ({}))) as { profile?: SessionProfile; error?: string };
  if (!res.ok) return { ok: false, error: data.error ?? "Request failed" };
  return { ok: true, profile: data.profile };
}

export function AuthProvider({
  initialProfile,
  children,
}: {
  initialProfile: SessionProfile | null;
  children: ReactNode;
}) {
  const [profile, setProfile] = useState<SessionProfile | null>(initialProfile);

  const login = useCallback(async (email: string, password: string) => {
    const res = await postJson("/api/auth/login", { email, password });
    if (res.ok && res.profile) setProfile(res.profile);
    return { ok: res.ok, error: res.error };
  }, []);

  const signup = useCallback(async (input: SignupInput) => {
    const res = await postJson("/api/auth/signup", input);
    if (res.ok && res.profile) setProfile(res.profile);
    return { ok: res.ok, error: res.error };
  }, []);

  const tryDemo = useCallback(async () => {
    const res = await postJson("/api/auth/demo", {});
    if (res.ok && res.profile) setProfile(res.profile);
    return { ok: res.ok, error: res.error };
  }, []);

  const logout = useCallback(async () => {
    await fetch("/api/auth/logout", { method: "POST" });
    setProfile(null);
  }, []);

  return (
    <AuthContext.Provider value={{ profile, login, signup, tryDemo, logout }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth(): AuthState {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within an AuthProvider");
  return ctx;
}
