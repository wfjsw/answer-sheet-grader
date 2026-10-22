"""Generate synthetic demo data so the grader can be tried without real exams.

Creates:
  examples/demo_roster.csv     — 6 fake students (Canvas-style export)
  examples/demo_scans.pdf      — 4 blank-ish answer sheets with printed grid

Usage:
  python scripts/make_demo.py
"""

from __future__ import annotations

import csv
from pathlib import Path

import pymupdf

ROOT = Path(__file__).resolve().parent.parent
EX = ROOT / "examples"
EX.mkdir(exist_ok=True)

STUDENTS = [
    ("Alba, Nora", "10001", "naa00001@example.edu", "DEMO 001"),
    ("Berg, Otto", "10002", "obb00002@example.edu", "DEMO 001"),
    ("Cruz, Ida", "10003", "idc00003@example.edu", "DEMO 001"),
    ("Diaz, Luis", "10004", "lud00004@example.edu", "DEMO 001"),
    ("Elliott, Bea", "10005", "bee00005@example.edu", "DEMO 001"),
    ("Fox, Sam", "10006", "saf00006@example.edu", "DEMO 001"),
]

# toy answers written on the sheets (index 0..3 used in the PDF)
ANSWER_SETS = [
    list("ABCDA") * 4,          # 20 answers
    list("BCDBC") * 4,
    list("CCCCA") * 4,
    ["A"] * 15 + [""] * 5,
]


def write_roster() -> Path:
    path = EX / "demo_roster.csv"
    fields = [
        "Student", "ID", "SIS Login ID", "Section",
        "Quiz 1 (000000)", "Current Score", "Final Score",
    ]
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(fields)
        w.writerow(["    Points Possible", "", "", "", "10.00", "", ""])
        for name, sid, sis, sec in STUDENTS:
            w.writerow([name, sid, sis, sec, "", "", ""])
    return path


def draw_sheet(page, student_name: str, netid: str, answers: list[str]) -> None:
    ink = (0, 0, 0)
    page.insert_text((50, 50), "Sample Quiz — Answer Sheet", fontsize=14, fontname="hebo", color=ink)
    page.insert_text((50, 80), "Student Name", fontsize=9, fontname="helv", color=ink)
    page.insert_text((160, 80), student_name, fontsize=11, fontname="helv", color=ink)
    page.insert_text((50, 100), "Student ID", fontsize=9, fontname="helv", color=ink)
    page.insert_text((160, 100), netid, fontsize=11, fontname="helv", color=ink)

    cols = [(122, 1), (240, 6), (348, 11), (470, 16)]
    row_y0, dy, n_rows = 182.0, 18.7, 5
    for ans_x, q_start in cols:
        for row in range(n_rows):
            q = q_start + row
            if q > 20:
                break
            y = row_y0 + row * dy + 12
            page.insert_text((ans_x - 30, y), str(q), fontsize=10, fontname="helv", color=ink)
            page.draw_rect(
                pymupdf.Rect(ans_x, y - 12, ans_x + 50, y + 4),
                color=(0.2, 0.2, 0.2),
                width=0.6,
            )
            letter = answers[q - 1] if q - 1 < len(answers) else ""
            if letter:
                page.insert_text((ans_x + 18, y), letter, fontsize=12, fontname="hebo", color=ink)


def write_scans() -> Path:
    path = EX / "demo_scans.pdf"
    doc = pymupdf.open()
    for i, (name, sid, sis, _sec) in enumerate(STUDENTS[:4]):
        page = doc.new_page(width=612, height=792)
        draw_sheet(page, name, sis.split("@")[0], ANSWER_SETS[i])
    doc.save(path)
    doc.close()
    return path


if __name__ == "__main__":
    r = write_roster()
    s = write_scans()
    print(f"Wrote {r}")
    print(f"Wrote {s} (4 pages)")
    print("Now run:  python -m grader   and open http://127.0.0.1:5050/")