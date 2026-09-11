import { ComponentFixture, TestBed } from '@angular/core/testing';
import { provideHttpClient } from '@angular/common/http';
import { provideHttpClientTesting, HttpTestingController } from '@angular/common/http/testing';
import { FormArray, FormBuilder, FormGroup } from '@angular/forms';
import { NoopAnimationsModule } from '@angular/platform-browser/animations';

import { MasterProfileRead, ParsedCvProfile } from '../../../core/models/master-profile.model';
import { CvImportComponent } from './cv-import.component';

const baseProfile: MasterProfileRead = {
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
  attachments: [],
  created_at: new Date().toISOString(),
  updated_at: new Date().toISOString(),
};

const parsedFixture: ParsedCvProfile = {
  full_name: 'Erika Musterfrau',
  email: 'erika@example.com',
  phone: '+49 123',
  address: 'Musterstraße 1',
  summary: 'Erfahrene Entwicklerin.',
  experiences: [
    { company: 'Acme', role: 'Engineer', start_date: '2020', end_date: null, description: 'Built things.' },
  ],
  education: [
    { institution: 'Uni', degree: 'B.Sc.', field_of_study: 'CS', start_date: '2016', end_date: '2019' },
  ],
  skills: ['TypeScript', 'Angular'],
  projects: [{ title: 'Side Project', description: 'A thing.', start_date: null, end_date: null, link: null }],
};

describe('CvImportComponent', () => {
  let fixture: ComponentFixture<CvImportComponent>;
  let component: CvImportComponent;
  let httpMock: HttpTestingController;
  let formBuilder: FormBuilder;
  let experiencesArray: FormArray<FormGroup>;
  let educationArray: FormArray<FormGroup>;
  let skillsArray: FormArray<FormGroup>;
  let projectsArray: FormArray<FormGroup>;
  let summaryControl: ReturnType<FormBuilder['nonNullable']['control']>;

  const setInputs = (lastSavedProfile: MasterProfileRead | null): void => {
    fixture.componentRef.setInput('summaryControl', summaryControl);
    fixture.componentRef.setInput('experiencesArray', experiencesArray);
    fixture.componentRef.setInput('educationArray', educationArray);
    fixture.componentRef.setInput('skillsArray', skillsArray);
    fixture.componentRef.setInput('projectsArray', projectsArray);
    fixture.componentRef.setInput('lastSavedProfile', lastSavedProfile);
    fixture.detectChanges();
  };

  const pdfFile = (name = 'cv.pdf'): File => new File([new Blob(['%PDF-1.4'])], name, { type: 'application/pdf' });

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [CvImportComponent, NoopAnimationsModule],
      providers: [provideHttpClient(), provideHttpClientTesting()],
    }).compileComponents();

    fixture = TestBed.createComponent(CvImportComponent);
    component = fixture.componentInstance;
    httpMock = TestBed.inject(HttpTestingController);
    formBuilder = TestBed.inject(FormBuilder);

    summaryControl = formBuilder.nonNullable.control('');
    experiencesArray = formBuilder.array<FormGroup>([]);
    educationArray = formBuilder.array<FormGroup>([]);
    skillsArray = formBuilder.array<FormGroup>([]);
    projectsArray = formBuilder.array<FormGroup>([]);
  });

  afterEach(() => {
    httpMock.verify();
  });

  it('should create', () => {
    setInputs(baseProfile);
    expect(component).toBeTruthy();
  });

  it('uploads a PDF, populates the form sections, and shows the identity fields read-only (no save call)', () => {
    setInputs(baseProfile);

    component.onFileSelected({ target: { files: [pdfFile()] } } as unknown as Event);

    const req = httpMock.expectOne((r) => r.url.endsWith('/cv-builder/parse') && r.method === 'POST');
    expect(req.request.body instanceof FormData).toBeTrue();
    req.flush({ parsed: parsedFixture, warnings: ['phone'] });
    fixture.detectChanges();

    expect(summaryControl.value).toBe('Erfahrene Entwicklerin.');
    expect(experiencesArray.getRawValue()).toEqual([
      { company: 'Acme', role: 'Engineer', start_date: '2020', end_date: '', description: 'Built things.' },
    ]);
    expect(educationArray.length).toBe(1);
    expect(skillsArray.getRawValue()).toEqual([
      { name: 'TypeScript', level: 'Grundkenntnisse' },
      { name: 'Angular', level: 'Grundkenntnisse' },
    ]);
    expect(projectsArray.length).toBe(1);

    // KTD1: Name/Kontakt nur zur Anzeige, nie in ein Formularfeld geschrieben.
    expect(component['parsedResult']()?.full_name).toBe('Erika Musterfrau');
    const compiled = fixture.nativeElement as HTMLElement;
    expect(compiled.textContent).toContain('Erika Musterfrau');
    expect(compiled.textContent).toContain('erika@example.com');

    httpMock.expectNone((r) => r.url.endsWith('/profile') && r.method === 'PATCH');
  });

  it('shows an inline error near the dropzone on parse failure, and retry re-triggers the upload', () => {
    setInputs(baseProfile);

    component.onFileSelected({ target: { files: [pdfFile()] } } as unknown as Event);
    httpMock
      .expectOne((r) => r.url.endsWith('/cv-builder/parse') && r.method === 'POST')
      .flush({ detail: 'KI nicht erreichbar' }, { status: 502, statusText: 'Bad Gateway' });

    fixture.detectChanges();
    expect(component['errorMessage']()).toContain('KI nicht erreichbar');
    const compiled = fixture.nativeElement as HTMLElement;
    const retryButton = compiled.querySelector('.cv-import__error button') as HTMLButtonElement;
    expect(retryButton).toBeTruthy();

    retryButton.click();
    const retryReq = httpMock.expectOne((r) => r.url.endsWith('/cv-builder/parse') && r.method === 'POST');
    retryReq.flush({ parsed: parsedFixture, warnings: [] });

    expect(component['errorMessage']()).toBeNull();
  });

  it('applies a re-parse directly without confirmation when no section has unsaved edits', () => {
    setInputs(baseProfile);

    component.onFileSelected({ target: { files: [pdfFile()] } } as unknown as Event);
    httpMock
      .expectOne((r) => r.url.endsWith('/cv-builder/parse') && r.method === 'POST')
      .flush({ parsed: parsedFixture, warnings: [] });

    expect(component['conflicts']()).toEqual([]);
    expect(experiencesArray.length).toBe(1);
  });

  it('warns before replacing a section with an unsaved hand-edited experience entry, and cancel leaves it untouched', () => {
    setInputs(baseProfile);

    // Hand-edited, unsaved experience entry (diverges from `lastSavedProfile`).
    experiencesArray.push(
      formBuilder.nonNullable.group({
        company: 'Hand-Edited Co',
        role: 'Hand Edited Role',
        start_date: '',
        end_date: '',
        description: '',
      }),
    );

    component.onFileSelected({ target: { files: [pdfFile()] } } as unknown as Event);
    httpMock
      .expectOne((r) => r.url.endsWith('/cv-builder/parse') && r.method === 'POST')
      .flush({ parsed: parsedFixture, warnings: [] });
    fixture.detectChanges();

    expect(component['conflicts']().map((c) => c.label)).toEqual(['Berufserfahrung']);
    // Education has no conflict - not applied yet either, pending the decision.
    expect(educationArray.length).toBe(0);

    const compiled = fixture.nativeElement as HTMLElement;
    expect(compiled.textContent).toContain('Berufserfahrung');

    const cancelButton = compiled.querySelector('.cv-import__conflict-actions button') as HTMLButtonElement;
    cancelButton.click();
    fixture.detectChanges();

    expect(component['conflicts']()).toEqual([]);
    expect(experiencesArray.getRawValue()).toEqual([
      {
        company: 'Hand-Edited Co',
        role: 'Hand Edited Role',
        start_date: '',
        end_date: '',
        description: '',
      },
    ]);
  });

  it('confirming a conflicted re-parse replaces only the named conflicting section(s)', () => {
    setInputs(baseProfile);

    experiencesArray.push(
      formBuilder.nonNullable.group({
        company: 'Hand-Edited Co',
        role: 'Hand Edited Role',
        start_date: '',
        end_date: '',
        description: '',
      }),
    );
    educationArray.push(
      formBuilder.nonNullable.group({
        institution: 'Existing Uni',
        degree: 'Existing Degree',
        field_of_study: '',
        start_date: '',
        end_date: '',
      }),
    );

    component.onFileSelected({ target: { files: [pdfFile()] } } as unknown as Event);
    httpMock
      .expectOne((r) => r.url.endsWith('/cv-builder/parse') && r.method === 'POST')
      .flush({ parsed: parsedFixture, warnings: [] });
    fixture.detectChanges();

    expect(component['conflicts']().map((c) => c.label).sort()).toEqual(['Ausbildung', 'Berufserfahrung']);

    const compiled = fixture.nativeElement as HTMLElement;
    const confirmButton = compiled.querySelectorAll('.cv-import__conflict-actions button')[1] as HTMLButtonElement;
    confirmButton.click();
    fixture.detectChanges();

    expect(component['conflicts']()).toEqual([]);
    expect(experiencesArray.getRawValue()).toEqual([
      { company: 'Acme', role: 'Engineer', start_date: '2020', end_date: '', description: 'Built things.' },
    ]);
    expect(educationArray.length).toBe(1);
    expect(educationArray.getRawValue()[0]['institution']).toBe('Uni');

    // Skills/Projects hatten keinen Konflikt (leer == leer, unverändert seit
    // `lastSavedProfile`) - "confirming replaces only the named section(s),
    // not sections that had no conflict": sie bleiben unangetastet, statt
    // aus dem neuen Parse befüllt zu werden.
    expect(skillsArray.length).toBe(0);
    expect(projectsArray.length).toBe(0);
  });
});
