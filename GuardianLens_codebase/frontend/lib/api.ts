// The website's thin client for the GuardianLens API: the API origin and one fetch helper. It sends
// the session cookie with every request (credentials: "include") and turns the API's error
// envelope into a typed GuardianLensApiError, so pages can show the message next to a field. The
// error class and the envelope reading are the shared package's, the same ones the extension uses.
import { GuardianLensApiError, REQUEST_TIMEOUT_MS, readApiError } from "@guardianlens/shared";

export { GuardianLensApiError };

/** The API's origin: NEXT_PUBLIC_API_BASE_URL when set, otherwise the local development server. */
export const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

/**
 * Calls one API endpoint with the session cookie attached.
 * @param path The endpoint path, for example "/api/v1/session/history".
 * @param options Standard fetch options; a FormData body keeps its own multipart content type.
 * @returns The parsed JSON body, or undefined for a 204 answer.
 * @throws GuardianLensApiError for any non-success status, including an answer that is not the
 *         API's error envelope (a proxy's HTML error page). A request that never reached the
 *         server, or got no answer within REQUEST_TIMEOUT_MS, throws fetch's own error.
 */
export async function apiFetch<T>(path: string, options?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    ...options,
    credentials: "include",
    signal: AbortSignal.timeout(REQUEST_TIMEOUT_MS),
    headers: {
      ...(options?.body instanceof FormData ? {} : { "Content-Type": "application/json" }),
      ...options?.headers,
    },
  });
  if (!response.ok) {
    throw new GuardianLensApiError(response.status, await readApiError(response));
  }
  if (response.status === 204) {
    return undefined as T;
  }
  return (await response.json()) as T;
}
