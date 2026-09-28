import { describe, expect, it, vi } from "vitest";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";

import {
  detectLinkedInCompletion,
  finalizeLinkedInSubmission,
  runEasyApply,
} from "../src/adapters/linkedin.js";
import { FLAG_REASON } from "../src/lib/flags.js";

const fixtureDir = path.join(path.dirname(fileURLToPath(import.meta.url)), "fixtures");

function parseHtml(html) {
  return new DOMParser().parseFromString(html, "text/html");
}

function loadFixture(name) {
  return parseHtml(readFileSync(path.join(fixtureDir, name), "utf8"));
}

const CV_DOCUMENT = {
  kind: "cv",
  filename: "lebenslauf.pdf",
  download_url: "http://localhost:8000/api/profile/cv-file",
};

const MAPPINGS = [
  { descriptor: { label: "Email address", name: "email", type: "email" }, value: "jane@example.com" },
  { descriptor: { label: "Phone country code", name: "phone", type: "tel" }, value: "+49 30 123456" },
  {
    descriptor: { label: "How many years of experience do you have with Python?" },
    kind: "select",
    value: "More than 5 years",
  },
];

const fetchDocument = async () => ({ bytes: new Uint8Array([1, 2, 3]), contentType: "application/pdf" });
const noWait = async () => {};

// Wires the recorded fixture's step transitions the way LinkedIn's React
// handlers do: each advance reveals the next step and finally the submit.
function wireLinkedInSteps(doc) {
  const step = (n) => doc.querySelector(`[data-easy-apply-step="${n}"]`);
  const advance1 = doc.querySelector('[data-easy-apply-advance="1"]');
  const advance2 = doc.querySelector('[data-easy-apply-advance="2"]');
  const submit = doc.querySelector('[data-easy-apply-submit]');
  advance1.addEventListener("click", () => {
    step(1).hidden = true;
    step(2).hidden = false;
    advance1.hidden = true;
    advance2.hidden = false;
  });
  advance2.addEventListener("click", () => {
    step(2).hidden = true;
    step(3).hidden = false;
    advance2.hidden = true;
    submit.hidden = false;
  });
  return { submit };
}

function acceptResume(doc) {
  doc.getElementById("easy-apply-resume").addEventListener("change", () => {
    const marker = doc.createElement("span");
    marker.className = "jobs-document-upload__file-name";
    marker.textContent = "lebenslauf.pdf";
    doc.querySelector(".jobs-document-upload__container").appendChild(marker);
  });
}

describe("adapters/linkedin.js", () => {
  it("AE1: fills the Easy Apply steps and stops before the final submit", async () => {
    const doc = loadFixture("linkedin-easy-apply.html");
    const { submit } = wireLinkedInSteps(doc);
    acceptResume(doc);
    let submitted = false;
    submit.addEventListener("click", () => {
      submitted = true;
    });

    const result = await runEasyApply({
      root: doc,
      url: "https://www.linkedin.com/jobs/view/4012345678",
      mappings: MAPPINGS,
      packet: { documents: [CV_DOCUMENT] },
      fetchDocument,
      wait: noWait,
    });

    expect(result.status).toBe("awaiting_submit");
    expect(submitted).toBe(false);
    expect(doc.getElementById("easy-apply-email").value).toBe("jane@example.com");
    expect(doc.getElementById("easy-apply-phone").value).toBe("+49 30 123456");
    expect(doc.getElementById("easy-apply-experience").value).toBe("8");
    expect(result.flags).toHaveLength(0);
    expect(result.results.some((entry) => entry.label === "Resume")).toBe(true);
  });

  it("flags the resume field when the widget rejects the synthesized File", async () => {
    const doc = loadFixture("linkedin-easy-apply.html");
    wireLinkedInSteps(doc);

    const result = await runEasyApply({
      root: doc,
      url: "https://www.linkedin.com/jobs/view/4012345678",
      mappings: MAPPINGS,
      packet: { documents: [CV_DOCUMENT] },
      fetchDocument,
      wait: noWait,
    });

    const resumeFlag = result.flags.find((flag) => flag.label === "Resume");
    expect(resumeFlag).toBeTruthy();
    expect(resumeFlag.reason).toBe(FLAG_REASON.UPLOAD_FAILED);
  });

  it("AE6: with no Easy Apply control it fills nothing and reports the reason", async () => {
    const doc = parseHtml('<main><button aria-label="Sign in to apply">Sign in to apply</button></main>');
    const result = await runEasyApply({
      root: doc,
      url: "https://www.linkedin.com/jobs/view/1",
      mappings: MAPPINGS,
      packet: { documents: [CV_DOCUMENT] },
      fetchDocument,
      wait: noWait,
    });

    expect(result.status).toBe("no_easy_apply");
    expect(result.externalLink).toBeNull();
    expect(result.results).toHaveLength(0);
    expect(result.flags).toHaveLength(0);
  });

  it("signals the external link when the posting has no Easy Apply", async () => {
    const doc = parseHtml('<main><a href="https://jobs.example.com/apply/42">Apply for this job</a></main>');
    const result = await runEasyApply({
      root: doc,
      url: "https://www.linkedin.com/jobs/view/1",
      mappings: [],
      wait: noWait,
    });
    expect(result.status).toBe("no_easy_apply");
    expect(result.externalLink).toBe("https://jobs.example.com/apply/42");
  });

  it("stops on an unrecognized interstitial and does not advance", async () => {
    const doc = parseHtml(
      '<div class="jobs-easy-apply-modal" role="dialog" aria-modal="true">' +
        '<div data-easy-apply-step="1"><p>Enter the verification code we sent to your phone</p></div>' +
        '<button aria-label="Continue to next step">Continue</button></div>'
    );
    let advanced = false;
    doc.querySelector('[aria-label="Continue to next step"]').addEventListener("click", () => {
      advanced = true;
    });

    const result = await runEasyApply({ root: doc, url: "https://www.linkedin.com/jobs/view/1", mappings: [], wait: noWait });
    expect(result.status).toBe("interstitial");
    expect(advanced).toBe(false);
  });

  it("AE5: detects a confirmation state and reports the submission", async () => {
    const doc = parseHtml(
      '<div class="artdeco-modal" role="dialog"><h2>Your application was sent to Acme GmbH.</h2></div>'
    );
    const detection = detectLinkedInCompletion({
      previousUrl: "https://www.linkedin.com/jobs/view/1",
      url: "https://www.linkedin.com/jobs/view/1",
      root: doc,
      submitWasPresent: true,
    });
    expect(detection.status).toBe("complete");
    expect(detection.confident).toBe(true);

    const report = vi.fn(async (payload) => ({ ...payload, submitted_at: "2026-09-22T00:00:00Z" }));
    const result = await finalizeLinkedInSubmission({
      detection,
      context: { jobOfferId: 3, portalUrl: "https://www.linkedin.com/jobs/view/1" },
      report,
      makeReportId: () => "rid-1",
    });

    expect(result.status).toBe("reported");
    expect(report).toHaveBeenCalledWith({
      report_id: "rid-1",
      job_offer_id: 3,
      portal_url: "https://www.linkedin.com/jobs/view/1",
    });
  });

  it("asks the user instead of reporting when the completion signals disagree", async () => {
    const doc = parseHtml(
      '<div class="artdeco-modal" role="dialog"><p>Your application was sent.</p>' +
        '<button aria-label="Submit application">Submit application</button></div>'
    );
    const detection = detectLinkedInCompletion({
      previousUrl: "https://www.linkedin.com/jobs/view/1",
      url: "https://www.linkedin.com/jobs/view/1",
      root: doc,
      submitWasPresent: true,
    });
    expect(detection.status).toBe("complete");
    expect(detection.confident).toBe(false);

    const report = vi.fn();
    const result = await finalizeLinkedInSubmission({ detection, context: {}, report, confirm: async () => false });
    expect(result.status).toBe("unconfirmed");
    expect(report).not.toHaveBeenCalled();
  });

  it("surfaces the failure and does not fabricate a record when the app is unreachable at submit", async () => {
    const detection = { status: "complete", confident: true, signals: {} };
    const report = vi.fn(async () => {
      throw new Error("ECONNREFUSED");
    });
    const result = await finalizeLinkedInSubmission({
      detection,
      context: { jobOfferId: 1, portalUrl: "https://www.linkedin.com/jobs/view/1" },
      report,
    });
    expect(result.status).toBe("report_failed");
    expect(result.error).toContain("ECONNREFUSED");
  });
});
