import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

function pick(store, keys) {
  const list = Array.isArray(keys) ? keys : [keys];
  const result = {};
  for (const key of list) if (key in store) result[key] = store[key];
  return result;
}

function makeChrome() {
  const local = {};
  return {
    local,
    api: {
      storage: {
        local: {
          get: async (keys) => pick(local, keys),
          set: async (obj) => Object.assign(local, obj),
        },
      },
    },
  };
}

describe("options.js KTD9 acknowledgement", () => {
  let chromeMock;

  beforeEach(() => {
    document.body.innerHTML = `
      <form id="options-form">
        <input id="api-base-url" />
        <input id="secret" />
        <input id="tos-ack" type="checkbox" />
        <span id="status"></span>
      </form>`;
    chromeMock = makeChrome();
    vi.stubGlobal("chrome", chromeMock.api);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    document.body.innerHTML = "";
  });

  it("refuses to save the secret until the acknowledgement is checked", async () => {
    const { save, TOS_STORAGE_KEY } = await import("../src/options.js");
    document.getElementById("secret").value = "abc";

    await save({ preventDefault() {} });

    expect(chromeMock.local["portalFillSecret"]).toBeUndefined();
    expect(chromeMock.local[TOS_STORAGE_KEY]).toBeUndefined();
    expect(document.getElementById("status").textContent).toMatch(/acknowledge/i);
  });

  it("saves the secret and records the acknowledgement once checked", async () => {
    const { save, TOS_STORAGE_KEY } = await import("../src/options.js");
    document.getElementById("secret").value = "abc";
    document.getElementById("tos-ack").checked = true;

    await save({ preventDefault() {} });

    expect(chromeMock.local["portalFillSecret"]).toBe("abc");
    expect(chromeMock.local[TOS_STORAGE_KEY]).toBe(true);
  });
});
