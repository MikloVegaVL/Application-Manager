// Filling engine (R5, R6, R8, R10, U6). Writes through native property setters
// and dispatches input/change, because framework-controlled inputs (React on
// LinkedIn, Angular on other ATS pages) ignore a plain `.value` assignment
// (KTD6). Never sets consent controls; never writes LLM answers into consent
// or identity fields (KTD5).

import { accessibleLabel, findField, listControls, normalizeText } from "./detect.js";
import { isVisible } from "./controls.js";
import {
  FLAG_REASON,
  isConsentControl,
  isIdentityControl,
  makeFlag,
} from "./flags.js";

const DEFAULT_MATCH_THRESHOLD = 80;

// Text-artige Eingaben, die eine LLM-Freitext-/Screening-Antwort erhalten
// dürfen (R7). Alles andere (email/tel/file/password/... ) bleibt unberührt.
const ANSWERABLE_INPUT_TYPES = new Set(["", "text", "search"]);
const MAX_LLM_ANSWERS_PER_PAGE = 5;

function nativeSetter(el, prop) {
  let proto = Object.getPrototypeOf(el);
  while (proto) {
    const descriptor = Object.getOwnPropertyDescriptor(proto, prop);
    if (descriptor && typeof descriptor.set === "function") return descriptor.set;
    proto = Object.getPrototypeOf(proto);
  }
  return null;
}

function dispatch(el, type) {
  el.dispatchEvent(new Event(type, { bubbles: true }));
}

export function setNativeValue(el, value) {
  const setter = nativeSetter(el, "value");
  if (setter) setter.call(el, value);
  else el.value = value;
  dispatch(el, "input");
  dispatch(el, "change");
}

export function setNativeChecked(el, checked) {
  const setter = nativeSetter(el, "checked");
  if (setter) setter.call(el, checked);
  else el.checked = checked;
  dispatch(el, "input");
  dispatch(el, "change");
}

// --- Text / select / checkbox / radio ------------------------------------

export function fillTextField(el, value) {
  setNativeValue(el, value == null ? "" : String(value));
  return { matched: true, value };
}

export function optionEntries(el) {
  return Array.from(el.options || []).map((option) => {
    const label = (option.textContent || "").trim();
    return { label, value: option.value || label };
  });
}

function levenshtein(a, b) {
  const rows = a.length + 1;
  const cols = b.length + 1;
  let prev = Array.from({ length: cols }, (_, i) => i);
  for (let i = 1; i < rows; i += 1) {
    const curr = [i];
    for (let j = 1; j < cols; j += 1) {
      const cost = a[i - 1] === b[j - 1] ? 0 : 1;
      curr[j] = Math.min(prev[j] + 1, curr[j - 1] + 1, prev[j - 1] + cost);
    }
    prev = curr;
  }
  return prev[cols - 1];
}

function tokenScore(a, b) {
  const setA = new Set(a.split(" "));
  const setB = new Set(b.split(" "));
  let shared = 0;
  for (const token of setA) if (setB.has(token)) shared += 1;
  const union = new Set([...setA, ...setB]).size;
  return union === 0 ? 0 : (shared / union) * 100;
}

export function similarity(a, b) {
  const x = normalizeText(a);
  const y = normalizeText(b);
  if (!x || !y) return 0;
  if (x === y) return 100;
  if (x.includes(y) || y.includes(x)) return 92;
  const distance = levenshtein(x, y);
  const ratio = (1 - distance / Math.max(x.length, y.length)) * 100;
  return Math.max(tokenScore(x, y), ratio);
}

// Picks the index of the best matching option, or null below the threshold -
// never force-picks the next-best candidate (ported from base.py).
export function bestMatchIndex(
  profileValue,
  optionLabels,
  optionValues,
  { threshold = DEFAULT_MATCH_THRESHOLD } = {}
) {
  let bestIndex = null;
  let bestScore = -1;
  for (let i = 0; i < optionLabels.length; i += 1) {
    const score = Math.max(
      similarity(profileValue, optionLabels[i]),
      similarity(profileValue, optionValues[i])
    );
    if (score > bestScore) {
      bestScore = score;
      bestIndex = i;
    }
  }
  return bestScore >= threshold ? bestIndex : null;
}

export function fillSelect(el, profileValue, options = {}) {
  const entries = optionEntries(el);
  const index = bestMatchIndex(
    profileValue,
    entries.map((entry) => entry.label),
    entries.map((entry) => entry.value),
    options
  );
  if (index === null) {
    return { matched: false, reason: FLAG_REASON.NO_MATCHING_OPTION, value: null };
  }
  setNativeValue(el, entries[index].value);
  return { matched: true, value: entries[index].value };
}

export function fillCheckbox(el, checked) {
  setNativeChecked(el, Boolean(checked));
  return { matched: true, value: Boolean(checked) };
}

// --- File upload (R8) ------------------------------------------------------

export function guessMimeType(filename = "") {
  const ext = String(filename).toLowerCase().split(".").pop();
  switch (ext) {
    case "pdf":
      return "application/pdf";
    case "doc":
      return "application/msword";
    case "docx":
      return "application/vnd.openxmlformats-officedocument.wordprocessingml.document";
    case "png":
      return "image/png";
    case "jpg":
    case "jpeg":
      return "image/jpeg";
    case "txt":
      return "text/plain";
    default:
      return "application/octet-stream";
  }
}

export function buildFile(bytes, filename, type) {
  return new File([bytes], filename, { type: type || guessMimeType(filename) });
}

function createFileList(el, files) {
  const view = el.ownerDocument && el.ownerDocument.defaultView;
  const DataTransferCtor =
    (view && view.DataTransfer) || (typeof DataTransfer !== "undefined" ? DataTransfer : null);
  if (DataTransferCtor) {
    try {
      const transfer = new DataTransferCtor();
      for (const file of files) transfer.items.add(file);
      return transfer.files;
    } catch {
      // jsdom without DataTransfer - fall through to the array-like fallback.
    }
  }
  return files;
}

export function fillFileInput(el, file) {
  Object.defineProperty(el, "files", {
    configurable: true,
    value: createFileList(el, [file]),
  });
  dispatch(el, "input");
  dispatch(el, "change");
  return { matched: true, value: file.name };
}

// Fetches bytes in the worker (via the injected fetchDocument), builds a File
// here, and never persists or logs the bytes (KTD13).
export async function loadDocumentFile(document, fetchDocument) {
  const result = await fetchDocument(document);
  const bytes = result && result.bytes != null ? result.bytes : result;
  const type = (result && result.contentType) || guessMimeType(document.filename);
  return buildFile(bytes, document.filename, type);
}

// --- LLM answering for unanswered freetext / screening fields (R7) --------

function isAnswerCandidate(el) {
  const tag = el.tagName.toLowerCase();
  if (tag === "textarea") return true;
  if (tag !== "input") return false;
  const type = (el.getAttribute("type") || "text").toLowerCase();
  return ANSWERABLE_INPUT_TYPES.has(type);
}

// Detects text/screening fields the profile mappings did not cover, asks the
// worker (via the injected `answerQuestion`) for an LLM answer grounded in the
// profile/job/cover letter, fills it, and flags the field when the call fails
// (R7/KTD7). Never writes an LLM answer into a consent or identity field
// (KTD5).
export async function fillUnansweredFields(
  root,
  { covered = new Set(), answerQuestion, maxFields = MAX_LLM_ANSWERS_PER_PAGE } = {}
) {
  const results = [];
  const flags = [];
  if (typeof answerQuestion !== "function") return { results, flags };

  let answered = 0;
  for (const el of listControls(root)) {
    if (answered >= maxFields) break;
    if (covered.has(el) || !isVisible(el)) continue;

    const isSelect = el.tagName.toLowerCase() === "select";
    if (!isSelect && !isAnswerCandidate(el)) continue;
    if (isSelect) {
      if (el.value && el.value !== "") continue;
    } else if (String(el.value || "").trim() !== "") {
      continue;
    }

    const label = (
      accessibleLabel(el) ||
      el.getAttribute("placeholder") ||
      el.getAttribute("name") ||
      ""
    ).trim();
    if (!label) continue;

    const consent = isConsentControl(el);
    const identity = isIdentityControl(el);
    if (consent || identity) {
      flags.push(makeFlag({ label, reason: consent ? FLAG_REASON.CONSENT : FLAG_REASON.IDENTITY }));
      continue;
    }

    let response;
    try {
      response = await answerQuestion(label);
    } catch {
      flags.push(makeFlag({ label, reason: FLAG_REASON.LLM_UNAVAILABLE }));
      continue;
    }

    const answer = response && typeof response === "object" ? response.answer : response;
    if (!answer || (response && response.insufficient_information)) {
      flags.push(makeFlag({ label, reason: FLAG_REASON.LLM_UNAVAILABLE }));
      continue;
    }

    if (isSelect) {
      const outcome = fillSelect(el, answer);
      if (!outcome.matched) flags.push(makeFlag({ label, reason: FLAG_REASON.NO_MATCHING_OPTION }));
      else {
        results.push({ matched: true, label, value: outcome.value, llm: true });
        answered += 1;
      }
    } else {
      const outcome = fillTextField(el, answer);
      results.push({ matched: true, label, value: outcome.value, llm: true });
      answered += 1;
    }
  }

  return { results, flags };
}

// --- Orchestrator ----------------------------------------------------------

// Fills a list of mappings against a root, returning the filled results plus
// the flags the review panel renders (R10). `fetchDocument` is injected so
// document bytes never leave the worker path.
export async function fillFields(root, mappings = [], options = {}) {
  const results = [];
  const flags = [];
  const covered = new Set();

  const flag = (label, reason) => {
    flags.push(makeFlag({ label, reason }));
    results.push({ matched: false, label, reason });
  };

  for (const mapping of mappings) {
    const descriptor = mapping.descriptor || {};
    const label =
      descriptor.label || descriptor.name || descriptor.placeholder || mapping.label || "?";
    const found = findField(root, descriptor);
    if (!found) {
      flag(label, FLAG_REASON.FIELD_NOT_FOUND);
      continue;
    }

    const el = found.element;
    covered.add(el);
    if (mapping.consent || isConsentControl(el)) {
      flag(label, FLAG_REASON.CONSENT);
      continue;
    }
    if (mapping.identity || (mapping.llm && isIdentityControl(el))) {
      flag(label, FLAG_REASON.IDENTITY);
      continue;
    }

    try {
      if (mapping.kind === "select") {
        const outcome = fillSelect(el, mapping.value, options);
        if (!outcome.matched) flag(label, FLAG_REASON.NO_MATCHING_OPTION);
        else results.push({ matched: true, label, value: outcome.value });
      } else if (mapping.kind === "checkbox" || mapping.kind === "radio") {
        const outcome = fillCheckbox(el, mapping.value);
        results.push({ matched: true, label, value: outcome.value });
      } else if (mapping.kind === "file") {
        if (typeof options.fetchDocument !== "function") {
          flag(label, FLAG_REASON.FILE_NOT_FOUND);
          continue;
        }
        const file = await loadDocumentFile(mapping.document, options.fetchDocument);
        const outcome = fillFileInput(el, file);
        results.push({ matched: true, label, value: outcome.value });
      } else {
        const outcome = fillTextField(el, mapping.value);
        results.push({ matched: true, label, value: outcome.value });
      }
    } catch {
      flag(label, FLAG_REASON.UPLOAD_FAILED);
    }
  }

  // R7: verbleibende, vom Profil nicht beantwortete Freitext-/Screening-
  // Felder über den LLM-Endpunkt beantworten (nur wenn injiziert).
  if (typeof options.answerQuestion === "function") {
    const llm = await fillUnansweredFields(root, {
      covered,
      answerQuestion: options.answerQuestion,
    });
    results.push(...llm.results);
    flags.push(...llm.flags);
  }

  return { results, flags };
}
