"""Controlled vocabularies and normalisation.

Prototype scope: small curated lexicons that cover the demo bundle plus common neighbours.
Production would replace these with RxNorm / SNOMED CT / LOINC lookups behind the same functions.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

# generic name -> (drug class, surface synonyms)
DRUGS: dict[str, tuple[str, list[str]]] = {
    "warfarin": ("anticoagulant", ["warfarin", "coumadin"]),
    "apixaban": ("anticoagulant", ["apixaban", "eliquis"]),
    "rivaroxaban": ("anticoagulant", ["rivaroxaban", "xarelto"]),
    "enoxaparin": ("anticoagulant", ["enoxaparin", "clexane"]),
    "heparin": ("anticoagulant", ["heparin"]),
    "metformin": ("biguanide", ["metformin", "glycomet", "glucophage"]),
    "atorvastatin": ("statin", ["atorvastatin", "atorva", "lipitor"]),
    "pantoprazole": ("proton pump inhibitor", ["pantoprazole", "pantocid"]),
    "amlodipine": ("calcium channel blocker", ["amlodipine", "amlong", "norvasc"]),
    "aspirin": ("antiplatelet", ["aspirin", "ecosprin"]),
    "insulin glargine": ("insulin", ["insulin glargine", "lantus"]),
    "morphine": ("opioid", ["morphine"]),
    "tramadol": ("opioid", ["tramadol"]),
    "paracetamol": ("analgesic", ["paracetamol", "acetaminophen"]),
}

DIAGNOSES: dict[str, list[str]] = {
    "pneumonia": ["community-acquired pneumonia", "pneumonia"],
    "type 2 diabetes mellitus": ["type 2 diabetes mellitus", "type 2 diabetes", "t2dm", "diabetes mellitus"],
    "hypertension": ["hypertension", "htn"],
    "atrial fibrillation": ["atrial fibrillation", "afib"],
    "chronic kidney disease": ["chronic kidney disease", "ckd"],
    "upper gastrointestinal bleed": ["upper gastrointestinal bleed", "upper gi bleed", "ugib"],
    "gastrointestinal bleed": ["gastrointestinal bleed", "gi bleed"],
    "tuberculosis": ["tuberculosis"],
    "stroke": ["stroke", "cerebrovascular accident"],
    "breast cancer": ["breast cancer"],
    "myocardial infarction": ["myocardial infarction"],
    "heart failure": ["heart failure"],
    "sepsis": ["sepsis"],
    "gastric ulcer": ["bleeding gastric ulcer", "gastric ulcer"],
}

SYMPTOMS: dict[str, list[str]] = {
    "fever": ["fever"],
    "cough": ["productive cough", "cough"],
    "melena": ["melena", "black stools", "tarry stools"],
    "shortness of breath": ["shortness of breath", "dyspnea"],
    "abdominal pain": ["abdominal pain"],
    "dizziness": ["dizziness"],
}

PROCEDURES: dict[str, list[str]] = {
    "chest x-ray": ["chest x-ray", "chest radiograph"],
    "blood transfusion": ["blood transfusion"],
    "upper gi endoscopy": ["upper gi endoscopy", "endoscopy"],
}

LABS: dict[str, list[str]] = {
    "hemoglobin": ["hemoglobin", "haemoglobin", "hb"],
    "potassium": ["potassium", "k"],
    "creatinine": ["creatinine"],
    "inr": ["inr"],
    "sodium": ["sodium", "na"],
}

ALLERGENS: dict[str, list[str]] = {
    "penicillin": ["penicillin"],
    "sulfonamide": ["sulfonamide", "sulfa"],
    "cephalosporin": ["cephalosporin"],
    "codeine": ["codeine"],
}

# referenced record types: keyword that precedes "report"
REPORT_TYPES = {"endoscopy", "histopathology", "biopsy", "pathology", "echocardiogram", "ct", "mri",
                "culture", "operative", "radiology", "laboratory", "lab", "ultrasound"}

FREQUENCIES: list[tuple[str, float]] = [
    (r"four times daily|qid|qds", 4.0),
    (r"three times daily|tds|tid", 3.0),
    (r"twice daily|twice a day|bd|bid", 2.0),
    (r"once daily|once a day|daily|od|qd|at night|nightly|hs|every morning", 1.0),
    (r"weekly|once a week", 1.0 / 7.0),
]
ROUTES: list[tuple[str, str]] = [
    (r"orally|oral|po|by mouth", "oral"),
    (r"intravenously|intravenous|iv", "IV"),
    (r"subcutaneously|subcutaneous|sc", "SC"),
    (r"intramuscularly|intramuscular|im", "IM"),
]


@dataclass(frozen=True)
class Match:
    canonical: str
    surface: str
    start: int
    end: int


def _compile(table: dict[str, list[str]]) -> tuple[re.Pattern, dict[str, str]]:
    lookup: dict[str, str] = {}
    for canonical, synonyms in table.items():
        for s in synonyms:
            lookup[s.lower()] = canonical
    alts = sorted(lookup, key=len, reverse=True)  # longest first
    pattern = re.compile(r"(?<![A-Za-z0-9])(" + "|".join(re.escape(a) for a in alts) + r")(?![A-Za-z0-9])",
                         re.IGNORECASE)
    return pattern, lookup


_DRUG_RE, _DRUG_LOOKUP = _compile({k: v[1] for k, v in DRUGS.items()})
_DX_RE, _DX_LOOKUP = _compile(DIAGNOSES)
_SYM_RE, _SYM_LOOKUP = _compile(SYMPTOMS)
_PROC_RE, _PROC_LOOKUP = _compile(PROCEDURES)
_LAB_RE, _LAB_LOOKUP = _compile(LABS)
_ALG_RE, _ALG_LOOKUP = _compile(ALLERGENS)


def _find(pattern: re.Pattern, lookup: dict[str, str], text: str) -> list[Match]:
    return [Match(lookup[m.group(1).lower()], m.group(1), m.start(1), m.end(1)) for m in pattern.finditer(text)]


def find_drugs(text: str) -> list[Match]:
    return _find(_DRUG_RE, _DRUG_LOOKUP, text)


def find_diagnoses(text: str) -> list[Match]:
    return _find(_DX_RE, _DX_LOOKUP, text)


def find_symptoms(text: str) -> list[Match]:
    return _find(_SYM_RE, _SYM_LOOKUP, text)


def find_procedures(text: str) -> list[Match]:
    return _find(_PROC_RE, _PROC_LOOKUP, text)


def find_allergens(text: str) -> list[Match]:
    return _find(_ALG_RE, _ALG_LOOKUP, text)


def lab_canonical(name: str) -> str | None:
    return _LAB_LOOKUP.get(name.strip().lower())


def drug_class(drug: str) -> str:
    return DRUGS[drug][0]


def synonyms_for(canonical: str) -> list[str]:
    """All surface forms for a canonical entity in any lexicon (used for retrieval expansion)."""
    if canonical in DRUGS:
        return DRUGS[canonical][1]
    for table in (DIAGNOSES, SYMPTOMS, PROCEDURES, LABS, ALLERGENS):
        if canonical in table:
            return table[canonical]
    return [canonical]


def parse_frequency(text: str) -> tuple[str | None, float | None]:
    for pattern, per_day in FREQUENCIES:
        m = re.search(rf"\b({pattern})\b", text, re.IGNORECASE)
        if m:
            return m.group(1), per_day
    return None, None


def parse_route(text: str) -> str | None:
    for pattern, route in ROUTES:
        if re.search(rf"\b({pattern})\b", text, re.IGNORECASE):
            return route
    return None


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
