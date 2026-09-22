// External-form fallback adapter (U8; R4/R9/R10/R11; KD6, KTD4, KTD6, KTD12).
// Routed to by the worker's dispatcher when the LinkedIn adapter reports no
// Easy Apply. Follows the employer link, then fills with the same U6 engine
// and never submits.

import { fillFields as defaultFillFields } from "../lib/fill.js";
import { findField } from "../lib/detect.js";
import { FLAG_REASON, makeFlag } from "../lib/flags.js";
import {
  detectInterstitial,
  findAdvanceControl,
  findExternalApplyLink,
  findSubmitControl,
  hasConfirmationText,
  isLinkedInUrl,
  isVisible,
} from "../lib/controls.js";
import { detectCompletion, finalizeSubmission, newReportId } from "../lib/submission.js";

export { detectCompletion, finalizeSubmission, newReportId, findExternalApplyLink, isLinkedInUrl };

export const finalizeExternalSubmission = finalizeSubmission;

async function defaultWait() {
  await Promise.resolve();
}

export function findExternalForm(root = document) {
  return root.querySelector("form") || null;
}

export function findVisibleFormStep(root = document) {
  const form = findExternalForm(root);
  if (!form) return root;
  const pages = Array.from(form.querySelectorAll("[data-page], .form-page, fieldset"));
  return pages.find(isVisible) || form;
}

// On the LinkedIn page: resolve the employer link, request the destination
// origin (worker registers the content script), then hand off navigation.
export async function followExternalLink({
  root = document,
  requestOrigin = null,
  probeLink = null,
  navigate = null,
} = {}) {
  const href = findExternalApplyLink(root);
  if (!href) return { status: "no_apply_path", reason: "no_external_link" };

  if (typeof probeLink === "function") {
    let alive = false;
    try {
      alive = Boolean(await probeLink(href));
    } catch {
      alive = false;
    }
    if (!alive) return { status: "no_apply_path", reason: "dead_link", href };
  }

  let origin;
  try {
    origin = new URL(href).origin;
  } catch {
    return { status: "no_apply_path", reason: "invalid_link", href };
  }

  if (typeof requestOrigin === "function") {
    const routing = await requestOrigin(origin);
    if (routing && routing.registered === false) {
      return { status: "no_apply_path", reason: routing.error || "permission_denied", href };
    }
  }

  if (typeof navigate === "function") navigate(href);
  return { status: "following_link", href, origin };
}

// Fills the form page by page; flags mappings that match no control anywhere in
// the form (R10) and stops at the submit control on whatever page it appears.
export async function driveExternalForm({
  root = document,
  url = "",
  mappings = [],
  fetchDocument = null,
  fill = defaultFillFields,
  wait = defaultWait,
  maxPages = 10,
} = {}) {
  const flags = [];
  const results = [];

  for (const mapping of mappings) {
    if (!findField(root, mapping.descriptor || {})) {
      flags.push(
        makeFlag({
          label: mapping.descriptor?.label || mapping.label || "?",
          reason: FLAG_REASON.UNMAPPED,
        })
      );
    }
  }

  for (let page = 0; page < maxPages; page += 1) {
    const stepRoot = findVisibleFormStep(root);
    const relevant = mappings.filter((mapping) => findField(stepRoot, mapping.descriptor || {}));
    const filled = await fill(stepRoot, relevant, { fetchDocument });
    results.push(...filled.results);
    flags.push(...filled.flags);

    if (detectInterstitial(stepRoot).detected) {
      return { status: "interstitial", page: page + 1, flags, results, url };
    }

    const submit = findSubmitControl(root);
    if (submit) {
      return { status: "awaiting_submit", submit, flags, results, url, pages: page + 1 };
    }

    const advance = findAdvanceControl(root);
    if (!advance) {
      return { status: "stuck", page: page + 1, flags, results, url };
    }
    advance.click();
    await wait();
  }

  return { status: "page_limit", flags, results, url };
}

export async function runExternalAdapter(options = {}) {
  const { root = document, url = typeof location !== "undefined" ? location.href : "" } = options;
  if (isLinkedInUrl(url)) {
    return followExternalLink(options);
  }
  return driveExternalForm(options);
}

export function detectExternalCompletion({
  previousUrl = "",
  url = "",
  root = document,
  submitWasPresent = true,
} = {}) {
  const submitGone = Boolean(submitWasPresent) && !findSubmitControl(root);
  const urlChanged = Boolean(url) && url !== previousUrl;
  const confirmationText = hasConfirmationText(root);
  return detectCompletion({ urlChanged, confirmationText, submitGone });
}
