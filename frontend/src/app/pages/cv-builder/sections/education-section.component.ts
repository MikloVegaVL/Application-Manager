import { ChangeDetectionStrategy, ChangeDetectorRef, Component, Input, inject } from '@angular/core';
import { FormArray, FormBuilder, FormGroup, ReactiveFormsModule } from '@angular/forms';

import { MatButtonModule } from '@angular/material/button';
import { MatCardModule } from '@angular/material/card';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatIconModule } from '@angular/material/icon';
import { MatInputModule } from '@angular/material/input';

import { EducationEntry } from '../../../core/models/master-profile.model';
import { createEducationGroup } from '../cv-section-forms.util';

/**
 * Ausbildung-Sektion des CV Builders (KTD10: eigene Kind-Komponente mit
 * eigenem FormArray, das der Elternform via `formArray`-Input übergeben
 * wird). Übernimmt die Add/Remove-Logik, die früher in
 * `profile.component.ts` lag (siehe U7).
 */
@Component({
  selector: 'app-education-section',
  standalone: true,
  imports: [
    ReactiveFormsModule,
    MatButtonModule,
    MatCardModule,
    MatFormFieldModule,
    MatIconModule,
    MatInputModule,
  ],
  template: `
    <section class="form-array-section">
      <div class="form-array-section__header">
        <h3>Ausbildung</h3>
        <button mat-stroked-button type="button" (click)="add()">
          <mat-icon>add</mat-icon>
          Station hinzufügen
        </button>
      </div>

      @if (formArray.length === 0) {
        <p class="form-array-section__empty">Noch keine Ausbildung erfasst.</p>
      }

      @for (group of formArray.controls; track $index) {
        <mat-card class="entry-card" appearance="outlined" [formGroup]="group">
          <mat-card-content class="entry-card__grid">
            <mat-form-field appearance="outline">
              <mat-label>Einrichtung</mat-label>
              <input matInput formControlName="institution" />
            </mat-form-field>
            <mat-form-field appearance="outline">
              <mat-label>Abschluss</mat-label>
              <input matInput formControlName="degree" />
            </mat-form-field>
            <mat-form-field appearance="outline">
              <mat-label>Studienfach</mat-label>
              <input matInput formControlName="field_of_study" />
            </mat-form-field>
            <mat-form-field appearance="outline">
              <mat-label>Start</mat-label>
              <input matInput formControlName="start_date" placeholder="z. B. 2017" />
            </mat-form-field>
            <mat-form-field appearance="outline">
              <mat-label>Ende</mat-label>
              <input matInput formControlName="end_date" placeholder="z. B. 2021" />
            </mat-form-field>
          </mat-card-content>
          <mat-card-actions align="end">
            <button mat-button color="warn" type="button" (click)="remove($index)">
              <mat-icon>delete</mat-icon>
              Entfernen
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
export class EducationSectionComponent {
  private readonly formBuilder = inject(FormBuilder);
  private readonly changeDetectorRef = inject(ChangeDetectorRef);

  /** FormArray von Ausbildungs-FormGroups, verwaltet von der Elternform. */
  @Input({ required: true }) formArray!: FormArray<FormGroup>;

  createGroup(entry?: EducationEntry): FormGroup {
    return createEducationGroup(this.formBuilder, entry);
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
