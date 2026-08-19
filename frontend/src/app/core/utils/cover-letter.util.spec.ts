import { parseBetreff } from './cover-letter.util';

describe('parseBetreff', () => {
  it('extracts the subject and message when the text starts with a Betreff line followed by a blank separator', () => {
    const text = 'Betreff: Bewerbung als X\n\nSehr geehrte...';

    const result = parseBetreff(text);

    expect(result.subject).toBe('Bewerbung als X');
    expect(result.message).toBe('Sehr geehrte...');
  });

  it('matches the Betreff label case-insensitively', () => {
    const result = parseBetreff('betreff: x');

    expect(result.subject).toBe('x');
    expect(result.message).toBe('');
  });

  it('returns a null subject and the trimmed input as message when there is no Betreff line at all', () => {
    const text = '  Sehr geehrte Damen und Herren,\n\nMit freundlichen Grüßen  ';

    const result = parseBetreff(text);

    expect(result.subject).toBeNull();
    expect(result.message).toBe('Sehr geehrte Damen und Herren,\n\nMit freundlichen Grüßen');
  });

  it('still matches the Betreff line when preceded by one or more leading blank lines', () => {
    const text = '\n\n  \nBetreff: Bewerbung als Y\n\nSehr geehrte...';

    const result = parseBetreff(text);

    expect(result.subject).toBe('Bewerbung als Y');
    expect(result.message).toBe('Sehr geehrte...');
  });

  it('parses \\r\\n line endings the same as \\n', () => {
    const text = 'Betreff: Bewerbung als Z\r\n\r\nSehr geehrte...\r\nMit freundlichen Grüßen';

    const result = parseBetreff(text);

    expect(result.subject).toBe('Bewerbung als Z');
    expect(result.message).toBe('Sehr geehrte...\nMit freundlichen Grüßen');
  });

  it('strips only the Betreff line itself when there is no blank separator line before the next content', () => {
    const text = 'Betreff: Bewerbung als X\nSehr geehrte Damen und Herren,';

    const result = parseBetreff(text);

    expect(result.subject).toBe('Bewerbung als X');
    expect(result.message).toBe('Sehr geehrte Damen und Herren,');
  });

  it('returns a null subject and empty message for null, undefined, and empty-string input', () => {
    expect(parseBetreff(null)).toEqual({ subject: null, message: '' });
    expect(parseBetreff(undefined)).toEqual({ subject: null, message: '' });
    expect(parseBetreff('')).toEqual({ subject: null, message: '' });
  });

  it('returns an empty message when nothing remains after stripping the Betreff line', () => {
    const result = parseBetreff('Betreff: Bewerbung als X');

    expect(result.subject).toBe('Bewerbung als X');
    expect(result.message).toBe('');
  });

  it('returns an empty message when only blank lines remain after stripping the Betreff line and its separator', () => {
    const result = parseBetreff('Betreff: Bewerbung als X\n\n   \n');

    expect(result.subject).toBe('Bewerbung als X');
    expect(result.message).toBe('');
  });
});
