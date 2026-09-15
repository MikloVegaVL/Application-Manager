import { Injectable, inject, signal } from '@angular/core';
import { Observable, of, tap } from 'rxjs';

import {
  ApplicationEmailLookupRequest,
  ApplicationEmailLookupResult,
  JobOffer,
  SourceStatus,
} from '../models/job-offer.model';
import { JobService } from './job.service';

/**
 * Hält die zuletzt gesuchten Stellenangebote über die Lebensdauer der
 * Angular-Anwendung hinweg (nicht nur der `JobSearchComponent`-Instanz).
 *
 * `providedIn: 'root'` macht daraus ein Singleton - navigiert man von der
 * Jobsuche weg (z. B. in den Bewerbungs-Editor) und zurück, wird
 * `JobSearchComponent` neu instanziiert, aber dieser Service nicht, daher
 * bleiben Trefferliste, Quellen-Status und bereits gespeicherte Jobs
 * erhalten. Überlebt keinen vollständigen Seiten-Reload (bewusst kein
 * localStorage - siehe ce-debug-Feature, 2026-08-20).
 */
@Injectable({ providedIn: 'root' })
export class JobSearchStateService {
  private readonly jobService = inject(JobService);

  readonly keywords = signal('');
  readonly location = signal('');
  readonly results = signal<JobOffer[]>([]);
  readonly sourceStatuses = signal<SourceStatus[]>([]);
  readonly hasSearched = signal(false);
  readonly errorMessage = signal<string | null>(null);

  /** Merkt sich bereits gespeicherte Jobs (source_url -> DB-ID), um Doppel-Saves zu vermeiden. */
  readonly savedJobIds = signal<Map<string, number>>(new Map());

  /**
   * Ergebnis der Bewerbungs-E-Mail-Suche pro `source_url` (KTD7). Unsaved
   * Karten-Jobs haben keine persistierte Zeile; ihr Ergebnis bleibt so
   * in-session sichtbar und wandert beim Speichern in den Save-Payload.
   */
  readonly applicationEmailResults = signal<Map<string, ApplicationEmailLookupResult>>(new Map());

  cacheSavedJob(sourceUrl: string, id: number): void {
    const updated = new Map(this.savedJobIds());
    updated.set(sourceUrl, id);
    this.savedJobIds.set(updated);
  }

  /** Liefert das gespeicherte Suchergebnis (oder `null`) - für Karte und Dialog. */
  applicationEmailResult(sourceUrl: string): ApplicationEmailLookupResult | null {
    return this.applicationEmailResults().get(sourceUrl) ?? null;
  }

  cacheApplicationEmailResult(sourceUrl: string, result: ApplicationEmailLookupResult): void {
    const updated = new Map(this.applicationEmailResults());
    updated.set(sourceUrl, result);
    this.applicationEmailResults.set(updated);
  }

  /**
   * Führt die Bewerbungs-E-Mail-Suche aus und teilt das Ergebnis zwischen
   * Karte und Dialog. Ein bereits gecachtes Ergebnis wird ohne erneuten
   * Request zurückgegeben; `force` erzwingt einen neuen Lookup (R11-Re-Run).
   */
  lookupApplicationEmail(
    payload: ApplicationEmailLookupRequest,
    options: { force?: boolean } = {},
  ): Observable<ApplicationEmailLookupResult> {
    const cached = this.applicationEmailResults().get(payload.source_url);
    if (cached && !options.force) {
      return of(cached);
    }
    return this.jobService
      .findApplicationEmail(payload)
      .pipe(tap((result) => this.cacheApplicationEmailResult(payload.source_url, result)));
  }

  /** Leert die Trefferliste für eine neue Suche - `savedJobIds` bleibt
   * bewusst bestehen: ein bereits gespeicherter Job ist weiterhin
   * gespeichert, unabhängig davon, ob die aktuelle Liste geleert wird. */
  clearResults(): void {
    this.results.set([]);
    this.sourceStatuses.set([]);
    this.hasSearched.set(false);
    this.errorMessage.set(null);
  }
}
