// Options page (U5): one-time secret entry plus the required KTD9 LinkedIn
// Terms-of-Service acknowledgement. The secret is stored in extension-private
// chrome.storage.local and never synced (KTD13).

import { DEFAULT_API_BASE_URL } from "./lib/api.js";

export const SECRET_STORAGE_KEY = "portalFillSecret";
export const BASE_URL_STORAGE_KEY = "apiBaseUrl";
export const TOS_STORAGE_KEY = "linkedinTosAcknowledged";

export async function load() {
  const stored = await chrome.storage.local.get([
    SECRET_STORAGE_KEY,
    BASE_URL_STORAGE_KEY,
    TOS_STORAGE_KEY,
  ]);
  document.getElementById("api-base-url").value =
    stored[BASE_URL_STORAGE_KEY] || DEFAULT_API_BASE_URL;
  document.getElementById("secret").value = stored[SECRET_STORAGE_KEY] || "";
  document.getElementById("tos-ack").checked = stored[TOS_STORAGE_KEY] === true;
}

export async function save(event) {
  event.preventDefault();
  const status = document.getElementById("status");
  const acknowledged = document.getElementById("tos-ack").checked;
  if (!acknowledged) {
    status.textContent =
      "Please acknowledge the LinkedIn Terms-of-Service notice before saving.";
    return;
  }

  const baseUrl = document.getElementById("api-base-url").value.trim() || DEFAULT_API_BASE_URL;
  const secret = document.getElementById("secret").value.trim();
  await chrome.storage.local.set({
    [BASE_URL_STORAGE_KEY]: baseUrl,
    [SECRET_STORAGE_KEY]: secret,
    [TOS_STORAGE_KEY]: true,
  });
  status.textContent = "Saved.";
}

if (typeof document !== "undefined" && document.getElementById) {
  document.addEventListener("DOMContentLoaded", () => {
    load();
    document.getElementById("options-form").addEventListener("submit", save);
  });
}
