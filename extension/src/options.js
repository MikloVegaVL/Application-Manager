// Options page (U5): one-time secret entry. The secret is stored in
// extension-private chrome.storage.local and never synced (KTD13).

import { DEFAULT_API_BASE_URL } from "./lib/api.js";

export const SECRET_STORAGE_KEY = "portalFillSecret";
export const BASE_URL_STORAGE_KEY = "apiBaseUrl";

async function load() {
  const stored = await chrome.storage.local.get([SECRET_STORAGE_KEY, BASE_URL_STORAGE_KEY]);
  const baseInput = document.getElementById("api-base-url");
  const secretInput = document.getElementById("secret");
  baseInput.value = stored[BASE_URL_STORAGE_KEY] || DEFAULT_API_BASE_URL;
  secretInput.value = stored[SECRET_STORAGE_KEY] || "";
}

async function save(event) {
  event.preventDefault();
  const status = document.getElementById("status");
  const baseUrl = document.getElementById("api-base-url").value.trim() || DEFAULT_API_BASE_URL;
  const secret = document.getElementById("secret").value.trim();
  await chrome.storage.local.set({
    [BASE_URL_STORAGE_KEY]: baseUrl,
    [SECRET_STORAGE_KEY]: secret,
  });
  status.textContent = "Saved.";
}

if (typeof document !== "undefined" && document.getElementById) {
  document.addEventListener("DOMContentLoaded", () => {
    load();
    document.getElementById("options-form").addEventListener("submit", save);
  });
}
