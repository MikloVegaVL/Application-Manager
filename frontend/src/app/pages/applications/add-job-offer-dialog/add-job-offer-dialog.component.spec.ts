import { ComponentFixture, TestBed } from '@angular/core/testing';
import { NoopAnimationsModule } from '@angular/platform-browser/animations';
import { MatDialogRef } from '@angular/material/dialog';

import { AddJobOfferDialogComponent } from './add-job-offer-dialog.component';

describe('AddJobOfferDialogComponent', () => {
  let component: AddJobOfferDialogComponent;
  let fixture: ComponentFixture<AddJobOfferDialogComponent>;
  let dialogRef: { close: jasmine.Spy };

  beforeEach(() => {
    dialogRef = { close: jasmine.createSpy('close') };

    TestBed.configureTestingModule({
      imports: [AddJobOfferDialogComponent, NoopAnimationsModule],
      providers: [{ provide: MatDialogRef, useValue: dialogRef }],
    });

    fixture = TestBed.createComponent(AddJobOfferDialogComponent);
    component = fixture.componentInstance;
    fixture.detectChanges();
  });

  function fillRequiredFields(): void {
    component['form'].setValue({
      title: 'Backend Engineer',
      company: 'Acme GmbH',
      source_url: 'https://acme.example/careers/backend-engineer',
      description_text: '',
      application_email: '',
    });
  }

  it('Covers AE1: closes with all five field values when everything is filled in', () => {
    component['form'].setValue({
      title: 'Backend Engineer',
      company: 'Acme GmbH',
      source_url: 'https://acme.example/careers/backend-engineer',
      description_text: 'We are looking for a backend engineer ...',
      application_email: 'jobs@acme.example',
    });

    component['onConfirm']();

    expect(dialogRef.close).toHaveBeenCalledWith({
      title: 'Backend Engineer',
      company: 'Acme GmbH',
      source_url: 'https://acme.example/careers/backend-engineer',
      description_text: 'We are looking for a backend engineer ...',
      application_email: 'jobs@acme.example',
    });
  });

  it('Covers AE3: closes successfully when only the required fields are filled in', () => {
    fillRequiredFields();

    component['onConfirm']();

    expect(dialogRef.close).toHaveBeenCalledWith(
      jasmine.objectContaining({
        title: 'Backend Engineer',
        company: 'Acme GmbH',
        source_url: 'https://acme.example/careers/backend-engineer',
      }),
    );
  });

  it('does not close when title is empty', () => {
    fillRequiredFields();
    component['form'].controls.title.setValue('');

    component['onConfirm']();

    expect(dialogRef.close).not.toHaveBeenCalled();
    expect(component['form'].controls.title.touched).toBe(true);
  });

  it('does not close when company is empty', () => {
    fillRequiredFields();
    component['form'].controls.company.setValue('');

    component['onConfirm']();

    expect(dialogRef.close).not.toHaveBeenCalled();
    expect(component['form'].controls.company.touched).toBe(true);
  });

  it('Covers R2: blocks submission when source_url is empty', () => {
    fillRequiredFields();
    component['form'].controls.source_url.setValue('');

    component['onConfirm']();

    expect(dialogRef.close).not.toHaveBeenCalled();
    expect(component['form'].controls.source_url.touched).toBe(true);
  });

  it('blocks submission when title, company, or source_url is whitespace-only', () => {
    fillRequiredFields();
    component['form'].controls.title.setValue('   ');
    component['form'].controls.company.setValue('   ');
    component['form'].controls.source_url.setValue('   ');

    component['onConfirm']();

    expect(dialogRef.close).not.toHaveBeenCalled();
  });

  it('blocks submission when application_email is not a valid email', () => {
    fillRequiredFields();
    component['form'].controls.application_email.setValue('not-an-email');

    component['onConfirm']();

    expect(dialogRef.close).not.toHaveBeenCalled();
  });

  it('emits no result when the user cancels', () => {
    fillRequiredFields();

    component['onCancel']();

    expect(dialogRef.close).toHaveBeenCalledWith();
  });
});
