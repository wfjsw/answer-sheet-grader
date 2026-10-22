/* Midterm Grader — keyboard-first UI */
"use strict";

const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => Array.from(document.querySelectorAll(sel));

const LETTERS = ["A", "B", "C", "D"];

// Answer-sheet geometry in PDF points (matches grader/config.py)
const FORM = {
  W: 612,
  H: 792,
  cols: [
    { ans_x: [122, 175], q_start: 1 },
    { ans_x: [240, 290], q_start: 18 },
    { ans_x: [348, 410], q_start: 35 },
    { ans_x: [470, 530], q_start: 52 },
  ],
  row_y0: 182,
  row_dy: 18.7,
  n_rows: 17,
  name_y: [93, 122],
  id_y: [108, 128],
  field_x: 155,
};

const S = {
  pages: [],
  roster: [],
  key: {},
  questionPoints: {},
  numQuestions: 68,
  pointsPossible: 20,
  currentPageId: null,
  currentQ: 1,
  zoom: 1.6,
  autoAdvance: true,
  showKey: true,
  assignedSet: new Set(),
  pageFilter: "",
  studentCursor: -1,
  studentMatches: [],
  busy: false,
  crop: { x0: 0, y0: 0, x1: 612, y1: 792 },
};

/* ------------------------------------------------------------------ */
/* boot                                                                */
/* ------------------------------------------------------------------ */

async function api(path, opts = {}) {
  const res = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...opts,
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.error || res.statusText);
  return data;
}

async function boot() {
  const data = await api("/api/bootstrap");
  S.pages = data.pages;
  S.roster = data.roster;
  S.key = data.key;
  S.questionPoints = data.question_points;
  S.numQuestions = data.num_questions;
  S.pointsPossible = data.points_possible;
  if (data.form) {
    FORM.W = data.form.page_width || FORM.W;
    FORM.H = data.form.page_height || FORM.H;
    FORM.cols = (data.form.cols || FORM.cols).map((c) => ({
      ans_x: c.ans_x || [122, 175],
      q_start: c.q_start || 1,
    }));
    FORM.row_y0 = data.form.row_y0 ?? FORM.row_y0;
    FORM.row_dy = data.form.row_dy ?? FORM.row_dy;
    FORM.n_rows = data.form.n_rows ?? FORM.n_rows;
    FORM.name_y = data.form.name_y || FORM.name_y;
    FORM.id_y = data.form.id_y || FORM.id_y;
    FORM.field_x = data.form.field_x ?? FORM.field_x;
    S.crop = { x0: 0, y0: 0, x1: FORM.W, y1: FORM.H };
  }
  if (data.title) document.title = data.title + " · Grader";

  $("#boot-info").textContent =
    `${data.course_csv}  ·  ${data.scan_files.join(", ")}  ·  key: ${data.key_source}  ·  ` +
    `${S.pointsPossible} pts / ${S.numQuestions} questions`;

  renderPageList();
  if (S.pages.length) selectPage(S.pages[0].id);
  updateProgress();
  bindUI();
  toast("Ready — press ? for shortcuts");
}

/* ------------------------------------------------------------------ */
/* render                                                              */
/* ------------------------------------------------------------------ */

function pageById(id) {
  return S.pages.find((p) => p.id === id) || null;
}

function refreshPageInList(page) {
  const i = S.pages.findIndex((p) => p.id === page.id);
  if (i >= 0) S.pages[i] = page;
}

function renderPageList() {
  const ul = $("#page-list");
  ul.innerHTML = "";
  const q = S.pageFilter.trim().toLowerCase();
  for (const p of S.pages) {
    const hay = `${p.label} ${p.student_name || ""} ${p.student_id || ""} ${p.ocr_name}`.toLowerCase();
    if (q && !hay.includes(q)) continue;

    const li = document.createElement("li");
    li.className = "page-item" + (p.id === S.currentPageId ? " active" : "");
    li.dataset.id = p.id;

    const scoreTag = p.points != null
      ? `<span class="tag score">${p.points.toFixed(2)}</span>`
      : "";
    const statusTag = p.student_id
      ? `<span class="tag ok">matched</span>`
      : `<span class="tag warn">open</span>`;

    li.innerHTML = `
      <div class="page-num">${p.scan_order + 1}</div>
      <div class="page-item-body">
        <div class="page-student ${p.student_name ? "" : "unassigned"}">
          ${escapeHtml(p.student_name || "Unassigned")}
          ${p.student_sis ? `<span class="sis">${escapeHtml(p.student_sis)}</span>` : ""}
        </div>
        <div class="page-meta">
          ${scoreTag}
          ${statusTag}
          <span class="page-file">${escapeHtml(p.file)} p${p.page_index + 1}</span>
        </div>
      </div>`;
    li.addEventListener("click", () => selectPage(p.id));
    ul.appendChild(li);
  }
}

function escapeHtml(s) {
  return String(s ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

function selectPage(id) {
  S.currentPageId = id;
  S.currentQ = 1;
  const p = pageById(id);
  renderPageList();
  if (!p) return;

  $("#page-title").textContent = `#${p.scan_order + 1}  ${p.file} · page ${p.page_index + 1}`;
  $("#student-current").textContent = p.student_name
    ? `${p.student_name}  ·  ${p.student_sis || p.student_id || ""}`
    : "No student assigned — press S to search";
  $("#student-current").classList.toggle("unassigned", !p.student_name);

  const badge = $("#assign-badge");
  badge.textContent = p.student_name ? "assigned" : "unassigned";
  badge.classList.toggle("assigned", !!p.student_name);

  $("#ocr-hint").innerHTML = p.ocr_name
    ? `OCR hint (unverified): <code>${escapeHtml(p.ocr_name)}</code>` +
      (p.ocr_id ? ` <code>${escapeHtml(p.ocr_id)}</code>` : "") +
      (p.netid_guess ? ` <code>${escapeHtml(p.netid_guess)}</code>` : "")
    : "";

  loadImage(p);
  renderAnswers(p);
  renderOverlay(p);
  updateScore(p);
  updateProgress();
  highlightCursor();
}

/* ------------------------------------------------------------------ */
/* scan overlay: recognized letters next to where the student wrote     */
/* ------------------------------------------------------------------ */

function pctX(x) {
  // Map PDF points → percent of the (possibly cropped) preview image.
  const c = S.crop || { x0: 0, x1: FORM.W };
  const w = Math.max(1, c.x1 - c.x0);
  return (((x - c.x0) / w) * 100).toFixed(3) + "%";
}
function pctY(y) {
  const c = S.crop || { y0: 0, y1: FORM.H };
  const h = Math.max(1, c.y1 - c.y0);
  return (((y - c.y0) / h) * 100).toFixed(3) + "%";
}

function renderOverlay(p) {
  const root = $("#page-overlay");
  if (!root) return;
  const enabled = $("#toggle-overlay")?.checked !== false;
  root.classList.toggle("is-hidden", !enabled);
  if (!enabled) {
    root.innerHTML = "";
    return;
  }

  const frag = document.createDocumentFragment();

  /**
   * One chip per cell: recorded value if present, otherwise recognized.
   * Different backgrounds: green = recorded, blue/amber = recognized.
   */
  function chip(xPct, yPct, html, kind, title, opts = {}) {
    if (html == null || html === "") return;
    const tag = document.createElement("div");
    let cls = "ocr-tag " + kind;
    if (opts.id) cls += " id-tag";
    if (opts.src) cls += " src-" + opts.src;
    if (opts.low) cls += " low";
    tag.className = cls;
    tag.style.left = xPct;
    tag.style.top = yPct;
    if (opts.alignRight) tag.style.transform = "translate(-100%, -50%)";
    if (opts.maxWidth) {
      tag.style.maxWidth = opts.maxWidth;
      tag.style.overflow = "hidden";
      tag.style.textOverflow = "ellipsis";
    }
    tag.innerHTML = html;
    if (title) tag.title = title;
    frag.appendChild(tag);
  }

  // --- identity: recorded SIS/name if assigned, else recognized ---
  const idY = pctY((FORM.id_y[0] + FORM.id_y[1]) / 2 + 2);
  const nameY = pctY((FORM.name_y[0] + FORM.name_y[1]) / 2 + 2);
  const idGuess = p.id_guess || p.netid_guess || "";
  const idRaw = (p.ocr_id || "").trim();
  const nameRaw = (p.ocr_name || "").trim();
  const recSis = p.student_sis || "";
  const recName = p.student_name || "";

  if (recSis) {
    chip(
      pctX(528), idY, `SIS ${escapeHtml(recSis)}`, "recorded",
      "Recorded SIS (assigned student)",
      { alignRight: true, id: true }
    );
  } else if (idGuess || idRaw) {
    chip(
      pctX(528), idY,
      `SIS ${escapeHtml(idGuess || "?")}` +
        (idRaw && idRaw !== idGuess ? `<span class="raw">ocr ${escapeHtml(idRaw)}</span>` : ""),
      "recognized",
      "Recognized SIS / netid (unassigned)",
      { alignRight: true, id: true, src: "ocr", low: !idGuess }
    );
  }

  if (recName) {
    chip(
      pctX(528), nameY, escapeHtml(recName), "recorded",
      "Recorded name (assigned student)",
      { alignRight: true, id: true, maxWidth: "40%" }
    );
  } else if (nameRaw) {
    chip(
      pctX(528), nameY, escapeHtml(nameRaw), "recognized",
      "OCR name (unverified)",
      { alignRight: true, id: true, src: "ocr", maxWidth: "40%" }
    );
  }

  // --- per-question: recorded if graded, else recognized guess ---
  for (const col of FORM.cols) {
    for (let row = 0; row < FORM.n_rows; row++) {
      const q = col.q_start + row;
      if (q > S.numQuestions) break;

      const y = pctY(FORM.row_y0 + row * FORM.row_dy + 8);
      const rec = (p.ocr_answers?.[String(q)] || "").toUpperCase();
      const shape = (p.shape_answers?.[String(q)] || "").toUpperCase();
      const conf = p.ocr_conf?.[String(q)] ?? 0;
      const src = p.ocr_src?.[String(q)] || "";
      const graded = (p.answers?.[String(q)] || "").toUpperCase();

      if (graded) {
        chip(
          pctX(col.ans_x[1] + 3), y, escapeHtml(graded), "recorded",
          `Q${q}: recorded ${graded}` +
            (rec && rec !== graded ? ` (was recognized ${rec})` : ""),
          {}
        );
      } else if (rec) {
        chip(
          pctX(col.ans_x[1] + 3), y, escapeHtml(rec), "recognized",
          `Q${q}: recognized ${rec}` +
            (src ? ` (${src}, ${Math.round(conf * 100)}%)` : "") +
            (shape && shape !== rec ? ` · shape=${shape}` : ""),
          { src: src || "ocr", low: conf > 0 && conf < 0.55 }
        );
      }
    }
  }

  root.innerHTML = "";
  root.appendChild(frag);
}

function loadImage(p) {
  const img = $("#page-image");
  const empty = $("#page-empty");
  const url = `/api/page/${encodeURIComponent(p.id)}/image?scale=${S.zoom}&crop=1`;
  img.classList.remove("is-hidden");
  empty.classList.add("is-hidden");

  fetch(url)
    .then((res) => {
      const crop = res.headers.get("X-Crop-Rect");
      if (crop) {
        const [x0, y0, x1, y1] = crop.split(",").map(Number);
        S.crop = { x0, y0, x1, y1 };
      } else {
        S.crop = { x0: 0, y0: 0, x1: FORM.W, y1: FORM.H };
      }
      return res.blob();
    })
    .then((blob) => {
      img.src = URL.createObjectURL(blob);
      img.onload = () => {
        empty.classList.add("is-hidden");
        renderOverlay(pageById(S.currentPageId));
      };
    })
    .catch(() => {
      img.classList.add("is-hidden");
      empty.classList.remove("is-hidden");
      empty.textContent = "Could not render page image";
    });
}

function renderAnswers(p) {
  const grid = $("#ans-grid");
  grid.innerHTML = "";
  const answers = p.answers || {};
  const n = S.numQuestions;

  // 4 columns × 17 rows to mirror the paper form
  const cols = [
    { start: 1, count: 17 },
    { start: 18, count: 17 },
    { start: 35, count: 17 },
    { start: 52, count: 17 },
  ];

  for (const col of cols) {
    const wrap = document.createElement("div");
    wrap.className = "ans-col";
    for (let q = col.start; q < col.start + col.count && q <= n; q++) {
      const got = (answers[String(q)] || "").toUpperCase();
      const expected = S.key[String(q)] || S.key[q] || "";
      const row = document.createElement("div");
      row.className = "q-row";
      row.dataset.q = String(q);
      const conf = p.ocr_conf?.[String(q)];
      const src = p.ocr_src?.[String(q)];
      const shape = p.shape_answers?.[String(q)];
      if (conf != null) {
        row.title = `prefill ${shape || "—"} (${src || "?"}, conf ${Math.round(conf * 100)}%)`;
      }
      if (got && expected && got === expected) row.classList.add("correct");
      else if (got && expected && got !== expected) row.classList.add("wrong");
      else if (!got) row.classList.add("blank", "has-expected");
      if (conf != null && conf < 0.55) row.classList.add("uncertain");

      const w = S.questionPoints[String(q)] ?? S.questionPoints[q] ?? 0.29;
      row.innerHTML = `
        <div class="q-num">${q}<span class="w">${w}p</span></div>
        <div class="q-opts">
          ${LETTERS.map((L) => {
            const sel = got === L ? " sel" : "";
            const exp = S.showKey && expected === L ? " expected" : "";
            return `<button type="button" class="q-opt${sel}${exp}" data-q="${q}" data-let="${L}">${L}</button>`;
          }).join("")}
        </div>`;
      wrap.appendChild(row);
    }
    grid.appendChild(wrap);
  }

  grid.addEventListener("click", onGridClick);
}

function onGridClick(e) {
  const btn = e.target.closest(".q-opt");
  if (!btn) return;
  const q = Number(btn.dataset.q);
  const letter = btn.dataset.let;
  setAnswer(q, letter, true);
}

function highlightCursor() {
  $$(".q-row").forEach((el) => {
    el.classList.toggle("cursor", Number(el.dataset.q) === S.currentQ);
  });
  const el = document.querySelector(`.q-row[data-q="${S.currentQ}"]`);
  if (el) el.scrollIntoView({ block: "nearest" });
}

function updateScore(p) {
  const correct = p.correct ?? 0;
  const wrong = p.wrong ?? 0;
  const blank = p.blank ?? 0;
  const points = p.points ?? 0;
  const pct = p.percent ?? 0;

  $("#score-big").textContent = `${points.toFixed(2)} / ${S.pointsPossible.toFixed(2)}`;
  $("#score-meta").textContent =
    `${correct} correct · ${wrong} wrong · ${blank} blank  ·  ${pct.toFixed(1)}%`;
  $("#score-bar-fill").style.width = `${Math.max(0, Math.min(100, pct))}%`;

  const earned = [];
  const missed = [];
  for (let q = 1; q <= S.numQuestions; q++) {
    const got = (p.answers?.[String(q)] || "").toUpperCase();
    const exp = S.key[String(q)] || "";
    if (got && exp && got === exp) earned.push(q);
    else missed.push(q);
  }
  $("#score-detail").textContent = missed.length
    ? `Missed: ${missed.slice(0, 30).join(", ")}${missed.length > 30 ? "…" : ""}`
    : "All correct.";
}

function updateProgress() {
  const total = S.pages.length;
  const matched = S.pages.filter((p) => p.student_id).length;
  $("#progress-pill").textContent = `${matched}/${total} pages matched`;
}

/* ------------------------------------------------------------------ */
/* mutations                                                           */
/* ------------------------------------------------------------------ */

async function setAnswer(q, letter, advance = false) {
  const p = pageById(S.currentPageId);
  if (!p) return;
  const val = letter ? letter.toUpperCase() : "";
  await api("/api/answers", {
    method: "POST",
    body: JSON.stringify({ page_id: p.id, answers: { [String(q)]: val } }),
  }).then((data) => {
    refreshPageInList(data.page);
    renderAnswers(data.page);
    renderOverlay(data.page);
    updateScore(data.page);
    renderPageList();
    S.currentQ = q;
    if (advance && S.autoAdvance && val) {
      const next = nextQuestion(q, +1, { skipFilled: false });
      if (next != null) S.currentQ = next;
    }
    highlightCursor();
  });
}

function nextQuestion(from, dir, { skipFilled = false, blanksOnly = false, wrongOnly = false } = {}) {
  const p = pageById(S.currentPageId);
  const n = S.numQuestions;
  let q = from;
  for (let i = 0; i < n; i++) {
    q += dir;
    if (q < 1) q = n;
    if (q > n) q = 1;
    const got = (p?.answers?.[String(q)] || "").toUpperCase();
    const exp = S.key[String(q)] || "";
    if (blanksOnly && got) continue;
    if (wrongOnly && !(got && exp && got !== exp)) continue;
    if (skipFilled && got) continue;
    return q;
  }
  return null;
}

function goQuestion(q) {
  q = Math.max(1, Math.min(S.numQuestions, Number(q) || 1));
  S.currentQ = q;
  highlightCursor();
}

function goPage(delta) {
  const idx = S.pages.findIndex((p) => p.id === S.currentPageId);
  if (idx < 0) return;
  const next = S.pages[Math.max(0, Math.min(S.pages.length - 1, idx + delta))];
  if (next) selectPage(next.id);
}

async function assignStudent(studentId) {
  const p = pageById(S.currentPageId);
  if (!p) return;
  const data = await api("/api/assign", {
    method: "POST",
    body: JSON.stringify({ page_id: p.id, student_id: studentId || null }),
  });
  refreshPageInList(data.page);
  // refresh roster assigned flags
  const amap = new Map();
  for (const pg of S.pages) {
    if (pg.student_id) amap.set(pg.student_id, pg.id);
  }
  for (const r of S.roster) r.assigned = amap.has(r.student_id);
  selectPage(data.page.id);
  if (data.warning) toast(`⚠ ${data.warning}`);
  else toast(studentId ? `Assigned to ${data.page.student_name}` : "Unassigned");
}

async function prefillOcr() {
  const p = pageById(S.currentPageId);
  if (!p) return;
  const data = await api("/api/prefill_ocr", {
    method: "POST",
    body: JSON.stringify({ page_id: p.id }),
  });
  refreshPageInList(data.page);
  renderAnswers(data.page);
  renderOverlay(data.page);
  updateScore(data.page);
  renderPageList();
  toast("OCR guesses copied — review every cell");
}

async function clearPage() {
  const p = pageById(S.currentPageId);
  if (!p) return;
  if (!confirm("Clear this page's student assignment and all answers?")) return;
  const data = await api("/api/clear_page", {
    method: "POST",
    body: JSON.stringify({ page_id: p.id }),
  });
  refreshPageInList(data.page);
  selectPage(data.page.id);
  toast("Page cleared");
}

async function exportAll() {
  if (S.busy) return;
  S.busy = true;
  const btn = $("#btn-export");
  btn.disabled = true;
  btn.textContent = "Exporting…";
  try {
    const order = $("#pdf-order")?.value || "scan";
    const data = await api("/api/export", {
      method: "POST",
      body: JSON.stringify({ pdf_order: order }),
    });
    const body = $("#export-body");
    body.innerHTML = data.files
      .map(
        (f) => `
        <a class="file-link" href="${f.url}" download>
          <div>
            <div class="name">${escapeHtml(f.name)}</div>
            <div class="desc">${
              f.kind === "canvas"
                ? "Canvas import CSV (Student, ID, score) — upload this one"
                : f.kind === "canvas_full"
                  ? "Full gradebook CSV with every Canvas column"
                  : f.kind === "pdf"
                    ? `Feedback PDF — one page/student, ${data.pdf_order === "reverse" ? "reversed for duplex back-side" : "scan order"}`
                    : "Per-scan audit CSV"
            }</div>
          </div>
          <div>Download ↓</div>
        </a>`
      )
      .join("");
    $("#export-dialog").showModal();
    toast(`Exported ${data.assigned_count} graded / ${data.page_count} pages`);
  } catch (err) {
    toast(`Export failed: ${err.message}`);
  } finally {
    S.busy = false;
    btn.disabled = false;
    btn.textContent = "Export grades + PDF";
  }
}

/* ------------------------------------------------------------------ */
/* student picker                                                      */
/* ------------------------------------------------------------------ */

function scoreStudent(stu, q) {
  const needle = q.trim().toLowerCase();
  if (!needle) return 1;
  const name = stu.name.toLowerCase();
  const id = (stu.student_id || "").toString();
  const sis = (stu.sis_login || "").toLowerCase();
  const netid = (stu.netid || stu.sis_id || "").toLowerCase();
  const display = (stu.display || "").toLowerCase();
  let s = 0;

  // SIS / netid (primary identifier)
  if (netid === needle || sis === needle) s = 1.0;
  else if (netid.startsWith(needle) || sis.startsWith(needle)) s = 0.95;
  else if (netid.includes(needle) || sis.includes(needle)) s = 0.88;

  // Numeric Canvas ID (still searchable)
  if (id === needle) s = Math.max(s, 1.0);
  else if (id.startsWith(needle)) s = Math.max(s, 0.92);
  else if (id.includes(needle) && needle.length >= 3) s = Math.max(s, 0.8);

  if (name.includes(needle)) s = Math.max(s, 0.85);
  if (display.includes(needle)) s = Math.max(s, 0.82);

  // token match: every word of the query appears
  const tokens = needle.split(/\s+/).filter(Boolean);
  if (
    tokens.length > 1 &&
    tokens.every((t) => name.includes(t) || id.includes(t) || netid.includes(t) || sis.includes(t))
  ) {
    s = Math.max(s, 0.9);
  }
  return s;
}

function updateStudentList() {
  const q = $("#student-search").value;
  const list = $("#student-list");
  if (!q.trim()) {
    list.classList.remove("open");
    list.innerHTML = "";
    S.studentMatches = [];
    return;
  }
  const scored = S.roster
    .map((stu) => ({ stu, s: scoreStudent(stu, q) }))
    .filter((x) => x.s > 0.25)
    .sort((a, b) => b.s - a.s || a.stu.name.localeCompare(b.stu.name))
    .slice(0, 12);
  S.studentMatches = scored;
  S.studentCursor = 0;

  list.innerHTML = scored
    .map((x, i) => {
      const taken = x.stu.assigned ? " taken" : "";
      const sis = x.stu.sis_id || x.stu.netid || x.stu.student_id || "";
      return `<li class="combo-item${taken}${i === 0 ? " cursor" : ""}" data-id="${escapeHtml(x.stu.student_id)}">
        <span class="who">${escapeHtml(x.stu.name)}</span>
        <span>
          <span class="sid">${escapeHtml(sis)}</span>
          ${x.stu.assigned ? '<span class="why">used</span>' : ""}
        </span>
      </li>`;
    })
    .join("");
  list.classList.add("open");
}

function moveStudentCursor(delta) {
  const items = $$("#student-list .combo-item");
  if (!items.length) return;
  S.studentCursor = (S.studentCursor + delta + items.length) % items.length;
  items.forEach((el, i) => el.classList.toggle("cursor", i === S.studentCursor));
  items[S.studentCursor].scrollIntoView({ block: "nearest" });
}

function confirmStudentSelection() {
  const items = $$("#student-list .combo-item");
  if (!items.length) {
    // no dropdown: treat as unassign attempt? ignore
    return;
  }
  const idx = Math.max(0, Math.min(items.length - 1, S.studentCursor));
  const id = items[idx].dataset.id;
  $("#student-search").value = "";
  $("#student-list").classList.remove("open");
  assignStudent(id);
  focusGridSoon();
}

/* ------------------------------------------------------------------ */
/* UI binding + shortcuts                                              */
/* ------------------------------------------------------------------ */

function focusGridSoon() {
  // Keep focus body-level so letter keys always work.
  document.body.focus();
}

function toast(msg) {
  const el = $("#toast");
  el.textContent = msg;
  el.hidden = false;
  clearTimeout(toast._t);
  toast._t = setTimeout(() => {
    el.hidden = true;
  }, 2600);
}

function inTextField() {
  const ae = document.activeElement;
  if (!ae) return false;
  const tag = ae.tagName;
  return tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT" || ae.isContentEditable;
}

function bindUI() {
  $("#btn-export").addEventListener("click", exportAll);
  $("#btn-prefill").addEventListener("click", prefillOcr);
  $("#btn-clear").addEventListener("click", clearPage);
  $("#btn-close-dialog").addEventListener("click", () => $("#export-dialog").close());
  $("#btn-close-help").addEventListener("click", () => $("#help-dialog").close());

  $("#btn-zoom-in").addEventListener("click", () => setZoom(S.zoom + 0.25));
  $("#btn-zoom-out").addEventListener("click", () => setZoom(S.zoom - 0.25));
  $("#btn-zoom-fit").addEventListener("click", () => setZoom(1.25));
  $("#toggle-overlay")?.addEventListener("change", () => {
    const p = pageById(S.currentPageId);
    if (p) renderOverlay(p);
  });

  $("#page-filter").addEventListener("input", (e) => {
    S.pageFilter = e.target.value;
    renderPageList();
  });

  $("#student-search").addEventListener("input", updateStudentList);
  $("#student-search").addEventListener("keydown", (e) => {
    if (e.key === "ArrowDown") {
      e.preventDefault();
      moveStudentCursor(1);
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      moveStudentCursor(-1);
    } else if (e.key === "Enter") {
      e.preventDefault();
      confirmStudentSelection();
    } else if (e.key === "Escape") {
      e.preventDefault();
      e.target.value = "";
      $("#student-list").classList.remove("open");
      e.target.blur();
    }
  });
  $("#student-list").addEventListener("click", (e) => {
    const item = e.target.closest(".combo-item");
    if (!item) return;
    $("#student-search").value = "";
    $("#student-list").classList.remove("open");
    assignStudent(item.dataset.id);
    focusGridSoon();
  });
  $("#btn-suggest").addEventListener("click", async () => {
    const p = pageById(S.currentPageId);
    if (!p) return;
    const data = await api(
      `/api/suggest?name=${encodeURIComponent(p.ocr_name)}&id=${encodeURIComponent(p.ocr_id)}&netid=${encodeURIComponent(p.netid_guess || "")}`
    );
    if (!data.suggestions.length) {
      toast("No OCR suggestions");
      return;
    }
    // Show suggestions in the dropdown
    S.studentMatches = data.suggestions.map((s) => ({
      stu: {
        student_id: s.student_id,
        name: s.name,
        sis_login: s.sis_login,
        display: `${s.name} (${s.student_id})`,
        assigned: S.roster.find((r) => r.student_id === s.student_id)?.assigned,
      },
      s: s.score,
      why: s.why,
    }));
    const list = $("#student-list");
    list.innerHTML = S.studentMatches
      .map((x, i) => {
        const taken = x.stu.assigned ? " taken" : "";
        const sis = x.stu.sis_id || x.stu.netid || x.stu.student_id || "";
        return `<li class="combo-item${taken}${i === 0 ? " cursor" : ""}" data-id="${escapeHtml(x.stu.student_id)}">
          <span class="who">${escapeHtml(x.stu.name)}</span>
          <span>
            <span class="sid">${escapeHtml(sis)}</span>
            ${x.why ? `<span class="why"> ${escapeHtml(x.why)}</span>` : ""}
          </span>
        </li>`;
      })
      .join("");
    list.classList.add("open");
    S.studentCursor = 0;
    toast("Suggestions loaded — press Enter to assign the top one, or click");
    $("#student-search").focus();
  });

  // Global keyboard
  window.addEventListener("keydown", onKeydown);

  // Click anywhere on the grid area keeps body focus for typing
  $("#ans-grid").addEventListener("mousedown", () => {
    setTimeout(focusGridSoon, 0);
  });
}

function setZoom(z) {
  S.zoom = Math.max(0.5, Math.min(3.5, z));
  const p = pageById(S.currentPageId);
  if (p) loadImage(p);
}

function onKeydown(e) {
  // Always allow Esc to close dialogs
  if (e.key === "Escape") {
    const help = $("#help-dialog");
    const exp = $("#export-dialog");
    if (help.open) {
      help.close();
      return;
    }
    if (exp.open) {
      exp.close();
      return;
    }
  }

  // Inside student search: only handle a few keys (handled separately too)
  if (document.activeElement && document.activeElement.id === "student-search") {
    return; // its own keydown handler runs
  }
  if (document.activeElement && document.activeElement.id === "page-filter") {
    if (e.key === "Escape") {
      document.activeElement.value = "";
      S.pageFilter = "";
      renderPageList();
      document.activeElement.blur();
    }
    return;
  }
  if (inTextField()) return;

  const k = e.key;
  const lower = k.length === 1 ? k.toLowerCase() : k;
  const p = pageById(S.currentPageId);

  // Dialog help
  if (lower === "?" || (e.shiftKey && k === "/")) {
    e.preventDefault();
    if (!$("#help-dialog").open) $("#help-dialog").showModal();
    return;
  }

  // Page navigation
  if (k === "PageDown" || (lower === "]" && !e.ctrlKey) || (e.ctrlKey && k === "ArrowRight")) {
    e.preventDefault();
    goPage(1);
    return;
  }
  if (k === "PageUp" || (lower === "[" && !e.ctrlKey) || (e.ctrlKey && k === "ArrowLeft")) {
    e.preventDefault();
    goPage(-1);
    return;
  }

  // Student / page actions  (never steal A/B/C/D — those are answers)
  if (lower === "s") {
    e.preventDefault();
    $("#student-search").focus();
    $("#student-search").select();
    return;
  }
  if (lower === "/") {
    e.preventDefault();
    $("#page-filter").focus();
    $("#page-filter").select();
    return;
  }
  if (lower === "u") {
    e.preventDefault();
    assignStudent(null);
    return;
  }
  if (lower === "p") {
    e.preventDefault();
    prefillOcr();
    return;
  }
  if (lower === "x" || (e.ctrlKey && lower === "k")) {
    // X = clear page (C is answer C)
    e.preventDefault();
    clearPage();
    return;
  }
  if (lower === "e" || (e.ctrlKey && lower === "e")) {
    e.preventDefault();
    exportAll();
    return;
  }
  if (lower === "v") {
    e.preventDefault();
    S.showKey = !S.showKey;
    if (p) renderAnswers(p);
    toast(S.showKey ? "Answer key highlight ON" : "Answer key highlight OFF");
    return;
  }
  if (lower === "o") {
    e.preventDefault();
    const cb = $("#toggle-overlay");
    if (cb) {
      cb.checked = !cb.checked;
      if (p) renderOverlay(p);
      toast(cb.checked ? "Scan overlay ON" : "Scan overlay OFF");
    }
    return;
  }

  // Zoom
  if (k === "+" || k === "=") {
    e.preventDefault();
    setZoom(S.zoom + 0.25);
    return;
  }
  if (k === "-" || k === "_") {
    // distinguish from clear-answer '-'
    if (k === "_") {
      e.preventDefault();
      setZoom(S.zoom - 0.25);
      return;
    }
  }
  if (lower === "f") {
    e.preventDefault();
    setZoom(1.25);
    return;
  }

  // Go to question
  if (lower === "g") {
    e.preventDefault();
    const raw = prompt("Go to question number (1–68):", String(S.currentQ));
    if (raw != null) goQuestion(raw);
    return;
  }

  // Jump helpers
  if (lower === "n") {
    e.preventDefault();
    const q = nextQuestion(S.currentQ, +1, { blanksOnly: true });
    if (q != null) goQuestion(q);
    else toast("No more blank questions");
    return;
  }
  if (lower === "w") {
    e.preventDefault();
    const q = nextQuestion(S.currentQ, +1, { wrongOnly: true });
    if (q != null) goQuestion(q);
    else toast("No more wrong questions");
    return;
  }

  // Question navigation
  if (k === "ArrowDown" || lower === "j" || k === "ArrowRight" || lower === "l") {
    e.preventDefault();
    goQuestion(S.currentQ + 1);
    return;
  }
  if (k === "ArrowUp" || lower === "k" || k === "ArrowLeft" || lower === "h") {
    e.preventDefault();
    goQuestion(S.currentQ - 1);
    return;
  }
  if (k === "Home") {
    e.preventDefault();
    goQuestion(1);
    return;
  }
  if (k === "End") {
    e.preventDefault();
    goQuestion(S.numQuestions);
    return;
  }

  // Tab: next blank
  if (k === "Tab") {
    e.preventDefault();
    const q = e.shiftKey
      ? nextQuestion(S.currentQ, -1, { blanksOnly: true })
      : nextQuestion(S.currentQ, +1, { blanksOnly: true });
    if (q != null) goQuestion(q);
    else toast("No more blank questions");
    return;
  }

  // Clear
  if (k === "Backspace") {
    e.preventDefault();
    const cur = S.currentQ;
    setAnswer(cur, "", false).then(() => goQuestion(cur - 1));
    return;
  }
  if (k === "Delete" || k === "0" || k === " " || k === "Spacebar" || k === "-" || k === ".") {
    e.preventDefault();
    setAnswer(S.currentQ, "", false);
    return;
  }

  // Reveal key
  if (k === "?" || (e.shiftKey && k === "/")) {
    // handled above
  }
  if (e.key === "?" ) return;

  // Enter / numbers / letters = set answer
  if (k === "Enter" || k === "Return") {
    e.preventDefault();
    // move to next without changing
    goQuestion(S.currentQ + 1);
    return;
  }

  const digitMap = { "1": "A", "2": "B", "3": "C", "4": "D" };
  if (digitMap[k]) {
    e.preventDefault();
    setAnswer(S.currentQ, digitMap[k], true);
    return;
  }
  if (["a", "b", "c", "d"].includes(lower)) {
    e.preventDefault();
    setAnswer(S.currentQ, lower.toUpperCase(), true);
    return;
  }
}

/* ------------------------------------------------------------------ */
/* start                                                               */
/* ------------------------------------------------------------------ */

boot().catch((err) => {
  console.error(err);
  $("#boot-info").textContent = `Failed to load: ${err.message}`;
  toast(`Failed to load: ${err.message}`);
});