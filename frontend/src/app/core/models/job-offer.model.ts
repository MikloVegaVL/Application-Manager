/**
 * Spiegelt exakt das Backend-Schema `JobOfferCreate` (siehe
 * `backend/app/schemas/job_offer.py`) wider. Die Feldnamen bleiben bewusst
 * im Snake-Case-Format der API, damit Requests/Responses ohne
 * Umbenennungsschicht 1:1 durchgereicht werden können.
 */
export interface JobOffer {
  title: string;
  company: string;
  location: string | null;
  source_url: string;
  description_text: string | null;
  source_platform: string;
}

/** Entspricht `JobOfferRead`: ein bereits in der DB persistiertes Stellenangebot. */
export interface JobOfferRead extends JobOffer {
  id: number;
  created_at: string;
  is_processed: boolean;
}

/**
 * Fehler-`detail` von `POST /jobs/save` bei 409 (Job bereits gespeichert).
 * Spiegelt das Backend-Detail-Objekt aus `save_job` (siehe
 * `backend/app/api/jobs.py`) - `job_offer_id` lässt das Frontend trotz
 * Konflikt direkt zum bereits gespeicherten Job navigieren, statt in einer
 * Sackgasse zu enden (ce-debug-Fix, 2026-08-24).
 */
export interface JobSaveConflictDetail {
  message: string;
  job_offer_id: number;
}

/**
 * Status einer einzelnen Quelle innerhalb einer Jobsuche-Antwort. Spiegelt
 * das Backend-Schema `SourceStatus` (siehe `backend/app/schemas/job_offer.py`).
 * `status: 'unavailable'` deckt laut Anforderung R5 sowohl echte Fehler/
 * Timeouts als auch eine leere Trefferliste ab; `reason` unterscheidet den
 * Fall näher (z. B. "timeout", "rate-limited", "error", "empty"). Der Grund
 * "not-configured" markiert Quellen, deren Zugangsdaten fehlen - sie werden
 * bewusst nicht abgefragt (siehe R9/KTD5).
 */
export interface SourceStatus {
  platform: string;
  status: 'ok' | 'unavailable';
  reason: 'timeout' | 'rate-limited' | 'error' | 'empty' | 'not-configured' | null;
}

/**
 * Antwort von `GET /jobs/search`. Spiegelt `JobSearchResponse` im Backend:
 * die zusammengeführten Ergebnisse aller Quellen plus ein Status-Eintrag
 * pro Quelle.
 */
export interface JobSearchResponse {
  results: JobOffer[];
  sources: SourceStatus[];
}
