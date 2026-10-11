/** Thrown by the API hooks; `message` is safe to show to the user. */
export class ApiError extends Error {
  constructor(
    message: string,
    readonly status?: number,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

/** The API's own message when it is a plain string (`{"detail": "..."}`), else the fallback. */
export function detailMessage(error: unknown, fallback: string): string {
  if (typeof error === "object" && error !== null && "detail" in error) {
    const { detail } = error as { detail: unknown };
    if (typeof detail === "string") {
      return detail;
    }
  }
  return fallback;
}

/** fetch() itself failed: the API is down or unreachable (or CORS refused the call). */
export function isNetworkError(error: unknown): boolean {
  return error instanceof TypeError;
}

export function userMessage(error: unknown): string {
  if (error instanceof ApiError) {
    return error.message;
  }
  if (isNetworkError(error)) {
    return "Cannot reach the FormPilot server. Is it running?";
  }
  return "Something went wrong. Please try again.";
}
