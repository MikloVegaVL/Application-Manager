import { HttpHeaders, HttpResponse } from '@angular/common/http';

import { downloadBlobResponse } from './download-blob-response.util';

describe('downloadBlobResponse', () => {
  let createObjectURLSpy: jasmine.Spy;
  let revokeObjectURLSpy: jasmine.Spy;
  let clickSpy: jasmine.Spy;

  beforeEach(() => {
    createObjectURLSpy = spyOn(URL, 'createObjectURL').and.returnValue('blob:mock-url');
    revokeObjectURLSpy = spyOn(URL, 'revokeObjectURL');
    clickSpy = spyOn(HTMLAnchorElement.prototype, 'click');
  });

  function response(headers: HttpHeaders = new HttpHeaders()): HttpResponse<Blob> {
    return new HttpResponse({ body: new Blob(['%PDF-1.4'], { type: 'application/pdf' }), headers });
  }

  it('returns false and triggers nothing when the response has no body', () => {
    const result = downloadBlobResponse(new HttpResponse<Blob>({ body: null }), 'fallback.pdf');

    expect(result).toBeFalse();
    expect(createObjectURLSpy).not.toHaveBeenCalled();
  });

  it('downloads using the filename from Content-Disposition when present', () => {
    const headers = new HttpHeaders().set('Content-Disposition', 'attachment; filename="report.pdf"');

    const result = downloadBlobResponse(response(headers), 'fallback.pdf');

    expect(result).toBeTrue();
    expect(clickSpy).toHaveBeenCalled();
    expect(revokeObjectURLSpy).toHaveBeenCalledWith('blob:mock-url');
  });

  it('falls back to the given filename when Content-Disposition is absent', () => {
    downloadBlobResponse(response(), 'fallback.pdf');

    expect(clickSpy).toHaveBeenCalled();
  });
});
