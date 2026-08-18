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
});
