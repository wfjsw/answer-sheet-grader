"""Detect the printed answer-sheet grid from a scan and write it to exam.json.

Usage (from the project folder):

    venv\\Scripts\\python.exe -m grader.detect_form [path/to/scan.pdf] [--write]

Without ``--write`` the detected form is printed. With ``--write`` the
``form`` section of exam.json is updated (other keys are preserved).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pymupdf

from . import config
from .exam_config import detect_form_from_page


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    write = "--write" in argv
    args = [a for a in argv if not a.startswith("--")]

    pdf = Path(args[0]) if args else (config.find_scan_pdfs() or [None])[0]
    if pdf is None or not Path(pdf).exists():
        print("No scan PDF found. Pass a path: python -m grader.detect_form scan.pdf")
        return 1

    doc = pymupdf.open(pdf)
    try:
        # Use the first page that has a reasonable number of Q tokens.
        form = {}
        for i in range(min(3, len(doc))):
            form = detect_form_from_page(doc[i])
            if form:
                print(f"Detected form from {pdf.name} page {i + 1}")
                break
    finally:
        doc.close()

    if not form:
        print("Could not detect a Q/Answer grid. Check that the scan has printed question numbers.")
        return 2

    form.pop("detected_q_ranges", None)
    print(json.dumps(form, indent=2))

    if write:
        cfg_path = config.ROOT / "exam.json"
        data = {}
        if cfg_path.exists():
            data = json.loads(cfg_path.read_text(encoding="utf-8"))
        data.setdefault("form", {})
        # Keep identity fields if already configured; only refresh the grid.
        for k, v in form.items():
            data["form"][k] = v
        if "name_y" not in data["form"]:
            data["form"]["name_y"] = list(config.NAME_Y)
        if "id_y" not in data["form"]:
            data["form"]["id_y"] = list(config.ID_Y)
        if "field_x" not in data["form"]:
            data["form"]["field_x"] = config.FIELD_X_MIN
        cfg_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        print(f"\nWrote form grid to {cfg_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())