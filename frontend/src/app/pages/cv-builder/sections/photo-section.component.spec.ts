import { ComponentFixture, TestBed } from '@angular/core/testing';
import { provideHttpClient } from '@angular/common/http';
import { provideHttpClientTesting, HttpTestingController } from '@angular/common/http/testing';
import { NoopAnimationsModule } from '@angular/platform-browser/animations';

import { PhotoSectionComponent } from './photo-section.component';

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
  photo_filename: 'photo.jpg',
  template_id: null,
  cv_filename: null,
  attachments: [],
  created_at: new Date().toISOString(),
  updated_at: new Date().toISOString(),
};

describe('PhotoSectionComponent', () => {
  let fixture: ComponentFixture<PhotoSectionComponent>;
  let component: PhotoSectionComponent;
  let httpMock: HttpTestingController;

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [PhotoSectionComponent, NoopAnimationsModule],
      providers: [provideHttpClient(), provideHttpClientTesting()],
    }).compileComponents();

    fixture = TestBed.createComponent(PhotoSectionComponent);
    component = fixture.componentInstance;
    httpMock = TestBed.inject(HttpTestingController);
    fixture.detectChanges();

    // Initialer GET /profile/photo-Aufruf aus ngOnInit abfangen (404 = noch kein Foto).
    // `responseType: 'blob'` verlangt einen Blob-Body auch für den Error-Flush -
    // TestRequest.flush konvertiert Objekte nicht automatisch in einen Blob.
    httpMock
      .expectOne((r) => r.url.endsWith('/profile/photo') && r.method === 'GET')
      .flush(new Blob(), { status: 404, statusText: 'Not Found' });
    fixture.detectChanges();
  });

  afterEach(() => {
    httpMock.verify();
  });

  it('should create', () => {
    expect(component).toBeTruthy();
  });

  it('shows the empty state when no photo has been uploaded yet (GET 404)', () => {
    const compiled = fixture.nativeElement as HTMLElement;

    expect(component['photoUrl']()).toBeNull();
    expect(compiled.querySelector('img')).toBeFalsy();
    expect(compiled.textContent).toContain('Noch kein Foto hochgeladen.');
  });

  it('uploads a selected image and displays the preview', () => {
    const file = new File([new Blob(['fake-image-bytes'])], 'photo.png', { type: 'image/png' });
    const input = { files: [file] } as unknown as HTMLInputElement;

    component.onFileSelected({ target: input } as unknown as Event);

    const uploadReq = httpMock.expectOne((r) => r.url.endsWith('/profile/photo') && r.method === 'POST');
    expect(uploadReq.request.body instanceof FormData).toBeTrue();
    uploadReq.flush(baseProfileResponse);

    const getReq = httpMock.expectOne((r) => r.url.endsWith('/profile/photo') && r.method === 'GET');
    getReq.flush(new Blob(['fake-image-bytes'], { type: 'image/png' }));
    fixture.detectChanges();

    expect(component['photoUrl']()).toMatch(/^blob:/);
    const img = (fixture.nativeElement as HTMLElement).querySelector('img');
    expect(img?.getAttribute('src')).toMatch(/^blob:/);
  });

  it('uploads a dropped image via the dropzone drop handler', () => {
    const file = new File([new Blob(['fake-image-bytes'])], 'photo.png', { type: 'image/png' });
    const dropEvent = {
      preventDefault: () => {},
      dataTransfer: { files: [file] },
    } as unknown as DragEvent;

    component.onDrop(dropEvent);

    const uploadReq = httpMock.expectOne((r) => r.url.endsWith('/profile/photo') && r.method === 'POST');
    uploadReq.flush(baseProfileResponse);

    const getReq = httpMock.expectOne((r) => r.url.endsWith('/profile/photo') && r.method === 'GET');
    getReq.flush(new Blob(['fake-image-bytes'], { type: 'image/png' }));

    expect(component['photoUrl']()).toMatch(/^blob:/);
    expect(component['isDragOver']()).toBeFalse();
  });

  it('rejects a non-image file client-side without an HTTP call', () => {
    const file = new File(['x'], 'notes.txt', { type: 'text/plain' });
    const input = { files: [file] } as unknown as HTMLInputElement;

    component.onFileSelected({ target: input } as unknown as Event);
    fixture.detectChanges();

    httpMock.expectNone((r) => r.url.endsWith('/profile/photo') && r.method === 'POST');
    expect(component['errorMessage']()).toBe('Bitte eine Bilddatei auswählen.');
    expect(component['photoUrl']()).toBeNull();
  });

  it('removes the photo and clears the preview', () => {
    const existingUrl = URL.createObjectURL(new Blob(['existing']));
    component['photoUrl'].set(existingUrl);
    fixture.detectChanges();

    component.remove();

    const req = httpMock.expectOne((r) => r.url.endsWith('/profile/photo') && r.method === 'DELETE');
    req.flush({ ...baseProfileResponse, photo_filename: null });
    fixture.detectChanges();

    expect(component['photoUrl']()).toBeNull();
    expect((fixture.nativeElement as HTMLElement).querySelector('img')).toBeFalsy();
  });
});
