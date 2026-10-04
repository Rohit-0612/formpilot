import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api, type User } from "./client";
import { ApiError, detailMessage } from "./errors";

export const meQueryKey = ["auth", "me"] as const;

type Credentials = { email: string; password: string };

/** The logged-in user, or `null` when there is no valid session (401). */
export function useMe() {
  return useQuery({
    queryKey: meQueryKey,
    queryFn: async (): Promise<User | null> => {
      const { data, response } = await api.GET("/api/v1/auth/me");
      if (response.status === 401) {
        return null;
      }
      if (!data) {
        throw new ApiError("Could not load your account.", response.status);
      }
      return data;
    },
    retry: false,
  });
}

export function useRegister() {
  return useMutation({
    mutationFn: async (body: Credentials): Promise<User> => {
      const { data, error, response } = await api.POST("/api/v1/auth/register", { body });
      if (data) {
        return data;
      }
      if (response.status === 422) {
        throw new ApiError(
          "Enter a valid email address and a password of at least 8 characters.",
          422,
        );
      }
      throw new ApiError(detailMessage(error, "Registration failed."), response.status);
    },
  });
}

export function useLogin() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (body: Credentials): Promise<User> => {
      const { data, error, response } = await api.POST("/api/v1/auth/login", { body });
      if (data) {
        return data;
      }
      if (response.status === 401 || response.status === 422) {
        throw new ApiError("Invalid email or password.", response.status);
      }
      throw new ApiError(detailMessage(error, "Login failed."), response.status);
    },
    onSuccess: (user) => queryClient.setQueryData(meQueryKey, user),
  });
}

export function useLogout() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (): Promise<void> => {
      const { response } = await api.POST("/api/v1/auth/logout");
      if (!response.ok) {
        throw new ApiError("Logout failed.", response.status);
      }
    },
    onSuccess: () => {
      queryClient.clear();
      queryClient.setQueryData(meQueryKey, null);
    },
  });
}
