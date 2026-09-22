import { ChangeDetectionStrategy, Component, OnInit, computed, inject, signal } from '@angular/core';
import { HttpErrorResponse } from '@angular/common/http';
import { Router } from '@angular/router';

import { MatButtonModule } from '@angular/material/button';
import { MatDialog } from '@angular/material/dialog';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatIconModule } from '@angular/material/icon';
import { MatInputModule } from '@angular/material/input';
import { MatProgressSpinnerModule } from '@angular/material/progress-spinner';
import { MatRadioModule } from '@angular/material/radio';
import { MatSnackBar } from '@angular/material/snack-bar';

import { Application, ApplicationStatus } from '../../core/models/application.model';
import { JobOffer } from '../../core/models/job-offer.model';
import { ApplicationService } from '../../core/services/application.service';
import { JobService, jobSaveConflictId } from '../../core/services/job.service';
import { sourceLabel as getSourceLabel } from '../../core/utils/source-label.util';
import {
  CompactCardComponent,
  CompactCardDetailRowItem,
  CompactCardMenuItem,
  CompactCardViewModel,
} from '../../shared/compact-card/compact-card.component';
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
    CompactCardComponent,
    MatButtonModule,
    MatFormFieldModule,
    MatIconModule,
    MatInputModule,
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

  /** localStorage-Schlüssel des einmaligen Extension-Installationshinweises (R17/KTD9) - die App kann
   * nicht erkennen, ob die Erweiterung installiert ist, daher wird der Hinweis einmalig gezeigt und
   * nach dem Wegklicken dauerhaft unterdrückt. */
  private static readonly INSTALL_HINT_STORAGE_KEY = 'applications.extension-install-hint-dismissed';

  protected readonly applications = signal<Application[]>([]);
  protected readonly loading = signal(true);
  protected readonly errorMessage = signal<string | null>(null);
  /** ID der Bewerbung, die gerade gelöscht wird (max. eine gleichzeitig - steuert Spinner/Disabled je Karte). */
  protected readonly deletingId = signal<number | null>(null);
  /** ID der Bewerbung, deren Status gerade per PUT gespeichert wird. */
  protected readonly updatingStatusId = signal<number | null>(null);
  /** True während ein manuell erfasstes Stellenangebot gespeichert wird (Dialog bereits geschlossen). */
  protected readonly savingNewJobOffer = signal(false);
  /** ID der Bewerbung, für die gerade ein Fill-Request läuft (busy-id-Muster wie `deletingId`). */
  protected readonly fillRequestingId = signal<number | null>(null);
  /** Aktiver Status-Filter; `all` zeigt jede Bewerbung. */
  protected readonly filter = signal<ApplicationFilter>('all');
  /** Freitextsuche über Jobtitel/Firma (rein clientseitig, kombiniert per AND mit `filter`). */
  protected readonly searchTerm = signal('');

  /** Ob der Installationshinweis bereits weggeklickt wurde (persistiert in localStorage). */
  private readonly installHintDismissed = signal(this.readInstallHintDismissed());

  /** Einmaliger Installationshinweis - nur solange er nicht weggeklickt wurde UND es mindestens eine
   * LinkedIn-Bewerbung ohne gemeldete Submission gibt, für die der Trigger sichtbar wäre (R17/KTD9). */
  protected readonly showInstallHint = computed(
    () =>
      !this.installHintDismissed() &&
      this.applications().some((application) => this.canApplyViaLinkedIn(application)),
  );

  /** Nach Status und Suchbegriff reduzierte Liste (rein clientseitig, `applications` bleibt vollständig). */
  protected readonly filteredApplications = computed(() => {
    const filter = this.filter();
    const term = this.searchTerm();
    const byStatus =
      filter === 'all' ? this.applications() : this.applications().filter((application) => application.status === filter);
    return byStatus.filter((application) => this.matchesSearch(application, term));
  });

  /** Case-insensitive Teilstring-Treffer auf Jobtitel oder Firma (R1); ein leerer Suchbegriff trifft immer. */
  private matchesSearch(application: Application, term: string): boolean {
    const needle = term.trim().toLowerCase();
    if (!needle) {
      return true;
    }
    return (
      application.job_offer.title.toLowerCase().includes(needle) ||
      application.job_offer.company.toLowerCase().includes(needle)
    );
  }

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

  // --- Apply via LinkedIn (U4) ------------------------------------------

  /** Der Trigger ist nur für eine LinkedIn-Bewerbung ohne bereits gemeldete Submission sichtbar (R1/R2,
   * R11) - sobald eine Submission vorliegt, wird stattdessen das "Applied"-Indiz gezeigt. */
  protected canApplyViaLinkedIn(application: Application): boolean {
    return application.job_offer.source_platform === 'linkedin' && !application.submission;
  }

  /** R1: startet den Fill in der Erweiterung, indem ein Fill-Request angelegt und die gelieferte Job-URL
   * in einem neuen Tab geöffnet wird. `fillRequestingId` sperrt die Karte während des Requests
   * (busy-id-Muster wie `deletingId`). */
  protected onApplyViaLinkedIn(application: Application): void {
    if (this.fillRequestingId() !== null) {
      return;
    }

    this.fillRequestingId.set(application.id);
    this.applicationService.requestFill(application.id).subscribe({
      next: ({ job_url }) => {
        this.fillRequestingId.set(null);
        window.open(job_url, '_blank', 'noopener,noreferrer');
      },
      error: (error: HttpErrorResponse) => {
        this.fillRequestingId.set(null);
        const message =
          (error.error?.detail as string | undefined) ?? 'The application could not be started.';
        this.snackBar.open(message, 'OK', { duration: 4000 });
      },
    });
  }

  protected onDismissInstallHint(): void {
    this.installHintDismissed.set(true);
    try {
      localStorage.setItem(ApplicationsComponent.INSTALL_HINT_STORAGE_KEY, '1');
    } catch {
      // Private-Mode/blocked storage: the in-memory signal still hides the hint for this session.
    }
  }

  private readInstallHintDismissed(): boolean {
    try {
      return localStorage.getItem(ApplicationsComponent.INSTALL_HINT_STORAGE_KEY) === '1';
    } catch {
      return false;
    }
  }

  /** KTD3/R11: menschenlesbares "Applied via <platform> on <date>"-Indiz aus `ApplicationRead.submission`,
   * gespiegelt zum persistenten `sent_to_email`-Indiz in `buildCardViewModel`. */
  protected appliedIndicatorLabel(application: Application): string | null {
    const submission = application.submission;
    if (!submission) {
      return null;
    }
    const platform = submission.platform ? this.sourceLabel(submission.platform) : 'portal';
    const date = new Date(submission.submitted_at).toLocaleDateString();
    return `Applied via ${platform} on ${date}`;
  }

  // --- Compact card -----------------------------------------------------

  /** Memoized per-application view-models for `<app-compact-card>` (R2/R6). A `computed()` keyed
   * by application id - NOT a plain method invoked as `cardViewModel(application)` straight from the
   * `@for` binding, which would build a fresh object every change-detection tick and defeat the
   * child's `OnPush`. */
  private readonly cardViewModelsById = computed(() => {
    const applications = this.filteredApplications();

    const map = new Map<number, CompactCardViewModel>();
    for (const application of applications) {
      map.set(application.id, this.buildCardViewModel(application));
    }
    return map;
  });

  protected cardViewModel(application: Application): CompactCardViewModel {
    return this.cardViewModelsById().get(application.id) ?? this.buildCardViewModel(application);
  }

  /** True while a request this card's primary action or `⋮` menu can trigger is in flight (R12) -
   * "Open application" and "Open ad" are plain navigation links with no async step, so they never
   * contribute. */
  protected isCardBusy(application: Application): boolean {
    return (
      this.deletingId() === application.id ||
      this.updatingStatusId() === application.id ||
      this.fillRequestingId() === application.id
    );
  }

  /** Routes a `(menuItemClick)` id from `<app-compact-card>` to the existing handler - no behavior
   * changes here (R8), only which UI element triggers it. */
  protected onMenuAction(application: Application, itemId: string): void {
    switch (itemId) {
      case 'mark-accepted':
        this.onStatusChange(application, 'accepted');
        break;
      case 'mark-rejected':
        this.onStatusChange(application, 'rejected');
        break;
      case 'apply-via-linkedin':
        this.onApplyViaLinkedIn(application);
        break;
      case 'delete':
        this.onDelete(application);
        break;
    }
  }

  private buildCardViewModel(application: Application): CompactCardViewModel {
    const menuItems: CompactCardMenuItem[] = [
      {
        id: 'open-ad',
        label: 'Open ad',
        icon: 'open_in_new',
        link: { href: application.job_offer.source_url, target: '_blank', rel: 'noopener noreferrer' },
      },
      { id: 'mark-accepted', label: 'Mark accepted', icon: 'check' },
      { id: 'mark-rejected', label: 'Mark rejected', icon: 'close' },
    ];

    if (this.canApplyViaLinkedIn(application)) {
      menuItems.push({ id: 'apply-via-linkedin', label: 'Apply via LinkedIn', icon: 'work' });
    }

    menuItems.push({ id: 'delete', label: 'Delete', icon: 'delete' });

    const detailRowItems: CompactCardDetailRowItem[] = [];
    const appliedIndicator = this.appliedIndicatorLabel(application);
    if (appliedIndicator) {
      detailRowItems.push({ label: appliedIndicator });
    }
    if (application.sent_to_email) {
      detailRowItems.push({ label: `Sent to: ${application.sent_to_email}` });
    }

    return {
      title: application.job_offer.title,
      company: application.job_offer.company,
      location: application.job_offer.location ?? '',
      chips: [
        { label: this.statusLabel(application.status) },
        { label: this.sourceLabel(application.job_offer.source_platform) },
      ],
      primaryAction: {
        label: 'Open application',
        link: { routerLink: ['/editor', application.job_offer.id] },
      },
      menuItems,
      detailRowItems,
    };
  }
}
