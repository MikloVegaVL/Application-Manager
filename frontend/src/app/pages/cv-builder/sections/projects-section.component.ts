import { ChangeDetectionStrategy, ChangeDetectorRef, Component, Input, inject } from '@angular/core';
import { FormArray, FormBuilder, FormGroup, ReactiveFormsModule } from '@angular/forms';

import { MatButtonModule } from '@angular/material/button';
import { MatCardModule } from '@angular/material/card';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatIconModule } from '@angular/material/icon';
import { MatInputModule } from '@angular/material/input';

import { TranslatePipe } from '../../../core/i18n/translate.pipe';
import { ProjectEntry } from '../../../core/models/master-profile.model';
import { TranslationService } from '../../../core/services/translation.service';
import { createProjectGroup } from '../cv-section-forms.util';

/**
 * Projekte-Sektion des CV Builders (KTD10, R3: Projekte mit mindestens
 * Titel und Beschreibung). FormArray von Projekt-FormGroups nach dem Muster
 * von `ExperienceSectionComponent` - `title`/`description` sind Pflicht,
 * `start_date`/`end_date`/`link` sind optional.
 */
@Component({
  selector: 'app-projects-section',
  standalone: true,
  imports: [
    ReactiveFormsModule,
    MatButtonModule,
    MatCardModule,
    MatFormFieldModule,
    MatIconModule,
    MatInputModule,
    TranslatePipe,
  ],
  template: `
    <section class="form-array-section">
      <div class="form-array-section__header">
        <h3>{{ 'cvBuilder.projects.heading' | translate: i18n.language() }}</h3>
        <button mat-stroked-button type="button" (click)="add()">
          <mat-icon>add</mat-icon>
          {{ 'cvBuilder.projects.add' | translate: i18n.language() }}
        </button>
      </div>

      @if (formArray.length === 0) {
        <p class="form-array-section__empty">{{ 'cvBuilder.projects.empty' | translate: i18n.language() }}</p>
      }

      @for (group of formArray.controls; track $index) {
        <mat-card class="entry-card" appearance="outlined" [formGroup]="group">
          <mat-card-content class="entry-card__grid">
            <mat-form-field appearance="outline">
              <mat-label>{{ 'cvBuilder.projects.title' | translate: i18n.language() }}</mat-label>
              <input matInput formControlName="title" />
            </mat-form-field>
            <mat-form-field appearance="outline">
              <mat-label>{{ 'cvBuilder.projects.link' | translate: i18n.language() }}</mat-label>
              <input
                matInput
                formControlName="link"
                [placeholder]="'cvBuilder.optional' | translate: i18n.language()"
              />
            </mat-form-field>
            <mat-form-field appearance="outline">
              <mat-label>{{ 'cvBuilder.start' | translate: i18n.language() }}</mat-label>
              <input
                matInput
                formControlName="start_date"
                [placeholder]="'cvBuilder.projects.startPlaceholder' | translate: i18n.language()"
              />
            </mat-form-field>
            <mat-form-field appearance="outline">
              <mat-label>{{ 'cvBuilder.end' | translate: i18n.language() }}</mat-label>
              <input
                matInput
                formControlName="end_date"
                [placeholder]="'cvBuilder.endPlaceholder' | translate: i18n.language()"
              />
            </mat-form-field>
            <mat-form-field appearance="outline" class="entry-card__description">
              <mat-label>{{ 'cvBuilder.description' | translate: i18n.language() }}</mat-label>
              <textarea matInput formControlName="description" rows="2"></textarea>
            </mat-form-field>
          </mat-card-content>
          <mat-card-actions align="end">
            <button mat-button color="warn" type="button" (click)="remove($index)">
              <mat-icon>delete</mat-icon>
              {{ 'common.remove' | translate: i18n.language() }}
            </button>
          </mat-card-actions>
        </mat-card>
      }
    </section>
  `,
  styles: `
    .form-array-section {
      display: flex;
      flex-direction: column;
      gap: 12px;

      &__header {
        display: flex;
        align-items: center;
        justify-content: space-between;

        h3 {
          margin: 0;
        }
      }

      &__empty {
        color: rgba(0, 0, 0, 0.5);
        font-style: italic;
        margin: 0;
      }
    }

    .entry-card {
      &__grid {
        display: grid;
        grid-template-columns: repeat(2, minmax(200px, 1fr));
        gap: 8px 16px;
        padding-top: 8px;
      }

      &__description {
        grid-column: 1 / -1;
      }
    }

    @media (prefers-color-scheme: dark) {
      .form-array-section__empty {
        color: rgba(255, 255, 255, 0.6);
      }
    }

    @media (max-width: 600px) {
      .entry-card__grid {
        grid-template-columns: 1fr;
      }
    }
  `,
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class ProjectsSectionComponent {
  private readonly formBuilder = inject(FormBuilder);
  private readonly changeDetectorRef = inject(ChangeDetectorRef);
  protected readonly i18n = inject(TranslationService);

  /** FormArray von Projekt-FormGroups, verwaltet von der Elternform. */
  @Input({ required: true }) formArray!: FormArray<FormGroup>;

  createGroup(entry?: ProjectEntry): FormGroup {
    return createProjectGroup(this.formBuilder, entry);
  }

  add(): void {
    this.formArray.push(this.createGroup());
    // OnPush + ein direkt (nicht über eine Input-Bindung) mutiertes FormArray
    // markiert diese View sonst nicht als dirty.
    this.changeDetectorRef.markForCheck();
  }

  remove(index: number): void {
    this.formArray.removeAt(index);
    this.changeDetectorRef.markForCheck();
  }
}
