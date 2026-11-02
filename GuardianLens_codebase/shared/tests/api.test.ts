// @vitest-environment node
// Pins the behaviour of the GuardianLens API client (shared by the extension and, later, the
// website) using a fake `fetch`, so no server is needed. The "node" environment above gives
// real Response, Headers and FormData objects.
//
// What matters here:
//  - the cookie transport sends credentials; the header transport sends X-Session-Token;
//  - a header client mints its own session once, and recovers from a stale token by minting
//    a new one and retrying the submission exactly once (backend restarts drop sessions);
//  - every failure is turned into a GuardianLensApiError the UI can show.
import { afterEach, describe, expect, it, vi } from "vitest";
import {
  GuardianLensApiError,
  REQUEST_TIMEOUT_MS,
  UPLOAD_TIMEOUT_MS,
  createClient,
  readApiError,
  type TokenStore,
} from "../src/api";

/** One recorded request: the URL fetched and the options it was fetched with. */
interface Call {
  url: string;
  init: RequestInit;
}

/** Builds a JSON Response with the given status. */
function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

/**
 * A scripted fetch: the Nth request is answered by the Nth handler, and every request is
 * recorded in `calls`. A request with no handler left fails the test loudly.
 */
function fakeFetch(handlers: Array<(call: Call) => Response | Promise<Response>>) {
  const calls: Call[] = [];
  const impl = (async (input: RequestInfo | URL, init?: RequestInit) => {
    const call = { url: String(input), init: init ?? {} };
    calls.push(call);
    const handler = handlers[calls.length - 1];
    if (!handler) throw new Error(`Unexpected request ${calls.length}: ${call.url}`);
    return handler(call);
  }) as typeof fetch;
  return { impl, calls };
}

/** An in-memory TokenStore; `value` lets a test read what was stored. */
function memoryStore(initial: string | null = null): TokenStore & { value: string | null } {
  const store = {
    value: initial,
    async get() {
      return store.value;
    },
    async set(token: string | null) {
      store.value = token;
    },
  };
  return store;
}

/** Reads one header off a recorded request. */
function headerOf(call: Call, name: string): string | null {
  return new Headers(call.init.headers).get(name);
}

// Website transport: the browser holds an httpOnly cookie, so the client only asks for it to be sent.
describe("cookie transport", () => {
  it("sends credentials and no session header", async () => {
    const { impl, calls } = fakeFetch([() => json([])]);
    const client = createClient({
      baseUrl: "http://api.test",
      transport: { kind: "cookie" },
      fetchImpl: impl,
    });
    await client.getHistory();
    expect(calls[0].url).toBe("http://api.test/api/v1/session/history");
    expect(calls[0].init.credentials).toBe("include");
    expect(headerOf(calls[0], "X-Session-Token")).toBeNull();
  });
});

// Extension transport: no cookie, so the client owns an opaque token and sends it as a header.
describe("header transport", () => {
  it("mints a session once and attaches the token", async () => {
    const store = memoryStore();
    const { impl, calls } = fakeFetch([
      () => json({ session_token: "token-1" }, 201),
      () => json({ assessment_id: "a1" }, 202),
      () => json({ status: "complete", stage: null, message: null }),
    ]);
    const client = createClient({
      baseUrl: "http://api.test",
      transport: { kind: "header", store },
      fetchImpl: impl,
    });

    await client.submit(new FormData());
    await client.getStatus("a1");

    expect(calls.map((call) => call.url)).toEqual([
      "http://api.test/api/v1/session",
      "http://api.test/api/v1/assess",
      "http://api.test/api/v1/assess/a1/status",
    ]);
    expect(store.value).toBe("token-1");
    expect(headerOf(calls[1], "X-Session-Token")).toBe("token-1");
    expect(headerOf(calls[2], "X-Session-Token")).toBe("token-1");
    // Header clients must not send cookies.
    expect(calls[1].init.credentials).toBeUndefined();
  });

  // The backend restarted and no longer knows the stored token, so the client replaces it.
  it("mints a new session and retries once when the stored token is rejected", async () => {
    const store = memoryStore("stale");
    const { impl, calls } = fakeFetch([
      () =>
        json(
          {
            error: { code: "session_invalid", message: "expired", field: null },
          },
          401,
        ),
      () => json({ session_token: "fresh" }, 201),
      () => json({ assessment_id: "a2" }, 202),
    ]);
    const client = createClient({
      baseUrl: "http://api.test",
      transport: { kind: "header", store },
      fetchImpl: impl,
    });

    const accepted = await client.submit(new FormData());

    expect(accepted.assessment_id).toBe("a2");
    expect(store.value).toBe("fresh");
    expect(headerOf(calls[0], "X-Session-Token")).toBe("stale");
    expect(headerOf(calls[2], "X-Session-Token")).toBe("fresh");
  });

  it("does not retry a second time", async () => {
    const store = memoryStore("stale");
    // A scripted answer saying the server does not recognise the session token.
    const invalid = () =>
      json({ error: { code: "session_invalid", message: "expired", field: null } }, 401);
    const { impl, calls } = fakeFetch([
      invalid,
      () => json({ session_token: "fresh" }, 201),
      invalid,
    ]);
    const client = createClient({
      baseUrl: "http://api.test",
      transport: { kind: "header", store },
      fetchImpl: impl,
    });

    await expect(client.submit(new FormData())).rejects.toMatchObject({
      code: "session_invalid",
    });
    // stale attempt, mint, one retry: three requests and then it gives up.
    expect(calls).toHaveLength(3);
  });
});

// Every failure becomes a GuardianLensApiError so the panel and site can show a plain message.
describe("errors", () => {
  it("maps the error envelope", async () => {
    const { impl } = fakeFetch([
      () =>
        json(
          {
            error: {
              code: "invalid_price",
              message: "Enter a valid non-negative price.",
              field: "price",
            },
          },
          422,
        ),
    ]);
    const client = createClient({
      baseUrl: "http://api.test",
      transport: { kind: "cookie" },
      fetchImpl: impl,
    });

    const error = await client.submit(new FormData()).catch((caught: unknown) => caught);

    expect(error).toBeInstanceOf(GuardianLensApiError);
    expect(error).toMatchObject({
      status: 422,
      code: "invalid_price",
      field: "price",
    });
  });

  it("reports an unreachable service", async () => {
    const impl = (async () => {
      throw new TypeError("fetch failed");
    }) as typeof fetch;
    const client = createClient({
      baseUrl: "http://api.test",
      transport: { kind: "cookie" },
      fetchImpl: impl,
    });

    await expect(client.getHistory()).rejects.toMatchObject({
      status: 0,
      code: "network_unreachable",
    });
  });

  it("reports a body that is not the error envelope", async () => {
    // For example an HTML error page from a proxy in front of the API.
    const { impl } = fakeFetch([() => new Response("<html>oops</html>", { status: 502 })]);
    const client = createClient({
      baseUrl: "http://api.test",
      transport: { kind: "cookie" },
      fetchImpl: impl,
    });

    await expect(client.getHistory()).rejects.toMatchObject({
      status: 502,
      code: "bad_response",
    });
  });

  it("returns undefined for 204 responses", async () => {
    const { impl } = fakeFetch([() => new Response(null, { status: 204 })]);
    const client = createClient({
      baseUrl: "http://api.test",
      transport: { kind: "cookie" },
      fetchImpl: impl,
    });

    await expect(client.cancel("a1")).resolves.toBeUndefined();
  });
});

// The website calls this once, right after reading the token from the handoff URL.
describe("claimSession", () => {
  it("posts the token as JSON with credentials", async () => {
    const { impl, calls } = fakeFetch([() => new Response(null, { status: 204 })]);
    const client = createClient({
      baseUrl: "http://api.test",
      transport: { kind: "cookie" },
      fetchImpl: impl,
    });

    await client.claimSession("token-9");

    expect(calls[0].url).toBe("http://api.test/api/v1/session/claim");
    expect(calls[0].init.method).toBe("POST");
    expect(calls[0].init.body).toBe(JSON.stringify({ token: "token-9" }));
    expect(headerOf(calls[0], "Content-Type")).toBe("application/json");
    expect(calls[0].init.credentials).toBe("include");
  });
});

// The one place a failed response is turned into an error body, used by this client and by the
// website's own fetch helper.
describe("readApiError", () => {
  it("returns the API's error envelope as sent", async () => {
    const envelope = { error: { code: "invalid_price", message: "Bad price.", field: "price" } };
    expect(await readApiError(json(envelope, 422))).toEqual(envelope);
  });

  it.each([
    ["an HTML error page", "<html>502 Bad Gateway</html>"],
    ["plain text", "Request Entity Too Large"],
    ["an empty body", ""],
    ["JSON that is not the envelope", JSON.stringify({ detail: "nope" })],
    ["JSON null", "null"],
  ])("gives the 'bad_response' error for %s", async (_name, body) => {
    expect(await readApiError(new Response(body, { status: 502 }))).toMatchObject({
      error: { code: "bad_response", field: null },
    });
  });
});

// A server that accepts the connection and never answers must not leave the caller waiting: the
// side panel would spin until its own give-up counter, which only advances while it is waiting.
describe("request timeout", () => {
  afterEach(() => {
    vi.useRealTimers();
  });

  // Never answers, but ends when the client aborts it, like the real fetch.
  const hungFetch = ((_input: RequestInfo | URL, init?: RequestInit) =>
    new Promise<Response>((_resolve, reject) => {
      init?.signal?.addEventListener("abort", () => reject(new DOMException("x", "AbortError")));
    })) as typeof fetch;
  const hungClient = () =>
    createClient({
      baseUrl: "http://api.test",
      transport: { kind: "cookie" },
      fetchImpl: hungFetch,
    });

  it("turns no answer into 'could not be reached'", async () => {
    vi.useFakeTimers();
    const outcome = hungClient()
      .getStatus("a1")
      .catch((error: unknown) => error);
    await vi.advanceTimersByTimeAsync(REQUEST_TIMEOUT_MS);
    expect(await outcome).toMatchObject({ status: 0, code: "network_unreachable" });
  });

  it("gives the photo upload longer than an ordinary request", async () => {
    vi.useFakeTimers();
    let settled = false;
    const outcome = hungClient()
      .submit(new FormData())
      .catch((error: unknown) => error)
      .finally(() => (settled = true));
    await vi.advanceTimersByTimeAsync(REQUEST_TIMEOUT_MS);
    expect(settled).toBe(false);
    await vi.advanceTimersByTimeAsync(UPLOAD_TIMEOUT_MS - REQUEST_TIMEOUT_MS);
    expect(await outcome).toMatchObject({ status: 0 });
  });

  it("leaves no timer running once the answer arrives", async () => {
    vi.useFakeTimers();
    const { impl } = fakeFetch([() => json([])]);
    const client = createClient({
      baseUrl: "http://api.test",
      transport: { kind: "cookie" },
      fetchImpl: impl,
    });
    await client.getHistory();
    expect(vi.getTimerCount()).toBe(0);
  });
});
