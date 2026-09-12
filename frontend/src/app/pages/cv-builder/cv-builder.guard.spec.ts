import { ActivatedRouteSnapshot, RouterStateSnapshot } from '@angular/router';

import { CvBuilderComponent } from './cv-builder.component';
import { cvBuilderCanDeactivateGuard } from './cv-builder.guard';

describe('cvBuilderCanDeactivateGuard', () => {
  const dummyRoute = {} as ActivatedRouteSnapshot;
  const dummyState = {} as RouterStateSnapshot;

  const componentWith = (hasUnsavedChanges: boolean): CvBuilderComponent =>
    ({ hasUnsavedChanges: () => hasUnsavedChanges }) as unknown as CvBuilderComponent;

  it('allows navigation without prompting when there are no unsaved changes', () => {
    spyOn(window, 'confirm');

    const result = cvBuilderCanDeactivateGuard(componentWith(false), dummyRoute, dummyState, dummyState);

    expect(result).toBeTrue();
    expect(window.confirm).not.toHaveBeenCalled();
  });

  it('prompts and allows navigation when the user confirms discarding unsaved changes', () => {
    spyOn(window, 'confirm').and.returnValue(true);

    const result = cvBuilderCanDeactivateGuard(componentWith(true), dummyRoute, dummyState, dummyState);

    expect(result).toBeTrue();
    expect(window.confirm).toHaveBeenCalledTimes(1);
  });

  it('prompts and blocks navigation when the user cancels', () => {
    spyOn(window, 'confirm').and.returnValue(false);

    const result = cvBuilderCanDeactivateGuard(componentWith(true), dummyRoute, dummyState, dummyState);

    expect(result).toBeFalse();
  });
});
