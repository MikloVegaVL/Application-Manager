import { EducationEntry, ExperienceEntry } from './master-profile.model';

/** Spiegelt `backend/app/models/application.py::ApplicationStatus` wider. */
export type ApplicationStatus = 'draft' | 'sent' | 'rejected' | 'interview';

/**
 * Render-fertiger, maßgeschneiderter Lebenslauf (entspricht
 * `backend/app/schemas/generation.py::TailoredCv`). Kontaktdaten stammen
 * deterministisch aus dem Profil, restliche Inhalte sind KI-kuratiert.
 */
export interface TailoredCv {
  full_name: string;
  email: string;
  phone: string | null;
  address: string | null;
  summary: string;
  experiences: ExperienceEntry[];
  education: EducationEntry[];
  skills: string[];
}

/** Entspricht `ApplicationRead`. */
export interface Application {
  id: number;
  job_offer_id: number;
  cover_letter_text: string | null;
  tailored_cv_json: TailoredCv | null;
  pdf_path: string | null;
  status: ApplicationStatus;
  sent_at: string | null;
  created_at: string;
}

/** Payload für `PUT /api/applications/{id}` (Editor-Änderungen). */
export interface ApplicationUpdatePayload {
  cover_letter_text?: string;
  tailored_cv_json?: TailoredCv;
}

/** Payload für `POST /api/applications/{id}/send`. */
export interface ApplicationSendPayload {
  to_email: string;
  subject?: string;
  message?: string;
}
