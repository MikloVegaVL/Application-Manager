import { provideHttpClient } from '@angular/common/http';
import { provideHttpClientTesting, HttpTestingController } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';

import { ContentTranslationService, CvTranslatableContent } from './content-translation.service';

/** Beispielinhalt inkl. Eigennamen, die NIE übersetzt werden dürfen (R8). */
const content: CvTranslatableContent = {
  summary: 'Zusammenfassung',
  berufsbezeichnung: 'Entwickler',
  experiences: [
    {
      company: 'Beispiel GmbH',
      role: 'Entwickler',
      start_date: null,
      end_date: null,
      description: 'Beschreibung',
    },
  ],
  education: [
    {
      institution: 'TU Musterstadt',
      degree: 'Bachelor',
      field_of_study: 'Informatik',
      start_date: null,
      end_date: null,
    },
  ],
  projects: [
    { title: 'Projekt', description: 'Projektbeschreibung', start_date: null, end_date: null, link: null },
  ],
  languages: [{ name: 'Deutsch', level: 'C1' }],
};

describe('ContentTranslationService', () => {
  let service: ContentTranslationService;
  let httpMock: HttpTestingController;

  beforeEach(() => {
    TestBed.configureTestingModule({
      providers: [provideHttpClient(), provideHttpClientTesting()],
    });
    service = TestBed.inject(ContentTranslationService);
    httpMock = TestBed.inject(HttpTestingController);
  });

  afterEach(() => httpMock.verify());

  it('flattens only the translatable prose fields under stable paths (R8)', () => {
    const fields = service.flatten(content);

    expect(Object.keys(fields).sort()).toEqual([
      'berufsbezeichnung',
      'education.0.degree',
      'education.0.field_of_study',
      'experience.0.description',
      'experience.0.role',
      'language.0.name',
      'project.0.description',
      'project.0.title',
      'summary',
    ]);

    // Eigennamen/Fremdinhalte bleiben außen vor (R8).
    expect(fields['experience.0.company']).toBeUndefined();
    expect(fields['education.0.institution']).toBeUndefined();
    expect(fields['language.0.level']).toBeUndefined();
  });

  it('applies translations without touching proper nouns (R8)', () => {
    const updated = service.apply(content, {
      'experience.0.role': 'Developer',
      'education.0.degree': 'BSc',
      'language.0.name': 'German',
    });

    expect(updated.experiences[0].role).toBe('Developer');
    expect(updated.experiences[0].company).toBe('Beispiel GmbH');
    expect(updated.education[0].degree).toBe('BSc');
    expect(updated.education[0].institution).toBe('TU Musterstadt');
    expect(updated.languages[0].name).toBe('German');
    expect(updated.languages[0].level).toBe('C1');
  });

  it('posts the flattened fields to /cv-builder/translate (R6)', () => {
    service.translate('de', 'en', content).subscribe();

    const req = httpMock.expectOne((r) => r.url.endsWith('/cv-builder/translate') && r.method === 'POST');
    expect(req.request.body.source_language).toBe('de');
    expect(req.request.body.target_language).toBe('en');
    expect(req.request.body.fields.summary).toBe('Zusammenfassung');
    req.flush({ translations: { summary: 'Summary' }, errors: {} });
  });
});
