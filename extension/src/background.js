// Service worker (U5). Every app API call lives here (KTD1): content scripts
// message the worker and never fetch. The fill packet is cached per tab in
// chrome.storage.session so a reload or a cross-origin navigation reuses it
// instead of re-requesting (KTD2).

import {
  DEFAULT_API_BASE_URL,
  fetchDocumentBytes,
  getFillContext,
  reportSubmission,
  requestAnswer,
} from "./lib/api.js";

export const SECRET_STORAGE_KEY = "portalFillSecret";
export const BASE_URL_STORAGE_KEY = "apiBaseUrl";
export const PACKET_CACHE_PREFIX = "fillPacket:";
export const EMPLOYER_SCRIPT_ID = "am-employer-form";

export const MESSAGE = {
  PAGE_READY: "PAGE_READY",
  REQUEST_ANSWER: "REQUEST_ANSWER",
  REPORT_SUBMISSION: "REPORT_SUBMISSION",
  FETCH_DOCUMENT: "FETCH_DOCUMENT",
  REGISTER_ORIGIN: "REGISTER_ORIGIN",
};

export async function getConfig() {
  const stored = await chrome.storage.local.get([SECRET_STORAGE_KEY, BASE_URL_STORAGE_KEY]);
  return {
    secret: stored[SECRET_STORAGE_KEY] || "",
    baseUrl: stored[BASE_URL_STORAGE_KEY] || DEFAULT_API_BASE_URL,
  };
}

export function packetKey(tabId) {
  return `${PACKET_CACHE_PREFIX}${tabId}`;
}

export async function readCachedPacket(tabId) {
  const key = packetKey(tabId);
  const stored = await chrome.storage.session.get(key);
  return stored[key] || null;
}

export async function cachePacket(tabId, packet) {
  await chrome.storage.session.set({ [packetKey(tabId)]: packet });
}

export async function clearCachedPacket(tabId) {
  await chrome.storage.session.remove(packetKey(tabId));
}

// On page load: serve the tab-scoped cached packet, else ask the app once.
// A 404 means no fill was started for this page, so the content script fills
// nothing (R14/AE3).
export async function handlePageReady({ tabId, url }) {
  const cached = await readCachedPacket(tabId);
  if (cached) return { packet: cached, cached: true };

  const { secret, baseUrl } = await getConfig();
  if (!secret) return { packet: null, error: "no_secret" };

  let packet;
  try {
    packet = await getFillContext(baseUrl, secret, url);
  } catch (error) {
    return { packet: null, error: "app_unreachable", detail: String(error && error.message) };
  }
  if (!packet) return { packet: null, error: "no_fill_request" };

  await cachePacket(tabId, packet);
  return { packet, cached: false };
}

// Runtime registration for an employer origin (R4/SC2): request the origin
// from the fill's user gesture, then register the content script for it only.
export async function registerEmployerContentScript(origin) {
  const pattern = `${origin.replace(/\/+$/, "")}/*`;
  const hasPermission = await chrome.permissions.contains({ origins: [pattern] });
  if (!hasPermission) {
    const granted = await chrome.permissions.request({ origins: [pattern] });
    if (!granted) return { registered: false, error: "permission_denied" };
  }
  try {
    await chrome.scripting.unregisterContentScripts({ ids: [EMPLOYER_SCRIPT_ID] });
  } catch {
    // Not registered yet - fine.
  }
  await chrome.scripting.registerContentScripts([
    { id: EMPLOYER_SCRIPT_ID, matches: [pattern], js: ["content.js"], runAt: "document_idle" },
  ]);
  return { registered: true, pattern };
}

export async function handleMessage(message, sender) {
  const tabId = message.tabId != null ? message.tabId : sender && sender.tab && sender.tab.id;
  switch (message.type) {
    case MESSAGE.PAGE_READY:
      return handlePageReady({ tabId, url: message.url });
    case MESSAGE.REQUEST_ANSWER: {
      const { secret, baseUrl } = await getConfig();
      if (!secret) return { error: "no_secret" };
      try {
        return { answer: await requestAnswer(baseUrl, secret, message.applicationId, message.question) };
      } catch (error) {
        return { error: "llm_unavailable", detail: String(error && error.message) };
      }
    }
    case MESSAGE.REPORT_SUBMISSION: {
      const { secret, baseUrl } = await getConfig();
      if (!secret) return { error: "no_secret" };
      try {
        return { submission: await reportSubmission(baseUrl, secret, message.payload) };
      } catch (error) {
        return { error: "report_failed", detail: String(error && error.message) };
      }
    }
    case MESSAGE.FETCH_DOCUMENT: {
      const { secret, baseUrl } = await getConfig();
      try {
        const { bytes, contentType } = await fetchDocumentBytes(
          baseUrl,
          secret,
          message.document.download_url
        );
        return {
          blob: new Blob([bytes], { type: contentType || "" }),
          filename: message.document.filename,
        };
      } catch (error) {
        return { error: "document_fetch_failed", detail: String(error && error.message) };
      }
    }
    case MESSAGE.REGISTER_ORIGIN:
      return registerEmployerContentScript(message.origin);
    default:
      return { error: "unknown_message" };
  }
}

function wireChromeListeners() {
  chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
    handleMessage(message, sender).then(sendResponse);
    return true;
  });
  chrome.tabs.onRemoved.addListener((tabId) => {
    clearCachedPacket(tabId);
  });
}

if (typeof chrome !== "undefined" && chrome.runtime && chrome.runtime.onMessage) {
  wireChromeListeners();
}
