import { ComponentFixture, TestBed } from '@angular/core/testing';
import { provideHttpClient } from '@angular/common/http';
import { provideHttpClientTesting, HttpTestingController } from '@angular/common/http/testing';
import { FormBuilder } from '@angular/forms';
import { provideRouter } from '@angular/router';
import { By } from '@angular/platform-browser';
import { NoopAnimationsModule } from '@angular/platform-browser/animations';
import { MatTabGroup } from '@angular/material/tabs';

import { CvBuilderComponent } from './cv-builder.component';

const templatesFixture = [
  { id: 'classic', label: 'Classic' },
  { id: 'template-1', label: 'Template 1' },
];

const baseProfileResponse = {
  id: 1,
  full_name: 'Max Mustermann',
  email: 'max@example.com',
  phone: null,
  address: null,
  summary: null,
  berufsbezeichnung: null,
  experiences_json: [],
  education_json: [],
  skills_json: [],
  languages_json: [],
  projects_json: [],
  photo_filename: null,
  template_id: null,
  cv_filename: null,
  attachments: [],
  created_at: new Date().toISOString(),
  updated_at: new Date().toISOString(),
};

describe('CvBuilderComponent', () => {
  let component: CvBuilderComponent;
  let fixture: ComponentFixture<CvBuilderComponent>;
  let httpMock: HttpTestingController;

  const flushProfileRequest = (
    status: number,
    body: object = { detail: 'error' },
    profileType: 'it' | 'full_life' = 'it',
  ): void => {
    const req = httpMock.expectOne((r) => r.url.endsWith(`/profile/${profileType}`) && r.method === 'GET');
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

  /** `PhotoSectionComponent` und `CvPreviewExportComponent` laden beim
   * Erstellen selbstständig ihr eigenes `GET /profile/photo` bzw.
   * `GET /cv-builder/templates` (alle Tabs werden eager instanziiert, siehe
   * `cv-builder.component.ts`) - unabhängig vom `GET /profile` der
   * Elternkomponente. `responseType: 'blob'` verlangt einen Blob-Body auch
   * für den Error-Flush, TestRequest.flush konvertiert Objekte nicht
   * automatisch. */
  const flushDependentRequests = (
    profileType: 'it' | 'full_life' = 'it',
    { includeTemplates = true }: { includeTemplates?: boolean } = {},
  ): void => {
    // `PhotoSectionComponent` re-fetches per profile type switch (`profile_type`
    // scoped, R3); `CvPreviewExportComponent`'s templates are global and load
    // only once in `ngOnInit` - a profile-type switch must not re-expect them.
    httpMock
      .expectOne((r) => r.url.endsWith(`/profile/${profileType}/photo`) && r.method === 'GET')
      .flush(new Blob(), { status: 404, statusText: 'Not Found' });
    if (includeTemplates) {
      httpMock
        .expectOne((r) => r.url.endsWith('/cv-builder/templates') && r.method === 'GET')
        .flush(templatesFixture);
    }
  };

  /** Bringt die Komponente in den `ready`-Zustand mit dem gegebenen Profil
   * (Merge über `baseProfileResponse`). */
  const goToReady = (overrides: Record<string, unknown> = {}): void => {
    fixture.detectChanges();
    flushProfileRequest(200, { ...baseProfileResponse, ...overrides });
    fixture.detectChanges();
    flushDependentRequests();
    fixture.detectChanges();
  };

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
    expect(compiled.textContent).toContain('No profile has been created yet');
    expect(compiled.querySelector('a[routerLink="/profile"]')).toBeTruthy();
  });

  it('renders a distinct error state with a retry action when GET /profile fails with a non-404 error', () => {
    fixture.detectChanges();
    flushProfileRequest(500);
    fixture.detectChanges();

    const compiled = fixture.nativeElement as HTMLElement;
    expect(compiled.querySelector('mat-progress-spinner')).toBeFalsy();
    expect(compiled.querySelector('mat-tab-group')).toBeFalsy();
    expect(compiled.textContent).not.toContain('No profile has been created yet');
    const retryButton = compiled.querySelector('button.cv-builder-page__retry') as HTMLButtonElement | null;
    expect(retryButton).toBeTruthy();

    retryButton?.click();
    flushProfileRequest(404);
  });

  // AE3: no language selector/translate affordance exists anywhere - the
  // tab labels (and every other UI string) are always the hardcoded English
  // text.
  it('renders the tabbed shell in English when GET /profile succeeds', () => {
    fixture.detectChanges();
    flushProfileRequest(200, baseProfileResponse);
    fixture.detectChanges();
    flushDependentRequests();
    fixture.detectChanges();

    const compiled = fixture.nativeElement as HTMLElement;
    expect(compiled.querySelector('mat-progress-spinner')).toBeFalsy();
    expect(compiled.querySelector('mat-tab-group')).toBeTruthy();
    const labels = Array.from(compiled.querySelectorAll('.mat-mdc-tab .mdc-tab__text-label')).map(
      (el) => el.textContent?.trim(),
    );
    expect(labels).toEqual([
      'Summary',
      'Work experience',
      'Education',
      'Skills',
      'Languages',
      'Projects',
      'Photo',
      'Import',
      'Preview & export',
    ]);

    const saveButton = compiled.querySelector('.cv-builder-page__save-bar button') as HTMLButtonElement;
    expect(saveButton.textContent).toContain('Save');
  });

  // ce-debug 2026-09-12: reproduces the crash seen against a backend running
  // pre-CV-Builder code (or a not-yet-migrated database) - its `GET /profile`
  // response simply doesn't have these fields at all, unlike a null/empty
  // value. Without `applyProfileToArrays`'s fallback, this throws "Cannot
  // read properties of undefined (reading 'forEach')" and the page never
  // reaches the ready state.
  it('renders the ready state without crashing when the backend response omits newer CV Builder fields', () => {
    const { languages_json, projects_json, photo_filename, ...staleBackendResponse } = baseProfileResponse;
    // template_id pinned to a non-null value (not destructured out, unlike
    // languages_json/projects_json above): CvPreviewExportComponent's KTD8
    // auto-select-first-template logic only fires when it's null, and that
    // interaction is unrelated to what this test checks (see the KTD12/
    // fix(review) #4 tests above for that case).
    const response = { ...staleBackendResponse, template_id: 'classic' };

    fixture.detectChanges();
    flushProfileRequest(200, response);
    fixture.detectChanges();
    flushDependentRequests();
    fixture.detectChanges();

    const compiled = fixture.nativeElement as HTMLElement;
    expect(compiled.querySelector('mat-progress-spinner')).toBeFalsy();
    expect(compiled.querySelector('mat-tab-group')).toBeTruthy();
    expect(component['languagesArray'].length).toBe(0);
    expect(component['projectsArray'].length).toBe(0);
    // fix(review) (ce-debug 2026-09-12): without normalizing lastSavedProfile
    // the same way applyProfileToArrays normalizes the FormArrays, this was
    // `true` with zero user edits - tripping the CanDeactivate guard and
    // beforeunload for exactly the version-skewed-backend case above.
    expect(component.hasUnsavedChanges()).toBeFalse();
  });

  it('saves via PATCH /profile with content fields only (no prior parse), and clears the unsaved-changes baseline', () => {
    goToReady();

    component['summaryControl'].setValue('New summary');
    const saveButton = (fixture.nativeElement as HTMLElement).querySelector(
      '.cv-builder-page__save-bar button',
    ) as HTMLButtonElement;
    expect(saveButton).toBeTruthy();
    saveButton.click();

    const req = httpMock.expectOne((r) => r.url.endsWith('/profile/it') && r.method === 'PATCH');
    expect(req.request.body).toEqual({
      summary: 'New summary',
      berufsbezeichnung: '',
      experiences_json: [],
      education_json: [],
      skills_json: [],
      languages_json: [],
      projects_json: [],
      // KTD8: `template_id` war auf dem Profil `null` -> `CvPreviewExportComponent`
      // hat beim Laden der Vorlagenliste (`templatesFixture`) die erste Vorlage vorbelegt.
      template_id: 'classic',
    });
    expect(Object.keys(req.request.body)).not.toContain('full_name');
    expect(Object.keys(req.request.body)).not.toContain('photo_path');

    req.flush({ ...baseProfileResponse, summary: 'New summary', template_id: 'classic' });
    fixture.detectChanges();

    expect(component.hasUnsavedChanges()).toBeFalse();
  });

  it('hasUnsavedChanges() treats a reordered-but-unchanged array as unchanged (KTD12)', () => {
    // template_id pinned to a non-null value so CvPreviewExportComponent's
    // KTD8 auto-select (which only fires when template_id is null) has
    // nothing to do here - this test is about skills-array reordering, not
    // template selection (see the fix(review) #4 test above for that).
    goToReady({
      template_id: 'classic',
      skills_json: [
        { name: 'TypeScript', level: 'Gut' },
        { name: 'Angular', level: 'Experte' },
      ],
    });

    const formBuilder = new FormBuilder();
    component['skillsArray'].clear();
    component['skillsArray'].push(formBuilder.nonNullable.group({ name: 'Angular', level: 'Experte' }));
    component['skillsArray'].push(formBuilder.nonNullable.group({ name: 'TypeScript', level: 'Gut' }));

    expect(component.hasUnsavedChanges()).toBeFalse();

    component['skillsArray'].at(0).get('level')?.setValue('Grundkenntnisse');
    expect(component.hasUnsavedChanges()).toBeTrue();
  });

  it('fix(review) #4: hasUnsavedChanges() is true when only template_id changed', () => {
    // save()'s PATCH payload includes template_id (asserted above), so a
    // template-only change must trip the same guard as any other section.
    goToReady({ template_id: 'classic' });

    expect(component.hasUnsavedChanges()).toBeFalse();

    component['templateIdControl'].setValue('template-1');

    expect(component.hasUnsavedChanges()).toBeTrue();
  });

  it('populates berufsbezeichnungControl from the loaded profile (R5)', () => {
    goToReady({ template_id: 'classic', berufsbezeichnung: 'Frontend Developer' });

    expect(component['berufsbezeichnungControl'].value).toBe('Frontend Developer');
  });

  it('hasUnsavedChanges() is true when only berufsbezeichnung changed (R5)', () => {
    goToReady({ template_id: 'classic', berufsbezeichnung: 'Frontend Developer' });

    expect(component.hasUnsavedChanges()).toBeFalse();

    component['berufsbezeichnungControl'].setValue('Full-Stack Developer');

    expect(component.hasUnsavedChanges()).toBeTrue();
  });

  it('onBeforeUnload prevents the default and sets returnValue when there are unsaved changes', () => {
    goToReady();
    component['summaryControl'].setValue('Unsaved edit');

    const event = {
      preventDefault: jasmine.createSpy('preventDefault'),
      returnValue: '',
    } as unknown as BeforeUnloadEvent;
    component.onBeforeUnload(event);

    expect(event.preventDefault).toHaveBeenCalled();
    expect(event.returnValue).toBe('');
  });

  it('onBeforeUnload does nothing when there are no unsaved changes', () => {
    // template_id pinned to a non-null value, same reasoning as the KTD12
    // reorder test above - this test isn't about template selection.
    goToReady({ template_id: 'classic' });

    const event = { preventDefault: jasmine.createSpy('preventDefault') } as unknown as BeforeUnloadEvent;
    component.onBeforeUnload(event);

    expect(event.preventDefault).not.toHaveBeenCalled();
  });

  // U7/R1/R3: two independent profiles, switched via the button-toggle above
  // the tab group.
  describe('profile-type switching (U7)', () => {
    it('renders the IT/Full-life toggle and defaults to "it"', () => {
      fixture.detectChanges();
      flushProfileRequest(404);
      fixture.detectChanges();

      const compiled = fixture.nativeElement as HTMLElement;
      const toggles = compiled.querySelectorAll('mat-button-toggle-group[aria-label="Choose profile type"] mat-button-toggle');
      expect(toggles.length).toBe(2);
      expect(component['profileType']()).toBe('it');
    });

    it('switching profile type with no unsaved changes reloads with the other profile\'s own data', () => {
      goToReady({ template_id: 'classic', summary: 'IT summary' });
      expect(component['summaryControl'].value).toBe('IT summary');

      component['onProfileTypeChange']('full_life');

      const req = httpMock.expectOne((r) => r.url.endsWith('/profile/full_life') && r.method === 'GET');
      req.flush({ ...baseProfileResponse, summary: 'Full-life summary', template_id: 'classic' });
      fixture.detectChanges();
      flushDependentRequests('full_life', { includeTemplates: false });
      fixture.detectChanges();

      expect(component['profileType']()).toBe('full_life');
      expect(component['summaryControl'].value).toBe('Full-life summary');
    });

    it('switching profile type with unsaved changes prompts a confirm dialog; declining keeps the current type', () => {
      goToReady({ template_id: 'classic' });
      component['summaryControl'].setValue('Unsaved edit');
      expect(component.hasUnsavedChanges()).toBeTrue();

      spyOn(window, 'confirm').and.returnValue(false);

      component['onProfileTypeChange']('full_life');

      expect(window.confirm).toHaveBeenCalled();
      httpMock.expectNone((r) => r.url.endsWith('/profile/full_life'));
      expect(component['profileType']()).toBe('it');
      expect(component['summaryControl'].value).toBe('Unsaved edit');
    });

    it('switching profile type with unsaved changes, then confirming, discards the edits and loads the other profile', () => {
      goToReady({ template_id: 'classic' });
      component['summaryControl'].setValue('Unsaved edit');

      spyOn(window, 'confirm').and.returnValue(true);

      component['onProfileTypeChange']('full_life');

      expect(window.confirm).toHaveBeenCalled();
      const req = httpMock.expectOne((r) => r.url.endsWith('/profile/full_life') && r.method === 'GET');
      req.flush({ ...baseProfileResponse, summary: 'Full-life summary', template_id: 'classic' });
      fixture.detectChanges();
      flushDependentRequests('full_life', { includeTemplates: false });
      fixture.detectChanges();

      expect(component['profileType']()).toBe('full_life');
      expect(component['summaryControl'].value).toBe('Full-life summary');
    });

    it('passes the selected profileType through to app-cv-preview-export', async () => {
      goToReady({ template_id: 'classic' });

      // Preview & export is the last tab (index 8: Summary, Work experience,
      // Education, Skills, Languages, Projects, Photo, Import, Preview &
      // export). `mat-tab-group`'s body content attaches only after its
      // (Noop, but still async) selection animation settles - awaiting
      // `whenStable()` (NgZone stabilization) is more reliable here than
      // `fakeAsync`'s timer-queue flush for the CDK animation callback.
      const tabGroup = fixture.debugElement.query(By.directive(MatTabGroup)).componentInstance as MatTabGroup;
      tabGroup.selectedIndex = 8;
      fixture.detectChanges();
      await fixture.whenStable();
      fixture.detectChanges();

      const preview = fixture.debugElement.query(By.css('app-cv-preview-export'));
      expect(preview.componentInstance.profileType).toBe('it');
    });
  });
});
