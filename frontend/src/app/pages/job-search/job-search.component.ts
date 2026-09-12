import { ChangeDetectionStrategy, Component, computed, inject, signal } from '@angular/core';
import { HttpErrorResponse } from '@angular/common/http';
import { FormBuilder, ReactiveFormsModule, Validators } from '@angular/forms';
import { Router } from '@angular/router';

import { MatButtonModule } from '@angular/material/button';
import { MatCardModule } from '@angular/material/card';
import { MatChipsModule } from '@angular/material/chips';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatIconModule } from '@angular/material/icon';
import { MatInputModule } from '@angular/material/input';
import { MatProgressSpinnerModule } from '@angular/material/progress-spinner';
import { MatSnackBar } from '@angular/material/snack-bar';

import { TranslatePipe } from '../../core/i18n/translate.pipe';
import { JobOffer, JobSaveConflictDetail } from '../../core/models/job-offer.model';
import { JobSearchStateService } from '../../core/services/job-search-state.service';
import { JobService } from '../../core/services/job.service';
import { TranslationService } from '../../core/services/translation.service';

@Component({
  selector: 'app-job-search',
  standalone: true,
  imports: [
    ReactiveFormsModule,
    MatButtonModule,
    MatCardModule,
    MatChipsModule,
    MatFormFieldModule,
    MatIconModule,
    MatInputModule,
    MatProgressSpinnerModule,
    TranslatePipe,
  ],
  templateUrl: './job-search.component.html',
  styleUrl: './job-search.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class JobSearchComponent {
  private readonly formBuilder = inject(FormBuilder);
  private readonly jobService = inject(JobService);
  private readonly router = inject(Router);
  private readonly snackBar = inject(MatSnackBar);
  protected readonly i18n = inject(TranslationService);
  /** Hält Trefferliste/Status über die Komponenten-Lebensdauer hinaus am
   * Leben, damit ein Zurücknavigieren (z. B. aus dem Editor) die letzte
   * Suche nicht verwirft - siehe JobSearchStateService-Doc. */
  private readonly state = inject(JobSearchStateService);

  protected readonly searchForm = this.formBuilder.nonNullable.group({
    keywords: [this.state.keywords(), [Validators.required, Validators.minLength(2)]],
    location: [this.state.location()],
  });

  protected readonly results = this.state.results;
  /** Status pro Quelle (Arbeitsagentur/LinkedIn/Xing) der letzten Suche - siehe R5. */
  protected readonly sourceStatuses = this.state.sourceStatuses;
  protected readonly loading = signal(false);
  protected readonly hasSearched = this.state.hasSearched;
  protected readonly errorMessage = this.state.errorMessage;

  protected readonly unavailableSources = computed(() =>
    this.sourceStatuses().filter((source) => source.status === 'unavailable'),
  );

  /** Aktuell als Filter gewählte Quellen-Plattformen; leer = alle Treffer anzeigen. */
  protected readonly selectedSources = signal<string[]>([]);

  protected readonly hasActiveSourceFilter = computed(() => this.selectedSources().length > 0);

  /** Auf die gewählten Quellen reduzierte Trefferliste (rein clientseitig,
   * `results` bleibt vollständig - vgl. den Status-Filter der Bewerbungen). */
  protected readonly filteredResults = computed(() => {
    const selected = this.selectedSources();
    if (selected.length === 0) {
      return this.results();
    }
    return this.results().filter((job) => selected.includes(job.source_platform));
  });

  /** True, wenn jede abgefragte Quelle in der letzten Suche unavailable war -
   * dann ist eine leere Ergebnisliste kein "falscher Suchbegriff", sondern
   * ein Erreichbarkeitsproblem (siehe Design-Review zu U7). */
  protected readonly allSourcesUnavailable = computed(
    () => this.sourceStatuses().length > 0 && this.unavailableSources().length === this.sourceStatuses().length,
  );

  private static readonly SOURCE_LABELS: Record<string, string> = {
    arbeitsagentur: 'Arbeitsagentur',
    linkedin: 'LinkedIn',
    xing: 'Xing',
    adzuna: 'Adzuna',
    jooble: 'Jooble',
    devjobs: 'DEVjobs.de',
    kimeta: 'Kimeta',
    stepstone: 'Stepstone',
    germantechjobs: 'GermanTechJobs',
    indeed: 'Indeed',
    programmiererjobboerse: 'Programmiererjobboerse.de',
    'it-entwickler-jobs': 'IT-Entwickler-Jobs.de',
  };

  private readonly savedJobIds = this.state.savedJobIds;
  protected readonly savingSourceUrl = signal<string | null>(null);
  protected readonly generatingSourceUrl = signal<string | null>(null);

  onSearch(): void {
    if (this.searchForm.invalid) {
      this.searchForm.markAllAsTouched();
      return;
    }

    const { keywords, location } = this.searchForm.getRawValue();
    this.state.keywords.set(keywords);
    this.state.location.set(location);
    this.loading.set(true);
    this.errorMessage.set(null);
    // Status der vorherigen Suche zurücksetzen - sonst könnte z. B. noch
    // "LinkedIn nicht verfügbar" von der letzten Suche angezeigt werden,
    // während die neue Suche noch läuft.
    this.sourceStatuses.set([]);
    // Ein Quellen-Filter der letzten Suche passt nicht zu den neuen Quellen.
    this.selectedSources.set([]);
    this.hasSearched.set(true);

    this.jobService.searchJobs(keywords.trim(), location.trim() || undefined).subscribe({
      next: (response) => {
        this.results.set(response.results);
        this.sourceStatuses.set(response.sources);
        this.loading.set(false);
      },
      error: (error: HttpErrorResponse) => {
        console.error('Jobsuche fehlgeschlagen', error);
        this.results.set([]);
        this.sourceStatuses.set([]);
        this.loading.set(false);
        this.errorMessage.set(this.i18n.translate('jobSearch.error'));
      },
    });
  }

  /** Leert die angezeigte Trefferliste, um Platz für eine neue Suche zu
   * schaffen - lässt Suchbegriff/Ort im Formular unangetastet, damit man
   * dieselbe Suche leicht abwandeln kann. */
  onClearResults(): void {
    this.selectedSources.set([]);
    this.state.clearResults();
  }

  /** Übernimmt die im Quellen-Chip-Listbox gewählten Plattformen
   * (Mehrfachauswahl; leere Auswahl = alle Treffer). */
  onSourceFilterChange(selected: string[] | string | null): void {
    this.selectedSources.set(Array.isArray(selected) ? selected : selected ? [selected] : []);
  }

  clearSourceFilter(): void {
    this.selectedSources.set([]);
  }

  /** Menschenlesbares Label für einen Quellen-Platform-Key (z. B. "linkedin" -> "LinkedIn"). */
  sourceLabel(platform: string): string {
    return JobSearchComponent.SOURCE_LABELS[platform] ?? platform;
  }

  isSaved(job: JobOffer): boolean {
    return this.savedJobIds().has(job.source_url);
  }

  isSaving(job: JobOffer): boolean {
    return this.savingSourceUrl() === job.source_url;
  }

  isGenerating(job: JobOffer): boolean {
    return this.generatingSourceUrl() === job.source_url;
  }

  onSaveJob(job: JobOffer): void {
    if (this.isSaved(job) || this.isSaving(job)) {
      return;
    }
    this.savingSourceUrl.set(job.source_url);

    this.jobService.saveJob(job).subscribe({
      next: (saved) => {
        this.state.cacheSavedJob(job.source_url, saved.id);
        this.savingSourceUrl.set(null);
        this.snackBar.open(
          this.i18n.translate('jobSearch.snackbar.saved', { title: job.title }),
          this.i18n.translate('common.ok'),
          { duration: 3000 },
        );
      },
      error: (error: HttpErrorResponse) => {
        this.savingSourceUrl.set(null);
        const conflictId = this.conflictJobOfferId(error);
        if (conflictId !== null) {
          // Job existiert bereits serverseitig (z. B. nach einem Reload,
          // siehe JobSearchStateService) - Cache nachziehen statt nur zu
          // melden, sonst bliebe der Button dauerhaft im "speichern"-Zustand.
          this.state.cacheSavedJob(job.source_url, conflictId);
          this.snackBar.open(
            this.i18n.translate('jobSearch.snackbar.alreadySaved'),
            this.i18n.translate('common.ok'),
            { duration: 3000 },
          );
          return;
        }
        this.snackBar.open(
          this.i18n.translate('jobSearch.snackbar.saveFailed'),
          this.i18n.translate('common.ok'),
          { duration: 3000 },
        );
      },
    });
  }

  /** Speichert den Job (falls nötig) und leitet zur Editor-Komponente mit der Job-ID weiter. */
  onGenerateApplication(job: JobOffer): void {
    const cachedId = this.savedJobIds().get(job.source_url);
    if (cachedId !== undefined) {
      this.navigateToEditor(cachedId);
      return;
    }
    if (this.isGenerating(job)) {
      return;
    }
    this.generatingSourceUrl.set(job.source_url);

    this.jobService.saveJob(job).subscribe({
      next: (saved) => {
        this.state.cacheSavedJob(job.source_url, saved.id);
        this.generatingSourceUrl.set(null);
        this.navigateToEditor(saved.id);
      },
      error: (error: HttpErrorResponse) => {
        this.generatingSourceUrl.set(null);
        const conflictId = this.conflictJobOfferId(error);
        if (conflictId !== null) {
          // Job existiert bereits (z. B. aus einer früheren Session) - statt
          // in einer Sackgasse zu enden, direkt zum bestehenden Editor
          // weiterleiten (ce-debug-Fix, 2026-08-24: der Job tauchte vorher
          // nirgends mehr auf, siehe der `save_job`-Backfill im Backend).
          this.state.cacheSavedJob(job.source_url, conflictId);
          this.navigateToEditor(conflictId);
          return;
        }
        this.snackBar.open(
          this.i18n.translate('jobSearch.snackbar.generateFailed'),
          this.i18n.translate('common.ok'),
          { duration: 4000 },
        );
      },
    });
  }

  private navigateToEditor(jobOfferId: number): void {
    void this.router.navigate(['/editor', jobOfferId]);
  }

  /** Liest `job_offer_id` aus dem 409-Detail von `POST /jobs/save` (siehe
   * `JobSaveConflictDetail` und das Backend-Backfill in `save_job`) -
   * `null`, wenn der Fehler kein solcher Konflikt war. */
  private conflictJobOfferId(error: HttpErrorResponse): number | null {
    if (error.status !== 409) {
      return null;
    }
    const detail = error.error?.detail as JobSaveConflictDetail | undefined;
    return typeof detail?.job_offer_id === 'number' ? detail.job_offer_id : null;
  }
}
