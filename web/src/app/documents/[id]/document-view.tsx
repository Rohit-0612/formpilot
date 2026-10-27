"use client";

import Link from "next/link";
import type { ReactNode } from "react";

import { AppHeader } from "@/components/app-header";
import { PageViewer } from "@/components/page-viewer";
import { useRequireUser } from "@/lib/api/auth";
import { type DocumentInfo, isAnalysing, useDocument, useMaskedIr } from "@/lib/api/documents";
import { userMessage } from "@/lib/api/errors";

import { QuestionsPanel } from "./questions-panel";

const SOURCE_KIND: Record<string, string> = {
  flat_text: "PDF with a text layer",
  fillable: "fillable PDF form",
  scanned: "scanned PDF",
  photo: "photo",
};

function Notice({ tone, children }: { tone: "error" | "info"; children: ReactNode }) {
  const colours =
    tone === "error"
      ? "border-red-200 bg-red-50 text-red-800"
      : "border-slate-200 bg-white text-slate-700";
  return (
    <div
      role={tone === "error" ? "alert" : "status"}
      className={`rounded-lg border p-6 text-sm ${colours}`}
    >
      {children}
    </div>
  );
}

function UploadAnother() {
  return (
    <Link href="/documents/new" className="mt-3 inline-block font-medium underline">
      Upload another form
    </Link>
  );
}

function Analysing({ document }: { document: DocumentInfo }) {
  const message =
    document.status === "uploaded"
      ? "Waiting for the analysis to start…"
      : "Analysing the form…";
  return (
    <Notice tone="info">
      <span className="mr-2 inline-block h-3 w-3 animate-spin rounded-full border-2 border-slate-400 border-t-transparent align-middle" />
      {message}
    </Notice>
  );
}

function Failed({ document }: { document: DocumentInfo }) {
  // The API's readable message for the job's error (Step 8), never an internal error text.
  const message = document.job?.error_message ?? "The analysis failed.";
  return (
    <Notice tone="error">
      <p>{message}</p>
      <UploadAnother />
    </Notice>
  );
}

function Ready({ documentId, document }: { documentId: string; document: DocumentInfo }) {
  const ir = useMaskedIr(documentId, true);
  if (ir.isPending) {
    return <p className="text-sm text-slate-500">Loading the detected fields…</p>;
  }
  if (ir.isError) {
    return <Notice tone="error">{userMessage(ir.error)}</Notice>;
  }
  const fields = ir.data.fields ?? [];
  const fieldCount = fields.length;
  const fromProfile = fields.filter(
    (f) => f.value_source === "profile" || f.value_source === "derived",
  ).length;
  const kind = document.source_kind ? SOURCE_KIND[document.source_kind] : null;
  return (
    <>
      <p className="mb-4 text-sm text-slate-600">
        {kind ? `${kind[0].toUpperCase()}${kind.slice(1)}, ` : ""}
        {ir.data.pages.length} {ir.data.pages.length === 1 ? "page" : "pages"}, {fieldCount}{" "}
        {fieldCount === 1 ? "field" : "fields"} detected, {fromProfile} filled from{" "}
        <Link href="/profile" className="underline">
          your profile
        </Link>
        .
      </p>
      <section aria-labelledby="questions-heading" className="mb-8">
        <h2 id="questions-heading" className="mb-3 text-lg font-semibold">
          Questions
        </h2>
        <QuestionsPanel documentId={documentId} />
      </section>
      <PageViewer documentId={documentId} ir={ir.data} />
    </>
  );
}

function Body({ documentId }: { documentId: string }) {
  const document = useDocument(documentId);
  if (document.isPending) {
    return <p className="text-sm text-slate-500">Loading…</p>;
  }
  if (document.isError) {
    return <Notice tone="error">{userMessage(document.error)}</Notice>;
  }
  if (document.data === null) {
    return (
      <Notice tone="error">
        <p>This form was not found. It may have expired or belong to another account.</p>
        <UploadAnother />
      </Notice>
    );
  }
  const doc = document.data;
  return (
    <>
      <h1 className="mb-1 truncate text-2xl font-semibold" title={doc.original_filename}>
        {doc.original_filename}
      </h1>
      <div className="mt-4">
        {isAnalysing(doc) ? (
          <Analysing document={doc} />
        ) : doc.status === "failed" ? (
          <Failed document={doc} />
        ) : (
          <Ready documentId={documentId} document={doc} />
        )}
      </div>
    </>
  );
}

export function DocumentView({ documentId }: { documentId: string }) {
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
      <main className="mx-auto max-w-5xl px-4 py-8">
        <Body documentId={documentId} />
      </main>
    </div>
  );
}
