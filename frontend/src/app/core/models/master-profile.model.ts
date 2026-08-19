/** Spiegelt `backend/app/schemas/master_profile.py` wider. */

export interface ExperienceEntry {
  company: string;
  role: string;
  start_date: string | null;
  end_date: string | null;
  description: string | null;
}

export interface EducationEntry {
  institution: string;
  degree: string;
  field_of_study: string | null;
  start_date: string | null;
  end_date: string | null;
}

/** Entspricht `MasterProfileCreate` - Payload für `PUT /api/profile` (Upsert). */
export interface MasterProfile {
  full_name: string;
  email: string;
  phone: string | null;
  address: string | null;
  summary: string | null;
  experiences_json: ExperienceEntry[];
  education_json: EducationEntry[];
  skills_json: string[];
}

/** Entspricht `MasterProfileRead`: das persistierte Profil inkl. Metadaten. */
export interface MasterProfileRead extends MasterProfile {
  id: number;
  /** Name der hochgeladenen Lebenslauf-Anhang-Datei, `null` = noch keine hochgeladen. */
  cv_filename: string | null;
  created_at: string;
  updated_at: string;
}

/**
 * Entspricht `CvUploadResponse`: Antwort von `POST /profile/upload-cv`.
 * `upload_cv` übernimmt ein Feld nur, wenn die KI dafür etwas gefunden hat -
 * `warnings` benennt jedes Feld, das deshalb NICHT übernommen wurde, damit
 * ein unvollständiger CV-Import nicht als unbedingter Erfolg erscheint
 * (siehe ce-debug-Untersuchung, 2026-08-18).
 */
export interface CvUploadResponse {
  profile: MasterProfileRead;
  warnings: string[];
}
