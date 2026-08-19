/**
 * Splits an Anschreiben (cover letter) text into its Betreff-derived subject
 * and the remaining message body.
 *
 * Only the first non-empty line of the text is checked for a `Betreff:` label
 * (case-insensitive). When found, the remainder of that line becomes the
 * subject, and the Betreff line — plus one immediately-following blank
 * separator line, if present — is removed from the message. When no Betreff
 * line is found, the subject is `null` and the message is the trimmed input,
 * unchanged.
 */
export function parseBetreff(
  coverLetterText: string | null | undefined
): { subject: string | null; message: string } {
  if (!coverLetterText) {
    return { subject: null, message: '' };
  }

  const normalized = coverLetterText.replace(/\r\n/g, '\n');
  const lines = normalized.split('\n');

  const firstNonEmptyIndex = lines.findIndex((line) => line.trim().length > 0);
  if (firstNonEmptyIndex === -1) {
    return { subject: null, message: '' };
  }

  const betreffMatch = lines[firstNonEmptyIndex].match(/^\s*Betreff\s*:\s*(.+)$/i);
  if (!betreffMatch) {
    return { subject: null, message: normalized.trim() };
  }

  const subject = betreffMatch[1].trim();

  // Drop the Betreff line itself, plus one immediately-following blank
  // separator line, if present.
  let removeEnd = firstNonEmptyIndex + 1;
  if (removeEnd < lines.length && lines[removeEnd].trim().length === 0) {
    removeEnd += 1;
  }

  const remainingLines = [...lines.slice(0, firstNonEmptyIndex), ...lines.slice(removeEnd)];
  const message = remainingLines.join('\n').trim();

  return { subject, message };
}
