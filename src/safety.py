"""Emergency screen. Plain code, runs before any reply is spoken.

A false alarm costs one sentence, and a missed emergency costs far more. So any
present-tense or unclear mention triggers. A mention is skipped only when it is
clearly negated ("I don't have chest pain") or clearly in the past ("I had chest
pain last year"). Someone else's problem with no sign it is happening now gets one
question instead of a 911 line.

Spec: docs/MEMBERGUIDE-FINAL-PLAN.md, section 7 ("Safety screen").
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

Kind = Literal["emergency", "self_harm", "ask"]

EMERGENCY_LINE = (
    "This sounds urgent. Please hang up and call 911 now. "
    "I can't place the call for you, so please call right away."
)
EMERGENCY_REMINDER = (
    "Please call 911 right away. I'm here if there's anything else I can do."
)
SELF_HARM_LINE = "Please call or text 988 now to reach someone who can help."
ASK_LINE = "Is that happening right now?"

_EMERGENCY = [
    r"chest pain",
    r"chest pressure",
    r"(?:can'?t|cannot|can not|unable to) breathe",
    r"trouble breathing",
    r"difficulty breathing",
    r"short(?:ness)? of breath",
    r"not breathing",
    r"heart attack",
    r"(?<!golf )(?<!breast)(?<!back)(?<!swim )stroke",
    r"throat (?:is |was )?(?:closing|swelling)",
    r"allergic reaction",
    r"anaphyla\w+",
    r"(?:bleeding|blood) (?:won'?t|will not|isn'?t going to) stop",
    r"can'?t stop the bleeding",
    r"too many (?:pills|tablets|meds|medications)",
    r"collapsed",
    r"unresponsive",
    r"(?:isn'?t|is not|not|stopped) (?:moving|responding)",
    r"overdos(?:e|ed|ing)",
    r"severe bleeding",
    r"bleeding (?:heavily|badly|a lot)",
    r"unconscious",
    r"passed out",
    r"seizure",
    r"(?:it|this|that)(?:'?s| is) (?:a |an )?(?:medical )?emergency",
    r"(?:medical )?emergency",
    r"ambulance",
    r"(?:call|dial|need|get) (?:me )?(?:911|nine one one)",
    r"\b911\b",
    r"(?:can'?t|cannot) feel my (?:arm|arms|leg|legs|face|hand|hands)",
    r"numb(?:ness)? (?:in|on) (?:my|one side|the)\b",
    r"face (?:is )?drooping",
    r"slurred speech",
    r"(?:chest|heart) (?:is )?(?:tight|racing|pounding|crushing)",
    r"tight(?:ness)? in my chest",
    r"(?:feel|feeling|about to) (?:faint|pass out)",
    r"fainted",
    r"(?:coughing|vomiting|throwing up) (?:up )?blood",
    r"choking",
]
_SELF_HARM = [
    r"kill myself",
    r"end my life",
    r"suicid(?:e|al)",
    r"want to die",
    r"end it all",
    r"(?:don'?t|do not) want to (?:live|be here|be alive)(?: anymore)?",
    r"better off dead",
    r"no reason to live",
    r"hurt myself",
    r"harm myself",
]

_EMERGENCY_RE = re.compile("|".join(f"(?:{p})" for p in _EMERGENCY), re.I)
_SELF_HARM_RE = re.compile("|".join(f"(?:{p})" for p in _SELF_HARM), re.I)

# A negation in the few words just before the phrase.
_NEGATION = re.compile(
    r"\b(?:no|not|never|without|none|nothing|isn'?t|aren'?t|wasn'?t|weren'?t|"
    r"don'?t|doesn'?t|didn'?t|haven'?t|hasn'?t|hadn'?t|won'?t|"
    r"do not|does not|did not|have not|has not|had not|"
    r"don'?t (?:have|feel|get)|no sign of|rule out|ruled out)\b",
    re.I,
)
# Words that put the problem in the past.
_PAST = re.compile(
    r"\b(?:last (?:year|month|week|decade)|years? ago|months? ago|weeks? ago|"
    r"days? ago|in the past|used to|history of|when i was|as a (?:kid|child)|"
    r"previously|a while back|back in (?:\d{4}|college|high school))\b",
    re.I,
)
# Words that say it is happening now.
_PRESENT = re.compile(
    r"\b(?:right now|currently|at the moment|as we speak|today|tonight|"
    r"i(?:'m| am) (?:having|getting|feeling|about to)|is having|are having|"
    r"is not breathing|just (?:happened|started)|happening now|"
    r"it (?:is|'s) happening)\b",
    re.I,
)
# Someone other than the caller.
_THIRD_PARTY = re.compile(
    r"\b(?:my|his|her|their)\s+(?:mom|mother|dad|father|wife|husband|son|daughter|"
    r"brother|sister|partner|friend|neighbou?r|coworker|boss|grand\w+|uncle|aunt|"
    r"cousin|baby|child|kid)\b|\b(?:someone|somebody|he|she|they)\b",
    re.I,
)


@dataclass(frozen=True)
class Verdict:
    kind: Kind
    line: str
    task_detail: str


# A new clause resets a negation: "no wait, I'm having chest pain" is not negated.
_CLAUSE_BREAK = re.compile(
    r"[,.;!?]|\b(?:but|wait|actually|however|though|and|so|because)\b", re.I
)
# "I don't know if it's a stroke" doubts the cause. It does not deny the symptom.
_DOUBT = re.compile(
    r"\b(?:(?:don'?t|do not|didn'?t|not) (?:know|sure|think)|no idea|unsure|not certain)\b",
    re.I,
)


def _negated(before: str) -> bool:
    """A negation within the last four words of the same clause, before the phrase."""
    clause = _CLAUSE_BREAK.split(before)[-1]
    clause = _DOUBT.sub(" ", clause)
    words = clause.split()[-4:]
    return bool(_NEGATION.search(" ".join(words)))


def _classify(text: str, match: re.Match[str]) -> Kind | None:
    """What to do with one phrase hit, or None to skip it."""
    before = text[: match.start()]
    if _negated(before):
        return None
    if _PRESENT.search(text):
        return "emergency"
    if _PAST.search(text):
        return None
    if _THIRD_PARTY.search(before):
        # "he is unconscious" is happening now. "my mother had a stroke" is unclear.
        if re.search(r"\b(?:is|are)\b|'s\b", " ".join(before.split()[-3:]), re.I):
            return "emergency"
        return "ask"
    return "emergency"


def check_safety(text: str) -> Verdict | None:
    """Return what to say for an emergency or self-harm mention, or None."""
    t = " ".join(text.replace("\u2019", "'").split())
    if not t:
        return None

    for m in _SELF_HARM_RE.finditer(t):
        kind = _classify(t, m)
        if kind == "emergency":
            return Verdict("self_harm", SELF_HARM_LINE, "Caller mentioned self-harm.")
        if kind == "ask":
            return Verdict("ask", ASK_LINE, "Unclear self-harm mention, asked once.")

    for m in _EMERGENCY_RE.finditer(t):
        kind = _classify(t, m)
        if kind == "emergency":
            return Verdict(
                "emergency", EMERGENCY_LINE, f"Caller mentioned: {m.group(0).lower()}."
            )
        if kind == "ask":
            return Verdict("ask", ASK_LINE, f"Unclear mention: {m.group(0).lower()}.")
    return None
