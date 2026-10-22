"""Export Canvas gradebook CSV and a print-ready feedback PDF."""

from __future__ import annotations

import csv
import io
from pathlib import Path

import pymupdf

from .config import ASSIGNMENT_HEADER, NUM_QUESTIONS
from .scoring import grade_answers


# ---------------------------------------------------------------------------
# Canvas CSV
# ---------------------------------------------------------------------------

def canvas_csv(
    roster_rows: list[dict],
    grades_by_student_id: dict[str, float],
    assignment_header: str = ASSIGNMENT_HEADER,
    points_possible: float = 20.0,
) -> str:
    """Build a Canvas-importable CSV (full gradebook columns).

    Preserves the roster export columns and fills in the midterm score column.
    Students without a graded scan keep a blank score (Canvas leaves them empty).
    The "Points Possible" summary row is kept and the midterm points filled in.
    """
    if not roster_rows:
        return "Student,ID,SIS Login ID,Section," + assignment_header + "\n"

    fieldnames = list(roster_rows[0].keys())
    if assignment_header not in fieldnames:
        fieldnames.append(assignment_header)

    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=fieldnames, lineterminator="\n")
    writer.writeheader()
    for row in roster_rows:
        out = dict(row)
        student_name = (row.get("Student") or "").strip()
        sid = (row.get("ID") or "").strip()

        if "Points Possible" in student_name:
            out[assignment_header] = f"{points_possible:.2f}"
        elif sid in grades_by_student_id:
            out[assignment_header] = f"{grades_by_student_id[sid]:.2f}"
        else:
            out[assignment_header] = ""
        writer.writerow(out)
    return buf.getvalue()


def canvas_import_csv(
    roster_rows: list[dict],
    grades_by_student_id: dict[str, float],
    assignment_header: str = ASSIGNMENT_HEADER,
    points_possible: float = 20.0,
) -> str:
    """Minimal Canvas import: Student / ID / SIS / Section + one score column.

    This is the cleanest upload. Rows without a grade are omitted so Canvas
    does not clear an existing score.
    """
    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator="\n")
    writer.writerow(["Student", "ID", "SIS Login ID", "Section", assignment_header])
    writer.writerow(["Points Possible", "", "", "", f"{points_possible:.2f}"])
    for row in roster_rows:
        sid = (row.get("ID") or "").strip()
        if sid not in grades_by_student_id:
            continue
        writer.writerow(
            [
                row.get("Student", ""),
                sid,
                row.get("SIS Login ID", ""),
                row.get("Section", ""),
                f"{grades_by_student_id[sid]:.2f}",
            ]
        )
    return buf.getvalue()


def simple_scores_csv(
    page_records: list[dict],
    points_possible: float,
) -> str:
    """One row per scanned page (scan order) — handy as an audit trail."""
    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator="\n")
    writer.writerow(
        [
            "scan_order",
            "source_file",
            "page",
            "student",
            "sis_id",
            "student_id",
            "correct",
            "wrong",
            "blank",
            "score",
            "points_possible",
        ]
    )
    for rec in page_records:
        writer.writerow(
            [
                rec["scan_order"] + 1,
                rec["file"],
                rec["page_index"] + 1,
                rec.get("student_name") or "",
                rec.get("sis_id") or "",
                rec.get("student_id") or "",
                rec.get("correct", ""),
                rec.get("wrong", ""),
                rec.get("blank", ""),
                f"{float(rec.get('points') or 0.0):.2f}",
                f"{points_possible:.2f}",
            ]
        )
    return buf.getvalue()


# ---------------------------------------------------------------------------
# Feedback PDF — standalone back-side report (no scan image)
# ---------------------------------------------------------------------------
# One page per student, in scan order, so the stack can be printed onto the
# back of the answer sheets. Includes name, netid, grade, and every missed
# question with the instructor justification.

_PAGE_W, _PAGE_H = 612.0, 792.0  # US Letter
_M = 42.0  # margin


def _netid_from_sis(sis_login: str) -> str:
    login = (sis_login or "").split("@", 1)[0].strip()
    return login


def _wrap_lines(text: str, width_chars: int) -> list[str]:
    """Greedy wrap for body copy. Uses character estimate ~0.5*fontsize width."""
    if not text:
        return []
    words = text.split()
    lines: list[str] = []
    cur = ""
    for w in words:
        trial = w if not cur else cur + " " + w
        if len(trial) <= width_chars:
            cur = trial
        else:
            if cur:
                lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines


def _draw_report_page(
    page,
    student_name: str,
    netid: str,
    grade,
    key: dict[int, str],
    justifications: dict[int, str],
) -> None:
    """Draw one grade report that always fits a single page.

    Font size and column count shrink automatically so a full 68-miss report
    still lands on one sheet (meant for the back of the answer paper).
    """
    ink = (0.12, 0.12, 0.12)
    muted = (0.38, 0.38, 0.38)
    rule = (0.75, 0.75, 0.75)
    # Grayscale only — print-friendly for the back of the answer sheet.
    good = ink
    bad = ink

    # ---- identity: name and netid on one line ----
    y = _M + 14
    page.insert_text((_M, y), "Name", fontsize=8, fontname="hebo", color=muted)
    page.insert_text(
        (_M + 42, y),
        student_name or "(unassigned)",
        fontsize=12,
        fontname="hebo",
        color=ink,
    )
    page.insert_text((_M + 320, y), "NetID", fontsize=8, fontname="hebo", color=muted)
    page.insert_text((_M + 368, y), netid or "—", fontsize=11, fontname="helv", color=ink)

    # ---- score line (no background fill) ----
    y += 22
    band = pymupdf.Rect(_M, y - 12, _PAGE_W - _M, y + 28)
    score_color = ink
    page.insert_text(
        (_M + 12, y + 12),
        f"{grade.points:.2f} / {grade.points_possible:.2f}",
        fontsize=20,
        fontname="hebo",
        color=score_color,
    )
    page.insert_text(
        (_M + 168, y + 12),
        f"{grade.percent:.1f}%",
        fontsize=14,
        fontname="hebo",
        color=ink,
    )
    page.insert_text(
        (_M + 240, y + 6),
        f"Correct {grade.correct}   Wrong {grade.wrong}   Blank {grade.blank}   (of {grade.total})",
        fontsize=9,
        fontname="helv",
        color=ink,
    )
    y = band.y1 + 16

    # ---- recognized answers: ONE line, 5 answers per group ----
    n_q = grade.total
    group = 5
    parts = []
    for q0 in range(1, n_q + 1, group):
        chunk = []
        for q in range(q0, min(q0 + group, n_q + 1)):
            got = (grade.per_question.get(q, {}).get("got") or "").strip().upper()
            chunk.append(got if got else "-")
        parts.append(" ".join(chunk))
    ans_line = "   ".join(parts)  # 5 letters per group, extra gap between groups

    page.insert_text((_M, y), "ANSWERS", fontsize=8, fontname="hebo", color=muted)
    y += 11
    page.draw_line(
        pymupdf.Point(_M, y),
        pymupdf.Point(_PAGE_W - _M, y),
        color=rule,
        width=0.5,
    )
    y += 10

    # Fit the single line across the usable page width.
    usable = _PAGE_W - 2 * _M
    # helv is ~0.50 * fontsize per char
    est_w = len(ans_line) * 0.50 * 8.5
    ans_fs = 8.5 if est_w <= usable else max(5.0, 8.5 * usable / max(est_w, 1.0))
    page.insert_text((_M, y), ans_line, fontsize=ans_fs, fontname="helv", color=ink)
    y += 14

    # ---- missed questions ----
    missed = [q for q in sorted(key) if grade.per_question.get(q, {}).get("status") != "correct"]
    page.insert_text(
        (_M, y),
        "MISSED QUESTIONS",
        fontsize=8,
        fontname="hebo",
        color=muted,
    )
    y += 8
    page.draw_line(
        pymupdf.Point(_M, y),
        pymupdf.Point(_PAGE_W - _M, y),
        color=rule,
        width=0.5,
    )
    y += 6

    if not missed:
        page.insert_text(
            (_M, y + 10),
            "Perfect score — no missed questions.",
            fontsize=10,
            fontname="helv",
            color=ink,
        )
        _draw_footer(page)
        return

    bottom = _PAGE_H - _M - 18
    avail_h = bottom - y

    # Prepare item texts (justification only — keep it short and dense).
    items = []
    for q in missed:
        info = grade.per_question[q]
        items.append(
            {
                "q": q,
                "got": info["got"] or "—",
                "exp": info["expected"],
                "status": info["status"],
                "w": info.get("weight", 0.29),
                "just": (justifications.get(q) or "").strip(),
            }
        )

    # Pick (cols, font, gap) so everything fits on this one page.
    # Try denser settings until the measured height fits.
    layouts = [
        # (n_cols, fs_q, fs_body, line_h, gap)
        (1, 8.5, 7.5, 9.2, 5.0),
        (2, 8.0, 7.0, 8.6, 4.5),
        (2, 7.5, 6.5, 8.0, 4.0),
        (2, 7.0, 6.0, 7.4, 3.5),
        (3, 7.0, 6.0, 7.2, 3.5),
        (3, 6.5, 5.5, 6.6, 3.0),
        (3, 6.0, 5.0, 6.0, 2.5),
        (4, 6.0, 5.0, 5.8, 2.5),
        (4, 5.5, 4.6, 5.3, 2.0),
        (4, 5.0, 4.2, 4.9, 1.8),
    ]

    def measure(n_cols, fs_q, fs_body, line_h, gap, truncate=False):
        gutter = 10.0 if n_cols <= 2 else 8.0
        col_w = (_PAGE_W - 2 * _M - gutter * (n_cols - 1)) / n_cols
        body_chars = max(18, int(col_w / (fs_body * 0.46)))
        head_chars = max(18, int(col_w / (fs_q * 0.46)))
        col_h = [0.0] * n_cols
        col_idx = 0
        rendered = []
        for it in items:
            just = it["just"]
            jlines = _wrap_lines(just, body_chars)
            if truncate and len(jlines) > 6:
                jlines = jlines[:6]
                if jlines:
                    jlines[-1] = jlines[-1] + " …"
            # header may need wrapping on very narrow columns
            head = f"Q{it['q']}  you:{it['got']}  key:{it['exp']}  [{it['w']}p]"
            if it["status"] == "blank":
                head += "  (blank)"
            hlines = _wrap_lines(head, head_chars)
            block_h = line_h * (len(hlines) + len(jlines)) + gap
            # place in shortest column
            c = min(range(n_cols), key=lambda i: col_h[i])
            if col_h[c] + block_h > avail_h and truncate:
                # shrink justification to 2 lines for the overflow tail
                jlines = _wrap_lines(just, body_chars)[:2]
                if jlines:
                    jlines[-1] = jlines[-1] + " …"
                block_h = line_h * (len(hlines) + len(jlines)) + gap
            col_h[c] += block_h
            rendered.append((c, hlines, jlines))
        total_needed = max(col_h) if col_h else 0.0
        fits = total_needed <= avail_h
        return fits, n_cols, fs_q, fs_body, line_h, gap, col_w, body_chars, rendered, total_needed

    chosen = None
    for spec in layouts:
        fits, n_cols, fs_q, fs_body, line_h, gap, col_w, body_chars, rendered, needed = measure(
            *spec, truncate=False
        )
        if fits:
            chosen = (n_cols, fs_q, fs_body, line_h, gap, col_w, rendered)
            break
    if chosen is None:
        # Last resort: densest layout + truncate justifications.
        spec = layouts[-1]
        fits, n_cols, fs_q, fs_body, line_h, gap, col_w, body_chars, rendered, needed = measure(
            *spec, truncate=True
        )
        chosen = (n_cols, fs_q, fs_body, line_h, gap, col_w, rendered)

    n_cols, fs_q, fs_body, line_h, gap, col_w, rendered = chosen
    gutter = 10.0 if n_cols <= 2 else 8.0
    col_x = [_M + i * (col_w + gutter) for i in range(n_cols)]
    col_y = [y + 4.0] * n_cols

    for c, hlines, jlines in rendered:
        x = col_x[c]
        yy = col_y[c]
        for j, hl in enumerate(hlines):
            page.insert_text(
                (x, yy),
                hl,
                fontsize=fs_q,
                fontname="hebo" if j == 0 else "helv",
                color=ink if j == 0 else muted,
            )
            yy += line_h
        for jl in jlines:
            page.insert_text((x, yy), jl, fontsize=fs_body, fontname="helv", color=ink)
            yy += line_h
        col_y[c] = yy + gap

    _draw_footer(page)


def _draw_footer(page) -> None:
    """No footer decoration (keeps the sheet clean for duplex printing)."""
    return


def build_feedback_pdf(
    pages_meta: list[dict],
    key: dict[int, str],
    points_possible: float,
    out_path: Path,
    justifications: dict[int, str] | None = None,
    pdf_order: str = "scan",
) -> Path:
    """One clean report page per scanned sheet.

    The original scan is NOT reproduced — this is meant to print on the back
    of the answer sheet. Each page has student name, netid, grade, and the
    missed questions with justifications. Content is auto-shrunk so each
    student stays on exactly one page.

    ``pdf_order``:
      - "scan":    page 1 = scan page 1 (same order as the stack)
      - "reverse": page 1 = last scan page (for duplex printing onto the
                   back of a stack that is fed face-down / flipped)

    ``pages_meta`` items:
      file, page_index, scan_order, student_name, student_id, sis_login,
      section, answers: {q: letter}
    """
    just = justifications or {}
    ordered = sorted(
        pages_meta,
        key=lambda m: (m.get("scan_order", 0), m.get("file", ""), m.get("page_index", 0)),
    )
    if (pdf_order or "scan").lower() == "reverse":
        ordered = list(reversed(ordered))

    out = pymupdf.open()
    try:
        for meta in ordered:
            raw_ans = meta.get("answers") or {}
            answers: dict[int, str] = {}
            for q in range(1, NUM_QUESTIONS + 1):
                val = raw_ans.get(str(q)) or raw_ans.get(q) or ""
                answers[q] = str(val).upper() if val else ""
            grade = grade_answers(answers, key, points_possible)

            page = out.new_page(width=_PAGE_W, height=_PAGE_H)
            _draw_report_page(
                page,
                student_name=meta.get("student_name") or "",
                netid=_netid_from_sis(meta.get("sis_login") or meta.get("sis_id") or ""),
                grade=grade,
                key=key,
                justifications=just,
            )

        out_path.parent.mkdir(parents=True, exist_ok=True)
        out.save(out_path)
    finally:
        try:
            out.close()
        except Exception:
            pass
    return out_path