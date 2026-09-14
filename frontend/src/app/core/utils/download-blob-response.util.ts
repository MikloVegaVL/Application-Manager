import { HttpResponse } from '@angular/common/http';

/**
 * Triggers a browser download for a blob HTTP response, naming the file
 * from its `Content-Disposition` header when present (falling back to
 * `fallbackFilename` otherwise). Shared by every PDF-export button
 * (`cv-preview-export.component.ts`, `sent-emails.component.ts`) so the
 * blob-URL create/click/revoke sequence and filename parsing exist once.
 */
export function downloadBlobResponse(response: HttpResponse<Blob>, fallbackFilename: string): boolean {
  const blob = response.body;
  if (!blob) {
    return false;
  }

  const objectUrl = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = objectUrl;
  link.download = resolveFilename(response.headers.get('Content-Disposition')) ?? fallbackFilename;
  link.click();
  URL.revokeObjectURL(objectUrl);
  return true;
}

function resolveFilename(contentDisposition: string | null): string | null {
  if (!contentDisposition) {
    return null;
  }
  const match = /filename="?([^";]+)"?/.exec(contentDisposition);
  return match?.[1] ?? null;
}
