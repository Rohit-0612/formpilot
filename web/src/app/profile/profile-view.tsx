"use client";

import { type FormEvent, useMemo, useState } from "react";

import { AppHeader } from "@/components/app-header";
import { useRequireUser } from "@/lib/api/auth";
import { userMessage } from "@/lib/api/errors";
import { type Profile, type ProfileField, useProfile, useUpdateProfile } from "@/lib/api/profile";

const inputClass =
  "w-full rounded-md border border-slate-300 px-3 py-2 text-sm focus:border-slate-500 focus:outline-none disabled:bg-slate-50";

function groupsOf(fields: ProfileField[]): [string, ProfileField[]][] {
  const groups = new Map<string, ProfileField[]>();
  for (const field of fields) {
    groups.set(field.group, [...(groups.get(field.group) ?? []), field]);
  }
  return [...groups.entries()];
}

function ProfileForm({ profile }: { profile: Profile }) {
  const labels = useMemo(
    () => Object.fromEntries(profile.fields.map((f) => [f.key, f.label])),
    [profile.fields],
  );
  const update = useUpdateProfile(labels);
  // Edited values only; a sensitive field's stored value is masked and never put in an input.
  const [edits, setEdits] = useState<Record<string, string>>({});
  const [optIn, setOptIn] = useState<Record<string, boolean>>({});
  const [saved, setSaved] = useState(false);

  const optedIn = (key: string) => optIn[key] ?? profile.sensitive_opt_in.includes(key);

  function onSubmit(event: FormEvent) {
    event.preventDefault();
    const values = Object.fromEntries(
      Object.entries(edits).map(([key, value]) => [key, value.trim() ? value : null]),
    );
    const changedOptIn = Object.fromEntries(
      Object.entries(optIn).filter(([key, on]) => on !== profile.sensitive_opt_in.includes(key)),
    );
    setSaved(false);
    update.mutate(
      { values, sensitive_opt_in: changedOptIn },
      {
        onSuccess: () => {
          setEdits({});
          setOptIn({});
          setSaved(true);
        },
      },
    );
  }

  return (
    <form onSubmit={onSubmit} className="space-y-6">
      {groupsOf(profile.fields).map(([group, fields]) => (
        <fieldset key={group} className="rounded-lg border border-slate-200 bg-white p-4">
          <legend className="px-1 text-sm font-semibold">{group}</legend>
          <div className="grid gap-4 sm:grid-cols-2">
            {fields.map((field) => {
              const stored = profile.values[field.key];
              const locked = field.sensitive && !optedIn(field.key);
              return (
                <div key={field.key} className="text-xs text-slate-600">
                  <label htmlFor={`profile-${field.key}`}>{field.label}</label>
                  <input
                    id={`profile-${field.key}`}
                    type={field.key === "date_of_birth" ? "date" : "text"}
                    autoComplete="off"
                    disabled={locked}
                    placeholder={field.sensitive && stored ? `Saved: ${stored}` : undefined}
                    value={edits[field.key] ?? (field.sensitive ? "" : (stored ?? ""))}
                    onChange={(event) => setEdits({ ...edits, [field.key]: event.target.value })}
                    className={inputClass}
                  />
                  {field.sensitive ? (
                    <label className="mt-1 flex items-center gap-2">
                      <input
                        type="checkbox"
                        checked={optedIn(field.key)}
                        onChange={(event) => setOptIn({ ...optIn, [field.key]: event.target.checked })}
                      />
                      Allow saving my {field.label} (stored encrypted; unticking deletes it)
                    </label>
                  ) : null}
                </div>
              );
            })}
          </div>
        </fieldset>
      ))}
      {update.isError ? (
        <p role="alert" className="text-sm text-red-700">
          {userMessage(update.error)}
        </p>
      ) : null}
      {saved ? (
        <p role="status" className="text-sm text-emerald-700">
          Profile saved.
        </p>
      ) : null}
      <button
        type="submit"
        disabled={update.isPending}
        className="rounded-md bg-slate-900 px-4 py-2 text-sm font-medium text-white hover:bg-slate-700 disabled:opacity-60"
      >
        {update.isPending ? "Saving…" : "Save profile"}
      </button>
    </form>
  );
}

export function ProfileView() {
  const me = useRequireUser();
  const profile = useProfile();
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
      <main className="mx-auto max-w-5xl px-4 py-8">
        <h1 className="mb-1 text-2xl font-semibold">Your profile</h1>
        <p className="mb-6 text-sm text-slate-600">
          FormPilot fills forms from these values. They are stored encrypted. ID numbers (PAN,
          Aadhaar, passport, voter ID, bank account) are saved only for the fields you allow, and
          are shown masked.
        </p>
        {profile.isPending ? (
          <p className="text-sm text-slate-500">Loading your profile…</p>
        ) : profile.isError ? (
          <p role="alert" className="text-sm text-red-700">
            {userMessage(profile.error)}
          </p>
        ) : (
          <ProfileForm profile={profile.data} />
        )}
      </main>
    </div>
  );
}
