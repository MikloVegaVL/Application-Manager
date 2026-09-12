import { ComponentFixture, TestBed } from '@angular/core/testing';
import { FormArray, FormGroup } from '@angular/forms';
import { NoopAnimationsModule } from '@angular/platform-browser/animations';

import { ProjectsSectionComponent } from './projects-section.component';

describe('ProjectsSectionComponent', () => {
  let fixture: ComponentFixture<ProjectsSectionComponent>;
  let component: ProjectsSectionComponent;
  let formArray: FormArray<FormGroup>;

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [ProjectsSectionComponent, NoopAnimationsModule],
    }).compileComponents();

    fixture = TestBed.createComponent(ProjectsSectionComponent);
    component = fixture.componentInstance;
    formArray = new FormArray<FormGroup>([]);
    fixture.componentRef.setInput('formArray', formArray);
    fixture.detectChanges();
  });

  it('should create', () => {
    expect(component).toBeTruthy();
  });

  it('adds a project entry to the form array', () => {
    component.add();

    expect(formArray.length).toBe(1);
  });

  it('removes a project entry from the form array', () => {
    component.add();
    component.add();

    component.remove(0);

    expect(formArray.length).toBe(1);
  });

  it('requires title and description', () => {
    component.add();
    const group = formArray.at(0);

    expect(group.valid).toBeFalse();
    expect(group.get('title')?.hasError('required')).toBeTrue();
    expect(group.get('description')?.hasError('required')).toBeTrue();
  });

  it('is valid once title and description are filled, leaving start_date/end_date/link empty', () => {
    component.add();
    const group = formArray.at(0);

    group.patchValue({ title: 'Portfolio', description: 'Persönliche Website.' });

    expect(group.valid).toBeTrue();
    expect(group.get('start_date')?.value).toBe('');
    expect(group.get('end_date')?.value).toBe('');
    expect(group.get('link')?.value).toBe('');
  });
});
