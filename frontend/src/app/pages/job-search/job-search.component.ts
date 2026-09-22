import { ChangeDetectionStrategy, Component, computed, inject, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { HttpErrorResponse } from '@angular/common/http';
import { FormBuilder, ReactiveFormsModule, Validators } from '@angular/forms';
import { Router } from '@angular/router';

import { MatButtonModule } from '@angular/material/button';
import { MatChipsModule } from '@angular/material/chips';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatIconModule } from '@angular/material/icon';
import { MatInputModule } from '@angular/material/input';
import { MatProgressSpinnerModule } from '@angular/material/progress-spinner';
import { MatSelectModule } from '@angular/material/select';
import { MatSnackBar } from '@angular/material/snack-bar';

import {
  ApplicationEmailLookupResult,
  JobOffer,
  toApplicationEmailLookupRequest,
} from '../../core/models/job-offer.model';
import { JobSearchStateService } from '../../core/services/job-search-state.service';
import { JobService, jobSaveConflictId } from '../../core/services/job.service';
import { extractEmail } from '../../core/utils/email-extraction.util';
import { sourceLabel as getSourceLabel } from '../../core/utils/source-label.util';
import {
  CompactCardChip,
  CompactCardComponent,
  CompactCardDetailRowItem,
  CompactCardMenuItem,
  CompactCardViewModel,
} from '../../shared/compact-card/compact-card.component';

@Component({
  selector: 'app-job-search',
  standalone: true,
  imports: [
    ReactiveFormsModule,
    MatButtonModule,
    MatChipsModule,
    MatFormFieldModule,
    MatIconModule,
    MatInputModule,
    MatProgressSpinnerModule,
    MatSelectModule,
    CompactCardComponent,
  ],
  templateUrl: './job-search.component.html',
  styleUrl: './job-search.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class JobSearchComponent {
  private readonly formBuilder = inject(FormBuilder);
  private readonly jobService = inject(JobService);
  private readonly router = inject(Router);
  private readonly snackBar = inject(MatSnackBar);
  /** Hält Trefferliste/Status über die Komponenten-Lebensdauer hinaus am
   * Leben, damit ein Zurücknavigieren (z. B. aus dem Editor) die letzte
   * Suche nicht verwirft - siehe JobSearchStateService-Doc. */
  private readonly state = inject(JobSearchStateService);

  /** Umkreis-Stufen in km (KTD3) - Jooble rundet einen gewählten Wert intern
   * auf die nächstgrößere eigene Stufe auf (siehe `JoobleJobsClient`). */
  protected readonly radiusKmOptions = ['5', '10', '25', '50', '100', '200'];

  protected readonly searchForm = this.formBuilder.nonNullable.group({
    keywords: [this.state.keywords(), [Validators.required, Validators.minLength(2)]],
    location: [this.state.location()],
    radiusKm: [{ value: this.state.radiusKm(), disabled: !this.state.location().trim() }],
  });

  /** Der Umkreis ist ohne Ort bedeutungslos (R2) - deaktiviert/aktiviert das
   * Control passend zum Ort-Feld, statt eine sinnlose Auswahl zuzulassen. */
  private readonly toggleRadiusOnLocationChange = this.searchForm.controls.location.valueChanges
    .pipe(takeUntilDestroyed())
    .subscribe((location) => {
      const radiusControl = this.searchForm.controls.radiusKm;
      const shouldEnable = !!location.trim();
      // `enable()`/`disable()` re-run validity recalculation even when the
      // control is already in the target state - guard against re-running
      // that on every keystroke, not just on the empty<->non-empty transition.
      if (shouldEnable === radiusControl.enabled) {
        return;
      }
      if (shouldEnable) {
        radiusControl.enable({ emitEvent: false });
      } else {
        radiusControl.disable({ emitEvent: false });
      }
    });

  protected readonly results = this.state.results;
  /** Status pro Quelle (Arbeitsagentur/LinkedIn/Xing) der letzten Suche - siehe R5. */
  protected readonly sourceStatuses = this.state.sourceStatuses;
  protected readonly loading = signal(false);
  protected readonly hasSearched = this.state.hasSearched;
  protected readonly errorMessage = this.state.errorMessage;

  protected readonly unavailableSources = computed(() =>
    this.sourceStatuses().filter((source) => source.status === 'unavailable'),
  );

  /** Aktuell als Filter gewählte Quellen-Plattformen; leer = alle Treffer anzeigen. */
  protected readonly selectedSources = signal<string[]>([]);

  protected readonly hasActiveSourceFilter = computed(() => this.selectedSources().length > 0);

  /** Auf die gewählten Quellen reduzierte Trefferliste (rein clientseitig,
   * `results` bleibt vollständig - vgl. den Status-Filter der Bewerbungen). */
  protected readonly filteredResults = computed(() => {
    const selected = this.selectedSources();
    if (selected.length === 0) {
      return this.results();
    }
    return this.results().filter((job) => selected.includes(job.source_platform));
  });

  /** True, wenn jede abgefragte Quelle in der letzten Suche unavailable war -
   * dann ist eine leere Ergebnisliste kein "falscher Suchbegriff", sondern
   * ein Erreichbarkeitsproblem (siehe Design-Review zu U7). */
  protected readonly allSourcesUnavailable = computed(
    () => this.sourceStatuses().length > 0 && this.unavailableSources().length === this.sourceStatuses().length,
  );

  /** True, wenn die Liste leer ist, weil alle Treffer bereits beworben
   * wurden - dann statt des generischen Leerzustands die eigene Meldung
   * (R4/R6). */
  protected readonly allResultsApplied = computed(
    () => this.results().length === 0 && this.state.appliedHiddenCount() > 0,
  );

  private readonly savedJobIds = this.state.savedJobIds;
  protected readonly savingSourceUrl = signal<string | null>(null);
  protected readonly generatingSourceUrl = signal<string | null>(null);
  /** Per Row laufende E-Mail-Suchen, gekeyt nach `source_url` (KTD7/R1). */
  private readonly lookupLoadingUrls = signal<Set<string>>(new Set());

  onSearch(): void {
    if (this.searchForm.invalid) {
      this.searchForm.markAllAsTouched();
      return;
    }

    const { keywords, location, radiusKm } = this.searchForm.getRawValue();
    this.state.keywords.set(keywords);
    this.state.location.set(location);
    this.state.radiusKm.set(radiusKm);
    this.loading.set(true);
    this.errorMessage.set(null);
    // Status der vorherigen Suche zurücksetzen - sonst könnte z. B. noch
    // "LinkedIn nicht verfügbar" von der letzten Suche angezeigt werden,
    // während die neue Suche noch läuft.
    this.sourceStatuses.set([]);
    // Ein Quellen-Filter der letzten Suche passt nicht zu den neuen Quellen.
    this.selectedSources.set([]);
    // Der "bereits beworben"-Zähler der letzten Suche gilt nicht mehr.
    this.state.appliedHiddenCount.set(0);
    this.hasSearched.set(true);

    this.jobService
      .searchJobs(keywords.trim(), {
        location: location.trim() || undefined,
        radiusKm: radiusKm || undefined,
      })
      .subscribe({
        next: (response) => {
          this.results.set(response.results);
          this.sourceStatuses.set(response.sources);
          this.state.appliedHiddenCount.set(response.excluded_applied_count ?? 0);
          this.loading.set(false);
        },
        error: (error: HttpErrorResponse) => {
          console.error('Jobsuche fehlgeschlagen', error);
          this.results.set([]);
          this.sourceStatuses.set([]);
          this.state.appliedHiddenCount.set(0);
          this.loading.set(false);
          this.errorMessage.set('The job search failed. Please try again later.');
        },
      });
  }

  /** Leert die angezeigte Trefferliste, um Platz für eine neue Suche zu
   * schaffen - lässt Suchbegriff/Ort im Formular unangetastet, damit man
   * dieselbe Suche leicht abwandeln kann. */
  onClearResults(): void {
    this.selectedSources.set([]);
    this.state.clearResults();
  }

  /** Übernimmt die im Quellen-Chip-Listbox gewählten Plattformen
   * (Mehrfachauswahl; leere Auswahl = alle Treffer). */
  onSourceFilterChange(selected: string[] | string | null): void {
    this.selectedSources.set(Array.isArray(selected) ? selected : selected ? [selected] : []);
  }

  clearSourceFilter(): void {
    this.selectedSources.set([]);
  }

  sourceLabel(platform: string): string {
    return getSourceLabel(platform);
  }

  /** Empfängeradresse aus dem Anzeigentext - dieselbe Extraktion wie im
   * Editor (siehe `email-extraction.util`). `null`, wenn die Anzeige keine
   * E-Mail nennt; die Karte zeigt dann einen Platzhalter. */
  recipientEmail(job: JobOffer): string | null {
    return extractEmail(job.description_text);
  }

  isSaved(job: JobOffer): boolean {
    return this.savedJobIds().has(job.source_url);
  }

  isSaving(job: JobOffer): boolean {
    return this.savingSourceUrl() === job.source_url;
  }

  isGenerating(job: JobOffer): boolean {
    return this.generatingSourceUrl() === job.source_url;
  }

  isLookingUp(job: JobOffer): boolean {
    return this.lookupLoadingUrls().has(job.source_url);
  }

  /** Ergebnis der letzten Suche für diesen Job (oder `null`) - steuert die
   * Status-Anzeige (`not-found` vs. `failed`, siehe A5/KTD4). */
  lookupResult(job: JobOffer): ApplicationEmailLookupResult | null {
    return this.state.applicationEmailResult(job.source_url);
  }

  /** Gefundene Bewerbungs-E-Mail aus dem Lookup-Cache - `null`, solange kein
   * `found`-Ergebnis vorliegt. */
  applicationEmail(job: JobOffer): string | null {
    const result = this.lookupResult(job);
    return result?.status === 'found' ? (result.email ?? null) : null;
  }

  applicationEmailSourceUrl(job: JobOffer): string | null {
    const result = this.lookupResult(job);
    return result?.status === 'found' ? (result.source_url ?? null) : null;
  }

  /** Empfängeradresse für die Karte: zuerst das Lookup-Ergebnis, dann die
   * Extraktion aus dem Anzeigentext (R12 - die bestehende Extraktion bleibt
   * unverändert). */
  displayedRecipient(job: JobOffer): string | null {
    return this.applicationEmail(job) ?? this.recipientEmail(job);
  }

  /**
   * Per-`source_url` view-models for the U4 card layout (R5/R6/R11/R12) -
   * `computed()` rebuilds this `Map` only when a signal read while building
   * it actually changes (`filteredResults`, `savedJobIds`,
   * `savingSourceUrl`, `generatingSourceUrl`, `lookupLoadingUrls`, the
   * state service's lookup-result cache). `cardViewModel()` below then only
   * does a `Map` lookup per template call, returning the *same* object
   * reference across change-detection ticks for an unaffected card - which
   * is what lets `CompactCardComponent`'s `OnPush` skip re-rendering it.
   * Calling `buildCardViewModel()` directly from the `@for` binding instead
   * would allocate a fresh object every tick and defeat that.
   */
  private readonly cardViewModels = computed<Map<string, CompactCardViewModel>>(() => {
    const map = new Map<string, CompactCardViewModel>();
    for (const job of this.filteredResults()) {
      map.set(job.source_url, this.buildCardViewModel(job));
    }
    return map;
  });

  cardViewModel(job: JobOffer): CompactCardViewModel {
    return this.cardViewModels().get(job.source_url) ?? this.buildCardViewModel(job);
  }

  /** True while a request this card's primary action or `⋮` menu can
   * trigger is in flight (R12) - "Open ad" and "Source of this address"
   * are plain navigation links with no async step, so they never
   * contribute. */
  isCardBusy(job: JobOffer): boolean {
    return this.isSaving(job) || this.isGenerating(job) || this.isLookingUp(job);
  }

  private buildCardViewModel(job: JobOffer): CompactCardViewModel {
    const chips: CompactCardChip[] = [{ label: this.sourceLabel(job.source_platform) }];
    const lookup = this.lookupResult(job);
    if (lookup) {
      chips.push({ label: this.lookupStatusChipLabel(lookup.status) });
    }

    const detailRowItems: CompactCardDetailRowItem[] = [];
    const recipient = this.displayedRecipient(job);
    if (recipient) {
      detailRowItems.push({ label: `Recipient: ${recipient}` });
    }

    const menuItems: CompactCardMenuItem[] = [
      {
        id: 'open-ad',
        label: 'Open ad',
        icon: 'open_in_new',
        link: { href: job.source_url, target: '_blank', rel: 'noopener noreferrer' },
      },
    ];
    const sourceUrl = this.applicationEmailSourceUrl(job);
    if (sourceUrl) {
      // R11: mirrors the Applications sent-to-email placement, but as a real
      // anchor (not the plain-text detail row above) since it navigates.
      menuItems.push({
        id: 'source-link',
        label: 'Source of this address',
        icon: 'open_in_new',
        link: { href: sourceUrl, target: '_blank', rel: 'noopener noreferrer' },
      });
    }
    menuItems.push({
      id: 'save-job',
      label: this.isSaved(job) ? 'Saved' : 'Save job',
      icon: this.isSaved(job) ? 'bookmark_added' : 'bookmark_add',
      disabled: this.isSaved(job) || this.isSaving(job),
    });
    // R8: keep the existing `extractEmail` gating for "Find email (again)"
    // untouched - it stays keyed off `recipientEmail()`, not lookup state.
    if (!this.recipientEmail(job)) {
      menuItems.push({
        id: 'find-email',
        label: lookup ? 'Find email again' : 'Find email',
        icon: 'travel_explore',
        disabled: this.isLookingUp(job),
      });
    }

    return {
      title: job.title,
      company: job.company,
      location: job.location ?? '',
      chips,
      snippet: job.description_text || 'No description available.',
      primaryAction: {
        label: 'Generate application',
        disabled: this.isGenerating(job),
      },
      menuItems,
      detailRowItems,
    };
  }

  private lookupStatusChipLabel(status: ApplicationEmailLookupResult['status']): string {
    switch (status) {
      case 'found':
        return 'Application email found';
      case 'not-found':
        return 'No application email found';
      case 'failed':
        return "Couldn't reach the employer's site — try again";
    }
  }

  /** Routes a `⋮` menu selection (id from `CompactCardMenuItem.id`) to the
   * existing handler - "Open ad" and "Source of this address" need none,
   * they navigate natively via the view-model's `link`. */
  onMenuAction(job: JobOffer, itemId: string): void {
    switch (itemId) {
      case 'save-job':
        this.onSaveJob(job);
        break;
      case 'find-email':
        this.onFindApplicationEmail(job);
        break;
    }
  }

  /**
   * Startet die On-Demand-Suche (R1/R2). Die Karte übergibt denselben Payload
   * wie der Editor (KTD1); `force` wird gesetzt, sobald bereits ein Ergebnis
   * vorliegt, damit der Re-Run-Affordance (R11) tatsächlich neu sucht - und
   * im Payload ans Backend mitgeschickt, sonst liefert ein gespeicherter Job
   * nur die persistierte Adresse zurück.
   */
  onFindApplicationEmail(job: JobOffer): void {
    if (this.isLookingUp(job)) {
      return;
    }
    const force = this.lookupResult(job) !== null;
    this.setLookupLoading(job.source_url, true);
    this.state
      .lookupApplicationEmail(toApplicationEmailLookupRequest(job, force), { force })
      .subscribe({
        next: () => {
          // Das Ergebnis ist im State-Service bereits gecacht (KTD7).
          this.setLookupLoading(job.source_url, false);
        },
        error: (error: HttpErrorResponse) => {
          // Ein echter HTTP-Fehler ist laut A5 ein `failed`-Ergebnis, kein
          // stiller No-Op - sonst bliebe die Karte ohne Rückmeldung.
          console.error('Application-email lookup failed', error);
          this.state.cacheApplicationEmailResult(job.source_url, { status: 'failed' });
          this.setLookupLoading(job.source_url, false);
        },
      });
  }

  private setLookupLoading(sourceUrl: string, loading: boolean): void {
    const updated = new Set(this.lookupLoadingUrls());
    if (loading) {
      updated.add(sourceUrl);
    } else {
      updated.delete(sourceUrl);
    }
    this.lookupLoadingUrls.set(updated);
  }

  /** Reicht eine gecachte, gefundene Adresse beim Speichern mit, damit sie
   * persistiert wird (KTD7/A1). */
  private withCachedApplicationEmail(job: JobOffer): JobOffer {
    const email = this.applicationEmail(job);
    if (!email) {
      return job;
    }
    return {
      ...job,
      application_email: email,
      application_email_source_url: this.applicationEmailSourceUrl(job),
    };
  }

  onSaveJob(job: JobOffer): void {
    if (this.isSaved(job) || this.isSaving(job)) {
      return;
    }
    this.savingSourceUrl.set(job.source_url);

    this.jobService.saveJob(this.withCachedApplicationEmail(job)).subscribe({
      next: (saved) => {
        this.state.cacheSavedJob(job.source_url, saved.id);
        this.state.removeResult(job.source_url);
        this.savingSourceUrl.set(null);
        this.snackBar.open(`"${job.title}" was saved.`, 'OK', { duration: 3000 });
      },
      error: (error: HttpErrorResponse) => {
        this.savingSourceUrl.set(null);
        const conflictId = jobSaveConflictId(error);
        if (conflictId !== null) {
          // Job existiert bereits serverseitig (z. B. nach einem Reload,
          // siehe JobSearchStateService) - Cache nachziehen statt nur zu
          // melden, sonst bliebe der Button dauerhaft im "speichern"-Zustand.
          this.state.cacheSavedJob(job.source_url, conflictId);
          this.state.removeResult(job.source_url);
          this.snackBar.open('This job has already been saved.', 'OK', { duration: 3000 });
          return;
        }
        this.snackBar.open('The job could not be saved.', 'OK', { duration: 3000 });
      },
    });
  }

  /** Speichert den Job (falls nötig) und leitet zur Editor-Komponente mit der Job-ID weiter. */
  onGenerateApplication(job: JobOffer): void {
    const cachedId = this.savedJobIds().get(job.source_url);
    if (cachedId !== undefined) {
      this.state.removeResult(job.source_url);
      this.navigateToEditor(cachedId);
      return;
    }
    if (this.isGenerating(job)) {
      return;
    }
    this.generatingSourceUrl.set(job.source_url);

    this.jobService.saveJob(this.withCachedApplicationEmail(job)).subscribe({
      next: (saved) => {
        this.state.cacheSavedJob(job.source_url, saved.id);
        this.state.removeResult(job.source_url);
        this.generatingSourceUrl.set(null);
        this.navigateToEditor(saved.id);
      },
      error: (error: HttpErrorResponse) => {
        this.generatingSourceUrl.set(null);
        const conflictId = jobSaveConflictId(error);
        if (conflictId !== null) {
          // Job existiert bereits (z. B. aus einer früheren Session) - statt
          // in einer Sackgasse zu enden, direkt zum bestehenden Editor
          // weiterleiten (ce-debug-Fix, 2026-08-24: der Job tauchte vorher
          // nirgends mehr auf, siehe der `save_job`-Backfill im Backend).
          this.state.cacheSavedJob(job.source_url, conflictId);
          this.state.removeResult(job.source_url);
          this.navigateToEditor(conflictId);
          return;
        }
        this.snackBar.open('The application could not be started.', 'OK', { duration: 4000 });
      },
    });
  }

  private navigateToEditor(jobOfferId: number): void {
    void this.router.navigate(['/editor', jobOfferId]);
  }
}
