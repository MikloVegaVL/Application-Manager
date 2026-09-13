import { TRANSLATIONS } from './translations';

describe('TRANSLATIONS', () => {
  it('defines every cvBuilder.* key in both languages (R3/R4)', () => {
    const deKeys = Object.keys(TRANSLATIONS.de).filter((key) => key.startsWith('cvBuilder.'));
    const enKeys = Object.keys(TRANSLATIONS.en).filter((key) => key.startsWith('cvBuilder.'));

    expect(deKeys.length).toBeGreaterThan(0);
    expect(new Set(enKeys)).toEqual(new Set(deKeys));

    for (const key of deKeys) {
      expect(TRANSLATIONS.de[key].length).toBeGreaterThan(0);
      expect(TRANSLATIONS.en[key].length).toBeGreaterThan(0);
    }
  });
});
