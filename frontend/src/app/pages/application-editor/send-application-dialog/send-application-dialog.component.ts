import { ChangeDetectionStrategy, Component, inject } from '@angular/core';
import { FormBuilder, ReactiveFormsModule, Validators } from '@angular/forms';
import { MatButtonModule } from '@angular/material/button';
import { MAT_DIALOG_DATA, MatDialogModule, MatDialogRef } from '@angular/material/dialog';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatIconModule } from '@angular/material/icon';
import { MatInputModule } from '@angular/material/input';

import { TranslatePipe } from '../../../core/i18n/translate.pipe';
import { TranslationService } from '../../../core/services/translation.service';

export interface SendApplicationDialogData {
  toEmail: string;
  subject: string;
  message: string;
  jobTitle?: string;
  companyName?: string;
}

export interface SendApplicationDialogResult {
  to_email: string;
  subject: string;
  message: string;
}

@Component({
  selector: 'app-send-application-dialog',
  standalone: true,
  imports: [
    ReactiveFormsModule,
    MatButtonModule,
    MatDialogModule,
    MatFormFieldModule,
    MatIconModule,
    MatInputModule,
    TranslatePipe,
  ],
  templateUrl: './send-application-dialog.component.html',
  styleUrl: './send-application-dialog.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class SendApplicationDialogComponent {
  private readonly dialogRef = inject(MatDialogRef<SendApplicationDialogComponent, SendApplicationDialogResult>);
  private readonly formBuilder = inject(FormBuilder);
  protected readonly data = inject<SendApplicationDialogData>(MAT_DIALOG_DATA);
  protected readonly i18n = inject(TranslationService);

  protected readonly form = this.formBuilder.nonNullable.group({
    to_email: [this.data.toEmail, [Validators.required, Validators.email]],
    subject: [this.data.subject],
    message: [this.data.message],
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
