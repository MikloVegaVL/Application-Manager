import { ChangeDetectionStrategy, Component, Input, inject, signal } from '@angular/core';
import { HttpErrorResponse } from '@angular/common/http';
import { FormArray, FormBuilder, FormControl, FormGroup } from '@angular/forms';

import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatProgressSpinnerModule } from '@angular/material/progress-spinner';

import { MasterProfileRead, ParsedCvProfile, SkillEntry } from '../../../core/models/master-profile.model';
import { ProfileService } from '../../../core/services/profile.service';
import {
  createEducationGroup,
  createExperienceGroup,
  createProjectGroup,
  createSkillGroup,
} from '../cv-section-forms.util';
import { sectionsEqual } from '../cv-section-diff.util';

/** Die vier Sektionen, die ein CV-Import befüllt und die dem R13-
 * Konfliktcheck unterliegen (KTD12) - `summary` bewusst NICHT enthalten
 * (R13 nennt ausdrücklich nur Berufserfahrung/Ausbildung/Skills/Projekte;
 * die Zusammenfassung wird bei jedem Import direkt übernommen). Foto und
 * Sprachen werden vom Parse nie befüllt (R7) und tauchen hier ebenfalls
 * nicht auf. */
type ImportSectionKey = 'experiences_json' | 'education_json' | 'skills_json' | 'projects_json';

interface ImportSectionConflict {
  key: ImportSectionKey;
  label: string;
}

const SECTION_LABELS: Record<ImportSectionKey, string> = {
  experiences_json: 'Berufserfahrung',
  education_json: 'Ausbildung',
  skills_json: 'Skills',
  projects_json: 'Projekte',
};

/** KTD5: Default-Kompetenzgrad für aus dem CV-Import übernommene Skills - die
 * KI liefert nur Namen (`ParsedCvProfile.skills: string[]`), nie einen
 * Kompetenzgrad (R7, bewusst dem Nutzer überlassen). */
const IMPORTED_SKILL_LEVEL: SkillEntry['level'] = 'Grundkenntnisse';

/**
 * Import-Sektion des CV Builders (R5-R8, R13). Lädt eine Lebenslauf-PDF hoch
 * (`ProfileService.parseCv`) und befüllt die vom Eltern-`CvBuilderComponent`
 * übergebenen Formularsektionen - Name/Kontakt aus der Antwort werden
 * ausschließlich read-only zur Anzeige gerendert und nie in ein Formularfeld
 * geschrieben (KTD1). Foto und Sprachen bleiben unangetastet (R7).
 *
 * KTD12/R13: bevor ein erneuter Import (Re-Parse) Berufserfahrung/
 * Ausbildung/Skills/Projekte überschreibt, wird jede dieser vier Sektionen
 * strukturell gegen den zuletzt gespeicherten Profilstand verglichen. Nur
 * Sektionen mit einer Abweichung (= ungespeicherte Handbearbeitung) lösen
 * eine Bestätigung aus; ist keine betroffen, wird der neue Import sofort
 * übernommen.
 */
@Component({
  selector: 'app-cv-import',
  standalone: true,
  imports: [MatButtonModule, MatIconModule, MatProgressSpinnerModule],
  template: `
    <section class="cv-import">
      <h3>Lebenslauf importieren</h3>
      <p>
        Lade eine Lebenslauf-PDF hoch, um Zusammenfassung, Berufserfahrung, Ausbildung, Skills und
        Projekte automatisch vorzubefüllen. Foto und Sprachen werden dabei nicht verändert - Name-
        und Kontaktdaten dienen nur zur Kontrolle und werden nicht übernommen.
      </p>

      <div
        class="cv-import__dropzone"
        [class.cv-import__dropzone--dragover]="isDragOver()"
        (dragover)="onDragOver($event)"
        (dragleave)="onDragLeave($event)"
        (drop)="onDrop($event)"
        (click)="fileInput.click()"
      >
        @if (uploading()) {
          <mat-progress-spinner mode="indeterminate" diameter="32" />
          <p>Lebenslauf wird analysiert ...</p>
        } @else {
          <mat-icon>upload_file</mat-icon>
          <p>Lebenslauf-PDF hierher ziehen oder klicken zum Auswählen</p>
        }
      </div>
      <input #fileInput type="file" accept="application/pdf" hidden (change)="onFileSelected($event)" />

      @if (errorMessage(); as message) {
        <div class="cv-import__error">
          <p>{{ message }}</p>
          <button mat-stroked-button type="button" (click)="retry()">Erneut versuchen</button>
        </div>
      }

      @if (conflicts().length > 0) {
        <div class="cv-import__conflict">
          <p>
            Diese Bereiche enthalten noch nicht gespeicherte Änderungen und werden beim Übernehmen
            des neuen Imports ersetzt: {{ conflictLabels() }}.
          </p>
          <div class="cv-import__conflict-actions">
            <button mat-stroked-button type="button" (click)="cancelReplace()">Abbrechen</button>
            <button mat-flat-button color="primary" type="button" (click)="confirmReplace()">
              Übernehmen
            </button>
          </div>
        </div>
      }

      @if (parsedResult(); as parsed) {
        <div class="cv-import__identity">
          <h4>Erkannte Kontaktdaten (nur zur Anzeige, wird nicht gespeichert)</h4>
          <dl>
            <dt>Name</dt>
            <dd>{{ parsed.full_name || '—' }}</dd>
            <dt>E-Mail</dt>
            <dd>{{ parsed.email || '—' }}</dd>
            <dt>Telefon</dt>
            <dd>{{ parsed.phone || '—' }}</dd>
            <dt>Adresse</dt>
            <dd>{{ parsed.address || '—' }}</dd>
          </dl>
        </div>
      }

      @if (warnings().length > 0) {
        <ul class="cv-import__warnings">
          @for (warning of warnings(); track warning) {
            <li>{{ warning }}</li>
          }
        </ul>
      }
    </section>
  `,
  styles: `
    .cv-import {
      display: flex;
      flex-direction: column;
      gap: 12px;

      h3,
      h4 {
        margin: 0;
      }

      &__dropzone {
        display: flex;
        flex-direction: column;
        align-items: center;
        justify-content: center;
        gap: 8px;
        padding: 40px 24px;
        border: 2px dashed rgba(255, 255, 255, 0.6);
        border-radius: 8px;
        cursor: pointer;
        text-align: center;
        color: rgba(255, 255, 255, 0.6);
        transition:
          border-color 150ms ease,
          background-color 150ms ease;

        mat-icon {
          font-size: 40px;
          width: 40px;
          height: 40px;
        }

        &--dragover {
          background-color: rgba(63, 81, 181, 0.06);
        }
      }

      &__error p {
        color: #b3261e;
        margin: 0 0 8px;
      }

      &__conflict {
        border: 1px solid rgba(179, 38, 30, 0.4);
        border-radius: 8px;
        padding: 12px 16px;

        p {
          margin: 0 0 8px;
        }
      }

      &__conflict-actions {
        display: flex;
        gap: 8px;
        justify-content: flex-end;
      }

      &__identity dl {
        display: grid;
        grid-template-columns: auto 1fr;
        gap: 4px 12px;
        margin: 8px 0 0;
      }

      &__identity dt {
        font-weight: 600;
      }

      &__identity dd {
        margin: 0;
      }

      &__warnings {
        margin: 0;
        padding-left: 20px;
      }
    }

    @media (prefers-color-scheme: dark) {
      .cv-import__dropzone {
        border-color: rgba(255, 255, 255, 0.6);
      }
    }
  `,
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class CvImportComponent {
  private readonly profileService = inject(ProfileService);
  private readonly formBuilder = inject(FormBuilder);

  @Input({ required: true }) summaryControl!: FormControl<string>;
  @Input({ required: true }) experiencesArray!: FormArray<FormGroup>;
  @Input({ required: true }) educationArray!: FormArray<FormGroup>;
  @Input({ required: true }) skillsArray!: FormArray<FormGroup>;
  @Input({ required: true }) projectsArray!: FormArray<FormGroup>;
  /** Zuletzt gespeicherter Profilstand (KTD12-Vergleichsbasis) - `null`, solange
   * noch nie gespeichert wurde bzw. das Profil noch nicht geladen ist. */
  @Input({ required: true }) lastSavedProfile: MasterProfileRead | null = null;

  protected readonly isDragOver = signal(false);
  protected readonly uploading = signal(false);
  protected readonly errorMessage = signal<string | null>(null);
  protected readonly parsedResult = signal<ParsedCvProfile | null>(null);
  protected readonly warnings = signal<string[]>([]);
  protected readonly conflicts = signal<ImportSectionConflict[]>([]);

  private lastFile: File | null = null;
  private pendingParse: ParsedCvProfile | null = null;

  onDragOver(event: DragEvent): void {
    event.preventDefault();
    this.isDragOver.set(true);
  }

  onDragLeave(event: DragEvent): void {
    event.preventDefault();
    this.isDragOver.set(false);
  }

  onDrop(event: DragEvent): void {
    event.preventDefault();
    this.isDragOver.set(false);
    const file = event.dataTransfer?.files?.[0];
    if (file) {
      this.startUpload(file);
    }
  }

  onFileSelected(event: Event): void {
    const input = event.target as HTMLInputElement;
    const file = input.files?.[0];
    if (file) {
      this.startUpload(file);
    }
    input.value = '';
  }

  retry(): void {
    if (this.lastFile) {
      this.startUpload(this.lastFile);
    }
  }

  confirmReplace(): void {
    if (!this.pendingParse) {
      return;
    }
    this.applySections(
      this.pendingParse,
      this.conflicts().map((conflict) => conflict.key),
    );
    this.pendingParse = null;
    this.conflicts.set([]);
  }

  cancelReplace(): void {
    // R13: Cancel verwirft den neuen Import vollständig - die vorhandenen
    // Handbearbeitungen in den betroffenen Sektionen bleiben unangetastet.
    this.pendingParse = null;
    this.conflicts.set([]);
  }

  protected conflictLabels(): string {
    return this.conflicts()
      .map((conflict) => conflict.label)
      .join(', ');
  }

  private startUpload(file: File): void {
    if (file.type && file.type !== 'application/pdf') {
      this.errorMessage.set('Bitte eine PDF-Datei auswählen.');
      return;
    }

    this.lastFile = file;
    this.errorMessage.set(null);
    this.uploading.set(true);
    this.profileService.parseCv(file).subscribe({
      next: (response) => {
        this.uploading.set(false);
        this.parsedResult.set(response.parsed);
        this.warnings.set(response.warnings);
        this.applyParseResult(response.parsed);
      },
      error: (error: HttpErrorResponse) => {
        this.uploading.set(false);
        this.errorMessage.set(this.resolveErrorMessage(error));
      },
    });
  }

  private applyParseResult(parsed: ParsedCvProfile): void {
    // R13/KTD12: `summary` ist bewusst nicht Teil des Konfliktchecks (siehe
    // `ImportSectionKey`) - wird bei jedem Import direkt übernommen.
    this.summaryControl.setValue(parsed.summary ?? '');

    const allKeys: ImportSectionKey[] = ['experiences_json', 'education_json', 'skills_json', 'projects_json'];
    const conflicts = allKeys
      .filter((key) => !sectionsEqual(this.currentSectionValue(key), this.savedSectionValue(key)))
      .map((key) => ({ key, label: SECTION_LABELS[key] }));

    if (conflicts.length === 0) {
      this.applySections(parsed, allKeys);
      this.pendingParse = null;
      this.conflicts.set([]);
      return;
    }

    this.pendingParse = parsed;
    this.conflicts.set(conflicts);
  }

  private applySections(parsed: ParsedCvProfile, keys: ImportSectionKey[]): void {
    if (keys.includes('experiences_json')) {
      this.replaceArray(this.experiencesArray, parsed.experiences, (entry) =>
        createExperienceGroup(this.formBuilder, entry),
      );
    }
    if (keys.includes('education_json')) {
      this.replaceArray(this.educationArray, parsed.education, (entry) =>
        createEducationGroup(this.formBuilder, entry),
      );
    }
    if (keys.includes('skills_json')) {
      const skillEntries: SkillEntry[] = parsed.skills.map((name) => ({ name, level: IMPORTED_SKILL_LEVEL }));
      this.replaceArray(this.skillsArray, skillEntries, (entry) => createSkillGroup(this.formBuilder, entry));
    }
    if (keys.includes('projects_json')) {
      this.replaceArray(this.projectsArray, parsed.projects, (entry) => createProjectGroup(this.formBuilder, entry));
    }
  }

  private replaceArray<T>(array: FormArray<FormGroup>, entries: T[], factory: (entry: T) => FormGroup): void {
    array.clear();
    entries.forEach((entry) => array.push(factory(entry)));
  }

  private currentSectionValue(key: ImportSectionKey): unknown {
    switch (key) {
      case 'experiences_json':
        return this.experiencesArray.getRawValue();
      case 'education_json':
        return this.educationArray.getRawValue();
      case 'skills_json':
        return this.skillsArray.getRawValue();
      case 'projects_json':
        return this.projectsArray.getRawValue();
    }
  }

  private savedSectionValue(key: ImportSectionKey): unknown {
    return this.lastSavedProfile ? this.lastSavedProfile[key] : [];
  }

  private resolveErrorMessage(error: HttpErrorResponse): string {
    const detail = typeof error.error?.detail === 'string' ? (error.error.detail as string) : null;
    if (error.status === 502) {
      return (
        detail ??
        'Der Lebenslauf konnte nicht automatisch analysiert werden (KI-Dienst nicht erreichbar). Bitte später erneut versuchen.'
      );
    }
    return detail ?? 'Der Import ist fehlgeschlagen. Bitte die Datei prüfen und erneut versuchen.';
  }
}
