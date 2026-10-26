"""A later, reviewed source increase is an outcome; reallocating old evidence is not."""

from tests.trinetra.test_api import world  # noqa: F401
from tests.trinetra.test_workflows import setup_case


def run_comparison(client, tenant, world, *, before, after):
    url, body, case = setup_case(client, tenant, world)
    headers = tenant.owner.headers
    statement = {
        "profile_id": body["profile_id"],
        "source_work_item_id": str(world[2].id),
        "year": 2025,
        "pan": "ABCDE1234F",
        "confirmed": True,
        "rows": [{"tan": "ABCD12345E", "amount": before, "reference": "Previous Q4"}],
    }
    old = client.post(url + "/reviewed-statements", headers=headers, json=statement)
    assert old.status_code == 200, old.text
    path = url + "/credits/" + case["id"]

    def decide(revision, action, allocations=()):
        result = client.post(
            path + "/decisions",
            headers=headers,
            json={
                "revision": revision,
                "action": action,
                "reason": "Reviewed source comparison and documented evidence.",
                "allocations": list(allocations),
                "review_minutes": 3,
            },
        )
        assert result.status_code == 200, result.text
        return result.json()

    allocated = decide(
        case["revision"],
        "ALLOCATE",
        [{"snapshot_id": old.json()["id"], "line_id": "0", "amount": before}],
    )
    statement["rows"][0].update(amount=after, reference="Later Q4")
    latest = client.post(url + "/reviewed-statements", headers=headers, json=statement)
    assert latest.status_code == 200, latest.text
    current = client.get(path, headers=headers).json()
    allocated = decide(
        current["revision"],
        "ALLOCATE",
        [{"snapshot_id": latest.json()["id"], "line_id": "0", "amount": after}],
    )
    assert (
        client.get(url + "/summary", headers=headers).json()["outcomes"][
            "confirmed_gap_closure_micros"
        ]
        == "0"
    )
    reviewed = decide(allocated["revision"], "CA_REVIEWED")
    return url, path, reviewed


def test_only_later_source_increase_and_accountant_review_count(client, tenant, world):
    url, path, case = run_comparison(client, tenant, world, before="1000", after="2000")
    summary = client.get(url + "/summary", headers=tenant.owner.headers).json()
    assert summary["outcomes"]["confirmed_gap_closure_micros"] == "1000000000"
    assert summary["outcomes"]["review_minutes"] == 9
    assert summary["outcomes"]["confirmed_cases"] == 1
    # A changed expectation invalidates the comparison, not a new saving.
    corrected = client.post(
        path + "/reconfirm",
        headers=tenant.owner.headers,
        json={
            "revision": case["revision"],
            "amount": "1500",
            "reason": "Corrected the original expectation with new evidence.",
        },
    )
    assert corrected.status_code == 200
    assert (
        client.get(url + "/summary", headers=tenant.owner.headers).json()["outcomes"][
            "confirmed_gap_closure_micros"
        ]
        == "0"
    )


def test_reimport_or_reallocation_of_same_source_amount_is_not_closure(
    client, tenant, world
):
    url, _, _ = run_comparison(client, tenant, world, before="2000", after="2000")
    outcomes = client.get(url + "/summary", headers=tenant.owner.headers).json()[
        "outcomes"
    ]
    assert (
        outcomes["confirmed_gap_closure_micros"] == "0"
        and outcomes["confirmed_cases"] == 0
    )


def test_review_minutes_must_be_bounded_whole_minutes(client, tenant, world):
    url, _, case = setup_case(client, tenant, world)
    for minutes in (-1, 481, 1.5):
        response = client.post(
            url + "/credits/" + case["id"] + "/decisions",
            headers=tenant.owner.headers,
            json={
                "revision": case["revision"],
                "action": "DISPUTED",
                "reason": "This review time is invalid.",
                "review_minutes": minutes,
            },
        )
        assert response.status_code == 422
