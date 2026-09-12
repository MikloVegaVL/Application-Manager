import { FormArray, FormBuilder, FormGroup, Validators } from '@angular/forms';

import {
  EducationEntry,
  ExperienceEntry,
  LanguageEntry,
  MasterProfileRead,
  ProjectEntry,
  SkillCategory,
  SkillEntry,
} from '../../core/models/master-profile.model';

/**
 * Geteilte "eine Eintrags-FormGroup bauen"-Fabriken für die CV-Builder-
 * Sektionen (KTD10). Vorher jeweils bis zu dreifach dupliziert:
 * `CvBuilderComponent` (Laden aus dem Profil), `CvImportComponent`
 * (Übernahme eines KI-Parse-Ergebnisses) und die jeweilige
 * `*SectionComponent` (`add()`). Feldliste/Validatoren/Defaults sind für
 * jede Entität hier die einzige Quelle der Wahrheit.
 */

export function createExperienceGroup(fb: FormBuilder, entry?: ExperienceEntry): FormGroup {
  return fb.nonNullable.group({
    company: [entry?.company ?? '', Validators.required],
    role: [entry?.role ?? '', Validators.required],
    start_date: [entry?.start_date ?? ''],
    end_date: [entry?.end_date ?? ''],
    description: [entry?.description ?? ''],
  });
}

export function createEducationGroup(fb: FormBuilder, entry?: EducationEntry): FormGroup {
  return fb.nonNullable.group({
    institution: [entry?.institution ?? '', Validators.required],
    degree: [entry?.degree ?? '', Validators.required],
    field_of_study: [entry?.field_of_study ?? ''],
    start_date: [entry?.start_date ?? ''],
    end_date: [entry?.end_date ?? ''],
  });
}

/** Die Kategorien, nach denen der CV Skills gruppiert (siehe `SkillCategory`
 * im Backend). `Other` ist der Default für neue bzw. nicht zugeordnete
 * Skills - so ist das Kategorie-Feld nie leer und der Vergleich gegen den
 * gespeicherten Stand bleibt stabil. */
export const SKILL_CATEGORIES: SkillCategory[] = ['Frontend', 'Backend', 'Tools', 'Soft Skills', 'Other'];
export const DEFAULT_SKILL_CATEGORY: SkillCategory = 'Other';

/** KTD5: Default-Kompetenzgrad, den die Skills-Migration (U1) jedem
 * bestehenden Skill zuweist, sowie der Default für neu hinzugefügte bzw.
 * per CV-Import übernommene Skills (R7: die KI liefert keinen Kompetenzgrad). */
export function createSkillGroup(fb: FormBuilder, entry?: SkillEntry): FormGroup {
  return fb.nonNullable.group({
    name: [entry?.name ?? '', Validators.required],
    level: [entry?.level ?? 'Grundkenntnisse', Validators.required],
    category: [entry?.category ?? DEFAULT_SKILL_CATEGORY, Validators.required],
  });
}

export function createLanguageGroup(fb: FormBuilder, entry?: LanguageEntry): FormGroup {
  return fb.nonNullable.group({
    name: [entry?.name ?? '', Validators.required],
    level: [entry?.level ?? 'A1', Validators.required],
  });
}

export function createProjectGroup(fb: FormBuilder, entry?: ProjectEntry): FormGroup {
  return fb.nonNullable.group({
    title: [entry?.title ?? '', Validators.required],
    description: [entry?.description ?? '', Validators.required],
    start_date: [entry?.start_date ?? ''],
    end_date: [entry?.end_date ?? ''],
    link: [entry?.link ?? ''],
  });
}

/** Geteiltes "eine Sektions-FormArray aus Backend-/Parse-Einträgen neu
 * aufbauen" (KTD10) - vorher in `CvBuilderComponent` und `CvImportComponent`
 * dupliziert. `entries` toleriert `null`/`undefined` (ein Backend, das eine
 * neuere Sektion noch nicht kennt - siehe `ce-debug`, 2026-09-12), damit der
 * Fallback nicht an jeder Aufrufstelle wiederholt werden muss. */
export function replaceArray<T>(
  array: FormArray<FormGroup>,
  entries: T[] | null | undefined,
  factory: (entry: T) => FormGroup,
): void {
  array.clear();
  (entries ?? []).forEach((entry) => array.push(factory(entry)));
}

/** fix(review) (ce-debug, 2026-09-12): normalisiert die Sektions-Felder
 * eines vom Backend geladenen/gespeicherten Profils genau wie `replaceArray`
 * die FormArrays normalisiert - fehlende Felder werden zu `[]`. Muss auf
 * jedem Profil angewendet werden, bevor es in `lastSavedProfile` landet:
 * sonst vergleicht `sectionsEqual` das `[]` der FormArray gegen ein
 * `undefined` im rohen Profil (normalisiert zu `null` statt `[]`) und meldet
 * fälschlich ungespeicherte Änderungen - genau für den Fall eines
 * versionsversetzten Backends, den dieser Fix eigentlich beheben soll. */
export function normalizeProfileSections(profile: MasterProfileRead): MasterProfileRead {
  return {
    ...profile,
    experiences_json: profile.experiences_json ?? [],
    education_json: profile.education_json ?? [],
    // Skills ohne Kategorie (Altdaten) auf den Form-Default normalisieren -
    // sonst vergleicht `sectionsEqual` ein `null` gegen das `Other` des
    // Formulars und meldet fälschlich ungespeicherte Änderungen.
    skills_json: (profile.skills_json ?? []).map((skill) => ({
      ...skill,
      category: skill.category ?? DEFAULT_SKILL_CATEGORY,
    })),
    languages_json: profile.languages_json ?? [],
    projects_json: profile.projects_json ?? [],
  };
}
