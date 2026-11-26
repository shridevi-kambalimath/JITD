"""Keyword-based evidence retrieval (BM25, pure Python, no index files: built in memory per run).

Two scopes:
* passage: one indexed unit per passage (search API, verification check V7)
* section: passages grouped by (document, section); used by reconciliation investigation to
  catch evidence that spans sentences, which the sentence-scoped extractor cannot see.

Query expansion uses the lexicon so 'metformin' also matches 'Glycomet'.
"""
from __future__ import annotations

import math
import re
from collections import Counter, defaultdict
from typing import Protocol

from ..schemas.domain import Passage, SearchHit
from . import lexicon as lx

BM25_K1 = 1.5
BM25_B = 0.75

_STOP = {"the", "a", "an", "of", "and", "or", "to", "in", "on", "for", "with", "was", "is", "be", "at", "by",
         "from", "as", "per", "patient"}
_TOKEN = re.compile(r"[a-z0-9]+")


def tokenize(text: str) -> list[str]:
    return [t for t in _TOKEN.findall(text.lower()) if t not in _STOP]


def expand_query(query: str) -> list[str]:
    tokens = tokenize(query)
    extra: list[str] = []
    finders = (lx.find_drugs, lx.find_diagnoses, lx.find_symptoms, lx.find_procedures)
    for find in finders:
        for m in find(query):
            for syn in lx.synonyms_for(m.canonical):
                extra.extend(tokenize(syn))
    for t in tokens:  # lab abbreviations: "hb" also finds "Hemoglobin"
        if (lab := lx.lab_canonical(t)) is not None:
            for syn in lx.synonyms_for(lab):
                extra.extend(tokenize(syn))
    return tokens + list(dict.fromkeys(t for t in extra if t not in tokens))


class Retriever(Protocol):
    """What the search API needs from a retriever. BM25 implements it today; a semantic or hybrid retriever
    can replace it later without touching the API, as long as hits still point at stored passages."""

    def search(self, query: str, k: int = 10, expand: bool = True) -> list[SearchHit]: ...


def match_spans(text: str, terms: list[str]) -> list[tuple[int, int]]:
    """Character spans in text of whole-token matches for any term (case-insensitive), for highlighting."""
    wanted = set(terms)
    return [(m.start(), m.end()) for m in _TOKEN.finditer(text.lower()) if m.group(0) in wanted]


class _BM25:
    def __init__(self, docs: list[list[str]]):
        self.docs = docs
        self.n = len(docs)
        self.avgdl = (sum(len(d) for d in docs) / self.n) if self.n else 0.0
        self.tf = [Counter(d) for d in docs]
        df: Counter = Counter()
        for d in docs:
            df.update(set(d))
        self.idf = {t: math.log(1 + (self.n - f + 0.5) / (f + 0.5)) for t, f in df.items()}

    def scores(self, query: list[str]) -> list[float]:
        out = []
        for tf, d in zip(self.tf, self.docs):
            s = 0.0
            for t in set(query):
                if t not in tf:
                    continue
                f = tf[t]
                s += self.idf[t] * f * (BM25_K1 + 1) / (f + BM25_K1 * (1 - BM25_B + BM25_B * len(d) / (self.avgdl or 1)))
            out.append(s)
        return out


class EvidenceIndex:
    def __init__(self, passages: list[Passage]):
        self.passages = [p for p in passages if p.section != "HEADER"]
        # the section label is indexed with each passage, so "allergies" finds the lines under ALLERGIES:
        self._p_index = _BM25([tokenize(f"{p.section} {p.text}") for p in self.passages])
        groups: dict[tuple[str, str], list[Passage]] = defaultdict(list)
        for p in self.passages:
            groups[(p.document_id, p.section)].append(p)
        self.sections = list(groups.values())
        self.section_by_first = {g[0].passage_id: g for g in self.sections}
        self._s_index = _BM25([tokenize(" ".join(p.text for p in g)) for g in self.sections])

    def search(self, query: str, k: int = 10, expand: bool = True) -> list[SearchHit]:
        q = expand_query(query) if expand else tokenize(query)
        ranked = sorted(zip(self._p_index.scores(q), self.passages), key=lambda x: (-x[0], x[1].passage_id))
        return [SearchHit(passage_id=p.passage_id, document_id=p.document_id, section=p.section,
                          score=round(s, 4), text=p.text) for s, p in ranked[:k] if s > 0]

    def search_sections(self, query: str, k: int = 10, expand: bool = True) -> list[SearchHit]:
        q = expand_query(query) if expand else tokenize(query)
        ranked = sorted(zip(self._s_index.scores(q), self.sections), key=lambda x: (-x[0], x[1][0].passage_id))
        return [SearchHit(passage_id=g[0].passage_id, document_id=g[0].document_id, section=g[0].section,
                          score=round(s, 4), text=" ".join(p.text for p in g)) for s, g in ranked[:k] if s > 0]
