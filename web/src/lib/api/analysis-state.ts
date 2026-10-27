import type { components } from "./schema";

type DocumentInfo = components["schemas"]["DocumentResponse"];

/**
 * Where the analysis is. The document is `ready` as soon as detection is stored (Form IR v1),
 * but the analyze job then understands and fills the form (v2, v3); the fields and questions are
 * only loaded once that job has finished, or the page would show the detection-only version.
 */
export type AnalysisStep = "waiting" | "detecting" | "filling" | "done";

export function analysisStep(document: DocumentInfo | null | undefined): AnalysisStep {
  if (document?.status === "uploaded") {
    return "waiting";
  }
  if (document?.status === "analyzing") {
    return "detecting";
  }
  const job = document?.job;
  const running = job?.status === "queued" || job?.status === "running";
  if (document?.status === "ready" && job?.type === "analyze" && running) {
    return "filling";
  }
  return "done";
}

/** Still waiting for the analyze job: keep polling, do not load fields or questions yet. */
export function isAnalysing(document: DocumentInfo | null | undefined): boolean {
  return analysisStep(document) !== "done";
}
