import { Injectable, signal } from '@angular/core';

import { JobOffer, SourceStatus } from '../models/job-offer.model';

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
  readonly keywords = signal('');
  readonly location = signal('');
  readonly results = signal<JobOffer[]>([]);
  readonly sourceStatuses = signal<SourceStatus[]>([]);
  readonly hasSearched = signal(false);
  readonly errorMessage = signal<string | null>(null);

  /** Merkt sich bereits gespeicherte Jobs (source_url -> DB-ID), um Doppel-Saves zu vermeiden. */
  readonly savedJobIds = signal<Map<string, number>>(new Map());

  cacheSavedJob(sourceUrl: string, id: number): void {
    const updated = new Map(this.savedJobIds());
    updated.set(sourceUrl, id);
    this.savedJobIds.set(updated);
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
