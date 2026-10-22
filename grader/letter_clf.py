"""Shape-based classifier for a single handwritten MC letter (A/B/C/D).

No external OCR model required. Uses ink geometry on a high-res crop of one
answer box: hole count, side openings, and left/right stroke density.

Works well on the blocky capitals students write on this exam form.
"""

from __future__ import annotations

from dataclasses import dataclass

from PIL import Image


@dataclass
class LetterGuess:
    letter: str  # A/B/C/D or "" if too uncertain
    confidence: float  # 0..1
    features: dict


def _to_ink_mask(im: Image.Image, thresh: int | None = None) -> list[list[int]]:
    """Return a small binary mask (1=ink) as a list of rows."""
    g = im.convert("L")
    # Otsu-ish: use a percentile of the dark tail, fallback 160
    hist = g.histogram()
    total = sum(hist) or 1
    if thresh is None:
        # default: anything clearly darker than paper
        # paper on these scans is ~220-255 after autocontrast; ink is < 140
        thresh = 150
    w, h = g.size
    px = g.load()
    mask = [[0] * w for _ in range(h)]
    for y in range(h):
        for x in range(w):
            mask[y][x] = 1 if px[x, y] < thresh else 0
    return mask


def _remove_long_lines(mask: list[list[int]]) -> list[list[int]]:
    """Drop near-full ink rows/cols (form rules) and tiny noise specks."""
    h = len(mask)
    w = len(mask[0])
    if h < 4 or w < 4:
        return mask
    # A row/col is a "rule" if ink covers > 70% of its length
    row_rule = [1 if sum(row) > 0.70 * w else 0 for row in mask]
    col_ink = [sum(mask[y][x] for y in range(h)) for x in range(w)]
    col_rule = [1 if col_ink[x] > 0.70 * h else 0 for x in range(w)]

    out = []
    for y in range(h):
        if row_rule[y]:
            out.append([0] * w)
            continue
        row = [0 if col_rule[x] else mask[y][x] for x in range(w)]
        out.append(row)

    # Keep ink blobs that are large enough; drop speckles. Keep ALL big parts
    # (a broken 'B' can split into two components).
    seen = [[False] * w for _ in range(h)]
    keep = [[0] * w for _ in range(h)]
    min_keep = max(6, (h * w) // 80)
    for y in range(h):
        for x in range(w):
            if out[y][x] and not seen[y][x]:
                stack = [(y, x)]
                comp = []
                seen[y][x] = True
                while stack:
                    cy, cx = stack.pop()
                    comp.append((cy, cx))
                    for ny, nx in ((cy+1,cx),(cy-1,cx),(cy,cx+1),(cy,cx-1),
                                   (cy+1,cx+1),(cy+1,cx-1),(cy-1,cx+1),(cy-1,cx-1)):
                        if 0 <= ny < h and 0 <= nx < w and out[ny][nx] and not seen[ny][nx]:
                            seen[ny][nx] = True
                            stack.append((ny, nx))
                if len(comp) >= min_keep:
                    for yy, xx in comp:
                        keep[yy][xx] = 1
    return keep


def _crop_to_ink(mask: list[list[int]], pad: int = 1):
    ys = [y for y, row in enumerate(mask) if any(row)]
    if not ys:
        return None
    xs = [x for y, row in enumerate(mask) for x, v in enumerate(row) if v]
    y0, y1 = min(ys), max(ys)
    x0, x1 = min(xs), max(xs)
    if x1 - x0 < 2 or y1 - y0 < 2:
        return None
    y0 = max(0, y0 - pad)
    x0 = max(0, x0 - pad)
    y1 = min(len(mask) - 1, y1 + pad)
    x1 = min(len(mask[0]) - 1, x1 + pad)
    sub = [row[x0 : x1 + 1] for row in mask[y0 : y1 + 1]]
    return sub


def _downsample(mask: list[list[int]], max_side: int = 40) -> list[list[int]]:
    h = len(mask)
    w = len(mask[0])
    step = max(1, max(h, w) // max_side)
    out = []
    for y in range(0, h, step):
        row = []
        for x in range(0, w, step):
            # any ink in the block
            v = 0
            for yy in range(y, min(h, y + step)):
                for xx in range(x, min(w, x + step)):
                    if mask[yy][xx]:
                        v = 1
                        break
                if v:
                    break
            row.append(v)
        out.append(row)
    return out


def _morph_close(mask: list[list[int]]) -> list[list[int]]:
    """Fill 1-pixel gaps so B/D/A holes are fully enclosed."""
    h = len(mask)
    w = len(mask[0])
    out = [row[:] for row in mask]
    for y in range(h):
        for x in range(w):
            if mask[y][x]:
                continue
            n = 0
            for ny, nx in ((y+1,x),(y-1,x),(y,x+1),(y,x-1),
                           (y+1,x+1),(y+1,x-1),(y-1,x+1),(y-1,x-1)):
                if 0 <= ny < h and 0 <= nx < w and mask[ny][nx]:
                    n += 1
            if n >= 5:
                out[y][x] = 1
    return out


def _count_holes(mask: list[list[int]]) -> int:
    """Count background components not connected to the border."""
    h = len(mask)
    w = len(mask[0])
    seen = [[False] * w for _ in range(h)]

    def flood(sy, sx, want: int):
        stack = [(sy, sx)]
        comp = []
        while stack:
            y, x = stack.pop()
            if y < 0 or x < 0 or y >= h or x >= w:
                continue
            if seen[y][x] or mask[y][x] != want:
                continue
            seen[y][x] = True
            comp.append((y, x))
            stack.extend(((y + 1, x), (y - 1, x), (y, x + 1), (y, x - 1)))
        return comp

    holes = 0
    for y in range(h):
        for x in range(w):
            if seen[y][x] or mask[y][x] != 0:
                continue
            comp = flood(y, x, 0)
            # touches border?
            touches = any(
                py == 0 or px == 0 or py == h - 1 or px == w - 1 for py, px in comp
            )
            if not touches and len(comp) >= 2:
                holes += 1
    return holes


def _density_rows(mask: list[list[int]], x0_frac: float, x1_frac: float) -> float:
    h = len(mask)
    w = len(mask[0])
    x0 = int(w * x0_frac)
    x1 = max(x0 + 1, int(w * x1_frac))
    ink = tot = 0
    for row in mask:
        for x in range(x0, min(x1, w)):
            tot += 1
            ink += row[x]
    return ink / tot if tot else 0.0


def _right_gap_fraction(mask: list[list[int]]) -> float:
    """How open the right side is (high for C)."""
    h = len(mask)
    w = len(mask[0])
    if w < 3:
        return 0.0
    # For each row, distance from right edge of bbox to rightmost ink
    gaps = 0
    used = 0
    for row in mask:
        last = -1
        for x, v in enumerate(row):
            if v:
                last = x
        if last < 0:
            continue
        used += 1
        gaps += (w - 1 - last)
    return gaps / (used * w) if used else 0.0


def _left_stroke_density(mask: list[list[int]]) -> float:
    return _density_rows(mask, 0.0, 0.28)


def _right_stroke_density(mask: list[list[int]]) -> float:
    return _density_rows(mask, 0.72, 1.0)


def _top_bottom_balance(mask: list[list[int]]) -> tuple[float, float]:
    h = len(mask)
    mid = h // 2
    top = sum(sum(r) for r in mask[:mid]) / max(1, mid * len(mask[0]))
    bot = sum(sum(r) for r in mask[mid:]) / max(1, (h - mid) * len(mask[0]))
    return top, bot


def _band_profile(mask: list[list[int]], n_bands: int = 5) -> list[tuple[float, float, float]]:
    """For each horizontal band, (left_ink, center_ink, right_ink) densities."""
    h = len(mask)
    w = len(mask[0])
    if h == 0 or w == 0:
        return [(0.0, 0.0, 0.0)] * n_bands
    out = []
    for b in range(n_bands):
        y0 = (h * b) // n_bands
        y1 = (h * (b + 1)) // n_bands
        if y1 <= y0:
            y1 = y0 + 1
        lx = int(w * 0.32)
        cx1 = int(w * 0.68)
        def dens(x0, x1):
            ink = tot = 0
            for y in range(y0, min(y1, h)):
                for x in range(x0, min(x1, w)):
                    tot += 1
                    ink += mask[y][x]
            return ink / tot if tot else 0.0
        out.append((dens(0, lx), dens(lx, cx1), dens(cx1, w)))
    return out


def classify_letter_image(im: Image.Image) -> LetterGuess:
    """Classify a PIL image of one answer cell into A/B/C/D."""
    # Aggressive cleanup: autocontrast + threshold
    from PIL import ImageOps

    g = ImageOps.autocontrast(im.convert("L"))
    # Two thresholds and pick the one with a sane ink ratio
    best_mask = None
    for thresh in (140, 160, 120):
        mask = _to_ink_mask(g, thresh=thresh)
        ink = sum(sum(r) for r in mask)
        ratio = ink / (len(mask) * len(mask[0]))
        if 0.02 <= ratio <= 0.45:
            best_mask = mask
            break
        if best_mask is None or abs(ratio - 0.12) < abs(
            sum(sum(r) for r in best_mask) / (len(best_mask) * len(best_mask[0])) - 0.12
        ):
            best_mask = mask

    sub = _crop_to_ink(_remove_long_lines(best_mask)) if best_mask else None
    if not sub:
        return LetterGuess("", 0.0, {"error": "empty"})

    small = _downsample(sub, 48)
    holes = _count_holes(small)
    left = _left_stroke_density(small)
    right = _right_stroke_density(small)
    gap = _right_gap_fraction(small)
    top, bot = _top_bottom_balance(small)
    bands = _band_profile(small, 5)
    h = len(small)
    w = len(small[0])
    aspect = h / w if w else 1.0

    # Right-ink by band: B/D closed bowls vs C open middle vs A legs
    r0, r1, r2, r3, r4 = [b[2] for b in bands]
    l0, l1, l2, l3, l4 = [b[0] for b in bands]
    c0, c1, c2, c3, c4 = [b[1] for b in bands]
    right_mid_dip = ((r0 + r4) / 2) - r2  # high when middle-right is empty
    left_bar = (l0 + l1 + l2 + l3 + l4) / 5

    scores = {"A": 0.0, "B": 0.0, "C": 0.0, "D": 0.0}

    # --- row-profile signatures ---
    # B: left bar + right ink top&bottom + mid dip + often 2 holes
    b_like = 0.0
    b_like += 1.2 if right_mid_dip > 0.12 else 0.0
    b_like += 0.8 if r0 > 0.08 and r4 > 0.08 else 0.0
    b_like += 0.6 if left_bar > 0.16 else 0.0
    b_like += 1.4 if holes >= 2 else (0.6 if holes == 1 and right_mid_dip > 0.1 else 0.0)
    scores["B"] += b_like

    # C: open right in the middle, no/weak right bar, no left-heavy stem
    c_like = 0.0
    c_like += 1.4 if right_mid_dip > 0.16 else (0.5 if right_mid_dip > 0.08 else 0.0)
    c_like += 1.0 if right < 0.16 else 0.0
    c_like += 0.8 if holes == 0 else (-0.8 if holes >= 1 else 0.0)
    c_like += 0.5 if gap > 0.12 else 0.0
    # C usually has center ink at top and bottom of the arc
    c_like += 0.3 if (c0 + c4) > (c2) else 0.0
    scores["C"] += c_like

    # D: left bar + right ink throughout (no mid dip), one big hole
    d_like = 0.0
    d_like += 1.2 if right_mid_dip < 0.08 and (r2 > 0.10) else 0.0
    d_like += 1.0 if left_bar > 0.18 else 0.0
    d_like += 1.2 if holes == 1 else (0.4 if holes == 0 else -0.3)
    d_like += 0.6 if r0 > 0.10 and r2 > 0.10 and r4 > 0.10 else 0.0
    d_like += 0.5 if gap < 0.10 else 0.0
    scores["D"] += d_like

    # A: weak left bar, center peak at top (apex), legs at bottom (two bottom corners)
    a_like = 0.0
    a_like += 1.0 if left_bar < 0.16 else -0.5
    a_like += 0.8 if c0 > l0 and c0 > r0 else 0.0   # apex
    a_like += 0.8 if (l4 + r4) > r2 + 0.05 else 0.0  # feet
    a_like += 1.0 if holes == 1 and left_bar < 0.18 else 0.0
    a_like += 0.6 if (bot > top + 0.015) else 0.0
    a_like -= 0.8 if right_mid_dip > 0.15 and left_bar > 0.18 else 0.0  # that's B/C
    scores["A"] += a_like

    # --- hole overrides ---
    if holes >= 2:
        scores["B"] += 1.5
        scores["C"] -= 1.5
        scores["A"] -= 0.8
        scores["D"] -= 0.5
    elif holes == 1:
        scores["C"] -= 1.0
        if right_mid_dip > 0.12:
            scores["B"] += 0.8
            scores["A"] += 0.3
        else:
            scores["D"] += 0.8

    ranked = sorted(scores.items(), key=lambda kv: -kv[1])
    top_letter, top_score = ranked[0]
    second_score = ranked[1][1]
    margin = top_score - second_score

    conf = max(0.0, min(1.0, 0.32 + margin * 0.22 + min(max(top_score, 0), 3.5) * 0.08))
    feats = {
        "holes": holes,
        "left": round(left, 3),
        "right": round(right, 3),
        "gap": round(gap, 3),
        "aspect": round(aspect, 2),
        "right_mid_dip": round(right_mid_dip, 3),
        "left_bar": round(left_bar, 3),
        "bands_r": [round(r, 2) for r in (r0, r1, r2, r3, r4)],
        "scores": {k: round(v, 2) for k, v in scores.items()},
    }
    if top_score < 0.9 or margin < 0.20:
        return LetterGuess("", min(conf, 0.35), feats)
    return LetterGuess(top_letter, conf, feats)


def classify_letter_bytes(data: bytes) -> LetterGuess:
    import io

    return classify_letter_image(Image.open(io.BytesIO(data)))