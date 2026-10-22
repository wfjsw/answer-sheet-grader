"""Local web app: assign scan pages to students, grade, export."""

from __future__ import annotations

import io
import re
from pathlib import Path

import pymupdf
from flask import Flask, jsonify, request, send_file, send_from_directory

from . import config, export, extract, match, state as state_mod
from .answer_key import load_answer_key, load_key_and_justifications
from .scoring import POINTS_POSSIBLE, QUESTION_POINTS, grade_answers, points_for

app = Flask(__name__, static_folder="static", template_folder="templates")

# ---------------------------------------------------------------------------
# Session data loaded at startup
# ---------------------------------------------------------------------------

ROOT = config.ROOT
ROSTER_CSV = config.find_roster_csv(ROOT)
SCAN_PDFS = config.find_scan_pdfs(ROOT)
KEY_DOCX = config.find_answer_key_docx(ROOT)

ROSTER = config.load_roster(ROSTER_CSV)
ROSTER_BY_ID = {s.student_id: s for s in ROSTER}
ANSWER_KEY, JUSTIFICATIONS = load_key_and_justifications(KEY_DOCX)
PAGES = extract.extract_all(SCAN_PDFS)
PAGE_BY_ID = {p.page_id: p for p in PAGES}

# Full Canvas roster rows (for export)
import csv as _csv
with ROSTER_CSV.open(newline="", encoding="utf-8-sig") as _fh:
    ROSTER_ROWS = list(_csv.DictReader(_fh))

_state = state_mod.load_state()


def _save():
    state_mod.save_state(_state)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _assigned_map() -> dict[str, str]:
    """student_id -> page_id of the page currently assigned to them."""
    out = {}
    for pid, slot in (_state.get("pages") or {}).items():
        sid = slot.get("student_id")
        if sid:
            out[sid] = pid
    return out


def _page_payload(p: extract.PageExtract) -> dict:
    slot = state_mod.page_slot(_state, p.page_id)
    answers = state_mod.normalized_answers(slot, config.NUM_QUESTIONS)
    sid = slot.get("student_id")
    stu = ROSTER_BY_ID.get(sid) if sid else None
    grade = grade_answers(answers, ANSWER_KEY)
    return {
        "id": p.page_id,
        "file": p.file,
        "page_index": p.page_index,
        "scan_order": p.scan_order,
        "label": f"{p.scan_order + 1}. {p.file} p{p.page_index + 1}",
        "student_id": sid or None,
        "student_name": stu.name if stu else None,
        "student_sis": stu.sis_id if stu else None,
        "student_netid": stu.netid if stu else None,
        "student_label": stu.display if stu else None,
        "answers": {str(q): answers.get(q, "") for q in range(1, config.NUM_QUESTIONS + 1)},
        "ocr_name": p.ocr_name,
        "ocr_id": p.ocr_id,
        "netid_guess": p.netid_guess,
        "id_guess": p.id_guess,
        "crop_rect": list(p.crop_rect),
        "ocr_answers": {str(q): p.answers.get(q, "") for q in range(1, config.NUM_QUESTIONS + 1)},
        "ocr_raw": {str(q): p.answers_raw.get(q, "") for q in range(1, config.NUM_QUESTIONS + 1)},
        "ocr_conf": {str(q): round(p.answers_conf.get(q, 0.0), 2) for q in range(1, config.NUM_QUESTIONS + 1)},
        "ocr_src": {str(q): p.answers_src.get(q, "") for q in range(1, config.NUM_QUESTIONS + 1)},
        "shape_answers": {str(q): p.answers_shape.get(q, "") for q in range(1, config.NUM_QUESTIONS + 1)},
        "correct": grade.correct,
        "wrong": grade.wrong,
        "blank": grade.blank,
        "points": grade.points,
        "points_possible": grade.points_possible,
        "percent": round(grade.percent, 1),
        "notes": slot.get("notes") or "",
    }


def _find_page(page_id: str) -> extract.PageExtract:
    p = PAGE_BY_ID.get(page_id)
    if not p:
        raise KeyError(f"unknown page {page_id}")
    return p


def _grade_for_slot(slot: dict):
    answers = state_mod.normalized_answers(slot, config.NUM_QUESTIONS)
    return grade_answers(answers, ANSWER_KEY)


# ---------------------------------------------------------------------------
# Pages
# ---------------------------------------------------------------------------

@app.get("/")
def index():
    return send_from_directory(app.template_folder, "index.html")


@app.get("/static/<path:fname>")
def static_files(fname: str):
    return send_from_directory(app.static_folder, fname)


# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------

@app.get("/api/bootstrap")
def bootstrap():
    pages = [_page_payload(p) for p in PAGES]
    assigned_ids = {
        (s.get("student_id") or "")
        for s in (_state.get("pages") or {}).values()
        if s.get("student_id")
    }
    return jsonify(
        {
            "course_csv": ROSTER_CSV.name,
            "scan_files": [p.name for p in SCAN_PDFS],
            "key_source": KEY_DOCX.name if KEY_DOCX else "built-in",
            "num_questions": config.NUM_QUESTIONS,
            "points_possible": POINTS_POSSIBLE,
            "question_points": {str(q): points_for(q) for q in range(1, config.NUM_QUESTIONS + 1)},
            "title": config.EXAM.title,
            "assignment": config.ASSIGNMENT_HEADER,
            "form": {
                "page_width": config.EXAM.form.page_width,
                "page_height": config.EXAM.form.page_height,
                "row_y0": config.FORM_ROW_Y0,
                "row_dy": config.FORM_ROW_DY,
                "n_rows": config.FORM_N_ROWS,
                "cols": [
                    {"ans_x": list(c["ans_x"]), "q_start": c["q_start"]}
                    for c in config.FORM_COLS
                ],
                "name_y": list(config.NAME_Y),
                "id_y": list(config.ID_Y),
                "field_x": config.FIELD_X_MIN,
            },
            "key": {str(q): ANSWER_KEY.get(q, "") for q in range(1, config.NUM_QUESTIONS + 1)},
            "roster": [
                {
                    "student_id": s.student_id,
                    "name": s.name,
                    "sis_login": s.sis_login,
                    "sis_id": s.sis_id,
                    "netid": s.netid,
                    "section": s.section,
                    "display": s.display,
                    "assigned": s.student_id in assigned_ids,
                }
                for s in sorted(ROSTER, key=lambda z: z.name.lower())
            ],
            "pages": pages,
        }
    )


@app.post("/api/assign")
def assign():
    data = request.get_json(force=True, silent=True) or {}
    page_id = data.get("page_id") or ""
    student_id = data.get("student_id") or None
    if student_id in ("", None):
        student_id = None
    if student_id is not None and student_id not in ROSTER_BY_ID:
        return jsonify({"error": f"unknown student id {student_id}"}), 400
    try:
        page = _find_page(page_id)
    except KeyError as e:
        return jsonify({"error": str(e)}), 404

    slot = state_mod.page_slot(_state, page_id)
    slot["student_id"] = student_id
    _save()

    warning = None
    if student_id:
        amap = _assigned_map()
        others = [pid for sid, pid in amap.items() if sid == student_id and pid != page_id]
        if others:
            warning = f"{ROSTER_BY_ID[student_id].name} is also assigned to {others[0]}"

    return jsonify({"ok": True, "page": _page_payload(page), "warning": warning})


@app.post("/api/answers")
def set_answers():
    data = request.get_json(force=True, silent=True) or {}
    page_id = data.get("page_id") or ""
    answers = data.get("answers") or {}
    try:
        page = _find_page(page_id)
    except KeyError as e:
        return jsonify({"error": str(e)}), 404

    slot = state_mod.page_slot(_state, page_id)
    store = slot.setdefault("answers", {})
    # Accept {q: letter} with str or int keys; clear when empty.
    for k, v in answers.items():
        try:
            q = int(k)
        except (TypeError, ValueError):
            continue
        if not (1 <= q <= config.NUM_QUESTIONS):
            continue
        val = (str(v) if v is not None else "").strip().upper()
        if val == "" or val == "-":
            store[str(q)] = ""
        elif val in {"A", "B", "C", "D"}:
            store[str(q)] = val
    _save()
    return jsonify({"ok": True, "page": _page_payload(page)})


@app.post("/api/clear_page")
def clear_page():
    data = request.get_json(force=True, silent=True) or {}
    page_id = data.get("page_id") or ""
    try:
        page = _find_page(page_id)
    except KeyError as e:
        return jsonify({"error": str(e)}), 404
    slot = state_mod.page_slot(_state, page_id)
    slot["student_id"] = None
    slot["answers"] = {}
    slot["notes"] = ""
    _save()
    return jsonify({"ok": True, "page": _page_payload(page)})


@app.post("/api/prefill_ocr")
def prefill_ocr():
    """Optional: copy OCR guesses into the answer grid (teacher still confirms)."""
    data = request.get_json(force=True, silent=True) or {}
    page_id = data.get("page_id") or ""
    try:
        page = _find_page(page_id)
    except KeyError as e:
        return jsonify({"error": str(e)}), 404
    slot = state_mod.page_slot(_state, page_id)
    store = slot.setdefault("answers", {})
    for q in range(1, config.NUM_QUESTIONS + 1):
        guess = page.answers.get(q, "")
        if guess in {"A", "B", "C", "D"}:
            store[str(q)] = guess
    _save()
    return jsonify({"ok": True, "page": _page_payload(page)})


@app.get("/api/suggest")
def suggest():
    ocr_name = request.args.get("name") or ""
    ocr_id = request.args.get("id") or ""
    netid = request.args.get("netid") or ""
    blob = " ".join(x for x in (ocr_name, ocr_id, netid) if x)
    return jsonify({"suggestions": match.suggest_students(blob, ocr_id, ROSTER)})


def _crop_for_page(page_id: str) -> tuple[float, float, float, float]:
    """Content bbox (PDF points) from extraction cache — trims white margins."""
    pe = PAGE_BY_ID.get(page_id)
    if pe is not None and getattr(pe, "crop_rect", None):
        return tuple(pe.crop_rect)
    return (0.0, 0.0, 612.0, 792.0)


@app.get("/api/page/<path:page_id>/image")
def page_image(page_id: str):
    # page_id is "file.pdf::index"
    if "::" not in page_id:
        return jsonify({"error": "bad page id"}), 400
    file_part, idx_s = page_id.rsplit("::", 1)
    try:
        idx = int(idx_s)
    except ValueError:
        return jsonify({"error": "bad page index"}), 400
    path = ROOT / file_part
    if not path.exists():
        return jsonify({"error": f"missing {file_part}"}), 404

    scale = float(request.args.get("scale") or 1.6)
    scale = max(0.5, min(scale, 4.0))
    crop_on = request.args.get("crop", "1") != "0"
    rect = _crop_for_page(page_id) if crop_on else None

    doc = pymupdf.open(path)
    try:
        if idx < 0 or idx >= len(doc):
            return jsonify({"error": "page out of range"}), 404
        page = doc[idx]
        if rect is None:
            clip = page.rect
            rect = (clip.x0, clip.y0, clip.x1, clip.y1)
        else:
            clip = pymupdf.Rect(*rect) & page.rect
        pix = page.get_pixmap(matrix=pymupdf.Matrix(scale, scale), clip=clip, alpha=False)
    finally:
        doc.close()
    resp = send_file(io.BytesIO(pix.tobytes("png")), mimetype="image/png")
    # PDF-space crop rect so the overlay stays aligned after trimming.
    resp.headers["X-Crop-Rect"] = f"{rect[0]:.2f},{rect[1]:.2f},{rect[2]:.2f},{rect[3]:.2f}"
    resp.headers["Access-Control-Expose-Headers"] = "X-Crop-Rect"
    return resp


@app.get("/api/page/<path:page_id>/crop")
def page_crop(page_id: str):
    """Crop a region (PDF points) — used to zoom an answer box during review."""
    if "::" not in page_id:
        return jsonify({"error": "bad page id"}), 400
    file_part, idx_s = page_id.rsplit("::", 1)
    try:
        idx = int(idx_s)
    except ValueError:
        return jsonify({"error": "bad page index"}), 400
    path = ROOT / file_part
    x0 = float(request.args.get("x0") or 0)
    y0 = float(request.args.get("y0") or 0)
    x1 = float(request.args.get("x1") or 0)
    y1 = float(request.args.get("y1") or 0)
    scale = float(request.args.get("scale") or 3.0)
    doc = pymupdf.open(path)
    try:
        page = doc[idx]
        clip = pymupdf.Rect(x0, y0, x1, y1) & page.rect
        pix = page.get_pixmap(matrix=pymupdf.Matrix(scale, scale), clip=clip, alpha=False)
    finally:
        doc.close()
    return send_file(io.BytesIO(pix.tobytes("png")), mimetype="image/png")


@app.post("/api/export")
def do_export():
    """Write Canvas CSV + audit CSV + feedback PDF. Returns download names."""
    payload = request.get_json(force=True, silent=True) or {}
    pdf_order = (payload.get("pdf_order") or "scan").lower()
    if pdf_order not in {"scan", "reverse"}:
        pdf_order = "scan"
    # Collect page records in scan order
    page_records = []
    grades_by_student: dict[str, float] = {}
    pages_meta = []

    for p in PAGES:
        slot = state_mod.page_slot(_state, p.page_id)
        answers = state_mod.normalized_answers(slot, config.NUM_QUESTIONS)
        sid = slot.get("student_id")
        stu = ROSTER_BY_ID.get(sid) if sid else None
        grade = grade_answers(answers, ANSWER_KEY)
        rec = {
            "scan_order": p.scan_order,
            "file": p.file,
            "page_index": p.page_index,
            "student_name": stu.name if stu else "",
            "student_id": sid or "",
            "sis_id": stu.sis_id if stu else "",
            "correct": grade.correct,
            "wrong": grade.wrong,
            "blank": grade.blank,
            "points": grade.points,
        }
        page_records.append(rec)
        pages_meta.append(
            {
                "file": p.file,
                "page_index": p.page_index,
                "scan_order": p.scan_order,
                "student_name": stu.name if stu else "",
                "student_id": sid or "",
                "sis_login": stu.sis_login if stu else "",
                "sis_id": stu.sis_id if stu else "",
                "section": stu.section if stu else "",
                "answers": {str(q): answers.get(q, "") for q in range(1, config.NUM_QUESTIONS + 1)},
            }
        )
        if sid:
            # If the same student somehow has two scans, keep the higher score.
            prev = grades_by_student.get(sid)
            if prev is None or grade.points > prev:
                grades_by_student[sid] = grade.points

    out_dir = config.OUTPUT_DIR
    out_dir.mkdir(parents=True, exist_ok=True)

    canvas_name = "canvas_import.csv"
    canvas_full_name = "canvas_grades.csv"
    audit_name = "scan_audit.csv"
    pdf_name = "graded_feedback.pdf"

    (out_dir / canvas_name).write_text(
        export.canvas_import_csv(
            ROSTER_ROWS, grades_by_student, config.ASSIGNMENT_HEADER, POINTS_POSSIBLE
        ),
        encoding="utf-8",
    )
    (out_dir / canvas_full_name).write_text(
        export.canvas_csv(
            ROSTER_ROWS, grades_by_student, config.ASSIGNMENT_HEADER, POINTS_POSSIBLE
        ),
        encoding="utf-8",
    )
    (out_dir / audit_name).write_text(
        export.simple_scores_csv(page_records, POINTS_POSSIBLE),
        encoding="utf-8",
    )
    export.build_feedback_pdf(
        pages_meta,
        ANSWER_KEY,
        POINTS_POSSIBLE,
        out_dir / pdf_name,
        justifications=JUSTIFICATIONS,
        pdf_order=pdf_order,
    )

    return jsonify(
        {
            "ok": True,
            "files": [
                {"name": canvas_name, "url": f"/download/{canvas_name}", "kind": "canvas"},
                {"name": canvas_full_name, "url": f"/download/{canvas_full_name}", "kind": "canvas_full"},
                {"name": audit_name, "url": f"/download/{audit_name}", "kind": "audit"},
                {"name": pdf_name, "url": f"/download/{pdf_name}", "kind": "pdf"},
            ],
            "assigned_count": len(grades_by_student),
            "page_count": len(PAGES),
            "pdf_order": pdf_order,
        }
    )


@app.get("/download/<path:fname>")
def download(fname: str):
    return send_from_directory(config.OUTPUT_DIR, fname, as_attachment=True)


def main(host: str = "127.0.0.1", port: int = 5050) -> None:
    print("=" * 60)
    print(f"Grader — {config.EXAM.title}")
    print(f"  Config : exam.json  ({config.NUM_QUESTIONS} Q · {POINTS_POSSIBLE} pts · '{config.ASSIGNMENT_HEADER}')")
    print(f"  Roster : {ROSTER_CSV.name}  ({len(ROSTER)} students)")
    print(f"  Scans  : {', '.join(p.name for p in SCAN_PDFS)}  ({len(PAGES)} pages)")
    print(f"  Key    : {KEY_DOCX.name if KEY_DOCX else 'exam.json / built-in'}  ({len(ANSWER_KEY)} questions)")
    print(f"  State  : {config.STATE_PATH}")
    print(f"  Output : {config.OUTPUT_DIR}")
    print(f"Open   : http://{host}:{port}/")
    print("=" * 60)
    app.run(host=host, port=port, debug=False)


if __name__ == "__main__":
    main()