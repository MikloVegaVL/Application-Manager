import { ComponentFixture, TestBed } from '@angular/core/testing';
import { NoopAnimationsModule } from '@angular/platform-browser/animations';
import { MatDialogRef } from '@angular/material/dialog';

import { StartPortalFillDialogComponent } from './start-portal-fill-dialog.component';

describe('StartPortalFillDialogComponent', () => {
  let component: StartPortalFillDialogComponent;
  let fixture: ComponentFixture<StartPortalFillDialogComponent>;
  let dialogRef: { close: jasmine.Spy };

  beforeEach(() => {
    dialogRef = { close: jasmine.createSpy('close') };

    TestBed.configureTestingModule({
      imports: [StartPortalFillDialogComponent, NoopAnimationsModule],
      providers: [{ provide: MatDialogRef, useValue: dialogRef }],
    });

    fixture = TestBed.createComponent(StartPortalFillDialogComponent);
    component = fixture.componentInstance;
    fixture.detectChanges();
  });

  it('closes with the URL and dry-run value when submitted', () => {
    component['form'].setValue({ url: 'https://acme.example/apply', dryRun: true });

    component['onConfirm']();

    expect(dialogRef.close).toHaveBeenCalledWith({
      url: 'https://acme.example/apply',
      dryRun: true,
    });
  });

  it('closes with an empty URL when submitted blank, matching today\'s inline form (no added validation)', () => {
    component['form'].setValue({ url: '', dryRun: false });

    component['onConfirm']();

    expect(dialogRef.close).toHaveBeenCalledWith({ url: '', dryRun: false });
  });

  it('closes without data when canceled', () => {
    component['form'].setValue({ url: 'https://acme.example/apply', dryRun: true });

    component['onCancel']();

    expect(dialogRef.close).toHaveBeenCalledWith();
  });
});
