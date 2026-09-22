import { ComponentFixture } from '@angular/core/testing';

/**
 * Shared test helpers for interacting with `<app-compact-card>`'s `⋮` menu, which
 * Angular Material portals to `document.body` via the CDK overlay rather than
 * rendering it under the component's own DOM subtree.
 */

/** Opens the (single, currently rendered) card's `⋮` menu and waits for the CDK
 * overlay to settle. For `fakeAsync` specs, click the trigger and call `tick()`
 * directly instead - awaiting a real Promise breaks the fake zone. */
export async function openCompactCardMenu(fixture: ComponentFixture<unknown>): Promise<void> {
  const trigger = fixture.nativeElement.querySelector('.compact-card__menu-trigger') as HTMLButtonElement;
  trigger.click();
  fixture.detectChanges();
  await fixture.whenStable();
  fixture.detectChanges();
}

/** Finds an open menu's item (button or anchor) whose text includes `text`. */
export function findCompactCardMenuItem(text: string): HTMLElement | null {
  const items = Array.from(document.querySelectorAll<HTMLElement>('.mat-mdc-menu-item'));
  return items.find((item) => item.textContent?.includes(text)) ?? null;
}

/** Removes any CDK overlay containers left in `document.body` - call from `afterEach`
 * so a leftover open menu from one test can't be picked up by the next one. */
export function cleanupCompactCardOverlays(): void {
  document.querySelectorAll('.cdk-overlay-container').forEach((el) => el.remove());
}
