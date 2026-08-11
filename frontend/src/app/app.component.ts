import { ChangeDetectionStrategy, Component } from '@angular/core';
import { NavLayoutComponent } from './layout/nav-layout/nav-layout.component';

@Component({
  selector: 'app-root',
  standalone: true,
  imports: [NavLayoutComponent],
  templateUrl: './app.component.html',
  styleUrl: './app.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class AppComponent {
  protected readonly title = 'Application Manager';
}
