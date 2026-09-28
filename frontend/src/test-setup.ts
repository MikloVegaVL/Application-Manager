import '@analogjs/vitest-angular/setup-zone';

import { afterEach, expect, vi } from 'vitest';
import { getTestBed } from '@angular/core/testing';
import {
  BrowserDynamicTestingModule,
  platformBrowserDynamicTesting,
} from '@angular/platform-browser-dynamic/testing';

getTestBed().initTestEnvironment(BrowserDynamicTestingModule, platformBrowserDynamicTesting(), {
  teardown: { destroyAfterEach: true },
});

// jsdom implements neither Blob URL helper, yet the download/preview flows rely on them.
if (typeof URL.createObjectURL !== 'function') {
  URL.createObjectURL = () => `blob:vitest/${Math.random().toString(36).slice(2)}`;
}
if (typeof URL.revokeObjectURL !== 'function') {
  URL.revokeObjectURL = () => undefined;
}

// --- Jasmine compatibility for the in-progress Karma -> Vitest migration ---
// The spec suite still uses Jasmine's `spyOn`/`jasmine.*` helpers and the
// `toBeTrue`/`toBeFalse` matchers. Vitest ships none of them. Each spy is
// backed by `vi.fn()` so Vitest's native mock matchers keep working too.
//
// Jasmine semantics: `spyOn(obj, 'method')` STUBS the method (no call-through
// to the original) unless `.and.callThrough()` is requested, and every spy is
// automatically restored after the spec. The previous shim installed the
// original as the default implementation and never restored, which silently
// changed behavior; both are fixed here.
const globalScope = globalThis as unknown as {
  spyOn?: (obj: Record<string, unknown>, method: string, accessType?: 'get') => unknown;
  jasmine?: Record<string, unknown>;
};

type SpyRestoration = {
  target: Record<string, unknown>;
  method: string;
  descriptor: PropertyDescriptor | undefined;
};

const spyRestorations: SpyRestoration[] = [];

function restoreSpies(): void {
  // Reverse order so nested/repeated spying restores to the state before the
  // outermost spy, matching Jasmine's restore-after-each-spec behavior.
  for (const record of spyRestorations.splice(0).reverse()) {
    if (record.descriptor) {
      Object.defineProperty(record.target, record.method, record.descriptor);
    } else {
      delete record.target[record.method];
    }
  }
}

afterEach(() => {
  restoreSpies();
});

function createSpy(name = 'spy', originalFn?: (...args: unknown[]) => unknown) {
  // Jasmine stubs by default: the mock has NO implementation unless
  // `.and.callThrough()` (or another `.and.*` method) is used.
  const mock = vi.fn();
  const spy = mock as unknown as {
    and: Record<string, unknown>;
    calls: Record<string, unknown>;
  };

  spy.and = {
    identity: name,
    returnValue: (value: unknown) => {
      mock.mockReturnValue(value);
      return spy;
    },
    returnValues: (...values: unknown[]) => {
      values.forEach((value) => mock.mockReturnValueOnce(value));
      return spy;
    },
    callThrough: () => {
      if (originalFn) {
        mock.mockImplementation(originalFn);
      }
      return spy;
    },
    callFake: (fn: (...args: unknown[]) => unknown) => {
      mock.mockImplementation(fn);
      return spy;
    },
    resolveTo: (value: unknown) => {
      mock.mockResolvedValue(value);
      return spy;
    },
    rejectWith: (value: unknown) => {
      mock.mockRejectedValue(value);
      return spy;
    },
    throwError: (error: unknown) => {
      mock.mockImplementation(() => {
        throw error;
      });
      return spy;
    },
    stub: () => {
      mock.mockImplementation(() => undefined);
      return spy;
    },
  };

  spy.calls = {
    count: () => mock.mock.calls.length,
    any: () => mock.mock.calls.length > 0,
    all: () =>
      mock.mock.calls.map((args, index) => ({ args, returnValue: mock.mock.results[index]?.value })),
    allArgs: () => mock.mock.calls,
    argsFor: (index: number) => mock.mock.calls[index] ?? [],
    mostRecent: () => ({
      args: mock.mock.calls[mock.mock.calls.length - 1] ?? [],
      returnValue: mock.mock.results[mock.mock.results.length - 1]?.value,
    }),
    first: () => ({
      args: mock.mock.calls[0] ?? [],
      returnValue: mock.mock.results[0]?.value,
    }),
    reset: () => mock.mockClear(),
  };

  return spy;
}

if (!globalScope.spyOn) {
  globalScope.spyOn = (obj, method, accessType) => {
    const original = obj[method];
    const descriptor = Object.getOwnPropertyDescriptor(obj, method);
    if (accessType === 'get') {
      const spy = createSpy(method);
      const mockFn = spy as unknown as () => unknown;
      // A getter whose value is the mock's result, so `.and.returnValue(x)`
      // (or a plain stub returning undefined) actually surfaces on property
      // access - unlike assigning the mock itself as the getter.
      Object.defineProperty(obj, method, {
        configurable: true,
        get: () => mockFn(),
      });
      spyRestorations.push({ target: obj, method, descriptor });
      return spy;
    }
    const spy = createSpy(method, original as (...args: unknown[]) => unknown);
    obj[method] = spy;
    spyRestorations.push({ target: obj, method, descriptor });
    return spy;
  };
}

if (!globalScope.jasmine) {
  globalScope.jasmine = {
    createSpy,
    objectContaining: (sample: unknown) => expect.objectContaining(sample as object),
    any: (type: unknown) => expect.any(type as new (...args: unknown[]) => unknown),
  };
}

expect.extend({
  toBeTrue(received: unknown) {
    return {
      pass: received === true,
      message: () => `expected ${String(received)} to be true`,
    };
  },
  toBeFalse(received: unknown) {
    return {
      pass: received === false,
      message: () => `expected ${String(received)} to be false`,
    };
  },
});
