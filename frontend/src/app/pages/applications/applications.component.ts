import { ChangeDetectionStrategy, Component, OnInit, computed, inject, signal } from '@angular/core';
import { HttpErrorResponse } from '@angular/common/http';
import { Router, RouterLink } from '@angular/router';

import { MatButtonModule } from '@angular/material/button';
import { MatButtonToggleModule } from '@angular/material/button-toggle';
import { MatCardModule } from '@angular/material/card';
import { MatChipsModule } from '@angular/material/chips';
import { MatDialog } from '@angular/material/dialog';
import { MatIconModule } from '@angular/material/icon';
import { MatProgressSpinnerModule } from '@angular/material/progress-spinner';
import { MatRadioModule } from '@angular/material/radio';
import { MatSnackBar } from '@angular/material/snack-bar';

import { Application, ApplicationStatus } from '../../core/models/application.model';
import { JobOffer } from '../../core/models/job-offer.model';
import { ApplicationService } from '../../core/services/application.service';
import { JobService, jobSaveConflictId } from '../../core/services/job.service';
import { sourceLabel as getSourceLabel } from '../../core/utils/source-label.util';
import {
  AddJobOfferDialogComponent,
  AddJobOfferDialogResult,
} from './add-job-offer-dialog/add-job-offer-dialog.component';

/** Auswahl der Status-Filter über der Bewerbungsliste. */
type ApplicationFilter = 'all' | ApplicationStatus;

@Component({
  selector: 'app-applications',
  standalone: true,
  imports: [
    RouterLink,
    MatButtonModule,
    MatButtonToggleModule,
    MatCardModule,
    MatChipsModule,
    MatIconModule,
    MatProgressSpinnerModule,
    MatRadioModule,
  ],
  templateUrl: './applications.component.html',
  styleUrl: './applications.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class ApplicationsComponent implements OnInit {
  private readonly applicationService = inject(ApplicationService);
  private readonly jobService = inject(JobService);
  private readonly dialog = inject(MatDialog);
  private readonly router = inject(Router);
  private readonly snackBar = inject(MatSnackBar);

  protected readonly applications = signal<Application[]>([]);
  protected readonly loading = signal(true);
  protected readonly errorMessage = signal<string | null>(null);
  /** ID der Bewerbung, die gerade gelöscht wird (max. eine gleichzeitig - steuert Spinner/Disabled je Karte). */
  protected readonly deletingId = signal<number | null>(null);
  /** ID der Bewerbung, deren Status gerade per PUT gespeichert wird. */
  protected readonly updatingStatusId = signal<number | null>(null);
  /** True während ein manuell erfasstes Stellenangebot gespeichert wird (Dialog bereits geschlossen). */
  protected readonly savingNewJobOffer = signal(false);
  /** Aktiver Status-Filter; `all` zeigt jede Bewerbung. */
  protected readonly filter = signal<ApplicationFilter>('all');

  /** Nach dem gewählten Filter reduzierte Liste (rein clientseitig, `applications` bleibt vollständig). */
  protected readonly filteredApplications = computed(() => {
    const filter = this.filter();
    if (filter === 'all') {
      return this.applications();
    }
    return this.applications().filter((application) => application.status === filter);
  });

  private static readonly STATUS_LABELS: Record<ApplicationStatus, string> = {
    draft: 'Draft',
    sent: 'Sent',
    rejected: 'Rejection',
    accepted: 'Offer',
    interview: 'Interview',
  };

  ngOnInit(): void {
    this.loadApplications();
  }

  private loadApplications(): void {
    this.loading.set(true);
    this.errorMessage.set(null);

    this.applicationService.list().subscribe({
      next: (applications) => {
        this.applications.set(applications);
        this.loading.set(false);
      },
      error: (error: HttpErrorResponse) => {
        console.error('Bewerbungen konnten nicht geladen werden', error);
        this.applications.set([]);
        this.loading.set(false);
        this.errorMessage.set('The applications could not be loaded. Please try again later.');
      },
    });
  }

  statusLabel(status: ApplicationStatus): string {
    return ApplicationsComponent.STATUS_LABELS[status];
  }

  sourceLabel(platform: string): string {
    return getSourceLabel(platform);
  }

  onFilterChange(filter: ApplicationFilter): void {
    this.filter.set(filter);
  }

  isDeleting(application: Application): boolean {
    return this.deletingId() === application.id;
  }

  isUpdatingStatus(application: Application): boolean {
    return this.updatingStatusId() === application.id;
  }

  /** Speichert eine per selektierbarem Label gewählte Zusage/Absage sofort im Backend. */
  onStatusChange(application: Application, status: ApplicationStatus | null | undefined): void {
    if (status !== 'accepted' && status !== 'rejected') {
      return;
    }
    if (application.status === status || this.updatingStatusId() !== null) {
      return;
    }

    this.updatingStatusId.set(application.id);
    this.applicationService.update(application.id, { status }).subscribe({
      next: (updated) => {
        this.applications.update((applications) =>
          applications.map((item) => (item.id === updated.id ? updated : item)),
        );
        this.updatingStatusId.set(null);
        this.snackBar.open('Status was updated.', 'OK', { duration: 3000 });
      },
      error: (error: HttpErrorResponse) => {
        this.updatingStatusId.set(null);
        const message =
          (error.error?.detail as string | undefined) ?? 'The status could not be updated.';
        this.snackBar.open(message, 'OK', { duration: 4000 });
      },
    });
  }

  onDelete(application: Application): void {
    if (this.deletingId() !== null) {
      return;
    }
    const confirmed = window.confirm(
      `Permanently delete application "${application.job_offer.title}" at ${application.job_offer.company}?`,
    );
    if (!confirmed) {
      return;
    }

    this.deletingId.set(application.id);
    this.applicationService.deleteById(application.id).subscribe({
      next: () => {
        this.applications.update((applications) => applications.filter((a) => a.id !== application.id));
        this.deletingId.set(null);
        this.snackBar.open('Application was deleted.', 'OK', { duration: 3000 });
      },
      error: (error: HttpErrorResponse) => {
        this.deletingId.set(null);
        const message =
          (error.error?.detail as string | undefined) ?? 'The application could not be deleted.';
        this.snackBar.open(message, 'OK', { duration: 4000 });
      },
    });
  }

  /** Öffnet den Dialog für ein direkt gefundenes Stellenangebot (R1); der
   * Dialog liefert nur Formulardaten zurück (KTD3), gespeichert wird erst
   * danach hier. */
  onAddJobOffer(): void {
    if (this.savingNewJobOffer()) {
      return;
    }

    const dialogRef = this.dialog.open(AddJobOfferDialogComponent, { width: '520px' });
    dialogRef.afterClosed().subscribe((result?: AddJobOfferDialogResult) => {
      if (!result) {
        return;
      }
      this.saveManualJobOffer(result);
    });
  }

  /** Speichert das manuell erfasste Stellenangebot über den bestehenden
   * Job-Save-Flow (KTD2, wie `JobSearchComponent.onGenerateApplication`) und
   * navigiert direkt in den Editor - bei einem 409-Konflikt stattdessen in
   * die bereits bestehende Bewerbung (R6). */
  private saveManualJobOffer(result: AddJobOfferDialogResult): void {
    this.savingNewJobOffer.set(true);

    const payload: JobOffer = {
      title: result.title,
      company: result.company,
      location: null,
      source_url: result.source_url,
      description_text: result.description_text || null,
      source_platform: 'manual',
      application_email: result.application_email || null,
      application_email_source_url: null,
    };

    this.jobService.saveJob(payload).subscribe({
      next: (saved) => {
        this.savingNewJobOffer.set(false);
        void this.router.navigate(['/editor', saved.id]);
      },
      error: (error: HttpErrorResponse) => {
        this.savingNewJobOffer.set(false);
        const conflictId = jobSaveConflictId(error);
        if (conflictId !== null) {
          this.snackBar.open('This job offer was already saved - opening it now.', 'OK', {
            duration: 4000,
          });
          void this.router.navigate(['/editor', conflictId]);
          return;
        }
        this.snackBar.open('The job offer could not be saved.', 'OK', { duration: 4000 });
      },
    });
  }
}
