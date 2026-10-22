"""Exam-specific configuration loaded from ``exam.json``.

Everything that changes between exams lives in that file:

- how many questions and their point weights
- Canvas assignment column name
- where the roster / scans / answer key are
- the printed answer-sheet grid (or auto-detected)

Swap in a new ``exam.json`` and the grader works for another exam —
no code changes.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG = ROOT / "exam.json"


@dataclass
class FormCol:
    q_x: tuple[float, float]
    ans_x: tuple[float, float]
    q_start: int


@dataclass
class FormLayout:
    page_width: float = 612.0
    page_height: float = 792.0
    row_y0: float = 182.0
    row_dy: float = 18.7
    n_rows: int = 17
    cols: list[FormCol] = field(default_factory=list)
    name_y: tuple[float, float] = (93.0, 122.0)
    id_y: tuple[float, float] = (108.0, 128.0)
    field_x: float = 155.0


@dataclass
class ExamConfig:
    title: str = "Exam"
    canvas_assignment: str = "Assignment"
    points_possible: float = 20.0
    num_questions: int = 50
    question_points: dict[int, float] = field(default_factory=dict)
    default_question_points: float = 1.0
    answer_key_docx: str | None = None
    answer_key_inline: dict[int, str] = field(default_factory=dict)
    roster_glob: str = "*.csv"
    scan_globs: list[str] = field(default_factory=lambda: ["*.pdf"])
    work_dir: Path = ROOT / "work"
    output_dir: Path = ROOT / "output"
    form: FormLayout = field(default_factory=FormLayout)
    raw: dict[str, Any] = field(default_factory=dict)

    def points_for(self, q: int) -> float:
        return float(self.question_points.get(q, self.default_question_points))

    @property
    def total_points(self) -> float:
        return round(sum(self.points_for(q) for q in range(1, self.num_questions + 1)), 2)


def _as_pt_pair(val: Any, fallback: tuple[float, float]) -> tuple[float, float]:
    if isinstance(val, (list, tuple)) and len(val) == 2:
        return (float(val[0]), float(val[1]))
    return fallback


def load_exam_config(path: Path | None = None) -> ExamConfig:
    """Load ``exam.json`` (or the given path). Missing file → sensible defaults."""
    path = path or DEFAULT_CONFIG
    data: dict[str, Any] = {}
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            data = {}

    root = path.parent if path.exists() else ROOT

    # --- point weights ---
    qp_raw = data.get("question_points") or {}
    question_points: dict[int, float] = {}
    default_pts = float(qp_raw.get("default", 1.0)) if isinstance(qp_raw, dict) else 1.0
    if isinstance(qp_raw, dict):
        for k, v in qp_raw.items():
            if str(k).isdigit():
                question_points[int(k)] = float(v)

    num_q = int(data.get("num_questions") or 0)
    if num_q <= 0:
        num_q = max(question_points) if question_points else 50

    # --- answer key ---
    ak = data.get("answer_key") or {}
    inline_key: dict[int, str] = {}
    if isinstance(ak.get("inline"), dict):
        for k, v in ak["inline"].items():
            if str(k).isdigit() and str(v).upper() in {"A", "B", "C", "D"}:
                inline_key[int(k)] = str(v).upper()

    # --- paths ---
    paths = data.get("paths") or {}
    work_dir = root / paths.get("work_dir", "work")
    output_dir = root / paths.get("output_dir", "output")
    scan_globs = paths.get("scan_globs") or ["*.pdf"]
    if isinstance(scan_globs, str):
        scan_globs = [scan_globs]

    # --- form grid ---
    fraw = data.get("form") or {}
    cols: list[FormCol] = []
    for c in fraw.get("cols") or []:
        try:
            cols.append(
                FormCol(
                    q_x=_as_pt_pair(c.get("q_x"), (88.0, 108.0)),
                    ans_x=_as_pt_pair(c.get("ans_x"), (122.0, 175.0)),
                    q_start=int(c.get("q_start", 1)),
                )
            )
        except (TypeError, ValueError):
            continue

    form = FormLayout(
        page_width=float(fraw.get("page_width", 612.0)),
        page_height=float(fraw.get("page_height", 792.0)),
        row_y0=float(fraw.get("row_y0", 182.0)),
        row_dy=float(fraw.get("row_dy", 18.7)),
        n_rows=int(fraw.get("n_rows", 17)),
        cols=cols,
        name_y=_as_pt_pair(fraw.get("name_y"), (93.0, 122.0)),
        id_y=_as_pt_pair(fraw.get("id_y"), (108.0, 128.0)),
        field_x=float(fraw.get("field_x", 155.0)),
    )

    return ExamConfig(
        title=str(data.get("title", "Exam")),
        canvas_assignment=str(data.get("canvas_assignment", "Assignment")),
        points_possible=float(data.get("points_possible", 20.0)),
        num_questions=num_q,
        question_points=question_points,
        default_question_points=default_pts,
        answer_key_docx=ak.get("docx"),
        answer_key_inline=inline_key,
        roster_glob=str(paths.get("roster_glob", "*.csv")),
        scan_globs=list(scan_globs),
        work_dir=work_dir,
        output_dir=output_dir,
        form=form,
        raw=data,
    )


def detect_form_from_page(page) -> dict:
    """Best-effort detection of a printed Q/Answer grid on a scanned page.

    Returns a dict suitable for the ``form`` section of exam.json. Used by
    ``python -m grader.detect_form`` when setting up a new exam.
    """
    words = page.get_text("words")
    # Printed question numbers: short digit tokens in the body of the sheet.
    q_toks = []
    for w in words:
        x0, y0, x1, y1, text = w[0], w[1], w[2], w[3], w[4]
        t = text.strip()
        if t.isdigit() and 1 <= int(t) <= 300 and (x1 - x0) < 18:
            cy = (y0 + y1) / 2.0
            if 140 < cy < 620:
                q_toks.append((int(t), x0, x1, cy))
    if len(q_toks) < 10:
        return {}

    # Cluster question-number x-centers into columns.
    xs = sorted(( (t[1] + t[2]) / 2.0, t) for t in q_toks)
    clusters: list[list[tuple]] = []
    for xc, tok in xs:
        if not clusters or xc - clusters[-1][-1][0] > 40:
            clusters.append([(xc, tok)])
        else:
            clusters[-1].append((xc, tok))

    cols = []
    for cl in clusters:
        if len(cl) < 4:
            continue
        xcs = [c[0] for c in cl]
        q0 = min(c[1][0] for c in cl)
        q1 = max(c[1][0] for c in cl)
        x_min = min(c[1][1] for c in cl)
        x_max = max(c[1][2] for c in cl)
        # Answer box sits to the right of the Q number column.
        ans_x0 = x_max + 8
        ans_x1 = ans_x0 + 55
        cols.append(
            {
                "q_x": [round(x_min - 4, 1), round(x_max + 4, 1)],
                "ans_x": [round(ans_x0, 1), round(ans_x1, 1)],
                "q_start": q0,
                "q_end": q1,
            }
        )

    if not cols:
        return {}

    # Row pitch from the densest column
    best = max(clusters, key=len)
    ys = sorted(c[1][3] for c in best)
    diffs = [ys[i + 1] - ys[i] for i in range(len(ys) - 1)]
    diffs = [d for d in diffs if 8 < d < 40]
    row_dy = round(sum(diffs) / len(diffs), 2) if diffs else 18.7
    row_y0 = round(ys[0] - row_dy * 0.35, 1)
    n_rows = int(round((ys[-1] - ys[0]) / row_dy)) + 1 if ys else 17

    return {
        "page_width": float(page.rect.width),
        "page_height": float(page.rect.height),
        "row_y0": row_y0,
        "row_dy": row_dy,
        "n_rows": n_rows,
        "cols": [
            {"q_x": c["q_x"], "ans_x": c["ans_x"], "q_start": c["q_start"]}
            for c in cols
        ],
        "detected_q_ranges": [(c["q_start"], c["q_end"]) for c in cols],
    }