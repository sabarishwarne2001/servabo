/**
 * Support for the exception-agent specs: an organization's REVIEWED HISTORY.
 *
 * Calibrated autonomy only lets the agent schedule an automatic resolution once the organization has a
 * fitted model, and a model needs hundreds of reviewed outcomes. In real life they accumulate over months of
 * people reviewing documents; a browser test cannot wait for that. This adds that history (the outcomes of
 * past reviews: the engine's score, and whether the engine was right) to ONE organization, the same way
 * backend/tests/engines/test_autonomy_limit_changes_decisions_live.py does. The model is then FITTED by the
 * product (the error limit saved through the real endpoint), and the agent plans through the real sweep.
 */
import { execFileSync } from "node:child_process";
import fs from "node:fs";
import path from "node:path";

import { BACKEND_DIR } from "./env";

const SCRIPT = `
import sys, uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from sqlalchemy import text
from app.db.session import SessionLocal
from app.services.calibration import vocabulary as vocab

org, count = sys.argv[1], int(sys.argv[2])
now = datetime.now(timezone.utc)
rows = []
for index in range(count):
    score = Decimal(index) / Decimal(count)
    correct = (index * 7919) % 100 < int(score * 120) - 20
    rows.append({"id": str(uuid.uuid4()), "org": org, "decision": vocab.DECISION_VERIFICATION_DOCUMENT, "score": score,
                 "correct": correct, "source": vocab.SOURCE_DOCUMENT_VERIFICATIONS, "source_id": str(uuid.uuid4()),
                 "at": now - timedelta(hours=count - index)})
with SessionLocal() as db, db.begin():
    db.execute(text(
        "INSERT INTO calibration_labels (id, organization_id, decision_type, raw_score, correct, source_table, "
        "source_id, was_auto_approved, was_audit_sample, auto_eligible, sample_weight, observed_at) VALUES "
        "(:id, :org, :decision, :score, :correct, :source, :source_id, false, false, true, 1, :at)"), rows)
print("ok")
`;

function python(): string {
  if (process.env.E2E_PYTHON) return process.env.E2E_PYTHON;
  const candidate = path.join(BACKEND_DIR, ".venv", "bin", "python");
  return fs.existsSync(candidate) ? candidate : "python3";
}

/** Add `count` reviewed outcomes for the "verification.document" decision to one organization. */
export function seedReviewedHistory(organizationId: string, count = 600): void {
  const out = execFileSync(python(), ["-c", SCRIPT, organizationId, String(count)], {
    cwd: BACKEND_DIR, encoding: "utf8", timeout: 120_000,
  });
  if (!out.trim().endsWith("ok")) throw new Error(`reviewed history was not added: ${out.slice(-300)}`);
}
