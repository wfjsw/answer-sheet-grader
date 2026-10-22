"""Grade calculation against the answer key.

Point weights come from ``exam.json`` (``question_points``). Default weight
for questions not listed there is ``question_points.default``.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .config import EXAM, POINTS_POSSIBLE
from .exam_config import load_exam_config


@dataclass
class GradeResult:
    correct: int
    wrong: int
    blank: int
    total: int
    points: float
    points_possible: float
    earned_by_q: dict[int, float] = field(default_factory=dict)
    per_question: dict[int, dict] = field(default_factory=dict)

    @property
    def percent(self) -> float:
        if self.points_possible <= 0:
            return 0.0
        return 100.0 * self.points / self.points_possible


def points_for(q: int) -> float:
    return EXAM.points_for(q)


# Backwards-compatible alias used by the web UI bootstrap.
QUESTION_POINTS: dict[int, float] = {
    q: EXAM.points_for(q) for q in range(1, EXAM.num_questions + 1)
}


def grade_answers(
    answers: dict[int, str],
    key: dict[int, str],
    points_possible: float | None = None,
) -> GradeResult:
    """Score answers with the per-question weights from exam.json.

    Wrong / blank = 0 for that question (no negative penalty).
    """
    total = len(key)
    correct = wrong = blank = 0
    points = 0.0
    earned_by_q: dict[int, float] = {}
    per: dict[int, dict] = {}

    for q, expected in key.items():
        w = points_for(q)
        got = (answers.get(q) or "").strip().upper()
        if not got:
            blank += 1
            status = "blank"
            earned = 0.0
        elif got == expected:
            correct += 1
            status = "correct"
            earned = w
        else:
            wrong += 1
            status = "wrong"
            earned = 0.0
        points += earned
        earned_by_q[q] = earned
        per[q] = {
            "got": got,
            "expected": expected,
            "status": status,
            "weight": w,
            "earned": earned,
        }

    pts_possible = POINTS_POSSIBLE if points_possible is None else float(points_possible)
    return GradeResult(
        correct=correct,
        wrong=wrong,
        blank=blank,
        total=total,
        points=round(points, 2),
        points_possible=pts_possible,
        earned_by_q=earned_by_q,
        per_question=per,
    )