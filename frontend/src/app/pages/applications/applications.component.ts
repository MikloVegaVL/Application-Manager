import { ChangeDetectionStrategy, Component, OnInit, inject, signal } from '@angular/core';
import { HttpErrorResponse } from '@angular/common/http';
import { RouterLink } from '@angular/router';

import { MatButtonModule } from '@angular/material/button';
import { MatCardModule } from '@angular/material/card';
import { MatChipsModule } from '@angular/material/chips';
import { MatIconModule } from '@angular/material/icon';
import { MatProgressSpinnerModule } from '@angular/material/progress-spinner';

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

  protected readonly applications = signal<Application[]>([]);
  protected readonly loading = signal(true);
  protected readonly errorMessage = signal<string | null>(null);

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
}
