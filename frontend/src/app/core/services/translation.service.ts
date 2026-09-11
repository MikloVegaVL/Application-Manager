import { DOCUMENT } from '@angular/common';
import { Injectable, inject, signal } from '@angular/core';

import { Language, TRANSLATIONS } from '../i18n/translations';

const STORAGE_KEY = 'app-language';
const DEFAULT_LANGUAGE: Language = 'de';

export interface LanguageOption {
  id: Language;
  label: string;
}

export const LANGUAGE_OPTIONS: readonly LanguageOption[] = [
  { id: 'de', label: 'Deutsch' },
  { id: 'en', label: 'English' },
];

/**
 * Runtime-Übersetzung für UI-Texte. Anders als Angulars Build-Time-i18n
 * erlaubt dieser Service das Umschalten der Sprache ohne Reload.
 *
 * Übersetzt werden ausschließlich statische Labels/Buttons/Hinweise - niemals
 * Nutzereingaben oder Backend-Inhalte.
 */
@Injectable({ providedIn: 'root' })
export class TranslationService {
  private readonly document = inject(DOCUMENT);
  private readonly languageSignal = signal<Language>(this.readStoredLanguage());

  readonly languages = LANGUAGE_OPTIONS;
  readonly language = this.languageSignal.asReadonly();

  constructor() {
    this.applyLanguage(this.languageSignal());
  }

  setLanguage(language: Language): void {
    this.languageSignal.set(language);
    this.applyLanguage(language);
  }

  /** Übersetzt `key` in die aktuelle Sprache und ersetzt `{name}`-Platzhalter. */
  translate(key: string, params?: Record<string, string | number>): string {
    return this.translateIn(this.languageSignal(), key, params);
  }

  /**
   * Übersetzt `key` in eine explizit übergebene Sprache. Wird vom
   * (reinen) `TranslatePipe` genutzt, der die Sprache als Argument erhält -
   * dadurch wird die View beim Sprachwechsel zuverlässig neu gerendert, auch
   * in OnPush-Komponenten.
   */
  translateIn(language: Language, key: string, params?: Record<string, string | number>): string {
    const dictionary = TRANSLATIONS[language] ?? TRANSLATIONS[DEFAULT_LANGUAGE];
    let text = dictionary[key] ?? TRANSLATIONS[DEFAULT_LANGUAGE][key] ?? key;

    if (params) {
      for (const [name, value] of Object.entries(params)) {
        text = text.split(`{${name}}`).join(String(value));
      }
    }

    return text;
  }

  private applyLanguage(language: Language): void {
    this.document.documentElement.setAttribute('lang', language);

    try {
      localStorage.setItem(STORAGE_KEY, language);
    } catch {
      /* localStorage nicht verfügbar - Auswahl gilt nur für die aktuelle Sitzung. */
    }
  }

  private readStoredLanguage(): Language {
    try {
      const stored = localStorage.getItem(STORAGE_KEY);
      if (stored === 'de' || stored === 'en') {
        return stored;
      }
    } catch {
      /* localStorage nicht verfügbar - Standardsprache verwenden. */
    }
    return DEFAULT_LANGUAGE;
  }
}
