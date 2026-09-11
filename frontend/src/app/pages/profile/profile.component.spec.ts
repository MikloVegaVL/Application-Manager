import { ComponentFixture, TestBed } from '@angular/core/testing';
import { provideHttpClient } from '@angular/common/http';
import { provideHttpClientTesting, HttpTestingController } from '@angular/common/http/testing';
import { provideRouter } from '@angular/router';
import { NoopAnimationsModule } from '@angular/platform-browser/animations';

import { ProfileComponent } from './profile.component';

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

    // Initialer GET /api/profile-Aufruf aus ngOnInit abfangen (404 = noch kein Profil).
    httpMock.expectOne((req) => req.url.endsWith('/profile')).flush(
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
    const labels = Array.from(compiled.querySelectorAll('.mat-mdc-tab .mdc-tab__text-label')).map((el) =>
      el.textContent?.trim(),
    );

    expect(labels).toEqual(['Persönliche Daten', 'Lebenslauf-Anhang', 'Weitere Anhänge']);
    expect(labels).not.toContain('Berufserfahrung & Ausbildung');
    expect(labels).not.toContain('Skills & Zertifikate');
    expect(labels).not.toContain('CV-Import');

    expect(compiled.querySelector('input[formcontrolname="full_name"]')).toBeTruthy();
    expect(compiled.querySelector('input[formcontrolname="email"]')).toBeTruthy();
    expect(compiled.querySelector('input[formcontrolname="phone"]')).toBeTruthy();
    expect(compiled.querySelector('input[formcontrolname="address"]')).toBeTruthy();
    expect(compiled.querySelector('textarea[formcontrolname="summary"]')).toBeFalsy();
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

      const req = httpMock.expectOne((r) => r.url.endsWith('/profile/cv-file') && r.method === 'POST');
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

      const req = httpMock.expectOne((r) => r.url.endsWith('/profile/cv-file') && r.method === 'DELETE');
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

      const req = httpMock.expectOne((r) => r.url.endsWith('/profile/attachments') && r.method === 'POST');
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

      const req = httpMock.expectOne((r) => r.url.endsWith('/profile/attachments/1') && r.method === 'DELETE');
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
    summary: 'Erfahrene Softwareentwicklerin.',
    experiences_json: [
      { company: 'Acme GmbH', role: 'Senior Engineer', start_date: '2020', end_date: null, description: 'Backend.' },
    ],
    education_json: [
      { institution: 'TU Berlin', degree: 'MSc', field_of_study: 'Informatik', start_date: '2015', end_date: '2019' },
    ],
    skills_json: [{ name: 'TypeScript', level: 'Experte' }],
    languages_json: [{ name: 'Englisch', level: 'C1' }],
    projects_json: [
      { title: 'Portfolio', description: 'Persönliche Website.', start_date: '2022', end_date: null, link: null },
    ],
    photo_filename: 'photo.jpg',
    template_id: 'modern',
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

    httpMock.expectOne((req) => req.url.endsWith('/profile') && req.method === 'GET').flush(loadedProfileFixture);
  });

  afterEach(() => {
    httpMock.verify();
  });

  it('sends a PUT payload whose non-identity fields match the last-loaded profile exactly', () => {
    component['profileForm'].patchValue({ full_name: 'Erika Musterfrau' });

    component.onSubmit();

    const getReq = httpMock.expectOne((r) => r.url.endsWith('/profile') && r.method === 'GET');
    getReq.flush(loadedProfileFixture);

    const req = httpMock.expectOne((r) => r.url.endsWith('/profile') && r.method === 'PUT');
    const body = req.request.body;

    expect(body.full_name).toBe('Erika Musterfrau');
    expect(body.email).toBe(loadedProfileFixture.email);
    expect(body.phone).toBe(loadedProfileFixture.phone);
    expect(body.address).toBe(loadedProfileFixture.address);

    expect(body.summary).toBe(loadedProfileFixture.summary);
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

    const getReq = httpMock.expectOne((r) => r.url.endsWith('/profile') && r.method === 'GET');
    getReq.flush(updatedElsewhere);

    const req = httpMock.expectOne((r) => r.url.endsWith('/profile') && r.method === 'PUT');
    expect(req.request.body.experiences_json).toEqual(updatedElsewhere.experiences_json);
    expect(req.request.body.photo_filename).toBe('new-photo-from-other-tab.jpg');

    req.flush(updatedElsewhere);
  });

  it('fix(review) #1: still saves identity-only changes when no profile exists yet (404 on the pre-submit fetch)', () => {
    component['profileForm'].patchValue({ full_name: 'Neu Angelegt' });
    component.onSubmit();

    const getReq = httpMock.expectOne((r) => r.url.endsWith('/profile') && r.method === 'GET');
    getReq.flush({ detail: 'not found' }, { status: 404, statusText: 'Not Found' });

    const req = httpMock.expectOne((r) => r.url.endsWith('/profile') && r.method === 'PUT');
    expect(req.request.body.full_name).toBe('Neu Angelegt');
    expect(req.request.body.experiences_json).toEqual([]);

    req.flush({ ...loadedProfileFixture, full_name: 'Neu Angelegt' });
  });
});
