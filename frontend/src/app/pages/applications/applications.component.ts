import { ChangeDetectionStrategy, Component, DestroyRef, OnInit, computed, inject, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { HttpErrorResponse } from '@angular/common/http';
import { Router, RouterLink } from '@angular/router';
import { catchError, of, switchMap, takeUntil, takeWhile, timer } from 'rxjs';

import { MatButtonModule } from '@angular/material/button';
import { MatButtonToggleModule } from '@angular/material/button-toggle';
import { MatCardModule } from '@angular/material/card';
import { MatCheckboxModule } from '@angular/material/checkbox';
import { MatChipsModule } from '@angular/material/chips';
import { MatDialog } from '@angular/material/dialog';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatIconModule } from '@angular/material/icon';
import { MatInputModule } from '@angular/material/input';
import { MatProgressSpinnerModule } from '@angular/material/progress-spinner';
import { MatRadioModule } from '@angular/material/radio';
import { MatSnackBar } from '@angular/material/snack-bar';

import { Application, ApplicationStatus, PortalFillStatus } from '../../core/models/application.model';
import { JobOffer } from '../../core/models/job-offer.model';
import { ApplicationService } from '../../core/services/application.service';
import { JobService, jobSaveConflictId } from '../../core/services/job.service';
import { TabTitleService } from '../../core/services/tab-title.service';
import { sourceLabel as getSourceLabel } from '../../core/utils/source-label.util';
import {
  AddJobOfferDialogComponent,
  AddJobOfferDialogResult,
} from './add-job-offer-dialog/add-job-offer-dialog.component';

type AutomationState = PortalFillStatus['automation_state'];

/** Alle Pausengründe aus der U1-Vokabel (`PauseReason`) - Grundlage für die Copy-Vollständigkeit. */
export const PAUSE_REASONS = [
  'captcha',
  'low_confidence_field',
  'pre_submit_confirmation',
  'dry_run',
  'screening_question',
] as const;

/** Alle Fehlgründe aus der U1-Vokabel (`FailureReason`). */
export const FAILURE_REASONS = [
  'timeout',
  'iframe_not_found',
  'unhandled_error',
  'browser_launch_failed',
  'cancelled_by_user',
  'interrupted_by_restart',
  'iframe_untrusted_host',
] as const;

/** KTD5: Fehlgründe, die gefahrlos erneut versucht werden dürfen - alles andere (auch unbekannt) gilt terminal. */
export const RETRYABLE_FAILURE_REASONS: ReadonlySet<string> = new Set<string>([
  'timeout',
  'iframe_not_found',
  'unhandled_error',
  'browser_launch_failed',
  'interrupted_by_restart',
]);

/** Copy je `action_needed_reason` während einer Pause (R10/R11) - unbekannte/neue Gründe fallen auf einen
 * generischen Hinweis zurück statt nichts anzuzeigen. Referenziert seit KTD1 (headless überall) die
 * Screenshot-Ansicht statt eines sichtbaren Browser-Fensters (das es nicht mehr gibt). */
export const ACTION_NEEDED_COPY: Record<string, string> = {
  captcha: 'A captcha appeared — solve it using the live connection below, then Continue.',
  low_confidence_field: 'A field needs your review — check the screenshot below, then Continue.',
  pre_submit_confirmation: 'Form is filled — review the screenshot below, then Continue to submit.',
  dry_run:
    'Dry run complete — the form is filled but nothing was submitted. Review the screenshot below, then submit for real.',
  screening_question:
    'A screening question needs a factual answer — check the screenshot below, then Continue.',
};

/** KTD8: fester Debug-Port aus `settings.PORTAL_FILL_DEBUG_PORT` (Backend-Default, siehe
 * `backend/app/core/config.py`) - reine Deployment-Konstante, kein Laufzeitzustand, daher hier fest
 * hinterlegt statt über die API geliefert. Bei Änderung des Backend-Defaults hier mitziehen. */
const PORTAL_FILL_DEBUG_PORT = 9222;

/** Menschenlesbare Übersetzung der rohen `action_needed_reason`-Werte bei `failed` (siehe `session.py`). */
export const FAILURE_REASON_COPY: Record<string, string> = {
  timeout: 'The run timed out waiting for you.',
  iframe_not_found: "Couldn't find the application form on that page.",
  unhandled_error: 'Something went wrong during the run.',
  browser_launch_failed: 'The browser could not be launched.',
  cancelled_by_user: 'Cancelled.',
  interrupted_by_restart: 'Interrupted by a backend restart.',
  iframe_untrusted_host: 'The application form is hosted on an untrusted site.',
};

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
    MatCheckboxModule,
    MatChipsModule,
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
  private readonly tabTitleService = inject(TabTitleService);
  private readonly destroyRef = inject(DestroyRef);

  /** Abstand zwischen zwei Status-Abfragen eines Portal-Auto-Fill-Laufs - gleiche Kadenz wie
   * `ApplicationEditorComponent.pollForRunningGeneration` (siehe dort). */
  private static readonly PORTAL_FILL_POLL_INTERVAL_MS = 5000;
  /** Obergrenze NUR für die `running`-Phase (mirrort den ursprünglichen, auf einen einzelnen
   * beschränkten LLM-Aufruf gemünzten Timeout-Einsatz aus dem Editor) - eine `paused`-Phase ist
   * menschengesteuert und bewusst unbegrenzt (siehe Auftrag). */
  private static readonly PORTAL_FILL_RUNNING_TIMEOUT_MS = 30 * 60 * 1000;

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
  /** Freitextsuche über Jobtitel/Firma (rein clientseitig, kombiniert per AND mit `filter`). */
  protected readonly searchTerm = signal('');

  /** ID der Bewerbung, für die gerade `POST .../portal-fill/start` läuft. */
  protected readonly portalFillStartingId = signal<number | null>(null);
  /** Live-Status je Bewerbung, seit diese Seite geladen wurde (Polling-Ergebnis) - überschreibt das beim
   * initialen `list()` mitgelieferte `automation_state`/`action_needed_reason` der jeweiligen Bewerbung,
   * bis eine neue Liste geladen wird (siehe `automationState()`/`actionNeededReason()`). */
  protected readonly portalFillStatuses = signal<Record<number, PortalFillStatus>>({});
  /** IDs, für die die `failed`-Meldung bereits weggeklickt wurde (bleibt bis zum nächsten Start gesetzt). */
  protected readonly dismissedFailureIds = signal<ReadonlySet<number>>(new Set());
  /** Cache-Bust-Zähler je Bewerbung für den Pause-Screenshot (R2/U2) - der Screenshot ist eine
   * Zeitpunktaufnahme (KTD6), kein Live-Feed, daher erzwingt ein Refresh-Klick oder eine neue Pause einen
   * frischen `<img>`-Request statt der zwischengespeicherten vorherigen Antwort. */
  protected readonly screenshotRefreshTokens = signal<Record<number, number>>({});
  /** IDs, deren Screenshot-`<img>` gerade fehlschlägt (404/500/Netzwerkfehler gleichermaßen) - blendet das
   * Bild aus statt ein kaputtes Icon zu zeigen. */
  protected readonly screenshotLoadFailedIds = signal<ReadonlySet<number>>(new Set());

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

  // --- Portal-Auto-Fill (U7) --------------------------------------------

  /** Aktueller Automations-Status einer Karte: Live-Polling-Ergebnis, falls schon eines eingetroffen ist,
   * sonst der beim Laden der Liste mitgelieferte Stand. */
  protected automationState(application: Application): AutomationState {
    const live = this.portalFillStatuses()[application.id];
    if (live) {
      return live.automation_state;
    }
    return application.automation_state ?? null;
  }

  private actionNeededReason(application: Application): string | null {
    const live = this.portalFillStatuses()[application.id];
    if (live) {
      return live.action_needed_reason;
    }
    return application.action_needed_reason ?? null;
  }

  /** Konkretes Feld/Frage-Label der Pause (R9) - nur aus dem Live-Status, da `ApplicationRead` es nicht liefert. */
  protected actionNeededDetail(application: Application): string | null {
    return this.portalFillStatuses()[application.id]?.action_needed_detail ?? null;
  }

  /** KTD5: retryable vs. terminal. Bevorzugt das vom Backend abgeleitete `failure_class`; fällt auf eine
   * lokale Ableitung aus dem Grund zurück, solange kein Live-Status vorliegt (z. B. direkt nach `list()`). */
  protected failureClass(application: Application): 'retryable' | 'terminal' {
    const live = this.portalFillStatuses()[application.id];
    if (live?.failure_class) {
      return live.failure_class;
    }
    const reason = this.actionNeededReason(application);
    return reason && RETRYABLE_FAILURE_REASONS.has(reason) ? 'retryable' : 'terminal';
  }

  /** Ob für diese Karte die URL-Eingabe/der Start-Button gezeigt werden soll: noch nie gestartet, oder der
   * letzte Lauf ist fehlgeschlagen (R1) - während `running`/`paused`/`submitted` nicht. */
  protected showPortalFillTrigger(application: Application): boolean {
    const state = this.automationState(application);
    return state === null || state === 'failed';
  }

  protected showActionNeededBanner(application: Application): boolean {
    return this.automationState(application) === 'paused';
  }

  protected showFailureNotice(application: Application): boolean {
    return this.automationState(application) === 'failed' && !this.dismissedFailureIds().has(application.id);
  }

  /** Sperrt Delete/Outcome-Toggle einer Karte, während ihr Auto-Fill-Lauf aktiv ist (R10/R11 - der Browser
   * arbeitet gerade mit dieser Bewerbung, ein Statuswechsel/Löschen darunter wäre inkonsistent). */
  protected isPortalFillActive(application: Application): boolean {
    const state = this.automationState(application);
    return state === 'running' || state === 'paused';
  }

  protected actionNeededCopy(application: Application): string {
    const reason = this.actionNeededReason(application);
    return (reason && ACTION_NEEDED_COPY[reason]) ?? 'Action needed — check the screenshot below, then Continue.';
  }

  /** R3/KTD8: nur bei einer Captcha-Pause zeigt die Karte den Hinweis auf die native Chromium-Remote-
   * Debugging-Verbindung (siehe `PORTAL_FILL_DEBUG_PORT`) - alle anderen Pausengründe kommen mit dem
   * Screenshot allein aus (KTD2). */
  protected isCaptchaPause(application: Application): boolean {
    return this.actionNeededReason(application) === 'captcha';
  }

  protected readonly captchaConnectionInstructions =
    `Open http://localhost:${PORTAL_FILL_DEBUG_PORT} (or chrome://inspect, configured with that address) for a live, clickable view of the page.`;

  /** URL des Pause-Screenshots inkl. Cache-Bust-Token (R2/U2) - siehe `screenshotRefreshTokens`. */
  protected screenshotUrl(application: Application): string {
    const token = this.screenshotRefreshTokens()[application.id] ?? 0;
    return `${this.applicationService.portalFillScreenshotUrl(application.id)}?t=${token}`;
  }

  protected screenshotAvailable(application: Application): boolean {
    return !this.screenshotLoadFailedIds().has(application.id);
  }

  protected onScreenshotLoadError(application: Application): void {
    this.screenshotLoadFailedIds.update((ids) => {
      if (ids.has(application.id)) {
        return ids;
      }
      return new Set(ids).add(application.id);
    });
  }

  protected onRefreshScreenshot(application: Application): void {
    this.clearScreenshotLoadFailure(application.id);
    this.screenshotRefreshTokens.update((tokens) => ({
      ...tokens,
      [application.id]: (tokens[application.id] ?? 0) + 1,
    }));
  }

  private clearScreenshotLoadFailure(applicationId: number): void {
    this.screenshotLoadFailedIds.update((ids) => {
      if (!ids.has(applicationId)) {
        return ids;
      }
      const next = new Set(ids);
      next.delete(applicationId);
      return next;
    });
  }

  protected failureCopy(application: Application): string {
    const reason = this.actionNeededReason(application);
    return (reason && FAILURE_REASON_COPY[reason]) ?? 'The run failed.';
  }

  /** R3/KTD5: Label, ob der Fehler erneut versucht werden darf - inkl. Einstiegspunkt für den Retry. */
  protected failureRetryabilityCopy(application: Application): string {
    return this.failureClass(application) === 'retryable'
      ? 'This failure is retryable — re-enter the form URL below and start again.'
      : 'This failure is not retryable.';
  }

  /** KTD4: der Resume-Button einer Dry-Run-Pause muss ausdrücklich sagen, dass er wirklich sendet. */
  protected continueActionLabel(application: Application): string {
    return this.actionNeededReason(application) === 'dry_run' ? 'Submit for real' : 'Continue';
  }

  protected submittedDateLabel(application: Application): string {
    const iso = application.automation_started_at ?? new Date().toISOString();
    return new Date(iso).toLocaleString();
  }

  protected onDismissFailure(application: Application): void {
    this.dismissedFailureIds.update((ids) => new Set(ids).add(application.id));
  }

  protected onStartPortalFill(application: Application, applicationFormUrl: string, dryRun = false): void {
    const url = applicationFormUrl.trim();
    if (!url || this.portalFillStartingId() !== null) {
      return;
    }

    this.portalFillStartingId.set(application.id);
    this.dismissedFailureIds.update((ids) => {
      if (!ids.has(application.id)) {
        return ids;
      }
      const next = new Set(ids);
      next.delete(application.id);
      return next;
    });

    this.applicationService.start(application.id, url, dryRun).subscribe({
      next: (updated) => {
        this.portalFillStartingId.set(null);
        this.replaceApplication(updated);
        this.setPortalFillStatus(application.id, {
          automation_state: updated.automation_state ?? null,
          action_needed_reason: updated.action_needed_reason ?? null,
          action_needed_detail: null,
          failure_class: null,
        });
        this.pollPortalFillPhase(application.id, 'running');
      },
      error: (error: HttpErrorResponse) => {
        this.portalFillStartingId.set(null);
        const message =
          (error.error?.detail as string | undefined) ?? 'The portal-fill run could not be started.';
        this.snackBar.open(message, 'OK', { duration: 4000 });
      },
    });
  }

  protected onContinuePortalFill(application: Application): void {
    this.applicationService.continuePortalFill(application.id).subscribe({
      error: (error: HttpErrorResponse) => {
        const message = (error.error?.detail as string | undefined) ?? 'Could not continue the run.';
        this.snackBar.open(message, 'OK', { duration: 4000 });
      },
    });
  }

  protected onCancelPortalFill(application: Application): void {
    this.applicationService.cancelPortalFill(application.id).subscribe({
      next: (updated) => {
        this.replaceApplication(updated);
        this.setPortalFillStatus(application.id, {
          automation_state: updated.automation_state ?? null,
          action_needed_reason: updated.action_needed_reason ?? null,
          action_needed_detail: null,
          failure_class: null,
        });
      },
      error: (error: HttpErrorResponse) => {
        const message = (error.error?.detail as string | undefined) ?? 'Could not cancel the run.';
        this.snackBar.open(message, 'OK', { duration: 4000 });
      },
    });
  }

  private replaceApplication(updated: Application): void {
    this.applications.update((applications) =>
      applications.map((item) => (item.id === updated.id ? updated : item)),
    );
  }

  /** Übernimmt einen gepollten Status in die Live-Overlay-Map (siehe `portalFillStatuses`) und stößt das
   * Tab-Titel-Signal (R10/R11) an, sobald diese Karte GERADE erst `paused` wird - `markGenerationSettled()`
   * ist selbst dafür zuständig, das nur zu tun, während der Tab im Hintergrund ist (siehe `TabTitleService`),
   * hier wird nur die Transition (statt jedes einzelnen `paused`-Ticks) erkannt. */
  private setPortalFillStatus(applicationId: number, status: PortalFillStatus): void {
    const previous = this.portalFillStatuses()[applicationId];
    if (
      previous?.automation_state === status.automation_state &&
      previous?.action_needed_reason === status.action_needed_reason &&
      previous?.action_needed_detail === status.action_needed_detail &&
      previous?.failure_class === status.failure_class
    ) {
      return; // unveränderter Tick - kein Signal-Write/Change-Detection-Zyklus nötig
    }
    const wasPaused = previous?.automation_state === 'paused';
    this.portalFillStatuses.update((map) => ({ ...map, [applicationId]: status }));
    if (status.automation_state === 'paused' && !wasPaused) {
      this.tabTitleService.markGenerationSettled();
      // Neue Pause: ein vorheriger Lade-Fehlschlag darf die Karte nicht dauerhaft ohne Screenshot
      // lassen - der neue Pause-Screenshot verdient einen frischen Ladeversuch. Das Cache-Bust-
      // Token MUSS hier ebenfalls erhöht werden (nicht nur bei manuellem Refresh, siehe
      // `onRefreshScreenshot`) - sonst bleibt `screenshotUrl()` zwischen zwei Pausen INNERHALB
      // desselben Laufs (z. B. captcha -> continue -> pre_submit_confirmation) byte-identisch,
      // und ein `<img>`, das die erste URL bereits geladen hat, zeigt den veralteten Screenshot
      // der ERSTEN Pause an, statt den der neuen - genau während der Review, die R10/R11 als
      // sicherheitsrelevant markieren.
      this.clearScreenshotLoadFailure(applicationId);
      this.screenshotRefreshTokens.update((tokens) => ({
        ...tokens,
        [applicationId]: (tokens[applicationId] ?? 0) + 1,
      }));
    }
  }

  /** Pollt eine Phase (`running`: bounded per Timeout; `paused`: unbounded, da R10/R11 menschengesteuert
   * und damit von Natur aus zeitlich offen sind) - exakt dasselbe RxJS-Muster wie
   * `ApplicationEditorComponent.pollForRunningGeneration` (timer + switchMap + per-Tick catchError +
   * takeUntilDestroyed), zusätzlich mit `takeWhile`, um bei einem Wechsel in die jeweils andere Phase
   * sauber zu stoppen, ohne den letzten Stand zu verlieren. Wechselt der Status in die andere Phase,
   * übernimmt ein rekursiver Aufruf mit der neuen Phase weiter. */
  private pollPortalFillPhase(applicationId: number, phase: 'running' | 'paused'): void {
    const otherPhase = phase === 'running' ? 'paused' : 'running';
    const poll$ = timer(
      ApplicationsComponent.PORTAL_FILL_POLL_INTERVAL_MS,
      ApplicationsComponent.PORTAL_FILL_POLL_INTERVAL_MS,
    ).pipe(
      switchMap(() =>
        this.applicationService.getPortalFillStatus(applicationId).pipe(catchError(() => of(null))),
      ),
      takeWhile((status) => status === null || status.automation_state === phase, true),
    );

    // Bounded nur in der `running`-Phase (mirrort die ursprüngliche, für den einzelnen LLM-Call
    // bemessene `pollForRunningGeneration`-Semantik) - `paused` bleibt bewusst unbounded (R10/R11).
    const bounded$ =
      phase === 'running'
        ? poll$.pipe(takeUntil(timer(ApplicationsComponent.PORTAL_FILL_RUNNING_TIMEOUT_MS)))
        : poll$;

    bounded$.pipe(takeUntilDestroyed(this.destroyRef)).subscribe((status) => {
      if (status === null) {
        return;
      }
      this.setPortalFillStatus(applicationId, status);
      if (status.automation_state === otherPhase) {
        this.pollPortalFillPhase(applicationId, otherPhase);
      }
    });
  }
}
