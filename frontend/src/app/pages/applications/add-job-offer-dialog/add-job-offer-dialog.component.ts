import { ChangeDetectionStrategy, Component, inject } from '@angular/core';
import { FormBuilder, ReactiveFormsModule, Validators } from '@angular/forms';
import { MatButtonModule } from '@angular/material/button';
import { MatDialogModule, MatDialogRef } from '@angular/material/dialog';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatInputModule } from '@angular/material/input';

/** Ergebnis des Dialogs - reine Formulardaten, kein HTTP-Request (KTD3). Der
 * Aufrufer (`ApplicationsComponent`) baut daraus den `JobOffer`-Payload und
 * speichert ihn. */
export interface AddJobOfferDialogResult {
  title: string;
  company: string;
  source_url: string;
  description_text: string;
  application_email: string;
}

@Component({
  selector: 'app-add-job-offer-dialog',
  standalone: true,
  imports: [
    ReactiveFormsModule,
    MatButtonModule,
    MatDialogModule,
    MatFormFieldModule,
    MatInputModule,
  ],
  templateUrl: './add-job-offer-dialog.component.html',
  styleUrl: './add-job-offer-dialog.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class AddJobOfferDialogComponent {
  private readonly dialogRef = inject(MatDialogRef<AddJobOfferDialogComponent, AddJobOfferDialogResult>);
  private readonly formBuilder = inject(FormBuilder);

  protected readonly form = this.formBuilder.nonNullable.group({
    title: ['', Validators.required],
    company: ['', Validators.required],
    source_url: ['', Validators.required],
    description_text: [''],
    application_email: ['', Validators.email],
  });

  onCancel(): void {
    this.dialogRef.close();
  }

  onConfirm(): void {
    if (this.form.invalid) {
      this.form.markAllAsTouched();
      return;
    }
    this.dialogRef.close(this.form.getRawValue());
  }
}
