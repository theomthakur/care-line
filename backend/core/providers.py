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
from .referrals import SPECIALTIES, referral_evidence, require_referral

SPECIALTY_ALIASES = {
    "primary care": "primary care",
    "primary care doctor": "primary care",
    "pcp": "primary care",
    "cardiology": "cardiology",
    "cardiologist": "cardiology",
    "heart doctor": "cardiology",
    "dermatology": "dermatology",
    "dermatologist": "dermatology",
    "skin doctor": "dermatology",
}

ZIP_ORDER = {
    "10019": ["10019", "10023", "10024"],
    "10023": ["10023", "10024", "10019"],
    "10024": ["10024", "10023", "10019"],
    # Added with the wider roster. The three above are unchanged.
    "10001": ["10001", "10011", "10019"],
    "10011": ["10011", "10001", "10019"],
    "10025": ["10025", "10023", "10024"],
    "10128": ["10128", "10023", "10025"],
}


def zip_order(conn, zip_code):
    """Provider ZIPs, nearest first. Listed ZIPs keep their fixed order. Other NYC-area
    ZIPs (100xx-119xx) fall back to the nearest ZIP in our list by number. Anything else
    has no match."""
    if zip_code in ZIP_ORDER:
        return ZIP_ORDER[zip_code]
    if not zip_code.startswith(("10", "11")):
        return None
    zips = {
        r["zip"]
        for r in conn.execute(
            "SELECT zip FROM providers WHERE specialty='primary care'"
        )
    }
    return sorted(zips, key=lambda z: (abs(int(z) - int(zip_code)), z))


def preventive_evidence(conn, member):
    row = conn.execute(
        "SELECT id,title,text FROM plan_sections WHERE plan_id=? AND topic='preventive'",
        (member["plan_id"],),
    ).fetchone()
    if not row:
        raise DomainError("NO_SUPPORTED_ANSWER")
    return dict(row)


def plan_evidence(conn, member, specialty):
    if specialty == "primary care":
        return preventive_evidence(conn, member)
    return referral_evidence(conn, member)


def provider_order(conn, zip_code, specialty):
    """Primary care stays strict to the nearby ZIP list. Specialists are scarcer, so
    every eligible one is offered, nearest ZIP first."""
    order = zip_order(conn, zip_code)
    if specialty == "primary care":
        return order, lambda p: p["zip"] in (order or [])
    if not zip_code.startswith(("10", "11")):
        return None, lambda p: False
    order = order or []
    return order, lambda p: True


def distance_key(order, zip_code):
    def key(p):
        if p["zip"] in order:
            return (0, order.index(p["zip"]), p["id"])
        return (1, abs(int(p["zip"]) - int(zip_code)), p["id"])

    return key


def search_providers(db, call_id, specialty, zip_code):
    with db.transaction() as conn:
        call = get_call(conn, call_id, verified=True, mutable=True)
        member = get_member(conn, call)
        now = db.now()
        today = now.astimezone(EASTERN).date()
        require_coverage(member, today)
        if not re.fullmatch(r"[0-9]{5}", zip_code):
            raise DomainError("INVALID_ZIP")
        specialty = SPECIALTY_ALIASES.get(specialty.strip().lower(), specialty)
        if specialty not in ("primary care", *SPECIALTIES):
            raise DomainError("VISIT_TYPE_UNAVAILABLE")
        evidence = plan_evidence(conn, member, specialty)
        referral = None
        invalidate(conn, call, clear_offers=True)
        version = call["request_version"] + 1
        conn.execute(
            "UPDATE calls SET request_version=?,specialty=?,zip=?,selected_provider_id=NULL,providers_json='[]',excluded_json='[]',evidence_json=?,availability_query_json=NULL WHERE id=?",
            (version, specialty, zip_code, json.dumps([evidence]), call_id),
        )
        if specialty != "primary care":
            # Refusals persist so the console shows the referral outcome and evidence.
            try:
                referral = require_referral(
                    conn, member, specialty, today, persist=True
                )
            except DomainError:
                event(conn, call_id, "referral_required", now)
                raise
        eligible, excluded = [], []
        order, nearby = provider_order(conn, zip_code, specialty)
        if order is not None:
            for provider in conn.execute(
                "SELECT * FROM providers WHERE specialty=? ORDER BY id", (specialty,)
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
                elif nearby(provider):
                    eligible.append(provider_view(provider))
            eligible.sort(key=distance_key(order, zip_code))
            eligible = eligible[:3]
        conn.execute(
            "UPDATE calls SET providers_json=?,excluded_json=? WHERE id=?",
            (json.dumps(eligible), json.dumps(excluded), call_id),
        )
        event(conn, call_id, "providers_searched", now)
        if not eligible:
            label = (
                "primary care provider"
                if specialty == "primary care"
                else specialty + " specialist"
            )
            raise DomainError(
                "NO_MATCH",
                f"I couldn't find an in-network {label} taking new patients near that ZIP.",
                persist=True,
            )
        names = " and ".join(p["name"] for p in eligible)
        lead = ""
        if referral and referral["status"] == "valid":
            lead = "I see your referral on file. "
        elif referral and referral["status"] == "not_required":
            lead = "Your plan doesn't need a referral for that. "
        reply = {
            "providers": eligible,
            "excluded": excluded,
            "evidence": [evidence],
            "request_version": version,
            "speak": f"{lead}I found {names} near you. Which would you like?",
        }
        if referral is not None:
            reply["referral"] = referral
        return reply


def select_provider(db, call_id, provider_id):
    with db.transaction() as conn:
        call = get_call(conn, call_id, verified=True, mutable=True)
        member = get_member(conn, call)
        now = db.now()
        require_coverage(member, now.astimezone(EASTERN).date())
        provider = check_provider(conn, call, member, provider_id)
        evidence = plan_evidence(conn, member, call["specialty"] or "primary care")
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
            "speak": f"Good choice, {provider['name']}. What day works for you?",
        }
