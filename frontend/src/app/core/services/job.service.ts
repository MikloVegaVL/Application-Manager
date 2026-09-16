import { HttpClient, HttpErrorResponse, HttpParams } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';

import { environment } from '../../../environments/environment';
import {
  ApplicationEmailLookupRequest,
  ApplicationEmailLookupResult,
  JobOffer,
  JobOfferRead,
  JobSaveConflictDetail,
  JobSearchResponse,
} from '../models/job-offer.model';

/** Liest `job_offer_id` aus dem 409-Detail von `POST /jobs/save` (siehe
 * `JobSaveConflictDetail` und das Backend-Backfill in `save_job`) - `null`,
 * wenn der Fehler kein solcher Konflikt war. Gemeinsam genutzt von
 * `JobSearchComponent` und `ApplicationsComponent`, damit dieselbe
 * 409-Auswertung nicht ein drittes Mal dupliziert wird. */
export function jobSaveConflictId(error: HttpErrorResponse): number | null {
  if (error.status !== 409) {
    return null;
  }
  const detail = error.error?.detail as JobSaveConflictDetail | undefined;
  return typeof detail?.job_offer_id === 'number' ? detail.job_offer_id : null;
}

/**
 * Kommuniziert mit den Job-Endpunkten des Backends
 * (`/api/jobs/search`, `/api/jobs/save`, siehe `backend/app/api/jobs.py`).
 */
@Injectable({ providedIn: 'root' })
export class JobService {
  private readonly http = inject(HttpClient);
  private readonly baseUrl = `${environment.apiBaseUrl}/jobs`;

  /**
   * Sucht Stellenangebote gleichzeitig über Arbeitsagentur, LinkedIn und
   * Xing (und bei Bedarf über den generischen Fallback-Scraper). Liefert
   * die zusammengeführten Ergebnisse plus einen Status pro Quelle.
   */
  searchJobs(
    keywords: string,
    location?: string,
    radiusKm?: string,
    fallbackUrl?: string,
  ): Observable<JobSearchResponse> {
    let params = new HttpParams().set('keywords', keywords);
    if (location) {
      params = params.set('location', location);
    }
    if (radiusKm) {
      params = params.set('radius_km', radiusKm);
    }
    if (fallbackUrl) {
      params = params.set('fallback_url', fallbackUrl);
    }

    return this.http.get<JobSearchResponse>(`${this.baseUrl}/search`, { params });
  }

  /** Speichert ein ausgewähltes Suchergebnis dauerhaft als `JobOffer`. */
  saveJob(job: JobOffer): Observable<JobOfferRead> {
    return this.http.post<JobOfferRead>(`${this.baseUrl}/save`, job);
  }

  /** Lädt ein einzelnes gespeichertes Stellenangebot (z. B. für den Editor). */
  getJob(jobOfferId: number): Observable<JobOfferRead> {
    return this.http.get<JobOfferRead>(`${this.baseUrl}/${jobOfferId}`);
  }

  /**
   * Stößt die On-Demand-Suche nach einer Bewerbungs-E-Mail an (R1). Der
   * Endpunkt liefert `found`/`not-found`/`failed` immer mit HTTP 200; ein
   * echter HTTP-Fehler wird von den Aufrufern wie `failed` behandelt.
   */
  findApplicationEmail(
    payload: ApplicationEmailLookupRequest,
  ): Observable<ApplicationEmailLookupResult> {
    return this.http.post<ApplicationEmailLookupResult>(
      `${this.baseUrl}/application-email-lookup`,
      payload,
    );
  }
}
