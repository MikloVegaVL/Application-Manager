import { HttpClient, HttpResponse } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';

import { environment } from '../../../environments/environment';
import {
  CvParseResponse,
  CvRenderPayload,
  CvTemplate,
  MasterProfile,
  MasterProfileRead,
  ProfileContentUpdate,
} from '../models/master-profile.model';

/**
 * U7: mirrors the backend's `ProfileType` literal (`app.api.profile`) - the
 * app supports exactly two fully independent profiles (R1).
 */
export type ProfileType = 'it' | 'full_life';

/** Antwort von `GET /profile/migration-status` (U6, R8). */
export interface MigrationStatusResponse {
  has_untyped_profile: boolean;
}

/**
 * Kommuniziert mit den Profil-Endpunkten des Backends
 * (`/api/profile/{profile_type}`, siehe `backend/app/api/profile.py`)
 * sowie mit dem CV-Builder-Parse-Endpunkt (`/api/cv-builder/parse`, siehe
 * `backend/app/api/cv_builder.py`).
 *
 * U7: jeder Endpunkt unter `/profile` trägt seit U2 einen `profile_type`-
 * Pfadparameter (`it`/`full_life`) - jede Methode hier, die einen solchen
 * Endpunkt aufruft, nimmt deshalb `profileType` als ersten Parameter.
 * `/cv-builder/preview` und `.../export` nehmen `profile_type` stattdessen
 * als Query-Parameter (U5) - über die `params`-Option von `HttpClient`, NICHT
 * per String-Konkatenation in die URL, damit `HttpRequest.url` in bestehenden
 * Tests unverändert bleibt (die Query landet separat in `HttpRequest.params`).
 *
 * `uploadPhoto`/`getPhoto`/`deletePhoto` fallen unter dieselbe U2-Regel wie
 * jeder andere `/profile`-Endpunkt (`/profile/{profile_type}/photo`) und
 * nehmen deshalb ebenfalls `profileType`. `parseCv`/`getTemplates` (unter
 * `/cv-builder`) bleiben ohne `profile_type`, da diese Endpunkte kein
 * Profil lesen/schreiben.
 */
@Injectable({ providedIn: 'root' })
export class ProfileService {
  private readonly http = inject(HttpClient);
  private readonly baseUrl = `${environment.apiBaseUrl}/profile`;
  private readonly cvBuilderBaseUrl = `${environment.apiBaseUrl}/cv-builder`;

  private profileUrl(profileType: ProfileType): string {
    return `${this.baseUrl}/${profileType}`;
  }

  /** Lädt das Master-Profil des gegebenen Typs. Löst mit HTTP 404, falls noch keines angelegt wurde. */
  getProfile(profileType: ProfileType): Observable<MasterProfileRead> {
    return this.http.get<MasterProfileRead>(this.profileUrl(profileType));
  }

  /** Legt das Profil des gegebenen Typs an (Erstaufruf) oder überschreibt es vollständig (Upsert). */
  saveProfile(profileType: ProfileType, profile: MasterProfile): Observable<MasterProfileRead> {
    return this.http.put<MasterProfileRead>(this.profileUrl(profileType), profile);
  }

  /**
   * Partielles Update der CV-Builder-Inhaltsfelder (R2-R4, KTD2). Schreibt
   * NIE Identitätsfelder oder das Foto - siehe `ProfileContentUpdate`. Löst
   * mit HTTP 422, falls doch ein nicht-null Identitätsfeld mitgeschickt
   * wird, bzw. HTTP 404, falls noch kein Profil dieses Typs existiert (KTD9).
   */
  patchProfile(profileType: ProfileType, payload: ProfileContentUpdate): Observable<MasterProfileRead> {
    return this.http.patch<MasterProfileRead>(this.profileUrl(profileType), payload);
  }

  /**
   * Lädt eine Lebenslauf-PDF hoch und lässt sie serverseitig per KI in eine
   * reine Vorschau strukturieren (`POST /cv-builder/parse`, R5/R6). Schreibt
   * NICHTS in die Datenbank - das Ergebnis befüllt im CV-Builder-Formular
   * nur die Formularfelder, bis der Nutzer explizit speichert (KTD1). Die
   * KI gibt die extrahierten Textwerte immer auf Englisch aus. Kein
   * `profile_type` nötig - dieser Endpunkt liest/schreibt kein Profil.
   */
  parseCv(file: File): Observable<CvParseResponse> {
    const formData = new FormData();
    formData.append('file', file, file.name);
    return this.http.post<CvParseResponse>(`${this.cvBuilderBaseUrl}/parse`, formData);
  }

  /**
   * Lädt die Lebenslauf-Anhang-Datei hoch, die (unverändert, ohne KI-
   * Analyse) beim Versand einer Bewerbung als E-Mail-Anhang verwendet wird.
   */
  uploadCvFile(profileType: ProfileType, file: File): Observable<MasterProfileRead> {
    const formData = new FormData();
    formData.append('file', file, file.name);
    return this.http.post<MasterProfileRead>(`${this.profileUrl(profileType)}/cv-file`, formData);
  }

  /** Entfernt die hochgeladene Lebenslauf-Anhang-Datei wieder. */
  deleteCvFile(profileType: ProfileType): Observable<MasterProfileRead> {
    return this.http.delete<MasterProfileRead>(`${this.profileUrl(profileType)}/cv-file`);
  }

  /**
   * Lädt einen zusätzlichen PDF-Anhang hoch (max. 3, unabhängig vom
   * Lebenslauf-Anhang), der beim Versand einer Bewerbung zusätzlich zum
   * Lebenslauf mitgeschickt wird.
   */
  uploadAttachment(profileType: ProfileType, file: File): Observable<MasterProfileRead> {
    const formData = new FormData();
    formData.append('file', file, file.name);
    return this.http.post<MasterProfileRead>(`${this.profileUrl(profileType)}/attachments`, formData);
  }

  /** Entfernt einen zusätzlichen PDF-Anhang wieder (per ID). */
  deleteAttachment(profileType: ProfileType, attachmentId: number): Observable<MasterProfileRead> {
    return this.http.delete<MasterProfileRead>(`${this.profileUrl(profileType)}/attachments/${attachmentId}`);
  }

  /**
   * Lädt das Profilfoto hoch (JPEG/PNG, <= 5 MB serverseitig geprüft, siehe
   * KTD4 / `backend/app/api/profile.py:upload_photo`) - ersetzt ein bereits
   * vorhandenes Foto.
   */
  uploadPhoto(profileType: ProfileType, file: File): Observable<MasterProfileRead> {
    const formData = new FormData();
    formData.append('file', file, file.name);
    return this.http.post<MasterProfileRead>(`${this.profileUrl(profileType)}/photo`, formData);
  }

  /**
   * Lädt das aktuelle Profilfoto als Blob (für eine Bildvorschau im CV
   * Builder). Löst mit HTTP 404, falls noch kein Foto hochgeladen wurde.
   */
  getPhoto(profileType: ProfileType): Observable<Blob> {
    return this.http.get(`${this.profileUrl(profileType)}/photo`, { responseType: 'blob' });
  }

  /** Entfernt das hochgeladene Profilfoto wieder. */
  deletePhoto(profileType: ProfileType): Observable<MasterProfileRead> {
    return this.http.delete<MasterProfileRead>(`${this.profileUrl(profileType)}/photo`);
  }

  /** Lädt die kleine, feste Auswahl wählbarer CV-Vorlagen (R9, KTD8). Kein `profile_type` nötig. */
  getTemplates(): Observable<CvTemplate[]> {
    return this.http.get<CvTemplate[]>(`${this.cvBuilderBaseUrl}/templates`);
  }

  /**
   * Rendert den aktuellen (ggf. ungespeicherten) CV-Builder-Formularinhalt
   * als PDF zur Inline-Anzeige (`POST /cv-builder/preview`, R10, KTD7/KTD11).
   * `profile_type` (U5) wählt, dessen Identitätsfelder/Foto serverseitig
   * gemergt werden - als Query-Parameter über `params`, siehe Klassen-
   * Kommentar oben. `observe: 'response'` liefert die vollständige Antwort
   * inkl. Headern - hier ungenutzt, aber symmetrisch zu `exportCv`, das den
   * `Content-Disposition`-Dateinamen daraus liest.
   */
  previewCv(profileType: ProfileType, payload: CvRenderPayload): Observable<HttpResponse<Blob>> {
    return this.http.post(`${this.cvBuilderBaseUrl}/preview`, payload, {
      responseType: 'blob',
      observe: 'response',
      params: { profile_type: profileType },
    });
  }

  /**
   * Rendert den aktuellen (ggf. ungespeicherten) CV-Builder-Formularinhalt
   * als PDF zum Download (`POST /cv-builder/export`, R11, KTD11). `profile_type` siehe `previewCv` oben.
   */
  exportCv(profileType: ProfileType, payload: CvRenderPayload): Observable<HttpResponse<Blob>> {
    return this.http.post(`${this.cvBuilderBaseUrl}/export`, payload, {
      responseType: 'blob',
      observe: 'response',
      params: { profile_type: profileType },
    });
  }

  /**
   * Meldet, ob noch eine untypisierte Alt-Zeile existiert (U6, R8) - das
   * Frontend zeigt den einmaligen Migrations-Prompt genau dann, wenn
   * `has_untyped_profile` true ist.
   */
  getMigrationStatus(): Observable<MigrationStatusResponse> {
    return this.http.get<MigrationStatusResponse>(`${this.baseUrl}/migration-status`);
  }

  /**
   * Ordnet die untypisierte Alt-Zeile einmalig einem der beiden Profiltypen
   * zu (U6, R8) - 409, falls keine untypisierte Zeile (mehr) existiert.
   */
  migrateProfile(profileType: ProfileType): Observable<MasterProfileRead> {
    return this.http.post<MasterProfileRead>(`${this.baseUrl}/migrate`, { profile_type: profileType });
  }
}
