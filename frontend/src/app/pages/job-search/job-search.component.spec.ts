import { ComponentFixture, TestBed } from '@angular/core/testing';
import { provideHttpClient } from '@angular/common/http';
import { provideHttpClientTesting } from '@angular/common/http/testing';
import { provideRouter } from '@angular/router';
import { NoopAnimationsModule } from '@angular/platform-browser/animations';

import { JobSearchComponent } from './job-search.component';

describe('JobSearchComponent', () => {
  let component: JobSearchComponent;
  let fixture: ComponentFixture<JobSearchComponent>;

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [JobSearchComponent, NoopAnimationsModule],
      providers: [provideHttpClient(), provideHttpClientTesting(), provideRouter([])],
    }).compileComponents();

    fixture = TestBed.createComponent(JobSearchComponent);
    component = fixture.componentInstance;
    fixture.detectChanges();
  });

  it('should create', () => {
    expect(component).toBeTruthy();
  });

  it('should mark the search form invalid without keywords', () => {
    expect(component['searchForm'].invalid).toBeTrue();
  });
});
