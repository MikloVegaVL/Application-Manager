import { ChangeDetectionStrategy, Component, OnInit, inject, signal } from '@angular/core';
import { HttpErrorResponse } from '@angular/common/http';
import { FormBuilder, FormGroup, ReactiveFormsModule, Validators } from '@angular/forms';
import { RouterLink } from '@angular/router';

import { MatButtonModule } from '@angular/material/button';
import { MatCardModule } from '@angular/material/card';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatIconModule } from '@angular/material/icon';
import { MatInputModule } from '@angular/material/input';
import { MatProgressSpinnerModule } from '@angular/material/progress-spinner';
import { MatSnackBar } from '@angular/material/snack-bar';
import { MatTabsModule } from '@angular/material/tabs';

import { MasterProfile, MasterProfileRead, ProfileAttachment } from '../../core/models/master-profile.model';
import { ProfileService } from '../../core/services/profile.service';

/**
 * Profil-Seite: nur noch Identitätsfelder (Name, E-Mail, Telefon, Adresse)
 * plus die datei-basierten Tabs (Lebenslauf-Anhang, Weitere Anhänge). Die
 * inhaltliche CV-Pflege (Berufserfahrung, Ausbildung, Skills, Zusammen-
 * fassung) und der KI-gestützte CV-Import sind in den CV Builder
 * (`cv-builder.component.ts`) umgezogen - siehe R2/R3 in U7.
 */
@Component({
  selector: 'app-profile',
  standalone: true,
  imports: [
    ReactiveFormsModule,
    RouterLink,
    MatButtonModule,
    MatCardModule,
    MatFormFieldModule,
    MatIconModule,
    MatInputModule,
    MatProgressSpinnerModule,
    MatTabsModule,
  ],
  templateUrl: './profile.component.html',
  styleUrl: './profile.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class ProfileComponent implements OnInit {
  private readonly formBuilder = inject(FormBuilder);
  private readonly profileService = inject(ProfileService);
  private readonly snackBar = inject(MatSnackBar);

  protected readonly profileId = signal<number | null>(null);
  protected readonly loading = signal(true);
  protected readonly saving = signal(false);

  // --- Lebenslauf-Anhang (Tab 2) - wird unverändert als E-Mail-Anhang
  // genutzt, wenn eine Bewerbung versendet wird (siehe
  // `app.api.profile.upload_cv_file`). ---
  protected readonly cvFilename = signal<string | null>(null);
  protected readonly selectedCvFile = signal<File | null>(null);
  protected readonly isCvFileDragOver = signal(false);
  protected readonly uploadingCvFile = signal(false);
  protected readonly deletingCvFile = signal(false);

  // --- Weitere Anhänge (Tab 3) - bis zu MAX_ATTACHMENTS zusätzliche PDFs,
  // die beim Versand ZUSÄTZLICH zum Lebenslauf mitgeschickt werden (siehe
  // `app.api.profile`, `app.api.applications.send_application`). ---
  protected readonly MAX_ATTACHMENTS = 3;
  protected readonly attachments = signal<ProfileAttachment[]>([]);
  protected readonly selectedAttachmentFile = signal<File | null>(null);
  protected readonly isAttachmentDragOver = signal(false);
  protected readonly uploadingAttachment = signal(false);
  protected readonly deletingAttachmentId = signal<number | null>(null);

  protected readonly profileForm: FormGroup = this.formBuilder.nonNullable.group({
    full_name: ['', [Validators.required, Validators.maxLength(255)]],
    email: ['', [Validators.required, Validators.email]],
    phone: [''],
    address: [''],
  });

  ngOnInit(): void {
    this.loadProfile();
  }

  // --- Tab 1: Laden & Speichern -------------------------------------------

  private loadProfile(): void {
    this.loading.set(true);
    this.profileService.getProfile().subscribe({
      next: (profile) => {
        this.applyProfileToForm(profile);
        this.loading.set(false);
      },
      error: (error: HttpErrorResponse) => {
        this.loading.set(false);
        if (error.status !== 404) {
          this.snackBar.open('Profil konnte nicht geladen werden.', 'OK', { duration: 4000 });
        }
        // 404 = es existiert noch kein Profil -> leeres Formular für die Neuanlage.
      },
    });
  }

  onSubmit(): void {
    if (this.profileForm.invalid) {
      this.profileForm.markAllAsTouched();
      this.snackBar.open('Bitte prüfe die markierten Pflichtfelder.', 'OK', { duration: 3000 });
      return;
    }

    const raw = this.profileForm.getRawValue();
    this.saving.set(true);

    // KTD14: NUR die Identitätsfelder überschreiben, alle Builder-eigenen
    // Felder (experiences_json, education_json, skills_json, ...) unverändert
    // zurückschicken, weil `PUT /profile` alle Felder feldweise überschreibt.
    // Review-Fund (fix(review)): der Payload wird bewusst NICHT mehr aus
    // `this.lastLoadedProfile` gebaut, einer beim Seitenaufruf einmalig
    // geladenen Momentaufnahme, die von keiner anderen Quelle (z. B. einem
    // zwischenzeitlichen Save im CV Builder in einem anderen Tab) aktualisiert
    // wird - ein PUT mit dieser veralteten Momentaufnahme würde dort
    // inzwischen gespeicherte Builder-Inhalte sonst stillschweigend
    // zurücksetzen. Stattdessen wird das Profil unmittelbar vor dem PUT frisch
    // geladen, damit der Payload garantiert den aktuellen Stand aller
    // Builder-Felder enthält.
    this.profileService.getProfile().subscribe({
      next: (base) => this.submitWithBase(raw, base),
      error: (error: HttpErrorResponse) => {
        // 404 = es existiert noch kein Profil -> Neuanlage, kein Builder-
        // Inhalt zu bewahren.
        if (error.status === 404) {
          this.submitWithBase(raw, null);
          return;
        }
        this.saving.set(false);
        this.snackBar.open('Profil konnte nicht gespeichert werden.', 'OK', { duration: 4000 });
      },
    });
  }

  private submitWithBase(
    raw: { full_name: string; email: string; phone: string; address: string },
    base: MasterProfileRead | null,
  ): void {
    const payload: MasterProfile = {
      full_name: raw.full_name,
      email: raw.email,
      phone: raw.phone || null,
      address: raw.address || null,
      summary: base?.summary ?? null,
      experiences_json: base?.experiences_json ?? [],
      education_json: base?.education_json ?? [],
      skills_json: base?.skills_json ?? [],
      languages_json: base?.languages_json ?? [],
      projects_json: base?.projects_json ?? [],
      photo_filename: base?.photo_filename ?? null,
      template_id: base?.template_id ?? null,
    };

    this.profileService.saveProfile(payload).subscribe({
      next: (profile) => {
        this.saving.set(false);
        this.applyProfileToForm(profile);
        this.snackBar.open('Profil wurde gespeichert.', 'OK', { duration: 3000 });
      },
      error: () => {
        this.saving.set(false);
        this.snackBar.open('Profil konnte nicht gespeichert werden.', 'OK', { duration: 4000 });
      },
    });
  }

  private applyProfileToForm(profile: MasterProfileRead): void {
    this.profileId.set(profile.id);
    this.cvFilename.set(profile.cv_filename);
    this.attachments.set(profile.attachments ?? []);
    this.profileForm.patchValue({
      full_name: profile.full_name,
      email: profile.email,
      phone: profile.phone ?? '',
      address: profile.address ?? '',
    });
  }

  // --- Tab 2: Lebenslauf-Anhang (Dropzone) --------------------------------

  onCvFileDragOver(event: DragEvent): void {
    event.preventDefault();
    this.isCvFileDragOver.set(true);
  }

  onCvFileDragLeave(event: DragEvent): void {
    event.preventDefault();
    this.isCvFileDragOver.set(false);
  }

  onCvFileDrop(event: DragEvent): void {
    event.preventDefault();
    this.isCvFileDragOver.set(false);
    const file = event.dataTransfer?.files?.[0];
    if (file) {
      this.setSelectedCvFile(file);
    }
  }

  onCvFileSelected(event: Event): void {
    const input = event.target as HTMLInputElement;
    const file = input.files?.[0];
    if (file) {
      this.setSelectedCvFile(file);
    }
    input.value = '';
  }

  private setSelectedCvFile(file: File): void {
    const isPdf = file.type === 'application/pdf' || file.name.toLowerCase().endsWith('.pdf');
    if (!isPdf) {
      this.snackBar.open('Bitte eine PDF-Datei auswählen.', 'OK', { duration: 3000 });
      return;
    }
    this.selectedCvFile.set(file);
  }

  clearSelectedCvFile(): void {
    this.selectedCvFile.set(null);
  }

  uploadCvFile(): void {
    const file = this.selectedCvFile();
    if (!file || this.uploadingCvFile()) {
      return;
    }

    this.uploadingCvFile.set(true);
    this.profileService.uploadCvFile(file).subscribe({
      next: (profile) => {
        this.uploadingCvFile.set(false);
        this.selectedCvFile.set(null);
        this.cvFilename.set(profile.cv_filename);
        this.snackBar.open('Lebenslauf-Datei wurde hochgeladen.', 'OK', { duration: 3000 });
      },
      error: (error: HttpErrorResponse) => {
        this.uploadingCvFile.set(false);
        const message =
          (error.error?.detail as string | undefined) ?? 'Upload fehlgeschlagen. Bitte erneut versuchen.';
        this.snackBar.open(message, 'OK', { duration: 5000 });
      },
    });
  }

  deleteCvFile(): void {
    if (this.deletingCvFile()) {
      return;
    }

    this.deletingCvFile.set(true);
    this.profileService.deleteCvFile().subscribe({
      next: (profile) => {
        this.deletingCvFile.set(false);
        this.cvFilename.set(profile.cv_filename);
        this.snackBar.open('Lebenslauf-Datei wurde entfernt.', 'OK', { duration: 3000 });
      },
      error: () => {
        this.deletingCvFile.set(false);
        this.snackBar.open('Lebenslauf-Datei konnte nicht entfernt werden.', 'OK', { duration: 4000 });
      },
    });
  }

  // --- Tab 3: Weitere Anhänge (Dropzone, bis zu MAX_ATTACHMENTS) ---------

  onAttachmentDragOver(event: DragEvent): void {
    event.preventDefault();
    this.isAttachmentDragOver.set(true);
  }

  onAttachmentDragLeave(event: DragEvent): void {
    event.preventDefault();
    this.isAttachmentDragOver.set(false);
  }

  onAttachmentDrop(event: DragEvent): void {
    event.preventDefault();
    this.isAttachmentDragOver.set(false);
    const file = event.dataTransfer?.files?.[0];
    if (file) {
      this.setSelectedAttachmentFile(file);
    }
  }

  onAttachmentFileSelected(event: Event): void {
    const input = event.target as HTMLInputElement;
    const file = input.files?.[0];
    if (file) {
      this.setSelectedAttachmentFile(file);
    }
    input.value = '';
  }

  private setSelectedAttachmentFile(file: File): void {
    if (this.attachments().length >= this.MAX_ATTACHMENTS) {
      this.snackBar.open(`Es können maximal ${this.MAX_ATTACHMENTS} zusätzliche Anhänge hochgeladen werden.`, 'OK', {
        duration: 4000,
      });
      return;
    }
    const isPdf = file.type === 'application/pdf' || file.name.toLowerCase().endsWith('.pdf');
    if (!isPdf) {
      this.snackBar.open('Bitte eine PDF-Datei auswählen.', 'OK', { duration: 3000 });
      return;
    }
    this.selectedAttachmentFile.set(file);
  }

  clearSelectedAttachmentFile(): void {
    this.selectedAttachmentFile.set(null);
  }

  uploadAttachment(): void {
    const file = this.selectedAttachmentFile();
    if (!file || this.uploadingAttachment()) {
      return;
    }

    this.uploadingAttachment.set(true);
    this.profileService.uploadAttachment(file).subscribe({
      next: (profile) => {
        this.uploadingAttachment.set(false);
        this.selectedAttachmentFile.set(null);
        this.attachments.set(profile.attachments);
        this.snackBar.open('Anhang wurde hochgeladen.', 'OK', { duration: 3000 });
      },
      error: (error: HttpErrorResponse) => {
        this.uploadingAttachment.set(false);
        const message =
          (error.error?.detail as string | undefined) ?? 'Upload fehlgeschlagen. Bitte erneut versuchen.';
        this.snackBar.open(message, 'OK', { duration: 5000 });
      },
    });
  }

  deleteAttachment(attachmentId: number): void {
    if (this.deletingAttachmentId() !== null) {
      return;
    }

    this.deletingAttachmentId.set(attachmentId);
    this.profileService.deleteAttachment(attachmentId).subscribe({
      next: (profile) => {
        this.deletingAttachmentId.set(null);
        this.attachments.set(profile.attachments);
        this.snackBar.open('Anhang wurde entfernt.', 'OK', { duration: 3000 });
      },
      error: () => {
        this.deletingAttachmentId.set(null);
        this.snackBar.open('Anhang konnte nicht entfernt werden.', 'OK', { duration: 4000 });
      },
    });
  }
}
