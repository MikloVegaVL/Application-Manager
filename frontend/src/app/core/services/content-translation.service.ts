import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';

import {
  CvTranslateResponse,
  DocumentLanguage,
  EducationEntry,
  ExperienceEntry,
  LanguageEntry,
  ProjectEntry,
} from '../models/master-profile.model';
import { ProfileService } from './profile.service';

/**
 * Der übersetzbare Prosa-Ausschnitt des CV-Builder-Inhalts (R8). Bewusst ohne
 * Identitätsfelder, Firmen-/Einrichtungsnamen, Skill-Namen und Kontaktdaten -
 * diese sind Eigennamen bzw. Fremdinhalte und werden nie übersetzt.
 */
export interface CvTranslatableContent {
  summary: string;
  berufsbezeichnung: string;
  experiences: ExperienceEntry[];
  education: EducationEntry[];
  projects: ProjectEntry[];
  languages: LanguageEntry[];
}

/**
 * Übersetzt die Prosa-Felder des CV-Builders zwischen Deutsch und Englisch
 * (U5, R5-R9).
 *
 * Der Service kennt das stabile Pfad-Schema (`summary`,
 * `experience.0.role`, `education.0.field_of_study`, `project.0.title`,
 * `language.0.name`, ...), flacht damit den Formularinhalt zu einer flachen
 * `{pfad: text}`-Zuordnung ab und ruft `ProfileService.translateContent` auf.
 * Dadurch bleibt der Übersetzungs-Endpunkt unabhängig von der konkreten
 * Formularstruktur und der Snapshot (`content_translations_json`) hat überall
 * dieselbe, stabile Form.
 */
@Injectable({ providedIn: 'root' })
export class ContentTranslationService {
  private readonly profileService = inject(ProfileService);

  /**
   * Flacht den Prosa-Inhalt zu `{pfad: text}` ab. Alle Pfade werden immer
   * aufgenommen - auch leere Texte -, damit ein später angewendeter Snapshot
   * ein Feld auch bewusst leeren kann (sonst würde ein leerer Zielwert ein
   * noch vorhandenes Quelltext-Feld stehen lassen). Der Übersetzungs-Endpunkt
   * reicht leere Werte unverändert durch, ohne Ollama aufzurufen.
   */
  flatten(content: CvTranslatableContent): Record<string, string> {
    const fields: Record<string, string> = {
      summary: content.summary ?? '',
      berufsbezeichnung: content.berufsbezeichnung ?? '',
    };

    content.experiences.forEach((entry, index) => {
      fields[`experience.${index}.role`] = entry.role ?? '';
      fields[`experience.${index}.description`] = entry.description ?? '';
    });
    content.education.forEach((entry, index) => {
      fields[`education.${index}.degree`] = entry.degree ?? '';
      fields[`education.${index}.field_of_study`] = entry.field_of_study ?? '';
    });
    content.projects.forEach((entry, index) => {
      fields[`project.${index}.title`] = entry.title ?? '';
      fields[`project.${index}.description`] = entry.description ?? '';
    });
    content.languages.forEach((entry, index) => {
      fields[`language.${index}.name`] = entry.name ?? '';
    });

    return fields;
  }

  /**
   * Wendet eine flache `{pfad: text}`-Zuordnung auf den Inhalt an und liefert
   * eine neue Kopie zurück. Pfade, die nicht enthalten sind, bleiben
   * unverändert - so lassen sich Snapshots auch auf einen inzwischen
   * erweiterten Inhalt anwenden.
   */
  apply(content: CvTranslatableContent, fields: Record<string, string>): CvTranslatableContent {
    return {
      summary: fields['summary'] ?? content.summary,
      berufsbezeichnung: fields['berufsbezeichnung'] ?? content.berufsbezeichnung,
      experiences: content.experiences.map((entry, index) => ({
        ...entry,
        role: fields[`experience.${index}.role`] ?? entry.role,
        description: fields[`experience.${index}.description`] ?? entry.description,
      })),
      education: content.education.map((entry, index) => ({
        ...entry,
        degree: fields[`education.${index}.degree`] ?? entry.degree,
        field_of_study: fields[`education.${index}.field_of_study`] ?? entry.field_of_study,
      })),
      projects: content.projects.map((entry, index) => ({
        ...entry,
        title: fields[`project.${index}.title`] ?? entry.title,
        description: fields[`project.${index}.description`] ?? entry.description,
      })),
      languages: content.languages.map((entry, index) => ({
        ...entry,
        name: fields[`language.${index}.name`] ?? entry.name,
      })),
    };
  }

  /**
   * Übersetzt `content` von `source` nach `target` (R6). Liefert die
   * per-Feld-Ergebnisse des Backends unverändert zurück, inklusive der
   * fehlgeschlagenen Felder in `errors` (R9).
   */
  translate(
    source: DocumentLanguage,
    target: DocumentLanguage,
    content: CvTranslatableContent,
  ): Observable<CvTranslateResponse> {
    return this.profileService.translateContent(source, target, this.flatten(content));
  }
}
