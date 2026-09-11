import { ChangeDetectionStrategy, ChangeDetectorRef, Component, Input, inject } from '@angular/core';
import { FormArray, FormBuilder, FormGroup, ReactiveFormsModule, Validators } from '@angular/forms';

import { MatButtonModule } from '@angular/material/button';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatIconModule } from '@angular/material/icon';
import { MatInputModule } from '@angular/material/input';
import { MatSelectModule } from '@angular/material/select';

import { LanguageEntry, LanguageLevel } from '../../../core/models/master-profile.model';

/**
 * KTD3: die sechs CEFR-Niveaustufen (A1-C2), identisch zu `LanguageLevel`
 * in `backend/app/schemas/master_profile.py` - ein bestehender externer
 * Standard, kein bespoke-Design nötig.
 */
const LANGUAGE_LEVELS: LanguageLevel[] = ['A1', 'A2', 'B1', 'B2', 'C1', 'C2'];

const DEFAULT_LEVEL: LanguageLevel = 'A1';

/**
 * Sprachen-Sektion des CV Builders (KTD10). FormArray von
 * `{ name, level }`-FormGroups, exakt nach dem Muster von
 * `SkillsSectionComponent`, nur mit CEFR- statt Kompetenzgrad-Skala. Keine
 * Migrations-Hinweis-Logik hier - die betrifft laut KTD5 ausschließlich
 * Skills (die aus rohen Strings migriert wurden), Sprachen sind ein
 * komplett neues Feld ohne Altbestand.
 */
@Component({
  selector: 'app-languages-section',
  standalone: true,
  imports: [
    ReactiveFormsModule,
    MatButtonModule,
    MatFormFieldModule,
    MatIconModule,
    MatInputModule,
    MatSelectModule,
  ],
  template: `
    <section class="form-array-section">
      <div class="form-array-section__header">
        <h3>Sprachen</h3>
        <button mat-stroked-button type="button" (click)="add()">
          <mat-icon>add</mat-icon>
          Sprache hinzufügen
        </button>
      </div>

      @if (formArray.length === 0) {
        <p class="form-array-section__empty">Noch keine Sprachen erfasst.</p>
      }

      @for (group of formArray.controls; track $index) {
        <div class="language-row" [formGroup]="group">
          <mat-form-field appearance="outline" class="language-row__name">
            <mat-label>Sprache</mat-label>
            <input matInput formControlName="name" />
          </mat-form-field>

          <mat-form-field appearance="outline" class="language-row__level">
            <mat-label>Niveau</mat-label>
            <mat-select formControlName="level">
              @for (level of languageLevels; track level) {
                <mat-option [value]="level">{{ level }}</mat-option>
              }
            </mat-select>
          </mat-form-field>

          <button
            mat-icon-button
            color="warn"
            type="button"
            class="language-row__remove"
            [attr.aria-label]="'Sprache entfernen'"
            (click)="remove($index)"
          >
            <mat-icon>delete</mat-icon>
          </button>
        </div>
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

    .language-row {
      display: grid;
      grid-template-columns: 2fr 1fr auto;
      align-items: start;
      column-gap: 12px;

      &__name,
      &__level {
        width: 100%;
      }
    }

    @media (prefers-color-scheme: dark) {
      .form-array-section__empty {
        color: rgba(255, 255, 255, 0.6);
      }
    }

    @media (max-width: 600px) {
      .language-row {
        grid-template-columns: 1fr;
      }
    }
  `,
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class LanguagesSectionComponent {
  private readonly formBuilder = inject(FormBuilder);
  private readonly changeDetectorRef = inject(ChangeDetectorRef);

  protected readonly languageLevels = LANGUAGE_LEVELS;

  /** FormArray von Sprach-FormGroups (`{ name, level }`), verwaltet von der Elternform. */
  @Input({ required: true }) formArray!: FormArray<FormGroup>;

  createGroup(entry?: LanguageEntry): FormGroup {
    return this.formBuilder.nonNullable.group({
      name: [entry?.name ?? '', Validators.required],
      level: [entry?.level ?? DEFAULT_LEVEL, Validators.required],
    });
  }

  add(): void {
    this.formArray.push(this.createGroup());
    // OnPush + ein direkt (nicht über eine Input-Bindung) mutiertes FormArray
    // markiert diese View sonst nicht als dirty - siehe `remove()`.
    this.changeDetectorRef.markForCheck();
  }

  remove(index: number): void {
    this.formArray.removeAt(index);
    this.changeDetectorRef.markForCheck();
  }
}
