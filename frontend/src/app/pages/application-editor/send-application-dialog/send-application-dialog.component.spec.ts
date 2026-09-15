import { ComponentFixture, TestBed } from '@angular/core/testing';
import { HttpErrorResponse } from '@angular/common/http';
import { NoopAnimationsModule } from '@angular/platform-browser/animations';
import { MAT_DIALOG_DATA, MatDialogRef } from '@angular/material/dialog';
import { By } from '@angular/platform-browser';
import { Subject, of, throwError } from 'rxjs';

import {
  SendApplicationDialogComponent,
  SendApplicationDialogData,
} from './send-application-dialog.component';
import { ApplicationEmailLookupResult } from '../../../core/models/job-offer.model';

describe('SendApplicationDialogComponent', () => {
  let component: SendApplicationDialogComponent;
  let fixture: ComponentFixture<SendApplicationDialogComponent>;
  let dialogRef: { close: jasmine.Spy };

  function setup(data: Partial<SendApplicationDialogData> = {}): void {
    TestBed.configureTestingModule({
      imports: [SendApplicationDialogComponent, NoopAnimationsModule],
      providers: [
        {
          provide: MAT_DIALOG_DATA,
          useValue: {
            toEmail: '',
            subject: 'Application as Backend Engineer',
            message: 'Sehr geehrte Damen und Herren,',
            ...data,
          } satisfies SendApplicationDialogData,
        },
        { provide: MatDialogRef, useValue: dialogRef },
      ],
    });

    fixture = TestBed.createComponent(SendApplicationDialogComponent);
    component = fixture.componentInstance;
    fixture.detectChanges();
  }

  beforeEach(() => {
    dialogRef = { close: jasmine.createSpy('close') };
  });

  it('Covers R8: a found address is written into to_email and stays editable', () => {
    setup({
      findApplicationEmail: () =>
        of({
          status: 'found',
          email: 'bewerbung@acme.example',
          source_url: 'https://acme.example/karriere',
        } satisfies ApplicationEmailLookupResult),
    });

    component['onFindApplicationEmail']();
    fixture.detectChanges();

    expect(component['form'].controls.to_email.value).toBe('bewerbung@acme.example');

    component['form'].controls.to_email.setValue('manuell@acme.example');
    component['onConfirm']();

    expect(dialogRef.close).toHaveBeenCalledWith(
      jasmine.objectContaining({ to_email: 'manuell@acme.example' }),
    );
  });

  it('renders the source link for a found address', () => {
    setup({
      findApplicationEmail: () =>
        of({
          status: 'found',
          email: 'bewerbung@acme.example',
          source_url: 'https://acme.example/karriere',
        } satisfies ApplicationEmailLookupResult),
    });

    component['onFindApplicationEmail']();
    fixture.detectChanges();

    const link = fixture.debugElement.query(By.css('.dialog-form__lookup-source'));
    expect(link.nativeElement.getAttribute('href')).toBe('https://acme.example/karriere');
    expect(link.nativeElement.getAttribute('target')).toBe('_blank');
    expect(link.nativeElement.getAttribute('rel')).toBe('noopener noreferrer');
  });

  it('Covers R9: a not-found result leaves to_email empty and shows the not-found state', () => {
    setup({ findApplicationEmail: () => of({ status: 'not-found' } satisfies ApplicationEmailLookupResult) });

    component['onFindApplicationEmail']();
    fixture.detectChanges();

    expect(component['form'].controls.to_email.value).toBe('');
    const text = fixture.nativeElement.textContent as string;
    expect(text).toContain('No application email found');
    expect(text).not.toContain("Couldn't reach the employer's site");
  });

  it('Covers R9: a failed result shows the distinct failure copy', () => {
    setup({ findApplicationEmail: () => of({ status: 'failed' } satisfies ApplicationEmailLookupResult) });

    component['onFindApplicationEmail']();
    fixture.detectChanges();

    const text = fixture.nativeElement.textContent as string;
    expect(text).toContain("Couldn't reach the employer's site — try again");
    expect(text).not.toContain('No application email found');
  });

  it('Covers R11: a re-run can be triggered after an address is present and forces a fresh lookup', () => {
    const findSpy = jasmine
      .createSpy('findApplicationEmail')
      .and.returnValues(
        of({
          status: 'found',
          email: 'bewerbung@acme.example',
          source_url: 'https://acme.example/karriere',
        } satisfies ApplicationEmailLookupResult),
        of({
          status: 'found',
          email: 'jobs@acme.example',
          source_url: 'https://acme.example/jobs',
        } satisfies ApplicationEmailLookupResult),
      );
    setup({ findApplicationEmail: findSpy });

    component['onFindApplicationEmail']();
    fixture.detectChanges();
    expect(fixture.nativeElement.textContent).toContain('Find email again');

    component['onFindApplicationEmail']();
    fixture.detectChanges();

    expect(findSpy.calls.argsFor(0)).toEqual([false]);
    expect(findSpy.calls.argsFor(1)).toEqual([true]);
    expect(component['form'].controls.to_email.value).toBe('jobs@acme.example');
  });

  it('Covers A5: an HTTP error maps to the distinct failure copy and re-enables the action', () => {
    setup({
      findApplicationEmail: () =>
        throwError(
          () => new HttpErrorResponse({ status: 500, statusText: 'Internal Server Error' }),
        ),
    });

    component['onFindApplicationEmail']();
    fixture.detectChanges();

    const text = fixture.nativeElement.textContent as string;
    expect(text).toContain("Couldn't reach the employer's site — try again");
    expect(text).not.toContain('No application email found');

    const button = fixture.debugElement.query(By.css('.dialog-form__find-email-btn'))
      .nativeElement as HTMLButtonElement;
    expect(button.disabled).toBeFalse();
  });

  it('Loading: the action is disabled and an inline spinner shows while in flight', () => {
    const pending = new Subject<ApplicationEmailLookupResult>();
    setup({ findApplicationEmail: () => pending.asObservable() });

    component['onFindApplicationEmail']();
    fixture.detectChanges();

    const button = fixture.debugElement.query(By.css('.dialog-form__find-email-btn'))
      .nativeElement as HTMLButtonElement;
    expect(button.disabled).toBeTrue();
    expect(button.querySelector('mat-progress-spinner')).toBeTruthy();

    pending.next({ status: 'not-found' });
    pending.complete();
    fixture.detectChanges();

    expect(
      (fixture.debugElement.query(By.css('.dialog-form__find-email-btn'))
        .nativeElement as HTMLButtonElement).disabled,
    ).toBeFalse();
  });

  it('does not render the Find email action without an injected callback', () => {
    setup();

    expect(fixture.debugElement.query(By.css('.dialog-form__find-email-btn'))).toBeFalsy();
  });
});
