import { FormBuilder, FormGroup, Validators } from '@angular/forms';

import {
  EducationEntry,
  ExperienceEntry,
  LanguageEntry,
  ProjectEntry,
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

/** KTD5: Default-Kompetenzgrad, den die Skills-Migration (U1) jedem
 * bestehenden Skill zuweist, sowie der Default für neu hinzugefügte bzw.
 * per CV-Import übernommene Skills (R7: die KI liefert keinen Kompetenzgrad). */
export function createSkillGroup(fb: FormBuilder, entry?: SkillEntry): FormGroup {
  return fb.nonNullable.group({
    name: [entry?.name ?? '', Validators.required],
    level: [entry?.level ?? 'Grundkenntnisse', Validators.required],
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
