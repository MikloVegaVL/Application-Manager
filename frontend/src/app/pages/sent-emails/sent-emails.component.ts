import { ChangeDetectionStrategy, Component, OnInit, inject, signal } from '@angular/core';
import { DatePipe, NgTemplateOutlet } from '@angular/common';
import { HttpErrorResponse } from '@angular/common/http';
import { RouterLink } from '@angular/router';

import { MatButtonModule } from '@angular/material/button';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatIconModule } from '@angular/material/icon';
import { MatInputModule } from '@angular/material/input';
import { MatProgressSpinnerModule } from '@angular/material/progress-spinner';
import { MatSelectModule } from '@angular/material/select';
import { MatSnackBar } from '@angular/material/snack-bar';
import { MatTableModule } from '@angular/material/table';

import { SENDER_EMAIL_OPTIONS } from '../../core/models/master-profile.model';
import { SentEmail, SentEmailFilterParams } from '../../core/models/sent-email.model';
import { SentEmailService } from '../../core/services/sent-email.service';
import { downloadBlobResponse } from '../../core/utils/download-blob-response.util';
import { sourceLabel } from '../../core/utils/source-label.util';

const DEFAULT_FILTERED_FILENAME = 'sent-emails-filtered.pdf';
const DEFAULT_FULL_LOG_FILENAME = 'sent-emails-full-log.pdf';

/**
 * "Sent Emails"-Übersicht (docs/plans/2026-09-14-001-feat-application-email-
 * log-plan.md): listet jeden protokollierten Bewerbungsmail-Versand,
 * filterbar nach Firma/Absender-Account/Zeitraum (R4/R7), mit Link-through
 * zur Application (R5, sofern noch vorhanden) und PDF-Export der aktuellen
 * Ansicht bzw. des gesamten Protokolls (R8/R9). Kein Resend/Edit - nur
 * Löschen einzelner Log-Einträge ist möglich (kein R6 mehr).
 *
 * KTD4: Filterung läuft serverseitig (Query-Parameter), nicht clientseitig
 * wie in `applications.component.ts` - der Export der "aktuellen Ansicht"
 * muss exakt dieselbe Ergebnismenge wie die Anzeige liefern, ohne eine
 * gefilterte ID-Liste extra zum Backend zu schicken.
 */
@Component({
  selector: 'app-sent-emails',
  standalone: true,
  imports: [
    DatePipe,
    NgTemplateOutlet,
    RouterLink,
    MatButtonModule,
    MatFormFieldModule,
    MatIconModule,
    MatInputModule,
    MatProgressSpinnerModule,
    MatSelectModule,
    MatTableModule,
  ],
  templateUrl: './sent-emails.component.html',
  styleUrl: './sent-emails.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class SentEmailsComponent implements OnInit {
  private readonly sentEmailService = inject(SentEmailService);
  private readonly snackBar = inject(MatSnackBar);

  protected readonly senderEmailOptions = SENDER_EMAIL_OPTIONS;
  protected readonly sourceLabel = sourceLabel;
  protected readonly displayedColumns = [
    'company',
    'ad_url',
    'source_platform',
    'recipient_email',
    'sent_at',
    'sender_email',
    'subject',
    'attachment_filenames',
    'outcome',
    'actions',
  ];

  /** Anzeigetext je `outcome` (KTD1) - "Offer"/"Rejection" spiegeln die Wortwahl aus
   * `ApplicationsComponent.STATUS_LABELS` für denselben Zusage/Absage-Zustand. */
  private static readonly OUTCOME_LABELS: Record<SentEmail['outcome'], string> = {
    offer: 'Offer',
    rejection: 'Rejection',
    pending: 'Pending',
  };

  protected readonly entries = signal<SentEmail[]>([]);
  protected readonly loading = signal(true);
  protected readonly errorMessage = signal<string | null>(null);
  /** ID des Log-Eintrags, der gerade gelöscht wird (max. einer gleichzeitig). */
  protected readonly deletingId = signal<number | null>(null);

  protected readonly companyFilter = signal('');
  protected readonly senderEmailFilter = signal<string | null>(null);
  protected readonly dateFromFilter = signal('');
  protected readonly dateToFilter = signal('');
  protected readonly outcomeFilter = signal<string | null>(null);

  protected readonly exportingCurrent = signal(false);
  protected readonly exportingAll = signal(false);
  protected readonly exportError = signal<string | null>(null);

  ngOnInit(): void {
    this.load();
  }

  protected onFilterChange(): void {
    this.load();
  }

  protected hasActiveFilter(): boolean {
    const filter = this.currentFilter();
    return Boolean(
      filter.company || filter.sender_email || filter.date_from || filter.date_to || filter.outcome,
    );
  }

  protected outcomeLabel(outcome: SentEmail['outcome']): string {
    return SentEmailsComponent.OUTCOME_LABELS[outcome];
  }

  protected exportCurrent(): void {
    if (this.exportingCurrent()) {
      return;
    }
    this.exportingCurrent.set(true);
    this.exportError.set(null);
    this.sentEmailService.exportCurrent(this.currentFilter()).subscribe({
      next: (response) => {
        this.exportingCurrent.set(false);
        if (!downloadBlobResponse(response, DEFAULT_FILTERED_FILENAME)) {
          this.exportError.set('Export failed. Please try again.');
        }
      },
      error: () => {
        this.exportingCurrent.set(false);
        this.exportError.set('Export failed. Please try again.');
      },
    });
  }

  protected exportAll(): void {
    if (this.exportingAll()) {
      return;
    }
    this.exportingAll.set(true);
    this.exportError.set(null);
    this.sentEmailService.exportAll().subscribe({
      next: (response) => {
        this.exportingAll.set(false);
        if (!downloadBlobResponse(response, DEFAULT_FULL_LOG_FILENAME)) {
          this.exportError.set('Export failed. Please try again.');
        }
      },
      error: () => {
        this.exportingAll.set(false);
        this.exportError.set('Export failed. Please try again.');
      },
    });
  }

  protected isDeleting(entry: SentEmail): boolean {
    return this.deletingId() === entry.id;
  }

  protected onDelete(entry: SentEmail): void {
    if (this.deletingId() !== null) {
      return;
    }
    const confirmed = window.confirm(
      `Permanently delete this log entry (${entry.recipient_email}, ${entry.company ?? 'unknown company'})?`,
    );
    if (!confirmed) {
      return;
    }

    this.deletingId.set(entry.id);
    this.sentEmailService.deleteById(entry.id).subscribe({
      next: () => {
        this.entries.update((entries) => entries.filter((e) => e.id !== entry.id));
        this.deletingId.set(null);
        this.snackBar.open('Log entry was deleted.', 'OK', { duration: 3000 });
      },
      error: (error: HttpErrorResponse) => {
        this.deletingId.set(null);
        const message =
          (error.error?.detail as string | undefined) ?? 'The log entry could not be deleted.';
        this.snackBar.open(message, 'OK', { duration: 4000 });
      },
    });
  }

  private currentFilter(): SentEmailFilterParams {
    return {
      company: this.companyFilter().trim() || null,
      sender_email: this.senderEmailFilter(),
      date_from: this.dateFromFilter() || null,
      date_to: this.dateToFilter() || null,
      outcome: this.outcomeFilter(),
    };
  }

  private load(): void {
    this.loading.set(true);
    this.errorMessage.set(null);

    this.sentEmailService.list(this.currentFilter()).subscribe({
      next: (entries) => {
        this.entries.set(entries);
        this.loading.set(false);
      },
      error: (error: HttpErrorResponse) => {
        console.error('Sent emails could not be loaded', error);
        this.entries.set([]);
        this.loading.set(false);
        this.errorMessage.set('The sent emails log could not be loaded. Please try again later.');
      },
    });
  }

}
