"""Paths and exam settings — sourced from exam.json via exam_config.

Other exams: edit ``exam.json`` (or point EXAM_CONFIG at another file).
You should not need to change this module for a new exam.
"""

from __future__ import annotations

import csv
import os
from dataclasses import dataclass, field
from pathlib import Path

from .exam_config import ExamConfig, FormCol, FormLayout, load_exam_config

ROOT = Path(__file__).resolve().parent.parent

# Optional override: EXAM_CONFIG=/path/to/other_exam.json
_EXAM_PATH = Path(os.environ["EXAM_CONFIG"]) if os.environ.get("EXAM_CONFIG") else None
EXAM: ExamConfig = load_exam_config(_EXAM_PATH)

WORK_DIR: Path = EXAM.work_dir
OUTPUT_DIR: Path = EXAM.output_dir
STATE_PATH: Path = WORK_DIR / "state.json"

POINTS_POSSIBLE: float = EXAM.points_possible
ASSIGNMENT_HEADER: str = EXAM.canvas_assignment
NUM_QUESTIONS: int = EXAM.num_questions

# Form grid (PDF user-space points) — from exam.json
# Kept as plain dicts so extract/export can use col["ans_x"] style access.
FORM_COLS = [
    {"q_x": tuple(c.q_x), "ans_x": tuple(c.ans_x), "q_start": c.q_start}
    for c in EXAM.form.cols
]
FORM_ROW_Y0: float = EXAM.form.row_y0
FORM_ROW_DY: float = EXAM.form.row_dy
FORM_N_ROWS: int = EXAM.form.n_rows
NAME_Y = tuple(EXAM.form.name_y)
ID_Y = tuple(EXAM.form.id_y)
FIELD_X_MIN: float = EXAM.form.field_x


@dataclass
class Student:
    name: str
    student_id: str
    sis_login: str
    section: str
    row_index: int
    extra: dict = field(default_factory=dict)

    @property
    def display(self) -> str:
        net = self.netid
        return f"{self.name} ({net})" if net else self.name

    @property
    def netid(self) -> str:
        login = (self.sis_login or "").split("@", 1)[0]
        return login

    @property
    def sis_id(self) -> str:
        """SIS / netid shown in the UI (prefer netid; fall back to email)."""
        return self.netid or self.sis_login or self.student_id


def load_roster(csv_path: Path) -> list[Student]:
    """Load students from a Canvas gradebook export."""
    students: list[Student] = []
    with csv_path.open(newline="", encoding="utf-8-sig") as fh:
        reader = csv.DictReader(fh)
        for i, row in enumerate(reader):
            name = (row.get("Student") or "").strip()
            # Skip header artifacts and the "Points Possible" summary row.
            if not name or name in {"Student"} or "Points Possible" in name:
                continue
            sid = (row.get("ID") or "").strip()
            if not sid:
                continue
            students.append(
                Student(
                    name=name,
                    student_id=sid,
                    sis_login=(row.get("SIS Login ID") or "").strip(),
                    section=(row.get("Section") or "").strip(),
                    row_index=i,
                )
            )
    return students


def find_roster_csv(root: Path | None = None) -> Path:
    root = root or ROOT
    patterns = [EXAM.roster_glob, "*.csv"]
    seen: set[Path] = set()
    candidates: list[Path] = []
    for pat in patterns:
        for p in sorted(root.glob(pat)):
            if p not in seen:
                seen.add(p)
                candidates.append(p)

    # Prefer a Canvas gradebook export (has an ID column).
    for p in candidates:
        try:
            with p.open(newline="", encoding="utf-8-sig") as fh:
                header = next(csv.reader(fh), [])
            if "ID" in header and "Student" in header:
                return p
        except OSError:
            continue
    if candidates:
        return candidates[0]
    raise FileNotFoundError(f"No roster CSV matching {EXAM.roster_glob!r} in {root}")


def find_answer_key_docx(root: Path | None = None) -> Path | None:
    root = root or ROOT
    named = EXAM.answer_key_docx
    if named:
        p = root / named
        if p.exists():
            return p
    for p in sorted(root.glob("*.docx")):
        return p
    return None


def find_scan_pdfs(root: Path | None = None) -> list[Path]:
    root = root or ROOT
    out: list[Path] = []
    seen: set[Path] = set()
    for pat in EXAM.scan_globs:
        for p in sorted(root.glob(pat)):
            if p.name.lower() in {"graded_feedback.pdf"} or p in seen:
                continue
            # Skip obvious non-scan PDFs
            if "feedback" in p.name.lower() or "report" in p.name.lower():
                continue
            seen.add(p)
            out.append(p)
    return out