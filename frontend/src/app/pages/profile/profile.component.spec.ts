import { ComponentFixture, TestBed } from '@angular/core/testing';
import { provideHttpClient } from '@angular/common/http';
import { provideHttpClientTesting, HttpTestingController } from '@angular/common/http/testing';
import { NoopAnimationsModule } from '@angular/platform-browser/animations';

import { ProfileComponent } from './profile.component';

describe('ProfileComponent', () => {
  let component: ProfileComponent;
  let fixture: ComponentFixture<ProfileComponent>;
  let httpMock: HttpTestingController;

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [ProfileComponent, NoopAnimationsModule],
      providers: [provideHttpClient(), provideHttpClientTesting()],
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

  it('should start with an empty experiences/education array', () => {
    expect(component['experiencesArray'].length).toBe(0);
    expect(component['educationArray'].length).toBe(0);
  });

  it('should add and remove skills', () => {
    component['skills'].set(['Python']);
    component.removeSkill('Python');
    expect(component['skills']()).toEqual([]);
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
        cv_filename: null,
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
      });

      expect(component['cvFilename']()).toBeNull();
    });
  });
});
