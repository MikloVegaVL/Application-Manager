import { ChangeDetectionStrategy, ChangeDetectorRef, Component, Input, inject } from '@angular/core';
import { FormArray, FormBuilder, FormGroup, ReactiveFormsModule } from '@angular/forms';

import { MatButtonModule } from '@angular/material/button';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatIconModule } from '@angular/material/icon';
import { MatInputModule } from '@angular/material/input';
import { MatSelectModule } from '@angular/material/select';

import { SkillEntry, SkillLevel } from '../../../core/models/master-profile.model';
import { createSkillGroup } from '../cv-section-forms.util';

/**
 * KTD3: die vier zulässigen Kompetenzgrade, identisch zu
 * `SkillLevel` in `backend/app/schemas/master_profile.py`.
 */
const SKILL_LEVELS: SkillLevel[] = ['Grundkenntnisse', 'Gut', 'Sehr gut', 'Experte'];

/**
 * Der Default-Wert, den die Skills-Migration (U1) jedem bestehenden Skill
 * zuweist, weil aus rohen Skill-Strings kein Kompetenzgrad ableitbar ist
 * (KTD5). Skills mit diesem Level zeigen einen Hinweis, dass der Wert vor
 * dem Export geprüft werden sollte - eine reine Anzeige-Heuristik: ein Skill,
 * der absichtlich auf "Grundkenntnisse" gesetzt wurde, zeigt den Hinweis
 * ebenfalls (akzeptierter False Positive, siehe Plan).
 */
const MIGRATION_DEFAULT_LEVEL: SkillLevel = 'Grundkenntnisse';

/**
 * Skills-Sektion des CV Builders (KTD10). Ersetzt den bisherigen Chip-Editor
 * (der nur einen Skill-Namen ohne Kompetenzgrad abbilden konnte) durch eine
 * FormArray von `{ name, level }`-FormGroups (siehe U1: `SkillEntry`).
 */
@Component({
  selector: 'app-skills-section',
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
        <h3>Skills & Zertifikate</h3>
        <button mat-stroked-button type="button" (click)="add()">
          <mat-icon>add</mat-icon>
          Skill hinzufügen
        </button>
      </div>

      @if (formArray.length === 0) {
        <p class="form-array-section__empty">Noch keine Skills erfasst.</p>
      }

      @for (group of formArray.controls; track $index) {
        <div class="skill-row" [formGroup]="group">
          <mat-form-field appearance="outline" class="skill-row__name">
            <mat-label>Skill</mat-label>
            <input matInput formControlName="name" />
          </mat-form-field>

          <mat-form-field appearance="outline" class="skill-row__level">
            <mat-label>Niveau</mat-label>
            <mat-select formControlName="level">
              @for (level of skillLevels; track level) {
                <mat-option [value]="level">{{ level }}</mat-option>
              }
            </mat-select>
          </mat-form-field>

          <button
            mat-icon-button
            color="warn"
            type="button"
            class="skill-row__remove"
            [attr.aria-label]="'Skill entfernen'"
            (click)="remove($index)"
          >
            <mat-icon>delete</mat-icon>
          </button>

          @if (group.get('level')?.value === migrationDefaultLevel) {
            <p class="skill-row__hint">Auto-migriert auf niedrigstem Niveau - vor dem Export prüfen.</p>
          }
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

    .skill-row {
      display: grid;
      grid-template-columns: 2fr 1fr auto;
      align-items: start;
      column-gap: 12px;

      &__name,
      &__level {
        width: 100%;
      }

      &__hint {
        grid-column: 1 / -1;
        margin: -8px 0 8px;
        font-size: 0.8125rem;
        color: rgba(0, 0, 0, 0.6);
      }
    }

    @media (prefers-color-scheme: dark) {
      .form-array-section__empty,
      .skill-row__hint {
        color: rgba(255, 255, 255, 0.6);
      }
    }

    @media (max-width: 600px) {
      .skill-row {
        grid-template-columns: 1fr;
      }
    }
  `,
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class SkillsSectionComponent {
  private readonly formBuilder = inject(FormBuilder);
  private readonly changeDetectorRef = inject(ChangeDetectorRef);

  protected readonly skillLevels = SKILL_LEVELS;
  protected readonly migrationDefaultLevel = MIGRATION_DEFAULT_LEVEL;

  /** FormArray von Skill-FormGroups (`{ name, level }`), verwaltet von der Elternform. */
  @Input({ required: true }) formArray!: FormArray<FormGroup>;

  createGroup(entry?: SkillEntry): FormGroup {
    return createSkillGroup(this.formBuilder, entry);
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
