import { ChangeDetectionStrategy, Component, inject } from '@angular/core';
import { FormBuilder, ReactiveFormsModule } from '@angular/forms';
import { MatButtonModule } from '@angular/material/button';
import { MatCheckboxModule } from '@angular/material/checkbox';
import { MatDialogModule, MatDialogRef } from '@angular/material/dialog';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatInputModule } from '@angular/material/input';

/** Dialog result - matches the arguments `onStartPortalFill` already accepts from
 * today's inline trigger form (`applicationFormUrl`, `dryRun`). Callers use
 * `onStartPortalFill(application, result.url, result.dryRun)`. */
export interface StartPortalFillDialogResult {
  url: string;
  dryRun: boolean;
}

@Component({
  selector: 'app-start-portal-fill-dialog',
  standalone: true,
  imports: [
    ReactiveFormsModule,
    MatButtonModule,
    MatCheckboxModule,
    MatDialogModule,
    MatFormFieldModule,
    MatInputModule,
  ],
  templateUrl: './start-portal-fill-dialog.component.html',
  styleUrl: './start-portal-fill-dialog.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class StartPortalFillDialogComponent {
  private readonly dialogRef = inject(MatDialogRef<StartPortalFillDialogComponent, StartPortalFillDialogResult>);
  private readonly formBuilder = inject(FormBuilder);

  /** No validator - the inline trigger form had none either; trimming and the
   * empty check stay in `onStartPortalFill` itself (R8: no new validation). */
  protected readonly form = this.formBuilder.nonNullable.group({
    url: [''],
    dryRun: [false],
  });

  onCancel(): void {
    this.dialogRef.close();
  }

  onConfirm(): void {
    this.dialogRef.close(this.form.getRawValue());
  }
}
