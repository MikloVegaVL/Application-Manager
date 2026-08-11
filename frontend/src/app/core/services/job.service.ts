import { HttpClient, HttpParams } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';

import { environment } from '../../../environments/environment';
import { JobOffer, JobOfferRead } from '../models/job-offer.model';

/**
 * Kommuniziert mit den Job-Endpunkten des Backends
 * (`/api/jobs/search`, `/api/jobs/save`, siehe `backend/app/api/jobs.py`).
 */
@Injectable({ providedIn: 'root' })
export class JobService {
  private readonly http = inject(HttpClient);
  private readonly baseUrl = `${environment.apiBaseUrl}/jobs`;

  /**
   * Sucht Stellenangebote über die Arbeitsagentur-API und - falls diese
   * keine Treffer liefert - optional über den generischen Fallback-Scraper.
   */
  searchJobs(keywords: string, location?: string, fallbackUrl?: string): Observable<JobOffer[]> {
    let params = new HttpParams().set('keywords', keywords);
    if (location) {
      params = params.set('location', location);
    }
    if (fallbackUrl) {
      params = params.set('fallback_url', fallbackUrl);
    }

    return this.http.get<JobOffer[]>(`${this.baseUrl}/search`, { params });
  }

  /** Speichert ein ausgewähltes Suchergebnis dauerhaft als `JobOffer`. */
  saveJob(job: JobOffer): Observable<JobOfferRead> {
    return this.http.post<JobOfferRead>(`${this.baseUrl}/save`, job);
  }
}
