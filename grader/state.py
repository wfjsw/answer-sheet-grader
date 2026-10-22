"""Persistent work state: page→student assignments and per-page answers."""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

from .config import NUM_QUESTIONS, STATE_PATH


def empty_state() -> dict:
    return {
        "version": 1,
        "points_possible": 20.0,
        "num_questions": NUM_QUESTIONS,
        "pages": {},  # page_id -> {student_id, answers: {q: letter}, notes}
    }


def load_state(path: Path | None = None) -> dict:
    path = path or STATE_PATH
    if not path.exists():
        return empty_state()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return empty_state()
    if not isinstance(data, dict) or "pages" not in data:
        return empty_state()
    data.setdefault("version", 1)
    data.setdefault("points_possible", 20.0)
    data.setdefault("num_questions", NUM_QUESTIONS)
    data.setdefault("pages", {})
    return data


def save_state(state: dict, path: Path | None = None) -> None:
    path = path or STATE_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=2, sort_keys=True), encoding="utf-8")
    tmp.replace(path)


def page_slot(state: dict, page_id: str) -> dict:
    pages = state.setdefault("pages", {})
    if page_id not in pages:
        pages[page_id] = {"student_id": None, "answers": {}, "notes": ""}
    slot = pages[page_id]
    slot.setdefault("student_id", None)
    slot.setdefault("answers", {})
    slot.setdefault("notes", "")
    return slot


def normalized_answers(slot: dict, num_questions: int | None = None) -> dict[int, str]:
    n = num_questions or state_num(slot)
    out: dict[int, str] = {}
    raw = slot.get("answers") or {}
    for q in range(1, n + 1):
        val = (raw.get(str(q)) or raw.get(q) or "").strip().upper()
        if val in {"A", "B", "C", "D"}:
            out[q] = val
        elif val in {"", "-"}:
            continue
        else:
            # Accept accidental lowercase / whitespace; anything else ignored.
            if len(val) == 1 and val.isalpha():
                out[q] = val
    return out


def state_num(slot: dict) -> int:
    return NUM_QUESTIONS


def clone_state(state: dict) -> dict:
    return deepcopy(state)