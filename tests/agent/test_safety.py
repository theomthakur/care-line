"""Safety screen: triggers on present or unclear mentions, skips negated and past ones."""

import pytest

from safety import ASK_LINE, EMERGENCY_LINE, SELF_HARM_LINE, check_safety


@pytest.mark.parametrize(
    "text",
    [
        "I have chest pain",
        "I'm having severe chest pain and trouble breathing",
        "i cant breathe",
        "I can't breathe",
        "My chest pain started an hour ago",
        "I think I'm having a stroke",
        "I took too many pills, an overdose",
        "There is severe bleeding",
        "he is unconscious",
        "My husband is having chest pain right now",
        "My mom has chest pain right now",
        "Actually, I'm having chest pain right now, forget the appointment",
        "chest pain",
        "I have a doctor visit and I also have chest pain",
    ],
)
def test_present_or_unclear_mentions_trigger(text: str) -> None:
    v = check_safety(text)
    assert v is not None and v.kind == "emergency" and v.line == EMERGENCY_LINE


@pytest.mark.parametrize(
    "text",
    [
        "I don't have chest pain, I just need a checkup",
        "No chest pain, just a regular visit",
        "I do not have chest pain",
        "I never had a stroke",
        "I haven't had any chest pain",
        "I wasn't unconscious",
        "I had chest pain last year but it's fine now and I need a new doctor",
        "My dad had a stroke years ago and I want a primary care doctor",
        "I used to have seizures when I was a kid",
        "history of heart attack in my family, looking for a cardiologist",
    ],
)
def test_negated_or_past_mentions_do_not_trigger(text: str) -> None:
    assert check_safety(text) is None


@pytest.mark.parametrize(
    "text",
    [
        "My mother had a stroke",
        "my brother had chest pain",
        "someone had a seizure",
    ],
)
def test_someone_elses_unclear_mention_asks_once(text: str) -> None:
    v = check_safety(text)
    assert v is not None and v.kind == "ask" and v.line == ASK_LINE


@pytest.mark.parametrize(
    "text",
    ["I want to kill myself", "I'm thinking about suicide", "I want to die", "I might hurt myself"],
)
def test_self_harm_gets_the_988_line(text: str) -> None:
    v = check_safety(text)
    assert v is not None and v.kind == "self_harm" and v.line == SELF_HARM_LINE


@pytest.mark.parametrize(
    "text",
    ["I don't want to kill myself", "I'm not suicidal", "No thoughts of suicide"],
)
def test_negated_self_harm_does_not_trigger(text: str) -> None:
    assert check_safety(text) is None


@pytest.mark.parametrize(
    "text",
    [
        "",
        "   ",
        "I need a primary care doctor near 10023",
        "Do you have anything Thursday morning?",
        "Yes, please book it",
        "The doctor's office is on Park Avenue",
        "I broke my chest freezer",
    ],
)
def test_ordinary_calls_do_not_trigger(text: str) -> None:
    assert check_safety(text) is None


def test_curly_apostrophes_are_handled() -> None:
    assert check_safety("I can’t breathe") is not None
    assert check_safety("I don’t have chest pain") is None
