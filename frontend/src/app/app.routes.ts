import { Routes } from '@angular/router';

import { cvBuilderCanDeactivateGuard } from './pages/cv-builder/cv-builder.guard';

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
    title: 'Job search',
  },
  {
    path: 'profile',
    loadComponent: () =>
      import('./pages/profile/profile.component').then((m) => m.ProfileComponent),
    title: 'Profile',
  },
  {
    path: 'cv-builder',
    loadComponent: () =>
      import('./pages/cv-builder/cv-builder.component').then((m) => m.CvBuilderComponent),
    canDeactivate: [cvBuilderCanDeactivateGuard],
    title: 'CV Builder',
  },
  {
    path: 'applications',
    loadComponent: () =>
      import('./pages/applications/applications.component').then(
        (m) => m.ApplicationsComponent,
      ),
    title: 'Applications',
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
    // U9/R5 (KTD12): eine konkrete Bewerbung ansteuern, wenn ein
    // Stellenangebot mehrere hat (je eine pro Profil) - ohne `applicationId`
    // (Route oben) löst der Editor auf die erste zurückgegebene Bewerbung
    // auf, was für den weiterhin häufigsten Fall (nur eine Bewerbung) genügt.
    path: 'editor/:jobOfferId/:applicationId',
    loadComponent: () =>
      import('./pages/application-editor/application-editor.component').then(
        (m) => m.ApplicationEditorComponent,
      ),
    title: 'Editor',
  },
  {
    path: 'sent-emails',
    loadComponent: () =>
      import('./pages/sent-emails/sent-emails.component').then((m) => m.SentEmailsComponent),
    title: 'Sent Emails',
  },
  {
    path: '**',
    redirectTo: 'job-search',
  },
];
