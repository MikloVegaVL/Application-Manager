import { describe, expect, it, vi } from "vitest";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";

import {
  detectExternalCompletion,
  finalizeExternalSubmission,
  runExternalAdapter,
} from "../src/adapters/external.js";
import { FLAG_REASON } from "../src/lib/flags.js";

const fixtureDir = path.join(path.dirname(fileURLToPath(import.meta.url)), "fixtures");

function parseHtml(html) {
  return new DOMParser().parseFromString(html, "text/html");
}

function loadFixture(name) {
  return parseHtml(readFileSync(path.join(fixtureDir, name), "utf8"));
}

const noWait = async () => {};

function wireWizard(doc) {
  const page1 = doc.querySelector('[data-page="1"]');
  const page2 = doc.querySelector('[data-page="2"]');
  doc.getElementById("next-btn").addEventListener("click", () => {
    page1.hidden = true;
    page2.hidden = false;
  });
  return { submit: doc.getElementById("submit-btn") };
}

const WIZARD_MAPPINGS = [
  { descriptor: { label: "First name", name: "first_name", autocomplete: "given-name" }, value: "Jane" },
  { descriptor: { label: "Last name", name: "last_name", autocomplete: "family-name" }, value: "Doe" },
  { descriptor: { label: "Email", name: "email", autocomplete: "email", type: "email" }, value: "jane@example.com" },
  { descriptor: { label: "Phone", name: "phone", autocomplete: "tel", type: "tel" }, value: "+49 30 1" },
  { descriptor: { label: "LinkedIn profile", name: "linkedin" }, value: "https://linkedin.com/in/jane" },
  { descriptor: { label: "Cover letter", name: "cover_letter" }, value: "Dear hiring team" },
];

describe("adapters/external.js", () => {
  it("AE2: fills an external form across a wizard and stops before submit", async () => {
    const doc = loadFixture("external-form.html");
    const { submit } = wireWizard(doc);
    let submitted = false;
    submit.addEventListener("click", () => {
      submitted = true;
    });

    const result = await runExternalAdapter({
      root: doc,
      url: "https://jobs.example.com/apply/42",
      mappings: WIZARD_MAPPINGS,
      wait: noWait,
    });

    expect(result.status).toBe("awaiting_submit");
    expect(result.pages).toBe(2);
    expect(submitted).toBe(false);
    expect(doc.getElementById("first_name").value).toBe("Jane");
    expect(doc.getElementById("last_name").value).toBe("Doe");
    expect(doc.getElementById("linkedin").value).toBe("https://linkedin.com/in/jane");
    expect(result.flags).toHaveLength(0);
  });

  it("AE4: flags an unmapped field visibly instead of guessing", async () => {
    const doc = loadFixture("external-form.html");
    const mappings = [
      { descriptor: { label: "First name" }, value: "Jane" },
      { descriptor: { label: "Favorite dinosaur" }, value: "T-Rex" },
    ];

    const result = await runExternalAdapter({
      root: doc,
      url: "https://jobs.example.com/apply/42",
      mappings,
      wait: noWait,
      maxPages: 1,
    });

    const flag = result.flags.find((entry) => entry.label === "Favorite dinosaur");
    expect(flag).toBeTruthy();
    expect(flag.reason).toBe(FLAG_REASON.UNMAPPED);
  });

  it("detects completion per KTD4 when the submit sits on a later URL", () => {
    const doc = parseHtml("<div><h2>Thank you for applying!</h2></div>");
    const detection = detectExternalCompletion({
      previousUrl: "https://jobs.example.com/apply/42",
      url: "https://jobs.example.com/apply/42/thanks",
      root: doc,
      submitWasPresent: true,
    });
    expect(detection.status).toBe("complete");
    expect(detection.confident).toBe(true);
  });

  it("KTD4: a URL change plus a vanished submit is NOT confident without confirmation text", () => {
    // Bloßes Verlassen der Seite darf nicht als Bewerbung gelten (P1/R11).
    const doc = parseHtml("<main><h1>Some other page</h1></main>");
    const detection = detectExternalCompletion({
      previousUrl: "https://jobs.example.com/apply/42",
      url: "https://jobs.example.com/other",
      root: doc,
      submitWasPresent: true,
    });
    expect(detection.status).toBe("complete");
    expect(detection.confident).toBe(false);
  });

  it("surfaces an app failure at submit and does not fabricate a record", async () => {
    const detection = { status: "complete", confident: true, signals: {} };
    const report = vi.fn(async () => {
      throw new Error("ECONNREFUSED");
    });
    const result = await finalizeExternalSubmission({
      detection,
      context: { jobOfferId: 5, portalUrl: "https://jobs.example.com/apply/42" },
      report,
    });
    expect(result.status).toBe("report_failed");
    expect(result.error).toContain("ECONNREFUSED");
  });
});
