import { extractEmail } from './email-extraction.util';

describe('extractEmail', () => {
  it('returns null for null/undefined/empty input', () => {
    expect(extractEmail(null)).toBeNull();
    expect(extractEmail(undefined)).toBeNull();
    expect(extractEmail('')).toBeNull();
  });

  it('returns null when the text has no email address', () => {
    const text = 'Wir suchen eine Softwareentwicklerin (m/w/d) in Vollzeit.';

    expect(extractEmail(text)).toBeNull();
  });

  it('extracts a bare email address found anywhere in the text', () => {
    const text = 'Bitte sende deine Bewerbung an bewerbung@example.de - wir freuen uns!';

    expect(extractEmail(text)).toBe('bewerbung@example.de');
  });

  it('prefers a mailto: link over a bare address elsewhere in the text', () => {
    const text =
      'Kontakt: info@example.de\n<a href="mailto:bewerbung@example.de">Jetzt bewerben</a>';

    expect(extractEmail(text)).toBe('bewerbung@example.de');
  });

  it('strips trailing punctuation/query params from a mailto: link', () => {
    const text = '<a href="mailto:bewerbung@example.de?subject=Bewerbung">Bewerben</a>';

    expect(extractEmail(text)).toBe('bewerbung@example.de');
  });

  it('strips a trailing closing paren from a mailto: link written as plain text', () => {
    const text = 'Bewerbungen bitte per Mail (mailto:bewerbung@example.de) einreichen.';

    expect(extractEmail(text)).toBe('bewerbung@example.de');
  });

  it('returns the first bare address when multiple are present', () => {
    const text = 'Fachliche Fragen: hr@example.de. Allgemein: info@example.de.';

    expect(extractEmail(text)).toBe('hr@example.de');
  });
});
