import { ComponentFixture, TestBed } from '@angular/core/testing';
import { FormArray, FormGroup } from '@angular/forms';
import { NoopAnimationsModule } from '@angular/platform-browser/animations';

import { EducationSectionComponent } from './education-section.component';

describe('EducationSectionComponent', () => {
  let fixture: ComponentFixture<EducationSectionComponent>;
  let component: EducationSectionComponent;
  let formArray: FormArray<FormGroup>;

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [EducationSectionComponent, NoopAnimationsModule],
    }).compileComponents();

    fixture = TestBed.createComponent(EducationSectionComponent);
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

  it('adds an education entry to the form array', () => {
    component.add();

    expect(formArray.length).toBe(1);
    expect(formArray.at(0).get('institution')).toBeTruthy();
    expect(formArray.at(0).get('degree')).toBeTruthy();
  });

  it('removes an education entry from the form array', () => {
    component.add();
    component.add();

    component.remove(0);

    expect(formArray.length).toBe(1);
  });

  it('populates a created group from an existing entry', () => {
    const group = component.createGroup({
      institution: 'TU Berlin',
      degree: 'MSc',
      field_of_study: 'Informatik',
      start_date: '2017',
      end_date: '2021',
    });

    expect(group.getRawValue()).toEqual({
      institution: 'TU Berlin',
      degree: 'MSc',
      field_of_study: 'Informatik',
      start_date: '2017',
      end_date: '2021',
    });
  });
});
