// Submission detection and reporting shared by the U7/U8 adapters (KTD4, R11).
// Detection combines a URL transition, confirmation text, and disappearance of
// the submit control; when the signals disagree the caller asks the user to
// confirm rather than reporting a non-submission.

export function newReportId() {
  if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") {
    return crypto.randomUUID();
  }
  return `report-${Date.now()}-${Math.random().toString(36).slice(2)}`;
}

// KTD4: nur der Bestätigungs-TEXT darf einen Submit bestätigen. `urlChanged`
// + `submitGone` allein beschreibt jede Navigation (z. B. bloßes Verlassen
// der Seite) und würde sonst eine Nicht-Bewerbung verbuchen. Fehlt der
// Bestätigungstext, bleibt das Ergebnis `confident:false`; `finalizeSubmission`
// fragt dann den Nutzer (explizite Bestätigung). Kein stilles Melden bei
// Unsicherheit.
export function detectCompletion({ urlChanged = false, confirmationText = false, submitGone = false } = {}) {
  const signals = {
    urlChanged: Boolean(urlChanged),
    confirmationText: Boolean(confirmationText),
    submitGone: Boolean(submitGone),
  };
  const positives = Object.values(signals).filter(Boolean).length;
  if (positives === 0) return { status: "pending", confident: false, signals };
  if (signals.confirmationText && positives >= 2) {
    return { status: "complete", confident: true, signals };
  }
  return { status: "complete", confident: false, signals };
}

// Reports only on confident detection or explicit user confirmation, and only
// surfaces a failure (never fabricates a record) when the app is unreachable.
export async function finalizeSubmission({
  detection,
  context = {},
  report,
  confirm,
  makeReportId = newReportId,
} = {}) {
  if (!detection || detection.status === "pending") {
    return { status: "not_complete", detection };
  }

  let confirmed = detection.confident === true;
  if (!confirmed) {
    confirmed = typeof confirm === "function" ? Boolean(await confirm(detection)) : false;
  }
  if (!confirmed) return { status: "unconfirmed", detection };

  const payload = {
    report_id: makeReportId(),
    job_offer_id: context.jobOfferId,
    portal_url: context.portalUrl,
  };

  try {
    const submission = await report(payload);
    return { status: "reported", submission, payload, detection };
  } catch (error) {
    return { status: "report_failed", error: String((error && error.message) || error), detection };
  }
}
