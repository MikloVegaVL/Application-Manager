import { ChangeDetectionStrategy, Component, OnInit, computed, inject, signal } from '@angular/core';
import { NgTemplateOutlet } from '@angular/common';
import { HttpErrorResponse } from '@angular/common/http';
import { FormBuilder, FormGroup, ReactiveFormsModule, Validators } from '@angular/forms';
import { RouterLink } from '@angular/router';

import { MatButtonModule } from '@angular/material/button';
import { MatCardModule } from '@angular/material/card';
import { MatDialog, MatDialogModule, MatDialogRef } from '@angular/material/dialog';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatIconModule } from '@angular/material/icon';
import { MatInputModule } from '@angular/material/input';
import { MatProgressSpinnerModule } from '@angular/material/progress-spinner';
import { MatSelectModule } from '@angular/material/select';
import { MatSnackBar } from '@angular/material/snack-bar';
import { MatTabsModule } from '@angular/material/tabs';

import {
  MasterProfile,
  MasterProfileRead,
  ProfileAttachment,
  SENDER_EMAIL_OPTIONS,
} from '../../core/models/master-profile.model';
import { ProfileService, ProfileType } from '../../core/services/profile.service';

/**
 * U7: blockierender Erstlauf-Dialog (R8) - fragt, welchem der beiden
 * Profiltypen die untypisierte Alt-Zeile zugeordnet werden soll. Als
 * zusätzliche, im selben File definierte Standalone-Komponente statt eines
 * eigenen `.ts`/`.html`-Paars, da U7's Datei-Scope nur `profile.component.ts`
 * (nicht neue Dateien) umfasst. `disableClose` wird beim `MatDialog.open`-
 * Aufruf gesetzt (siehe `ProfileComponent.promptMigration`), nicht hier.
 */
@Component({
  selector: 'app-profile-migration-dialog',
  standalone: true,
  imports: [MatButtonModule, MatDialogModule],
  template: `
    <h2 mat-dialog-title>Choose a profile type</h2>
    <mat-dialog-content>
      <p>
        Your existing profile needs to be assigned to one of the two profile types before you can
        continue. The other profile will start empty.
      </p>
    </mat-dialog-content>
    <mat-dialog-actions align="end">
      <button mat-stroked-button type="button" (click)="choose('it')">IT</button>
      <button mat-flat-button color="primary" type="button" (click)="choose('full_life')">
        Full-life/Non-IT
      </button>
    </mat-dialog-actions>
  `,
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class ProfileMigrationDialogComponent {
  private readonly dialogRef = inject(MatDialogRef<ProfileMigrationDialogComponent, ProfileType>);

  choose(profileType: ProfileType): void {
    this.dialogRef.close(profileType);
  }
}

/**
 * Profil-Seite: nur noch Identitätsfelder (Name, E-Mail, Telefon, Adresse)
 * plus die datei-basierten Tabs (Lebenslauf-Anhang, Weitere Anhänge). Die
 * inhaltliche CV-Pflege (Berufserfahrung, Ausbildung, Skills, Zusammen-
 * fassung) und der KI-gestützte CV-Import sind in den CV Builder
 * (`cv-builder.component.ts`) umgezogen - siehe R2/R3 in U7.
 *
 * U7: verwaltet zusätzlich zwei vollständig unabhängige Profile ("it"/
 * "full_life", R1/R2/R3) über einen äußeren Tab-Umschalter, der die
 * bestehenden drei Feld-Tabs umschließt. Beim ersten Laden wird geprüft, ob
 * noch eine untypisierte Alt-Zeile existiert (R8) - falls ja, blockiert ein
 * `MatDialog` jedes Rendern der Profil-Tabs, bis der Nutzer einen Typ wählt.
 */
@Component({
  selector: 'app-profile',
  standalone: true,
  imports: [
    NgTemplateOutlet,
    ReactiveFormsModule,
    RouterLink,
    MatButtonModule,
    MatCardModule,
    MatDialogModule,
    MatFormFieldModule,
    MatIconModule,
    MatInputModule,
    MatProgressSpinnerModule,
    MatSelectModule,
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
  private readonly dialog = inject(MatDialog);

  /** U7/R8: `true` solange die Migrationsprüfung (und ggf. der Migrations-
   * Dialog) noch nicht abgeschlossen ist - so lange rendert das Template
   * weder den Tab-Umschalter noch irgendeinen Profilinhalt. */
  protected readonly initializing = signal(true);

  /** U7/R1: der aktuell gewählte Profiltyp - Reihenfolge entspricht den
   * Tab-Indizes im Template (`profileTypeOrder`). */
  protected readonly profileType = signal<ProfileType>('it');
  /** ce-simplify-code-Fund: abgeleitet statt separat gepflegt - vorher
   * mussten beide Signale an jeder Änderungsstelle synchron gesetzt werden,
   * ein stiller Invarianten-Bruch bei einer künftigen Änderung war so nur
   * eine Frage der Zeit. */
  protected readonly profileTypeIndex = computed(() => this.profileTypeOrder.indexOf(this.profileType()));
  private readonly profileTypeOrder: readonly ProfileType[] = ['it', 'full_life'];

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

  protected readonly senderEmailOptions = SENDER_EMAIL_OPTIONS;

  protected readonly profileForm: FormGroup = this.formBuilder.nonNullable.group({
    full_name: ['', [Validators.required, Validators.maxLength(255)]],
    email: ['', [Validators.required, Validators.email]],
    phone: [''],
    address: [''],
    linkedin: [''],
    website: [''],
    sender_email: [SENDER_EMAIL_OPTIONS[0]],
  });

  ngOnInit(): void {
    this.checkMigrationThenLoad();
  }

  // --- U7/R8: Erstlauf-Migrationsprüfung ----------------------------------

  private checkMigrationThenLoad(): void {
    this.profileService.getMigrationStatus().subscribe({
      next: ({ has_untyped_profile }) => {
        if (has_untyped_profile) {
          this.promptMigration();
        } else {
          this.initializing.set(false);
          this.loadProfile(this.profileType());
        }
      },
      error: () => {
        // Fail open: kann der Migrationsstatus nicht geladen werden, verhält
        // sich die Seite wie zuvor (kein Prompt) statt den Nutzer dauerhaft
        // auszusperren.
        this.initializing.set(false);
        this.loadProfile(this.profileType());
      },
    });
  }

  private promptMigration(): void {
    const dialogRef = this.dialog.open(ProfileMigrationDialogComponent, { disableClose: true });
    dialogRef.afterClosed().subscribe((chosenType) => {
      if (!chosenType) {
        // `disableClose: true` verhindert Esc/Backdrop-Schließen - dieser
        // Fall sollte praktisch nicht auftreten, aber sicherheitshalber
        // erneut fragen statt die Seite in einem halb-initialisierten
        // Zustand zu belassen.
        this.promptMigration();
        return;
      }

      this.profileService.migrateProfile(chosenType).subscribe({
        next: (profile) => {
          this.profileType.set(chosenType);
          this.initializing.set(false);
          this.applyProfileToForm(profile);
          this.loading.set(false);
          this.notify('Profile migrated.');
        },
        error: () => {
          this.notify('Migration failed. Please try again.', 4000);
          this.promptMigration();
        },
      });
    });
  }

  // --- U7/R1-R3: Wechsel des Profiltyp-Tabs -------------------------------

  protected onTopTabIndexChange(newIndex: number): void {
    const currentIndex = this.profileTypeOrder.indexOf(this.profileType());
    if (newIndex === currentIndex) {
      return;
    }

    if (this.profileForm.dirty) {
      // `window.confirm` statt eines `MatDialog` (ce-simplify-code-Fund:
      // dieselbe Ja/Nein-Bestätigung nutzt `cv-builder.component.ts` bereits
      // so, und `cv-builder.guard.ts` dokumentiert das als die bewusst
      // einfachste ausreichende Lösung für genau diesen Fall).
      const discard = window.confirm('You have unsaved changes on this profile. Switching profiles will discard them.');
      if (discard) {
        this.switchProfileType(newIndex);
      }
      // Ablehnung: `profileType`/`profileTypeIndex` bleiben unverändert -
      // `[selectedIndex]` synchronisiert den `mat-tab-group` beim nächsten
      // Change-Detection-Lauf von selbst zurück auf den bisherigen Tab.
      return;
    }

    this.switchProfileType(newIndex);
  }

  private switchProfileType(newIndex: number): void {
    const newType = this.profileTypeOrder[newIndex];
    this.profileType.set(newType);
    this.loadProfile(newType);
  }

  // --- Tab 1: Laden & Speichern -------------------------------------------

  private loadProfile(profileType: ProfileType): void {
    this.loading.set(true);
    this.profileService.getProfile(profileType).subscribe({
      next: (profile) => {
        this.applyProfileToForm(profile);
        this.loading.set(false);
      },
      error: (error: HttpErrorResponse) => {
        this.loading.set(false);
        // R1/R3: kein Rest des zuvor angezeigten Profils darf stehen bleiben,
        // wenn dieser Typ noch gar nicht existiert (404 = es existiert noch
        // kein Profil dieses Typs -> leeres Formular für die Neuanlage).
        this.resetProfileState();
        if (error.status !== 404) {
          this.notify('The profile could not be loaded.', 4000);
        }
      },
    });
  }

  private resetProfileState(): void {
    this.profileId.set(null);
    this.cvFilename.set(null);
    this.attachments.set([]);
    this.selectedCvFile.set(null);
    this.selectedAttachmentFile.set(null);
    this.profileForm.reset({
      full_name: '',
      email: '',
      phone: '',
      address: '',
      linkedin: '',
      website: '',
      sender_email: SENDER_EMAIL_OPTIONS[0],
    });
  }

  onSubmit(): void {
    if (this.profileForm.invalid) {
      this.profileForm.markAllAsTouched();
      this.notify('Please check the highlighted required fields.');
      return;
    }

    const raw = this.profileForm.getRawValue();
    const profileType = this.profileType();
    this.saving.set(true);

    // KTD14: NUR die Identitätsfelder überschreiben, alle Builder-eigenen
    // Felder (experiences_json, education_json, skills_json, ...) unverändert
    // zurückschicken, weil `PUT /profile/{profile_type}` alle Felder
    // feldweise überschreibt.
    // Review-Fund (fix(review)): der Payload wird bewusst NICHT mehr aus
    // `this.lastLoadedProfile` gebaut, einer beim Seitenaufruf einmalig
    // geladenen Momentaufnahme, die von keiner anderen Quelle (z. B. einem
    // zwischenzeitlichen Save im CV Builder in einem anderen Tab) aktualisiert
    // wird - ein PUT mit dieser veralteten Momentaufnahme würde dort
    // inzwischen gespeicherte Builder-Inhalte sonst stillschweigend
    // zurücksetzen. Stattdessen wird das Profil unmittelbar vor dem PUT frisch
    // geladen, damit der Payload garantiert den aktuellen Stand aller
    // Builder-Felder enthält.
    this.profileService.getProfile(profileType).subscribe({
      next: (base) => this.submitWithBase(raw, base, profileType),
      error: (error: HttpErrorResponse) => {
        // 404 = es existiert noch kein Profil dieses Typs -> Neuanlage, kein
        // Builder-Inhalt zu bewahren.
        if (error.status === 404) {
          this.submitWithBase(raw, null, profileType);
          return;
        }
        this.saving.set(false);
        this.notify('The profile could not be saved.', 4000);
      },
    });
  }

  private submitWithBase(
    raw: {
      full_name: string;
      email: string;
      phone: string;
      address: string;
      linkedin: string;
      website: string;
      sender_email: string;
    },
    base: MasterProfileRead | null,
    profileType: ProfileType,
  ): void {
    const payload: MasterProfile = {
      full_name: raw.full_name,
      email: raw.email,
      phone: raw.phone || null,
      address: raw.address || null,
      linkedin: raw.linkedin || null,
      website: raw.website || null,
      sender_email: raw.sender_email || null,
      summary: base?.summary ?? null,
      berufsbezeichnung: base?.berufsbezeichnung ?? null,
      experiences_json: base?.experiences_json ?? [],
      education_json: base?.education_json ?? [],
      skills_json: base?.skills_json ?? [],
      languages_json: base?.languages_json ?? [],
      projects_json: base?.projects_json ?? [],
      photo_filename: base?.photo_filename ?? null,
      template_id: base?.template_id ?? null,
    };

    this.profileService.saveProfile(profileType, payload).subscribe({
      next: (profile) => {
        this.saving.set(false);
        this.applyProfileToForm(profile);
        this.notify('Profile was saved.');
      },
      error: () => {
        this.saving.set(false);
        this.notify('The profile could not be saved.', 4000);
      },
    });
  }

  private applyProfileToForm(profile: MasterProfileRead): void {
    this.profileId.set(profile.id);
    this.cvFilename.set(profile.cv_filename);
    this.attachments.set(profile.attachments ?? []);
    this.selectedCvFile.set(null);
    this.selectedAttachmentFile.set(null);
    this.profileForm.patchValue({
      full_name: profile.full_name,
      email: profile.email,
      phone: profile.phone ?? '',
      address: profile.address ?? '',
      linkedin: profile.linkedin ?? '',
      website: profile.website ?? '',
      sender_email: profile.sender_email ?? SENDER_EMAIL_OPTIONS[0],
    });
    // U7: Baseline für den Dirty-Check beim Tab-Wechsel (`onTopTabIndexChange`)
    // - ein frisch geladenes/gespeichertes Profil gilt nie als "unsaved".
    this.profileForm.markAsPristine();
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
      this.notify('Please select a PDF file.');
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
    this.profileService.uploadCvFile(this.profileType(), file).subscribe({
      next: (profile) => {
        this.uploadingCvFile.set(false);
        this.selectedCvFile.set(null);
        this.cvFilename.set(profile.cv_filename);
        this.notify('CV file was uploaded.');
      },
      error: (error: HttpErrorResponse) => {
        this.uploadingCvFile.set(false);
        const message =
          (error.error?.detail as string | undefined) ?? 'Upload failed. Please try again.';
        this.snackBar.open(message, 'OK', { duration: 5000 });
      },
    });
  }

  deleteCvFile(): void {
    if (this.deletingCvFile()) {
      return;
    }

    this.deletingCvFile.set(true);
    this.profileService.deleteCvFile(this.profileType()).subscribe({
      next: (profile) => {
        this.deletingCvFile.set(false);
        this.cvFilename.set(profile.cv_filename);
        this.notify('CV file was removed.');
      },
      error: () => {
        this.deletingCvFile.set(false);
        this.notify('The CV file could not be removed.', 4000);
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
      this.notify(
        `A maximum of ${this.MAX_ATTACHMENTS} additional attachments can be uploaded.`,
        4000,
      );
      return;
    }
    const isPdf = file.type === 'application/pdf' || file.name.toLowerCase().endsWith('.pdf');
    if (!isPdf) {
      this.notify('Please select a PDF file.');
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
    this.profileService.uploadAttachment(this.profileType(), file).subscribe({
      next: (profile) => {
        this.uploadingAttachment.set(false);
        this.selectedAttachmentFile.set(null);
        this.attachments.set(profile.attachments);
        this.notify('Attachment was uploaded.');
      },
      error: (error: HttpErrorResponse) => {
        this.uploadingAttachment.set(false);
        const message =
          (error.error?.detail as string | undefined) ?? 'Upload failed. Please try again.';
        this.snackBar.open(message, 'OK', { duration: 5000 });
      },
    });
  }

  deleteAttachment(attachmentId: number): void {
    if (this.deletingAttachmentId() !== null) {
      return;
    }

    this.deletingAttachmentId.set(attachmentId);
    this.profileService.deleteAttachment(this.profileType(), attachmentId).subscribe({
      next: (profile) => {
        this.deletingAttachmentId.set(null);
        this.attachments.set(profile.attachments);
        this.notify('Attachment was removed.');
      },
      error: () => {
        this.deletingAttachmentId.set(null);
        this.notify('The attachment could not be removed.', 4000);
      },
    });
  }

  /** Zeigt eine SnackBar-Meldung mit "OK"-Label. */
  private notify(message: string, duration = 3000): void {
    this.snackBar.open(message, 'OK', { duration });
  }
}
