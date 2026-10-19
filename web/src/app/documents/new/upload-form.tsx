"use client";

import { useRouter } from "next/navigation";
import { type FormEvent, useState } from "react";

import { AppHeader } from "@/components/app-header";
import { FormMessage, SubmitButton } from "@/components/auth-card";
import { useRequireUser } from "@/lib/api/auth";
import { MAX_UPLOAD_MB, useUpload } from "@/lib/api/documents";
import { userMessage } from "@/lib/api/errors";

export function UploadForm() {
  const router = useRouter();
  const me = useRequireUser();
  const upload = useUpload();
  const [file, setFile] = useState<File | null>(null);

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

  function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (file) {
      upload.mutate(file, {
        onSuccess: ({ document_id }) => router.push(`/documents/${document_id}`),
      });
    }
  }

  return (
    <div className="min-h-screen">
      <AppHeader email={me.data.email} />
      <main className="mx-auto max-w-xl px-4 py-10">
        <h1 className="mb-2 text-2xl font-semibold">Upload a form</h1>
        <p className="mb-6 text-sm text-slate-600">
          A blank PDF form, up to {MAX_UPLOAD_MB} MB. FormPilot finds the places to fill in.
        </p>
        <form onSubmit={onSubmit} className="rounded-lg border border-slate-200 bg-white p-6 shadow-sm">
          {upload.isError ? (
            <FormMessage tone="error">{userMessage(upload.error)}</FormMessage>
          ) : null}
          <label className="mb-4 block">
            <span className="mb-1 block text-sm font-medium text-slate-700">PDF file</span>
            <input
              type="file"
              name="file"
              accept="application/pdf,.pdf"
              required
              onChange={(event) => {
                upload.reset();
                setFile(event.target.files?.[0] ?? null);
              }}
              className="block w-full text-sm file:mr-3 file:rounded-md file:border file:border-slate-300 file:bg-white file:px-3 file:py-1.5 file:text-sm file:font-medium hover:file:bg-slate-100"
            />
          </label>
          <SubmitButton pending={upload.isPending}>
            {upload.isPending ? "Uploading…" : "Upload"}
          </SubmitButton>
        </form>
      </main>
    </div>
  );
}
