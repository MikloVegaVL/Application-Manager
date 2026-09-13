import { ComponentFixture, TestBed } from '@angular/core/testing';
import { provideHttpClient } from '@angular/common/http';
import { provideHttpClientTesting, HttpTestingController } from '@angular/common/http/testing';
import { FormBuilder } from '@angular/forms';
import { provideRouter } from '@angular/router';
import { NoopAnimationsModule } from '@angular/platform-browser/animations';

import { CvBuilderComponent } from './cv-builder.component';
import { TranslationService } from '../../core/services/translation.service';

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
  content_language: 'de',
  content_translations_json: {},
  cv_filename: null,
  attachments: [],
  created_at: new Date().toISOString(),
  updated_at: new Date().toISOString(),
};

describe('CvBuilderComponent', () => {
  let component: CvBuilderComponent;
  let fixture: ComponentFixture<CvBuilderComponent>;
  let httpMock: HttpTestingController;
  let i18n: TranslationService;

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
    i18n = TestBed.inject(TranslationService);
    i18n.setLanguage('de');
  });

  afterEach(() => {
    i18n.setLanguage('de');
    httpMock.verify();
  });

  /** `PhotoSectionComponent` und `CvPreviewExportComponent` laden beim
   * Erstellen selbstständig ihr eigenes `GET /profile/photo` bzw.
   * `GET /cv-builder/templates` (alle Tabs werden eager instanziiert, siehe
   * `cv-builder.component.ts`) - unabhängig vom `GET /profile` der
   * Elternkomponente. `responseType: 'blob'` verlangt einen Blob-Body auch
   * für den Error-Flush, TestRequest.flush konvertiert Objekte nicht
   * automatisch. */
  const flushDependentRequests = (): void => {
    httpMock
      .expectOne((r) => r.url.endsWith('/profile/photo') && r.method === 'GET')
      .flush(new Blob(), { status: 404, statusText: 'Not Found' });
    httpMock
      .expectOne((r) => r.url.endsWith('/cv-builder/templates') && r.method === 'GET')
      .flush(templatesFixture);
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

  it('renders English UI labels when the global language is English (R3)', () => {
    i18n.setLanguage('en');
    goToReady();

    const compiled = fixture.nativeElement as HTMLElement;
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

    // Grobe Hardcoded-German-Scan: keine der deutschen Sektions-/Aktionslabels
    // darf im englischen UI übrig bleiben (R3/R4).
    const germanLeftovers = [
      'Zusammenfassung',
      'Berufserfahrung',
      'Ausbildung',
      'Projekte',
      'Sprachen',
      'Speichern',
      'Unternehmen',
      'Position',
      'Beschreibung',
      'Niveau',
      'Noch keine',
      'Vorlage',
      'Vorschau',
    ];
    for (const german of germanLeftovers) {
      expect(compiled.textContent).not.toContain(german);
    }
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

    const req = httpMock.expectOne((r) => r.url.endsWith('/profile') && r.method === 'PATCH');
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
      // KTD1: die aktive Sprache (globaler Selektor) plus der bestehende
      // Übersetzungs-Snapshot aus dem geladenen Profil.
      content_language: 'de',
      content_translations_json: {},
    });
    expect(Object.keys(req.request.body)).not.toContain('full_name');
    expect(Object.keys(req.request.body)).not.toContain('photo_path');

    // fix(review) #4 fixture correction: the mock backend must echo back
    // template_id: 'classic' too, matching what the PATCH body above actually
    // sent (auto-selected by CvPreviewExportComponent since the profile had
    // no saved template yet) - otherwise lastSavedProfile would disagree with
    // templateIdControl for a reason unrelated to what this test checks.
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

  it('sends the active content language as content_language on save (R2)', () => {
    goToReady({ template_id: 'classic' });
    i18n.setLanguage('en');
    // P1: der Save schickt die aktive Inhaltssprache - der Sprachwechsel muss
    // also erst abgeschlossen sein (leeres Profil: kein Übersetzungsaufruf).
    fixture.detectChanges();

    component['summaryControl'].setValue('Neue Zusammenfassung');
    component['save']();

    const req = httpMock.expectOne((r) => r.url.endsWith('/profile') && r.method === 'PATCH');
    expect(req.request.body.content_language).toBe('en');
    expect(Object.keys(req.request.body)).not.toContain('document_language');
    req.flush({ ...baseProfileResponse, template_id: 'classic', content_language: 'en' });
    fixture.detectChanges();
  });

  it('preserves a fresh inactive-language snapshot on save (KTD1)', () => {
    const snapshot = { summary: 'Experienced developer.' };
    goToReady({ template_id: 'classic', content_translations_json: snapshot });

    component['save']();

    const req = httpMock.expectOne((r) => r.url.endsWith('/profile') && r.method === 'PATCH');
    expect(req.request.body.content_translations_json).toEqual(snapshot);
    req.flush({ ...baseProfileResponse, template_id: 'classic', content_translations_json: snapshot });
    fixture.detectChanges();
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

  // --- U5: zweisprachiger Inhalt mit automatischer Übersetzung (R5-R9) -----

  const flushTranslation = (body: {
    translations?: Record<string, string>;
    errors?: Record<string, string>;
  }): void => {
    const req = httpMock.expectOne((r) => r.url.endsWith('/cv-builder/translate') && r.method === 'POST');
    req.flush({ translations: body.translations ?? {}, errors: body.errors ?? {} });
  };

  it('switching language generates the other version and preserves the original (AE3, R5/R6)', () => {
    goToReady({ template_id: 'classic', summary: 'Hallo', berufsbezeichnung: 'Entwickler' });
    expect(component['summaryControl'].value).toBe('Hallo');

    i18n.setLanguage('en');
    fixture.detectChanges();

    const req = httpMock.expectOne((r) => r.url.endsWith('/cv-builder/translate') && r.method === 'POST');
    expect(req.request.body.source_language).toBe('de');
    expect(req.request.body.target_language).toBe('en');
    expect(req.request.body.fields.summary).toBe('Hallo');
    expect(req.request.body.fields.berufsbezeichnung).toBe('Entwickler');
    req.flush({
      translations: { summary: 'Hello', berufsbezeichnung: 'Developer' },
      errors: {},
    });
    fixture.detectChanges();

    expect(component['summaryControl'].value).toBe('Hello');
    expect(component['berufsbezeichnungControl'].value).toBe('Developer');
    expect(component['translationError']()).toBeNull();

    // Zurückschalten nutzt den deutschen Snapshot, ohne erneut zu übersetzen.
    i18n.setLanguage('de');
    fixture.detectChanges();

    expect(component['summaryControl'].value).toBe('Hallo');
    expect(component['berufsbezeichnungControl'].value).toBe('Entwickler');
    httpMock.expectNone((r) => r.url.endsWith('/cv-builder/translate'));
  });

  it('editing a prose field marks the other language stale and re-translates on switch (AE4, R7)', () => {
    goToReady({ template_id: 'classic', summary: 'Hallo' });

    i18n.setLanguage('en');
    fixture.detectChanges();
    flushTranslation({ translations: { summary: 'Hello' } });
    fixture.detectChanges();
    expect(component['summaryControl'].value).toBe('Hello');

    i18n.setLanguage('de');
    fixture.detectChanges();
    expect(component['summaryControl'].value).toBe('Hallo');

    // Nutzereingabe in der aktiven Sprache invalidiert den EN-Snapshot.
    component['summaryControl'].setValue('Neue Zusammenfassung');

    i18n.setLanguage('en');
    fixture.detectChanges();

    const req = httpMock.expectOne((r) => r.url.endsWith('/cv-builder/translate') && r.method === 'POST');
    expect(req.request.body.fields.summary).toBe('Neue Zusammenfassung');
    req.flush({ translations: { summary: 'New summary' }, errors: {} });
    fixture.detectChanges();

    expect(component['summaryControl'].value).toBe('New summary');
  });

  it('a failed translation keeps the original text and surfaces a non-blocking error (AE6, R9)', () => {
    goToReady({ template_id: 'classic', summary: 'Hallo' });

    i18n.setLanguage('en');
    fixture.detectChanges();
    flushTranslation({ errors: { summary: 'Ollama nicht erreichbar' } });
    fixture.detectChanges();

    expect(component['summaryControl'].value).toBe('Hallo');
    expect(component['translationError']()).toBeTruthy();
    expect(component['translating']()).toBeFalse();

    const compiled = fixture.nativeElement as HTMLElement;
    expect(compiled.querySelector('.cv-builder-page__translate-error')).toBeTruthy();
  });

  it('applies the stored other-language snapshot on load when the global language differs (U5)', () => {
    i18n.setLanguage('en');
    goToReady({
      template_id: 'classic',
      content_language: 'de',
      summary: 'Hallo',
      content_translations_json: { summary: 'Hello' },
    });

    expect(component['summaryControl'].value).toBe('Hello');
    httpMock.expectNone((r) => r.url.endsWith('/cv-builder/translate'));
  });

  it('translates the loaded content when the global language differs and no snapshot exists (U5, R6)', () => {
    i18n.setLanguage('en');
    goToReady({ template_id: 'classic', content_language: 'de', summary: 'Hallo' });

    flushTranslation({ translations: { summary: 'Hello' } });
    fixture.detectChanges();

    expect(component['summaryControl'].value).toBe('Hello');
  });

  it('sends the inactive-language snapshot and the active language on save (U5, KTD1)', () => {
    goToReady({ template_id: 'classic', summary: 'Hallo' });

    i18n.setLanguage('en');
    fixture.detectChanges();
    flushTranslation({ translations: { summary: 'Hello' } });
    fixture.detectChanges();

    component['save']();
    const req = httpMock.expectOne((r) => r.url.endsWith('/profile') && r.method === 'PATCH');
    expect(req.request.body.content_language).toBe('en');
    expect(req.request.body.summary).toBe('Hello');
    expect(req.request.body.content_translations_json.summary).toBe('Hallo');
    req.flush({
      ...baseProfileResponse,
      template_id: 'classic',
      summary: 'Hello',
      content_language: 'en',
      content_translations_json: { summary: 'Hallo' },
    });
    fixture.detectChanges();
  });

  it('a language switch alone does not trip hasUnsavedChanges(), but a later edit does (U5)', () => {
    goToReady({ template_id: 'classic', summary: 'Hallo' });
    expect(component.hasUnsavedChanges()).toBeFalse();

    i18n.setLanguage('en');
    fixture.detectChanges();
    flushTranslation({ translations: { summary: 'Hello' } });
    fixture.detectChanges();

    expect(component.hasUnsavedChanges()).toBeFalse();

    component['summaryControl'].setValue('Edited in English');
    expect(component.hasUnsavedChanges()).toBeTrue();
  });

  // --- fix(review) P1-P3: Übersetzungs-Robustheit ------------------------

  it('P1: a totally failed translation keeps the source language and the save payload in it', () => {
    goToReady({ template_id: 'classic', summary: 'Hallo' });

    i18n.setLanguage('en');
    fixture.detectChanges();
    flushTranslation({ errors: { summary: 'Ollama nicht erreichbar' } });
    fixture.detectChanges();

    // Inhalt, aktive Sprache und Fehler bleiben unangetastet.
    expect(component['summaryControl'].value).toBe('Hallo');
    expect(component['activeContentLanguage']).toBe('de');
    expect(component['translationError']()).toBeTruthy();

    component['save']();
    const req = httpMock.expectOne((r) => r.url.endsWith('/profile') && r.method === 'PATCH');
    expect(req.request.body.content_language).toBe('de');
    expect(req.request.body.summary).toBe('Hallo');
    req.flush({ ...baseProfileResponse, template_id: 'classic', summary: 'Hallo', content_language: 'de' });
    fixture.detectChanges();
  });

  it('P1: an edit during an in-flight translation cannot be overwritten (prose controls disabled)', () => {
    goToReady({ template_id: 'classic', summary: 'Hallo' });

    i18n.setLanguage('en');
    fixture.detectChanges();

    // Während die Übersetzung läuft, sind die Prosa-Felder deaktiviert -
    // eine Nutzereingabe kann die Antwort also nicht überschreiben.
    expect(component['summaryControl'].disabled).toBeTrue();
    const textarea = (fixture.nativeElement as HTMLElement).querySelector('textarea') as HTMLTextAreaElement;
    expect(textarea.disabled).toBeTrue();

    flushTranslation({ translations: { summary: 'Hello' } });
    fixture.detectChanges();

    expect(component['summaryControl'].disabled).toBeFalse();
    expect(component['summaryControl'].value).toBe('Hello');
  });

  it('P1: a non-prose edit made during an in-flight translation is preserved', () => {
    goToReady({
      template_id: 'classic',
      summary: 'Hallo',
      experiences_json: [
        { company: 'Acme', role: 'Entwickler', start_date: null, end_date: null, description: 'Text' },
      ],
    });

    i18n.setLanguage('en');
    fixture.detectChanges();

    const companyControl = component['experiencesArray'].at(0).get('company');
    expect(companyControl?.disabled).toBeFalse();
    companyControl?.setValue('Neue Firma');

    flushTranslation({
      translations: { summary: 'Hello', 'experience.0.role': 'Developer', 'experience.0.description': 'Text' },
    });
    fixture.detectChanges();

    expect(component['experiencesArray'].at(0).get('company')?.value).toBe('Neue Firma');
    expect(component['summaryControl'].value).toBe('Hello');
  });

  it('P2: an edit followed by a language switch keeps hasUnsavedChanges() true', () => {
    goToReady({ template_id: 'classic', summary: 'Hallo' });
    expect(component.hasUnsavedChanges()).toBeFalse();

    component['summaryControl'].setValue('Neue Zusammenfassung');
    expect(component.hasUnsavedChanges()).toBeTrue();

    i18n.setLanguage('en');
    fixture.detectChanges();
    flushTranslation({ translations: { summary: 'New summary' } });
    fixture.detectChanges();

    expect(component['summaryControl'].value).toBe('New summary');
    expect(component.hasUnsavedChanges()).toBeTrue();
  });

  it('P2: an import replacement adopts the header language and invalidates the other snapshot', () => {
    goToReady({ template_id: 'classic', summary: 'Hallo' });

    // Totale Übersetzungsfehlschlag: Inhalt bleibt deutsch, Header steht auf en.
    i18n.setLanguage('en');
    fixture.detectChanges();
    flushTranslation({ errors: { summary: 'Ollama nicht erreichbar' } });
    fixture.detectChanges();
    expect(component['activeContentLanguage']).toBe('de');

    // Der Import ersetzt den Inhalt in der aktuellen Header-Sprache (en).
    component['onImportContentReplaced']();
    component['save']();

    const req = httpMock.expectOne((r) => r.url.endsWith('/profile') && r.method === 'PATCH');
    expect(req.request.body.content_language).toBe('en');
    expect(req.request.body.content_translations_json).toEqual({});
    req.flush({ ...baseProfileResponse, template_id: 'classic', content_language: 'en' });
    fixture.detectChanges();
  });

  it('P3: editing a non-translatable field keeps the other-language snapshot fresh', () => {
    goToReady({
      template_id: 'classic',
      summary: 'Hallo',
      experiences_json: [
        { company: 'Acme', role: 'Entwickler', start_date: null, end_date: null, description: 'Text' },
      ],
      content_translations_json: {
        summary: 'Hello',
        'experience.0.role': 'Developer',
        'experience.0.description': 'Text',
      },
    });

    // Nur die (nicht übersetzbare) Firma ändern.
    component['experiencesArray'].at(0).get('company')?.setValue('Neue Firma');

    i18n.setLanguage('en');
    fixture.detectChanges();

    // Der frische Snapshot wird direkt angewendet - keine neue Übersetzung.
    expect(component['summaryControl'].value).toBe('Hello');
    expect(component['experiencesArray'].at(0).get('role')?.value).toBe('Developer');
    httpMock.expectNone((r) => r.url.endsWith('/cv-builder/translate'));
  });
});
