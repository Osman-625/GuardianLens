// Pins the whole side panel working together, with a fake API client, fake photo downloads, and a
// fake capture store, so no browser or server is needed. These are the journeys a buyer takes:
//   - capture arrives -> Review -> Check listing -> result, with ONE submission even when the
//     button is pressed twice;
//   - the server rejects the description (unsupported language): the buyer stays in Review with
//     every typed value kept and the error next to the field;
//   - the service is unreachable: a calm failure screen, and "Try again" returns with the draft intact;
//   - "See full explanation" opens the website with the session handoff in the URL fragment;
//   - a draft saved earlier comes back when the panel is reopened.
import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { GuardianLensApiError, type AssessmentStatusResponse } from "@guardianlens/shared";
import { describe, expect, it, vi } from "vitest";
import { PanelApp } from "@/entrypoints/sidepanel/PanelApp";
import type { CaptureJob } from "@/lib/capture/runner";
import type { ControllerDeps } from "@/lib/panel/controller";
import { draftFromListing } from "@/lib/panel/draft";
import type { PanelStorage, SavedPanel } from "@/lib/panel/storage";
import { sampleListing, sampleResult } from "../helpers/samples";

// The website origin the fake dependencies open links on.
const SITE = "http://localhost:3000";

/** A finished listing capture, as the service worker would store it. */
const listingJob = (id = 10, listing = sampleListing()): CaptureJob => ({
  id,
  tabId: 1,
  status: "done",
  result: { kind: "listing", listing },
});

/** A fake capture store: `emit` pushes a job to the panel as if the service worker wrote it. */
function fakeStorage(saved: SavedPanel | null = null) {
  const listeners: Array<(job: CaptureJob | null) => void> = [];
  const storage: PanelStorage = {
    readCaptureState: async () => null,
    watchCaptureState: (listener) => {
      listeners.push(listener);
      return () => {
        listeners.splice(listeners.indexOf(listener), 1);
      };
    },
    readSaved: async () => saved,
    writeSaved: vi.fn(async () => undefined),
  };
  return {
    storage,
    emit: (job: CaptureJob) => act(async () => listeners.forEach((listener) => listener(job))),
  };
}

/** Fake dependencies: a client that succeeds by default, instant waits, and tiny photo downloads. */
function fakeDeps(storage: PanelStorage) {
  const client = {
    ensureSession: vi.fn(async () => undefined),
    submit: vi.fn(async (_form: FormData) => ({ assessment_id: "a1" })),
    getStatus: vi.fn(async (): Promise<AssessmentStatusResponse> => ({
      status: "complete",
      stage: null,
      message: null,
    })),
    getResult: vi.fn(async () => sampleResult()),
    cancel: vi.fn(async () => undefined),
    sendFeedback: vi.fn(async () => undefined),
    getHistory: vi.fn(async () => []),
    claimSession: vi.fn(async () => undefined),
    getToken: vi.fn(async () => "tok-123"),
  };
  const openUrl = vi.fn();
  const captureActiveTab = vi.fn(async () => undefined);
  const deps: ControllerDeps = {
    client,
    photoDeps: {
      fetchBlob: async () => new Blob([new Uint8Array(1000)], { type: "image/jpeg" }),
      encodeJpeg: async () => new Blob([new Uint8Array(1000)], { type: "image/jpeg" }),
    },
    storage,
    openUrl,
    captureActiveTab,
    siteBaseUrl: SITE,
    wait: async () => undefined,
  };
  return { deps, client, openUrl, captureActiveTab };
}

// PanelApp wired to fake storage and a fake API: the whole panel from idle to result.
describe("PanelApp", () => {
  it("starts with the idle message", async () => {
    const { storage } = fakeStorage();
    render(<PanelApp deps={fakeDeps(storage).deps} />);
    expect(
      await screen.findByText(
        "Open a Mudah.my or Carousell listing, then click the GuardianLens icon.",
      ),
    ).toBeInTheDocument();
  });

  it("shows a headed, announced message while the page is being read", async () => {
    const { storage, emit } = fakeStorage();
    render(<PanelApp deps={fakeDeps(storage).deps} />);
    await emit({ id: 5, tabId: 1, status: "capturing" });
    expect(
      await screen.findByRole("heading", {
        level: 1,
        name: /Reading this page/,
      }),
    ).toBeInTheDocument();
  });

  it("'Open seller page' opens the seller link the listing page offered", async () => {
    const { storage, emit } = fakeStorage();
    const { deps, openUrl } = fakeDeps(storage);
    render(<PanelApp deps={deps} />);
    await emit(
      listingJob(10, sampleListing({ sellerUrl: "https://www.carousell.com.my/u/someone/" })),
    );
    await userEvent.click(await screen.findByRole("button", { name: "Open seller page" }));
    expect(openUrl).toHaveBeenCalledExactlyOnceWith("https://www.carousell.com.my/u/someone/");
  });

  it("'Capture the seller's page' reads the page open in the browser now", async () => {
    const { storage, emit } = fakeStorage();
    const { deps, captureActiveTab } = fakeDeps(storage);
    render(<PanelApp deps={deps} />);
    await emit(listingJob(10, sampleListing()));
    await userEvent.click(await screen.findByRole("button", { name: "Capture the seller's page" }));
    expect(captureActiveTab).toHaveBeenCalledTimes(1);
  });

  it("shows the 'could not be read' message when 'Capture the seller's page' fails", async () => {
    const { storage, emit } = fakeStorage();
    const { deps, captureActiveTab } = fakeDeps(storage);
    captureActiveTab.mockRejectedValueOnce(new Error("no gesture"));
    render(<PanelApp deps={deps} />);
    await emit(listingJob(10, sampleListing()));
    await userEvent.click(await screen.findByRole("button", { name: "Capture the seller's page" }));
    expect(await screen.findByText(/The page could not be read/)).toBeInTheDocument();
  });

  it("never opens a stored link that is not a seller page of a supported marketplace", async () => {
    const { storage, emit } = fakeStorage();
    const { deps, openUrl } = fakeDeps(storage);
    render(<PanelApp deps={deps} />);
    await emit(listingJob(10, sampleListing({ sellerUrl: "https://example.com/u/someone/" })));
    await userEvent.click(await screen.findByRole("button", { name: "Open seller page" }));
    expect(openUrl).not.toHaveBeenCalled();
  });

  it("goes from capture to result and submits only once when the button is pressed twice", async () => {
    const { storage, emit } = fakeStorage();
    const { deps, client } = fakeDeps(storage);
    render(<PanelApp deps={deps} />);
    await emit(listingJob());
    await screen.findByText("Check the captured details");

    await userEvent.dblClick(screen.getByRole("button", { name: "Check listing" }));

    const region = await screen.findByRole("region", {
      name: "Score 58 out of 100, moderate risk",
    });
    expect(within(region).getByText(/Decision support only/)).toBeInTheDocument();
    expect(client.submit).toHaveBeenCalledTimes(1);
    const form = client.submit.mock.calls[0]?.[0] as FormData;
    expect(form.get("source")).toBe("extension");
  });

  it("keeps every typed value and shows the server's error next to the description", async () => {
    const { storage, emit } = fakeStorage();
    const { deps, client } = fakeDeps(storage);
    client.submit.mockRejectedValueOnce(
      new GuardianLensApiError(422, {
        error: {
          code: "unsupported_language",
          message:
            "Chinese-dominant listings are outside this prototype's supported language scope.",
          field: "description",
        },
      }),
    );
    render(<PanelApp deps={deps} />);
    await emit(listingJob());
    await screen.findByText("Check the captured details");
    await userEvent.clear(screen.getByLabelText("Title"));
    await userEvent.type(screen.getByLabelText("Title"), "My edited title");

    await userEvent.click(screen.getByRole("button", { name: "Check listing" }));

    expect(
      await screen.findByText(/outside this prototype's supported language scope/),
    ).toBeInTheDocument();
    expect(screen.getByLabelText("Title")).toHaveValue("My edited title");
    expect(screen.getByLabelText("Description")).toHaveValue("Original unit. COD available.");
  });

  it("shows a calm failure when the service is unreachable, and Try again keeps the draft", async () => {
    const { storage, emit } = fakeStorage();
    const { deps, client } = fakeDeps(storage);
    client.submit.mockRejectedValueOnce(
      new GuardianLensApiError(0, {
        error: { code: "network_unreachable", message: "x", field: null },
      }),
    );
    render(<PanelApp deps={deps} />);
    await emit(listingJob());
    await screen.findByText("Check the captured details");
    await userEvent.click(screen.getByRole("button", { name: "Check listing" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("not reachable");
    await userEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(await screen.findByText("Check the captured details")).toBeInTheDocument();
    expect(screen.getByLabelText("Title")).toHaveValue("Used laptop in good condition");
  });

  it("opens the full explanation on the website with the session in the URL fragment", async () => {
    const { storage, emit } = fakeStorage();
    const { deps, openUrl } = fakeDeps(storage);
    render(<PanelApp deps={deps} />);
    await emit(listingJob());
    await userEvent.click(await screen.findByRole("button", { name: "Check listing" }));
    await userEvent.click(await screen.findByRole("button", { name: "See full explanation" }));
    // The URL is built after the client returns the session token, so wait for the call.
    await waitFor(() =>
      expect(openUrl).toHaveBeenLastCalledWith(`${SITE}/assess/a1/explanation#st=tok-123`),
    );
  });

  it("jumps to a signal's section when its card is opened", async () => {
    const { storage, emit } = fakeStorage();
    const { deps, openUrl } = fakeDeps(storage);
    render(<PanelApp deps={deps} />);
    await emit(listingJob());
    await userEvent.click(await screen.findByRole("button", { name: "Check listing" }));
    await userEvent.click(await screen.findByRole("link", { name: /Photos/ }));
    await waitFor(() =>
      expect(openUrl).toHaveBeenLastCalledWith(
        `${SITE}/assess/a1/explanation#st=tok-123&signal=visual`,
      ),
    );
  });

  it("restores a saved draft when the panel is reopened", async () => {
    const draft = draftFromListing(
      sampleListing({ title: { status: "captured", value: "Saved earlier" } }),
    );
    const { storage } = fakeStorage({ draft, lastDoneJobId: 10 });
    render(<PanelApp deps={fakeDeps(storage).deps} />);
    expect(await screen.findByText("Check the captured details")).toBeInTheDocument();
    expect(screen.getByLabelText("Title")).toHaveValue("Saved earlier");
  });

  // The website reads History from the visitor's own session cookie, so a bare /history link would
  // show an empty list even though the buyer has checks in the panel. The link carries the same
  // session handoff as "See full explanation". The manual form needs no session, so it does not.
  it("opens the session history with the session handoff in the URL fragment", async () => {
    const { storage } = fakeStorage();
    const { deps, openUrl } = fakeDeps(storage);
    render(<PanelApp deps={deps} />);
    await userEvent.click(await screen.findByRole("button", { name: "This session" }));
    await waitFor(() => expect(openUrl).toHaveBeenLastCalledWith(`${SITE}/history#st=tok-123`));
  });

  it("opens the website form without any session token", async () => {
    const { storage } = fakeStorage();
    const { deps, openUrl } = fakeDeps(storage);
    render(<PanelApp deps={deps} />);
    await userEvent.click(await screen.findByRole("button", { name: "Use the website form" }));
    await waitFor(() => expect(openUrl).toHaveBeenLastCalledWith(`${SITE}/assess`));
  });

  // Two races between a running check and a new action. Each holds the first status call open, as
  // a slow server would, so the first check is still running when the buyer acts again.
  it("lets the buyer cancel and press Check listing again at once (the second check starts)", async () => {
    const { storage, emit } = fakeStorage();
    const { deps, client } = fakeDeps(storage);
    // Answers the held-open status call, once the test decides the slow server replies.
    let releaseFirst: (status: AssessmentStatusResponse) => void = () => undefined;
    client.getStatus.mockImplementationOnce(
      () =>
        new Promise((resolve) => {
          releaseFirst = resolve;
        }),
    );
    render(<PanelApp deps={deps} />);
    await emit(listingJob());
    await userEvent.click(await screen.findByRole("button", { name: "Check listing" }));
    await userEvent.click(await screen.findByRole("button", { name: "Cancel" }));
    await userEvent.click(await screen.findByRole("button", { name: "Check listing" }));

    // The second check finishes even though the first is still waiting on the server.
    expect(
      await screen.findByRole("region", { name: /^Score \d+ out of 100/ }),
    ).toBeInTheDocument();
    expect(client.submit).toHaveBeenCalledTimes(2);
    // The first check answering late changes nothing.
    await act(async () => releaseFirst({ status: "processing", stage: "visual", message: null }));
    expect(screen.getByRole("region", { name: /^Score \d+ out of 100/ })).toBeInTheDocument();
  });

  it("a capture that arrives during a check replaces it instead of mixing two listings", async () => {
    const { storage, emit } = fakeStorage();
    const { deps, client } = fakeDeps(storage);
    // Answers the held-open status call, once the test decides the slow server replies.
    let releaseFirst: (status: AssessmentStatusResponse) => void = () => undefined;
    client.getStatus.mockImplementationOnce(
      () =>
        new Promise((resolve) => {
          releaseFirst = resolve;
        }),
    );
    render(<PanelApp deps={deps} />);
    await emit(listingJob());
    await userEvent.click(await screen.findByRole("button", { name: "Check listing" }));
    await screen.findByRole("button", { name: "Cancel" });

    // The buyer clicks the icon on a different listing while the first is being checked.
    const second = sampleListing({
      title: { status: "captured", value: "Second listing" },
    });
    await emit(listingJob(11, second));
    expect(await screen.findByLabelText("Title")).toHaveValue("Second listing");

    // The first check completes late. Its result must not replace the second listing's Review.
    await act(async () => releaseFirst({ status: "complete", stage: null, message: null }));
    expect(screen.getByLabelText("Title")).toHaveValue("Second listing");
    expect(screen.queryByRole("region", { name: /^Score \d+ out of 100/ })).not.toBeInTheDocument();
  });
});
