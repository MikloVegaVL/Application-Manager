/**
 * Spiegelt exakt das Backend-Schema `JobOfferCreate` (siehe
 * `backend/app/schemas/job_offer.py`) wider. Die Feldnamen bleiben bewusst
 * im Snake-Case-Format der API, damit Requests/Responses ohne
 * Umbenennungsschicht 1:1 durchgereicht werden können.
 */
export interface JobOffer {
  title: string;
  company: string;
  location: string | null;
  source_url: string;
  description_text: string | null;
  source_platform: string;
}

/** Entspricht `JobOfferRead`: ein bereits in der DB persistiertes Stellenangebot. */
export interface JobOfferRead extends JobOffer {
  id: number;
  created_at: string;
  is_processed: boolean;
}
