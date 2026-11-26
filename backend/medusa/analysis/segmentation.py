"""Segmentation: a processed document's canonical text -> passages with absolute character offsets.

Passages are the unit every claim cites. Header lines (KEY: value, up to '---') become HEADER passages;
in the body a line that is an uppercase label ending in ':' opens a section, and each sentence or list
line becomes one passage.

Invariant (tested): text[p.char_start:p.char_end] == p.text for every passage.
"""
from __future__ import annotations

import re

from ..schemas.domain import Passage

_SECTION_LINE = re.compile(r"^([A-Z][A-Z0-9 /&()\-]+):\s*$")
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+(?=[A-Z])")  # after . ! ? followed by space and a capital


def segment(document_id: str, text: str) -> list[Passage]:
    passages: list[Passage] = []

    def add(section: str, start: int, end: int) -> None:
        while start < end and text[start].isspace():
            start += 1
        while end > start and text[end - 1].isspace():
            end -= 1
        if end > start:
            passages.append(Passage(passage_id=f"{document_id}:P{len(passages) + 1:03d}", document_id=document_id,
                                    section=section, char_start=start, char_end=end, text=text[start:end]))

    lines = text.split("\n")
    has_header = any(ln.strip() == "---" for ln in lines[:61])
    offset, in_header, section = 0, has_header, "BODY"
    for line in lines:
        start = offset
        offset += len(line) + 1
        if in_header:
            if line.strip() == "---":
                in_header = False
            else:
                add("HEADER", start, start + len(line))
            continue
        if not line.strip():
            continue
        m = _SECTION_LINE.match(line.strip())
        if m:
            section = m.group(1).strip()
            continue
        cursor = 0
        for sm in _SENTENCE_SPLIT.finditer(line):
            add(section, start + cursor, start + sm.start())
            cursor = sm.end()
        add(section, start + cursor, start + len(line))
    return passages
