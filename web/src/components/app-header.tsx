"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";

import { useLogout } from "@/lib/api/auth";
import { userMessage } from "@/lib/api/errors";

/** Header of the signed-in pages: brand (to the dashboard), the user's email, log out. */
export function AppHeader({ email }: { email: string }) {
  const router = useRouter();
  const logout = useLogout();

  return (
    <header className="border-b border-slate-200 bg-white">
      <div className="mx-auto flex max-w-5xl items-center justify-between px-4 py-3">
        <Link href="/dashboard" className="font-semibold">
          FormPilot
        </Link>
        <div className="flex items-center gap-4 text-sm">
          {logout.isError ? (
            <span role="alert" className="text-red-700">
              {userMessage(logout.error)}
            </span>
          ) : null}
          <Link href="/profile" className="font-medium hover:underline">
            Profile
          </Link>
          <span className="text-slate-600">{email}</span>
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
  );
}
