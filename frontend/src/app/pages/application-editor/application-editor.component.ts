import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  OnInit,
  inject,
  input,
  signal,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { FormBuilder, ReactiveFormsModule, Validators } from '@angular/forms';
import { catchError, filter, of, switchMap, take, takeUntil, timer } from 'rxjs';

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
import { TranslatePipe } from '../../core/i18n/translate.pipe';
import { Application } from '../../core/models/application.model';
import { JobOfferRead } from '../../core/models/job-offer.model';
import { ApplicationService } from '../../core/services/application.service';
import { JobService } from '../../core/services/job.service';
import { TranslationService } from '../../core/services/translation.service';
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
    TranslatePipe,
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
  private readonly destroyRef = inject(DestroyRef);
  protected readonly i18n = inject(TranslationService);

  /** Abstand zwischen zwei Status-Abfragen, während auf eine bereits
   * laufende Generierung gewartet wird (siehe `pollForRunningGeneration`). */
  private static readonly GENERATION_POLL_INTERVAL_MS = 5000;
  /** Obergrenze für die Wartezeit auf eine fremde, bereits laufende
   * Generierung (ce-code-review-Fund, 2026-08-28: ohne diese Grenze wartete
   * `pollForRunningGeneration` unbegrenzt weiter, wenn die abgewartete
   * Generierung am Ende fehlschlug - genau das Symptom, das dieser Fix
   * eigentlich beheben sollte, nur über einen anderen Auslöser). 30 Minuten
   * geben selbst dem dokumentierten Ollama-Worst-Case (3 sequentielle
   * Aufrufe à bis zu `OLLAMA_TIMEOUT_SECONDS`=600s, siehe config.py/
   * nginx.conf) Spielraum. */
  private static readonly GENERATION_POLL_TIMEOUT_MS = 30 * 60 * 1000;

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
      this.errorMessage.set(this.i18n.translate('editor.noJobId'));
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
      next: (application) => {
        // `POST /jobs/save` legt seit ce-debug (2026-08-20) sofort eine
        // Application ohne Anschreiben an, damit gespeicherte Jobs auf der
        // Bewerbungsübersicht sichtbar sind - dieser Fall (200 mit leerem
        // `cover_letter_text`) muss die Erstgenerierung genauso anstoßen wie
        // ein bislang fehlendes (404) Anschreiben.
        if (!application.cover_letter_text) {
          this.generateForFirstTime(jobOfferId);
          return;
        }
        this.applyApplication(application);
      },
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
        this.snackBar.open(
          this.i18n.translate('editor.generated'),
          this.i18n.translate('common.ok'),
          { duration: 3000 },
        );
      },
      error: (error: HttpErrorResponse) => {
        if (error.status === 409) {
          // Für dieses Stellenangebot läuft bereits eine Generierung - z. B.
          // weil dieser Editor schon einmal (Browser-Zurück, Reload, erneuter
          // Klick auf "Bewerbung generieren" in der Jobsuche) geöffnet wurde,
          // bevor die erste Generierung fertig war (siehe Backend-Sperre in
          // `app.api.applications.generate_application`, ce-debug-
          // Untersuchung, 2026-08-28). Statt eine weitere, überlappende
          // KI-Generierung anzustoßen - die das laufende Ergebnis nur
          // überschrieben und den Editor endlos ohne Ergebnis hätte wirken
          // lassen -, wird stattdessen auf deren Ergebnis gewartet.
          this.pollForRunningGeneration(jobOfferId);
          return;
        }
        this.handleGenerationError(error);
      },
    });
  }

  /** Wartet auf das Ergebnis einer bereits laufenden Generierung (409 von
   * `POST /applications/generate`), statt selbst eine weitere anzustoßen -
   * fragt periodisch `GET /applications/by-job-offer/:id` ab, bis
   * `cover_letter_text` gefüllt ist. `takeUntilDestroyed` beendet das
   * Polling automatisch, sobald der Editor verlassen wird.
   *
   * Zwei Robustheits-Eigenschaften (ce-code-review-Fund, 2026-08-28):
   * - `catchError` auf der einzelnen Status-Abfrage: ein einzelner
   *   fehlgeschlagener Tick (z. B. kurzer Netzwerk-/Backend-Hänger) darf die
   *   gesamte Wartezeit nicht sofort mit einem permanenten Fehler beenden -
   *   er wird übersprungen, der nächste Tick versucht es erneut.
   * - `takeUntil(timedOut$)`: schlägt die abgewartete fremde Generierung am
   *   Ende fehl (z. B. 502 beim Original-Aufruf), bliebe `cover_letter_text`
   *   für immer leer und der `filter` unten würde nie durchlassen - ohne
   *   diese Obergrenze liefe das Polling dann unbegrenzt weiter, also genau
   *   das ursprüngliche "Editor läuft endlos ohne Ergebnis"-Symptom, nur
   *   über einen anderen Auslöser reproduziert. */
  private pollForRunningGeneration(jobOfferId: number): void {
    const timedOut$ = timer(ApplicationEditorComponent.GENERATION_POLL_TIMEOUT_MS);

    timer(
      ApplicationEditorComponent.GENERATION_POLL_INTERVAL_MS,
      ApplicationEditorComponent.GENERATION_POLL_INTERVAL_MS,
    )
      .pipe(
        switchMap(() =>
          this.applicationService.getByJobOffer(jobOfferId).pipe(catchError(() => of(null))),
        ),
        filter((application): application is Application => !!application?.cover_letter_text),
        take(1),
        takeUntil(timedOut$),
        takeUntilDestroyed(this.destroyRef),
      )
      .subscribe({
        next: (application) => {
          this.isFirstGeneration.set(false);
          this.applyApplication(application);
        },
        complete: () => {
          // `takeUntil(timedOut$)` kann den Stream beenden, ohne dass `next`
          // je gefeuert hat (Timeout erreicht, bevor ein Ergebnis vorlag) -
          // in dem Fall (isFirstGeneration noch true) einen Fehler zeigen,
          // statt den Editor stillschweigend im Warte-Zustand zu belassen.
          if (this.isFirstGeneration()) {
            this.isFirstGeneration.set(false);
            this.loading.set(false);
            this.errorMessage.set(this.i18n.translate('editor.generationTimeout'));
          }
        },
      });
  }

  /** Gemeinsame Fehlerbehandlung für `generateForFirstTime` und
   * `pollForRunningGeneration` - beide beenden die Generierungs-Wartezeit
   * gleich (Hinweis-Anzeige aus, Fehler anzeigen). */
  private handleGenerationError(error: HttpErrorResponse): void {
    this.isFirstGeneration.set(false);
    this.handleLoadError(error);
  }

  private handleLoadError(error: HttpErrorResponse): void {
    this.loading.set(false);
    this.errorMessage.set(
      (error.error?.detail as string | undefined) ?? this.i18n.translate('editor.loadFailed'),
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
      this.snackBar.open(
        this.i18n.translate('editor.enterCoverLetter'),
        this.i18n.translate('common.ok'),
        { duration: 3000 },
      );
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
          this.snackBar.open(
            this.i18n.translate('editor.saved'),
            this.i18n.translate('common.ok'),
            { duration: 3000 },
          );
        },
        error: (error: HttpErrorResponse) => {
          this.saving.set(false);
          const message =
            (error.error?.detail as string | undefined) ?? this.i18n.translate('editor.saveFailed');
          this.snackBar.open(message, this.i18n.translate('common.ok'), { duration: 4000 });
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
    const fallbackSubject = jobOffer?.title
      ? this.i18n.translate('editor.fallbackSubjectWithTitle', { title: jobOffer.title })
      : this.i18n.translate('editor.fallbackSubject');

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
          this.snackBar.open(
            this.i18n.translate('editor.sent'),
            this.i18n.translate('common.ok'),
            { duration: 4000 },
          );
        },
        error: (error: HttpErrorResponse) => {
          this.sending.set(false);
          const message =
            (error.error?.detail as string | undefined) ?? this.i18n.translate('editor.sendFailed');
          this.snackBar.open(message, this.i18n.translate('common.ok'), { duration: 5000 });
        },
      });
  }
}
