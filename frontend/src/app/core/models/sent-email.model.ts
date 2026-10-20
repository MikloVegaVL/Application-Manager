/** Entspricht `SentEmailRead` (siehe `backend/app/schemas/sent_email.py`). */
export type SentEmailChannel = 'email' | 'webform';

export interface SentEmail {
  id: number;
  application_id: number | null;
  /** Live (kein Snapshot) - `null`, sobald die Application gelöscht ist; steuert den Link-through (R5). */
  job_offer_id: number | null;
  /** Live (kein Snapshot) - URL der ursprünglichen Stellenanzeige, `null` sobald die Application gelöscht ist. */
  ad_url: string | null;
  /** Live (kein Snapshot) - abgeleitet aus dem Status der verknüpften Application; "pending" ohne Entscheidung
   * oder nach Löschung der Application. */
  outcome: 'offer' | 'rejection' | 'pending';
  company: string | null;
  job_title: string | null;
  source_platform: string | null;
  /** "email" für echte Mailversände, "webform" für Direkt-Versände über das Firmenwebsite-Formular. */
  channel: SentEmailChannel;
  /** `null` bei "webform"-Einträgen - ein Website-Formular hat keinen E-Mail-Empfänger. */
  recipient_email: string | null;
  sent_at: string;
  sender_email: string | null;
  subject: string | null;
  /** Alle tatsächlich mitgeschickten Anhänge in Versandreihenfolge (Lebenslauf zuerst); leer für Altbestand und "webform". */
  attachment_filenames: string[];
}

/** Entspricht `SentEmailFilter` - gemeinsamer Filter-Vertrag von Liste und Export (KTD4). */
export interface SentEmailFilterParams {
  company?: string | null;
  sender_email?: string | null;
  date_from?: string | null;
  date_to?: string | null;
  outcome?: SentEmail['outcome'] | null;
  /** Versandart: "email" (Mailversand) oder "webform" (Website-Formular). */
  channel?: SentEmailChannel | null;
}
