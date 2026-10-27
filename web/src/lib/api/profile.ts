import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "./client";
import { ApiError, detailMessage } from "./errors";
import type { components } from "./schema";

/** Sensitive values arrive masked (SPEC §8); the page never sees them in full. */
export type Profile = components["schemas"]["ProfileResponse"];
export type ProfileField = components["schemas"]["ProfileFieldInfo"];
export type ProfileUpdate = components["schemas"]["ProfileUpdate"];

export const profileQueryKey = ["profile"] as const;

export function useProfile() {
  return useQuery({
    queryKey: profileQueryKey,
    queryFn: async (): Promise<Profile> => {
      const { data, response } = await api.GET("/api/v1/profile");
      if (!data) {
        throw new ApiError("Could not load your profile.", response.status);
      }
      return data;
    },
    retry: false,
  });
}

/** The API's per-field problems (422) as one readable line; messages never contain values. */
function problemsMessage(error: unknown, labels: Record<string, string>): string {
  if (typeof error === "object" && error !== null && "detail" in error) {
    const { detail } = error as { detail: unknown };
    if (Array.isArray(detail)) {
      return detail
        .map((p: { key?: string; message?: string }) => `${labels[p.key ?? ""] ?? p.key}: ${p.message}`)
        .join(" ");
    }
  }
  return detailMessage(error, "Your profile could not be saved.");
}

export function useUpdateProfile(labels: Record<string, string>) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (update: ProfileUpdate): Promise<Profile> => {
      const { data, error, response } = await api.PUT("/api/v1/profile", { body: update });
      if (data) {
        return data;
      }
      throw new ApiError(problemsMessage(error, labels), response.status);
    },
    onSuccess: (profile) => queryClient.setQueryData(profileQueryKey, profile),
  });
}
