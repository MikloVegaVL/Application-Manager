import { ChangeDetectionStrategy, Component, Input } from '@angular/core';
import { FormControl, ReactiveFormsModule } from '@angular/forms';

import { MatFormFieldModule } from '@angular/material/form-field';
import { MatInputModule } from '@angular/material/input';

/**
 * Zusammenfassung-Sektion des CV Builders (KTD10). Ein einzelnes Freitextfeld
 * (`summary`), das früher auf der Profil-Seite lag und dort bereits von U7
 * entfernt wurde. Bewusst kein eigenes FormGroup/FormArray - der Elternform
 * genügt ein einzelnes `FormControl<string>`.
 */
@Component({
  selector: 'app-summary-section',
  standalone: true,
  imports: [ReactiveFormsModule, MatFormFieldModule, MatInputModule],
  template: `
    <section class="form-array-section">
      <h3>Zusammenfassung</h3>
      <mat-form-field appearance="outline" class="summary-section__field">
        <mat-label>Professionelle Zusammenfassung</mat-label>
        <textarea
          matInput
          [formControl]="control"
          rows="6"
          placeholder="Kurzer Überblick über deine Qualifikationen und Erfahrung ..."
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
  /** FormControl für die Zusammenfassung, verwaltet von der Elternform. */
  @Input({ required: true }) control!: FormControl<string>;
}
