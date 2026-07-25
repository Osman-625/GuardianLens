import type { ApiError } from "@/lib/types";

export const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

export class GuardianLensApiError extends Error {
  readonly code: string;
  readonly field: string | null;
  readonly status: number;

  constructor(status: number, payload: ApiError) {
    super(payload.error.message);
    this.name = "GuardianLensApiError";
    this.status = status;
    this.code = payload.error.code;
    this.field = payload.error.field;
  }
}

export async function apiFetch<T>(path: string, options?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    ...options,
    credentials: "include",
    headers: {
      ...(options?.body instanceof FormData ? {} : { "Content-Type": "application/json" }),
      ...options?.headers,
    },
  });
  if (!response.ok) {
    const payload = (await response.json()) as ApiError;
    throw new GuardianLensApiError(response.status, payload);
  }
  if (response.status === 204) {
    return undefined as T;
  }
  return (await response.json()) as T;
}
