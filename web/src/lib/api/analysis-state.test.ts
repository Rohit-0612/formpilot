// Run with `npm test` (Node's built-in test runner; no extra dependency).
import assert from "node:assert/strict";
import { test } from "node:test";

import { analysisStep, isAnalysing } from "./analysis-state.ts";
import type { components } from "./schema";

type DocumentInfo = components["schemas"]["DocumentResponse"];
type Job = NonNullable<DocumentInfo["job"]>;

function doc(status: DocumentInfo["status"], job: Partial<Job> | null): DocumentInfo {
  return {
    id: "d",
    original_filename: "form.pdf",
    status,
    source_kind: "flat_text",
    page_count: 1,
    created_at: "2026-10-27T00:00:00Z",
    expires_at: "2026-10-28T00:00:00Z",
    job: job && { id: "j", type: "analyze", status: "running", error_message: null, ...job },
  };
}

test("waits while the document is uploaded or being detected", () => {
  assert.equal(isAnalysing(doc("uploaded", { status: "queued" })), true);
  assert.equal(isAnalysing(doc("analyzing", { status: "running" })), true);
});

test("keeps waiting after detection while the analyze job understands and fills", () => {
  // The document is `ready` once detection is stored; understanding and filling still run.
  assert.equal(isAnalysing(doc("ready", { status: "running" })), true);
  assert.equal(isAnalysing(doc("ready", { status: "queued" })), true);
  assert.equal(analysisStep(doc("ready", { status: "running" })), "filling");
});

test("is done when the analyze job is done or failed", () => {
  assert.equal(isAnalysing(doc("ready", { status: "done" })), false);
  assert.equal(isAnalysing(doc("failed", { status: "failed" })), false);
  assert.equal(isAnalysing(doc("ready", null)), false);
});

test("an answers job does not hide the form (the questions panel follows it)", () => {
  assert.equal(isAnalysing(doc("ready", { type: "answers", status: "running" })), false);
});
