import { HttpClient, HttpParams, HttpResponse } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';

import { environment } from '../../../environments/environment';
import { SentEmail, SentEmailFilterParams } from '../models/sent-email.model';

/**
 * Kommuniziert mit den Sent-Emails-Endpunkten des Backends
 * (`/api/sent-emails`, siehe `backend/app/api/sent_emails.py`).
 */
@Injectable({ providedIn: 'root' })
export class SentEmailService {
  private readonly http = inject(HttpClient);
  private readonly baseUrl = `${environment.apiBaseUrl}/sent-emails`;

  /** Listet das Protokoll, optional gefiltert (R4/R7). */
  list(filter: SentEmailFilterParams): Observable<SentEmail[]> {
    return this.http.get<SentEmail[]>(this.baseUrl, { params: this.buildParams(filter) });
  }

  /**
   * Exportiert die aktuell gefilterte Ansicht als PDF (R8) - derselbe
   * Filter-Vertrag wie `list()` (KTD4), damit der Export exakt die
   * angezeigte Ansicht widerspiegelt.
   */
  exportCurrent(filter: SentEmailFilterParams): Observable<HttpResponse<Blob>> {
    return this.http.get(`${this.baseUrl}/export`, {
      params: this.buildParams(filter),
      responseType: 'blob',
      observe: 'response',
    });
  }

  /** Exportiert das vollständige Protokoll als PDF, unabhängig von aktiven Filtern (R9). */
  exportAll(): Observable<HttpResponse<Blob>> {
    return this.http.get(`${this.baseUrl}/export/all`, {
      responseType: 'blob',
      observe: 'response',
    });
  }

  /** Löscht einen einzelnen Log-Eintrag. */
  deleteById(sentEmailId: number): Observable<void> {
    return this.http.delete<void>(`${this.baseUrl}/${sentEmailId}`);
  }

  private buildParams(filter: SentEmailFilterParams): HttpParams {
    let params = new HttpParams();
    if (filter.company) {
      params = params.set('company', filter.company);
    }
    if (filter.sender_email) {
      params = params.set('sender_email', filter.sender_email);
    }
    if (filter.date_from) {
      params = params.set('date_from', filter.date_from);
    }
    if (filter.date_to) {
      params = params.set('date_to', filter.date_to);
    }
    if (filter.outcome) {
      params = params.set('outcome', filter.outcome);
    }
    return params;
  }
}
