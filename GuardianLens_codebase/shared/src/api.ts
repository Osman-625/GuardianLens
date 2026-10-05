// GuardianLens API client, shared by the extension and the website.
//
// It wraps `fetch` for the /api/v1 endpoints and hides the one real difference between the
// two clients: how the buyer's anonymous session travels.
//   - "cookie"  (website): the browser keeps an httpOnly cookie; we only ask for it to be sent.
//   - "header"  (extension): there is no cookie, so the client mints a session token, stores it
//                            through a TokenStore, and sends it as the X-Session-Token header.
// Every failure is surfaced as a GuardianLensApiError so the UI can show a plain message.
import type {
  ApiError,
  AssessmentResult,
  AssessmentStatusResponse,
  FeedbackRequest,
  HistoryItem,
  SessionCreated,
} from "./types";

/**
 * An error from the API or the network. `status` is the HTTP status, or 0 when the service
 * could not be reached. `code` is a stable machine-readable string; `field` names the form
 * field the error belongs to, when there is one.
 */
export class GuardianLensApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly field: string | null;

  constructor(status: number, payload: ApiError) {
    super(payload.error.message);
    this.name = "GuardianLensApiError";
    this.status = status;
    this.code = payload.error.code;
    this.field = payload.error.field;
  }
}

/** Where a header-transport client keeps its token (chrome.storage in the extension). */
export interface TokenStore {
  get(): Promise<string | null>;
  /** Pass null to forget the token. */
  set(token: string | null): Promise<void>;
}

/** How the anonymous session travels with each request. */
export type SessionTransport = { kind: "cookie" } | { kind: "header"; store: TokenStore };

/** Settings for createClient. `fetchImpl` exists so tests can script responses. */
export interface ClientOptions {
  baseUrl: string;
  transport: SessionTransport;
  fetchImpl?: typeof fetch;
}

// Header the API reads for the extension's session token.
const SESSION_HEADER = "X-Session-Token";

// Synthetic errors for failures that never produced a proper API error body.
const NETWORK_ERROR: ApiError = {
  error: { code: "network_unreachable", message: "Can't reach the GuardianLens service.", field: null },
};
const BAD_RESPONSE: ApiError = {
  error: { code: "bad_response", message: "The service returned an unexpected response.", field: null },
};

/**
 * Creates an API client.
 * @param options Base URL (no trailing slash needed), the session transport, and an optional
 *                fetch override for tests.
 * @returns An object with one method per endpoint the clients use.
 */
export function createClient(options: ClientOptions) {
  const baseUrl = options.baseUrl.replace(/\/+$/, "");
  // Wrapped so `fetch` is always called with the right `this`, whatever the environment.
  const doFetch: typeof fetch = options.fetchImpl ?? ((input, init) => fetch(input, init));
  const { transport } = options;

  /** Sends one request with the session attached; turns a network failure into an API error. */
  async function send(path: string, init: RequestInit = {}): Promise<Response> {
    const headers = new Headers(init.headers);
    // JSON bodies are strings; FormData sets its own multipart header, so it is left alone.
    if (typeof init.body === "string" && !headers.has("Content-Type")) {
      headers.set("Content-Type", "application/json");
    }
    const request: RequestInit = { ...init, headers };
    if (transport.kind === "cookie") {
      request.credentials = "include";
    } else {
      const token = await transport.store.get();
      if (token) headers.set(SESSION_HEADER, token);
    }
    try {
      return await doFetch(`${baseUrl}${path}`, request);
    } catch {
      throw new GuardianLensApiError(0, NETWORK_ERROR);
    }
  }

  /** Parses a response: throws on error statuses, returns undefined for 204, JSON otherwise. */
  async function read<T>(response: Response): Promise<T> {
    if (!response.ok) {
      let payload: ApiError = BAD_RESPONSE;
      try {
        const body = (await response.json()) as Partial<ApiError> | null;
        // Only trust a body that really is the documented error envelope.
        if (body?.error?.code && body.error.message) payload = body as ApiError;
      } catch {
        payload = BAD_RESPONSE;
      }
      throw new GuardianLensApiError(response.status, payload);
    }
    if (response.status === 204) return undefined as T;
    return (await response.json()) as T;
  }

  /** Header transport only: makes sure a session token is stored, minting one if needed. */
  async function ensureSession(): Promise<void> {
    if (transport.kind !== "header") return;
    if (await transport.store.get()) return;
    const created = await read<SessionCreated>(await send("/api/v1/session", { method: "POST" }));
    await transport.store.set(created.session_token);
  }

  /**
   * Submits a listing. For header clients, a "session_invalid" answer means the server no
   * longer knows the stored token (for example it restarted), so the client forgets the
   * token, mints a fresh session, and retries exactly once. The same FormData is reused.
   */
  async function submit(form: FormData): Promise<{ assessment_id: string }> {
    await ensureSession();
    const attempt = async () =>
      read<{ assessment_id: string }>(await send("/api/v1/assess", { method: "POST", body: form }));
    try {
      return await attempt();
    } catch (error) {
      if (
        transport.kind === "header" &&
        error instanceof GuardianLensApiError &&
        error.code === "session_invalid"
      ) {
        await transport.store.set(null);
        await ensureSession();
        return attempt();
      }
      throw error;
    }
  }

  return {
    ensureSession,
    submit,
    /** Polls the processing stage of an assessment. */
    async getStatus(id: string): Promise<AssessmentStatusResponse> {
      return read(await send(`/api/v1/assess/${id}/status`));
    },
    /** Fetches the finished result (409 while it is not ready, 404 for a foreign session). */
    async getResult(id: string): Promise<AssessmentResult> {
      return read(await send(`/api/v1/assess/${id}/result`));
    },
    /** Abandons a running assessment. */
    async cancel(id: string): Promise<void> {
      return read(await send(`/api/v1/assess/${id}/cancel`, { method: "POST" }));
    },
    /** Saves the buyer's helpful / unclear / potentially incorrect choice. */
    async sendFeedback(id: string, body: FeedbackRequest): Promise<void> {
      return read(await send(`/api/v1/assess/${id}/feedback`, { method: "POST", body: JSON.stringify(body) }));
    },
    /** Lists this session's checks, newest first. */
    async getHistory(): Promise<HistoryItem[]> {
      return read(await send("/api/v1/session/history"));
    },
    /** Website only: attaches an extension session to this browser by setting the cookie. */
    async claimSession(token: string): Promise<void> {
      return read(await send("/api/v1/session/claim", { method: "POST", body: JSON.stringify({ token }) }));
    },
    /** The stored session token (header transport), or null. Used to build the handoff URL. */
    async getToken(): Promise<string | null> {
      return transport.kind === "header" ? transport.store.get() : null;
    },
  };
}

/** The type of the object createClient returns, for code that receives a client. */
export type GuardianLensClient = ReturnType<typeof createClient>;
