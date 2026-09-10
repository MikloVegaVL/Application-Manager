import { ChangeDetectionStrategy, Component, inject, signal } from '@angular/core';
import { toSignal } from '@angular/core/rxjs-interop';
import { RouterLink, RouterLinkActive, RouterOutlet } from '@angular/router';
import { BreakpointObserver, Breakpoints } from '@angular/cdk/layout';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatListModule } from '@angular/material/list';
import { MatSidenavModule } from '@angular/material/sidenav';
import { MatToolbarModule } from '@angular/material/toolbar';
import { map } from 'rxjs/operators';

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
  ],
  templateUrl: './nav-layout.component.html',
  styleUrl: './nav-layout.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class NavLayoutComponent {
  private readonly breakpointObserver = inject(BreakpointObserver);

  protected readonly navItems: NavItem[] = [
    { path: '/job-search', label: 'Jobsuche', icon: 'search' },
    { path: '/profile', label: 'Profil', icon: 'person' },
    { path: '/cv-builder', label: 'Lebenslauf', icon: 'description' },
    { path: '/applications', label: 'Bewerbungen', icon: 'work_outline' },
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
