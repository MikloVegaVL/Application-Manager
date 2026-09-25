import { ComponentFixture, TestBed } from '@angular/core/testing';
import { provideHttpClient } from '@angular/common/http';
import { provideHttpClientTesting, HttpTestingController } from '@angular/common/http/testing';
import { provideRouter } from '@angular/router';
import { MatDialog } from '@angular/material/dialog';
import { NoopAnimationsModule } from '@angular/platform-browser/animations';
import { of } from 'rxjs';

import { ProfileComponent } from './profile.component';

/** Flush a `GET /profile/migration-status` request (U6/R8). Every test needs
 * this handled once, since `ngOnInit` always checks it before loading any
 * profile. */
const flushMigrationStatus = (
  httpMock: HttpTestingController,
  hasUntypedProfile = false,
): void => {
  httpMock
    .expectOne((req) => req.url.endsWith('/profile/migration-status') && req.method === 'GET')
    .flush({ has_untyped_profile: hasUntypedProfile });
};

describe('ProfileComponent', () => {
  let component: ProfileComponent;
  let fixture: ComponentFixture<ProfileComponent>;
  let httpMock: HttpTestingController;

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [ProfileComponent, NoopAnimationsModule],
      providers: [provideHttpClient(), provideHttpClientTesting(), provideRouter([])],
    }).compileComponents();

    fixture = TestBed.createComponent(ProfileComponent);
    component = fixture.componentInstance;
    httpMock = TestBed.inject(HttpTestingController);
    fixture.detectChanges();

    flushMigrationStatus(httpMock);
    fixture.detectChanges();

    // Initialer GET /api/profile/it-Aufruf aus ngOnInit abfangen (404 = noch kein Profil).
    httpMock.expectOne((req) => req.url.endsWith('/profile/it')).flush(
      { detail: 'not found' },
      { status: 404, statusText: 'Not Found' },
    );
  });

  afterEach(() => {
    httpMock.verify();
  });

  it('should create', () => {
    expect(component).toBeTruthy();
  });

  it('renders only identity fields and the file tabs - content-editing and AI CV-Import tabs are gone', () => {
    fixture.detectChanges();

    const compiled = fixture.nativeElement as HTMLElement;
    const labels = Array.from(
      compiled.querySelectorAll('.profile-page__field-tabs .mat-mdc-tab .mdc-tab__text-label'),
    ).map((el) => el.textContent?.trim());

    expect(labels).toEqual(['Personal details', 'CV attachment', 'Additional attachments']);
    expect(labels).not.toContain('Berufserfahrung & Ausbildung');
    expect(labels).not.toContain('Skills & Zertifikate');
    expect(labels).not.toContain('CV-Import');

    expect(compiled.querySelector('input[formcontrolname="full_name"]')).toBeTruthy();
    expect(compiled.querySelector('input[formcontrolname="email"]')).toBeTruthy();
    expect(compiled.querySelector('input[formcontrolname="phone"]')).toBeTruthy();
    expect(compiled.querySelector('input[formcontrolname="address"]')).toBeTruthy();
    expect(compiled.querySelector('textarea[formcontrolname="summary"]')).toBeFalsy();
  });

  it('renders the top-level IT / Full-life profile-type tabs', () => {
    fixture.detectChanges();

    const compiled = fixture.nativeElement as HTMLElement;
    // `> mat-tab-header` (direct child) scopes to the outer tab-group's own
    // header row only - a plain descendant selector also matches the nested
    // `.profile-page__field-tabs` tab-group's header, which lives inside the
    // outer group's active tab body.
    const labels = Array.from(
      compiled.querySelectorAll('.profile-page__type-tabs > mat-tab-header .mat-mdc-tab .mdc-tab__text-label'),
    ).map((el) => el.textContent?.trim());

    expect(labels).toEqual(['IT', 'Full-life/Non-IT']);
  });

  it('no longer exposes skill/experience/education editing APIs', () => {
    expect((component as unknown as Record<string, unknown>)['skills']).toBeUndefined();
    expect((component as unknown as Record<string, unknown>)['experiencesArray']).toBeUndefined();
    expect((component as unknown as Record<string, unknown>)['educationArray']).toBeUndefined();
    expect((component as unknown as Record<string, unknown>)['uploadCv']).toBeUndefined();
  });

  describe('Lebenslauf-Anhang', () => {
    const pdfFile = new File([new Blob(['%PDF-1.4'])], 'lebenslauf.pdf', { type: 'application/pdf' });

    it('rejects a non-PDF file without uploading', () => {
      const input = { files: [new File(['x'], 'lebenslauf.docx')] } as unknown as HTMLInputElement;
      component.onCvFileSelected({ target: input } as unknown as Event);

      expect(component['selectedCvFile']()).toBeNull();
    });

    it('uploads the selected CV file and stores the returned filename', () => {
      const input = { files: [pdfFile] } as unknown as HTMLInputElement;
      component.onCvFileSelected({ target: input } as unknown as Event);
      expect(component['selectedCvFile']()).toBe(pdfFile);

      component.uploadCvFile();

      const req = httpMock.expectOne((r) => r.url.endsWith('/profile/it/cv-file') && r.method === 'POST');
      req.flush({
        id: 1,
        full_name: 'Max Mustermann',
        email: 'max@example.com',
        phone: null,
        address: null,
        summary: null,
        experiences_json: [],
        education_json: [],
        skills_json: [],
        languages_json: [],
        projects_json: [],
        photo_filename: null,
        template_id: null,
        cv_filename: 'lebenslauf.pdf',
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
      });

      expect(component['cvFilename']()).toBe('lebenslauf.pdf');
      expect(component['selectedCvFile']()).toBeNull();
    });

    it('deletes the uploaded CV file and clears the filename', () => {
      component['cvFilename'].set('lebenslauf.pdf');

      component.deleteCvFile();

      const req = httpMock.expectOne((r) => r.url.endsWith('/profile/it/cv-file') && r.method === 'DELETE');
      req.flush({
        id: 1,
        full_name: 'Max Mustermann',
        email: 'max@example.com',
        phone: null,
        address: null,
        summary: null,
        experiences_json: [],
        education_json: [],
        skills_json: [],
        languages_json: [],
        projects_json: [],
        photo_filename: null,
        template_id: null,
        cv_filename: null,
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
      });

      expect(component['cvFilename']()).toBeNull();
    });
  });

  describe('Weitere Anhänge', () => {
    const pdfFile = new File([new Blob(['%PDF-1.4'])], 'zeugnis.pdf', { type: 'application/pdf' });
    const baseProfileResponse = {
      id: 1,
      full_name: 'Max Mustermann',
      email: 'max@example.com',
      phone: null,
      address: null,
      summary: null,
      experiences_json: [],
      education_json: [],
      skills_json: [],
      languages_json: [],
      projects_json: [],
      photo_filename: null,
      template_id: null,
      cv_filename: null,
      created_at: new Date().toISOString(),
      updated_at: new Date().toISOString(),
    };

    it('rejects a non-PDF file without uploading', () => {
      const input = { files: [new File(['x'], 'zeugnis.docx')] } as unknown as HTMLInputElement;
      component.onAttachmentFileSelected({ target: input } as unknown as Event);

      expect(component['selectedAttachmentFile']()).toBeNull();
    });

    it('refuses to select a file once the maximum is reached', () => {
      component['attachments'].set([
        { id: 1, filename: 'a.pdf', created_at: new Date().toISOString() },
        { id: 2, filename: 'b.pdf', created_at: new Date().toISOString() },
        { id: 3, filename: 'c.pdf', created_at: new Date().toISOString() },
      ]);

      const input = { files: [pdfFile] } as unknown as HTMLInputElement;
      component.onAttachmentFileSelected({ target: input } as unknown as Event);

      expect(component['selectedAttachmentFile']()).toBeNull();
    });

    it('uploads the selected attachment and stores the returned list', () => {
      const input = { files: [pdfFile] } as unknown as HTMLInputElement;
      component.onAttachmentFileSelected({ target: input } as unknown as Event);
      expect(component['selectedAttachmentFile']()).toBe(pdfFile);

      component.uploadAttachment();

      const req = httpMock.expectOne((r) => r.url.endsWith('/profile/it/attachments') && r.method === 'POST');
      req.flush({
        ...baseProfileResponse,
        attachments: [{ id: 1, filename: 'zeugnis.pdf', created_at: new Date().toISOString() }],
      });

      expect(component['attachments']().length).toBe(1);
      expect(component['attachments']()[0].filename).toBe('zeugnis.pdf');
      expect(component['selectedAttachmentFile']()).toBeNull();
    });

    it('deletes an attachment and stores the returned list', () => {
      component['attachments'].set([{ id: 1, filename: 'zeugnis.pdf', created_at: new Date().toISOString() }]);

      component.deleteAttachment(1);

      const req = httpMock.expectOne((r) => r.url.endsWith('/profile/it/attachments/1') && r.method === 'DELETE');
      req.flush({ ...baseProfileResponse, attachments: [] });

      expect(component['attachments']()).toEqual([]);
    });
  });
});

describe('ProfileComponent - non-destructive identity save (KTD14)', () => {
  let component: ProfileComponent;
  let fixture: ComponentFixture<ProfileComponent>;
  let httpMock: HttpTestingController;

  const loadedProfileFixture = {
    id: 42,
    full_name: 'Erika Mustermann',
    email: 'erika@example.com',
    phone: '+49 30 1234567',
    address: 'Musterstraße 1, Berlin',
    linkedin: 'linkedin.com/in/erika-mustermann',
    website: 'erika-mustermann.dev',
    summary: 'Erfahrene Softwareentwicklerin.',
    berufsbezeichnung: 'Frontend Developer',
    experiences_json: [
      { company: 'Acme GmbH', role: 'Senior Engineer', start_date: '2020', end_date: null, description: 'Backend.' },
    ],
    education_json: [
      {
        institution: 'TU Berlin',
        degree: 'MSc',
        field_of_study: 'Informatik',
        start_date: '2015',
        end_date: '2019',
        description: null,
      },
    ],
    skills_json: [{ name: 'TypeScript', level: 'Experte' }],
    languages_json: [{ name: 'Englisch', level: 'C1' }],
    projects_json: [
      { title: 'Portfolio', description: 'Persönliche Website.', start_date: '2022', end_date: null, link: null },
    ],
    photo_filename: 'photo.jpg',
    template_id: 'template-1',
    cv_filename: null,
    attachments: [],
    created_at: new Date().toISOString(),
    updated_at: new Date().toISOString(),
  };

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [ProfileComponent, NoopAnimationsModule],
      providers: [provideHttpClient(), provideHttpClientTesting(), provideRouter([])],
    }).compileComponents();

    fixture = TestBed.createComponent(ProfileComponent);
    component = fixture.componentInstance;
    httpMock = TestBed.inject(HttpTestingController);
    fixture.detectChanges();

    flushMigrationStatus(httpMock);
    fixture.detectChanges();

    httpMock.expectOne((req) => req.url.endsWith('/profile/it') && req.method === 'GET').flush(loadedProfileFixture);
  });

  afterEach(() => {
    httpMock.verify();
  });

  it('sends a PUT payload whose non-identity fields match the last-loaded profile exactly', () => {
    component['profileForm'].patchValue({ full_name: 'Erika Musterfrau' });

    component.onSubmit();

    const getReq = httpMock.expectOne((r) => r.url.endsWith('/profile/it') && r.method === 'GET');
    getReq.flush(loadedProfileFixture);

    const req = httpMock.expectOne((r) => r.url.endsWith('/profile/it') && r.method === 'PUT');
    const body = req.request.body;

    expect(body.full_name).toBe('Erika Musterfrau');
    expect(body.email).toBe(loadedProfileFixture.email);
    expect(body.phone).toBe(loadedProfileFixture.phone);
    expect(body.address).toBe(loadedProfileFixture.address);
    expect(body.linkedin).toBe(loadedProfileFixture.linkedin);
    expect(body.website).toBe(loadedProfileFixture.website);

    expect(body.summary).toBe(loadedProfileFixture.summary);
    expect(body.berufsbezeichnung).toBe(loadedProfileFixture.berufsbezeichnung);
    expect(body.experiences_json).toEqual(loadedProfileFixture.experiences_json);
    expect(body.education_json).toEqual(loadedProfileFixture.education_json);
    expect(body.skills_json).toEqual(loadedProfileFixture.skills_json);
    expect(body.languages_json).toEqual(loadedProfileFixture.languages_json);
    expect(body.projects_json).toEqual(loadedProfileFixture.projects_json);
    expect(body.photo_filename).toBe(loadedProfileFixture.photo_filename);
    expect(body.template_id).toBe(loadedProfileFixture.template_id);

    req.flush(loadedProfileFixture);
  });

  it('fix(review) #1: re-fetches the profile at submit time instead of reusing the initial-load snapshot, so a save in another tab is not reverted', () => {
    // Simulates the cross-tab scenario the finding describes: another tab
    // (e.g. the CV Builder) saved new content after this component's initial
    // load. onSubmit() must reflect that fresh state, not the stale snapshot
    // captured on ngOnInit.
    const updatedElsewhere = {
      ...loadedProfileFixture,
      experiences_json: [
        ...loadedProfileFixture.experiences_json,
        { company: 'Other GmbH', role: 'Added in another tab', start_date: '2024', end_date: null, description: null },
      ],
      photo_filename: 'new-photo-from-other-tab.jpg',
    };

    component['profileForm'].patchValue({ full_name: 'Erika Musterfrau' });
    component.onSubmit();

    const getReq = httpMock.expectOne((r) => r.url.endsWith('/profile/it') && r.method === 'GET');
    getReq.flush(updatedElsewhere);

    const req = httpMock.expectOne((r) => r.url.endsWith('/profile/it') && r.method === 'PUT');
    expect(req.request.body.experiences_json).toEqual(updatedElsewhere.experiences_json);
    expect(req.request.body.photo_filename).toBe('new-photo-from-other-tab.jpg');

    req.flush(updatedElsewhere);
  });

  it('fix(review) #1: still saves identity-only changes when no profile exists yet (404 on the pre-submit fetch)', () => {
    component['profileForm'].patchValue({ full_name: 'Neu Angelegt' });
    component.onSubmit();

    const getReq = httpMock.expectOne((r) => r.url.endsWith('/profile/it') && r.method === 'GET');
    getReq.flush({ detail: 'not found' }, { status: 404, statusText: 'Not Found' });

    const req = httpMock.expectOne((r) => r.url.endsWith('/profile/it') && r.method === 'PUT');
    expect(req.request.body.full_name).toBe('Neu Angelegt');
    expect(req.request.body.experiences_json).toEqual([]);

    req.flush({ ...loadedProfileFixture, full_name: 'Neu Angelegt' });
  });
});

describe('ProfileComponent - U7: two independent profile types', () => {
  let component: ProfileComponent;
  let fixture: ComponentFixture<ProfileComponent>;
  let httpMock: HttpTestingController;

  const itProfile = {
    id: 1,
    full_name: 'IT Person',
    email: 'it@example.com',
    phone: null,
    address: null,
    summary: null,
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

  const fullLifeProfile = {
    ...itProfile,
    id: 2,
    full_name: 'Full-life Person',
    email: 'fulllife@example.com',
  };

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [ProfileComponent, NoopAnimationsModule],
      providers: [provideHttpClient(), provideHttpClientTesting(), provideRouter([])],
    }).compileComponents();

    fixture = TestBed.createComponent(ProfileComponent);
    component = fixture.componentInstance;
    httpMock = TestBed.inject(HttpTestingController);
  });

  afterEach(() => {
    httpMock.verify();
  });

  it('switching the top-level tab from IT to Full-life with no unsaved edits loads that profile\'s own data with no cross-contamination', () => {
    fixture.detectChanges();
    flushMigrationStatus(httpMock);
    fixture.detectChanges();
    httpMock.expectOne((r) => r.url.endsWith('/profile/it') && r.method === 'GET').flush(itProfile);
    fixture.detectChanges();

    expect(component['profileForm'].value.full_name).toBe('IT Person');

    component['onTopTabIndexChange'](1);

    const req = httpMock.expectOne((r) => r.url.endsWith('/profile/full_life') && r.method === 'GET');
    req.flush(fullLifeProfile);
    fixture.detectChanges();

    expect(component['profileType']()).toBe('full_life');
    expect(component['profileForm'].value.full_name).toBe('Full-life Person');
    expect(component['profileForm'].value.email).toBe('fulllife@example.com');
  });

  it('shows the migration dialog before rendering any profile content when has_untyped_profile is true, and applies the chosen type', () => {
    const dialog = fixture.debugElement.injector.get(MatDialog);
    spyOn(dialog, 'open').and.returnValue({ afterClosed: () => of('it') } as never);

    fixture.detectChanges();
    httpMock
      .expectOne((r) => r.url.endsWith('/profile/migration-status') && r.method === 'GET')
      .flush({ has_untyped_profile: true });
    fixture.detectChanges();

    // No profile GET should have happened yet - the dialog is blocking.
    httpMock.expectNone((r) => r.url.endsWith('/profile/it') && r.method === 'GET');

    expect(dialog.open).toHaveBeenCalled();

    const migrateReq = httpMock.expectOne((r) => r.url.endsWith('/profile/migrate') && r.method === 'POST');
    expect(migrateReq.request.body).toEqual({ profile_type: 'it' });
    migrateReq.flush(itProfile);
    fixture.detectChanges();

    expect(component['initializing']()).toBeFalse();
    expect(component['profileType']()).toBe('it');
    expect(component['profileForm'].value.full_name).toBe('IT Person');

    const compiled = fixture.nativeElement as HTMLElement;
    expect(compiled.querySelector('.profile-page__type-tabs')).toBeTruthy();
  });

  it('does not show the migration dialog when has_untyped_profile is false', () => {
    const dialog = fixture.debugElement.injector.get(MatDialog);
    spyOn(dialog, 'open');

    fixture.detectChanges();
    flushMigrationStatus(httpMock, false);
    fixture.detectChanges();
    httpMock.expectOne((r) => r.url.endsWith('/profile/it') && r.method === 'GET').flush(itProfile);
    fixture.detectChanges();

    expect(dialog.open).not.toHaveBeenCalled();
  });

  it('switching tabs with unsaved edits prompts a confirm/discard dialog; declining keeps the edits and the current tab', () => {
    fixture.detectChanges();
    flushMigrationStatus(httpMock);
    fixture.detectChanges();
    httpMock.expectOne((r) => r.url.endsWith('/profile/it') && r.method === 'GET').flush(itProfile);
    fixture.detectChanges();

    // `patchValue` alone never marks a Reactive Forms control dirty - only
    // real user input (or an explicit `markAsDirty()`) does. Mirrors what a
    // real keystroke would do, since `onTopTabIndexChange` gates on `dirty`.
    component['profileForm'].patchValue({ full_name: 'Edited but unsaved' });
    component['profileForm'].markAsDirty();
    expect(component['profileForm'].dirty).toBeTrue();

    const dialog = fixture.debugElement.injector.get(MatDialog);
    spyOn(dialog, 'open').and.returnValue({ afterClosed: () => of(false) } as never);

    component['onTopTabIndexChange'](1);

    expect(dialog.open).toHaveBeenCalled();
    // Declined -> no reload of the other profile, current tab/edits intact.
    httpMock.expectNone((r) => r.url.endsWith('/profile/full_life'));
    expect(component['profileType']()).toBe('it');
    expect(component['profileForm'].value.full_name).toBe('Edited but unsaved');
    expect(component['profileTypeIndex']()).toBe(0);
  });

  it('switching tabs with unsaved edits, then accepting, discards the edits and loads the other profile', () => {
    fixture.detectChanges();
    flushMigrationStatus(httpMock);
    fixture.detectChanges();
    httpMock.expectOne((r) => r.url.endsWith('/profile/it') && r.method === 'GET').flush(itProfile);
    fixture.detectChanges();

    component['profileForm'].patchValue({ full_name: 'Edited but unsaved' });
    component['profileForm'].markAsDirty();

    const dialog = fixture.debugElement.injector.get(MatDialog);
    spyOn(dialog, 'open').and.returnValue({ afterClosed: () => of(true) } as never);

    component['onTopTabIndexChange'](1);

    const req = httpMock.expectOne((r) => r.url.endsWith('/profile/full_life') && r.method === 'GET');
    req.flush(fullLifeProfile);
    fixture.detectChanges();

    expect(component['profileType']()).toBe('full_life');
    expect(component['profileForm'].value.full_name).toBe('Full-life Person');
  });
});
