import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "./client";
import { documentQueryKey } from "./documents";
import { ApiError, detailMessage } from "./errors";
import type { components } from "./schema";

export type Question = components["schemas"]["Question"];
export type QuestionPart = components["schemas"]["QuestionPart"];
export type Answer = components["schemas"]["Answer"];
export type Job = components["schemas"]["JobResponse"];

const POLL_MS = 1500;

export function questionsQueryKey(documentId: string) {
  return [...documentQueryKey(documentId), "questions"] as const;
}

export function useQuestions(documentId: string, enabled: boolean) {
  return useQuery({
    queryKey: questionsQueryKey(documentId),
    queryFn: async () => {
      const { data, response } = await api.GET("/api/v1/documents/{document_id}/questions", {
        params: { path: { document_id: documentId } },
      });
      if (!data) {
        throw new ApiError("Could not load the questions.", response.status);
      }
      return data;
    },
    enabled,
    retry: false,
  });
}

export function useSubmitAnswers(documentId: string) {
  return useMutation({
    mutationFn: async (answers: Answer[]): Promise<string> => {
      const { data, error, response } = await api.POST(
        "/api/v1/documents/{document_id}/answers",
        { params: { path: { document_id: documentId } }, body: { answers } },
      );
      if (data) {
        return data.job_id;
      }
      throw new ApiError(detailMessage(error, "Your answers could not be sent."), response.status);
    },
  });
}

function finished(job: Job | undefined): boolean {
  return job?.status === "done" || job?.status === "failed";
}

/** Polls the answers job; when it is done, the form and its questions are loaded again. */
export function useAnswersJob(documentId: string, jobId: string | null) {
  const queryClient = useQueryClient();
  return useQuery({
    queryKey: ["jobs", jobId],
    queryFn: async (): Promise<Job> => {
      const { data, response } = await api.GET("/api/v1/jobs/{job_id}", {
        params: { path: { job_id: jobId ?? "" } },
      });
      if (!data) {
        throw new ApiError("Could not check your answers' progress.", response.status);
      }
      if (finished(data)) {
        await queryClient.invalidateQueries({ queryKey: documentQueryKey(documentId) });
      }
      return data;
    },
    enabled: jobId !== null,
    refetchInterval: (query) => (finished(query.state.data) ? false : POLL_MS),
    retry: false,
  });
}
