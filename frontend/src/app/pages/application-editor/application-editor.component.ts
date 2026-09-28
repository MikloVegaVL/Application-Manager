import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  OnInit,
  TemplateRef,
  ViewChild,
  computed,
  inject,
  input,
  signal,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { FormBuilder, ReactiveFormsModule, Validators } from '@angular/forms';
import { Router, RouterLink } from '@angular/router';
import { catchError, filter, of, switchMap, take, takeUntil, timer } from 'rxjs';

import { TextFieldModule } from '@angular/cdk/text-field';
import { MatButtonModule } from '@angular/material/button';
import { MatButtonToggleModule } from '@angular/material/button-toggle';
import { MatDialog, MatDialogModule } from '@angular/material/dialog';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatIconModule } from '@angular/material/icon';
import { MatInputModule } from '@angular/material/input';
import { MatProgressSpinnerModule } from '@angular/material/progress-spinner';
import { MatSnackBar } from '@angular/material/snack-bar';
import { MatTabsModule } from '@angular/material/tabs';
import { MatToolbarModule } from '@angular/material/toolbar';
import { MatTooltipModule } from '@angular/material/tooltip';

import { HttpErrorResponse } from '@angular/common/http';
import { Application, ProfileType } from '../../core/models/application.model';
import { JobOfferRead, toApplicationEmailLookupRequest } from '../../core/models/job-offer.model';
import { ApplicationService } from '../../core/services/application.service';
import { JobSearchStateService } from '../../core/services/job-search-state.service';
import { JobService } from '../../core/services/job.service';
import { TabTitleService } from '../../core/services/tab-title.service';
import { parseBetreff } from '../../core/utils/cover-letter.util';
import { downloadBlobResponse } from '../../core/utils/download-blob-response.util';
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
    RouterLink,
    MatButtonModule,
    MatButtonToggleModule,
    MatDialogModule,
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
  /** Wird über den optionalen Routenparameter `:applicationId` befüllt (U9,
   * R5/KTD12) - wählt bei mehreren Bewerbungen für dasselbe Stellenangebot
   * die konkret gemeinte aus; ohne Angabe wird die erste zurückgegebene
   * verwendet (weiterhin der häufigste Fall: nur eine Bewerbung). */
  readonly applicationId = input<string>();

  private readonly applicationService = inject(ApplicationService);
  private readonly jobService = inject(JobService);
  /** Teilt das Lookup-Ergebnis mit der Job-Suchkarte (KTD7) und cached es,
   * wenn der Dialog die Suche auslöst. */
  private readonly jobSearchState = inject(JobSearchStateService);
  private readonly formBuilder = inject(FormBuilder);
  private readonly snackBar = inject(MatSnackBar);
  private readonly dialog = inject(MatDialog);
  private readonly destroyRef = inject(DestroyRef);
  private readonly router = inject(Router);
  private readonly tabTitleService = inject(TabTitleService);

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
  /** True während das Anschreiben als PDF heruntergeladen wird (sperrt den Download-Button). */
  protected readonly downloading = signal(false);
  /** True während eine Regenerate-Anfrage läuft (R8) - sperrt Regenerate,
   * Save und Send bis die Anfrage abgeschlossen ist (KTD4). */
  protected readonly regenerating = signal(false);
  /** True während "Start a new application with the other profile" läuft
   * (U9, R5/KTD12). */
  protected readonly startingNewApplication = signal(false);
  /** Fasst alle "gerade läuft etwas"-Signale zusammen (ce-simplify-code-
   * Fund: einzeln kopierte Kombinationen in den drei Button-Bindings waren
   * auseinandergedriftet - Regenerate erlaubte einen Klick während Send
   * bereits lief). Einzige Quelle für die `[disabled]`-Bindings im Template,
   * damit sie nicht wieder auseinanderlaufen können. */
  protected readonly busy = computed(
    () => this.saving() || this.sending() || this.regenerating() || this.startingNewApplication(),
  );
  protected readonly errorMessage = signal<string | null>(null);
  /** True während der erstmaligen KI-Generierung (siehe `generateForFirstTime`) -
   * steuert den Hinweis, dass das ohne GPU-Beschleunigung mehrere Minuten
   * dauern kann (ce-debug-Untersuchung, 2026-08-18: "Generate Application"
   * wirkte dadurch wie hängengeblieben statt nur langsam). */
  protected readonly isFirstGeneration = signal(false);

  protected readonly application = signal<Application | null>(null);
  protected readonly jobOffer = signal<JobOfferRead | null>(null);

  /** Das jeweils ANDERE Profil zum aktuell gesperrten (U9, R5/KTD12) -
   * `null`, solange kein Profil gesperrt ist (Sperre erst nach der ersten
   * Generierung, R5) - steuert Sichtbarkeit/Ziel von "Start a new
   * application with the other profile". */
  protected readonly otherProfileType = computed<ProfileType | null>(() => {
    const current = this.application()?.profile_type;
    if (current === 'it') {
      return 'full_life';
    }
    if (current === 'full_life') {
      return 'it';
    }
    return null;
  });

  /** Aktuell im Profilwahl-Dialog markierte Option (R4) - `null`, solange
   * noch nichts ausgewählt wurde (sperrt den "Continue"-Button). */
  protected readonly selectedProfileType = signal<ProfileType | null>(null);
  /** Gesetzt, wenn die letzte Generierung an einem fehlenden Profil
   * scheiterte (404 von `POST /applications/generate`, U3) - steuert den
   * "Go to profile"-Link im Fehlerblock (statt der generischen Meldung). */
  protected readonly missingProfileType = signal<ProfileType | null>(null);

  @ViewChild('profileTypeDialog') private readonly profileTypeDialogTemplate!: TemplateRef<unknown>;

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
      this.errorMessage.set('No job ID was provided.');
      this.loading.set(false);
      return;
    }
    const jobOfferId = Number(jobOfferIdParam);
    const applicationIdParam = this.applicationId();
    const applicationId = applicationIdParam ? Number(applicationIdParam) : undefined;

    this.loading.set(true);
    this.errorMessage.set(null);
    this.missingProfileType.set(null);

    this.jobService.getJob(jobOfferId).subscribe({
      next: (job) => this.jobOffer.set(job),
      error: () => {
        // Nicht kritisch für den Editor selbst - dient nur der Kopfzeile.
      },
    });

    this.applicationService.getByJobOffer(jobOfferId, applicationId).subscribe({
      next: (application) => {
        if (!application) {
          // Für dieses Stellenangebot existiert noch gar keine Bewerbung -
          // damit ist zwangsläufig noch kein Profil gesperrt (R4).
          this.promptForProfileType(jobOfferId);
          return;
        }
        // `POST /jobs/save` legt seit ce-debug (2026-08-20) sofort eine
        // Application ohne Anschreiben an, damit gespeicherte Jobs auf der
        // Bewerbungsübersicht sichtbar sind - dieser Fall (leeres
        // `cover_letter_text`) muss die Erstgenerierung genauso anstoßen wie
        // eine noch gar nicht existierende Bewerbung.
        if (!application.cover_letter_text) {
          // Noch kein Profil gesperrt (U3/R4) - der Nutzer muss es erst
          // wählen, bevor überhaupt generiert werden darf. Ist bereits ein
          // Profil gesperrt (z. B. ein vorheriger Versuch scheiterte nach dem
          // Sperren - kommt praktisch nicht vor, siehe Backend, aber zur
          // Sicherheit abgedeckt), läuft die bisherige Auto-Generierung
          // unverändert.
          if (application.profile_type === null) {
            this.promptForProfileType(jobOfferId);
            return;
          }
          this.generateForFirstTime(jobOfferId);
          return;
        }
        this.applyApplication(application);
      },
      error: (error: HttpErrorResponse) => this.handleLoadError(error),
    });
  }

  /** Zeigt den blockierenden Profilwahl-Dialog (IT/Full-life, R4) vor der
   * ERSTEN Generierung für dieses Stellenangebot - `disableClose`, damit der
   * Nutzer die Wahl nicht per Escape/Backdrop umgehen kann, ohne eine Option
   * gewählt zu haben. Schließt der Dialog mit einer Wahl, wird direkt wie
   * bisher generiert (KTD4: kein weiterer Guard nötig, da die HTTP-Anfrage
   * erst NACH dem Schließen des Dialogs startet - ein erneutes Öffnen
   * während einer laufenden Anfrage ist aus diesem Ablauf heraus nicht
   * erreichbar). */
  private promptForProfileType(jobOfferId: number): void {
    this.selectedProfileType.set(null);
    this.dialog
      .open<unknown, unknown, ProfileType>(this.profileTypeDialogTemplate, {
        disableClose: true,
        width: '480px',
      })
      .afterClosed()
      .subscribe((profileType) => {
        if (!profileType) {
          return;
        }
        this.generateForFirstTime(jobOfferId, profileType);
      });
  }

  private generateForFirstTime(jobOfferId: number, profileType?: ProfileType): void {
    this.isFirstGeneration.set(true);
    this.tabTitleService.markGenerationStarted();
    this.applicationService.generate(jobOfferId, profileType).subscribe({
      next: (application) => {
        this.isFirstGeneration.set(false);
        this.tabTitleService.markGenerationSettled();
        this.applyApplication(application);
        this.snackBar.open('Cover letter was generated for the first time.', 'OK', {
          duration: 3000,
        });
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
        if (error.status === 404 && profileType) {
          // Das gewählte Profil hat noch keine Daten (`_get_profile_or_404`,
          // U2/U3) - benennt das konkrete Profil statt einer generischen
          // Fehlermeldung und bietet einen Link zur Profilseite an (U8).
          this.handleMissingProfileError(profileType);
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
          // Die eigene POST-/generate-Anfrage endete mit 409 (siehe oben) -
          // erst hier, mit dem Ergebnis der abgewarteten fremden Generierung,
          // ist der Vorgang aus Sicht dieses Tabs abgeschlossen (R6).
          this.tabTitleService.markGenerationSettled();
          this.applyApplication(application);
        },
        complete: () => {
          // `takeUntil(timedOut$)` kann den Stream beenden, ohne dass `next`
          // je gefeuert hat (Timeout erreicht, bevor ein Ergebnis vorlag) -
          // in dem Fall (isFirstGeneration noch true) einen Fehler zeigen,
          // statt den Editor stillschweigend im Warte-Zustand zu belassen.
          if (this.isFirstGeneration()) {
            this.isFirstGeneration.set(false);
            this.tabTitleService.markGenerationSettled();
            this.loading.set(false);
            this.errorMessage.set(
              'The generation is taking unusually long or has failed. Please reload the page to try again.',
            );
          }
        },
      });
  }

  /** Gemeinsame Fehlerbehandlung für `generateForFirstTime` - beendet die
   * Generierungs-Wartezeit (Hinweis-Anzeige aus, Fehler anzeigen, Tab-Titel-
   * Tracking abgeschlossen). */
  private handleGenerationError(error: HttpErrorResponse): void {
    this.isFirstGeneration.set(false);
    this.tabTitleService.markGenerationSettled();
    this.handleLoadError(error);
  }

  private handleLoadError(error: HttpErrorResponse): void {
    this.loading.set(false);
    this.errorMessage.set(
      (error.error?.detail as string | undefined) ?? 'The application could not be loaded.',
    );
  }

  /** Zeigt statt der generischen Fehlermeldung eine, die das konkret
   * gewählte Profil benennt (`profileTypeLabel`) plus Link zur Profilseite
   * (`missingProfileType`, siehe Template) - das gewählte Profil hat noch
   * keine Daten (404 von `POST /applications/generate`, U2/U3). */
  private handleMissingProfileError(profileType: ProfileType): void {
    this.isFirstGeneration.set(false);
    this.tabTitleService.markGenerationSettled();
    this.loading.set(false);
    this.missingProfileType.set(profileType);
    this.errorMessage.set(`The ${this.profileTypeLabel(profileType)} profile has no data yet.`);
  }

  /** Deckt sich mit `_PROFILE_TYPE_LABELS` in `backend/app/api/profile.py`. */
  protected profileTypeLabel(profileType: ProfileType): string {
    return profileType === 'it' ? 'IT' : 'Full-life/Non-IT';
  }

  private applyApplication(application: Application): void {
    this.application.set(application);
    this.coverLetterForm.patchValue({ cover_letter_text: application.cover_letter_text ?? '' });
    this.loading.set(false);
    this.missingProfileType.set(null);
  }

  // --- Toolbar-Aktionen -----------------------------------------------

  onSaveCoverLetter(): void {
    const application = this.application();
    if (!application) {
      return;
    }
    if (this.coverLetterForm.invalid) {
      this.coverLetterForm.markAllAsTouched();
      this.snackBar.open('Please enter a cover letter text.', 'OK', { duration: 3000 });
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
          this.snackBar.open('Cover letter was saved.', 'OK', { duration: 3000 });
        },
        error: (error: HttpErrorResponse) => {
          this.saving.set(false);
          const message =
            (error.error?.detail as string | undefined) ?? 'The cover letter could not be saved.';
          this.snackBar.open(message, 'OK', { duration: 4000 });
        },
      });
  }

  /** Lädt das GESPEICHERTE Anschreiben als PDF herunter (konsistent mit dem
   * Mailversand, der ebenfalls den gespeicherten Text nutzt) - der Dateiname
   * kommt aus dem `Content-Disposition`-Header des Backends. */
  onDownloadCoverLetter(): void {
    const application = this.application();
    if (!application || this.downloading()) {
      return;
    }

    this.downloading.set(true);
    this.applicationService.downloadCoverLetter(application.id).subscribe({
      next: (response) => {
        this.downloading.set(false);
        if (!downloadBlobResponse(response, 'cover-letter.pdf')) {
          this.snackBar.open('The cover letter PDF could not be downloaded.', 'OK', {
            duration: 4000,
          });
        }
      },
      error: (error: HttpErrorResponse) => {
        this.downloading.set(false);
        const message =
          (error.error?.detail as string | undefined) ??
          'The cover letter PDF could not be downloaded.';
        this.snackBar.open(message, 'OK', { duration: 4000 });
      },
    });
  }

  /** Erzeugt ein neues Anschreiben für eine Bewerbung, die bereits eines hat
   * (R4) - überschreibt den gespeicherten Text nach Bestätigung (R5) und ist
   * gegen Doppel-Klicks/laufende Anfragen abgesichert (R8, KTD4). Nutzt
   * bewusst nicht `handleGenerationError`/`handleLoadError`: die von diesen
   * Methoden gesteuerte Seiten-Fehleransicht (`@if (errorMessage())` im
   * Template) würde bei einem Fehlschlag den ganzen Editor-Inhalt ersetzen
   * und damit das aktuell gespeicherte/handbearbeitete Anschreiben
   * verstecken - stattdessen bleibt der Text sichtbar/editierbar und der
   * Fehler wird nur per Snackbar gezeigt (analog `onSaveCoverLetter`). */
  onRegenerate(): void {
    const application = this.application();
    if (!application || this.regenerating()) {
      return;
    }

    const confirmed = window.confirm(
      'Regenerating will replace the current cover letter text with a newly generated one. Continue?',
    );
    if (!confirmed) {
      return;
    }

    this.regenerating.set(true);
    this.tabTitleService.markGenerationStarted();
    this.applicationService.generate(application.job_offer_id).subscribe({
      next: (updated) => {
        this.regenerating.set(false);
        this.tabTitleService.markGenerationSettled();
        this.applyApplication(updated);
        this.snackBar.open('Cover letter was regenerated.', 'OK', { duration: 3000 });
      },
      error: (error: HttpErrorResponse) => {
        // Ein 409 (das per-Job-Angebot-Lock des Backends, siehe KTD4) wird
        // hier bewusst wie ein gewöhnlicher Fehler behandelt statt wie in
        // `generateForFirstTime` in `pollForRunningGeneration` zu münden -
        // das `regenerating`-Guard-Signal (R8) macht diesen Wettlauf im
        // Normalbetrieb unerreichbar.
        this.regenerating.set(false);
        this.tabTitleService.markGenerationSettled();
        const message =
          (error.error?.detail as string | undefined) ??
          'The cover letter could not be regenerated.';
        this.snackBar.open(message, 'OK', { duration: 4000 });
      },
    });
  }

  /** R5's Ausweg (U9, KTD12): startet eine ZUSÄTZLICHE, unabhängige
   * Bewerbung für dasselbe Stellenangebot mit dem jeweils ANDEREN Profil,
   * statt das hier bereits gesperrte zu überschreiben - navigiert nach
   * erfolgreicher Generierung zum Editor der neuen Bewerbung (eigene
   * `applicationId`). Nur erreichbar, wenn ein Profil gesperrt ist
   * (`otherProfileType()` sonst `null`, siehe Template). */
  onStartNewApplicationWithOtherProfile(): void {
    const application = this.application();
    const otherProfileType = this.otherProfileType();
    if (!application || !otherProfileType || this.busy()) {
      return;
    }

    this.startingNewApplication.set(true);
    this.applicationService.generate(application.job_offer_id, otherProfileType, true).subscribe({
      next: (newApplication) => {
        this.startingNewApplication.set(false);
        void this.router.navigate(['/editor', application.job_offer_id, newApplication.id]);
      },
      error: (error: HttpErrorResponse) => {
        this.startingNewApplication.set(false);
        const message =
          (error.error?.detail as string | undefined) ??
          'A new application for the other profile could not be started.';
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
    const fallbackSubject = jobOffer?.title
      ? `Application as ${jobOffer.title}`
      : 'Application';

    // Persistierte Adresse schlägt die Extraktion aus dem Anzeigentext
    // (R10/AE4); ein in-session gefundenes Ergebnis der Karte kommt davor,
    // damit ein frisch gesuchter Job beim Öffnen nicht leer startet. Nur ein
    // `found`-Ergebnis liefert eine Adresse - `not-found`/`failed` dürfen
    // nicht als (leerer) Vorschlag durchschlagen.
    const cachedLookupResult = jobOffer
      ? this.jobSearchState.applicationEmailResult(jobOffer.source_url)
      : null;
    const cachedLookupEmail =
      cachedLookupResult?.status === 'found' ? (cachedLookupResult.email ?? null) : null;

    const dialogRef = this.dialog.open(SendApplicationDialogComponent, {
      width: '520px',
      data: {
        toEmail:
          jobOffer?.application_email ??
          cachedLookupEmail ??
          extractEmail(jobOffer?.description_text) ??
          '',
        subject: derivedSubject ?? fallbackSubject,
        message: derivedMessage,
        jobTitle: jobOffer?.title,
        companyName: jobOffer?.company,
        findApplicationEmail: jobOffer
          ? (force: boolean) =>
              this.jobSearchState.lookupApplicationEmail(
                toApplicationEmailLookupRequest(jobOffer, force),
                { force },
              )
          : undefined,
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
          this.snackBar.open('Application was sent successfully.', 'OK', { duration: 4000 });
          // Nach erfolgreichem Versand zurück zur Übersicht, damit der neue
          // Status (Versendet + Empfängeradresse) direkt sichtbar ist.
          void this.router.navigate(['/applications']);
        },
        error: (error: HttpErrorResponse) => {
          this.sending.set(false);
          const message =
            (error.error?.detail as string | undefined) ?? 'The application could not be sent.';
          this.snackBar.open(message, 'OK', { duration: 5000 });
        },
      });
  }
}
