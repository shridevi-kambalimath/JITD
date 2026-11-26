from datetime import date

import pytest

from medusa.analysis.assertion import classify
from medusa.analysis.dates import DateContext, extract_date
from medusa.analysis.lexicon import find_diagnoses, find_drugs, parse_frequency, parse_route

CTX = DateContext(document_date=date(2026, 3, 12), admission_date=date(2026, 3, 10))


@pytest.mark.parametrize("text,value,precision,approx,basis", [
    ("Transfusion given on 2026-03-12.", date(2026, 3, 12), "day", False, "explicit"),
    ("Seen on 12 March 2026.", date(2026, 3, 12), "day", False, "explicit"),
    ("Seen on March 12, 2026.", date(2026, 3, 12), "day", False, "explicit"),
    ("Diagnosed in March 2020.", date(2020, 3, 1), "month", False, "explicit"),
    ("History of tuberculosis, treated in 2015.", date(2015, 1, 1), "year", False, "explicit"),
    ("On hospital day 3 the patient bled.", date(2026, 3, 12), "day", False, "relative"),
    ("Fever for approximately 3 days prior to admission.", date(2026, 3, 7), "day", True, "relative"),
    ("Cough for 1 week before admission.", date(2026, 3, 3), "day", False, "relative"),
    ("Black stools since last night.", date(2026, 3, 11), "day", True, "relative"),
])
def test_date_resolution(text, value, precision, approx, basis):
    dv = extract_date(text, CTX)
    assert dv is not None
    assert (dv.value, dv.precision, dv.approximate, dv.basis) == (value, precision, approx, basis)
    assert dv.raw_text


def test_relative_without_anchor_is_not_guessed():
    dv = extract_date("On hospital day 3 the patient bled.", DateContext(document_date=date(2026, 3, 15)))
    assert dv.value is None and dv.precision == "unknown" and dv.basis == "relative"
    assert "not resolved" in dv.note


def test_no_date_returns_none():
    assert extract_date("Type 2 diabetes mellitus.", CTX) is None


def test_invalid_calendar_date_rejected():
    assert extract_date("Seen on 2026-02-30.", CTX) is None


def _assert(sentence, term, section=""):
    m = next(x for x in find_diagnoses(sentence) if x.surface.lower() == term)
    return classify(sentence, m.start, m.end, section)[0]


@pytest.mark.parametrize("sentence,term,expected", [
    ("Type 2 diabetes mellitus.", "type 2 diabetes mellitus", "present"),
    ("No history of stroke.", "stroke", "absent"),
    ("No known chronic kidney disease.", "chronic kidney disease", "absent"),
    ("No evidence of pneumonia.", "pneumonia", "absent"),
    ("Pneumonia was ruled out on chest X-ray.", "pneumonia", "absent"),
    ("Possible pneumonia; chest X-ray requested.", "pneumonia", "possible"),
    ("r/o pneumonia with chest X-ray.", "pneumonia", "possible"),
    ("?pneumonia on admission.", "pneumonia", "possible"),
    ("History of tuberculosis, treated in 2015.", "tuberculosis", "historical"),
    ("Mother had breast cancer.", "breast cancer", "family"),
    ("Warfarin held due to upper gastrointestinal bleed.", "upper gastrointestinal bleed", "present"),
    ("No fever; hypertension noted.", "hypertension", "present"),  # negation does not cross ';'
])
def test_assertion(sentence, term, expected):
    assert _assert(sentence, term) == expected


def test_family_section_forces_family():
    assert _assert("Hypertension.", "hypertension", section="FAMILY HISTORY") == "family"


def test_negation_window_limited():
    s = "No fever reported by the patient during the long night and hypertension noted."
    assert _assert(s, "hypertension") == "present"


def test_drug_normalisation_and_regimen_parsing():
    assert [m.canonical for m in find_drugs("Glycomet 500 mg orally twice daily.")] == ["metformin"]
    assert [m.canonical for m in find_drugs("Atorva 20 mg at night")] == ["atorvastatin"]
    assert parse_frequency("40 mg IV twice daily") == ("twice daily", 2.0)
    assert parse_frequency("20 mg orally at night")[1] == 1.0
    assert parse_route("40 mg IV twice daily") == "IV"
    assert parse_route("5 mg orally once daily") == "oral"


def test_longest_match_wins():
    assert [m.canonical for m in find_diagnoses("upper gastrointestinal bleed")] == ["upper gastrointestinal bleed"]
