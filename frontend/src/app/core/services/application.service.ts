import { HttpClient, HttpResponse } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable, map } from 'rxjs';

import { environment } from '../../../environments/environment';
import {
  Application,
  ApplicationSendPayload,
  ApplicationUpdatePayload,
  FillRequestResponse,
  ProfileType,
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

  /** Stößt die KI-gestützte Generierung des Anschreibens an.
   *
   * `profileType` ist nur für die ERSTE Generierung eines Stellenangebots
   * Pflicht (R4, `ApplicationGenerateRequest.profile_type`) - ist für die
   * Bewerbung bereits ein Profil gesperrt (R5), reicht der Aufruf ohne
   * `profileType` (Regenerate, unverändert): das Backend ignoriert einen
   * dann trotzdem mitgeschickten Wert ohnehin (KTD3, U3). Wird hier daher
   * bewusst nur bei Angabe in den Body aufgenommen, statt immer `null`/
   * `undefined` mitzuschicken.
   *
   * `forNewApplication` ist R5's Ausweg (U9, KTD12): legt statt eines
   * Upserts eine zusätzliche, unabhängige Bewerbung für dasselbe
   * Stellenangebot an, gesperrt auf `profileType`. Standardmäßig `false`
   * und dann ebenfalls NICHT mitgeschickt - hält `onRegenerate()`s
   * Request-Body unverändert (kein `for_new_application`-Feld). */
  generate(
    jobOfferId: number,
    profileType?: ProfileType,
    forNewApplication = false,
  ): Observable<Application> {
    return this.http.post<Application>(`${this.baseUrl}/generate`, {
      job_offer_id: jobOfferId,
      ...(profileType ? { profile_type: profileType } : {}),
      ...(forNewApplication ? { for_new_application: true } : {}),
    });
  }

  /** Lädt ALLE zu einem Stellenangebot gehörenden Bewerbungen (neueste
   * zuerst) - seit U9/R5 (KTD12) kann ein Stellenangebot mehr als eine
   * Bewerbung haben (je eine pro genutztem Profil). Leeres Array, solange
   * noch keine generiert wurde. */
  getAllByJobOffer(jobOfferId: number): Observable<Application[]> {
    return this.http.get<Application[]>(`${this.baseUrl}/by-job-offer/${jobOfferId}`);
  }

  /** Lädt GENAU EINE Bewerbung zu einem Stellenangebot - mit `applicationId`
   * genau diese (sofern in der Liste vorhanden), sonst die erste (häufigster
   * Fall: nur eine Bewerbung existiert). `null`, solange noch keine
   * Bewerbung generiert wurde. */
  getByJobOffer(jobOfferId: number, applicationId?: number): Observable<Application | null> {
    return this.getAllByJobOffer(jobOfferId).pipe(
      map((applications) => {
        if (applications.length === 0) {
          return null;
        }
        if (applicationId !== undefined) {
          return applications.find((application) => application.id === applicationId) ?? applications[0];
        }
        return applications[0];
      }),
    );
  }

  /** Lädt eine einzelne Bewerbung. */
  getById(applicationId: number): Observable<Application> {
    return this.http.get<Application>(`${this.baseUrl}/${applicationId}`);
  }

  /** Speichert den manuell bearbeiteten Anschreiben-Text (ohne erneuten KI-Aufruf). */
  update(applicationId: number, payload: ApplicationUpdatePayload): Observable<Application> {
    return this.http.put<Application>(`${this.baseUrl}/${applicationId}`, payload);
  }

  /** Versendet die Bewerbung per E-Mail inkl. der im Profil hochgeladenen Lebenslauf-Datei als Anhang. */
  send(applicationId: number, payload: ApplicationSendPayload): Observable<Application> {
    return this.http.post<Application>(`${this.baseUrl}/${applicationId}/send`, payload);
  }

  /** Löscht eine einzelne Bewerbung unwiderruflich. */
  deleteById(applicationId: number): Observable<void> {
    return this.http.delete<void>(`${this.baseUrl}/${applicationId}`);
  }

  /** Legt einen kurzlebigen Fill-Request für eine LinkedIn-Bewerbung an und liefert die Job-URL, die in
   * einem neuen Tab geöffnet wird (R1/R2, siehe `app.api.portal_fill`). Der leere JSON-Body hält den
   * Request bewusst aus der CORS-Simple-Request-Klasse (KTD13). */
  requestFill(applicationId: number): Observable<FillRequestResponse> {
    return this.http.post<FillRequestResponse>(`${this.baseUrl}/${applicationId}/fill-request`, {});
  }

  /** Lädt das gespeicherte Anschreiben einer Bewerbung als PDF-Download (Blob). */
  downloadCoverLetter(applicationId: number): Observable<HttpResponse<Blob>> {
    return this.http.get(`${this.baseUrl}/${applicationId}/cover-letter.pdf`, {
      responseType: 'blob',
      observe: 'response',
    });
  }

  /** Direkt-Download-URL des Anschreibens (für einfache `<a href>`-Links, z. B. das Karten-Menü). */
  coverLetterDownloadUrl(applicationId: number): string {
    return `${this.baseUrl}/${applicationId}/cover-letter.pdf`;
  }
}
