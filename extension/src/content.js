// Page entry point (U5). Messages the worker only and acts only when a fill
// packet is available (R14/AE3). Never fetches the app directly (KTD1).
// Dispatches to the U7 LinkedIn adapter on LinkedIn, otherwise to the U8
// external-form fallback.

import { renderFlags } from "./lib/flags.js";
import { buildProfileMappings } from "./lib/mappings.js";
import {
  detectLinkedInCompletion,
  finalizeLinkedInSubmission,
  isLinkedInUrl,
  runEasyApply,
} from "./adapters/linkedin.js";
import {
  detectExternalCompletion,
  finalizeExternalSubmission,
  runExternalAdapter,
} from "./adapters/external.js";

export const MESSAGE = {
  PAGE_READY: "PAGE_READY",
  FETCH_DOCUMENT: "FETCH_DOCUMENT",
  REPORT_SUBMISSION: "REPORT_SUBMISSION",
  ROUTE_EXTERNAL: "ROUTE_EXTERNAL",
};

export { buildProfileMappings };

function send(message) {
  return new Promise((resolve) => chrome.runtime.sendMessage(message, resolve));
}

function fetchDocument(documentDescriptor) {
  return send({ type: MESSAGE.FETCH_DOCUMENT, document: documentDescriptor }).then((response) => {
    if (!response || response.error) {
      throw new Error((response && response.error) || "document_fetch_failed");
    }
    return { bytes: response.blob, contentType: response.blob.type };
  });
}

function reportSubmission(payload) {
  return send({ type: MESSAGE.REPORT_SUBMISSION, payload }).then((response) => {
    if (!response || response.error) {
      throw new Error((response && response.error) || "report_failed");
    }
    return response.submission;
  });
}

export function renderNotice(message) {
  const existing = document.getElementById("am-notice");
  if (existing) existing.remove();
  const notice = document.createElement("div");
  notice.id = "am-notice";
  notice.textContent = message;
  document.body.appendChild(notice);
  return notice;
}

export function renderReviewPanel(flags) {
  if (!flags || flags.length === 0) return null;
  const panel = document.createElement("div");
  panel.id = "am-review-panel";
  const title = document.createElement("strong");
  title.textContent = "Autofill: fields that need your attention";
  const list = document.createElement("ul");
  renderFlags(list, flags);
  panel.appendChild(title);
  panel.appendChild(list);
  document.body.appendChild(panel);
  return panel;
}

// LinkedIn: fill Easy Apply, or signal the worker's dispatcher to route to the
// external adapter when there is none (U7 step 7, AE6).
async function runLinkedInFlow(packet, mappings) {
  const result = await runEasyApply({
    root: document,
    url: window.location.href,
    mappings,
    packet,
    fetchDocument,
  });

  if (result.status === "no_easy_apply") {
    const routing = await send({ type: MESSAGE.ROUTE_EXTERNAL, url: result.externalLink || null });
    if (routing && routing.routed && result.externalLink) {
      window.location.assign(result.externalLink);
      return;
    }
    renderNotice("No Easy Apply and no reachable external application link on this posting.");
    return;
  }
  if (result.status === "interstitial") {
    renderReviewPanel(result.flags);
    renderNotice(result.message);
    return;
  }
  renderReviewPanel(result.flags);
  if (result.status === "awaiting_submit") watchForSubmission(packet, "linkedin");
}

// External fallback: fill the employer form and stop before submit (U8).
async function runExternalFlow(packet, mappings) {
  const result = await runExternalAdapter({
    root: document,
    url: window.location.href,
    mappings,
    packet,
    fetchDocument,
  });
  if (result.status === "no_apply_path") {
    renderNotice("No reachable application form was found on this posting.");
    return;
  }
  renderReviewPanel(result.flags);
  if (result.status === "awaiting_submit") watchForSubmission(packet, "external");
}

// Watches for the user's submit and reports only on a confident or
// user-confirmed detection (KTD4, R11). Never submits itself (R9).
function watchForSubmission(packet, kind) {
  const context = { jobOfferId: packet.job_offer_id, portalUrl: window.location.href };
  const previousUrl = window.location.href;

  const detect = () =>
    kind === "linkedin"
      ? detectLinkedInCompletion({ previousUrl, url: window.location.href, root: document, submitWasPresent: true })
      : detectExternalCompletion({ previousUrl, url: window.location.href, root: document, submitWasPresent: true });

  const finalize = (detection) => {
    const options = {
      detection,
      context,
      report: reportSubmission,
      confirm: () => Promise.resolve(window.confirm("Did this application submit? Confirm to record it.")),
    };
    return kind === "linkedin" ? finalizeLinkedInSubmission(options) : finalizeExternalSubmission(options);
  };

  const check = async () => {
    const detection = detect();
    if (detection.status === "pending") return false;
    const outcome = await finalize(detection);
    if (outcome.status === "reported") renderNotice("Application recorded as submitted.");
    else if (outcome.status === "report_failed") renderNotice("Could not reach the app to record the submission.");
    return true;
  };

  if (typeof MutationObserver === "function") {
    const observer = new MutationObserver(() => {
      check().then((done) => {
        if (done) observer.disconnect();
      });
    });
    observer.observe(document.body, { subtree: true, childList: true, attributes: true });
  }
}

async function init() {
  const response = await send({ type: MESSAGE.PAGE_READY, url: window.location.href });
  if (!response || !response.packet) return;
  const packet = response.packet;
  const mappings = buildProfileMappings(packet);
  if (isLinkedInUrl(window.location.href)) await runLinkedInFlow(packet, mappings);
  else await runExternalFlow(packet, mappings);
}

if (typeof chrome !== "undefined" && chrome.runtime && chrome.runtime.sendMessage) {
  init();
}
