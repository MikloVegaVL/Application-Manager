// Unmapped/uncertain field flags for the review panel (R10, U6).
// Legal-consent controls are flagged, never set (KTD5). LLM answers are never
// written into consent or identity fields.

import { accessibleLabel } from "./detect.js";

export const FLAG_REASON = {
  FIELD_NOT_FOUND: "field_not_found",
  UNMAPPED: "unmapped",
  NO_MATCHING_OPTION: "no_matching_option",
  CONSENT: "consent",
  IDENTITY: "identity",
  FILE_NOT_FOUND: "file_not_found",
  UPLOAD_FAILED: "upload_failed",
  LLM_UNAVAILABLE: "llm_unavailable",
};

export const FLAG_MESSAGE = {
  [FLAG_REASON.FIELD_NOT_FOUND]: "No matching field found on the page.",
  [FLAG_REASON.UNMAPPED]: "No confident match - please fill this in yourself.",
  [FLAG_REASON.NO_MATCHING_OPTION]: "No matching option - please choose yourself.",
  [FLAG_REASON.CONSENT]: "Consent control - must be checked by you.",
  [FLAG_REASON.IDENTITY]: "Identity/eligibility field - answer it yourself.",
  [FLAG_REASON.FILE_NOT_FOUND]: "Document not available - please upload it yourself.",
  [FLAG_REASON.UPLOAD_FAILED]: "Upload failed - please attach the file yourself.",
  [FLAG_REASON.LLM_UNAVAILABLE]: "No generated answer available - please answer yourself.",
};

export function makeFlag({ label, reason, detail = null }) {
  return {
    label: label || "?",
    reason,
    detail,
    message: FLAG_MESSAGE[reason] || "Needs your attention.",
  };
}

const CONSENT_PATTERNS = [
  /terms/i,
  /privacy/i,
  /\bconsent\b/i,
  /agree/i,
  /accept/i,
  /einverstand/i,
  /datenschutz/i,
  /nutzungsbedingung/i,
  /akzeptier/i,
  /ich stimme/i,
  /zustimm/i,
  /\bagb\b/i,
];

const IDENTITY_PATTERNS = [
  /staatsangehorigkeit|citizenship|nationality/i,
  /vorstraf|criminal|conviction/i,
  /visa|sponsorship/i,
  /arbeitserlaubnis|work permit|right to work|authorized to work|work authoriz/i,
  /geburtsdatum|date of birth/i,
  /sozialversicherung|social security/i,
  /passport|ausweis/i,
];

function controlText(el) {
  return [
    accessibleLabel(el),
    el.getAttribute && el.getAttribute("name"),
    el.getAttribute && el.getAttribute("id"),
  ]
    .filter(Boolean)
    .join(" ");
}

export function isConsentControl(el) {
  if (!el) return false;
  return CONSENT_PATTERNS.some((pattern) => pattern.test(controlText(el)));
}

export function isIdentityControl(el) {
  if (!el) return false;
  return IDENTITY_PATTERNS.some((pattern) => pattern.test(controlText(el)));
}

// Renders flags with DOM text APIs, never innerHTML (page-derived labels are
// untrusted text). Returns the container.
export function renderFlags(container, flags = []) {
  const doc = container.ownerDocument;
  container.textContent = "";
  for (const flag of flags) {
    const item = doc.createElement("li");
    item.className = "am-flag";
    item.dataset.reason = flag.reason;
    item.textContent = `${flag.label} - ${flag.message}`;
    container.appendChild(item);
  }
  return container;
}
