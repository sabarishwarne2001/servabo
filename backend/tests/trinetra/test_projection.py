from app.services.trinetra.projection import receivable
import pytest

pytestmark = pytest.mark.no_db


def test_withholding_explains_balance_without_becoming_cash():
    value = receivable(118000000000, 116000000000, 2000000000)
    assert value["cash_received_micros"] == 116000000000
    assert value["unexplained_micros"] == 0 and value["status"] == "EXPLAINED"


def test_cash_plus_withholding_cannot_be_counted_twice():
    value = receivable(118000000000, 118000000000, 2000000000)
    assert value["status"] == "CONFLICT" and value["overexplained_micros"] == 2000000000


@pytest.mark.parametrize(
    "gross,bank,withholding", [(None, 100, 10), (100, None, 10), (100, 90, None)]
)
def test_missing_evidence_is_unknown(gross, bank, withholding):
    assert receivable(gross, bank, withholding)["unexplained_micros"] is None


def test_signed_adjustment_requires_review():
    with pytest.raises(ValueError):
        receivable(100, -90, 10)
