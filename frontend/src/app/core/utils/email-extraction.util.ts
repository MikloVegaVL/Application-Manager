/**
 * Extracts the first contact email address found in a job posting's text.
 *
 * Looks for a `mailto:` link first (an explicit "send your application to"
 * signal), falling back to the first bare email address anywhere in the
 * text. Returns `null` when neither is found, so callers can fall back to
 * an empty/manually-entered value.
 */
const MAILTO_PATTERN = /mailto:([^\s"'<>?),\]]+)/i;
const BARE_EMAIL_PATTERN = /[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}/i;

export function extractEmail(text: string | null | undefined): string | null {
  if (!text) {
    return null;
  }

  const mailtoMatch = text.match(MAILTO_PATTERN);
  if (mailtoMatch) {
    return mailtoMatch[1];
  }

  const bareMatch = text.match(BARE_EMAIL_PATTERN);
  return bareMatch ? bareMatch[0] : null;
}
