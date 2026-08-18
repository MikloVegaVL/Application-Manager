import { ChangeDetectionStrategy, Component, OnInit, inject, signal } from '@angular/core';
import { HttpErrorResponse } from '@angular/common/http';
import { RouterLink } from '@angular/router';

import { MatButtonModule } from '@angular/material/button';
import { MatCardModule } from '@angular/material/card';
import { MatChipsModule } from '@angular/material/chips';
import { MatIconModule } from '@angular/material/icon';
import { MatProgressSpinnerModule } from '@angular/material/progress-spinner';
import { MatSnackBar } from '@angular/material/snack-bar';

import { Application, ApplicationStatus } from '../../core/models/application.model';
import { ApplicationService } from '../../core/services/application.service';

@Component({
  selector: 'app-applications',
  standalone: true,
  imports: [RouterLink, MatButtonModule, MatCardModule, MatChipsModule, MatIconModule, MatProgressSpinnerModule],
  templateUrl: './applications.component.html',
  styleUrl: './applications.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class ApplicationsComponent implements OnInit {
  private readonly applicationService = inject(ApplicationService);
  private readonly snackBar = inject(MatSnackBar);

  protected readonly applications = signal<Application[]>([]);
  protected readonly loading = signal(true);
  protected readonly errorMessage = signal<string | null>(null);
  /** ID der Bewerbung, die gerade gelöscht wird (max. eine gleichzeitig - steuert Spinner/Disabled je Karte). */
  protected readonly deletingId = signal<number | null>(null);

  private static readonly STATUS_LABELS: Record<ApplicationStatus, string> = {
    draft: 'Entwurf',
    sent: 'Versendet',
    rejected: 'Abgelehnt',
    interview: 'Vorstellungsgespräch',
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
        this.errorMessage.set('Die Bewerbungen konnten nicht geladen werden. Bitte versuche es später erneut.');
      },
    });
  }

  statusLabel(status: ApplicationStatus): string {
    return ApplicationsComponent.STATUS_LABELS[status] ?? status;
  }

  isDeleting(application: Application): boolean {
    return this.deletingId() === application.id;
  }

  onDelete(application: Application): void {
    if (this.deletingId() !== null) {
      return;
    }
    const confirmed = window.confirm(
      `Bewerbung "${application.job_offer.title}" bei ${application.job_offer.company} unwiderruflich löschen?`,
    );
    if (!confirmed) {
      return;
    }

    this.deletingId.set(application.id);
    this.applicationService.deleteById(application.id).subscribe({
      next: () => {
        this.applications.update((applications) => applications.filter((a) => a.id !== application.id));
        this.deletingId.set(null);
        this.snackBar.open('Bewerbung wurde gelöscht.', 'OK', { duration: 3000 });
      },
      error: (error: HttpErrorResponse) => {
        this.deletingId.set(null);
        const message =
          (error.error?.detail as string | undefined) ?? 'Bewerbung konnte nicht gelöscht werden.';
        this.snackBar.open(message, 'OK', { duration: 4000 });
      },
    });
  }
}
