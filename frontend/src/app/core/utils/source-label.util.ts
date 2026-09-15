/**
 * Menschenlesbares Label für einen Quellen-Platform-Key (z. B. "linkedin" ->
 * "LinkedIn"). Gemeinsam genutzt von Jobsuche, Bewerbungsübersicht und
 * Sent-Emails-Log, damit dieselbe Quelle überall identisch beschriftet wird
 * statt an drei Stellen eigene Maps zu pflegen.
 */
const SOURCE_LABELS: Record<string, string> = {
  arbeitsagentur: 'Arbeitsagentur',
  arbeitnow: 'Arbeitnow',
  linkedin: 'LinkedIn',
  xing: 'Xing',
  adzuna: 'Adzuna',
  jooble: 'Jooble',
  devjobs: 'DEVjobs.de',
  kimeta: 'Kimeta',
  programmiererjobboerse: 'Programmiererjobboerse.de',
};

export function sourceLabel(platform: string): string {
  return SOURCE_LABELS[platform] ?? platform;
}
