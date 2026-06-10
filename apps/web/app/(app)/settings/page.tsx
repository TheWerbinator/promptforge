"use client";

import { ApiKeysSection } from "@/components/settings/api-keys-section";
import { ByokSection } from "@/components/settings/byok-section";
import { useAuth } from "@/lib/auth-context";

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex justify-between gap-4 py-2 text-sm">
      <span className="text-neutral-500">{label}</span>
      <span className="truncate">{value}</span>
    </div>
  );
}

export default function SettingsPage() {
  const { profile } = useAuth();

  return (
    <div className="flex max-w-2xl flex-col gap-6">
      <h1 className="text-xl font-semibold">Settings</h1>

      <section className="flex flex-col gap-1 rounded-lg border border-neutral-800 p-5">
        <h2 className="mb-1 text-sm font-semibold">Profile</h2>
        {profile ? (
          <div className="divide-y divide-neutral-800">
            <Row label="Email" value={profile.email} />
            {profile.displayName && <Row label="Name" value={profile.displayName} />}
            <Row label="Workspace" value={profile.orgSlug} />
            <Row label="Role" value={profile.role} />
          </div>
        ) : (
          <p className="text-sm text-neutral-500">Not signed in.</p>
        )}
      </section>

      <ApiKeysSection canWrite={profile?.role !== "demo"} />
      <ByokSection />
    </div>
  );
}
