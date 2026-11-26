"""NegEx/ConText-style assertion classification for a single entity mention.

Output is one of: present, absent, possible, historical, family.
Precedence: family > absent > possible > historical > present.

Scope: the clause containing the entity, bounded by ';' and contrastive terminators.
Pre-triggers are only honoured within the last PRE_WINDOW words before the entity.
"""
from __future__ import annotations

import re

PRE_WINDOW = 6

_TERMINATORS = re.compile(r";|\bbut\b|\bhowever\b|\balthough\b|\bexcept\b|\baside from\b", re.IGNORECASE)

FAMILY = [r"mother", r"father", r"sister", r"brother", r"grandmother", r"grandfather", r"aunt", r"uncle",
          r"sibling", r"family history of", r"family history"]
NEG_PRE = [r"no evidence of", r"no history of", r"no known", r"no signs? of", r"negative for", r"denies",
           r"without", r"absence of", r"free of", r"not", r"no"]
NEG_POST = [r"was ruled out", r"has been ruled out", r"ruled out", r"was excluded", r"excluded", r"is absent",
            r"not seen", r"not present"]
POSS_PRE = [r"possible", r"suspected", r"probable", r"likely", r"query", r"r/o", r"rule out",
            r"concern for", r"cannot exclude", r"\?"]
POSS_POST = [r"is suspected", r"suspected", r"not excluded", r"cannot be excluded", r"\?"]
HIST_PRE = [r"history of", r"h/o", r"past", r"previous", r"prior", r"old"]
HIST_POST = [r"treated in (?:19|20)\d{2}", r"resolved", r"in remission", r"in the past"]


def _first(patterns: list[str], text: str) -> str | None:
    for p in patterns:
        # '?' and '/' are not word characters, so use explicit boundaries
        m = re.search(rf"(?<![A-Za-z0-9]){p}(?![A-Za-z0-9])", text, re.IGNORECASE)
        if m:
            return m.group(0)
    return None


def clause_bounds(sentence: str, start: int, end: int) -> tuple[int, int]:
    left = 0
    for m in _TERMINATORS.finditer(sentence, 0, start):
        left = m.end()
    right = len(sentence)
    m = _TERMINATORS.search(sentence, end)
    if m:
        right = m.start()
    return left, right


def classify(sentence: str, start: int, end: int, section: str = "") -> tuple[str, str | None]:
    """Classify the entity at sentence[start:end]. Returns (assertion, trigger_text)."""
    if "FAMILY" in section.upper():
        return "family", f"section {section}"
    left, right = clause_bounds(sentence, start, end)
    pre_full = sentence[left:start]
    pre = " ".join(pre_full.split()[-PRE_WINDOW:])
    post = sentence[end:right]

    if t := _first(FAMILY, pre_full):
        return "family", t
    if t := _first(NEG_POST, post):
        return "absent", t
    if t := _first(NEG_PRE, pre):
        # "no history of X" is negation, "history of X" alone is historical; NEG_PRE is checked first
        return "absent", t
    if t := _first(POSS_PRE, pre) or _first(POSS_POST, post):
        return "possible", t
    if t := _first(HIST_PRE, pre) or _first(HIST_POST, post):
        return "historical", t
    return "present", None
