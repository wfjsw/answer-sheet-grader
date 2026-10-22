"""Optional OCR hints for student matching. The UI is the source of truth.

Everything here is a *suggestion* only. The instructor assigns pages by hand.
"""

from __future__ import annotations

import re
from difflib import SequenceMatcher

from .config import Student


def _clean(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def _digits(s: str) -> str:
    return re.sub(r"\D", "", s or "")


def suggest_students(
    ocr_name: str,
    ocr_id: str,
    roster: list[Student],
    limit: int = 8,
) -> list[dict]:
    """Return ranked guesses. Scores are heuristic; never auto-assign."""
    name_c = _clean(ocr_name)
    id_digits = _digits(ocr_id)
    name_digits = _digits(ocr_name)
    blob = _clean(ocr_name) + _digits(ocr_name) + _digits(ocr_id)

    scored: list[tuple[float, Student, str]] = []
    for st in roster:
        last, first = (st.name.split(",", 1) + [""])[:2] if "," in st.name else (st.name, "")
        cands = [
            _clean(last) + _clean(first),
            _clean(first) + _clean(last),
            _clean(last),
            _clean(st.name),
        ]
        name_score = 0.0
        if name_c:
            for c in cands:
                if not c:
                    continue
                name_score = max(name_score, SequenceMatcher(None, name_c, c).ratio())

        id_score = 0.0
        for d in (id_digits, name_digits, _digits(ocr_name)):
            if not d:
                continue
            if d == st.student_id or st.student_id.endswith(d) or d.endswith(st.student_id):
                id_score = 1.0
                break
            if d in st.student_id or st.student_id in d:
                id_score = max(id_score, 0.75)

        net_score = 0.0
        net = st.netid.lower()
        if net and net in blob:
            net_score = 1.0
        elif net:
            net_score = SequenceMatcher(None, net, blob).ratio() * 0.6

        score = max(name_score * 0.85, id_score, net_score)
        if score < 0.28:
            continue
        why = []
        if id_score >= 0.75:
            why.append("id")
        if net_score >= 0.9:
            why.append("netid")
        if name_score >= 0.5:
            why.append(f"name {name_score:.2f}")
        scored.append((score, st, ", ".join(why) or "weak"))

    scored.sort(key=lambda z: (-z[0], z[1].name))
    out = []
    for score, st, why in scored[:limit]:
        out.append(
            {
                "name": st.name,
                "student_id": st.student_id,
                "sis_login": st.sis_login,
                "sis_id": st.sis_id,
                "netid": st.netid,
                "section": st.section,
                "score": round(score, 3),
                "why": why,
            }
        )
    return out