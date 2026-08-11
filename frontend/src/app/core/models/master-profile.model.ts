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
  created_at: string;
  updated_at: string;
}
