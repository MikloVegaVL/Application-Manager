import { HttpClient } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';

import { environment } from '../../../environments/environment';
import {
  CvParseResponse,
  CvUploadResponse,
  MasterProfile,
  MasterProfileRead,
  ProfileContentUpdate,
} from '../models/master-profile.model';

/**
 * Kommuniziert mit den Profil-Endpunkten des Backends
 * (`/api/profile`, `/api/profile/upload-cv`, siehe `backend/app/api/profile.py`)
 * sowie mit dem CV-Builder-Parse-Endpunkt (`/api/cv-builder/parse`, siehe
 * `backend/app/api/cv_builder.py`).
 */
@Injectable({ providedIn: 'root' })
export class ProfileService {
  private readonly http = inject(HttpClient);
  private readonly baseUrl = `${environment.apiBaseUrl}/profile`;
  private readonly cvBuilderBaseUrl = `${environment.apiBaseUrl}/cv-builder`;

  /** Lädt das Master-Profil. Löst mit HTTP 404, falls noch keines angelegt wurde. */
  getProfile(): Observable<MasterProfileRead> {
    return this.http.get<MasterProfileRead>(this.baseUrl);
  }

  /** Legt das Profil an (Erstaufruf) oder überschreibt es vollständig (Upsert). */
  saveProfile(profile: MasterProfile): Observable<MasterProfileRead> {
    return this.http.put<MasterProfileRead>(this.baseUrl, profile);
  }

  /**
   * Partielles Update der CV-Builder-Inhaltsfelder (R2-R4, KTD2). Schreibt
   * NIE Identitätsfelder oder das Foto - siehe `ProfileContentUpdate`. Löst
   * mit HTTP 422, falls doch ein nicht-null Identitätsfeld mitgeschickt
   * wird, bzw. HTTP 404, falls noch kein Profil existiert (KTD9).
   */
  patchProfile(payload: ProfileContentUpdate): Observable<MasterProfileRead> {
    return this.http.patch<MasterProfileRead>(this.baseUrl, payload);
  }

  /**
   * Lädt eine Lebenslauf-PDF hoch und lässt sie serverseitig per KI in eine
   * reine Vorschau strukturieren (`POST /cv-builder/parse`, R5/R6). Schreibt
   * NICHTS in die Datenbank - das Ergebnis befüllt im CV-Builder-Formular
   * nur die Formularfelder, bis der Nutzer explizit speichert (KTD1).
   */
  parseCv(file: File): Observable<CvParseResponse> {
    const formData = new FormData();
    formData.append('file', file, file.name);
    return this.http.post<CvParseResponse>(`${this.cvBuilderBaseUrl}/parse`, formData);
  }

  /**
   * Lädt eine Lebenslauf-PDF hoch und lässt sie serverseitig per KI analysieren.
   * `warnings` in der Antwort benennt Felder, die die KI nicht fand und die
   * deshalb NICHT übernommen wurden (siehe CvUploadResponse).
   */
  uploadCv(file: File): Observable<CvUploadResponse> {
    const formData = new FormData();
    formData.append('file', file, file.name);
    return this.http.post<CvUploadResponse>(`${this.baseUrl}/upload-cv`, formData);
  }

  /**
   * Lädt die Lebenslauf-Anhang-Datei hoch, die (unverändert, ohne KI-
   * Analyse) beim Versand einer Bewerbung als E-Mail-Anhang verwendet wird.
   */
  uploadCvFile(file: File): Observable<MasterProfileRead> {
    const formData = new FormData();
    formData.append('file', file, file.name);
    return this.http.post<MasterProfileRead>(`${this.baseUrl}/cv-file`, formData);
  }

  /** Entfernt die hochgeladene Lebenslauf-Anhang-Datei wieder. */
  deleteCvFile(): Observable<MasterProfileRead> {
    return this.http.delete<MasterProfileRead>(`${this.baseUrl}/cv-file`);
  }

  /**
   * Lädt einen zusätzlichen PDF-Anhang hoch (max. 3, unabhängig vom
   * Lebenslauf-Anhang), der beim Versand einer Bewerbung zusätzlich zum
   * Lebenslauf mitgeschickt wird.
   */
  uploadAttachment(file: File): Observable<MasterProfileRead> {
    const formData = new FormData();
    formData.append('file', file, file.name);
    return this.http.post<MasterProfileRead>(`${this.baseUrl}/attachments`, formData);
  }

  /** Entfernt einen zusätzlichen PDF-Anhang wieder (per ID). */
  deleteAttachment(attachmentId: number): Observable<MasterProfileRead> {
    return this.http.delete<MasterProfileRead>(`${this.baseUrl}/attachments/${attachmentId}`);
  }

  /**
   * Lädt das Profilfoto hoch (JPEG/PNG, <= 5 MB serverseitig geprüft, siehe
   * KTD4 / `backend/app/api/profile.py:upload_photo`) - ersetzt ein bereits
   * vorhandenes Foto.
   */
  uploadPhoto(file: File): Observable<MasterProfileRead> {
    const formData = new FormData();
    formData.append('file', file, file.name);
    return this.http.post<MasterProfileRead>(`${this.baseUrl}/photo`, formData);
  }

  /**
   * Lädt das aktuelle Profilfoto als Blob (für eine Bildvorschau im CV
   * Builder). Löst mit HTTP 404, falls noch kein Foto hochgeladen wurde.
   */
  getPhoto(): Observable<Blob> {
    return this.http.get(`${this.baseUrl}/photo`, { responseType: 'blob' });
  }

  /** Entfernt das hochgeladene Profilfoto wieder. */
  deletePhoto(): Observable<MasterProfileRead> {
    return this.http.delete<MasterProfileRead>(`${this.baseUrl}/photo`);
  }
}
