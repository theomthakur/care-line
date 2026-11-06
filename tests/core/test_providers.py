import pytest

from backend.core.calls import create_call
from backend.core.errors import DomainError
from backend.core.providers import search_providers, select_provider
from backend.core.verification import verify_member


def test_first_checkpoint_maya_to_omar(db):
    call, status = create_call(db, "checkpoint")
    assert status == 201
    verified = verify_member(db, call["call_id"], "four four one seven", 4)
    assert verified["member"] == {
        "name": "Maya T.",
        "id_masked": "***4417",
        "plan": "Gold 2026",
        "network": "METRO",
        "active": True,
    }
    result = search_providers(db, call["call_id"], "primary care", "10023")
    assert [p["id"] for p in result["providers"]] == ["P2", "P4"]
    assert result["providers"][0]["name"] == "Dr. Omar Haddad"
    assert {p["id"]: p["reason_code"] for p in result["excluded"]} == {
        "P1": "VISIT_TYPE_UNAVAILABLE",
        "P3": "NOT_BOOKABLE",
    }
    assert result["evidence"][0]["id"] == "GOLD-PREV"


def test_provider_selection_enforces_eligibility(db):
    call_id = create_call(db, "selection")[0]["call_id"]
    verify_member(db, call_id, "4417", 4)
    search_providers(db, call_id, "primary care", "10023")
    for provider, code in [
        ("P1", "VISIT_TYPE_UNAVAILABLE"),
        ("P3", "NOT_BOOKABLE"),
        ("guessed", "UNKNOWN_PROVIDER"),
    ]:
        with pytest.raises(DomainError, match=code):
            select_provider(db, call_id, provider)
    assert select_provider(db, call_id, "P2")["evidence_id"] == "GOLD-PREV"


def test_network_and_scope_are_checked_in_code(db):
    call_id = create_call(db, "riley")[0]["call_id"]
    verify_member(db, call_id, "2261", 6)
    result = search_providers(db, call_id, "primary care", "10019")
    assert [p["id"] for p in result["providers"]] == ["P3", "P4"]
    assert result["evidence"][0]["id"] == "BASIC-PREV"
    with pytest.raises(DomainError, match="VISIT_TYPE_UNAVAILABLE"):
        search_providers(db, call_id, "cardiology", "10023")


def test_expired_coverage_cannot_search(db):
    call_id = create_call(db, "devon")[0]["call_id"]
    verify_member(db, call_id, "8832", 9)
    with pytest.raises(DomainError, match="COVERAGE_ENDED"):
        search_providers(db, call_id, "primary care", "10023")
