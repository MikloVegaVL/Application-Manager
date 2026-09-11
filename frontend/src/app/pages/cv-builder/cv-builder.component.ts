import { ChangeDetectionStrategy, Component, OnInit, inject, signal } from '@angular/core';
import { HttpErrorResponse } from '@angular/common/http';
import { FormArray, FormBuilder, FormControl, FormGroup, Validators } from '@angular/forms';
import { RouterLink } from '@angular/router';

import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatProgressSpinnerModule } from '@angular/material/progress-spinner';
import { MatTabsModule } from '@angular/material/tabs';

import {
  EducationEntry,
  ExperienceEntry,
  LanguageEntry,
  MasterProfileRead,
  ProjectEntry,
  SkillEntry,
} from '../../core/models/master-profile.model';
import { ProfileService } from '../../core/services/profile.service';
import { EducationSectionComponent } from './sections/education-section.component';
import { ExperienceSectionComponent } from './sections/experience-section.component';
import { LanguagesSectionComponent } from './sections/languages-section.component';
import { PhotoSectionComponent } from './sections/photo-section.component';
import { ProjectsSectionComponent } from './sections/projects-section.component';
import { SkillsSectionComponent } from './sections/skills-section.component';
import { SummarySectionComponent } from './sections/summary-section.component';

type CvBuilderState = 'loading' | 'empty' | 'error' | 'ready';

/**
 * CV Builder-Seite (Lebenslauf-Editor). Baut auf dem bestehenden Master-
 * Profil auf (`GET /api/profile`) - siehe KTD9: existiert noch kein Profil
 * (HTTP 404), zeigt diese Seite einen Empty-State statt eines Formulars,
 * analog zur bestehenden 404-Behandlung in `profile.component.ts`. Ein
 * eigener "Builder legt das Profil an"-Pfad wird bewusst nicht gebaut.
 *
 * KTD10: die Editing-UI ist in eine Kind-Komponente pro CV-Sektion
 * aufgeteilt (`ExperienceSectionComponent`, `EducationSectionComponent`,
 * `SkillsSectionComponent`, `SummarySectionComponent`,
 * `LanguagesSectionComponent`, `ProjectsSectionComponent`,
 * `PhotoSectionComponent`), jede mit eigenem FormArray/FormControl, das hier
 * gehalten und per Input übergeben wird (siehe U7/U10) - `PhotoSectionComponent`
 * ist die Ausnahme: sie schreibt direkt über eigene HTTP-Calls
 * (`POST`/`DELETE /profile/photo`) statt über den `PUT /profile`-Payload
 * dieser Elternform. Import/Vorschau & Export bleiben in dieser Unit
 * Platzhalter und werden von nachfolgenden Units befüllt.
 */
@Component({
  selector: 'app-cv-builder',
  standalone: true,
  imports: [
    RouterLink,
    MatButtonModule,
    MatIconModule,
    MatProgressSpinnerModule,
    MatTabsModule,
    ExperienceSectionComponent,
    EducationSectionComponent,
    SkillsSectionComponent,
    SummarySectionComponent,
    LanguagesSectionComponent,
    ProjectsSectionComponent,
    PhotoSectionComponent,
  ],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <div class="cv-builder-page">
      <header class="cv-builder-page__intro">
        <h1>Lebenslauf</h1>
        <p>Inhalte für deinen Lebenslauf pflegen, per KI importieren und als Vorlage exportieren.</p>
      </header>

      @switch (state()) {
        @case ('loading') {
          <div class="cv-builder-page__loading">
            <mat-progress-spinner mode="indeterminate" diameter="48" />
            <p>Profil wird geladen ...</p>
          </div>
        }
        @case ('empty') {
          <div class="cv-builder-page__empty">
            <mat-icon>info</mat-icon>
            <p>Es wurde noch kein Profil angelegt. Bitte lege zuerst dein Profil an, bevor du den Lebenslauf bearbeitest.</p>
            <a mat-flat-button color="primary" routerLink="/profile">Zum Profil</a>
          </div>
        }
        @case ('error') {
          <div class="cv-builder-page__error">
            <mat-icon>error_outline</mat-icon>
            <p>Profil konnte nicht geladen werden.</p>
            <button
              mat-stroked-button
              type="button"
              class="cv-builder-page__retry"
              (click)="retry()"
            >
              Erneut versuchen
            </button>
          </div>
        }
        @case ('ready') {
          <mat-tab-group animationDuration="150ms">
            <mat-tab label="Zusammenfassung">
              <div class="tab-content">
                <app-summary-section [control]="summaryControl" />
              </div>
            </mat-tab>
            <mat-tab label="Berufserfahrung">
              <div class="tab-content">
                <app-experience-section [formArray]="experiencesArray" />
              </div>
            </mat-tab>
            <mat-tab label="Ausbildung">
              <div class="tab-content">
                <app-education-section [formArray]="educationArray" />
              </div>
            </mat-tab>
            <mat-tab label="Skills">
              <div class="tab-content">
                <app-skills-section [formArray]="skillsArray" />
              </div>
            </mat-tab>
            <mat-tab label="Sprachen">
              <div class="tab-content">
                <app-languages-section [formArray]="languagesArray" />
              </div>
            </mat-tab>
            <mat-tab label="Projekte">
              <div class="tab-content">
                <app-projects-section [formArray]="projectsArray" />
              </div>
            </mat-tab>
            <mat-tab label="Foto">
              <div class="tab-content">
                <app-photo-section />
              </div>
            </mat-tab>
            <mat-tab label="Import">
              <div class="tab-content"><p>Bald verfügbar.</p></div>
            </mat-tab>
            <mat-tab label="Vorschau & Export">
              <div class="tab-content"><p>Bald verfügbar.</p></div>
            </mat-tab>
          </mat-tab-group>
        }
      }
    </div>
  `,
  styles: `
    .cv-builder-page {
      max-width: 1000px;
      margin: 0 auto;
      padding: 24px;

      &__intro {
        margin-bottom: 16px;

        h1 {
          margin: 0 0 4px;
        }

        p {
          margin: 0;
        }
      }

      &__loading,
      &__empty,
      &__error {
        display: flex;
        flex-direction: column;
        align-items: center;
        gap: 12px;
        padding: 64px 0;
        text-align: center;
        color: rgba(0, 0, 0, 0.6);
      }
    }

    .tab-content {
      padding: 24px 0;
    }
  `,
})
export class CvBuilderComponent implements OnInit {
  private readonly profileService = inject(ProfileService);
  private readonly formBuilder = inject(FormBuilder);

  protected readonly state = signal<CvBuilderState>('loading');

  protected readonly summaryControl: FormControl<string> = this.formBuilder.nonNullable.control('');
  protected readonly experiencesArray: FormArray<FormGroup> = this.formBuilder.array<FormGroup>([]);
  protected readonly educationArray: FormArray<FormGroup> = this.formBuilder.array<FormGroup>([]);
  protected readonly skillsArray: FormArray<FormGroup> = this.formBuilder.array<FormGroup>([]);
  protected readonly languagesArray: FormArray<FormGroup> = this.formBuilder.array<FormGroup>([]);
  protected readonly projectsArray: FormArray<FormGroup> = this.formBuilder.array<FormGroup>([]);

  ngOnInit(): void {
    this.loadProfile();
  }

  protected retry(): void {
    this.loadProfile();
  }

  private loadProfile(): void {
    this.state.set('loading');
    this.profileService.getProfile().subscribe({
      next: (profile) => {
        this.applyProfileToArrays(profile);
        this.state.set('ready');
      },
      error: (error: HttpErrorResponse) => {
        this.state.set(error.status === 404 ? 'empty' : 'error');
      },
    });
  }

  private applyProfileToArrays(profile: MasterProfileRead): void {
    this.summaryControl.setValue(profile.summary ?? '');

    this.experiencesArray.clear();
    profile.experiences_json.forEach((entry) => this.experiencesArray.push(this.createExperienceGroup(entry)));

    this.educationArray.clear();
    profile.education_json.forEach((entry) => this.educationArray.push(this.createEducationGroup(entry)));

    this.skillsArray.clear();
    profile.skills_json.forEach((entry) => this.skillsArray.push(this.createSkillGroup(entry)));

    this.languagesArray.clear();
    profile.languages_json.forEach((entry) => this.languagesArray.push(this.createLanguageGroup(entry)));

    this.projectsArray.clear();
    profile.projects_json.forEach((entry) => this.projectsArray.push(this.createProjectGroup(entry)));
  }

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

  private createSkillGroup(entry?: SkillEntry): FormGroup {
    return this.formBuilder.nonNullable.group({
      name: [entry?.name ?? '', Validators.required],
      level: [entry?.level ?? 'Grundkenntnisse', Validators.required],
    });
  }

  private createLanguageGroup(entry?: LanguageEntry): FormGroup {
    return this.formBuilder.nonNullable.group({
      name: [entry?.name ?? '', Validators.required],
      level: [entry?.level ?? 'A1', Validators.required],
    });
  }

  private createProjectGroup(entry?: ProjectEntry): FormGroup {
    return this.formBuilder.nonNullable.group({
      title: [entry?.title ?? '', Validators.required],
      description: [entry?.description ?? '', Validators.required],
      start_date: [entry?.start_date ?? ''],
      end_date: [entry?.end_date ?? ''],
      link: [entry?.link ?? ''],
    });
  }
}
