import { HttpClient } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';

import { environment } from '../../../environments/environment';
import {
  Application,
  ApplicationSendPayload,
  ApplicationUpdatePayload,
} from '../models/application.model';

/**
 * Kommuniziert mit den Bewerbungs-Endpunkten des Backends
 * (siehe `backend/app/api/applications.py`).
 */
@Injectable({ providedIn: 'root' })
export class ApplicationService {
  private readonly http = inject(HttpClient);
  private readonly baseUrl = `${environment.apiBaseUrl}/applications`;

  /** Lädt alle gespeicherten Bewerbungen (neueste zuerst) für die Übersichtsseite. */
  list(): Observable<Application[]> {
    return this.http.get<Application[]>(this.baseUrl);
  }

  /** Stößt die KI-gestützte Erstgenerierung von Anschreiben + Lebenslauf-PDF an. */
  generate(jobOfferId: number): Observable<Application> {
    return this.http.post<Application>(`${this.baseUrl}/generate`, { job_offer_id: jobOfferId });
  }

  /** Lädt die zu einem Stellenangebot gehörende Bewerbung (404, falls noch keine generiert wurde). */
  getByJobOffer(jobOfferId: number): Observable<Application> {
    return this.http.get<Application>(`${this.baseUrl}/by-job-offer/${jobOfferId}`);
  }

  /** Lädt eine einzelne Bewerbung. */
  getById(applicationId: number): Observable<Application> {
    return this.http.get<Application>(`${this.baseUrl}/${applicationId}`);
  }

  /** Speichert manuell bearbeitete Texte und lässt das PDF (ohne erneuten KI-Aufruf) neu rendern. */
  update(applicationId: number, payload: ApplicationUpdatePayload): Observable<Application> {
    return this.http.put<Application>(`${this.baseUrl}/${applicationId}`, payload);
  }

  /** Versendet die Bewerbung per E-Mail inkl. PDF-Anhang. */
  send(applicationId: number, payload: ApplicationSendPayload): Observable<Application> {
    return this.http.post<Application>(`${this.baseUrl}/${applicationId}/send`, payload);
  }

  /** Lädt die generierte PDF-Datei als Blob (für Vorschau und Download). */
  downloadPdfBlob(applicationId: number): Observable<Blob> {
    return this.http.get(`${this.baseUrl}/${applicationId}/pdf`, { responseType: 'blob' });
  }

  /** Löscht eine einzelne Bewerbung unwiderruflich inkl. der generierten PDF-Datei. */
  deleteById(applicationId: number): Observable<void> {
    return this.http.delete<void>(`${this.baseUrl}/${applicationId}`);
  }
}
