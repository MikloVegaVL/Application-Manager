import { ChangeDetectionStrategy, Component, inject, signal } from '@angular/core';
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

import { JobOffer } from '../../core/models/job-offer.model';
import { JobService } from '../../core/services/job.service';

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

  protected readonly searchForm = this.formBuilder.nonNullable.group({
    keywords: ['', [Validators.required, Validators.minLength(2)]],
    location: [''],
  });

  protected readonly results = signal<JobOffer[]>([]);
  protected readonly loading = signal(false);
  protected readonly hasSearched = signal(false);
  protected readonly errorMessage = signal<string | null>(null);

  /** Merkt sich bereits gespeicherte Jobs (source_url -> DB-ID), um Doppel-Saves zu vermeiden. */
  private readonly savedJobIds = signal<Map<string, number>>(new Map());
  protected readonly savingSourceUrl = signal<string | null>(null);
  protected readonly generatingSourceUrl = signal<string | null>(null);

  onSearch(): void {
    if (this.searchForm.invalid) {
      this.searchForm.markAllAsTouched();
      return;
    }

    const { keywords, location } = this.searchForm.getRawValue();
    this.loading.set(true);
    this.errorMessage.set(null);
    this.hasSearched.set(true);

    this.jobService.searchJobs(keywords.trim(), location.trim() || undefined).subscribe({
      next: (offers) => {
        this.results.set(offers);
        this.loading.set(false);
      },
      error: (error: HttpErrorResponse) => {
        console.error('Jobsuche fehlgeschlagen', error);
        this.results.set([]);
        this.loading.set(false);
        this.errorMessage.set('Die Jobsuche ist fehlgeschlagen. Bitte versuche es später erneut.');
      },
    });
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
        this.cacheSavedJob(job.source_url, saved.id);
        this.savingSourceUrl.set(null);
        this.snackBar.open(`"${job.title}" wurde gespeichert.`, 'OK', { duration: 3000 });
      },
      error: (error: HttpErrorResponse) => {
        this.savingSourceUrl.set(null);
        const message =
          error.status === 409
            ? 'Dieser Job wurde bereits gespeichert.'
            : 'Job konnte nicht gespeichert werden.';
        this.snackBar.open(message, 'OK', { duration: 3000 });
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
        this.cacheSavedJob(job.source_url, saved.id);
        this.generatingSourceUrl.set(null);
        this.navigateToEditor(saved.id);
      },
      error: (error: HttpErrorResponse) => {
        this.generatingSourceUrl.set(null);
        const message =
          error.status === 409
            ? 'Dieser Job wurde bereits gespeichert - bitte über "Bewerbungen" öffnen.'
            : 'Bewerbung konnte nicht gestartet werden.';
        this.snackBar.open(message, 'OK', { duration: 4000 });
      },
    });
  }

  private cacheSavedJob(sourceUrl: string, id: number): void {
    const updated = new Map(this.savedJobIds());
    updated.set(sourceUrl, id);
    this.savedJobIds.set(updated);
  }

  private navigateToEditor(jobOfferId: number): void {
    void this.router.navigate(['/editor', jobOfferId]);
  }
}
