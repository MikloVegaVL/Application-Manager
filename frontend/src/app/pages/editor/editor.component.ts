import { ChangeDetectionStrategy, Component, input } from '@angular/core';

@Component({
  selector: 'app-editor',
  standalone: true,
  imports: [],
  templateUrl: './editor.component.html',
  styleUrl: './editor.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class EditorComponent {
  /** Wird über den Routenparameter `:jobOfferId` per Component-Input-Binding befüllt. */
  readonly jobOfferId = input<string>();
}
