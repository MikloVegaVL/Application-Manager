import { ChangeDetectionStrategy, Component, OnInit, inject, signal } from '@angular/core';
import { HttpErrorResponse } from '@angular/common/http';
import { FormArray, FormBuilder, FormGroup, ReactiveFormsModule, Validators } from '@angular/forms';

import { LiveAnnouncer } from '@angular/cdk/a11y';
import { COMMA, ENTER } from '@angular/cdk/keycodes';
import { MatButtonModule } from '@angular/material/button';
import { MatCardModule } from '@angular/material/card';
import {
  MatChipEditedEvent,
  MatChipInputEvent,
  MatChipsModule,
} from '@angular/material/chips';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatIconModule } from '@angular/material/icon';
import { MatInputModule } from '@angular/material/input';
import { MatProgressSpinnerModule } from '@angular/material/progress-spinner';
import { MatSnackBar } from '@angular/material/snack-bar';
import { MatTabsModule } from '@angular/material/tabs';

import {
  EducationEntry,
  ExperienceEntry,
  MasterProfile,
  MasterProfileRead,
} from '../../core/models/master-profile.model';
import { ProfileService } from '../../core/services/profile.service';

@Component({
  selector: 'app-profile',
  standalone: true,
  imports: [
    ReactiveFormsModule,
    MatButtonModule,
    MatCardModule,
    MatChipsModule,
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
  private readonly announcer = inject(LiveAnnouncer);

  protected readonly separatorKeysCodes = [ENTER, COMMA] as const;

  protected readonly profileId = signal<number | null>(null);
  protected readonly loading = signal(true);
  protected readonly saving = signal(false);
  protected readonly skills = signal<string[]>([]);

  // --- CV-Import (Tab 4) ---
  protected readonly selectedFile = signal<File | null>(null);
  protected readonly isDragOver = signal(false);
  protected readonly uploading = signal(false);

  protected readonly profileForm: FormGroup = this.formBuilder.nonNullable.group({
    full_name: ['', [Validators.required, Validators.maxLength(255)]],
    email: ['', [Validators.required, Validators.email]],
    phone: [''],
    address: [''],
    summary: [''],
    experiences: this.formBuilder.array<FormGroup>([]),
    education: this.formBuilder.array<FormGroup>([]),
  });

  ngOnInit(): void {
    this.loadProfile();
  }

  protected get experiencesArray(): FormArray<FormGroup> {
    return this.profileForm.get('experiences') as FormArray<FormGroup>;
  }

  protected get educationArray(): FormArray<FormGroup> {
    return this.profileForm.get('education') as FormArray<FormGroup>;
  }

  // --- Tab 1+2: Laden & Speichern ---------------------------------------

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
    const payload: MasterProfile = {
      full_name: raw.full_name,
      email: raw.email,
      phone: raw.phone || null,
      address: raw.address || null,
      summary: raw.summary || null,
      experiences_json: raw.experiences as ExperienceEntry[],
      education_json: raw.education as EducationEntry[],
      skills_json: this.skills(),
    };

    this.saving.set(true);
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
    this.profileForm.patchValue({
      full_name: profile.full_name,
      email: profile.email,
      phone: profile.phone ?? '',
      address: profile.address ?? '',
      summary: profile.summary ?? '',
    });

    this.experiencesArray.clear();
    profile.experiences_json.forEach((entry) => this.experiencesArray.push(this.createExperienceGroup(entry)));

    this.educationArray.clear();
    profile.education_json.forEach((entry) => this.educationArray.push(this.createEducationGroup(entry)));

    this.skills.set([...profile.skills_json]);
  }

  // --- Tab 2: Berufserfahrung & Ausbildung (dynamische FormArrays) ------

  private createExperienceGroup(entry?: ExperienceEntry): FormGroup {
    return this.formBuilder.nonNullable.group({
      company: [entry?.company ?? '', Validators.required],
      role: [entry?.role ?? '', Validators.required],
      start_date: [entry?.start_date ?? ''],
      end_date: [entry?.end_date ?? ''],
      description: [entry?.description ?? ''],
    });
  }

  private createEducationGroup(entry?: EducationEntry): FormGroup {
    return this.formBuilder.nonNullable.group({
      institution: [entry?.institution ?? '', Validators.required],
      degree: [entry?.degree ?? '', Validators.required],
      field_of_study: [entry?.field_of_study ?? ''],
      start_date: [entry?.start_date ?? ''],
      end_date: [entry?.end_date ?? ''],
    });
  }

  addExperience(): void {
    this.experiencesArray.push(this.createExperienceGroup());
  }

  removeExperience(index: number): void {
    this.experiencesArray.removeAt(index);
  }

  addEducation(): void {
    this.educationArray.push(this.createEducationGroup());
  }

  removeEducation(index: number): void {
    this.educationArray.removeAt(index);
  }

  // --- Tab 3: Skills & Zertifikate (mat-chip-grid) -----------------------

  addSkill(event: MatChipInputEvent): void {
    const value = (event.value || '').trim();
    if (value) {
      this.skills.update((skills) => (skills.includes(value) ? skills : [...skills, value]));
    }
    event.chipInput.clear();
  }

  removeSkill(skill: string): void {
    this.skills.update((skills) => skills.filter((s) => s !== skill));
    this.announcer.announce(`${skill} entfernt`);
  }

  editSkill(skill: string, event: MatChipEditedEvent): void {
    const value = event.value.trim();
    if (!value) {
      this.removeSkill(skill);
      return;
    }
    this.skills.update((skills) => {
      const index = skills.indexOf(skill);
      if (index < 0) {
        return skills;
      }
      const copy = [...skills];
      copy[index] = value;
      return copy;
    });
  }

  // --- Tab 4: CV-Import (Dropzone) ---------------------------------------

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
      this.setSelectedFile(file);
    }
  }

  onFileSelected(event: Event): void {
    const input = event.target as HTMLInputElement;
    const file = input.files?.[0];
    if (file) {
      this.setSelectedFile(file);
    }
    input.value = '';
  }

  private setSelectedFile(file: File): void {
    const isPdf = file.type === 'application/pdf' || file.name.toLowerCase().endsWith('.pdf');
    if (!isPdf) {
      this.snackBar.open('Bitte eine PDF-Datei auswählen.', 'OK', { duration: 3000 });
      return;
    }
    this.selectedFile.set(file);
  }

  clearSelectedFile(): void {
    this.selectedFile.set(null);
  }

  uploadCv(): void {
    const file = this.selectedFile();
    if (!file || this.uploading()) {
      return;
    }

    this.uploading.set(true);
    this.profileService.uploadCv(file).subscribe({
      next: ({ profile, warnings }) => {
        this.uploading.set(false);
        this.selectedFile.set(null);
        this.applyProfileToForm(profile);
        // `warnings` benennt Felder, die die KI nicht im CV fand und die
        // deshalb NICHT übernommen wurden (bestehende Daten bleiben
        // unverändert) - ohne diese Meldung wirkte ein unvollständiger
        // Import wie ein unbedingter Erfolg (siehe ce-debug-Untersuchung,
        // 2026-08-18).
        if (warnings.length > 0) {
          this.snackBar.open(
            `Profil teilweise befüllt - bitte manuell prüfen: ${warnings.join(' ')}`,
            'OK',
            { duration: 10000 },
          );
        } else {
          this.snackBar.open('Profil wurde aus dem Lebenslauf befüllt. Bitte prüfen und speichern.', 'OK', {
            duration: 5000,
          });
        }
      },
      error: (error: HttpErrorResponse) => {
        this.uploading.set(false);
        const message =
          (error.error?.detail as string | undefined) ?? 'CV-Analyse fehlgeschlagen. Bitte erneut versuchen.';
        this.snackBar.open(message, 'OK', { duration: 6000 });
      },
    });
  }
}
