// Shared control detection for the U7/U8 adapters (KTD4, KTD12). Field
// detection and filling stay in U6 (detect.js/fill.js); this module only
// locates the controls and confirmation/interstitial states the adapters
// reason about, so both adapters stay thin.

export const SUBMIT_PATTERN =
  /submit application|submit your application|send application|bewerbung (jetzt )?absenden|bewerbung abschicken|^submit$|^absenden$/i;
export const ADVANCE_PATTERN =
  /^(continue|next|review|continue to next step|review your application|weiter|nächste[rs]?|überprüfen)\b/i;
export const CONFIRMATION_PATTERN =
  /application (was )?(sent|submitted)|your application (has been|was) (sent|submitted)|thank you for applying|bewerbung (wurde )?(erfolgreich )?(gesendet|übermittelt|abgeschickt)|vielen dank für (deine|ihre) bewerbung/i;
export const INTERSTITIAL_PATTERN =
  /verification code|verify your|we sent (you )?(a )?(code|email|text|sms)|enter the (code|verification)|security code|bestätigungscode|sicherheitscode|challenge/i;

const INTERSTITIAL_SELECTOR =
  "iframe[src*='recaptcha'], iframe[src*='challenge'], [data-test-verification], .jobs-easy-apply-modal__verification";

export function isLinkedInUrl(url) {
  try {
    const host = new URL(url).hostname.toLowerCase();
    return host === "linkedin.com" || host.endsWith(".linkedin.com");
  } catch {
    return false;
  }
}

// Hidden-only visibility check (no getComputedStyle) so it works on jsdom
// fixtures parsed with DOMParser as well as live pages.
export function isVisible(el) {
  let node = el;
  while (node && node.nodeType === 1) {
    if (node.hasAttribute("hidden")) return false;
    if (node.getAttribute("aria-hidden") === "true") return false;
    const style = node.style;
    if (style && (style.display === "none" || style.visibility === "hidden")) return false;
    node = node.parentElement;
  }
  return Boolean(el);
}

export function labelOf(el) {
  return [el.getAttribute && el.getAttribute("aria-label"), el.textContent]
    .filter(Boolean)
    .join(" ")
    .trim();
}

function controls(root) {
  return Array.from(
    root.querySelectorAll("button, input[type=submit], input[type=button], a[role=button]")
  );
}

export function findSubmitControl(root = document) {
  return (
    controls(root).find((el) => isVisible(el) && SUBMIT_PATTERN.test(labelOf(el))) || null
  );
}

export function findAdvanceControl(root = document) {
  return (
    controls(root).find((el) => isVisible(el) && ADVANCE_PATTERN.test(labelOf(el))) || null
  );
}

export function findExternalApplyLink(root = document) {
  const anchors = Array.from(root.querySelectorAll("a[href]"));
  for (const anchor of anchors) {
    const href = anchor.getAttribute("href") || "";
    if (!/^https?:\/\//i.test(href)) continue;
    if (isLinkedInUrl(href)) continue;
    if (/apply|bewerb/i.test(labelOf(anchor))) return href;
  }
  return null;
}

function rootText(root) {
  if (root.body) return root.body.textContent || "";
  return root.textContent || "";
}

export function hasConfirmationText(root = document, pattern = CONFIRMATION_PATTERN) {
  return pattern.test(rootText(root));
}

export function detectInterstitial(root = document, pattern = INTERSTITIAL_PATTERN) {
  if (root.querySelector && root.querySelector(INTERSTITIAL_SELECTOR)) {
    return { detected: true, text: "verification challenge" };
  }
  const match = rootText(root).match(pattern);
  return match ? { detected: true, text: match[0] } : { detected: false, text: null };
}
