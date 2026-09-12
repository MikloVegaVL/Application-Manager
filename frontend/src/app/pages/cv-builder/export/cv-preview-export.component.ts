import { ChangeDetectionStrategy, Component, Input, OnDestroy, OnInit, inject, signal } from '@angular/core';
import { HttpErrorResponse } from '@angular/common/http';
import { FormArray, FormControl, FormGroup, ReactiveFormsModule } from '@angular/forms';
import { DomSanitizer, SafeResourceUrl } from '@angular/platform-browser';

import { MatButtonModule } from '@angular/material/button';
import { MatButtonToggleModule } from '@angular/material/button-toggle';
import { MatIconModule } from '@angular/material/icon';
import { MatProgressSpinnerModule } from '@angular/material/progress-spinner';

import {
  CvRenderPayload,
  CvTemplate,
  EducationEntry,
  ExperienceEntry,
  LanguageEntry,
  ProjectEntry,
  SkillEntry,
} from '../../../core/models/master-profile.model';
import { ProfileService } from '../../../core/services/profile.service';

const DEFAULT_EXPORT_FILENAME = 'lebenslauf.pdf';

/**
 * Vorschau & Export-Sektion des CV Builders (R9-R11, U9).
 *
 * KTD1: die Vorschau nutzt dieselbe PDF-Rendering-Pipeline wie der Export
 * (`POST /cv-builder/preview` bzw. `.../export`, siehe `cv_builder.py`), rendert
 * aber im `preview`-Modus (Beispiel-Skeleton) - das Ergebnis wird per
 * Browser-nativem `<embed>` angezeigt, nicht als separates Live-HTML/CSS-
 * Preview-Template nachgebaut.
 *
 * KTD11: Preview/Export senden den AKTUELLEN Formularinhalt (inkl. etwaiger
 * noch nicht gespeicherter Änderungen) als Request-Body - die vom
 * Eltern-`CvBuilderComponent` übergebenen FormArray/FormControl-Referenzen
 * werden bei jedem Klick per `getRawValue()`/`.value` frisch gelesen, nie aus
 * `lastSavedProfile`.
 *
 * KTD10: `templateIdControl` ist dieselbe FormControl-Instanz, die die
 * Elternform auch in den Save-Payload (`PATCH /profile`) übernimmt - die
 * gewählte Vorlage ist so Teil des persistierten Profils. Ist beim Laden der
 * Vorlagenliste keine Vorlage gewählt (Wert `null`, z. B. bei einem frisch
 * angelegten Profil) oder eine unbekannte (z. B. das entfernte `modern`), wird
 * automatisch die erste verfügbare Vorlage vorbelegt.
 */
@Component({
  selector: 'app-cv-preview-export',
  standalone: true,
  imports: [ReactiveFormsModule, MatButtonModule, MatButtonToggleModule, MatIconModule, MatProgressSpinnerModule],
  template: `
    <section class="cv-preview-export">
      <h3>Vorschau & Export</h3>
      <p>
        Wähle eine Vorlage und erzeuge eine Vorschau oder einen PDF-Download - basierend auf dem aktuellen
        Formularinhalt, auch wenn er noch nicht gespeichert wurde.
      </p>

      @if (templatesLoading()) {
        <div class="cv-preview-export__templates-loading">
          <mat-progress-spinner mode="indeterminate" diameter="24" />
          <p>Vorlagen werden geladen ...</p>
        </div>
      } @else if (templatesError()) {
        <div class="cv-preview-export__error">
          <p>{{ templatesError() }}</p>
          <button mat-stroked-button type="button" (click)="loadTemplates()">Erneut versuchen</button>
        </div>
      } @else {
        <mat-button-toggle-group [formControl]="templateIdControl" aria-label="Vorlage wählen">
          @for (template of templates(); track template.id) {
            <mat-button-toggle [value]="template.id">{{ template.label }}</mat-button-toggle>
          }
        </mat-button-toggle-group>
      }

      <div class="cv-preview-export__actions">
        <button
          mat-flat-button
          color="primary"
          type="button"
          [disabled]="!canRender() || previewLoading()"
          (click)="preview()"
        >
          @if (previewLoading()) {
            <mat-progress-spinner mode="indeterminate" diameter="18" />
          } @else {
            <mat-icon>visibility</mat-icon>
          }
          Vorschau
        </button>
        <button
          mat-stroked-button
          type="button"
          [disabled]="!canRender() || exporting()"
          (click)="export()"
        >
          @if (exporting()) {
            <mat-progress-spinner mode="indeterminate" diameter="18" />
          } @else {
            <mat-icon>download</mat-icon>
          }
          Als PDF exportieren
        </button>
      </div>

      @if (previewError(); as message) {
        <p class="cv-preview-export__error-message">{{ message }}</p>
      }
      @if (exportError(); as message) {
        <p class="cv-preview-export__error-message">{{ message }}</p>
      }

      @if (previewUrl(); as url) {
        <embed [src]="url" type="application/pdf" class="cv-preview-export__embed" />
      }
    </section>
  `,
  styles: `
    .cv-preview-export {
      display: flex;
      flex-direction: column;
      gap: 16px;

      h3 {
        margin: 0;
      }

      &__templates-loading {
        display: flex;
        align-items: center;
        gap: 8px;

        p {
          margin: 0;
        }
      }

      &__actions {
        display: flex;
        gap: 12px;

        mat-progress-spinner {
          display: inline-block;
          margin-right: 4px;
        }
      }

      &__error p,
      &__error-message {
        color: #b3261e;
        margin: 0;
      }

      &__embed {
        width: 100%;
        height: 800px;
        border: 1px solid rgba(0, 0, 0, 0.12);
        border-radius: 4px;
      }
    }
  `,
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class CvPreviewExportComponent implements OnInit, OnDestroy {
  private readonly profileService = inject(ProfileService);
  private readonly sanitizer = inject(DomSanitizer);

  @Input({ required: true }) summaryControl!: FormControl<string>;
  @Input({ required: true }) berufsbezeichnungControl!: FormControl<string>;
  @Input({ required: true }) experiencesArray!: FormArray<FormGroup>;
  @Input({ required: true }) educationArray!: FormArray<FormGroup>;
  @Input({ required: true }) skillsArray!: FormArray<FormGroup>;
  @Input({ required: true }) languagesArray!: FormArray<FormGroup>;
  @Input({ required: true }) projectsArray!: FormArray<FormGroup>;
  /** Von der Elternform gehaltene FormControl (KTD8) - round-tripped über `save()`/`PATCH /profile`. */
  @Input({ required: true }) templateIdControl!: FormControl<string | null>;

  protected readonly templates = signal<CvTemplate[]>([]);
  protected readonly templatesLoading = signal(true);
  protected readonly templatesError = signal<string | null>(null);

  protected readonly previewLoading = signal(false);
  protected readonly previewError = signal<string | null>(null);
  protected readonly previewUrl = signal<SafeResourceUrl | null>(null);

  protected readonly exporting = signal(false);
  protected readonly exportError = signal<string | null>(null);

  private currentObjectUrl: string | null = null;

  ngOnInit(): void {
    this.loadTemplates();
  }

  ngOnDestroy(): void {
    this.revokePreviewUrl();
  }

  protected canRender(): boolean {
    return !this.templatesError() && this.isKnownTemplate(this.templateIdControl.value);
  }

  /** KTD10: nur eine tatsächlich geladene Vorlage ist renderbar. */
  private isKnownTemplate(id: string | null): boolean {
    return id !== null && this.templates().some((template) => template.id === id);
  }

  loadTemplates(): void {
    this.templatesLoading.set(true);
    this.templatesError.set(null);
    this.profileService.getTemplates().subscribe({
      next: (templates) => {
        this.templatesLoading.set(false);
        this.templates.set(templates);
        // KTD10: gespeicherte Vorlage auf eine bekannte ID normalisieren - die
        // erste verfügbare vorbelegen, wenn keine (oder eine unbekannte, z. B.
        // das entfernte `modern`) gewählt war.
        if (!this.isKnownTemplate(this.templateIdControl.value) && templates.length > 0) {
          this.templateIdControl.setValue(templates[0].id);
        }
      },
      error: () => {
        this.templatesLoading.set(false);
        this.templatesError.set('Vorlagen konnten nicht geladen werden.');
      },
    });
  }

  protected preview(): void {
    const payload = this.buildPayload();
    if (!payload || this.previewLoading()) {
      return;
    }

    this.previewLoading.set(true);
    this.previewError.set(null);
    this.profileService.previewCv(payload).subscribe({
      next: (response) => {
        this.previewLoading.set(false);
        this.revokePreviewUrl();
        const blob = response.body;
        if (!blob) {
          this.previewUrl.set(null);
          this.previewError.set('Vorschau konnte nicht geladen werden.');
          return;
        }
        const objectUrl = URL.createObjectURL(blob);
        this.currentObjectUrl = objectUrl;
        this.previewUrl.set(this.sanitizer.bypassSecurityTrustResourceUrl(objectUrl));
      },
      error: (error: HttpErrorResponse) => {
        this.previewLoading.set(false);
        this.revokePreviewUrl();
        this.previewUrl.set(null);
        this.previewError.set(this.resolveErrorMessage(error));
      },
    });
  }

  protected export(): void {
    const payload = this.buildPayload();
    if (!payload || this.exporting()) {
      return;
    }

    this.exporting.set(true);
    this.exportError.set(null);
    this.profileService.exportCv(payload).subscribe({
      next: (response) => {
        this.exporting.set(false);
        const blob = response.body;
        if (!blob) {
          this.exportError.set('Export fehlgeschlagen. Bitte erneut versuchen.');
          return;
        }
        this.triggerDownload(blob, this.resolveFilename(response.headers.get('Content-Disposition')));
      },
      error: (error: HttpErrorResponse) => {
        this.exporting.set(false);
        this.exportError.set(this.resolveErrorMessage(error));
      },
    });
  }

  private buildPayload(): CvRenderPayload | null {
    const templateId = this.templateIdControl.value;
    if (!templateId) {
      return null;
    }

    return {
      template_id: templateId,
      summary: this.summaryControl.value,
      berufsbezeichnung: this.berufsbezeichnungControl.value,
      experiences_json: this.experiencesArray.getRawValue() as ExperienceEntry[],
      education_json: this.educationArray.getRawValue() as EducationEntry[],
      skills_json: this.skillsArray.getRawValue() as SkillEntry[],
      languages_json: this.languagesArray.getRawValue() as LanguageEntry[],
      projects_json: this.projectsArray.getRawValue() as ProjectEntry[],
    };
  }

  private triggerDownload(blob: Blob, filename: string): void {
    const objectUrl = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = objectUrl;
    link.download = filename;
    link.click();
    URL.revokeObjectURL(objectUrl);
  }

  private resolveFilename(contentDisposition: string | null): string {
    if (!contentDisposition) {
      return DEFAULT_EXPORT_FILENAME;
    }
    const match = /filename="?([^";]+)"?/.exec(contentDisposition);
    return match?.[1] ?? DEFAULT_EXPORT_FILENAME;
  }

  private resolveErrorMessage(error: HttpErrorResponse): string {
    switch (error.status) {
      case 404:
        return 'Es wurde noch kein Profil angelegt.';
      case 422:
        return 'Die gewählte Vorlage ist ungültig.';
      case 500:
        return 'Der Lebenslauf konnte nicht als PDF erzeugt werden.';
      default:
        return 'Etwas ist schiefgelaufen. Bitte erneut versuchen.';
    }
  }

  private revokePreviewUrl(): void {
    if (this.currentObjectUrl) {
      URL.revokeObjectURL(this.currentObjectUrl);
      this.currentObjectUrl = null;
    }
  }
}
