import { sourceLabel } from './source-label.util';

describe('sourceLabel', () => {
  it('returns the readable label for a known platform', () => {
    // Arrange
    const platform = 'linkedin';
    // Act
    const result = sourceLabel(platform);
    // Assert
    expect(result).toBe('LinkedIn');
  });
});
