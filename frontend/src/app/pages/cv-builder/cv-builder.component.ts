import {
  ChangeDetectionStrategy,
  Component,
  HostListener,
  OnInit,
  effect,
  inject,
  signal,
  untracked,
} from '@angular/core';
import { HttpErrorResponse } from '@angular/common/http';
import { AbstractControl, FormArray, FormBuilder, FormControl, FormGroup } from '@angular/forms';
import { RouterLink } from '@angular/router';

import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatProgressSpinnerModule } from '@angular/material/progress-spinner';
import { MatTabsModule } from '@angular/material/tabs';

import { TranslatePipe } from '../../core/i18n/translate.pipe';
import {
  DocumentLanguage,
  EducationEntry,
  ExperienceEntry,
  LanguageEntry,
  MasterProfileRead,
  ProfileContentUpdate,
  ProjectEntry,
  SkillEntry,
} from '../../core/models/master-profile.model';
import { ContentTranslationService, CvTranslatableContent } from '../../core/services/content-translation.service';
import { ProfileService } from '../../core/services/profile.service';
import { TranslationService } from '../../core/services/translation.service';
import {
  createEducationGroup,
  createExperienceGroup,
  createLanguageGroup,
  createProjectGroup,
  createSkillGroup,
  normalizeProfileSections,
  replaceArray,
} from './cv-section-forms.util';
import { sectionsEqual } from './cv-section-diff.util';
import { CvPreviewExportComponent } from './export/cv-preview-export.component';
import { CvImportComponent } from './import/cv-import.component';
import { EducationSectionComponent } from './sections/education-section.component';
import { ExperienceSectionComponent } from './sections/experience-section.component';
import { LanguagesSectionComponent } from './sections/languages-section.component';
import { PhotoSectionComponent } from './sections/photo-section.component';
import { ProjectsSectionComponent } from './sections/projects-section.component';
import { SkillsSectionComponent } from './sections/skills-section.component';
import { SummarySectionComponent } from './sections/summary-section.component';

type CvBuilderState = 'loading' | 'empty' | 'error' | 'ready';

/** Die jeweils andere der beiden unterstützten Sprachen (R8/R9-Scope). */
function otherLanguage(language: DocumentLanguage): DocumentLanguage {
  return language === 'de' ? 'en' : 'de';
}

/** Snapshot der inaktiven Sprache: flache `{pfad: text}`-Zuordnung plus die
 * Sprache, in der dieser Snapshot gehalten wird. */
interface ContentSnapshot {
  language: DocumentLanguage;
  fields: Record<string, string>;
}

/**
 * CV Builder-Seite (Lebenslauf-Editor). Baut auf dem bestehenden Master-
 * Profil auf (`GET /api/profile`) - siehe KTD9: existiert noch kein Profil
 * (HTTP 404), zeigt diese Seite einen Empty-State statt eines Formulars,
 * analog zur bestehenden 404-Behandlung in `profile.component.ts`. Ein
 * eigener "Builder legt das Profil an"-Pfad wird bewusst nicht gebaut.
 *
 * KTD10: die Editing-UI ist in eine Kind-Komponente pro CV-Sektion
 * aufgeteilt (`ExperienceSectionComponent`, `EducationSectionComponent`,
 * `SkillsSectionComponent`, `SummarySectionComponent`,
 * `LanguagesSectionComponent`, `ProjectsSectionComponent`,
 * `PhotoSectionComponent`), jede mit eigenem FormArray/FormControl, das hier
 * gehalten und per Input übergeben wird (siehe U7/U10) - `PhotoSectionComponent`
 * ist die Ausnahme: sie schreibt direkt über eigene HTTP-Calls
 * (`POST`/`DELETE /profile/photo`) statt über den `PUT /profile`-Payload
 * dieser Elternform. Vorschau & Export bleibt in dieser Unit Platzhalter und
 * wird von einer nachfolgenden Unit befüllt (U9).
 *
 * R14/KTD13: `hasUnsavedChanges()` vergleicht das gesamte Formular
 * strukturell (KTD12, siehe `cv-section-diff.util.ts`) gegen `lastSavedProfile`
 * - genutzt sowohl vom `CanDeactivate`-Guard (`cv-builder.guard.ts`) als auch
 * vom `beforeunload`-Listener unten. `lastSavedProfile` ist die
 * Vergleichsbasis, die nach jedem erfolgreichen Laden/Speichern aktualisiert
 * wird - sie ist zugleich die Grundlage für den Re-Import-Konfliktcheck
 * (R13) in `CvImportComponent`.
 *
 * U5/R5-R9: Das Formular hält immer den Inhalt der AKTIVEN Sprache (globaler
 * Header-Selektor). Die andere Sprache liegt als flacher Snapshot
 * (`otherSnapshot`, `{pfad: text}`) im Speicher. Beim Sprachwechsel wird ein
 * frischer Snapshot direkt angewendet, andernfalls der aktuelle Inhalt im
 * Hintergrund übersetzt (R6) und fehlgeschlagene Felder behalten ihren
 * Originaltext (R9). Eine Nutzereingabe markiert den Snapshot als veraltet
 * (R7); der Save schickt den aktiven Inhalt samt `content_language` und dem
 * inaktiven Snapshot als `content_translations_json`.
 */
@Component({
  selector: 'app-cv-builder',
  standalone: true,
  imports: [
    RouterLink,
    MatButtonModule,
    MatIconModule,
    MatProgressSpinnerModule,
    MatTabsModule,
    ExperienceSectionComponent,
    EducationSectionComponent,
    SkillsSectionComponent,
    SummarySectionComponent,
    LanguagesSectionComponent,
    ProjectsSectionComponent,
    PhotoSectionComponent,
    CvImportComponent,
    CvPreviewExportComponent,
    TranslatePipe,
  ],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <div class="cv-builder-page">
      <header class="cv-builder-page__intro">
        <h1>{{ 'cvBuilder.title' | translate: i18n.language() }}</h1>
        <p>{{ 'cvBuilder.intro' | translate: i18n.language() }}</p>
      </header>

      @switch (state()) {
        @case ('loading') {
          <div class="cv-builder-page__loading">
            <mat-progress-spinner mode="indeterminate" diameter="48" />
            <p>{{ 'cvBuilder.loading' | translate: i18n.language() }}</p>
          </div>
        }
        @case ('empty') {
          <div class="cv-builder-page__empty">
            <mat-icon>info</mat-icon>
            <p>{{ 'cvBuilder.empty' | translate: i18n.language() }}</p>
            <a mat-flat-button color="primary" routerLink="/profile">{{
              'cvBuilder.goToProfile' | translate: i18n.language()
            }}</a>
          </div>
        }
        @case ('error') {
          <div class="cv-builder-page__error">
            <mat-icon>error_outline</mat-icon>
            <p>{{ 'cvBuilder.loadFailed' | translate: i18n.language() }}</p>
            <button
              mat-stroked-button
              type="button"
              class="cv-builder-page__retry"
              (click)="retry()"
            >
              {{ 'cvBuilder.retry' | translate: i18n.language() }}
            </button>
          </div>
        }
        @case ('ready') {
          <div class="cv-builder-page__save-bar">
            <button
              mat-flat-button
              color="primary"
              type="button"
              [disabled]="saving() || translating()"
              (click)="save()"
            >
              @if (saving()) {
                <mat-progress-spinner mode="indeterminate" diameter="18" />
              } @else {
                <mat-icon>save</mat-icon>
              }
              {{ 'cvBuilder.save' | translate: i18n.language() }}
            </button>
            @if (translating()) {
              <span class="cv-builder-page__translating">
                <mat-progress-spinner mode="indeterminate" diameter="18" />
                {{ 'cvBuilder.translating' | translate: i18n.language() }}
              </span>
            }
            @if (translationError(); as message) {
              <p class="cv-builder-page__translate-error">{{ message }}</p>
            }
            @if (saveError(); as message) {
              <p class="cv-builder-page__save-error">{{ message }}</p>
            }
          </div>
          <mat-tab-group animationDuration="150ms">
            <mat-tab [label]="'cvBuilder.tab.summary' | translate: i18n.language()">
              <div class="tab-content">
                <app-summary-section
                  [control]="summaryControl"
                  [berufsbezeichnungControl]="berufsbezeichnungControl"
                />
              </div>
            </mat-tab>
            <mat-tab [label]="'cvBuilder.tab.experience' | translate: i18n.language()">
              <div class="tab-content">
                <app-experience-section [formArray]="experiencesArray" />
              </div>
            </mat-tab>
            <mat-tab [label]="'cvBuilder.tab.education' | translate: i18n.language()">
              <div class="tab-content">
                <app-education-section [formArray]="educationArray" />
              </div>
            </mat-tab>
            <mat-tab [label]="'cvBuilder.tab.skills' | translate: i18n.language()">
              <div class="tab-content">
                <app-skills-section [formArray]="skillsArray" />
              </div>
            </mat-tab>
            <mat-tab [label]="'cvBuilder.tab.languages' | translate: i18n.language()">
              <div class="tab-content">
                <app-languages-section [formArray]="languagesArray" />
              </div>
            </mat-tab>
            <mat-tab [label]="'cvBuilder.tab.projects' | translate: i18n.language()">
              <div class="tab-content">
                <app-projects-section [formArray]="projectsArray" />
              </div>
            </mat-tab>
            <mat-tab [label]="'cvBuilder.tab.photo' | translate: i18n.language()">
              <div class="tab-content">
                <app-photo-section />
              </div>
            </mat-tab>
            <mat-tab [label]="'cvBuilder.tab.import' | translate: i18n.language()">
              <div class="tab-content">
                <app-cv-import
                  [summaryControl]="summaryControl"
                  [experiencesArray]="experiencesArray"
                  [educationArray]="educationArray"
                  [skillsArray]="skillsArray"
                  [projectsArray]="projectsArray"
                  [lastSavedProfile]="lastSavedProfile()"
                  (contentReplaced)="onImportContentReplaced()"
                />
              </div>
            </mat-tab>
            <mat-tab [label]="'cvBuilder.tab.previewExport' | translate: i18n.language()">
              <div class="tab-content">
                <app-cv-preview-export
                  [summaryControl]="summaryControl"
                  [berufsbezeichnungControl]="berufsbezeichnungControl"
                  [experiencesArray]="experiencesArray"
                  [educationArray]="educationArray"
                  [skillsArray]="skillsArray"
                  [languagesArray]="languagesArray"
                  [projectsArray]="projectsArray"
                  [templateIdControl]="templateIdControl"
                />
              </div>
            </mat-tab>
          </mat-tab-group>
        }
      }
    </div>
  `,
  styles: `
    .cv-builder-page {
      max-width: 1000px;
      margin: 0 auto;
      padding: 24px;

      &__intro {
        margin-bottom: 16px;

        h1 {
          margin: 0 0 4px;
        }

        p {
          margin: 0;
        }
      }

      &__loading,
      &__empty,
      &__error {
        display: flex;
        flex-direction: column;
        align-items: center;
        gap: 12px;
        padding: 64px 0;
        text-align: center;
        color: rgba(0, 0, 0, 0.6);
      }
    }

    .tab-content {
      padding: 24px 0;
    }

    .cv-builder-page__save-bar {
      display: flex;
      align-items: center;
      gap: 12px;
      margin-bottom: 8px;

      mat-progress-spinner {
        display: inline-block;
        margin-right: 4px;
      }
    }

    .cv-builder-page__save-error {
      color: #b3261e;
      margin: 0;
    }

    .cv-builder-page__translating {
      display: inline-flex;
      align-items: center;
      gap: 6px;
      color: rgba(0, 0, 0, 0.6);
    }

    .cv-builder-page__translate-error {
      color: #b3261e;
      margin: 0;
    }
  `,
})
export class CvBuilderComponent implements OnInit {
  private readonly profileService = inject(ProfileService);
  private readonly formBuilder = inject(FormBuilder);
  private readonly contentTranslation = inject(ContentTranslationService);
  protected readonly i18n = inject(TranslationService);

  protected readonly state = signal<CvBuilderState>('loading');
  protected readonly saving = signal(false);
  protected readonly saveError = signal<string | null>(null);

  /** R6/R9: sichtbarer Fortschritt bzw. nicht-blockierender Fehler der
   * Hintergrund-Übersetzung beim Sprachwechsel. */
  protected readonly translating = signal(false);
  protected readonly translationError = signal<string | null>(null);

  /** R14/KTD13/R13: Vergleichsbasis für `hasUnsavedChanges()` und den
   * Re-Import-Konfliktcheck in `CvImportComponent` - der zuletzt vom Server
   * bestätigte Profilstand (nach initialem Laden bzw. nach einem
   * erfolgreichen `save()`). Bei einem Sprachwechsel wird sie synchron zum
   * aktiven Inhalt nachgeführt, damit ein reiner Sprachwechsel das Formular
   * nicht fälschlich als "ungespeichert" markiert (U5). */
  protected readonly lastSavedProfile = signal<MasterProfileRead | null>(null);

  /** Sprache, in der die aktuellen Formularwerte gehalten werden. */
  private activeContentLanguage: DocumentLanguage = 'de';

  /** R5: Snapshot der inaktiven Sprache (`null` = veraltet/unbekannt). */
  private otherSnapshot: ContentSnapshot | null = null;

  /** Erst nach dem Laden darf der Sprach-Effekt einen Wechsel auslösen. */
  private readonly contentReady = signal(false);

  /** Guard gegen Doppel-Übersetzungen, solange eine Anfrage läuft. */
  private switching = false;

  /** Letzter Stand der übersetzbaren Prosa-Felder (flach, siehe
   * `ContentTranslationService.flatten`) - eine Wertänderung markiert den
   * Snapshot der anderen Sprache nur dann als veraltet, wenn sich tatsächlich
   * ein übersetzbares Feld geändert hat (P3: nicht bei Firmen-/Datums-/
   * Link-/Niveau-Eingaben). */
  private lastTranslatableFields: Record<string, string> = {};

  /** Unterdrückt die "Snapshot veraltet"-Markierung bei programmatischen
   * Wertänderungen (Sprachwechsel/Snapshot anwenden). */
  private applyingProgrammatically = false;

  protected readonly summaryControl: FormControl<string> = this.formBuilder.nonNullable.control('');
  /** R5: optionaler Job-Titel, im CV unter dem Namen; Inhalt (kein Identitätsfeld). */
  protected readonly berufsbezeichnungControl: FormControl<string> = this.formBuilder.nonNullable.control('');
  protected readonly experiencesArray: FormArray<FormGroup> = this.formBuilder.array<FormGroup>([]);
  protected readonly educationArray: FormArray<FormGroup> = this.formBuilder.array<FormGroup>([]);
  protected readonly skillsArray: FormArray<FormGroup> = this.formBuilder.array<FormGroup>([]);
  protected readonly languagesArray: FormArray<FormGroup> = this.formBuilder.array<FormGroup>([]);
  protected readonly projectsArray: FormArray<FormGroup> = this.formBuilder.array<FormGroup>([]);
  /** R9/KTD8: gewählte CV-Vorlage - befüllt aus `profile.template_id` beim Laden,
   * per `app-cv-preview-export` (Vorschau & Export-Tab) auf die erste verfügbare
   * Vorlage vorbelegt, falls noch keine gewählt wurde. Teil des Save-Payloads,
   * damit die Wahl auf dem Profil persistiert wird. */
  protected readonly templateIdControl: FormControl<string | null> = this.formBuilder.control<string | null>(null);

  constructor() {
    // R6: reagiert auf den globalen Header-Selektor. Solange noch kein Profil
    // geladen ist (`contentReady` false), passiert nichts; nach dem Laden
    // gleicht `initializeContentLanguage` den Inhalt bereits selbst ab.
    effect(
      () => {
        const target = this.i18n.language();
        if (!this.contentReady() || target === this.activeContentLanguage) {
          return;
        }
        this.switchContentLanguage(target);
      },
      { allowSignalWrites: true },
    );

    // R7: jede echte Nutzereingabe in einem übersetzbaren Prosa-Feld macht den
    // Snapshot der anderen Sprache ungültig; er wird beim nächsten Wechsel
    // neu erzeugt. `markOtherLanguageStale` vergleicht dafür die übersetzbaren
    // Felder - eine reine Firmen-/Datums-/Link-/Niveau-Eingabe (P3) lässt den
    // Snapshot gültig. Programmatische Wertänderungen (Sprachwechsel) sind
    // über `applyingProgrammatically` ausgenommen.
    this.summaryControl.valueChanges.subscribe(() => this.markOtherLanguageStale());
    this.berufsbezeichnungControl.valueChanges.subscribe(() => this.markOtherLanguageStale());
    this.experiencesArray.valueChanges.subscribe(() => this.markOtherLanguageStale());
    this.educationArray.valueChanges.subscribe(() => this.markOtherLanguageStale());
    this.projectsArray.valueChanges.subscribe(() => this.markOtherLanguageStale());
    this.languagesArray.valueChanges.subscribe(() => this.markOtherLanguageStale());
  }

  ngOnInit(): void {
    this.loadProfile();
  }

  protected retry(): void {
    this.loadProfile();
  }

  /** Speichert die aktuellen Inhaltsfelder per `PATCH /profile` (R2-R4, KTD2)
   * - bewusst nur die Felder, die dieses Formular besitzt: keine
   * Identitätsfelder, kein Foto (siehe `ProfileContentUpdate`). Aktualisiert
   * bei Erfolg `lastSavedProfile`, wodurch der Guard/Re-Import-Konfliktcheck
   * wieder als "sauber" gilt (KTD12). */
  protected save(): void {
    if (this.saving()) {
      return;
    }

    this.saving.set(true);
    this.saveError.set(null);

    const payload: ProfileContentUpdate = {
      summary: this.summaryControl.value,
      berufsbezeichnung: this.berufsbezeichnungControl.value,
      experiences_json: this.experiencesArray.getRawValue() as ExperienceEntry[],
      education_json: this.educationArray.getRawValue() as EducationEntry[],
      skills_json: this.skillsArray.getRawValue() as SkillEntry[],
      languages_json: this.languagesArray.getRawValue() as LanguageEntry[],
      projects_json: this.projectsArray.getRawValue() as ProjectEntry[],
      template_id: this.templateIdControl.value,
      // P1: die Sprache, in der die aktiven Inhaltsfelder tatsächlich gehalten
      // werden - NICHT die Header-Sprache. Nach einer komplett
      // fehlgeschlagenen Übersetzung bleibt der Inhalt in der Quellsprache,
      // auch wenn der Header bereits die Zielsprache zeigt.
      content_language: this.activeContentLanguage,
      // U5/KTD1: die aktive Sprache plus der Snapshot der inaktiven Sprache.
      // Ein durch eine Nutzereingabe veralteter Snapshot ist `null` und wird
      // als leerer Snapshot gespeichert; er wird beim nächsten Wechsel neu
      // erzeugt (R7).
      content_translations_json: this.inactiveSnapshotFields(),
    };

    this.profileService.patchProfile(payload).subscribe({
      next: (profile) => {
        this.saving.set(false);
        const normalized = normalizeProfileSections(profile);
        this.lastSavedProfile.set(normalized);
        this.activeContentLanguage = normalized.content_language ?? this.activeContentLanguage;
        this.otherSnapshot = Object.keys(normalized.content_translations_json ?? {}).length
          ? { language: otherLanguage(this.activeContentLanguage), fields: { ...normalized.content_translations_json } }
          : null;
      },
      error: () => {
        this.saving.set(false);
        this.saveError.set(this.i18n.translate('cvBuilder.saveFailed'));
      },
    });
  }

  /** R14/KTD12: strukturliche Ganz-Formular-Prüfung gegen `lastSavedProfile`
   * - genutzt vom `CanDeactivate`-Guard (`cv-builder.guard.ts`) und vom
   * `beforeunload`-Listener unten. Öffentlich, da der Guard sie von außen
   * aufruft. */
  hasUnsavedChanges(): boolean {
    const saved = this.lastSavedProfile();
    if (!saved) {
      return false;
    }

    return (
      !sectionsEqual(this.summaryControl.value, saved.summary) ||
      !sectionsEqual(this.berufsbezeichnungControl.value, saved.berufsbezeichnung) ||
      !sectionsEqual(this.experiencesArray.getRawValue(), saved.experiences_json) ||
      !sectionsEqual(this.educationArray.getRawValue(), saved.education_json) ||
      !sectionsEqual(this.skillsArray.getRawValue(), saved.skills_json) ||
      !sectionsEqual(this.languagesArray.getRawValue(), saved.languages_json) ||
      !sectionsEqual(this.projectsArray.getRawValue(), saved.projects_json) ||
      // fix(review) #4: template_id is part of save()'s PATCH payload just
      // like the sections above, so switching templates and navigating away
      // without saving must also trip the unsaved-changes guard.
      !sectionsEqual(this.templateIdControl.value, saved.template_id)
    );
  }

  /** KTD13: Tab-Schließen/Reload-Schutz - der `CanDeactivate`-Guard deckt nur
   * Router-Navigation ab, nicht `beforeunload`. */
  @HostListener('window:beforeunload', ['$event'])
  onBeforeUnload(event: BeforeUnloadEvent): void {
    if (this.hasUnsavedChanges()) {
      event.preventDefault();
      event.returnValue = '';
    }
  }

  private loadProfile(): void {
    this.state.set('loading');
    this.profileService.getProfile().subscribe({
      next: (profile) => {
        this.applyProfileToArrays(profile);
        // fix(review): `lastSavedProfile` must carry the same []-defaulted
        // section values `applyProfileToArrays` just put on the FormArrays -
        // otherwise hasUnsavedChanges()'s sectionsEqual([], undefined) is
        // false right after load (undefined normalizes to null, [] stays
        // []), tripping the CanDeactivate guard/beforeunload with zero user
        // edits for exactly the version-skewed-backend case this fixes.
        this.lastSavedProfile.set(normalizeProfileSections(profile));
        this.state.set('ready');
        this.initializeContentLanguage(profile);
      },
      error: (error: HttpErrorResponse) => {
        this.state.set(error.status === 404 ? 'empty' : 'error');
      },
    });
  }

  private applyProfileToArrays(profile: MasterProfileRead): void {
    this.summaryControl.setValue(profile.summary ?? '');
    this.berufsbezeichnungControl.setValue(profile.berufsbezeichnung ?? '');
    this.templateIdControl.setValue(profile.template_id);

    // `replaceArray` tolerates a missing field - a version-skewed backend
    // (see ce-debug, 2026-09-12) can send a profile without a newer section
    // entirely, and the section should render empty rather than crash.
    replaceArray(this.experiencesArray, profile.experiences_json, (entry) =>
      createExperienceGroup(this.formBuilder, entry),
    );
    replaceArray(this.educationArray, profile.education_json, (entry) => createEducationGroup(this.formBuilder, entry));
    replaceArray(this.skillsArray, profile.skills_json, (entry) => createSkillGroup(this.formBuilder, entry));
    replaceArray(this.languagesArray, profile.languages_json, (entry) => createLanguageGroup(this.formBuilder, entry));
    replaceArray(this.projectsArray, profile.projects_json, (entry) => createProjectGroup(this.formBuilder, entry));
  }

  /** R5: baut den flachen Prosa-Inhalt aus den aktuellen Formularwerten. */
  private readTranslatableContent(): CvTranslatableContent {
    return {
      summary: this.summaryControl.value ?? '',
      berufsbezeichnung: this.berufsbezeichnungControl.value ?? '',
      experiences: this.experiencesArray.getRawValue() as ExperienceEntry[],
      education: this.educationArray.getRawValue() as EducationEntry[],
      projects: this.projectsArray.getRawValue() as ProjectEntry[],
      languages: this.languagesArray.getRawValue() as LanguageEntry[],
    };
  }

  /** KTD1: der inaktive Snapshot für den Save-Payload (`{}`, falls veraltet). */
  private inactiveSnapshotFields(): Record<string, string> {
    if (!this.otherSnapshot || this.otherSnapshot.language === this.activeContentLanguage) {
      return {};
    }
    return { ...this.otherSnapshot.fields };
  }

  /** R7: eine Nutzereingabe in einem übersetzbaren Prosa-Feld macht den
   * Snapshot der anderen Sprache ungültig. P3: Nicht-übersetzbare Felder
   * (Firma, Einrichtung, Link, Datum, Niveau) lassen ihn gültig - dafür wird
   * der flache Prosa-Stand vor/nach der Änderung verglichen. */
  private markOtherLanguageStale(): void {
    if (this.applyingProgrammatically) {
      return;
    }
    const current = this.contentTranslation.flatten(this.readTranslatableContent());
    if (JSON.stringify(current) === JSON.stringify(this.lastTranslatableFields)) {
      return;
    }
    this.lastTranslatableFields = current;
    this.otherSnapshot = null;
    this.translationError.set(null);
  }

  /** Führt den Vergleichsstand der übersetzbaren Felder nach einer
   * programmatischen Änderung (Laden/Sprachwechsel/Import) nach. */
  private refreshTranslatableCache(): void {
    this.lastTranslatableFields = this.contentTranslation.flatten(this.readTranslatableContent());
  }

  /** P1: deaktiviert während einer laufenden Übersetzung genau die
   * übersetzbaren Prosa-Felder, damit die Antwort keine Nutzereingabe
   * überschreiben kann. Nicht-übersetzbare Felder bleiben editierbar. */
  private setTranslatableControlsDisabled(disabled: boolean): void {
    const options = { emitEvent: false };
    const toggle = (control: AbstractControl | null): void => {
      if (!control) {
        return;
      }
      if (disabled) {
        control.disable(options);
      } else {
        control.enable(options);
      }
    };
    const toggleGroups = (array: FormArray<FormGroup>, fields: string[]): void => {
      for (const group of array.controls) {
        for (const field of fields) {
          toggle(group.get(field));
        }
      }
    };

    toggle(this.summaryControl);
    toggle(this.berufsbezeichnungControl);
    toggleGroups(this.experiencesArray, ['role', 'description']);
    toggleGroups(this.educationArray, ['degree', 'field_of_study']);
    toggleGroups(this.projectsArray, ['title', 'description']);
    toggleGroups(this.languagesArray, ['name']);
  }

  /** P2: Nach einem CV-Import hält das Formular den Inhalt in der aktuellen
   * Header-Sprache (der Parse-Aufruf sendet `i18n.language()`). Die aktive
   * Inhaltssprache wird deshalb übernommen und der Snapshot der anderen
   * Sprache verworfen, damit ein späterer Save das korrekte
   * `content_language` schickt und ein Sprachwechsel neu übersetzt. */
  protected onImportContentReplaced(): void {
    this.activeContentLanguage = this.i18n.language();
    this.otherSnapshot = null;
    this.refreshTranslatableCache();
  }

  /**
   * Gleicht den aktiven Formularinhalt nach dem Laden mit der globalen Sprache
   * ab (U5). Ist die globale Sprache bereits die Profilsprache, wird der
   * gespeicherte Snapshot nur übernommen; andernfalls wird gewechselt -
   * entweder durch direktes Anwenden des vorhandenen Snapshots oder durch
   * Hintergrund-Übersetzung (R6).
   */
  private initializeContentLanguage(profile: MasterProfileRead): void {
    const profileLanguage = profile.content_language ?? 'de';
    const storedSnapshot = profile.content_translations_json ?? {};

    this.activeContentLanguage = profileLanguage;
    this.otherSnapshot = Object.keys(storedSnapshot).length
      ? { language: otherLanguage(profileLanguage), fields: { ...storedSnapshot } }
      : null;

    this.refreshTranslatableCache();
    this.contentReady.set(true);
    if (this.i18n.language() !== profileLanguage) {
      this.switchContentLanguage(this.i18n.language());
    }
  }

  /**
   * Wechselt den aktiven Inhalt auf `target` (U5). Ist ein frischer Snapshot
   * vorhanden, wird er direkt angewendet; andernfalls wird der aktuelle Inhalt
   * im Hintergrund übersetzt. Ein fehlgeschlagenes Feld behält seinen
   * Originaltext und der Fehler wird nicht-blockierend angezeigt (R9).
   */
  private switchContentLanguage(target: DocumentLanguage): void {
    if (this.switching) {
      return;
    }
    const source = this.activeContentLanguage;
    if (target === source) {
      return;
    }

    // P2: Nur ein reiner Sprachwechsel (Formular vor dem Wechsel sauber) darf
    // die Vergleichsbasis nachführen. War das Formular bereits schmutzig, muss
    // es das nach dem Wechsel bleiben - sonst maskiert `syncBaseline` echte
    // ungespeicherte Änderungen. `untracked`, weil dies ein einmaliger
    // Schnappschuss ist und den Sprach-Effekt nicht an `lastSavedProfile`
    // binden darf (sonst löst eine Baseline-Änderung eine neue Übersetzung aus).
    const wasDirty = untracked(() => this.hasUnsavedChanges());

    const current = this.readTranslatableContent();
    const sourceFields = this.contentTranslation.flatten(current);

    if (this.otherSnapshot?.language === target) {
      const targetFields = this.otherSnapshot.fields;
      this.otherSnapshot = { language: source, fields: sourceFields };
      this.applyFields(targetFields);
      this.activeContentLanguage = target;
      this.syncBaseline(wasDirty);
      return;
    }

    // Nichts zu übersetzen (z. B. leeres Profil) - kein Ollama-Aufruf nötig.
    if (!Object.values(sourceFields).some((value) => value.trim() !== '')) {
      this.otherSnapshot = { language: source, fields: sourceFields };
      this.activeContentLanguage = target;
      this.syncBaseline(wasDirty);
      return;
    }

    const previousSnapshot = this.otherSnapshot;
    this.switching = true;
    this.translating.set(true);
    this.translationError.set(null);
    // P1: während der Übersetzung keine Prosa-Eingaben zulassen.
    this.setTranslatableControlsDisabled(true);

    this.contentTranslation.translate(source, target, current).subscribe({
      next: (result) => {
        // P1: eine Antwort ohne eine einzige erfolgreiche (nicht-leere)
        // Übersetzung darf weder angewendet werden noch die aktive Sprache
        // oder die Vergleichsbasis umstellen - sonst würde ein späterer Save
        // den unveränderten Quelltext als Zielsprache persistieren.
        const hasSuccessfulTranslation = Object.values(result.translations).some(
          (value) => value.trim() !== '',
        );
        if (!hasSuccessfulTranslation) {
          this.otherSnapshot = previousSnapshot;
          this.translating.set(false);
          this.switching = false;
          this.setTranslatableControlsDisabled(false);
          this.translationError.set(this.i18n.translate('cvBuilder.translationFailed'));
          return;
        }

        this.applyFields(result.translations);
        this.otherSnapshot = { language: source, fields: sourceFields };
        this.activeContentLanguage = target;
        this.translating.set(false);
        this.switching = false;
        this.setTranslatableControlsDisabled(false);
        this.translationError.set(
          Object.keys(result.errors).length > 0 ? this.i18n.translate('cvBuilder.translationFailed') : null,
        );
        this.syncBaseline(wasDirty);
        // Kam während der Anfrage ein weiterer Sprachwechsel dazwischen, jetzt
        // nachziehen (der Effekt-Lauf wurde vom `switching`-Guard geschluckt).
        if (this.i18n.language() !== this.activeContentLanguage) {
          this.switchContentLanguage(this.i18n.language());
        }
      },
      error: () => {
        this.otherSnapshot = previousSnapshot;
        this.translating.set(false);
        this.switching = false;
        this.setTranslatableControlsDisabled(false);
        this.translationError.set(this.i18n.translate('cvBuilder.translationFailed'));
      },
    });
  }

  /** Wendet eine flache `{pfad: text}`-Zuordnung auf die Formularwerte an. */
  private applyFields(fields: Record<string, string>): void {
    const updated = this.contentTranslation.apply(this.readTranslatableContent(), fields);
    this.applyingProgrammatically = true;
    try {
      this.summaryControl.setValue(updated.summary, { emitEvent: false });
      this.berufsbezeichnungControl.setValue(updated.berufsbezeichnung, { emitEvent: false });
      replaceArray(this.experiencesArray, updated.experiences, (entry) =>
        createExperienceGroup(this.formBuilder, entry),
      );
      replaceArray(this.educationArray, updated.education, (entry) => createEducationGroup(this.formBuilder, entry));
      replaceArray(this.languagesArray, updated.languages, (entry) => createLanguageGroup(this.formBuilder, entry));
      replaceArray(this.projectsArray, updated.projects, (entry) => createProjectGroup(this.formBuilder, entry));
    } finally {
      this.applyingProgrammatically = false;
    }
    this.refreshTranslatableCache();
  }

  /**
   * Führt die Vergleichsbasis nach einem programmatischen Sprachwechsel synchron
   * zum aktiven Inhalt nach, damit ein reiner Wechsel `hasUnsavedChanges()`
   * nicht fälschlich auf `true` setzt (U5). Eine spätere echte Nutzereingabe
   * weicht wieder von der Basis ab.
   *
   * P2: War das Formular vor dem Wechsel bereits schmutzig, bleibt die
   * Vergleichsbasis unangetastet - sonst würde ein Sprachwechsel die
   * ungespeicherten Änderungen als gespeichert maskieren.
   */
  private syncBaseline(wasDirty: boolean): void {
    if (wasDirty) {
      return;
    }
    const saved = this.lastSavedProfile();
    if (!saved) {
      return;
    }

    const content = this.readTranslatableContent();
    this.lastSavedProfile.set(
      normalizeProfileSections({
        ...saved,
        summary: content.summary || null,
        berufsbezeichnung: content.berufsbezeichnung || null,
        experiences_json: content.experiences,
        education_json: content.education,
        languages_json: content.languages,
        projects_json: content.projects,
        skills_json: this.skillsArray.getRawValue() as SkillEntry[],
        content_language: this.activeContentLanguage,
        content_translations_json: this.inactiveSnapshotFields(),
      }),
    );
  }
}
