import { JobOfferRead } from './job-offer.model';

/** Spiegelt `backend/app/models/application.py::ApplicationStatus` wider. */
export type ApplicationStatus = 'draft' | 'sent' | 'rejected' | 'accepted' | 'interview';

/** Spiegelt `ProfileType` aus `backend/app/schemas/application.py`
 * (`ApplicationGenerateRequest.profile_type`) - manuelle Profilwahl vor der
 * ersten Generierung (R4/U8). */
export type ProfileType = 'it' | 'full_life';

/**
 * Kompaktes "applied"-Indiz aus der jüngsten `PortalSubmission`-Zeile der
 * Bewerbung (`ApplicationRead.submission`, siehe U4/KTD3) - `null`, solange
 * kein Portal-Fill erfolgreich gemeldet wurde.
 */
export interface ApplicationSubmissionSummary {
  platform: string | null;
  portal_url: string;
  submitted_at: string;
}

/** Entspricht `ApplicationRead`. */
export interface Application {
  id: number;
  job_offer_id: number;
  cover_letter_text: string | null;
  status: ApplicationStatus;
  sent_at: string | null;
  /** Empfängeradresse des Mailversands - erst nach dem Versand gesetzt. */
  sent_to_email: string | null;
  /** "Applied"-Indiz aus der Portal-Submission - `null`, solange nichts gemeldet wurde. */
  submission: ApplicationSubmissionSummary | null;
  created_at: string;
  /** Zugeordnetes Profil (`it`/`full_life`, U3/R4/R5) - `null`, solange noch
   * nicht generiert wurde; danach für diese Bewerbung gesperrt. */
  profile_type: ProfileType | null;
  /** Stellenangebot, zu dem die Bewerbung gehört - für die Übersichtsliste. */
  job_offer: JobOfferRead;
}

/** Payload für `PUT /api/applications/{id}` (Editor-Änderungen). */
export interface ApplicationUpdatePayload {
  cover_letter_text?: string;
  status?: ApplicationStatus;
}

/** Payload für `POST /api/applications/{id}/send`. */
export interface ApplicationSendPayload {
  to_email: string;
  subject?: string;
  message?: string;
}

/** Antwort von `POST /api/applications/{id}/fill-request` - die Job-URL, die in einem neuen Tab geöffnet wird (R1). */
export interface FillRequestResponse {
  job_url: string;
}
