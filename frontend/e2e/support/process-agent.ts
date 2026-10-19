/**
 * Support for the exception-agent specs: an organization's REVIEWED HISTORY.
 *
 * Calibrated autonomy only lets the agent schedule an automatic resolution once the organization has a
 * fitted model, and a model needs reviewed outcomes (at least 50, hundreds for a useful one). In real life
 * they accumulate over months of people reviewing documents; a browser test cannot wait for that, and
 * driving 50 real reviews would take longer than the rest of the suite. So the history (the outcomes of
 * past reviews: the engine's score, and whether the engine was right) is added to ONE organization by the
 * stand-in tool. The model is then FITTED by the product (the error limit saved through the real
 * endpoint), and the agent plans through the real sweep. The need for a fitted model is the point of
 * calibrated autonomy, not a gap: no automatic resolution, and so no Undo, exists without one.
 */
import { standIn } from "./journey";

/**
 * Add `count` reviewed outcomes for the "verification.document" decision to one organization (by slug),
 * through the stand-in tool (backend/scripts/e2e_stand_in.py calibration-history), which a backend test
 * keeps honest: the history it writes lets the product fit a model.
 */
export function seedReviewedHistory(organizationSlug: string, count = 600): void {
  const out = standIn("calibration-history", organizationSlug, "--count", String(count));
  if (out.labels !== count) throw new Error(`reviewed history was not added: ${JSON.stringify(out).slice(0, 300)}`);
}
