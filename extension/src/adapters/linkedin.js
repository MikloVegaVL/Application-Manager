// LinkedIn Easy Apply adapter (U7; R3/R8/R9/R10/R11; KD4, KTD4, KTD9, KTD12).
// Thin: composes the U6 engine (detect.js/fill.js) and the shared control and
// submission helpers. Advances intermediate steps but never clicks the final
// submit control, and stops on an unrecognized interstitial for the user.

import { fillFields as defaultFillFields, fillFileInput, loadDocumentFile } from "../lib/fill.js";
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
  labelOf,
} from "../lib/controls.js";
import { detectCompletion, finalizeSubmission, newReportId } from "../lib/submission.js";

export { detectCompletion, finalizeSubmission, newReportId, findExternalApplyLink, isLinkedInUrl };

export const finalizeLinkedInSubmission = finalizeSubmission;

const EASY_APPLY_PATTERN = /easy apply|einfach bewerben/i;

async function defaultWait() {
  await Promise.resolve();
}

export function findEasyApplyButton(root = document) {
  return (
    Array.from(root.querySelectorAll("button, a")).find(
      (el) => isVisible(el) && EASY_APPLY_PATTERN.test(labelOf(el))
    ) || null
  );
}

export function findEasyApplyModal(root = document) {
  return (
    root.querySelector("[data-test-easy-apply-modal]") ||
    root.querySelector(".jobs-easy-apply-modal") ||
    root.querySelector("div[role='dialog'][aria-modal='true']") ||
    null
  );
}

export function findEasyApplyStep(modal) {
  if (!modal) return null;
  const steps = Array.from(modal.querySelectorAll("[data-easy-apply-step]"));
  return steps.find(isVisible) || modal;
}

export function findResumeInput(root = document) {
  const inputs = Array.from(root.querySelectorAll("input[type='file']"));
  return (
    inputs.find((el) =>
      /resume|cv|lebenslauf/i.test(`${el.getAttribute("name") || ""} ${el.id} ${labelOf(el)}`)
    ) ||
    inputs[0] ||
    null
  );
}

export function isResumeUploadComplete(root = document) {
  if (!root || !root.querySelector) return false;
  return Boolean(
    root.querySelector(
      ".jobs-document-upload__file-name, .artdeco-file-upload__preview, [data-test-resume-uploaded='true']"
    )
  );
}

function cvDocument(packet) {
  return ((packet && packet.documents) || []).find((document) => document.kind === "cv") || null;
}

// Drives LinkedIn's own upload control and observes its upload-complete state;
// when the widget does not accept the synthesized File the field is flagged
// rather than reported as filled (R8, R10).
export async function driveResumeUpload({
  stepRoot,
  container = stepRoot,
  packet = null,
  fetchDocument = null,
  wait = defaultWait,
} = {}) {
  const input = findResumeInput(stepRoot);
  if (!input) return null;

  const descriptor = cvDocument(packet);
  if (!descriptor || typeof fetchDocument !== "function") {
    return { flag: makeFlag({ label: "Resume", reason: FLAG_REASON.FILE_NOT_FOUND }) };
  }

  let file;
  try {
    file = await loadDocumentFile(descriptor, fetchDocument);
  } catch {
    return { flag: makeFlag({ label: "Resume", reason: FLAG_REASON.UPLOAD_FAILED }) };
  }

  try {
    fillFileInput(input, file);
  } catch {
    return { flag: makeFlag({ label: "Resume", reason: FLAG_REASON.UPLOAD_FAILED }) };
  }

  await wait();
  const accepted =
    isResumeUploadComplete(stepRoot) || (container !== stepRoot && isResumeUploadComplete(container));
  if (!accepted) {
    return {
      flag: makeFlag({
        label: "Resume",
        reason: FLAG_REASON.UPLOAD_FAILED,
        detail: "LinkedIn's upload widget did not accept the synthesized file",
      }),
    };
  }
  return { filled: { matched: true, label: "Resume", value: file.name } };
}

function presentMappings(stepRoot, mappings) {
  return mappings.filter((mapping) => findField(stepRoot, mapping.descriptor || {}));
}

// Fills the modal step by step and stops before the final submit (KTD12). On
// an interstitial it returns without advancing so the user can clear it and
// the same step can be resumed (KTD9).
export async function runEasyApply({
  root = document,
  url = typeof location !== "undefined" ? location.href : "",
  mappings = [],
  packet = null,
  fetchDocument = null,
  fill = defaultFillFields,
  wait = defaultWait,
  maxSteps = 12,
} = {}) {
  const modal = findEasyApplyModal(root);
  const easyApply = findEasyApplyButton(root);

  if (!modal && !easyApply) {
    return { status: "no_easy_apply", externalLink: findExternalApplyLink(root), flags: [], results: [] };
  }
  if (!modal) {
    return { status: "modal_closed", flags: [], results: [], message: "Open Easy Apply to continue." };
  }

  const fieldMappings = mappings.filter((mapping) => mapping.kind !== "file");
  const flags = [];
  const results = [];
  let step = 0;

  while (step < maxSteps) {
    const stepRoot = findEasyApplyStep(modal) || modal;

    const filled = await fill(stepRoot, presentMappings(stepRoot, fieldMappings), { fetchDocument });
    results.push(...filled.results);
    flags.push(...filled.flags);

    const resume = await driveResumeUpload({ stepRoot, container: modal, packet, fetchDocument, wait });
    if (resume && resume.flag) flags.push(resume.flag);
    else if (resume && resume.filled) results.push(resume.filled);

    if (detectInterstitial(stepRoot).detected || detectInterstitial(modal).detected) {
      return {
        status: "interstitial",
        step: step + 1,
        flags,
        results,
        message: "LinkedIn requires verification. Complete it, then resume the fill.",
      };
    }

    const submit = findSubmitControl(modal);
    if (submit) {
      return { status: "awaiting_submit", submit, flags, results, url };
    }

    const advance = findAdvanceControl(modal);
    if (!advance) {
      return { status: "stuck", step: step + 1, flags, results };
    }
    advance.click();
    await wait();
    step += 1;
  }

  return { status: "step_limit", flags, results };
}

export function detectLinkedInCompletion({
  previousUrl = "",
  url = "",
  root = document,
  submitWasPresent = true,
} = {}) {
  const submitGone = Boolean(submitWasPresent) && !findSubmitControl(root);
  const urlChanged = Boolean(url) && url !== previousUrl && !/\/jobs\/view\//.test(url);
  const confirmationText = hasConfirmationText(root);
  return detectCompletion({ urlChanged, confirmationText, submitGone });
}
