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

/** How long a request waits for the service to answer before it counts as unreachable. */
export const REQUEST_TIMEOUT_MS = 30_000;
/** The same for the photo upload, which is much larger than any other request. */
export const UPLOAD_TIMEOUT_MS = 120_000;

// Stand-in error for a request that never reached the service (offline, wrong address, refused).
const NETWORK_ERROR: ApiError = {
  error: {
    code: "network_unreachable",
    message: "Can't reach the GuardianLens service.",
    field: null,
  },
};
// Stand-in error for an answer that is not the documented error body, or is not valid JSON.
const BAD_RESPONSE: ApiError = {
  error: {
    code: "bad_response",
    message: "The service returned an unexpected response.",
    field: null,
  },
};

/**
 * Reads the body of a failed response as the API's error envelope. A body that is not that
 * envelope (an HTML error page from a proxy, plain text, nothing) gives the "bad_response" error,
 * so a caller can always show a message and never has to handle a thrown parse error.
 */
export async function readApiError(response: Response): Promise<ApiError> {
  try {
    const body = (await response.json()) as Partial<ApiError> | null;
    // Only trust a body that really is the documented error envelope.
    if (body?.error?.code && body.error.message) return body as ApiError;
  } catch {
    // Not JSON: fall through to the stand-in below.
  }
  return BAD_RESPONSE;
}

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

  /**
   * Sends one request with the session attached; turns a network failure, or no answer within
   * `timeoutMs`, into an API error (status 0), so a hung server cannot leave a caller waiting.
   */
  async function send(
    path: string,
    init: RequestInit = {},
    timeoutMs = REQUEST_TIMEOUT_MS,
  ): Promise<Response> {
    const headers = new Headers(init.headers);
    // JSON bodies are strings; FormData sets its own multipart header, so it is left alone.
    if (typeof init.body === "string" && !headers.has("Content-Type")) {
      headers.set("Content-Type", "application/json");
    }
    const controller = new AbortController();
    const request: RequestInit = { ...init, headers, signal: controller.signal };
    if (transport.kind === "cookie") {
      request.credentials = "include";
    } else {
      const token = await transport.store.get();
      if (token) headers.set(SESSION_HEADER, token);
    }
    // Stopped once the answer's headers arrive: the body is small and the server is alive by then.
    const timer = setTimeout(() => controller.abort(), timeoutMs);
    try {
      return await doFetch(`${baseUrl}${path}`, request);
    } catch {
      throw new GuardianLensApiError(0, NETWORK_ERROR);
    } finally {
      clearTimeout(timer);
    }
  }

  /** Parses a response: throws on error statuses, returns undefined for 204, JSON otherwise. */
  async function read<T>(response: Response): Promise<T> {
    if (!response.ok) throw new GuardianLensApiError(response.status, await readApiError(response));
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
    // One try at the upload; it is called a second time only after a stale session is replaced.
    const attempt = async () =>
      read<{ assessment_id: string }>(
        await send("/api/v1/assess", { method: "POST", body: form }, UPLOAD_TIMEOUT_MS),
      );
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
      return read(
        await send(`/api/v1/assess/${id}/feedback`, {
          method: "POST",
          body: JSON.stringify(body),
        }),
      );
    },
    /** Lists this session's checks, newest first. */
    async getHistory(): Promise<HistoryItem[]> {
      return read(await send("/api/v1/session/history"));
    },
    /** Website only: attaches an extension session to this browser by setting the cookie. */
    async claimSession(token: string): Promise<void> {
      return read(
        await send("/api/v1/session/claim", {
          method: "POST",
          body: JSON.stringify({ token }),
        }),
      );
    },
    /** The stored session token (header transport), or null. Used to build the handoff URL. */
    async getToken(): Promise<string | null> {
      return transport.kind === "header" ? transport.store.get() : null;
    },
  };
}

/** The type of the object createClient returns, for code that receives a client. */
export type GuardianLensClient = ReturnType<typeof createClient>;
