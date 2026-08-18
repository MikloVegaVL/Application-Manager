import { HttpClient, HttpParams } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';

import { environment } from '../../../environments/environment';
import { JobOffer, JobOfferRead, JobSearchResponse } from '../models/job-offer.model';

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
  searchJobs(keywords: string, location?: string, fallbackUrl?: string): Observable<JobSearchResponse> {
    let params = new HttpParams().set('keywords', keywords);
    if (location) {
      params = params.set('location', location);
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
}
