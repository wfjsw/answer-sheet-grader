"""Load the exam answer key from the instructor DOCX (or a fallback dict)."""

from __future__ import annotations

import re
import zipfile
from xml.etree import ElementTree as ET

# Empty by default. Provide answers via exam.json (`answer_key.inline`) or an
# instructor DOCX (`answer_key.docx`). Shipping a real exam key in source is
# almost always a bad idea.
FALLBACK_KEY: dict[int, str] = {}

_NS = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}


def _docx_text(path) -> str:
    with zipfile.ZipFile(path) as zf:
        xml = zf.read("word/document.xml")
    root = ET.fromstring(xml)
    paragraphs = []
    for p in root.iter("{http://schemas.openxmlformats.org/wordprocessingml/2006/main}p"):
        texts = [t.text or "" for t in p.iter("{http://schemas.openxmlformats.org/wordprocessingml/2006/main}t")]
        paragraphs.append("".join(texts))
    return "\n".join(paragraphs)


def load_answer_key(docx_path=None) -> dict[int, str]:
    """Return {question_number: letter}.

    Order of preference:
      1. ``answer_key.inline`` in exam.json
      2. Instructor DOCX answer table
      3. Built-in fallback for this midterm
    """
    key, _just = load_key_and_justifications(docx_path)
    return key


def load_key_and_justifications(docx_path=None) -> tuple[dict[int, str], dict[int, str]]:
    """Return (key, justifications).

    Justifications come from the "Detailed Answer Key with Justifications"
    table in the instructor DOCX when present.
    """
    from .config import EXAM, NUM_QUESTIONS

    key = dict(FALLBACK_KEY)
    just: dict[int, str] = {}

    # exam.json inline key wins when provided (generic exams).
    if EXAM.answer_key_inline:
        key = {q: str(a).upper() for q, a in EXAM.answer_key_inline.items()}
        # Fill any gaps so the key is always complete for scoring.
        for q in range(1, NUM_QUESTIONS + 1):
            key.setdefault(q, FALLBACK_KEY.get(q, ""))
        key = {q: key[q] for q in range(1, NUM_QUESTIONS + 1)}

    if docx_path is None:
        return key, just

    try:
        text = _docx_text(docx_path)
    except (OSError, zipfile.BadZipFile, ET.ParseError):
        return key, just

    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]

    # Prefer the detailed section (Q / Ans / justification triples).
    lowered = text.lower()
    marker = "detailed answer key"
    idx = lowered.find(marker)
    chunk_lines = lines
    if idx >= 0:
        # Re-split from the marker so we only see that section's paragraphs.
        chunk = text[idx:]
        chunk_lines = [ln.strip() for ln in chunk.splitlines() if ln.strip()]

    parsed: dict[int, str] = {}
    jmap: dict[int, str] = {}
    i = 0
    while i < len(chunk_lines) - 1:
        if chunk_lines[i].isdigit():
            q = int(chunk_lines[i])
            ans = chunk_lines[i + 1].strip().upper()
            if 1 <= q <= 200 and len(ans) == 1 and ans.isalpha():
                parsed[q] = ans
                # Next non-empty line(s) that are not a new "N / letter" pair
                # are the justification.
                jtext = ""
                if i + 2 < len(chunk_lines):
                    nxt = chunk_lines[i + 2]
                    # Stop if this looks like the next question number
                    if not (nxt.isdigit() and i + 3 < len(chunk_lines)
                            and len(chunk_lines[i + 3]) == 1
                            and chunk_lines[i + 3].isalpha()):
                        jtext = nxt
                if jtext:
                    jmap[q] = jtext
                i += 2 if not jtext else 3
                continue
        i += 1

    # Fallback: short answer table only (no justifications).
    if len(parsed) < 50:
        parsed = {}
        m = re.search(r"Answer Table.*?Detailed", text, flags=re.S | re.I)
        region = m.group(0) if m else text
        tokens = [t.strip() for t in region.splitlines() if t.strip()]
        for j in range(len(tokens) - 1):
            if tokens[j].isdigit() and len(tokens[j + 1]) == 1 and tokens[j + 1].isalpha():
                q = int(tokens[j])
                if 1 <= q <= 200:
                    parsed[q] = tokens[j + 1].upper()

    if len(parsed) >= 50:
        for q, ans in FALLBACK_KEY.items():
            parsed.setdefault(q, ans)
        key = {q: parsed[q] for q in sorted(parsed) if 1 <= q <= 68}
        just = {q: jmap.get(q, "") for q in key}
    return key, just