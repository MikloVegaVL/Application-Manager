import { JobOfferRead } from './job-offer.model';

/** Spiegelt `backend/app/models/application.py::ApplicationStatus` wider. */
export type ApplicationStatus = 'draft' | 'sent' | 'rejected' | 'accepted' | 'interview';

/** Entspricht `ApplicationRead`. */
export interface Application {
  id: number;
  job_offer_id: number;
  cover_letter_text: string | null;
  status: ApplicationStatus;
  sent_at: string | null;
  /** Empfängeradresse des Mailversands - erst nach dem Versand gesetzt. */
  sent_to_email: string | null;
  created_at: string;
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
