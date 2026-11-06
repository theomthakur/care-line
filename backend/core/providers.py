import json
import re

from .common import (
    EASTERN,
    check_provider,
    event,
    get_call,
    get_member,
    invalidate,
    provider_view,
    require_coverage,
)
from .errors import DomainError

ZIP_ORDER = {
    "10019": ["10019", "10023", "10024"],
    "10023": ["10023", "10024", "10019"],
    "10024": ["10024", "10023", "10019"],
}


def preventive_evidence(conn, member):
    row = conn.execute(
        "SELECT id,title,text FROM plan_sections WHERE plan_id=? AND topic='preventive'",
        (member["plan_id"],),
    ).fetchone()
    if not row:
        raise DomainError("NO_SUPPORTED_ANSWER")
    return dict(row)


def search_providers(db, call_id, specialty, zip_code):
    with db.transaction() as conn:
        call = get_call(conn, call_id, verified=True, mutable=True)
        member = get_member(conn, call)
        now = db.now()
        require_coverage(member, now.astimezone(EASTERN).date())
        if not re.fullmatch(r"[0-9]{5}", zip_code):
            raise DomainError("INVALID_ZIP")
        if specialty != "primary care":
            raise DomainError("VISIT_TYPE_UNAVAILABLE")
        evidence = preventive_evidence(conn, member)
        eligible, excluded = [], []
        if zip_code in ZIP_ORDER:
            for provider in conn.execute(
                "SELECT * FROM providers WHERE specialty='primary care' ORDER BY id"
            ):
                in_network = conn.execute(
                    "SELECT 1 FROM provider_networks WHERE provider_id=? AND network=?",
                    (provider["id"], member["network"]),
                ).fetchone()
                if not in_network or not provider["accepting_new_patients"]:
                    excluded.append(
                        {
                            "id": provider["id"],
                            "name": provider["name"],
                            "reason_code": "NOT_BOOKABLE"
                            if not in_network
                            else "VISIT_TYPE_UNAVAILABLE",
                            "reason": "out of network"
                            if not in_network
                            else "not accepting new patients",
                        }
                    )
                elif provider["zip"] in ZIP_ORDER[zip_code]:
                    eligible.append(provider_view(provider))
            eligible.sort(key=lambda p: (ZIP_ORDER[zip_code].index(p["zip"]), p["id"]))
            eligible = eligible[:3]
        invalidate(conn, call, clear_offers=True)
        version = call["request_version"] + 1
        conn.execute(
            "UPDATE calls SET request_version=?,specialty=?,zip=?,selected_provider_id=NULL,providers_json=?,excluded_json=?,evidence_json=?,availability_query_json=NULL WHERE id=?",
            (
                version,
                specialty,
                zip_code,
                json.dumps(eligible),
                json.dumps(excluded),
                json.dumps([evidence]),
                call_id,
            ),
        )
        event(conn, call_id, "providers_searched", now)
        if not eligible:
            raise DomainError("NO_MATCH", persist=True)
        names = " and ".join(p["name"] for p in eligible)
        return {
            "providers": eligible,
            "excluded": excluded,
            "evidence": [evidence],
            "request_version": version,
            "speak": f"The nearest eligible providers in our list are {names}. Which would you prefer?",
        }


def select_provider(db, call_id, provider_id):
    with db.transaction() as conn:
        call = get_call(conn, call_id, verified=True, mutable=True)
        member = get_member(conn, call)
        now = db.now()
        require_coverage(member, now.astimezone(EASTERN).date())
        provider = check_provider(conn, call, member, provider_id)
        evidence = preventive_evidence(conn, member)
        invalidate(conn, call, clear_offers=True)
        version = call["request_version"] + 1
        conn.execute(
            "UPDATE calls SET selected_provider_id=?,request_version=?,availability_query_json=NULL,evidence_json=? WHERE id=?",
            (provider_id, version, json.dumps([evidence]), call_id),
        )
        event(conn, call_id, "provider_selected", now)
        return {
            "provider": provider_view(provider),
            "evidence": evidence,
            "evidence_id": evidence["id"],
            "request_version": version,
            "speak": f"You've selected {provider['name']}. {evidence['text']} What day works for you?",
        }
