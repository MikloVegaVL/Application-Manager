import { ChangeDetectionStrategy, Component, inject, signal } from '@angular/core';
import { toSignal } from '@angular/core/rxjs-interop';
import { RouterLink, RouterLinkActive, RouterOutlet } from '@angular/router';
import { BreakpointObserver, Breakpoints } from '@angular/cdk/layout';
import { MatButtonModule } from '@angular/material/button';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatIconModule } from '@angular/material/icon';
import { MatListModule } from '@angular/material/list';
import { MatSelectModule } from '@angular/material/select';
import { MatSidenavModule } from '@angular/material/sidenav';
import { MatToolbarModule } from '@angular/material/toolbar';
import { map } from 'rxjs/operators';

import { ThemeService } from '../../core/services/theme.service';

interface NavItem {
  path: string;
  label: string;
  icon: string;
}

@Component({
  selector: 'app-nav-layout',
  standalone: true,
  imports: [
    RouterOutlet,
    RouterLink,
    RouterLinkActive,
    MatToolbarModule,
    MatSidenavModule,
    MatListModule,
    MatIconModule,
    MatButtonModule,
    MatFormFieldModule,
    MatSelectModule,
  ],
  templateUrl: './nav-layout.component.html',
  styleUrl: './nav-layout.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class NavLayoutComponent {
  private readonly breakpointObserver = inject(BreakpointObserver);
  protected readonly theme = inject(ThemeService);

  protected readonly navItems: NavItem[] = [
    { path: '/job-search', label: 'Job search', icon: 'search' },
    { path: '/profile', label: 'Profile', icon: 'person' },
    { path: '/cv-builder', label: 'CV Builder', icon: 'description' },
    { path: '/applications', label: 'Applications', icon: 'work_outline' },
    { path: '/editor', label: 'Editor', icon: 'edit_document' },
  ];

  /** Auf mobilen Viewports wird der Sidenav standardmäßig als Overlay geführt. */
  protected readonly isHandset = toSignal(
    this.breakpointObserver
      .observe(Breakpoints.Handset)
      .pipe(map((result) => result.matches)),
    { initialValue: false },
  );

  protected readonly sidenavOpened = signal(true);

  toggleSidenav(): void {
    this.sidenavOpened.update((opened) => !opened);
  }
}
