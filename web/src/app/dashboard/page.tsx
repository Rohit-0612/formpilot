"use client";

import { useRouter } from "next/navigation";
import { useEffect } from "react";

import { useLogout, useMe } from "@/lib/api/auth";
import { userMessage } from "@/lib/api/errors";

export default function DashboardPage() {
  const router = useRouter();
  const me = useMe();
  const logout = useLogout();

  // No valid session: go to the login page.
  useEffect(() => {
    if (me.data === null) {
      router.replace("/login");
    }
  }, [me.data, router]);

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
      <header className="border-b border-slate-200 bg-white">
        <div className="mx-auto flex max-w-4xl items-center justify-between px-4 py-3">
          <span className="font-semibold">FormPilot</span>
          <div className="flex items-center gap-4 text-sm">
            <span className="text-slate-600">{me.data.email}</span>
            <button
              type="button"
              onClick={() => logout.mutate(undefined, { onSuccess: () => router.push("/login") })}
              disabled={logout.isPending}
              className="rounded-md border border-slate-300 px-3 py-1.5 font-medium hover:bg-slate-100 disabled:opacity-60"
            >
              Log out
            </button>
          </div>
        </div>
      </header>
      <main className="mx-auto max-w-4xl px-4 py-10">
        <h1 className="mb-2 text-2xl font-semibold">Your forms</h1>
        {logout.isError ? (
          <p role="alert" className="mb-4 text-sm text-red-700">
            {userMessage(logout.error)}
          </p>
        ) : null}
        <div className="rounded-lg border border-dashed border-slate-300 bg-white p-10 text-center text-sm text-slate-500">
          No forms yet. Uploading forms arrives in the next phase.
        </div>
      </main>
    </div>
  );
}
