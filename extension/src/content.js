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
  REQUEST_ANSWER: "REQUEST_ANSWER",
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

function hostOf(url) {
  try {
    return new URL(url).host;
  } catch {
    return url;
  }
}

// P1: `chrome.permissions.request` requires a user gesture. The content
// script renders a clickable "Continue on <host>" control whose click sends
// the ROUTE_EXTERNAL message - only then does the worker call
// `permissions.request`/`registerContentScripts`, so the gesture is real.
export function renderContinueNotice(applyUrl, onContinue) {
  const existing = document.getElementById("am-notice");
  if (existing) existing.remove();
  const notice = document.createElement("div");
  notice.id = "am-notice";
  const text = document.createElement("span");
  text.textContent = `No Easy Apply here. Continue on ${hostOf(applyUrl)} to fill the employer's form?`;
  const button = document.createElement("button");
  button.type = "button";
  button.textContent = `Continue on ${hostOf(applyUrl)}`;
  button.addEventListener("click", () => {
    button.disabled = true;
    onContinue();
  });
  notice.appendChild(text);
  notice.appendChild(button);
  document.body.appendChild(notice);
  return notice;
}

// Presents the external fallback but does NOT request the origin until the
// user clicks (P1). Resolves once the routing attempt has run.
export function presentExternalFallback({
  externalLink,
  send,
  assign = (url) => window.location.assign(url),
  notice = renderNotice,
  continueNotice = renderContinueNotice,
}) {
  if (!externalLink) {
    notice("No Easy Apply and no reachable external application link on this posting.");
    return Promise.resolve({ routed: false, reason: "no_apply_path" });
  }
  return new Promise((resolve) => {
    continueNotice(externalLink, async () => {
      const routing = await send({ type: MESSAGE.ROUTE_EXTERNAL, url: externalLink });
      if (routing && routing.routed) {
        assign(externalLink);
        resolve({ routed: true });
        return;
      }
      notice("Could not get permission to fill that site. Fill it manually or retry.");
      resolve({ routed: false, reason: routing && routing.error });
    });
  });
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

// LinkedIn: fill Easy Apply, or present the user-gesture "Continue on <host>"
// control that routes to the external adapter when there is none (U7 step 7,
// AE6, P1).
async function runLinkedInFlow(packet, mappings, answerQuestion) {
  const result = await runEasyApply({
    root: document,
    url: window.location.href,
    mappings,
    packet,
    fetchDocument,
    answerQuestion,
  });

  if (result.status === "no_easy_apply") {
    await presentExternalFallback({ externalLink: result.externalLink, send });
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
async function runExternalFlow(packet, mappings, answerQuestion) {
  const result = await runExternalAdapter({
    root: document,
    url: window.location.href,
    mappings,
    packet,
    fetchDocument,
    answerQuestion,
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
  if (!response || !response.packet) {
    if (response && response.error === "tos_not_acknowledged") {
      renderNotice(
        "Open the Application Manager Autofill extension options and accept the LinkedIn Terms-of-Service notice before filling."
      );
    }
    return;
  }
  const packet = response.packet;
  const mappings = buildProfileMappings(packet);

  // R7: unanswered freetext/screening fields are answered through the worker
  // (which holds the secret and calls the app's LLM endpoint).
  const answerQuestion = (question) =>
    send({
      type: MESSAGE.REQUEST_ANSWER,
      applicationId: packet.application_id,
      question,
    }).then((reply) => {
      if (!reply || reply.error) {
        throw new Error((reply && reply.error) || "llm_unavailable");
      }
      return { answer: reply.answer, insufficient_information: reply.insufficient_information };
    });

  if (isLinkedInUrl(window.location.href)) await runLinkedInFlow(packet, mappings, answerQuestion);
  else await runExternalFlow(packet, mappings, answerQuestion);
}

if (typeof chrome !== "undefined" && chrome.runtime && chrome.runtime.sendMessage) {
  init();
}
