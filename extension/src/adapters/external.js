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
  findSubmitControl,
  hasConfirmationText,
  isVisible,
} from "../lib/controls.js";
import { detectCompletion, finalizeSubmission, newReportId } from "../lib/submission.js";

export { detectCompletion, finalizeSubmission, newReportId };

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

// Fills the form page by page; flags mappings that match no control anywhere in
// the form (R10) and stops at the submit control on whatever page it appears.
export async function driveExternalForm({
  root = document,
  url = "",
  mappings = [],
  fetchDocument = null,
  answerQuestion = null,
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
    const filled = await fill(stepRoot, relevant, { fetchDocument, answerQuestion });
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

// The worker's ROUTE_EXTERNAL path (U8 step 1) handles the LinkedIn-to-employer
// navigation and origin registration, so this adapter only ever runs on the
// employer form itself. The former `followExternalLink` LinkedIn branch was
// unreachable and duplicated that path, so it was removed.
export async function runExternalAdapter(options = {}) {
  return driveExternalForm(options);
}

export function detectExternalCompletion({
  previousUrl = "",
  url = "",
  root = document,
  submitWasPresent = false,
} = {}) {
  const submitGone = Boolean(submitWasPresent) && !findSubmitControl(root);
  const urlChanged = Boolean(url) && url !== previousUrl;
  const confirmationText = hasConfirmationText(root);
  return detectCompletion({ urlChanged, confirmationText, submitGone });
}
