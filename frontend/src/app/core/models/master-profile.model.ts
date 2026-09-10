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

/**
 * KTD3: Skill-Kompetenzgrad als 4-stufige Skala (deutschsprachige Konvention,
 * bereits im übrigen UI dieser App verwendet) - ein fixer, geschlossener
 * Wertebereich, kein bespoke-Design. `"Grundkenntnisse"` ist zugleich die
 * niedrigste Stufe UND der Default, den die Skills-Migration (siehe U1)
 * bestehenden Skills zuweist - siehe KTD5.
 */
export type SkillLevel = 'Grundkenntnisse' | 'Gut' | 'Sehr gut' | 'Experte';

/** Entspricht `SkillEntry`: ein Skill mit Kompetenzgrad. */
export interface SkillEntry {
  name: string;
  level: SkillLevel;
}

/**
 * KTD3: Sprachkenntnisse nutzen den bestehenden externen CEFR-Standard
 * (A1-C2), kein bespoke-Design nötig.
 */
export type LanguageLevel = 'A1' | 'A2' | 'B1' | 'B2' | 'C1' | 'C2';

/** Entspricht `LanguageEntry`: eine Sprachkenntnis mit CEFR-Niveau. */
export interface LanguageEntry {
  name: string;
  level: LanguageLevel;
}

/** Entspricht `ProjectEntry`: ein Projekt im CV-Builder. */
export interface ProjectEntry {
  title: string;
  description: string;
  start_date: string | null;
  end_date: string | null;
  link: string | null;
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
  skills_json: SkillEntry[];
  languages_json: LanguageEntry[];
  projects_json: ProjectEntry[];
  photo_filename: string | null;
  template_id: string | null;
}

/**
 * Entspricht `ProfileAttachmentRead`: ein zusätzlicher PDF-Anhang am
 * Stammprofil (max. 3, siehe `ProfileService.uploadAttachment`), der beim
 * Versand einer Bewerbung neben dem Lebenslauf mitgeschickt wird.
 */
export interface ProfileAttachment {
  id: number;
  filename: string;
  created_at: string;
}

/** Entspricht `MasterProfileRead`: das persistierte Profil inkl. Metadaten. */
export interface MasterProfileRead extends MasterProfile {
  id: number;
  /** Name der hochgeladenen Lebenslauf-Anhang-Datei, `null` = noch keine hochgeladen. */
  cv_filename: string | null;
  /** Zusätzliche PDF-Anhänge, unabhängig vom Lebenslauf - siehe `ProfileAttachment`. */
  attachments: ProfileAttachment[];
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
