import { ComponentFixture, TestBed } from '@angular/core/testing';
import { provideHttpClient } from '@angular/common/http';
import { provideHttpClientTesting, HttpTestingController } from '@angular/common/http/testing';
import { provideRouter } from '@angular/router';
import { NoopAnimationsModule } from '@angular/platform-browser/animations';

import { CvBuilderComponent } from './cv-builder.component';

describe('CvBuilderComponent', () => {
  let component: CvBuilderComponent;
  let fixture: ComponentFixture<CvBuilderComponent>;
  let httpMock: HttpTestingController;

  const flushProfileRequest = (status: number, body: object = { detail: 'error' }): void => {
    const req = httpMock.expectOne((r) => r.url.endsWith('/profile') && r.method === 'GET');
    if (status >= 200 && status < 300) {
      req.flush(body);
    } else {
      req.flush(body, { status, statusText: 'Error' });
    }
  };

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [CvBuilderComponent, NoopAnimationsModule],
      providers: [provideHttpClient(), provideHttpClientTesting(), provideRouter([])],
    }).compileComponents();

    fixture = TestBed.createComponent(CvBuilderComponent);
    component = fixture.componentInstance;
    httpMock = TestBed.inject(HttpTestingController);
  });

  afterEach(() => {
    httpMock.verify();
  });

  it('should create', () => {
    fixture.detectChanges();
    flushProfileRequest(404);
    expect(component).toBeTruthy();
  });

  it('shows a loading indicator while GET /profile is pending', () => {
    fixture.detectChanges();

    const compiled = fixture.nativeElement as HTMLElement;
    expect(compiled.querySelector('mat-progress-spinner')).toBeTruthy();
    expect(compiled.querySelector('mat-tab-group')).toBeFalsy();

    flushProfileRequest(404);
  });

  it('renders the empty state (not a form) when GET /profile returns 404', () => {
    fixture.detectChanges();
    flushProfileRequest(404);
    fixture.detectChanges();

    const compiled = fixture.nativeElement as HTMLElement;
    expect(compiled.querySelector('mat-progress-spinner')).toBeFalsy();
    expect(compiled.querySelector('mat-tab-group')).toBeFalsy();
    expect(compiled.textContent).toContain('noch kein Profil');
    expect(compiled.querySelector('a[routerLink="/profile"]')).toBeTruthy();
  });

  it('renders a distinct error state with a retry action when GET /profile fails with a non-404 error', () => {
    fixture.detectChanges();
    flushProfileRequest(500);
    fixture.detectChanges();

    const compiled = fixture.nativeElement as HTMLElement;
    expect(compiled.querySelector('mat-progress-spinner')).toBeFalsy();
    expect(compiled.querySelector('mat-tab-group')).toBeFalsy();
    expect(compiled.textContent).not.toContain('noch kein Profil');
    const retryButton = compiled.querySelector('button.cv-builder-page__retry') as HTMLButtonElement | null;
    expect(retryButton).toBeTruthy();

    retryButton?.click();
    flushProfileRequest(404);
  });

  it('renders the tabbed shell when GET /profile succeeds', () => {
    fixture.detectChanges();
    flushProfileRequest(200, {
      id: 1,
      full_name: 'Max Mustermann',
      email: 'max@example.com',
      phone: null,
      address: null,
      summary: null,
      experiences_json: [],
      education_json: [],
      skills_json: [],
      cv_filename: null,
      created_at: new Date().toISOString(),
      updated_at: new Date().toISOString(),
    });
    fixture.detectChanges();

    const compiled = fixture.nativeElement as HTMLElement;
    expect(compiled.querySelector('mat-progress-spinner')).toBeFalsy();
    expect(compiled.querySelector('mat-tab-group')).toBeTruthy();
    const labels = Array.from(compiled.querySelectorAll('.mat-mdc-tab .mdc-tab__text-label')).map(
      (el) => el.textContent?.trim(),
    );
    expect(labels).toEqual([
      'Zusammenfassung',
      'Berufserfahrung',
      'Ausbildung',
      'Skills',
      'Sprachen',
      'Projekte',
      'Foto',
      'Import',
      'Vorschau & Export',
    ]);
  });
});
