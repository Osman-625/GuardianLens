// Pins the website's fetch helper: an API error becomes a typed error with its field, an answer
// that is not the API's error envelope (a proxy's HTML page) is still a typed error and not a
// thrown parse error, 204 gives nothing, and a request that never reached the server is not
// disguised as an API answer.
import { afterEach, describe, expect, it, vi } from "vitest";
import { GuardianLensApiError, apiFetch } from "../lib/api";

afterEach(() => {
  vi.unstubAllGlobals();
});

/** Makes the next fetch answer with the given Response. */
function answerWith(response: Response) {
  const fetchMock = vi.fn(async () => response);
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

describe("apiFetch", () => {
  it("returns the JSON body of a success", async () => {
    answerWith(Response.json({ ok: true }));
    expect(await apiFetch("/x")).toEqual({ ok: true });
  });

  it("returns undefined for 204", async () => {
    answerWith(new Response(null, { status: 204 }));
    expect(await apiFetch("/x", { method: "POST" })).toBeUndefined();
  });

  it("turns the API's error envelope into a typed error with its field", async () => {
    answerWith(
      Response.json(
        {
          error: {
            code: "invalid_rating",
            message: "Enter a rating from 0 to 5.",
            field: "rating",
          },
        },
        { status: 422 },
      ),
    );
    await expect(apiFetch("/x")).rejects.toMatchObject({
      name: "GuardianLensApiError",
      status: 422,
      code: "invalid_rating",
      field: "rating",
      message: "Enter a rating from 0 to 5.",
    });
  });

  it("gives a typed 'bad_response' error for a proxy's HTML error page", async () => {
    answerWith(new Response("<html>502 Bad Gateway</html>", { status: 502 }));
    const error = await apiFetch("/x").catch((caught: unknown) => caught);
    expect(error).toBeInstanceOf(GuardianLensApiError);
    expect(error).toMatchObject({ status: 502, code: "bad_response" });
  });

  it("lets a request that never reached the server fail as itself", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("Failed to fetch")));
    const error = await apiFetch("/x").catch((caught: unknown) => caught);
    expect(error).toBeInstanceOf(TypeError);
    expect(error).not.toBeInstanceOf(GuardianLensApiError);
  });

  it("sends the cookie, and leaves a form upload's own content type alone", async () => {
    const fetchMock = answerWith(Response.json({}));
    await apiFetch("/x", { method: "POST", body: new FormData() });
    const init = (fetchMock.mock.calls[0] as unknown as [string, RequestInit])[1];
    expect(init.credentials).toBe("include");
    expect(new Headers(init.headers).has("Content-Type")).toBe(false);
  });

  // Without it a server that never answers leaves the page on "Loading" forever.
  it("gives every request a time limit", async () => {
    const fetchMock = answerWith(Response.json({}));
    await apiFetch("/x");
    const init = (fetchMock.mock.calls[0] as unknown as [string, RequestInit])[1];
    expect(init.signal).toBeInstanceOf(AbortSignal);
  });
});
