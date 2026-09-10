import { ComponentFixture, TestBed } from '@angular/core/testing';
import { FormArray, FormGroup } from '@angular/forms';
import { NoopAnimationsModule } from '@angular/platform-browser/animations';

import { ExperienceSectionComponent } from './experience-section.component';

describe('ExperienceSectionComponent', () => {
  let fixture: ComponentFixture<ExperienceSectionComponent>;
  let component: ExperienceSectionComponent;
  let formArray: FormArray<FormGroup>;

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [ExperienceSectionComponent, NoopAnimationsModule],
    }).compileComponents();

    fixture = TestBed.createComponent(ExperienceSectionComponent);
    component = fixture.componentInstance;
    formArray = new FormArray<FormGroup>([]);
    fixture.componentRef.setInput('formArray', formArray);
    fixture.detectChanges();
  });

  it('should create', () => {
    expect(component).toBeTruthy();
  });

  it('starts with an empty form array', () => {
    expect(formArray.length).toBe(0);
  });

  it('adds an experience entry to the form array', () => {
    component.add();

    expect(formArray.length).toBe(1);
    expect(formArray.at(0).get('company')).toBeTruthy();
    expect(formArray.at(0).get('role')).toBeTruthy();
  });

  it('removes an experience entry from the form array', () => {
    component.add();
    component.add();

    component.remove(0);

    expect(formArray.length).toBe(1);
  });

  it('populates a created group from an existing entry', () => {
    const group = component.createGroup({
      company: 'Acme',
      role: 'Engineer',
      start_date: '2020',
      end_date: null,
      description: 'Built things.',
    });

    expect(group.getRawValue()).toEqual({
      company: 'Acme',
      role: 'Engineer',
      start_date: '2020',
      end_date: '',
      description: 'Built things.',
    });
  });
});
