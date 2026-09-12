import { ChangeDetectionStrategy, Component, OnInit, computed, inject, signal } from '@angular/core';
import { HttpErrorResponse } from '@angular/common/http';
import { RouterLink } from '@angular/router';

import { MatButtonModule } from '@angular/material/button';
import { MatButtonToggleModule } from '@angular/material/button-toggle';
import { MatCardModule } from '@angular/material/card';
import { MatChipsModule } from '@angular/material/chips';
import { MatIconModule } from '@angular/material/icon';
import { MatProgressSpinnerModule } from '@angular/material/progress-spinner';
import { MatRadioModule } from '@angular/material/radio';
import { MatSnackBar } from '@angular/material/snack-bar';

import { TranslatePipe } from '../../core/i18n/translate.pipe';
import { Application, ApplicationStatus } from '../../core/models/application.model';
import { ApplicationService } from '../../core/services/application.service';
import { TranslationService } from '../../core/services/translation.service';

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
    TranslatePipe,
  ],
  templateUrl: './applications.component.html',
  styleUrl: './applications.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class ApplicationsComponent implements OnInit {
  private readonly applicationService = inject(ApplicationService);
  private readonly snackBar = inject(MatSnackBar);
  protected readonly i18n = inject(TranslationService);

  protected readonly applications = signal<Application[]>([]);
  protected readonly loading = signal(true);
  protected readonly errorMessage = signal<string | null>(null);
  /** ID der Bewerbung, die gerade gelöscht wird (max. eine gleichzeitig - steuert Spinner/Disabled je Karte). */
  protected readonly deletingId = signal<number | null>(null);
  /** ID der Bewerbung, deren Status gerade per PUT gespeichert wird. */
  protected readonly updatingStatusId = signal<number | null>(null);
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

  private static readonly STATUS_LABEL_KEYS: Record<ApplicationStatus, string> = {
    draft: 'applications.status.draft',
    sent: 'applications.status.sent',
    rejected: 'applications.status.rejected',
    accepted: 'applications.status.accepted',
    interview: 'applications.status.interview',
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
        this.errorMessage.set(this.i18n.translate('applications.error'));
      },
    });
  }

  statusLabel(status: ApplicationStatus): string {
    return this.i18n.translate(ApplicationsComponent.STATUS_LABEL_KEYS[status] ?? status);
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
        this.snackBar.open(
          this.i18n.translate('applications.snackbar.statusUpdated'),
          this.i18n.translate('common.ok'),
          { duration: 3000 },
        );
      },
      error: (error: HttpErrorResponse) => {
        this.updatingStatusId.set(null);
        const message =
          (error.error?.detail as string | undefined) ??
          this.i18n.translate('applications.snackbar.statusUpdateFailed');
        this.snackBar.open(message, this.i18n.translate('common.ok'), { duration: 4000 });
      },
    });
  }

  onDelete(application: Application): void {
    if (this.deletingId() !== null) {
      return;
    }
    const confirmed = window.confirm(
      this.i18n.translate('applications.confirmDelete', {
        title: application.job_offer.title,
        company: application.job_offer.company,
      }),
    );
    if (!confirmed) {
      return;
    }

    this.deletingId.set(application.id);
    this.applicationService.deleteById(application.id).subscribe({
      next: () => {
        this.applications.update((applications) => applications.filter((a) => a.id !== application.id));
        this.deletingId.set(null);
        this.snackBar.open(
          this.i18n.translate('applications.snackbar.deleted'),
          this.i18n.translate('common.ok'),
          { duration: 3000 },
        );
      },
      error: (error: HttpErrorResponse) => {
        this.deletingId.set(null);
        const message =
          (error.error?.detail as string | undefined) ??
          this.i18n.translate('applications.snackbar.deleteFailed');
        this.snackBar.open(message, this.i18n.translate('common.ok'), { duration: 4000 });
      },
    });
  }
}
