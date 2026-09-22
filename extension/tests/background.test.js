import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";

function pick(store, keys) {
  if (keys == null) return { ...store };
  const list = Array.isArray(keys) ? keys : [keys];
  const result = {};
  for (const key of list) if (key in store) result[key] = store[key];
  return result;
}

function makeChrome() {
  const local = {};
  const session = {};
  return {
    local,
    session,
    api: {
      storage: {
        local: {
          get: async (keys) => pick(local, keys),
          set: async (obj) => Object.assign(local, obj),
        },
        session: {
          get: async (keys) => pick(session, keys),
          set: async (obj) => Object.assign(session, obj),
          remove: async (keys) => {
            for (const key of Array.isArray(keys) ? keys : [keys]) delete session[key];
          },
        },
      },
      runtime: { onMessage: { addListener: () => {} } },
      tabs: { onRemoved: { addListener: () => {} } },
      permissions: {
        contains: vi.fn(async () => false),
        request: vi.fn(async () => true),
      },
      scripting: {
        registerContentScripts: vi.fn(async () => {}),
        unregisterContentScripts: vi.fn(async () => {}),
      },
    },
  };
}

function jsonResponse(body, status = 200) {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
    arrayBuffer: async () => new ArrayBuffer(0),
    headers: { get: () => "application/json" },
  };
}

let chromeMock;
let background;

beforeAll(async () => {
  chromeMock = makeChrome();
  vi.stubGlobal("chrome", chromeMock.api);
  background = await import("../src/background.js");
});

beforeEach(async () => {
  Object.keys(chromeMock.local).forEach((key) => delete chromeMock.local[key]);
  Object.keys(chromeMock.session).forEach((key) => delete chromeMock.session[key]);
  await chromeMock.api.storage.local.set({
    [background.SECRET_STORAGE_KEY]: "s3cret",
    [background.TOS_STORAGE_KEY]: true,
  });
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
  vi.stubGlobal("chrome", chromeMock.api);
});

describe("background.js", () => {
  it("requests context for a page URL and forwards the packet", async () => {
    const packet = { application_id: 7, job_offer_id: 3, profile: { full_name: "Jane" } };
    const fetchMock = vi.fn(async () => jsonResponse(packet));
    vi.stubGlobal("fetch", fetchMock);

    const result = await background.handleMessage(
      { type: background.MESSAGE.PAGE_READY, url: "https://www.linkedin.com/jobs/view/123", tabId: 5 },
      {}
    );

    expect(result.packet).toEqual(packet);
    const [calledUrl, calledInit] = fetchMock.mock.calls[0];
    expect(calledUrl).toContain("/portal-fill/context?url=");
    expect(calledInit.headers["X-Portal-Fill-Secret"]).toBe("s3cret");
  });

  it("reuses the tab-scoped cached packet on reload instead of re-requesting", async () => {
    const packet = { application_id: 7 };
    const fetchMock = vi.fn(async () => jsonResponse(packet));
    vi.stubGlobal("fetch", fetchMock);

    await background.handleMessage(
      { type: background.MESSAGE.PAGE_READY, url: "https://www.linkedin.com/jobs/view/123", tabId: 9 },
      {}
    );
    const second = await background.handleMessage(
      { type: background.MESSAGE.PAGE_READY, url: "https://www.linkedin.com/jobs/view/123", tabId: 9 },
      {}
    );

    expect(second.cached).toBe(true);
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("fills nothing (packet null) when the app has no matching fill request", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => jsonResponse({ detail: "nope" }, 404)));
    const result = await background.handleMessage(
      { type: background.MESSAGE.PAGE_READY, url: "https://example.com/apply", tabId: 1 },
      {}
    );
    expect(result.packet).toBeNull();
    expect(result.error).toBe("no_fill_request");
  });

  it("reports cleanly when the app is unreachable", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => {
        throw new Error("ECONNREFUSED");
      })
    );
    const result = await background.handleMessage(
      { type: background.MESSAGE.PAGE_READY, url: "https://www.linkedin.com/jobs/view/1", tabId: 2 },
      {}
    );
    expect(result.packet).toBeNull();
    expect(result.error).toBe("app_unreachable");
  });

  it("refuses to call the app when no secret is configured", async () => {
    delete chromeMock.local[background.SECRET_STORAGE_KEY];
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);

    const result = await background.handleMessage(
      { type: background.MESSAGE.PAGE_READY, url: "https://www.linkedin.com/jobs/view/1", tabId: 3 },
      {}
    );

    expect(result.error).toBe("no_secret");
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("KTD9: refuses to fill until the LinkedIn acknowledgement is stored", async () => {
    delete chromeMock.local[background.TOS_STORAGE_KEY];
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);

    const result = await background.handleMessage(
      { type: background.MESSAGE.PAGE_READY, url: "https://www.linkedin.com/jobs/view/1", tabId: 4 },
      {}
    );

    expect(result.packet).toBeNull();
    expect(result.error).toBe("tos_not_acknowledged");
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("R7: returns the answer and insufficiency flag from the app", async () => {
    const fetchMock = vi.fn(async () =>
      jsonResponse({ answer: "Weil ich Sie kenne.", insufficient_information: false })
    );
    vi.stubGlobal("fetch", fetchMock);

    const result = await background.handleMessage(
      {
        type: background.MESSAGE.REQUEST_ANSWER,
        applicationId: 7,
        question: "Warum möchten Sie bei uns arbeiten?",
      },
      {}
    );

    expect(result.answer).toBe("Weil ich Sie kenne.");
    expect(result.insufficient_information).toBe(false);
    const [calledUrl] = fetchMock.mock.calls[0];
    expect(calledUrl).toContain("/portal-fill/answer");
  });

  it("registers the content script for exactly the granted employer origin", async () => {
    const result = await background.handleMessage(
      { type: background.MESSAGE.REGISTER_ORIGIN, origin: "https://jobs.example.com" },
      {}
    );
    expect(result.registered).toBe(true);
    expect(chromeMock.api.permissions.request).toHaveBeenCalledWith({
      origins: ["https://jobs.example.com/*"],
    });
    expect(chromeMock.api.scripting.registerContentScripts).toHaveBeenCalledWith([
      expect.objectContaining({ matches: ["https://jobs.example.com/*"], js: ["content.js"] }),
    ]);
  });

  it("routes to the external adapter by registering the link's origin", async () => {
    const result = await background.handleMessage(
      { type: background.MESSAGE.ROUTE_EXTERNAL, url: "https://jobs.example.com/apply/42" },
      {}
    );
    expect(result.routed).toBe(true);
    expect(chromeMock.api.permissions.request).toHaveBeenCalledWith({
      origins: ["https://jobs.example.com/*"],
    });
  });

  it("reports no apply path when the LinkedIn adapter sends no external link", async () => {
    const result = await background.handleMessage(
      { type: background.MESSAGE.ROUTE_EXTERNAL, url: null },
      {}
    );
    expect(result.routed).toBe(false);
    expect(result.error).toBe("no_apply_path");
  });

  it("serves the cached packet after a cross-origin navigation instead of re-requesting", async () => {
    const packet = { application_id: 7 };
    const fetchMock = vi.fn(async () => jsonResponse(packet));
    vi.stubGlobal("fetch", fetchMock);

    await background.handleMessage(
      { type: background.MESSAGE.PAGE_READY, url: "https://www.linkedin.com/jobs/view/123", tabId: 21 },
      {}
    );
    const afterNavigation = await background.handleMessage(
      { type: background.MESSAGE.PAGE_READY, url: "https://jobs.example.com/apply/42", tabId: 21 },
      {}
    );

    expect(afterNavigation.cached).toBe(true);
    expect(afterNavigation.packet).toEqual(packet);
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });
});
