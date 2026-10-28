"""One deliberate data-lifecycle rule for tax evidence (Final 2T, Phase 1.7; N-200)."""

from app.services.compliance.data_map import REGISTRY, Erasure, Kind, OrgPurge, Sweep


def test_trinetra_working_papers_are_erased_with_their_documents_and_say_why():
    for table in ("trinetra_statements", "trinetra_credits", "trinetra_decisions"):
        rule = REGISTRY[table]
        assert (rule.kind, rule.erasure, rule.sweep, rule.org_purge) == (
            Kind.CONTENT, Erasure.DELETE, Sweep.DELETE, OrgPurge.DELETE), table
        assert rule.export, f"{table} must be in the export so the dossier is handed over before erasure"
    assert "N-200" in REGISTRY["trinetra_credits"].note and "N-200" in REGISTRY["trinetra_statements"].note


def test_gst_stays_the_opposite_rule_so_the_two_are_not_confused():
    assert REGISTRY["gst_returns"].erasure == Erasure.KEEP
