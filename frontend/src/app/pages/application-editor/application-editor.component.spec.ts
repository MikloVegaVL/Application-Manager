import { ComponentFixture, TestBed } from '@angular/core/testing';
import { provideHttpClient } from '@angular/common/http';
import { provideHttpClientTesting, HttpTestingController } from '@angular/common/http/testing';
import { NoopAnimationsModule } from '@angular/platform-browser/animations';

import { ApplicationEditorComponent } from './application-editor.component';

describe('ApplicationEditorComponent', () => {
  let component: ApplicationEditorComponent;
  let fixture: ComponentFixture<ApplicationEditorComponent>;
  let httpMock: HttpTestingController;

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [ApplicationEditorComponent, NoopAnimationsModule],
      providers: [provideHttpClient(), provideHttpClientTesting()],
    }).compileComponents();

    fixture = TestBed.createComponent(ApplicationEditorComponent);
    fixture.componentRef.setInput('jobOfferId', '1');
    component = fixture.componentInstance;
    httpMock = TestBed.inject(HttpTestingController);
    fixture.detectChanges();
  });

  afterEach(() => {
    httpMock.verify();
  });

  it('should create and request job + application data for the given jobOfferId', () => {
    expect(component).toBeTruthy();

    const jobReq = httpMock.expectOne((req) => req.url.endsWith('/jobs/1'));
    jobReq.flush({
      id: 1,
      title: 'Backend Engineer',
      company: 'Acme GmbH',
      location: 'Berlin',
      source_url: 'https://example.com/jobs/1',
      description_text: null,
      source_platform: 'arbeitsagentur',
      created_at: '2026-08-11T00:00:00',
      is_processed: false,
    });

    const appReq = httpMock.expectOne((req) => req.url.endsWith('/applications/by-job-offer/1'));
    appReq.flush({ detail: 'not found' }, { status: 404, statusText: 'Not Found' });

    const generateReq = httpMock.expectOne((req) => req.url.endsWith('/applications/generate'));
    expect(generateReq.request.body).toEqual({ job_offer_id: 1 });
    generateReq.flush({
      id: 1,
      job_offer_id: 1,
      cover_letter_text: 'Sehr geehrte Damen und Herren,',
      tailored_cv_json: {
        full_name: 'Erika Musterfrau',
        email: 'erika@example.com',
        phone: null,
        address: null,
        summary: 'Zusammenfassung',
        experiences: [],
        education: [],
        skills: ['Angular'],
      },
      pdf_path: '/generated/applications/application_1.pdf',
      status: 'draft',
      sent_at: null,
      created_at: '2026-08-11T00:00:00',
    });

    const pdfReq = httpMock.expectOne((req) => req.url.endsWith('/applications/1/pdf'));
    pdfReq.flush(new Blob(['%PDF-1.4'], { type: 'application/pdf' }));

    expect(component['application']()?.id).toBe(1);
    expect(component['skills']()).toEqual(['Angular']);
  });
});
