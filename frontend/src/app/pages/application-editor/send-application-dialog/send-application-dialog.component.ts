import { ChangeDetectionStrategy, Component, inject, signal } from '@angular/core';
import { FormBuilder, ReactiveFormsModule, Validators } from '@angular/forms';
import { MatButtonModule } from '@angular/material/button';
import { MAT_DIALOG_DATA, MatDialogModule, MatDialogRef } from '@angular/material/dialog';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatIconModule } from '@angular/material/icon';
import { MatInputModule } from '@angular/material/input';
import { MatProgressSpinnerModule } from '@angular/material/progress-spinner';
import { Observable } from 'rxjs';

import { ApplicationEmailLookupResult } from '../../../core/models/job-offer.model';

export interface SendApplicationDialogData {
  toEmail: string;
  subject: string;
  message: string;
  jobTitle?: string;
  companyName?: string;
  /**
   * Vom Editor injizierter Lookup-Callback (KTD6) - hält den Dialog frei von
   * einer direkten HTTP-Abhängigkeit und testbar. `force` erzwingt einen
   * erneuten Lookup (R11-Re-Run).
   */
  findApplicationEmail?: (force: boolean) => Observable<ApplicationEmailLookupResult>;
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
    MatProgressSpinnerModule,
  ],
  templateUrl: './send-application-dialog.component.html',
  styleUrl: './send-application-dialog.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class SendApplicationDialogComponent {
  private readonly dialogRef = inject(MatDialogRef<SendApplicationDialogComponent, SendApplicationDialogResult>);
  private readonly formBuilder = inject(FormBuilder);
  protected readonly data = inject<SendApplicationDialogData>(MAT_DIALOG_DATA);

  protected readonly form = this.formBuilder.nonNullable.group({
    to_email: [this.data.toEmail, [Validators.required, Validators.email]],
    subject: [this.data.subject],
    message: [this.data.message],
  });

  protected readonly lookingUp = signal(false);
  protected readonly lookupResult = signal<ApplicationEmailLookupResult | null>(null);

  /** True, sobald eine Suche gelaufen ist oder bereits eine Adresse im Feld
   * steht - steuert die Beschriftung des Re-Run-Affordance (R11). */
  protected hasRecipientOrResult(): boolean {
    return !!this.form.controls.to_email.value || this.lookupResult() !== null;
  }

  onFindApplicationEmail(): void {
    const find = this.data.findApplicationEmail;
    if (!find || this.lookingUp()) {
      return;
    }
    // Erneut suchen, sobald schon ein Ergebnis oder eine Adresse vorliegt -
    // sonst würde der Cache den Re-Run stillschweigend beantworten (R11).
    const force = this.hasRecipientOrResult();
    this.lookingUp.set(true);
    find(force).subscribe({
      next: (result) => {
        this.lookingUp.set(false);
        this.lookupResult.set(result);
        if (result.status === 'found' && result.email) {
          this.form.controls.to_email.setValue(result.email);
          this.form.controls.to_email.markAsDirty();
        }
      },
      error: () => {
        // Ein HTTP-Fehler ist laut A5 ein `failed`-Ergebnis (KTD4).
        this.lookingUp.set(false);
        this.lookupResult.set({ status: 'failed' });
      },
    });
  }

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
