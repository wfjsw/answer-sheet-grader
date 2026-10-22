"""Extract identity fields and MC answers from a scanned answer-sheet page.

Two independent signals are combined per answer cell:
  1. The PDF's embedded OCR text layer (noisy for handwriting, but fast).
  2. A shape classifier on a high-res crop of the answer box
     (see letter_clf) — better at single block capitals.

When they agree the guess is marked high-confidence; when only one fires
it is kept as a suggestion. The UI is the source of truth either way.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path

import pymupdf
from PIL import Image

from .config import (
    FIELD_X_MIN,
    FORM_COLS,
    FORM_N_ROWS,
    FORM_ROW_DY,
    FORM_ROW_Y0,
    ID_Y,
    NAME_Y,
    NUM_QUESTIONS,
)
from .letter_clf import classify_letter_image

# Map noisy OCR tokens onto A-D. Handwritten capitals are the target.
_LETTER_ALIASES = {
    "A": "A",
    "4": "A",
    "H": "A",  # sometimes a shaky A
    "B": "B",
    "8": "B",
    "6": "B",
    "13": "B",
    "R": "B",
    "P": "B",
    "C": "C",
    "L": "C",
    "E": "C",
    "(": "C",
    "<": "C",
    "(": "C",
    "O": "D",  # lowercase o / closed curve often is D
    "D": "D",
    "0": "D",
    "Q": "D",
}

# Extra heuristic map for common multi-char OCR debris of single letters.
_MULTI_ALIASES = {
    "T-": "C",
    "T2": "C",
    "TL": "C",
    "CF": "C",
    "C.": "C",
    "L.": "C",
    "BB": "B",
    "NB": "B",
    "13": "B",
    "TB": "B",
    "FT": "B",
    "R": "B",
    "R.": "B",
    "P)": "D",
    "1(]": "D",
    "{)": "D",
    "D.": "D",
    "FT": "B",
    "FT": "B",
    "0": "D",
    "O.": "D",
    "Q.": "D",
    "A.": "A",
    "A,": "A",
}


@dataclass
class PageExtract:
    file: str
    page_index: int  # 0-based within the file
    scan_order: int  # global 0-based across all PDFs (print order)
    ocr_name: str = ""
    ocr_id: str = ""
    answers_raw: dict[int, str] = field(default_factory=dict)  # q -> raw OCR token
    answers: dict[int, str] = field(default_factory=dict)  # q -> A/B/C/D or ""
    answers_shape: dict[int, str] = field(default_factory=dict)  # shape classifier
    answers_conf: dict[int, float] = field(default_factory=dict)  # 0..1
    answers_src: dict[int, str] = field(default_factory=dict)  # ocr|shape|both
    netid_guess: str = ""
    id_guess: str = ""
    # Content bbox in PDF points (cuts white scan margins). [x0, y0, x1, y1]
    crop_rect: tuple[float, float, float, float] = (0.0, 0.0, 612.0, 792.0)
    warnings: list[str] = field(default_factory=list)

    @property
    def page_id(self) -> str:
        return f"{self.file}::{self.page_index}"


_NETID_RE = re.compile(r"\b([a-zA-Z]{2,3}\d{5,7})\b")
_ID_RE = re.compile(r"\b(\d{4,6})\b")


def measure_content_rect(page, pad: float = 6.0) -> tuple[float, float, float, float]:
    """Measure the ink bounding box of a scanned page (PDF points).

    Used to trim white scan margins in the preview. Falls back to the full
    page rectangle when the page is blank or the scan is photo-only.
    """
    thumb = page.get_pixmap(matrix=pymupdf.Matrix(0.5, 0.5), alpha=False)
    im = Image.frombytes("RGB", (thumb.width, thumb.height), thumb.samples).convert("L")
    px = im.load()
    w, h = im.size
    min_x, min_y, max_x, max_y = w, h, -1, -1
    for y in range(h):
        for x in range(w):
            if px[x, y] < 240:
                if x < min_x:
                    min_x = x
                if y < min_y:
                    min_y = y
                if x > max_x:
                    max_x = x
                if y > max_y:
                    max_y = y
    if max_x < min_x:
        r = page.rect
        return (r.x0, r.y0, r.x1, r.y1)

    inv = 2.0  # thumbnail was 0.5x
    x0 = max(0.0, min_x * inv - pad)
    y0 = max(0.0, min_y * inv - pad)
    x1 = min(page.rect.width, (max_x + 1) * inv + pad)
    y1 = min(page.rect.height, (max_y + 1) * inv + pad)
    return (float(x0), float(y0), float(x1), float(y1))


def _norm_letter(token: str) -> str:
    """Best-effort mapping of an OCR token to A/B/C/D."""
    if not token:
        return ""
    t = token.strip().upper()
    t = t.replace(" ", "")
    if not t:
        return ""
    if t in _MULTI_ALIASES:
        return _MULTI_ALIASES[t]
    if len(t) == 1 and t in "ABCD":
        return t
    # Single-character debris
    if len(t) == 1:
        return _LETTER_ALIASES.get(t, "")
    # Collapse to first/last letter-ish char
    letters = [c for c in t if c.isalpha() or c in "()<>[]{}/\\|"]
    # Prefer an explicit A-D inside the token
    for c in t:
        if c in "ABCD":
            return c
    if t in _MULTI_ALIASES:
        return _MULTI_ALIASES[t]
    # Try common prefixes/suffixes
    for pref in ("B", "C", "D", "A"):
        if t.startswith(pref) and len(t) <= 3:
            return pref
    if letters:
        return _LETTER_ALIASES.get(letters[0], "") or _LETTER_ALIASES.get(letters[-1], "")
    return ""


def _words(page) -> list[tuple[float, float, float, float, str]]:
    out = []
    for w in page.get_text("words"):
        x0, y0, x1, y1, text = w[0], w[1], w[2], w[3], w[4]
        out.append((x0, y0, x1, y1, text))
    return out


def _in_y(x0, y0, x1, y1, band) -> bool:
    cy = (y0 + y1) / 2.0
    return band[0] <= cy <= band[1]


def _row_center(row: int) -> float:
    return FORM_ROW_Y0 + row * FORM_ROW_DY


def extract_page(page, file_name: str, page_index: int, scan_order: int) -> PageExtract:
    words = _words(page)
    pe = PageExtract(file=file_name, page_index=page_index, scan_order=scan_order)

    # --- Student name / ID ---
    name_toks = []
    id_toks = []
    for x0, y0, x1, y1, text in words:
        if x0 < FIELD_X_MIN:
            continue
        if _in_y(x0, y0, x1, y1, NAME_Y) and y1 <= ID_Y[1]:
            name_toks.append(text)
        elif _in_y(x0, y0, x1, y1, ID_Y):
            id_toks.append(text)
    # Fallback: anything after the labels
    if not name_toks:
        # Broader band just in case of slight skew
        for x0, y0, x1, y1, text in words:
            if x0 >= FIELD_X_MIN and 88 <= y0 <= 128:
                name_toks.append(text)
    pe.ocr_name = " ".join(name_toks).strip()
    pe.ocr_id = " ".join(id_toks).strip()

    # Measure white margins once per page (cached with the rest of extraction).
    pe.crop_rect = measure_content_rect(page)

    # Pull netid / student-id candidates out of the whole page text
    # (handwriting OCR often garbles the name field but occasionally
    # catches a printed-looking netid like "abc123456").
    full_text = page.get_text() or ""
    id_blob = pe.ocr_id.replace(" ", "").lower()
    netids = _NETID_RE.findall(full_text) + _NETID_RE.findall(pe.ocr_id) + _NETID_RE.findall(id_blob)
    # Prefer school-style netids: 2–3 letters + 5–7 digits
    school_like = [n for n in netids if re.fullmatch(r"[a-zA-Z]{2,3}\d{5,7}", n)]
    pe.netid_guess = (school_like[0] if school_like else (netids[0] if netids else "")).lower()
    ids = _ID_RE.findall(pe.ocr_id) + _ID_RE.findall(id_blob)
    # Drop course numbers (4-digit 3xxx–5xxx) and calendar years
    years = tuple(str(y) for y in range(2015, 2035))
    ids = [
        i
        for i in ids
        if not any(i.startswith(y) for y in years)
        and not (len(i) == 4 and 3000 <= int(i) <= 5999)
    ]
    pe.id_guess = ids[0] if ids else ""
    if not pe.id_guess and pe.netid_guess:
        pe.id_guess = pe.netid_guess

    # --- Answers ---
    # Bucket tokens by (column, row) using the fixed form grid.
    buckets: dict[tuple[int, int], list[str]] = {}
    qnum_hits: dict[tuple[int, int], list[str]] = {}

    for x0, y0, x1, y1, text in words:
        cy = (y0 + y1) / 2.0
        if cy < FORM_ROW_Y0 - 15 or cy > FORM_ROW_Y0 + FORM_N_ROWS * FORM_ROW_DY + 15:
            continue
        # Which column?
        col_idx = None
        for i, col in enumerate(FORM_COLS):
            ax = col["ans_x"]
            qx = col["q_x"]
            if ax[0] <= x0 <= ax[1] or ax[0] <= (x0 + x1) / 2 <= ax[1]:
                col_idx = i
                kind = "ans"
                break
            if qx[0] <= x0 <= qx[1] or qx[0] <= (x0 + x1) / 2 <= qx[1]:
                col_idx = i
                kind = "q"
                break
        if col_idx is None:
            continue
        # Which row?
        row = int(round((cy - FORM_ROW_Y0) / FORM_ROW_DY))
        if row < 0 or row >= FORM_N_ROWS:
            continue
        key = (col_idx, row)
        if kind == "ans":
            buckets.setdefault(key, []).append(text)
        else:
            qnum_hits.setdefault(key, []).append(text)

    # Build answers for Q1..Q68 from row/col template + shape classifier.
    for col_i, col in enumerate(FORM_COLS):
        q_start = col["q_start"]
        for row in range(FORM_N_ROWS):
            q = q_start + row
            if q > NUM_QUESTIONS:
                break
            raws = buckets.get((col_i, row), [])
            # Keep the most answer-like token (prefer single letters).
            raw = ""
            if raws:
                singles = [t for t in raws if len(t.strip()) == 1]
                if singles:
                    raw = singles[-1]
                else:
                    raw = " ".join(raws)
            pe.answers_raw[q] = raw
            ocr_letter = _norm_letter(raw)

            # Shape classifier on a high-res crop of this answer box.
            shape_letter, shape_conf = _classify_cell(page, col_i, row)

            # Combine
            if ocr_letter and shape_letter and ocr_letter == shape_letter:
                pe.answers[q] = ocr_letter
                pe.answers_conf[q] = min(1.0, 0.75 + shape_conf * 0.25)
                pe.answers_src[q] = "both"
            elif shape_letter and shape_conf >= 0.55:
                pe.answers[q] = shape_letter
                pe.answers_conf[q] = shape_conf * 0.75
                pe.answers_src[q] = "shape"
            elif ocr_letter:
                pe.answers[q] = ocr_letter
                pe.answers_conf[q] = 0.45
                pe.answers_src[q] = "ocr"
            elif shape_letter:
                pe.answers[q] = shape_letter
                pe.answers_conf[q] = shape_conf * 0.5
                pe.answers_src[q] = "shape"
            else:
                pe.answers[q] = ""
                pe.answers_conf[q] = 0.0
                pe.answers_src[q] = ""

            pe.answers_shape[q] = shape_letter
            if raw and not pe.answers[q]:
                pe.warnings.append(f"Q{q}: unparsed OCR {raw!r}")

    missing = [q for q in range(1, NUM_QUESTIONS + 1) if not pe.answers.get(q)]
    if missing:
        pe.warnings.append(f"{len(missing)} questions have no confident letter")

    return pe


def _classify_cell(page, col_i: int, row: int) -> tuple[str, float]:
    """Crop one answer box and run the shape classifier."""
    try:
        col = FORM_COLS[col_i]
        x0, x1 = col["ans_x"]
        # inset to skip the printed table rules
        pad_x = 3.0
        y0 = FORM_ROW_Y0 + row * FORM_ROW_DY + 1.5
        y1 = y0 + FORM_ROW_DY - 3.0
        clip = pymupdf.Rect(x0 + pad_x, y0, x1 - 2.0, y1)
        clip = clip & page.rect
        if clip.is_empty or clip.width < 6 or clip.height < 6:
            return "", 0.0
        pix = page.get_pixmap(matrix=pymupdf.Matrix(6, 6), clip=clip, alpha=False)
        im = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
        guess = classify_letter_image(im)
        return guess.letter, guess.confidence
    except Exception:
        return "", 0.0


def extract_pdf_pages(pdf_path: Path, start_scan_order: int = 0, use_cache: bool = True) -> list[PageExtract]:
    cache_path = Path(__file__).resolve().parent.parent / "work" / "extract_cache.json"
    cache: dict = {}
    if use_cache and cache_path.exists():
        try:
            cache = json.loads(cache_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            cache = {}

    results: list[PageExtract] = []
    doc = pymupdf.open(pdf_path)
    changed = False
    try:
        for i in range(len(doc)):
            key = f"{pdf_path.name}::{i}"
            st = pdf_path.stat()
            stamp = f"{st.st_mtime_ns}:{st.st_size}"
            hit = cache.get(key)
            if use_cache and hit and hit.get("stamp") == stamp and "crop_rect" in hit:
                pe = PageExtract(**{k: hit[k] for k in hit if k != "stamp"})
                # rebuild dicts with int keys where needed
                pe.answers = {int(k): v for k, v in pe.answers.items()}
                pe.answers_raw = {int(k): v for k, v in pe.answers_raw.items()}
                pe.answers_shape = {int(k): v for k, v in (pe.answers_shape or {}).items()}
                pe.answers_conf = {int(k): float(v) for k, v in (pe.answers_conf or {}).items()}
                pe.answers_src = {int(k): v for k, v in (pe.answers_src or {}).items()}
                pe.crop_rect = tuple(hit["crop_rect"])
                pe.scan_order = start_scan_order + i
                results.append(pe)
                continue
            pe = extract_page(doc[i], pdf_path.name, i, start_scan_order + i)
            payload = {
                "file": pe.file,
                "page_index": pe.page_index,
                "scan_order": pe.scan_order,
                "ocr_name": pe.ocr_name,
                "ocr_id": pe.ocr_id,
                "answers_raw": {str(k): v for k, v in pe.answers_raw.items()},
                "answers": {str(k): v for k, v in pe.answers.items()},
                "answers_shape": {str(k): v for k, v in pe.answers_shape.items()},
                "answers_conf": {str(k): v for k, v in pe.answers_conf.items()},
                "answers_src": {str(k): v for k, v in pe.answers_src.items()},
                "netid_guess": pe.netid_guess,
                "id_guess": pe.id_guess,
                "crop_rect": list(pe.crop_rect),
                "warnings": pe.warnings,
                "stamp": stamp,
            }
            cache[key] = payload
            changed = True
            results.append(pe)
    finally:
        doc.close()

    if use_cache and changed:
        try:
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            cache_path.write_text(json.dumps(cache), encoding="utf-8")
        except OSError:
            pass
    return results


def extract_all(pdf_paths: list[Path], use_cache: bool = True) -> list[PageExtract]:
    all_pages: list[PageExtract] = []
    order = 0
    for p in pdf_paths:
        pages = extract_pdf_pages(p, start_scan_order=order, use_cache=use_cache)
        all_pages.extend(pages)
        order += len(pages)
    return all_pages


def extract_all(pdf_paths: list[Path]) -> list[PageExtract]:
    all_pages: list[PageExtract] = []
    order = 0
    for p in pdf_paths:
        pages = extract_pdf_pages(p, start_scan_order=order)
        all_pages.extend(pages)
        order += len(pages)
    return all_pages