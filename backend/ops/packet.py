"""Handoff packets, built only from stored rows (never from model text)."""

from __future__ import annotations

import sqlite3

SUGGESTED = {
    "caller_requested": "Contact the member to help choose a provider and a visit time.",
    "knowledge_gap": "Answer the member's question from approved plan material and call back.",
    "verification_failed": "Do not share member details. Offer the caller a way to confirm identity through member services.",
    "tool_failure": "Check the demo service, then call the member back to finish the request.",
    "safety": "Follow the urgent-safety procedure and check on the caller.",
    "policy_required": "Review the request against policy and call the member back.",
    "waitlist": "Call the office for the next opening and offer the member a callback.",
}

_WHAT = {
    "caller_requested": "asked for help from a person before booking",
    "knowledge_gap": "asked something the demo has no supported plan answer for",
    "tool_failure": "was affected by two system failures in a row",
    "safety": "mentioned an urgent safety concern, and was given the 911 or 988 line",
    "policy_required": "asked for something that needs a person's review",
    "waitlist": "found no open times",
}


def _first_name(display: str) -> str:
    return display.split()[0] if display else "The caller"


def build_packet(
    conn: sqlite3.Connection, call_id: str, category: str, detail: str, reference: str
) -> dict:
    call = conn.execute("SELECT * FROM calls WHERE id = ?", (call_id,)).fetchone()
    member = None
    if call and call["member_id"]:
        member = conn.execute(
            "SELECT m.display_name, p.name AS plan FROM members m JOIN plans p ON p.id = m.plan_id WHERE m.id = ?",
            (call["member_id"],),
        ).fetchone()
    verified = bool(call and call["verification_status"] == "verified" and member)
    who = _first_name(member["display_name"]) if member else "The caller"
    need = call["first_request"] if call and call["first_request"] else None
    if category == "verification_failed":
        summary = "A caller could not be verified after three attempts. No member data was shared."
    else:
        lead = (
            f"{who}'s request: \u201c{need.strip()}\u201d "
            if need
            else f"{who} needed help with a primary care visit. "
        )
        summary = f"{lead}{who} {_WHAT.get(category, 'needs a person to follow up')}."
    names = [
        r["name"]
        for r in conn.execute(
            "SELECT name FROM events WHERE call_id = ? ORDER BY id", (call_id,)
        )
    ]
    zip_ = call["zip"] if call else None
    tried = []
    if "verified" in names:
        tried.append("Verified identity")
    elif call and call["verification_attempts"]:
        tried.append(
            f"Tried to verify identity ({call['verification_attempts']} attempts)"
        )
    if "providers_searched" in names:
        tried.append(
            f"Searched primary care near {zip_}"
            if zip_
            else "Searched primary care providers"
        )
        tried.append("Explained eligible and excluded providers")
    if "availability_offered" in names:
        tried.append("Offered open times")
    if "slot_taken" in names:
        tried.append("A chosen time was taken by another caller")
    return {
        "reference": reference,
        "category": category,
        "summary": summary,
        "detail": detail,
        "caller_verified": verified,
        "plan": member["plan"] if verified else None,
        "already_tried": tried,
        "suggested_next_action": SUGGESTED.get(category, "Follow up with the caller."),
    }
