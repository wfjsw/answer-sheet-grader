# answer-sheet-grader

Local web tool for grading **scanned multiple-choice answer sheets**:

1. **Match** scan pages to students (searchable roster — name, SIS/netID, ID)
2. **Grade** with a keyboard-first UI (`A` `B` `C` `D`, jump to blanks, etc.)
3. **Export** a Canvas gradebook CSV
4. **Print** a one-page feedback report per student (name, netID, score, answers, missed questions with justifications) — for the **back** of the sheet, in scan order or reverse for duplex

No cloud services. Student data stays on your machine.

---

## Quick start

```bat
python -m venv venv
venv\Scripts\python.exe -m pip install -r requirements.txt
venv\Scripts\python.exe scripts\make_demo.py
run.bat
```

Open **http://127.0.0.1:5050/**

The demo builds fake students and blank-ish scans so you can click through the workflow before using a real exam.

### Requirements

- Python 3.10+
- Windows / macOS / Linux

Optional: `easyocr` improves some handwriting recognition (`pip install easyocr`). The built-in shape classifier works without it.

---

## Workflow

1. Drop a **Canvas gradebook CSV**, **scanned PDFs**, and (optionally) an **answer-key DOCX** into the project folder (or point `exam.json` at them).
2. Start the app (`run.bat` or `python -m grader`).
3. Walk the page list (scan order). For each page press **`S`**, type a name or netID, **`Enter`**.
4. Enter answers. **`P`** prefills machine guesses (review them). **`Tab`** jumps to blanks.
5. Press **`E`** and download:
   - `canvas_import.csv` → Canvas → Grades → Import
   - `graded_feedback.pdf` → print on the back of the answer sheets

State is saved continuously to `work/state.json`.

---

## Keyboard shortcuts

Press **`?`** in the app for the full list.

| Keys | Action |
|------|--------|
| `A` `B` `C` `D` or `1`–`4` | Set answer (auto-advance) |
| `0` `⌫` `Del` `Space` `-` | Clear cell |
| `Tab` / `Shift+Tab` | Next / previous **blank** |
| `N` / `W` | Next blank / next wrong |
| `↑` `↓` `J`/`K` `H`/`L` | Move between questions |
| `PgUp` `PgDn` `[` `]` | Previous / next scan page |
| `S` | Search roster → assign |
| `U` / `X` | Unassign / clear page |
| `P` | Prefill from OCR |
| `O` / `V` | Scan overlay / answer-key highlight |
| `E` | Export |

`A`/`B`/`C`/`D` are **always** answers — never overridden by commands.

---

## Configure any exam (`exam.json`)

Everything exam-specific lives in **`exam.json`**. Copy `exam.example.json` and edit:

| Key | Meaning |
|-----|---------|
| `title` | Shown in the app |
| `canvas_assignment` | Canvas column header, e.g. `Midterm Exam (123456)` |
| `points_possible` | Total points in Canvas |
| `question_points` | Per-question weights; `"default"` covers the rest |
| `num_questions` | Question count |
| `answer_key.inline` | `{ "1": "A", … }` literal key |
| `answer_key.docx` | Instructor DOCX with an answer table + optional justifications |
| `paths.*` | Roster glob, scan globs, work/output dirs |
| `form.*` | Printed answer-sheet grid (columns, row pitch, name/ID fields) |

**Point weights** (example: 68 questions, 20 points):

```json
"question_points": { "1": 0.39, "2": 0.39, "3": 0.37, "default": 0.29 }
```

**Detect the form grid** from a scan (printed Q / Answer columns):

```bat
venv\Scripts\python.exe -m grader.detect_form path\to\scan.pdf
venv\Scripts\python.exe -m grader.detect_form path\to\scan.pdf --write
```

**Alternate config** without replacing `exam.json`:

```bat
set EXAM_CONFIG=exams\final.json
venv\Scripts\python.exe -m grader
```

---

## Inputs

| Input | Format |
|-------|--------|
| Roster | Canvas gradebook export (`Student`, `ID`, `SIS Login ID`, `Section`, …) |
| Scans | PDF, one student per page (or continuous pages in scan order) |
| Answer key | `inline` in `exam.json`, or DOCX with `Q` / letter / optional justification rows |

Students are shown as **`Name (netid)`**. Search accepts name, SIS/netID, or numeric ID.

---

## Outputs

| File | Use |
|------|-----|
| `output/canvas_import.csv` | Upload to Canvas (Student, ID, SIS, Section, score) |
| `output/canvas_grades.csv` | Full gradebook columns with the score filled in |
| `output/scan_audit.csv` | One row per scan page (optional audit) |
| `output/graded_feedback.pdf` | One report page per scan — **no scan image** — name, netID, score, **ANSWERS** (5 per group, one line), missed questions + justifications |

**Feedback PDF order** (top bar): *Scan order* (1→N) or *Reverse* for duplex printing onto the back of a stack.

Report layout is grayscale and auto-shrinks so a full miss list still fits **one page** per student.

---

## Answer prefill (optional)

**`P`** copies letter guesses into the grid from:

1. The PDF’s embedded OCR text layer (fast, noisy on handwriting)
2. A shape classifier on each answer box (holes + stroke profiles — no extra install)

Low-confidence cells are marked. **Always review before export.** The overlay (**`O`**) shows the **recorded** answer in green once you grade it, otherwise the **recognized** guess (blue/amber). White scan margins are trimmed automatically.

---

## Privacy / release checklist

- [x] No real student names, IDs, emails, or scans in this tree
- [x] No real exam answer key in source
- [x] `work/`, `output/`, `*.csv`, `*.pdf` ignored by git
- [x] Demo data is synthetic (`scripts/make_demo.py`)

**Before you publish a fork:** never commit `*Grades*.csv`, scan PDFs, `work/state.json`, or `output/`. `exam.json` with a real key should stay local.

---

## Project layout

```
answer-sheet-grader/
  exam.json            # this exam (edit per course)
  exam.example.json    # template
  requirements.txt
  run.bat
  scripts/make_demo.py # synthetic sample data
  grader/              # app (Flask UI, extract, grade, export)
  examples/            # generated demo roster + scans
  work/                # local state + extract cache (gitignored)
  output/              # exports (gitignored)
```

---

## License

MIT — see [LICENSE](LICENSE). Use at your own risk; verify every grade before posting.