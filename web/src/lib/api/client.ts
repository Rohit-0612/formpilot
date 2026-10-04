import createClient from "openapi-fetch";

import type { components, paths } from "./schema";

// Inlined at build time (NEXT_PUBLIC_*), so the Docker image gets it as a build argument.
const baseUrl = process.env.NEXT_PUBLIC_API_URL;
if (!baseUrl) {
  throw new Error("NEXT_PUBLIC_API_URL is not set");
}

/** Typed client generated from the backend's OpenAPI schema (`make types`). */
export const api = createClient<paths>({
  baseUrl,
  // Send and receive the httpOnly session cookie on cross-origin calls to the API.
  credentials: "include",
});

export type User = components["schemas"]["UserResponse"];
