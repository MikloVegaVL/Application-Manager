// API client for the Application-Manager fill API. Used ONLY by the service
// worker (KTD1, KTD13): MV3 content-script fetch is CORS-bound even with host
// permissions, while service-worker fetch is not. The content script reaches
// the app by messaging the worker, never by fetching.

export const DEFAULT_API_BASE_URL = "http://localhost:8000/api";

// Header the backend requires on every extension-facing /portal-fill/* route.
export const PORTAL_FILL_SECRET_HEADER = "X-Portal-Fill-Secret";

export class ApiError extends Error {
  constructor(message, status = 0) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

function join(baseUrl, path) {
  return `${String(baseUrl).replace(/\/+$/, "")}${path}`;
}

function authHeaders(secret) {
  return secret ? { [PORTAL_FILL_SECRET_HEADER]: secret } : {};
}

async function readError(res) {
  try {
    const body = await res.json();
    if (body && typeof body.detail === "string") return body.detail;
  } catch {
    // Non-JSON error body - fall through to the status text.
  }
  return `HTTP ${res.status}`;
}

// GET /portal-fill/context?url=... -> fill packet, or null on 404 (R14/AE3).
export async function getFillContext(baseUrl, secret, pageUrl) {
  const res = await fetch(
    join(baseUrl, `/portal-fill/context?url=${encodeURIComponent(pageUrl)}`),
    { method: "GET", headers: authHeaders(secret) }
  );
  if (res.status === 404) return null;
  if (!res.ok) throw new ApiError(await readError(res), res.status);
  return res.json();
}

// POST /portal-fill/answer -> { answer, insufficient_information } (R7).
export async function requestAnswer(baseUrl, secret, applicationId, question) {
  const res = await fetch(join(baseUrl, "/portal-fill/answer"), {
    method: "POST",
    headers: { "Content-Type": "application/json", ...authHeaders(secret) },
    body: JSON.stringify({ application_id: applicationId, question }),
  });
  if (!res.ok) throw new ApiError(await readError(res), res.status);
  return res.json();
}

// POST /portal-fill/submission -> stored PortalSubmission row (R11/KTD3).
export async function reportSubmission(baseUrl, secret, payload) {
  const res = await fetch(join(baseUrl, "/portal-fill/submission"), {
    method: "POST",
    headers: { "Content-Type": "application/json", ...authHeaders(secret) },
    body: JSON.stringify(payload),
  });
  if (!res.ok) throw new ApiError(await readError(res), res.status);
  return res.json();
}

// Document bytes are fetched only by the worker, only from the app origin
// (KTD13). Never logged, never written to extension storage.
export async function fetchDocumentBytes(baseUrl, secret, url) {
  const appOrigin = new URL(baseUrl).origin;
  const target = new URL(url);
  if (target.origin !== appOrigin) {
    throw new ApiError("Refusing to fetch a document outside the app origin", 0);
  }
  const res = await fetch(target.toString(), { headers: authHeaders(secret) });
  if (!res.ok) throw new ApiError(await readError(res), res.status);
  const bytes = await res.arrayBuffer();
  return { bytes, contentType: res.headers.get("content-type") || "" };
}
