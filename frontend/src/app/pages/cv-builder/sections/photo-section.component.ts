import { ChangeDetectionStrategy, Component, OnDestroy, OnInit, inject, signal } from '@angular/core';
import { HttpErrorResponse } from '@angular/common/http';

import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatProgressSpinnerModule } from '@angular/material/progress-spinner';

import { ProfileService } from '../../../core/services/profile.service';

/**
 * Foto-Sektion des CV Builders (KTD4/KTD10). Anders als die übrigen
 * Sektionen NICHT Teil des Eltern-`FormGroup`/`PUT /profile`-Payloads -
 * Upload/Löschen laufen über eigene, sofort wirksame Endpunkte
 * (`POST`/`GET`/`DELETE /profile/photo`, siehe `ProfileService`), analog zum
 * Lebenslauf-Anhang und den weiteren Anhängen in `profile.component.ts`,
 * nur mit einer Bildvorschau statt einer Dateiname-Anzeige.
 */
@Component({
  selector: 'app-photo-section',
  standalone: true,
  imports: [MatButtonModule, MatIconModule, MatProgressSpinnerModule],
  template: `
    <section class="form-array-section">
      <h3>Foto</h3>

      @if (photoUrl(); as url) {
        <div class="photo-section__preview">
          <img [src]="url" alt="Profilfoto" class="photo-section__image" />
          <button mat-button color="warn" type="button" [disabled]="deleting()" (click)="remove()">
            @if (deleting()) {
              <mat-progress-spinner mode="indeterminate" diameter="18" />
            } @else {
              <mat-icon>delete</mat-icon>
            }
            Entfernen
          </button>
        </div>
      } @else if (!loading()) {
        <p class="form-array-section__empty">Noch kein Foto hochgeladen.</p>
      }

      <div
        class="photo-dropzone"
        [class.photo-dropzone--dragover]="isDragOver()"
        (dragover)="onDragOver($event)"
        (dragleave)="onDragLeave($event)"
        (drop)="onDrop($event)"
        (click)="fileInput.click()"
      >
        @if (uploading()) {
          <mat-progress-spinner mode="indeterminate" diameter="32" />
        } @else {
          <mat-icon>upload_file</mat-icon>
        }
        <p>Bild hierher ziehen oder klicken zum Auswählen</p>
      </div>
      <input #fileInput type="file" accept="image/*" hidden (change)="onFileSelected($event)" />

      @if (errorMessage(); as message) {
        <p class="photo-section__error">{{ message }}</p>
      }
    </section>
  `,
  styles: `
    .form-array-section {
      display: flex;
      flex-direction: column;
      gap: 12px;

      h3 {
        margin: 0;
      }

      &__empty {
        color: rgba(0, 0, 0, 0.5);
        font-style: italic;
        margin: 0;
      }
    }

    .photo-section {
      &__preview {
        display: flex;
        align-items: center;
        gap: 16px;
      }

      &__image {
        width: 120px;
        height: 120px;
        object-fit: cover;
        border-radius: 8px;
      }

      &__error {
        color: #b3261e;
        margin: 0;
      }
    }

    .photo-dropzone {
      display: flex;
      flex-direction: column;
      align-items: center;
      justify-content: center;
      gap: 8px;
      padding: 40px 24px;
      border: 2px dashed rgba(255, 255, 255, 0.6);
      border-radius: 8px;
      cursor: pointer;
      text-align: center;
      color: rgba(255, 255, 255, 0.6);
      transition:
        border-color 150ms ease,
        background-color 150ms ease;

      mat-icon {
        font-size: 40px;
        width: 40px;
        height: 40px;
      }

      &--dragover {
        border-color: rgba(255, 255, 255, 0.6);
        background-color: rgba(63, 81, 181, 0.06);
      }
    }

    @media (prefers-color-scheme: dark) {
      .form-array-section__empty {
        color: rgba(255, 255, 255, 0.6);
      }

      .photo-dropzone {
        border-color: rgba(255, 255, 255, 0.6);
      }
    }
  `,
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class PhotoSectionComponent implements OnInit, OnDestroy {
  private readonly profileService = inject(ProfileService);

  protected readonly photoUrl = signal<string | null>(null);
  protected readonly loading = signal(true);
  protected readonly uploading = signal(false);
  protected readonly deleting = signal(false);
  protected readonly isDragOver = signal(false);
  protected readonly errorMessage = signal<string | null>(null);

  ngOnInit(): void {
    this.loadPhoto();
  }

  ngOnDestroy(): void {
    this.revokeCurrentUrl();
  }

  onDragOver(event: DragEvent): void {
    event.preventDefault();
    this.isDragOver.set(true);
  }

  onDragLeave(event: DragEvent): void {
    event.preventDefault();
    this.isDragOver.set(false);
  }

  onDrop(event: DragEvent): void {
    event.preventDefault();
    this.isDragOver.set(false);
    const file = event.dataTransfer?.files?.[0];
    if (file) {
      this.handleFile(file);
    }
  }

  onFileSelected(event: Event): void {
    const input = event.target as HTMLInputElement;
    const file = input.files?.[0];
    if (file) {
      this.handleFile(file);
    }
    input.value = '';
  }

  remove(): void {
    if (this.deleting()) {
      return;
    }

    this.deleting.set(true);
    this.profileService.deletePhoto().subscribe({
      next: () => {
        this.deleting.set(false);
        this.revokeCurrentUrl();
        this.photoUrl.set(null);
      },
      error: () => {
        this.deleting.set(false);
        this.errorMessage.set('Foto konnte nicht entfernt werden.');
      },
    });
  }

  private handleFile(file: File): void {
    // KTD4: clientseitig ablehnen, bevor überhaupt ein Request rausgeht -
    // die serverseitige MIME/Größenprüfung in `upload_photo` bleibt
    // zusätzlich bestehen, siehe `backend/app/api/profile.py`.
    if (!file.type.startsWith('image/')) {
      this.errorMessage.set('Bitte eine Bilddatei auswählen.');
      return;
    }

    this.errorMessage.set(null);
    this.uploading.set(true);
    this.profileService.uploadPhoto(file).subscribe({
      next: () => {
        this.uploading.set(false);
        this.loadPhoto();
      },
      error: (error: HttpErrorResponse) => {
        this.uploading.set(false);
        const message = (error.error?.detail as string | undefined) ?? 'Upload fehlgeschlagen. Bitte erneut versuchen.';
        this.errorMessage.set(message);
      },
    });
  }

  private loadPhoto(): void {
    this.loading.set(true);
    this.profileService.getPhoto().subscribe({
      next: (blob) => {
        this.loading.set(false);
        this.revokeCurrentUrl();
        this.photoUrl.set(URL.createObjectURL(blob));
      },
      error: (error: HttpErrorResponse) => {
        this.loading.set(false);
        this.revokeCurrentUrl();
        this.photoUrl.set(null);
        // 404 = noch kein Foto hochgeladen -> Empty-State statt Fehlermeldung.
        if (error.status !== 404) {
          this.errorMessage.set('Foto konnte nicht geladen werden.');
        }
      },
    });
  }

  private revokeCurrentUrl(): void {
    const current = this.photoUrl();
    if (current) {
      URL.revokeObjectURL(current);
    }
  }
}
