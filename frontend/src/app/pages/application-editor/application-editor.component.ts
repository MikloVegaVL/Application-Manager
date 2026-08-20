import {
  ChangeDetectionStrategy,
  Component,
  OnInit,
  inject,
  input,
  signal,
} from '@angular/core';
import { FormBuilder, ReactiveFormsModule, Validators } from '@angular/forms';

import { TextFieldModule } from '@angular/cdk/text-field';
import { MatButtonModule } from '@angular/material/button';
import { MatDialog } from '@angular/material/dialog';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatIconModule } from '@angular/material/icon';
import { MatInputModule } from '@angular/material/input';
import { MatProgressSpinnerModule } from '@angular/material/progress-spinner';
import { MatSnackBar } from '@angular/material/snack-bar';
import { MatTabsModule } from '@angular/material/tabs';
import { MatToolbarModule } from '@angular/material/toolbar';
import { MatTooltipModule } from '@angular/material/tooltip';

import { HttpErrorResponse } from '@angular/common/http';
import { Application } from '../../core/models/application.model';
import { JobOfferRead } from '../../core/models/job-offer.model';
import { ApplicationService } from '../../core/services/application.service';
import { JobService } from '../../core/services/job.service';
import { parseBetreff } from '../../core/utils/cover-letter.util';
import { extractEmail } from '../../core/utils/email-extraction.util';
import {
  SendApplicationDialogComponent,
  SendApplicationDialogData,
  SendApplicationDialogResult,
} from './send-application-dialog/send-application-dialog.component';

@Component({
  selector: 'app-application-editor',
  standalone: true,
  imports: [
    ReactiveFormsModule,
    MatButtonModule,
    MatFormFieldModule,
    MatIconModule,
    MatInputModule,
    MatProgressSpinnerModule,
    MatTabsModule,
    MatToolbarModule,
    MatTooltipModule,
    TextFieldModule,
  ],
  templateUrl: './application-editor.component.html',
  styleUrl: './application-editor.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class ApplicationEditorComponent implements OnInit {
  /** Wird über den Routenparameter `:jobOfferId` per Component-Input-Binding befüllt. */
  readonly jobOfferId = input<string>();

  private readonly applicationService = inject(ApplicationService);
  private readonly jobService = inject(JobService);
  private readonly formBuilder = inject(FormBuilder);
  private readonly snackBar = inject(MatSnackBar);
  private readonly dialog = inject(MatDialog);

  protected readonly loading = signal(true);
  protected readonly saving = signal(false);
  protected readonly sending = signal(false);
  protected readonly errorMessage = signal<string | null>(null);
  /** True während der erstmaligen KI-Generierung (siehe `generateForFirstTime`) -
   * steuert den Hinweis, dass das ohne GPU-Beschleunigung mehrere Minuten
   * dauern kann (ce-debug-Untersuchung, 2026-08-18: "Generate Application"
   * wirkte dadurch wie hängengeblieben statt nur langsam). */
  protected readonly isFirstGeneration = signal(false);

  protected readonly application = signal<Application | null>(null);
  protected readonly jobOffer = signal<JobOfferRead | null>(null);

  protected readonly coverLetterForm = this.formBuilder.nonNullable.group({
    cover_letter_text: ['', Validators.required],
  });

  ngOnInit(): void {
    this.loadOrGenerateApplication();
  }

  // --- Laden / Erstgenerierung -------------------------------------------

  private loadOrGenerateApplication(): void {
    const jobOfferIdParam = this.jobOfferId();
    if (!jobOfferIdParam) {
      this.errorMessage.set('Es wurde keine Job-ID übergeben.');
      this.loading.set(false);
      return;
    }
    const jobOfferId = Number(jobOfferIdParam);

    this.loading.set(true);
    this.errorMessage.set(null);

    this.jobService.getJob(jobOfferId).subscribe({
      next: (job) => this.jobOffer.set(job),
      error: () => {
        // Nicht kritisch für den Editor selbst - dient nur der Kopfzeile.
      },
    });

    this.applicationService.getByJobOffer(jobOfferId).subscribe({
      next: (application) => this.applyApplication(application),
      error: (error: HttpErrorResponse) => {
        if (error.status === 404) {
          this.generateForFirstTime(jobOfferId);
          return;
        }
        this.handleLoadError(error);
      },
    });
  }

  private generateForFirstTime(jobOfferId: number): void {
    this.isFirstGeneration.set(true);
    this.applicationService.generate(jobOfferId).subscribe({
      next: (application) => {
        this.isFirstGeneration.set(false);
        this.applyApplication(application);
        this.snackBar.open('Anschreiben wurde erstmalig generiert.', 'OK', { duration: 3000 });
      },
      error: (error: HttpErrorResponse) => {
        this.isFirstGeneration.set(false);
        this.handleLoadError(error);
      },
    });
  }

  private handleLoadError(error: HttpErrorResponse): void {
    this.loading.set(false);
    this.errorMessage.set(
      (error.error?.detail as string | undefined) ?? 'Bewerbung konnte nicht geladen werden.',
    );
  }

  private applyApplication(application: Application): void {
    this.application.set(application);
    this.coverLetterForm.patchValue({ cover_letter_text: application.cover_letter_text ?? '' });
    this.loading.set(false);
  }

  // --- Toolbar-Aktionen -----------------------------------------------

  onSaveCoverLetter(): void {
    const application = this.application();
    if (!application) {
      return;
    }
    if (this.coverLetterForm.invalid) {
      this.coverLetterForm.markAllAsTouched();
      this.snackBar.open('Bitte gib einen Anschreiben-Text ein.', 'OK', { duration: 3000 });
      return;
    }

    this.saving.set(true);
    this.applicationService
      .update(application.id, {
        cover_letter_text: this.coverLetterForm.getRawValue().cover_letter_text,
      })
      .subscribe({
        next: (updated) => {
          this.saving.set(false);
          this.applyApplication(updated);
          this.snackBar.open('Anschreiben wurde gespeichert.', 'OK', { duration: 3000 });
        },
        error: (error: HttpErrorResponse) => {
          this.saving.set(false);
          const message =
            (error.error?.detail as string | undefined) ?? 'Anschreiben konnte nicht gespeichert werden.';
          this.snackBar.open(message, 'OK', { duration: 4000 });
        },
      });
  }

  onOpenSendDialog(): void {
    const application = this.application();
    if (!application) {
      return;
    }

    const jobOffer = this.jobOffer();

    // Subject/Message leiten sich aus der *gespeicherten* Anschreiben-Zeile
    // ab (application(), nicht der live coverLetterForm-Wert) - das hält den
    // E-Mail-Text konsistent mit dem zuletzt gespeicherten Anschreiben.
    const { subject: derivedSubject, message: derivedMessage } = parseBetreff(
      application.cover_letter_text ?? null,
    );
    const fallbackSubject = jobOffer?.title ? `Bewerbung als ${jobOffer.title}` : 'Bewerbung';

    const dialogRef = this.dialog.open(SendApplicationDialogComponent, {
      width: '520px',
      data: {
        toEmail: extractEmail(jobOffer?.description_text) ?? '',
        subject: derivedSubject ?? fallbackSubject,
        message: derivedMessage,
        jobTitle: jobOffer?.title,
        companyName: jobOffer?.company,
      } satisfies SendApplicationDialogData,
    });

    dialogRef.afterClosed().subscribe((result?: SendApplicationDialogResult) => {
      if (!result) {
        return;
      }
      this.sendApplication(application.id, result);
    });
  }

  private sendApplication(applicationId: number, payload: SendApplicationDialogResult): void {
    this.sending.set(true);
    this.applicationService
      .send(applicationId, {
        to_email: payload.to_email,
        subject: payload.subject || undefined,
        message: payload.message || undefined,
      })
      .subscribe({
        next: (updated) => {
          this.sending.set(false);
          this.application.set(updated);
          this.snackBar.open('Bewerbung wurde erfolgreich versendet.', 'OK', { duration: 4000 });
        },
        error: (error: HttpErrorResponse) => {
          this.sending.set(false);
          const message =
            (error.error?.detail as string | undefined) ?? 'Bewerbung konnte nicht versendet werden.';
          this.snackBar.open(message, 'OK', { duration: 5000 });
        },
      });
  }
}
