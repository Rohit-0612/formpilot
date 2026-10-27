import { useMutation, useQuery } from "@tanstack/react-query";

import { api } from "./client";
import { ApiError, detailMessage } from "./errors";
import type { components } from "./schema";

export type DocumentInfo = components["schemas"]["DocumentResponse"];
export type UploadResult = components["schemas"]["UploadResponse"];

/**
 * The only Form IR type the web app uses. The API returns IRs only in this masked form (SPEC §8:
 * sensitive values masked in every response); the viewer never shows values at all.
 */
export type MaskedFormIR = components["schemas"]["MaskedFormIR"];
export type IrField = components["schemas"]["Field"];
export type PageInfo = components["schemas"]["PageInfo"];

// Guard: the generated schema has no plain (unmasked) FormIR. If one ever appears, this line
// stops being an error and `npm run typecheck` fails, so nobody starts using it by accident.
// @ts-expect-error -- the API must never expose an unmasked FormIR
export type _NoUnmaskedFormIR = components["schemas"]["FormIR"];

/**
 * Same limit as the API's MAX_UPLOAD_MB (keep the two equal). The API is the authority; this
 * check only gives the readable message early, because a browser often reports the API's early
 * 413 as a network error.
 */
const configuredMb = Number(process.env.NEXT_PUBLIC_MAX_UPLOAD_MB ?? "20");
export const MAX_UPLOAD_MB = Number.isFinite(configuredMb) && configuredMb > 0 ? configuredMb : 20;

const POLL_MS = 1500;

export function documentQueryKey(documentId: string) {
  return ["documents", documentId] as const;
}

/** Still waiting for the worker: keep polling. */
export function isAnalysing(document: DocumentInfo | null | undefined): boolean {
  return document?.status === "uploaded" || document?.status === "analyzing";
}

export function useUpload() {
  return useMutation({
    mutationFn: async (file: File): Promise<UploadResult> => {
      if (file.size > MAX_UPLOAD_MB * 1024 * 1024) {
        throw new ApiError(`The file is larger than ${MAX_UPLOAD_MB} MB.`, 413);
      }
      const { data, error, response } = await api.POST("/api/v1/documents", {
        // openapi-typescript types a binary multipart part as `string`; the part is the File.
        body: { file: file as unknown as string },
        bodySerializer: () => {
          const form = new FormData();
          form.append("file", file);
          return form;
        },
      });
      if (data) {
        return data;
      }
      throw new ApiError(detailMessage(error, "The upload failed."), response.status);
    },
  });
}

/** The document and its latest job; `null` when it does not exist or is someone else's (404). */
export function useDocument(documentId: string) {
  return useQuery({
    queryKey: documentQueryKey(documentId),
    queryFn: async (): Promise<DocumentInfo | null> => {
      const { data, response } = await api.GET("/api/v1/documents/{document_id}", {
        params: { path: { document_id: documentId } },
      });
      if (response.status === 404 || response.status === 422) {
        return null; // 422: not a valid id, so no such document either
      }
      if (!data) {
        throw new ApiError("Could not load the form.", response.status);
      }
      return data;
    },
    refetchInterval: (query) => (isAnalysing(query.state.data) ? POLL_MS : false),
    retry: false,
  });
}

/** The analysed form as the masked IR; only fetched once the document is ready. */
export function useMaskedIr(documentId: string, enabled: boolean) {
  return useQuery({
    queryKey: [...documentQueryKey(documentId), "ir"],
    queryFn: async (): Promise<MaskedFormIR> => {
      const { data, response } = await api.GET("/api/v1/documents/{document_id}/ir", {
        params: { path: { document_id: documentId } },
      });
      if (!data) {
        throw new ApiError("Could not load the detected fields.", response.status);
      }
      return data;
    },
    enabled,
    // A new version arrives after answers; useAnswersJob invalidates this query then.
    staleTime: Infinity,
    retry: false,
  });
}

/**
 * A page image as a Blob, fetched with the session cookie (an <img src> pointing at the API would
 * depend on cross-origin cookies). Page images never change, so they are cached for the session.
 */
export function usePageImage(documentId: string, page: number) {
  return useQuery({
    queryKey: [...documentQueryKey(documentId), "page", page],
    queryFn: async (): Promise<Blob> => {
      const { data, response } = await api.GET("/api/v1/documents/{document_id}/pages/{page}.png", {
        params: { path: { document_id: documentId, page } },
        parseAs: "blob",
      });
      if (!response.ok || !(data instanceof Blob)) {
        throw new ApiError("Could not load the page image.", response.status);
      }
      return data;
    },
    staleTime: Infinity,
    retry: false,
  });
}
