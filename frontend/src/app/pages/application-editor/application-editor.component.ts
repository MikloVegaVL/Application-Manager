import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  OnInit,
  inject,
  input,
  signal,
} from '@angular/core';
import { HttpErrorResponse } from '@angular/common/http';
import { FormArray, FormBuilder, FormGroup, ReactiveFormsModule, Validators } from '@angular/forms';
import { DomSanitizer, SafeResourceUrl } from '@angular/platform-browser';

import { LiveAnnouncer } from '@angular/cdk/a11y';
import { COMMA, ENTER } from '@angular/cdk/keycodes';
import { TextFieldModule } from '@angular/cdk/text-field';
import { MatButtonModule } from '@angular/material/button';
import { MatCardModule } from '@angular/material/card';
import { MatChipEditedEvent, MatChipInputEvent, MatChipsModule } from '@angular/material/chips';
import { MatDialog } from '@angular/material/dialog';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatIconModule } from '@angular/material/icon';
import { MatInputModule } from '@angular/material/input';
import { MatProgressSpinnerModule } from '@angular/material/progress-spinner';
import { MatSnackBar } from '@angular/material/snack-bar';
import { MatTabsModule } from '@angular/material/tabs';
import { MatToolbarModule } from '@angular/material/toolbar';
import { MatTooltipModule } from '@angular/material/tooltip';

import { Application, TailoredCv } from '../../core/models/application.model';
import { EducationEntry, ExperienceEntry } from '../../core/models/master-profile.model';
import { JobOfferRead } from '../../core/models/job-offer.model';
import { ApplicationService } from '../../core/services/application.service';
import { JobService } from '../../core/services/job.service';
import {
  SendApplicationDialogComponent,
  SendApplicationDialogData,
  SendApplicationDialogResult,
} from './send-application-dialog/send-application-dialog.component';

@Component({
  selector: 'app-application-editor',
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
    MatToolbarModule,
    MatTooltipModule,
    TextFieldModule,
  ],
  templateUrl: './application-editor.component.html',
  styleUrl: './application-editor.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class ApplicationEditorComponent implements OnInit {
  /** Wird über den Routenparameter `:jobOfferId` per Component-Input-Binding befüllt. */
  readonly jobOfferId = input<string>();

  private readonly applicationService = inject(ApplicationService);
  private readonly jobService = inject(JobService);
  private readonly formBuilder = inject(FormBuilder);
  private readonly snackBar = inject(MatSnackBar);
  private readonly dialog = inject(MatDialog);
  private readonly sanitizer = inject(DomSanitizer);
  private readonly announcer = inject(LiveAnnouncer);
  private readonly destroyRef = inject(DestroyRef);

  protected readonly separatorKeysCodes = [ENTER, COMMA] as const;

  protected readonly loading = signal(true);
  protected readonly regenerating = signal(false);
  protected readonly downloading = signal(false);
  protected readonly sending = signal(false);
  protected readonly pdfLoading = signal(false);
  protected readonly errorMessage = signal<string | null>(null);

  protected readonly application = signal<Application | null>(null);
  protected readonly jobOffer = signal<JobOfferRead | null>(null);
  protected readonly skills = signal<string[]>([]);
  protected readonly pdfUrl = signal<SafeResourceUrl | null>(null);

  private currentPdfObjectUrl: string | null = null;

  protected readonly coverLetterForm = this.formBuilder.nonNullable.group({
    cover_letter_text: ['', Validators.required],
  });

  protected readonly cvForm = this.formBuilder.nonNullable.group({
    summary: [''],
    experiences: this.formBuilder.array<FormGroup>([]),
    education: this.formBuilder.array<FormGroup>([]),
  });

  protected readonly emailForm = this.formBuilder.nonNullable.group({
    to_email: ['', [Validators.required, Validators.email]],
    subject: [''],
    message: [''],
  });

  constructor() {
    this.destroyRef.onDestroy(() => this.revokePdfObjectUrl());
  }

  ngOnInit(): void {
    this.loadOrGenerateApplication();
  }

  protected get experiencesArray(): FormArray<FormGroup> {
    return this.cvForm.get('experiences') as FormArray<FormGroup>;
  }

  protected get educationArray(): FormArray<FormGroup> {
    return this.cvForm.get('education') as FormArray<FormGroup>;
  }

  // --- Laden / Erstgenerierung -------------------------------------------

  private loadOrGenerateApplication(): void {
    const jobOfferIdParam = this.jobOfferId();
    if (!jobOfferIdParam) {
      this.errorMessage.set('Es wurde keine Job-ID übergeben.');
      this.loading.set(false);
      return;
    }
    const jobOfferId = Number(jobOfferIdParam);

    this.loading.set(true);
    this.errorMessage.set(null);

    this.jobService.getJob(jobOfferId).subscribe({
      next: (job) => this.jobOffer.set(job),
      error: () => {
        // Nicht kritisch für den Editor selbst - dient nur der Kopfzeile.
      },
    });

    this.applicationService.getByJobOffer(jobOfferId).subscribe({
      next: (application) => this.applyApplication(application),
      error: (error: HttpErrorResponse) => {
        if (error.status === 404) {
          this.generateForFirstTime(jobOfferId);
          return;
        }
        this.handleLoadError(error);
      },
    });
  }

  private generateForFirstTime(jobOfferId: number): void {
    this.applicationService.generate(jobOfferId).subscribe({
      next: (application) => {
        this.applyApplication(application);
        this.snackBar.open('Bewerbung wurde erstmalig generiert.', 'OK', { duration: 3000 });
      },
      error: (error: HttpErrorResponse) => this.handleLoadError(error),
    });
  }

  private handleLoadError(error: HttpErrorResponse): void {
    this.loading.set(false);
    this.errorMessage.set(
      (error.error?.detail as string | undefined) ?? 'Bewerbung konnte nicht geladen werden.',
    );
  }

  private applyApplication(application: Application): void {
    this.application.set(application);
    this.coverLetterForm.patchValue({ cover_letter_text: application.cover_letter_text ?? '' });

    const cv = application.tailored_cv_json;
    this.cvForm.patchValue({ summary: cv?.summary ?? '' });

    this.experiencesArray.clear();
    (cv?.experiences ?? []).forEach((entry) => this.experiencesArray.push(this.createExperienceGroup(entry)));

    this.educationArray.clear();
    (cv?.education ?? []).forEach((entry) => this.educationArray.push(this.createEducationGroup(entry)));

    this.skills.set(cv?.skills ? [...cv.skills] : []);

    this.loading.set(false);
    this.loadPdfPreview(application.id);
  }

  // --- PDF-Vorschau -------------------------------------------------------

  private loadPdfPreview(applicationId: number): void {
    this.pdfLoading.set(true);
    this.applicationService.downloadPdfBlob(applicationId).subscribe({
      next: (blob) => {
        this.revokePdfObjectUrl();
        const objectUrl = URL.createObjectURL(blob);
        this.currentPdfObjectUrl = objectUrl;
        this.pdfUrl.set(this.sanitizer.bypassSecurityTrustResourceUrl(objectUrl));
        this.pdfLoading.set(false);
      },
      error: () => {
        this.pdfLoading.set(false);
        this.snackBar.open('PDF-Vorschau konnte nicht geladen werden.', 'OK', { duration: 4000 });
      },
    });
  }

  private revokePdfObjectUrl(): void {
    if (this.currentPdfObjectUrl) {
      URL.revokeObjectURL(this.currentPdfObjectUrl);
      this.currentPdfObjectUrl = null;
    }
  }

  // --- Tab 2: Lebenslauf-Anpassungen (dynamische FormArrays) --------------

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

  // --- Toolbar-Aktionen -----------------------------------------------

  onRegeneratePdf(): void {
    const application = this.application();
    if (!application) {
      return;
    }
    if (this.coverLetterForm.invalid) {
      this.coverLetterForm.markAllAsTouched();
      this.snackBar.open('Bitte gib einen Anschreiben-Text ein.', 'OK', { duration: 3000 });
      return;
    }

    const existingCv = application.tailored_cv_json;
    const cvRaw = this.cvForm.getRawValue();
    const tailoredCv: TailoredCv = {
      full_name: existingCv?.full_name ?? '',
      email: existingCv?.email ?? '',
      phone: existingCv?.phone ?? null,
      address: existingCv?.address ?? null,
      summary: cvRaw.summary,
      experiences: cvRaw.experiences as ExperienceEntry[],
      education: cvRaw.education as EducationEntry[],
      skills: this.skills(),
    };

    this.regenerating.set(true);
    this.applicationService
      .update(application.id, {
        cover_letter_text: this.coverLetterForm.getRawValue().cover_letter_text,
        tailored_cv_json: tailoredCv,
      })
      .subscribe({
        next: (updated) => {
          this.regenerating.set(false);
          this.applyApplication(updated);
          this.snackBar.open('PDF wurde neu generiert.', 'OK', { duration: 3000 });
        },
        error: (error: HttpErrorResponse) => {
          this.regenerating.set(false);
          const message =
            (error.error?.detail as string | undefined) ?? 'PDF konnte nicht neu generiert werden.';
          this.snackBar.open(message, 'OK', { duration: 4000 });
        },
      });
  }

  onDownloadPdf(): void {
    const application = this.application();
    if (!application) {
      return;
    }

    this.downloading.set(true);
    this.applicationService.downloadPdfBlob(application.id).subscribe({
      next: (blob) => {
        this.downloading.set(false);
        const objectUrl = URL.createObjectURL(blob);
        const link = document.createElement('a');
        link.href = objectUrl;
        link.download = `bewerbung_${application.id}.pdf`;
        link.click();
        URL.revokeObjectURL(objectUrl);
      },
      error: () => {
        this.downloading.set(false);
        this.snackBar.open('PDF konnte nicht heruntergeladen werden.', 'OK', { duration: 4000 });
      },
    });
  }

  onOpenSendDialog(): void {
    const application = this.application();
    if (!application) {
      return;
    }

    const emailRaw = this.emailForm.getRawValue();
    const jobOffer = this.jobOffer();

    const dialogRef = this.dialog.open(SendApplicationDialogComponent, {
      width: '520px',
      data: {
        toEmail: emailRaw.to_email,
        subject: emailRaw.subject,
        message: emailRaw.message,
        jobTitle: jobOffer?.title,
        companyName: jobOffer?.company,
      } satisfies SendApplicationDialogData,
    });

    dialogRef.afterClosed().subscribe((result?: SendApplicationDialogResult) => {
      if (!result) {
        return;
      }
      this.emailForm.patchValue(result);
      this.sendApplication(application.id, result);
    });
  }

  private sendApplication(applicationId: number, payload: SendApplicationDialogResult): void {
    this.sending.set(true);
    this.applicationService
      .send(applicationId, {
        to_email: payload.to_email,
        subject: payload.subject || undefined,
        message: payload.message || undefined,
      })
      .subscribe({
        next: (updated) => {
          this.sending.set(false);
          this.application.set(updated);
          this.snackBar.open('Bewerbung wurde erfolgreich versendet.', 'OK', { duration: 4000 });
        },
        error: (error: HttpErrorResponse) => {
          this.sending.set(false);
          const message =
            (error.error?.detail as string | undefined) ?? 'Bewerbung konnte nicht versendet werden.';
          this.snackBar.open(message, 'OK', { duration: 5000 });
        },
      });
  }
}
