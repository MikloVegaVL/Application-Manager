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
    path: 'cv-builder',
    loadComponent: () =>
      import('./pages/cv-builder/cv-builder.component').then((m) => m.CvBuilderComponent),
    title: 'Lebenslauf',
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
      import('./pages/application-editor/application-editor.component').then(
        (m) => m.ApplicationEditorComponent,
      ),
    title: 'Editor',
  },
  {
    path: 'editor/:jobOfferId',
    loadComponent: () =>
      import('./pages/application-editor/application-editor.component').then(
        (m) => m.ApplicationEditorComponent,
      ),
    title: 'Editor',
  },
  {
    path: '**',
    redirectTo: 'job-search',
  },
];
