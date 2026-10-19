"use client";

import { AppHeader } from "@/components/app-header";
import { useRequireUser } from "@/lib/api/auth";
import { userMessage } from "@/lib/api/errors";

export default function DashboardPage() {
  const me = useRequireUser();

  if (me.isPending || me.data === null) {
    return <p className="p-8 text-sm text-slate-500">Loading…</p>;
  }
  if (me.isError) {
    return (
      <p role="alert" className="p-8 text-sm text-red-700">
        {userMessage(me.error)}
      </p>
    );
  }

  return (
    <div className="min-h-screen">
      <AppHeader email={me.data.email} />
      <main className="mx-auto max-w-5xl px-4 py-10">
        <h1 className="mb-2 text-2xl font-semibold">Your forms</h1>
        <div className="rounded-lg border border-dashed border-slate-300 bg-white p-10 text-center text-sm text-slate-500">
          No forms yet. Uploading forms arrives in the next phase.
        </div>
      </main>
    </div>
  );
}
