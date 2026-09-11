import { ComponentFixture, TestBed } from '@angular/core/testing';
import { provideHttpClient } from '@angular/common/http';
import { provideHttpClientTesting, HttpTestingController } from '@angular/common/http/testing';
import { FormArray, FormBuilder, FormControl, FormGroup } from '@angular/forms';
import { NoopAnimationsModule } from '@angular/platform-browser/animations';

import { CvPreviewExportComponent } from './cv-preview-export.component';

const templatesFixture = [
  { id: 'classic', label: 'Classic' },
  { id: 'modern', label: 'Modern' },
];

describe('CvPreviewExportComponent', () => {
  let fixture: ComponentFixture<CvPreviewExportComponent>;
  let component: CvPreviewExportComponent;
  let httpMock: HttpTestingController;
  let formBuilder: FormBuilder;

  let summaryControl: FormControl<string>;
  let experiencesArray: FormArray<FormGroup>;
  let educationArray: FormArray<FormGroup>;
  let skillsArray: FormArray<FormGroup>;
  let languagesArray: FormArray<FormGroup>;
  let projectsArray: FormArray<FormGroup>;
  let templateIdControl: FormControl<string | null>;

  const setInputs = (): void => {
    fixture.componentRef.setInput('summaryControl', summaryControl);
    fixture.componentRef.setInput('experiencesArray', experiencesArray);
    fixture.componentRef.setInput('educationArray', educationArray);
    fixture.componentRef.setInput('skillsArray', skillsArray);
    fixture.componentRef.setInput('languagesArray', languagesArray);
    fixture.componentRef.setInput('projectsArray', projectsArray);
    fixture.componentRef.setInput('templateIdControl', templateIdControl);
    fixture.detectChanges();
  };

  const flushTemplates = (templates = templatesFixture): void => {
    httpMock
      .expectOne((r) => r.url.endsWith('/cv-builder/templates') && r.method === 'GET')
      .flush(templates);
    fixture.detectChanges();
  };

  const expectedPayload = (overrides: Record<string, unknown> = {}) => ({
    template_id: 'classic',
    summary: '',
    experiences_json: [],
    education_json: [],
    skills_json: [],
    languages_json: [],
    projects_json: [],
    ...overrides,
  });

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [CvPreviewExportComponent, NoopAnimationsModule],
      providers: [provideHttpClient(), provideHttpClientTesting()],
    }).compileComponents();

    fixture = TestBed.createComponent(CvPreviewExportComponent);
    component = fixture.componentInstance;
    httpMock = TestBed.inject(HttpTestingController);
    formBuilder = TestBed.inject(FormBuilder);

    summaryControl = formBuilder.nonNullable.control('');
    experiencesArray = formBuilder.array<FormGroup>([]);
    educationArray = formBuilder.array<FormGroup>([]);
    skillsArray = formBuilder.array<FormGroup>([]);
    languagesArray = formBuilder.array<FormGroup>([]);
    projectsArray = formBuilder.array<FormGroup>([]);
    templateIdControl = new FormControl<string | null>(null);
  });

  afterEach(() => {
    httpMock.verify();
  });

  it('should create', () => {
    setInputs();
    flushTemplates();
    expect(component).toBeTruthy();
  });

  it('loads templates and renders a picker; selecting one updates the shared templateId control', () => {
    setInputs();
    flushTemplates();

    const compiled = fixture.nativeElement as HTMLElement;
    const toggles = compiled.querySelectorAll('mat-button-toggle');
    expect(toggles.length).toBe(2);

    // KTD8: no prior selection (null) -> first available template pre-selected.
    expect(templateIdControl.value).toBe('classic');

    const secondToggleButton = toggles[1].querySelector('button') as HTMLButtonElement;
    secondToggleButton.click();
    fixture.detectChanges();

    expect(templateIdControl.value).toBe('modern');
  });

  it('does not override an already-selected template when templates load', () => {
    templateIdControl.setValue('modern');
    setInputs();
    flushTemplates();

    expect(templateIdControl.value).toBe('modern');
  });

  it('shows an error with a retry action when templates fail to load', () => {
    setInputs();
    httpMock
      .expectOne((r) => r.url.endsWith('/cv-builder/templates') && r.method === 'GET')
      .flush({ detail: 'boom' }, { status: 500, statusText: 'Server Error' });
    fixture.detectChanges();

    const compiled = fixture.nativeElement as HTMLElement;
    expect(compiled.textContent).toContain('Vorlagen konnten nicht geladen werden.');

    const retryButton = compiled.querySelector('.cv-preview-export__error button') as HTMLButtonElement;
    retryButton.click();
    const retryReq = httpMock.expectOne((r) => r.url.endsWith('/cv-builder/templates') && r.method === 'GET');
    retryReq.flush(templatesFixture);
    fixture.detectChanges();

    expect(compiled.querySelectorAll('mat-button-toggle').length).toBe(2);
  });

  it('preview sends the current form content, shows a loading indicator while pending, and displays the PDF on success', () => {
    setInputs();
    flushTemplates();

    const compiled = fixture.nativeElement as HTMLElement;
    const previewButton = compiled.querySelectorAll('.cv-preview-export__actions button')[0] as HTMLButtonElement;
    previewButton.click();
    fixture.detectChanges();

    expect(component['previewLoading']()).toBeTrue();
    expect(compiled.querySelector('.cv-preview-export__actions mat-progress-spinner')).toBeTruthy();

    const req = httpMock.expectOne((r) => r.url.endsWith('/cv-builder/preview') && r.method === 'POST');
    expect(req.request.body).toEqual(expectedPayload());
    expect(req.request.responseType).toBe('blob');

    req.flush(new Blob(['%PDF-1.4'], { type: 'application/pdf' }), {
      headers: { 'Content-Disposition': 'inline; filename="lebenslauf-vorschau.pdf"' },
    });
    fixture.detectChanges();

    expect(component['previewLoading']()).toBeFalse();
    const embed = compiled.querySelector('embed');
    expect(embed).toBeTruthy();
    expect(embed?.getAttribute('src')).toMatch(/^blob:/);
  });

  it('shows an error message (not a stale preview) when the preview request fails with 404/422/500', () => {
    setInputs();
    flushTemplates();

    const compiled = fixture.nativeElement as HTMLElement;
    const previewButton = compiled.querySelectorAll('.cv-preview-export__actions button')[0] as HTMLButtonElement;

    // First produce a successful preview, then verify a subsequent failure clears it.
    previewButton.click();
    httpMock
      .expectOne((r) => r.url.endsWith('/cv-builder/preview') && r.method === 'POST')
      .flush(new Blob(['%PDF-1.4'], { type: 'application/pdf' }));
    fixture.detectChanges();
    expect(compiled.querySelector('embed')).toBeTruthy();

    previewButton.click();
    httpMock
      .expectOne((r) => r.url.endsWith('/cv-builder/preview') && r.method === 'POST')
      .flush(new Blob(), { status: 404, statusText: 'Not Found' });
    fixture.detectChanges();

    expect(component['previewError']()).toBe('Es wurde noch kein Profil angelegt.');
    expect(compiled.querySelector('embed')).toBeFalsy();
    expect(compiled.textContent).toContain('Es wurde noch kein Profil angelegt.');
  });

  it('shows a 422-specific error message for an invalid template', () => {
    setInputs();
    flushTemplates();

    const compiled = fixture.nativeElement as HTMLElement;
    const previewButton = compiled.querySelectorAll('.cv-preview-export__actions button')[0] as HTMLButtonElement;
    previewButton.click();
    httpMock
      .expectOne((r) => r.url.endsWith('/cv-builder/preview') && r.method === 'POST')
      .flush(new Blob(), { status: 422, statusText: 'Unprocessable Entity' });
    fixture.detectChanges();

    expect(component['previewError']()).toBe('Die gewählte Vorlage ist ungültig.');
  });

  it('shows a 500-specific error message when rendering fails', () => {
    setInputs();
    flushTemplates();

    const compiled = fixture.nativeElement as HTMLElement;
    const previewButton = compiled.querySelectorAll('.cv-preview-export__actions button')[0] as HTMLButtonElement;
    previewButton.click();
    httpMock
      .expectOne((r) => r.url.endsWith('/cv-builder/preview') && r.method === 'POST')
      .flush(new Blob(), { status: 500, statusText: 'Server Error' });
    fixture.detectChanges();

    expect(component['previewError']()).toBe('Der Lebenslauf konnte nicht als PDF erzeugt werden.');
  });

  it('export sends the same body and triggers a browser download using the Content-Disposition filename', () => {
    setInputs();
    flushTemplates();

    let downloadedFilename: string | undefined;
    let downloadedHref: string | undefined;
    spyOn(HTMLAnchorElement.prototype, 'click').and.callFake(function (this: HTMLAnchorElement): void {
      downloadedFilename = this.download;
      downloadedHref = this.href;
    });

    const compiled = fixture.nativeElement as HTMLElement;
    const exportButton = compiled.querySelectorAll('.cv-preview-export__actions button')[1] as HTMLButtonElement;
    exportButton.click();
    fixture.detectChanges();

    expect(component['exporting']()).toBeTrue();

    const req = httpMock.expectOne((r) => r.url.endsWith('/cv-builder/export') && r.method === 'POST');
    expect(req.request.body).toEqual(expectedPayload());
    req.flush(new Blob(['%PDF-1.4'], { type: 'application/pdf' }), {
      headers: { 'Content-Disposition': 'attachment; filename="lebenslauf_Max_Mustermann.pdf"' },
    });
    fixture.detectChanges();

    expect(component['exporting']()).toBeFalse();
    expect(downloadedFilename).toBe('lebenslauf_Max_Mustermann.pdf');
    expect(downloadedHref).toMatch(/^blob:/);
  });

  it('falls back to a default filename when Content-Disposition has no filename', () => {
    setInputs();
    flushTemplates();

    let downloadedFilename: string | undefined;
    spyOn(HTMLAnchorElement.prototype, 'click').and.callFake(function (this: HTMLAnchorElement): void {
      downloadedFilename = this.download;
    });

    const compiled = fixture.nativeElement as HTMLElement;
    const exportButton = compiled.querySelectorAll('.cv-preview-export__actions button')[1] as HTMLButtonElement;
    exportButton.click();
    httpMock
      .expectOne((r) => r.url.endsWith('/cv-builder/export') && r.method === 'POST')
      .flush(new Blob(['%PDF-1.4'], { type: 'application/pdf' }));
    fixture.detectChanges();

    expect(downloadedFilename).toBe('lebenslauf.pdf');
  });

  it('shows an error message when export fails', () => {
    setInputs();
    flushTemplates();

    const compiled = fixture.nativeElement as HTMLElement;
    const exportButton = compiled.querySelectorAll('.cv-preview-export__actions button')[1] as HTMLButtonElement;
    exportButton.click();
    httpMock
      .expectOne((r) => r.url.endsWith('/cv-builder/export') && r.method === 'POST')
      .flush(new Blob(), { status: 500, statusText: 'Server Error' });
    fixture.detectChanges();

    expect(component['exportError']()).toBe('Der Lebenslauf konnte nicht als PDF erzeugt werden.');
    expect(compiled.textContent).toContain('Der Lebenslauf konnte nicht als PDF erzeugt werden.');
  });

  it('KTD11: preview/export body reflects an unsaved edit made after the last save, not the saved profile', () => {
    setInputs();
    flushTemplates();

    // Simulates an edit made in the form after the last save, without saving again.
    summaryControl.setValue('Unsaved summary edit');

    const compiled = fixture.nativeElement as HTMLElement;
    const previewButton = compiled.querySelectorAll('.cv-preview-export__actions button')[0] as HTMLButtonElement;
    previewButton.click();

    const req = httpMock.expectOne((r) => r.url.endsWith('/cv-builder/preview') && r.method === 'POST');
    expect(req.request.body.summary).toBe('Unsaved summary edit');
    req.flush(new Blob(['%PDF-1.4'], { type: 'application/pdf' }));
  });
});
