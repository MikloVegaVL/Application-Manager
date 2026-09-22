// Site-agnostic field detection (R5, U6). Accessible-first order, ported from
// the removed backend/app/services/portal_agents/base.py:
//   aria -> <label> -> placeholder -> autocomplete -> name -> type
// Never throws: an unmatched descriptor returns matched=false so the caller
// flags the field (R10) instead of guessing.

export const DETECTION_SOURCE = {
  ARIA: "aria",
  LABEL: "label",
  PLACEHOLDER: "placeholder",
  AUTOCOMPLETE: "autocomplete",
  NAME: "name",
  TYPE: "type",
};

export function normalizeText(text) {
  if (text == null) return "";
  return String(text)
    .normalize("NFKD")
    .replace(/[\u0300-\u036f]/g, "")
    .toLowerCase()
    .replace(/\s+/g, " ")
    .trim();
}

export function listControls(root) {
  if (!root || typeof root.querySelectorAll !== "function") return [];
  return Array.from(root.querySelectorAll("input, select, textarea")).filter(
    (el) => !el.disabled
  );
}

function labelsFromAria(el, doc) {
  const ids = (el.getAttribute("aria-labelledby") || "").split(/\s+/).filter(Boolean);
  if (ids.length) {
    const text = ids
      .map((id) => {
        const ref = doc.getElementById(id);
        return ref ? ref.textContent : "";
      })
      .join(" ");
    if (text.trim()) return text;
  }
  const ariaLabel = el.getAttribute("aria-label");
  return ariaLabel || "";
}

function labelText(el) {
  const doc = el.ownerDocument;
  const id = el.getAttribute("id");
  if (id) {
    const explicit = Array.from(doc.querySelectorAll("label[for]")).find(
      (label) => label.getAttribute("for") === id
    );
    if (explicit && explicit.textContent.trim()) return explicit.textContent;
  }
  const wrapping = el.closest("label");
  if (wrapping && wrapping.textContent.trim()) return wrapping.textContent;
  return "";
}

export function accessibleLabel(el) {
  return labelsFromAria(el, el.ownerDocument).trim() || labelText(el).trim();
}

export function controlNames(el) {
  return {
    [DETECTION_SOURCE.ARIA]: labelsFromAria(el, el.ownerDocument).trim(),
    [DETECTION_SOURCE.LABEL]: labelText(el).trim(),
    [DETECTION_SOURCE.PLACEHOLDER]: el.getAttribute("placeholder") || "",
    [DETECTION_SOURCE.AUTOCOMPLETE]: el.getAttribute("autocomplete") || "",
    [DETECTION_SOURCE.NAME]: el.getAttribute("name") || "",
    [DETECTION_SOURCE.TYPE]: el.getAttribute("type") || el.tagName.toLowerCase(),
  };
}

// Accessible-first tier order. `type` is last and only matches when a
// descriptor explicitly asks for it (e.g. a lone file input).
const TIER_ORDER = [
  DETECTION_SOURCE.ARIA,
  DETECTION_SOURCE.LABEL,
  DETECTION_SOURCE.PLACEHOLDER,
  DETECTION_SOURCE.AUTOCOMPLETE,
  DETECTION_SOURCE.NAME,
  DETECTION_SOURCE.TYPE,
];

function descriptorValue(descriptor, source) {
  switch (source) {
    case DETECTION_SOURCE.ARIA:
    case DETECTION_SOURCE.LABEL:
      return descriptor.label || "";
    case DETECTION_SOURCE.PLACEHOLDER:
      return descriptor.placeholder || "";
    case DETECTION_SOURCE.AUTOCOMPLETE:
      return descriptor.autocomplete || "";
    case DETECTION_SOURCE.NAME:
      return descriptor.name || "";
    case DETECTION_SOURCE.TYPE:
      return descriptor.type || "";
    default:
      return "";
  }
}

// Returns { element, source } or null. Accessible-first, never throws.
export function findField(root, descriptor = {}) {
  const controls = listControls(root);
  for (const source of TIER_ORDER) {
    const wanted = normalizeText(descriptorValue(descriptor, source));
    if (!wanted) continue;
    for (const el of controls) {
      const names = controlNames(el);
      if (normalizeText(names[source]) === wanted) {
        return { element: el, source };
      }
    }
  }
  return null;
}

// Returns a per-field descriptor with a confidence result (U6 step 1).
export function detectField(root, descriptor = {}) {
  const found = findField(root, descriptor);
  if (!found) {
    return { matched: false, element: null, source: null, confidence: 0 };
  }
  const confidence = found.source === DETECTION_SOURCE.ARIA || found.source === DETECTION_SOURCE.LABEL ? 1 : 0.7;
  return { matched: true, element: found.element, source: found.source, confidence };
}

export function detectFields(root, descriptors = []) {
  return descriptors.map((descriptor) => ({ descriptor, ...detectField(root, descriptor) }));
}
