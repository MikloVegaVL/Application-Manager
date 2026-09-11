import { DOCUMENT } from '@angular/common';
import { Injectable, inject, signal } from '@angular/core';

export type ThemeId = 'deeppurple-amber' | 'indigo-pink' | 'pink-bluegrey' | 'purple-green';
export type ThemeTone = 'light' | 'dark';

export interface ThemeOption {
  id: ThemeId;
  label: string;
  /** Dateiname des gebündelten Angular-Material-Prebuilt-Themes. */
  href: string;
  /** Helligkeit des Themes - steuert die theme-abhängigen CSS-Tokens. */
  tone: ThemeTone;
}

const STORAGE_KEY = 'app-theme';
const DEFAULT_THEME: ThemeId = 'purple-green';

export const THEME_OPTIONS: readonly ThemeOption[] = [
  {
    id: 'deeppurple-amber',
    label: 'Deep Purple & Amber',
    href: 'theme-deeppurple-amber.css',
    tone: 'light',
  },
  { id: 'indigo-pink', label: 'Indigo & Pink', href: 'theme-indigo-pink.css', tone: 'light' },
  {
    id: 'pink-bluegrey',
    label: 'Pink & Blue Grey',
    href: 'theme-pink-bluegrey.css',
    tone: 'dark',
  },
  {
    id: 'purple-green',
    label: 'Purple & Green',
    href: 'theme-purple-green.css',
    tone: 'dark',
  },
];

const DEFAULT_OPTION = THEME_OPTIONS.find((option) => option.id === DEFAULT_THEME)!;

/**
 * Wechselt zur Laufzeit zwischen den vier Angular-Material-Prebuilt-Themes.
 *
 * Die Themes werden als eigenständige CSS-Bundles gebaut (`inject: false` in
 * `angular.json`) und über das `<link id="app-theme">` in `index.html`
 * eingebunden. Da alle Prebuilt-Themes dieselben CSS-Klassen definieren,
 * darf immer nur genau eines geladen sein - deshalb wird lediglich das `href`
 * ausgetauscht statt mehrere Themes parallel einzubinden.
 */
@Injectable({ providedIn: 'root' })
export class ThemeService {
  private readonly document = inject(DOCUMENT);
  private readonly selectedId = signal<ThemeId>(this.readStoredTheme());

  readonly options = THEME_OPTIONS;
  readonly selected = this.selectedId.asReadonly();

  constructor() {
    this.applyTheme(this.selectedId());
  }

  select(id: ThemeId): void {
    this.selectedId.set(id);
    this.applyTheme(id);
  }

  private applyTheme(id: ThemeId): void {
    const option = this.options.find((theme) => theme.id === id) ?? DEFAULT_OPTION;

    const link = this.document.getElementById('app-theme') as HTMLLinkElement | null;
    if (link) {
      link.href = option.href;
    }

    const root = this.document.documentElement;
    root.setAttribute('data-theme', option.id);
    root.setAttribute('data-theme-tone', option.tone);
    // Native UI (Scrollbars, Formulare) an den Hell/Dunkel-Ton angleichen.
    root.style.colorScheme = option.tone;

    try {
      localStorage.setItem(STORAGE_KEY, option.id);
    } catch {
      /* localStorage nicht verfügbar - Auswahl gilt nur für die aktuelle Sitzung. */
    }
  }

  private readStoredTheme(): ThemeId {
    try {
      const stored = localStorage.getItem(STORAGE_KEY);
      if (stored && THEME_OPTIONS.some((theme) => theme.id === stored)) {
        return stored as ThemeId;
      }
    } catch {
      /* localStorage nicht verfügbar - Standard-Theme verwenden. */
    }
    return DEFAULT_THEME;
  }
}
