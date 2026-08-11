import { Routes } from '@angular/router';

export const routes: Routes = [
  {
    path: '',
    pathMatch: 'full',
    redirectTo: 'job-search',
  },
  {
    path: 'job-search',
    loadComponent: () =>
      import('./pages/job-search/job-search.component').then((m) => m.JobSearchComponent),
    title: 'Jobsuche',
  },
  {
    path: 'profile',
    loadComponent: () =>
      import('./pages/profile/profile.component').then((m) => m.ProfileComponent),
    title: 'Profil',
  },
  {
    path: 'applications',
    loadComponent: () =>
      import('./pages/applications/applications.component').then(
        (m) => m.ApplicationsComponent,
      ),
    title: 'Bewerbungen',
  },
  {
    path: 'editor',
    loadComponent: () =>
      import('./pages/editor/editor.component').then((m) => m.EditorComponent),
    title: 'Editor',
  },
  {
    path: '**',
    redirectTo: 'job-search',
  },
];
