"""Specialist referral policy. The backend decides; the agent only speaks the result.

A specialist visit is allowed when the plan does not require a referral, or when
the member has a verified, non-revoked referral for that specialty that is valid
on the visit's Eastern date. A caller-reported recommendation never counts.
"""

from .errors import DomainError

SPECIALTIES = ("cardiology", "dermatology")

SPEAK = {
    "missing": "Your plan needs a referral from your primary care doctor before a {s} visit, and I don't see one on file. I can file a follow-up request for our team.",
    "reported": "Your plan needs a verified referral before a {s} visit. I only see a reported recommendation, not a referral from your doctor. I can file a follow-up request.",
    "expired": "Your plan needs a referral for a {s} visit, and the one on file isn't valid for that date. I can file a follow-up request for our team.",
    "revoked": "Your plan needs a referral for a {s} visit, and the one on file is no longer active. I can file a follow-up request for our team.",
}


def referral_evidence(conn, member):
    row = conn.execute(
        "SELECT id,title,text FROM plan_sections WHERE plan_id=? AND topic='referral'",
        (member["plan_id"],),
    ).fetchone()
    if not row:
        raise DomainError("NO_SUPPORTED_ANSWER")
    return dict(row)


def referral_view(row):
    return {
        key: row[key]
        for key in (
            "id",
            "referring_provider_id",
            "referring_appointment_id",
            "specialty",
            "status",
            "valid_from",
            "valid_until",
            "source",
        )
    }


def eligibility(conn, member, specialty, visit_date):
    """Return a ReferralEligibility dict for a specialist visit on visit_date."""
    evidence = referral_evidence(conn, member)
    required = bool(
        conn.execute(
            "SELECT specialist_referral_required FROM plans WHERE id=?",
            (member["plan_id"],),
        ).fetchone()[0]
    )
    result = {"required": required, "evidence_id": evidence["id"], "referral": None}
    if not required:
        return {**result, "status": "not_required", "eligible": True}
    rows = conn.execute(
        "SELECT * FROM referrals WHERE member_id=? AND specialty=? ORDER BY created_at DESC, id",
        (member["id"], specialty),
    ).fetchall()
    day = visit_date.isoformat()
    for row in rows:
        if (
            row["status"] == "verified"
            and row["valid_from"] <= day <= row["valid_until"]
        ):
            return {
                **result,
                "status": "valid",
                "eligible": True,
                "referral": referral_view(row),
            }
    # Explain the most useful reason when nothing is valid.
    status = "missing"
    for candidate in ("revoked", "expired", "reported"):
        match = next(
            (
                r
                for r in rows
                if (r["status"] == "verified" and candidate == "expired")
                or r["status"] == candidate
            ),
            None,
        )
        if match is not None:
            status = candidate
            result["referral"] = referral_view(match)
            break
    return {**result, "status": status, "eligible": False}


def require_referral(conn, member, specialty, visit_date, *, persist=False):
    """Raise REFERRAL_REQUIRED unless the specialist visit is allowed on that date."""
    result = eligibility(conn, member, specialty, visit_date)
    if not result["eligible"]:
        raise DomainError(
            "REFERRAL_REQUIRED",
            SPEAK[result["status"]].format(s=specialty),
            persist=persist,
            referral_status=result["status"],
        )
    return result
