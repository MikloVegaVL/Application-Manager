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

/**
 * Entspricht `ParsedCvProfile`: Ergebnis von `POST /cv-builder/parse`.
 * `full_name`/`email`/`phone`/`address` sind reine Anzeigefelder für den
 * CV-Builder-Import (KTD1) - werden im Formular nur read-only dargestellt
 * und NIE in den Save-Payload (`PATCH /profile`) übernommen. `skills` sind
 * bewusst reine Strings (kein `SkillEntry[]`): die KI leitet keinen
 * Kompetenzgrad ab (R7), das Frontend ergänzt beim Übernehmen einen
 * Default-Level.
 */
export interface ParsedCvProfile {
  full_name: string | null;
  email: string | null;
  phone: string | null;
  address: string | null;
  summary: string | null;
  experiences: ExperienceEntry[];
  education: EducationEntry[];
  skills: string[];
  projects: ProjectEntry[];
}

/**
 * Entspricht `CvParseResponse`: Antwort von `POST /cv-builder/parse`.
 * `warnings` benennt jedes Feld, für das die KI nichts gefunden hat - schreibt
 * NICHTS in die Datenbank (R6), das Ergebnis befüllt nur die Formularfelder
 * im Builder.
 */
export interface CvParseResponse {
  parsed: ParsedCvProfile;
  warnings: string[];
}

/**
 * Entspricht `MasterProfileUpdate` - Payload für `PATCH /api/profile`
 * (partielles Update, KTD2): nur die CV-Builder-Inhaltsfelder, bewusst OHNE
 * Identitätsfelder (`full_name`/`email`/`phone`/`address`, 422 falls
 * nicht-null mitgeschickt) und OHNE `photo_path`/`photo_filename` (laufen
 * ausschließlich über die Foto-Endpunkte).
 */
export interface ProfileContentUpdate {
  summary?: string | null;
  experiences_json?: ExperienceEntry[];
  education_json?: EducationEntry[];
  skills_json?: SkillEntry[];
  languages_json?: LanguageEntry[];
  projects_json?: ProjectEntry[];
  template_id?: string | null;
}

/** Entspricht einem Eintrag der `GET /cv-builder/templates`-Antwort (R9): eine wählbare CV-Vorlage. */
export interface CvTemplate {
  id: string;
  label: string;
}

/**
 * Entspricht `CvRenderRequest` - Payload für `POST /cv-builder/preview` und
 * `.../export` (R10/R11, KTD11): der aktuelle, ggf. noch nicht gespeicherte
 * Inhalt des CV-Builder-Formulars, bewusst 1:1 aus den Formularwerten und
 * NICHT aus `lastSavedProfile` gebaut. Identitätsfelder und Foto sind bewusst
 * NICHT Teil dieses Typs - der Server mergt sie serverseitig aus dem
 * gespeicherten `MasterProfile`-Datensatz (siehe `cv_builder.py`).
 */
export interface CvRenderPayload {
  template_id: string;
  summary: string | null;
  experiences_json: ExperienceEntry[];
  education_json: EducationEntry[];
  skills_json: SkillEntry[];
  languages_json: LanguageEntry[];
  projects_json: ProjectEntry[];
}
