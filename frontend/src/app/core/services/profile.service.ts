import { HttpClient } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';

import { environment } from '../../../environments/environment';
import { MasterProfile, MasterProfileRead } from '../models/master-profile.model';

/**
 * Kommuniziert mit den Profil-Endpunkten des Backends
 * (`/api/profile`, `/api/profile/upload-cv`, siehe `backend/app/api/profile.py`).
 */
@Injectable({ providedIn: 'root' })
export class ProfileService {
  private readonly http = inject(HttpClient);
  private readonly baseUrl = `${environment.apiBaseUrl}/profile`;

  /** Lädt das Master-Profil. Löst mit HTTP 404, falls noch keines angelegt wurde. */
  getProfile(): Observable<MasterProfileRead> {
    return this.http.get<MasterProfileRead>(this.baseUrl);
  }

  /** Legt das Profil an (Erstaufruf) oder überschreibt es vollständig (Upsert). */
  saveProfile(profile: MasterProfile): Observable<MasterProfileRead> {
    return this.http.put<MasterProfileRead>(this.baseUrl, profile);
  }

  /** Lädt eine Lebenslauf-PDF hoch und lässt sie serverseitig per KI analysieren. */
  uploadCv(file: File): Observable<MasterProfileRead> {
    const formData = new FormData();
    formData.append('file', file, file.name);
    return this.http.post<MasterProfileRead>(`${this.baseUrl}/upload-cv`, formData);
  }
}
