import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { fillFields, setNativeValue } from "../src/lib/fill.js";
import { FLAG_REASON, renderFlags } from "../src/lib/flags.js";

function setup(html) {
  document.body.innerHTML = html;
  return document;
}

describe("fill.js", () => {
  beforeEach(() => {
    document.body.innerHTML = "";
    vi.restoreAllMocks();
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("fills a labeled text input so a framework listener observes the change", async () => {
    setup('<label for="full-name">Full name</label><input id="full-name" />');
    const input = document.getElementById("full-name");

    // A framework-style instance-level value override that a plain assignment
    // would hit; the native setter must bypass it.
    const events = [];
    input.addEventListener("input", () => events.push(input.value));
    input.addEventListener("change", () => events.push(`change:${input.value}`));

    const { results, flags } = await fillFields(document, [
      { descriptor: { label: "Full name" }, value: "Jane Doe" },
    ]);

    expect(input.value).toBe("Jane Doe");
    expect(events).toContain("Jane Doe");
    expect(results[0]).toMatchObject({ matched: true, value: "Jane Doe" });
    expect(flags).toHaveLength(0);
  });

  it("writes through the native prototype setter, not the instance property", () => {
    setup('<input id="x" />');
    const input = document.getElementById("x");
    const spy = vi.spyOn(HTMLInputElement.prototype, "value", "set");
    setNativeValue(input, "native");
    expect(spy).toHaveBeenCalledWith("native");
  });

  it("sets a <select> to the matched option and a checkbox to its state", async () => {
    setup(`
      <label for="country">Country</label>
      <select id="country">
        <option value="">--</option>
        <option value="DE">Deutschland</option>
        <option value="AT">Österreich</option>
      </select>
      <label for="remote">Remote</label>
      <input id="remote" type="checkbox" />
    `);
    let changed = false;
    document.getElementById("remote").addEventListener("change", () => {
      changed = true;
    });

    const { flags } = await fillFields(document, [
      { descriptor: { label: "Country" }, kind: "select", value: "Deutschland" },
      { descriptor: { label: "Remote" }, kind: "checkbox", value: true },
    ]);

    expect(document.getElementById("country").value).toBe("DE");
    expect(document.getElementById("remote").checked).toBe(true);
    expect(changed).toBe(true);
    expect(flags).toHaveLength(0);
  });

  it("flags a select value with no confident option match instead of guessing", async () => {
    setup(`
      <label for="country">Country</label>
      <select id="country">
        <option value="">--</option>
        <option value="DE">Deutschland</option>
        <option value="AT">Österreich</option>
      </select>
    `);
    const { flags } = await fillFields(document, [
      { descriptor: { label: "Country" }, kind: "select", value: "Narnia" },
    ]);
    expect(flags[0].reason).toBe(FLAG_REASON.NO_MATCHING_OPTION);
    expect(document.getElementById("country").value).toBe("");
  });

  it("flags a consent checkbox and never sets it", async () => {
    setup(`
      <label for="terms">I agree to the Terms of Service and Privacy Policy</label>
      <input id="terms" type="checkbox" />
    `);
    const { flags } = await fillFields(document, [
      {
        descriptor: { label: "I agree to the Terms of Service and Privacy Policy" },
        kind: "checkbox",
        value: true,
      },
    ]);
    expect(flags[0].reason).toBe(FLAG_REASON.CONSENT);
    expect(document.getElementById("terms").checked).toBe(false);
  });

  it("never writes an LLM answer into an identity/eligibility field", async () => {
    setup(`
      <label for="work">Are you legally authorized to work in Germany?</label>
      <input id="work" type="text" />
    `);
    const { flags } = await fillFields(document, [
      {
        descriptor: { label: "Are you legally authorized to work in Germany?" },
        value: "Yes",
        llm: true,
      },
    ]);
    expect(flags[0].reason).toBe(FLAG_REASON.IDENTITY);
    expect(document.getElementById("work").value).toBe("");
  });

  it("R7: answers an uncovered freetext field through the injected LLM call", async () => {
    setup(`
      <label for="why">Why do you want to work here?</label>
      <input id="why" type="text" />
    `);
    const answerQuestion = vi.fn(async () => ({
      answer: "Because your mission matches my experience.",
      insufficient_information: false,
    }));

    const { results, flags } = await fillFields(document, [], { answerQuestion });

    expect(document.getElementById("why").value).toBe(
      "Because your mission matches my experience."
    );
    expect(answerQuestion).toHaveBeenCalledWith("Why do you want to work here?");
    expect(results.some((entry) => entry.llm === true)).toBe(true);
    expect(flags).toHaveLength(0);
  });

  it("R7: flags the field when the LLM call fails instead of leaving it silently empty", async () => {
    setup('<label for="why">Why us?</label><input id="why" type="text" />');
    const answerQuestion = vi.fn(async () => {
      throw new Error("llm_unavailable");
    });

    const { flags } = await fillFields(document, [], { answerQuestion });

    expect(flags[0].reason).toBe(FLAG_REASON.LLM_UNAVAILABLE);
    expect(document.getElementById("why").value).toBe("");
  });

  it("R7: never asks the LLM about an uncovered identity/eligibility field", async () => {
    setup(`
      <label for="permit">Do you have a work permit for Germany?</label>
      <input id="permit" type="text" />
    `);
    const answerQuestion = vi.fn();

    const { flags } = await fillFields(document, [], { answerQuestion });

    expect(answerQuestion).not.toHaveBeenCalled();
    expect(flags[0].reason).toBe(FLAG_REASON.IDENTITY);
    expect(document.getElementById("permit").value).toBe("");
  });

  it("flags a field with no confident match", async () => {
    setup('<input id="email" name="email" />');
    const { flags } = await fillFields(document, [
      { descriptor: { label: "Favorite dinosaur" }, value: "T-Rex" },
    ]);
    expect(flags[0].reason).toBe(FLAG_REASON.FIELD_NOT_FOUND);
    expect(flags[0].label).toBe("Favorite dinosaur");
  });

  it("fills a file input with a File built from fetched bytes", async () => {
    setup('<label for="resume">Resume</label><input id="resume" type="file" />');
    const fetchDocument = vi.fn(async () => ({
      bytes: new Uint8Array([1, 2, 3, 4]),
      contentType: "application/pdf",
    }));

    const { flags } = await fillFields(
      document,
      [
        {
          descriptor: { label: "Resume", type: "file" },
          kind: "file",
          document: { filename: "lebenslauf.pdf" },
        },
      ],
      { fetchDocument }
    );

    const input = document.getElementById("resume");
    expect(flags).toHaveLength(0);
    expect(input.files).toHaveLength(1);
    expect(input.files[0]).toBeInstanceOf(File);
    expect(input.files[0].name).toBe("lebenslauf.pdf");
    expect(input.files[0].type).toBe("application/pdf");
  });

  it("flags the upload field when the document fetch fails", async () => {
    setup('<label for="resume">Resume</label><input id="resume" type="file" />');
    const fetchDocument = vi.fn(async () => {
      throw new Error("network down");
    });

    const { flags } = await fillFields(
      document,
      [
        {
          descriptor: { label: "Resume", type: "file" },
          kind: "file",
          document: { filename: "lebenslauf.pdf" },
        },
      ],
      { fetchDocument }
    );

    expect(flags[0].reason).toBe(FLAG_REASON.UPLOAD_FAILED);
    expect(document.getElementById("resume").files).toHaveLength(0);
  });

  it("never writes document bytes to storage and never logs them", async () => {
    setup('<label for="resume">Resume</label><input id="resume" type="file" />');
    const localSet = vi.fn();
    const sessionSet = vi.fn();
    const setItem = vi.spyOn(Storage.prototype, "setItem");
    const log = vi.spyOn(console, "log").mockImplementation(() => {});
    vi.stubGlobal("chrome", {
      storage: {
        local: { set: localSet },
        session: { set: sessionSet },
      },
    });

    const bytes = new Uint8Array([9, 9, 9]);
    await fillFields(
      document,
      [
        {
          descriptor: { label: "Resume", type: "file" },
          kind: "file",
          document: { filename: "cv.pdf" },
        },
      ],
      { fetchDocument: async () => ({ bytes, contentType: "application/pdf" }) }
    );

    expect(localSet).not.toHaveBeenCalled();
    expect(sessionSet).not.toHaveBeenCalled();
    expect(setItem).not.toHaveBeenCalled();
    expect(log).not.toHaveBeenCalled();
  });

  it("inserts a page-derived label into the review panel as text, not markup", () => {
    const list = document.createElement("ul");
    const malicious = '<img src=x onerror="window.__xss=1">';
    renderFlags(list, [{ label: malicious, reason: FLAG_REASON.UNMAPPED }]);
    expect(list.querySelector("img")).toBeNull();
    expect(list.textContent).toContain(malicious);
    expect(window.__xss).toBeUndefined();
  });
});
