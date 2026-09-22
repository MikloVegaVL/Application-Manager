// Page entry point (U5). Messages the worker only and acts only when a fill
// packet is available (R14/AE3). Never fetches the app directly (KTD1).

import { fillFields } from "./lib/fill.js";
import { renderFlags } from "./lib/flags.js";

export const MESSAGE = {
  PAGE_READY: "PAGE_READY",
  FETCH_DOCUMENT: "FETCH_DOCUMENT",
};

function send(message) {
  return new Promise((resolve) => chrome.runtime.sendMessage(message, resolve));
}

function fetchDocument(document) {
  return send({ type: MESSAGE.FETCH_DOCUMENT, document }).then((response) => {
    if (!response || response.error) {
      throw new Error((response && response.error) || "document_fetch_failed");
    }
    return { bytes: response.blob, contentType: response.blob.type };
  });
}

// Generic, site-agnostic mapping (R5). Adapters (U7/U8) refine this.
export function buildProfileMappings(packet) {
  const profile = packet.profile || {};
  const mappings = [
    {
      descriptor: { label: "Full name", name: "name", autocomplete: "name" },
      value: profile.full_name,
    },
    {
      descriptor: { label: "Email", name: "email", autocomplete: "email", type: "email" },
      value: profile.email,
    },
    {
      descriptor: { label: "Phone", name: "phone", autocomplete: "tel", type: "tel" },
      value: profile.phone,
    },
    {
      descriptor: { label: "Address", name: "address", autocomplete: "street-address" },
      value: profile.address,
    },
    {
      descriptor: { label: "LinkedIn", name: "linkedin" },
      value: profile.linkedin,
    },
    {
      descriptor: { label: "Website", name: "website", autocomplete: "url" },
      value: profile.website,
    },
    {
      descriptor: { label: "Summary", name: "summary" },
      value: profile.summary,
    },
  ];
  const cv = (packet.documents || []).find((document) => document.kind === "cv");
  if (cv) {
    mappings.push({ descriptor: { label: "Resume", name: "resume", type: "file" }, kind: "file", document: cv });
  }
  return mappings;
}

export async function startFill(packet) {
  return fillFields(document, buildProfileMappings(packet), { fetchDocument });
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

async function init() {
  const response = await send({ type: MESSAGE.PAGE_READY, url: window.location.href });
  if (!response || !response.packet) return;
  const { flags } = await startFill(response.packet);
  renderReviewPanel(flags);
}

if (typeof chrome !== "undefined" && chrome.runtime && chrome.runtime.sendMessage) {
  init();
}
