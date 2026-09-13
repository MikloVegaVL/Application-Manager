import { ChangeDetectionStrategy, Component, Input, inject } from '@angular/core';
import { FormControl, ReactiveFormsModule } from '@angular/forms';

import { MatFormFieldModule } from '@angular/material/form-field';
import { MatInputModule } from '@angular/material/input';

import { TranslatePipe } from '../../../core/i18n/translate.pipe';
import { TranslationService } from '../../../core/services/translation.service';

/**
 * Zusammenfassung-Sektion des CV Builders (KTD10). Ein einzelnes Freitextfeld
 * (`summary`), das früher auf der Profil-Seite lag und dort bereits von U7
 * entfernt wurde. Bewusst kein eigenes FormGroup/FormArray - der Elternform
 * genügt ein einzelnes `FormControl<string>`.
 */
@Component({
  selector: 'app-summary-section',
  standalone: true,
  imports: [ReactiveFormsModule, MatFormFieldModule, MatInputModule, TranslatePipe],
  template: `
    <section class="form-array-section">
      <h3>{{ 'cvBuilder.summary.heading' | translate: i18n.language() }}</h3>
      <mat-form-field appearance="outline" class="summary-section__field">
        <mat-label>{{ 'cvBuilder.summary.berufsbezeichnung' | translate: i18n.language() }}</mat-label>
        <input
          matInput
          [formControl]="berufsbezeichnungControl"
          [placeholder]="'cvBuilder.summary.berufsbezeichnungPlaceholder' | translate: i18n.language()"
        />
      </mat-form-field>
      <mat-form-field appearance="outline" class="summary-section__field">
        <mat-label>{{ 'cvBuilder.summary.professionalSummary' | translate: i18n.language() }}</mat-label>
        <textarea
          matInput
          [formControl]="control"
          rows="6"
          [placeholder]="'cvBuilder.summary.placeholder' | translate: i18n.language()"
        ></textarea>
      </mat-form-field>
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
    }

    .summary-section__field {
      width: 100%;
      max-width: 720px;
    }
  `,
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class SummarySectionComponent {
  protected readonly i18n = inject(TranslationService);

  /** FormControl für die Zusammenfassung, verwaltet von der Elternform. */
  @Input({ required: true }) control!: FormControl<string>;

  /** R5: optionaler Job-Titel unter dem Namen, ebenfalls von der Elternform. */
  @Input({ required: true }) berufsbezeichnungControl!: FormControl<string>;
}
