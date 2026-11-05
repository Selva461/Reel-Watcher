/* Reel Shelf: the two main screens and the top bar.
   Library (#/): everything you kept, one search box (words, everyday questions, or your voice), kind chips and filters.
   Inbox (#/inbox): what came in today, tonight's run, the big actions, and what needs you.
   Uses local.js (db, settings, phone, sync, render...), search.js, catalog.js, watch.js, quotes.js and verify.js. */
"use strict";

const SVG = (d, extra = "") => `<svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" ${extra}>${d}</svg>`;
const UI = {
  mic: SVG('<rect x="9" y="3" width="6" height="11" rx="3"/><path d="M5 11a7 7 0 0 0 14 0M12 18v3"/>'),
  filter: SVG('<path d="M4 5h16l-6 7.5V19l-4 2v-8.5z"/>'),
  gear: SVG('<circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1.1-1.6 1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.6-1.1 1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.8.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1z"/>'),
  play: SVG('<path d="M7 5l12 7-12 7z" fill="currentColor"/>'),
  five: SVG('<path d="M15 4H9l-1 7c1-.7 2.2-1 3.5-1a4.5 4.5 0 1 1-4.3 5.8"/>'),
  image: SVG('<rect x="3" y="4" width="18" height="16" rx="2"/><circle cx="9" cy="10" r="2"/><path d="M21 16l-5-5-9 9"/>'),
  comment: SVG('<path d="M21 12a8 8 0 0 1-11.6 7.1L4 20l1-4.6A8 8 0 1 1 21 12z"/>'),
  plus: SVG('<path d="M12 5v14M5 12h14"/>'),
  moon: SVG('<path d="M20 14.5A8 8 0 0 1 9.5 4a8 8 0 1 0 10.5 10.5z"/>'),
  check: SVG('<path d="M5 12l4 4L19 6"/>'),
  spark: SVG('<path d="M12 3l1.8 5.2L19 10l-5.2 1.8L12 17l-1.8-5.2L5 10l5.2-1.8zM19 16l.8 2.2L22 19l-2.2.8L19 22l-.8-2.2L16 19l2.2-.8z"/>'),
  copy: SVG('<rect x="9" y="9" width="11" height="11" rx="2"/><path d="M5 15V5a2 2 0 0 1 2-2h10"/>'),
  close: SVG('<path d="M6 6l12 12M18 6L6 18"/>'),
  insta: SVG('<rect x="3" y="3" width="18" height="18" rx="5"/><circle cx="12" cy="12" r="4"/><circle cx="17.5" cy="6.5" r="1" fill="currentColor"/>'),
  globe: SVG('<circle cx="12" cy="12" r="9"/><path d="M3 12h18M12 3a14 14 0 0 1 0 18M12 3a14 14 0 0 0 0 18"/>'),
  ask: SVG('<path d="M9.1 9a3 3 0 0 1 5.8 1c0 2-3 3-3 3M12 17h.01"/><circle cx="12" cy="12" r="9"/>'),
};

// ------------------------------------------------------------------ state of the Library

const KINDS = [["all", "All"], ["reels", "Reels"], ["quotes", "Quotes"], ["movies", "Movies"], ["series", "Series"], ["anime", "Anime"], ["manga", "Manga"]];
let lib = { kind: "all", q: "", status: "", language: "", genre: "", year: "", maxMin: 0, verified: "", source: "", tag: "", more: 0 };
const MEDIA_KINDS = ["movies", "series", "anime", "manga"];
const isMediaKind = (k) => MEDIA_KINDS.includes(k);
const activeFilters = () => ["status", "language", "genre", "year", "maxMin", "verified", "source", "tag"].filter((k) => lib[k]).length;

// ------------------------------------------------------------------ the top bar (search, filter, mic, settings)

function topBar(show) {
  const bar = document.getElementById("top");
  if (!bar) return;
  bar.hidden = !show;
  document.body.classList.toggle("with-top", !!show);
  const q = document.getElementById("tq");
  if (q && document.activeElement !== q && q.value !== lib.q) q.value = lib.q;
  const dot = document.getElementById("fdot");
  if (dot) dot.hidden = !activeFilters();
}

let typing = 0;
function bindTopBar() {
  const q = document.getElementById("tq");
  if (!q || q.dataset.bound) return;
  q.dataset.bound = "1";
  q.addEventListener("input", () => {
    lib.q = q.value;
    lib.more = 0;
    clearTimeout(typing);
    typing = setTimeout(() => { if (!/^#?\/?$/.test(location.hash)) location.hash = "#/"; else paintLibrary(); }, 120);
  });
  q.addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); q.blur(); } });
  document.getElementById("tclear").addEventListener("click", () => { lib.q = ""; q.value = ""; paintLibrary(); q.focus(); });
  document.getElementById("mic").addEventListener("click", voiceSearch);
  document.getElementById("filt").addEventListener("click", filterSheet);
}

/** The mic: Android's own speech recognizer (on the phone when its offline language pack is there). Nothing is recorded by this app. */
function voiceSearch() {
  phone("listen").then((text) => {
    text = String(text || "").trim();
    if (!text) return;
    lib.q = text;
    lib.more = 0;
    const q = document.getElementById("tq");
    if (q) q.value = text;
    if (!/^#?\/?$/.test(location.hash)) location.hash = "#/"; else paintLibrary();
  }).catch((e) => { if (e.message !== "cancelled") toast(e.message); });
}

// ------------------------------------------------------------------ Library

function libraryScreen() {
  topBar(true);
  const st = isMediaKind(lib.kind) ? (lib.kind === "manga" ? [["", "All"], ["want", "To read"], ["watching", "Reading"], ["done", "Read"]]
    : [["", "All"], ["want", "To watch"], ["watching", "Watching"], ["done", "Watched"]]) : null;
  $app.innerHTML = `
    <div class="chips" role="group" aria-label="Kind">${KINDS.map(([k, l]) => `<button class="chip" data-kind="${k}" aria-pressed="${lib.kind === k}">${l}</button>`).join("")}</div>
    ${st ? `<div class="seg" role="group" aria-label="Status">${st.map(([k, l]) => `<button data-status="${k}" aria-pressed="${lib.status === k}">${l}</button>`).join("")}</div>` : ""}
    <div class="tagrow" id="understood"></div>
    <div class="stack" id="results"></div>`;
  bind("[data-kind]", "click", (e, b) => { lib.kind = b.dataset.kind; if (!isMediaKind(lib.kind)) lib.status = ""; lib.more = 0; libraryScreen(); });
  bind("[data-status]", "click", (e, b) => { lib.status = b.dataset.status; lib.more = 0; libraryScreen(); });
  paintLibrary();
}

function libFilters() {
  return { kind: lib.kind, status: lib.status, language: lib.language, genre: lib.genre, year: lib.year, maxMin: lib.maxMin, verified: lib.verified, source: lib.source };
}

const PAGE = 120;
function paintLibrary() {
  const box = document.getElementById("results");
  if (!box) { if (/^#?\/?$/.test(location.hash)) libraryScreen(); return; }
  topBar(true);
  const q = lib.q.trim();
  const res = Search.run(db, q, libFilters());
  if (lib.tag) res.reels = res.reels.filter((h) => ((h.reel.notes || {}).tags || []).includes(lib.tag));
  if (q) {  // a name or link typed exactly also finds the reel
    const plain = q.toLowerCase();
    const seen = new Set(res.reels.map((h) => h.reel));
    const wantsReels = lib.kind === "reels" || (lib.kind === "all" && (!res.p.kinds || res.p.kinds.includes("reels")) && !res.p.types && !res.p.maxMin && !res.p.status);
    if (wantsReels) for (const r of db.reels) if (!seen.has(r) && [r.author, r.url, r.code].join(" ").toLowerCase().includes(plain)) res.reels.push({ reel: r, score: 0, lines: [] });
  }
  const und = document.getElementById("understood");
  if (und) und.innerHTML = q && res.p.understood.length ? res.p.understood.map((u) => `<span class="tag ok" title="${esc(u.kind)}">${esc(u.label)}</span>`).join("") : "";
  const limit = PAGE * (lib.more + 1);
  const rows = [];
  if (!q && lib.kind === "all") {  // everything, newest first
    const all = [...res.reels.map((h) => ({ t: h.reel.added_at || 0, html: () => reelRow(h.reel) })),
      ...res.media.map((m) => ({ t: m.added_at || 0, html: () => titleRow(m) })),
      ...res.quotes.map((x) => ({ t: x.at || 0, html: () => quoteRow(x) }))].sort((a, b) => b.t - a.t);
    rows.push(...all.slice(0, limit).map((x) => x.html()));
    if (all.length > limit) rows.push(moreBtn(all.length - limit));
    if (!all.length) rows.push(db.reels.length ? `<div class="empty">Nothing here yet.</div>` : emptyShelf());
  } else {
    const sections = [];
    const one = !!(lib.kind !== "all");
    if (res.media.length || (res.noLength.length && (lib.kind === "all" || isMediaKind(lib.kind)))) sections.push(["Titles", res.media.map(titleRow), res.media.length, res.noLength]);
    if (res.reels.length) sections.push(["Reels", res.reels.map((h) => q ? reelHit(h, q) : reelRow(h.reel)), res.reels.length]);
    if (res.quotes.length) sections.push(["Quotes", res.quotes.map(quoteRow), res.quotes.length]);
    if (!res.p.structured) sections.sort((a, b) => sectionScore(b, q) - sectionScore(a, q));
    let left = limit;
    for (const [label, list, n, noLength] of sections) {
      if (!one || sections.length > 1) rows.push(`<div class="label">${label} · ${n}</div>`);
      rows.push(...list.slice(0, left));
      if (list.length > left) { rows.push(moreBtn(list.length - left)); left = 0; break; }
      left -= list.length;
      if (noLength && noLength.length) rows.push(noLengthHtml(noLength));
    }
    if (!sections.length) rows.push(nothingHtml(q, res));
  }
  if (q && looksLikeQuestion(q, res)) rows.unshift(`<a class="btn block" id="askq" href="#/ask?q=${enc(q)}">${UI.ask} Answer this</a>`);
  box.innerHTML = rows.join("");
  box.querySelectorAll("[data-copy]").forEach((b) => b.addEventListener("click", (e) => { e.preventDefault(); copyQuote(b.dataset.copy); }));
  const mb = box.querySelector("#more");
  if (mb) mb.addEventListener("click", () => { lib.more++; paintLibrary(); });
  const ai = box.querySelector("#aisearch");
  if (ai) ai.addEventListener("click", () => aiSearch(q, ai));
}

/** A question ("how do I...", "what is...?") or words that found nothing: offer an answer from the notes (and online, if on). */
function looksLikeQuestion(q, res) {
  if (res.p.structured) return false;
  return /\?\s*$/.test(q) || /^(how|what|why|who|when|where|which|is|are|can|does|do|should|explain|tell me)\b/i.test(q)
    || (!res.media.length && !res.reels.length && !res.quotes.length);
}

function sectionScore([label, , n], q) {
  if (!n) return -1;
  if (label === "Titles") return Catalog.filter(db, { q }).length ? 3 : 1;  // the name of a title wins
  return label === "Reels" ? 2 : 1.5;
}
function moreBtn(n) { return `<button class="btn block" id="more">+${n}</button>`; }

function reelHit(h, q) {
  const r = h.reel;
  const n = r.notes || {};
  const title = n.topic || (r.caption ? r.caption.split("\n")[0].slice(0, 90) : r.author ? `Reel by @${r.author}` : "Reel " + r.code);
  const line = (h.lines || [])[0];
  return `<a class="list-item" href="#/r/${enc(r.code)}"><span class="grow stack" style="gap:4px"><span class="title clamp">${Lib.highlight(title, q)}</span>
    ${line ? `<span class="small soft clamp">${Lib.highlight(line, q)}</span>` : ""}
    <span class="small muted">${esc([r.author ? "@" + r.author : "", day(r.added_at)].filter(Boolean).join(" · "))}</span></span></a>`;
}

function quoteRow(x) {
  return `<div class="list-item"><span class="grow stack" style="gap:4px"><span>“${esc(x.text)}”</span>${x.from ? `<span class="small muted">${esc(x.from)}</span>` : ""}</span>
    <button class="icon-btn" data-copy="${esc(x.id)}" aria-label="Copy">${UI.copy}</button></div>`;
}
function copyQuote(id) {
  const x = (db.quotes || []).find((q) => q.id === id);
  if (!x) return;
  sync("copy", `"${x.text}"${x.from ? " (" + x.from + ")" : ""}`);
  toast("Copied");
}

function noLengthHtml(list) {
  const unchecked = list.filter((m) => m.verified !== "verified").length;
  return `<details class="stack"><summary class="small muted">+${list.length} · length unknown${unchecked ? ` (${unchecked} not checked online yet)` : ""}</summary>
    <div class="stack" style="margin-top:8px">${list.slice(0, 60).map(titleRow).join("")}</div>
    ${Verify.counts(db).waiting || Verify.counts(db).lengths ? `<a class="btn block" href="#/check">${UI.check} Look up lengths</a>` : ""}</details>`;
}

function nothingHtml(q, res) {
  if (!q) return `<div class="empty">Nothing here yet.</div>`;
  const ready = !!modelInfo().ready;
  const fix = Lib.didYouMean(db.reels, q);
  return `<div class="empty stack">Nothing found${fix ? ` · <a href="#" id="dym" data-q="${esc(fix)}">${esc(fix)}</a>?` : ""}
    ${ready && q.split(/\s+/).length >= 3 && !res.p.structured ? `<button class="btn block" id="aisearch">${UI.spark} Phone AI</button>` : ""}</div>`;
}
document.addEventListener("click", (e) => {
  const a = e.target && e.target.closest && e.target.closest("#dym");
  if (!a) return;
  e.preventDefault();
  lib.q = a.dataset.q;
  const q = document.getElementById("tq");
  if (q) q.value = lib.q;
  paintLibrary();
});

/** Words the search did not understand: the on-phone AI turns them into a search it does (stays on the phone). */
async function aiSearch(q, btn) {
  btn.disabled = true;
  btn.textContent = "…";
  try {
    const out = JSON.parse(await phone("generate", Search.AI_PROMPT(q),
      JSON.stringify({ file: settings.modelFile, gpu: settings.gpu, system: "You turn a search into JSON. Answer with JSON only.", maxTokens: 160, temperature: 0 })));
    const nq = Search.fromAi(out.text);
    if (!nq) { toast("The AI could not read it"); btn.disabled = false; btn.innerHTML = `${UI.spark} Phone AI`; return; }
    lib.q = nq;
    const el = document.getElementById("tq");
    if (el) el.value = nq;
    paintLibrary();
  } catch (e) { toast(e.message); btn.disabled = false; btn.innerHTML = `${UI.spark} Phone AI`; }
}

// ------------------------------------------------------------------ the filter sheet

function filterSheet() {
  if (!/^#?\/?$/.test(location.hash)) location.hash = "#/";
  const mediaList = (db.media || []).filter((m) => m.verified !== "rejected" && (!isMediaKind(lib.kind) || Search.kindOf(m) === lib.kind));
  const f = Catalog.facets(db, mediaList);
  const tags = {};
  for (const r of db.reels) for (const t of (r.notes || {}).tags || []) tags[t] = (tags[t] || 0) + 1;
  const sel = (key, label, counts, name, order) => {
    const keys = Object.keys(counts).sort(order || ((a, b) => counts[b] - counts[a] || String(a).localeCompare(String(b))));
    if (lib[key] && !keys.includes(String(lib[key]))) keys.unshift(String(lib[key]));
    if (!keys.length) return "";
    return `<label class="field small-field"><span class="label">${label}</span><select class="input" data-f="${key}">
      <option value="">Any</option>${keys.map((k) => `<option value="${esc(k)}" ${String(lib[key]) === k ? "selected" : ""}>${esc(name(k))}${counts[k] != null ? ` (${counts[k]})` : ""}</option>`).join("")}</select></label>`;
  };
  const showMedia = lib.kind === "all" || isMediaKind(lib.kind);
  const showReels = lib.kind === "all" || lib.kind === "reels";
  const lengths = { 60: null, 90: null, 100: null, 120: null, 150: null };
  for (const k of Object.keys(lengths)) lengths[k] = mediaList.filter((m) => m.runtime > 0 && m.runtime <= Number(k)).length;
  const topTags = Object.fromEntries(Object.entries(tags).sort((a, b) => b[1] - a[1]).slice(0, 40));
  $dlg.innerHTML = `<form method="dialog" class="stack"><div class="row between"><h2>Filters</h2><button class="icon-btn" value="cancel" aria-label="Close">${UI.close}</button></div>
    <div class="grid2">
      ${showMedia ? sel("status", "Status", f.status, (k) => Catalog.STATUS[k] || k) : ""}
      ${showMedia ? sel("language", "Language", f.language, (k) => k === "unknown" ? "Unknown" : Catalog.langName(k)) : ""}
      ${showMedia ? sel("genre", "Genre", f.genre, (k) => k) : ""}
      ${showMedia ? sel("year", "Years", f.decade, (k) => k === "unknown" ? "Unknown" : k, (a, b) => (a === "unknown") - (b === "unknown") || String(b).localeCompare(String(a))) : ""}
      ${showMedia ? sel("maxMin", "Length", lengths, (k) => "≤ " + Search.fmtMin(Number(k)), (a, b) => Number(a) - Number(b)) : ""}
      ${showMedia ? sel("verified", "Checked", f.verified, (k) => Catalog.VERIFIED[k] || k) : ""}
      ${showMedia ? sel("source", "From", f.source, (k) => ({ screenshot: "Screenshots", reel: "Reels", manual: "You" }[k] || k)) : ""}
      ${showReels ? sel("tag", "Tag", topTags, (k) => "#" + k) : ""}
    </div>
    <div class="grid2"><button class="btn" id="fclear" value="cancel">Clear</button><button class="btn primary" value="ok">Done</button></div>
    ${showMedia ? `<button class="btn block" id="addt" value="cancel">${UI.plus} Title</button>` : ""}</form>`;
  $dlg.querySelectorAll("[data-f]").forEach((s) => s.addEventListener("change", () => {
    lib[s.dataset.f] = s.dataset.f === "maxMin" ? Number(s.value) || 0 : s.value;
    lib.more = 0;
    paintLibrary();
  }));
  $dlg.querySelector("#fclear").addEventListener("click", () => {
    for (const k of ["status", "language", "genre", "year", "verified", "source", "tag"]) lib[k] = "";
    lib.maxMin = 0;
    libraryScreen();
  });
  const add = $dlg.querySelector("#addt");
  if (add) add.addEventListener("click", () => setTimeout(() => titleDialog(null), 0));
  $dlg.showModal();
}

// ------------------------------------------------------------------ Inbox

function inboxCount() {
  const since = Date.now() - 86400e3;
  return db.reels.filter((r) => (r.added_at || 0) > since).length + (db.inbox || []).length + Verify.counts(db).review;
}

function inboxScreen() {
  topBar(true);
  const ready = !!modelInfo().ready;
  const todo = db.reels.filter((r) => needsWork(r, ready));
  const running = run && !run.finished;
  const since = Date.now() - 86400e3;
  const today = db.reels.filter((r) => (r.added_at || 0) > since).sort((a, b) => (b.added_at || 0) - (a.added_at || 0));
  const titlesToday = (db.media || []).filter((m) => (m.added_at || 0) > since && m.verified !== "rejected");
  const failed = db.reels.filter((r) => r.status === "failed");
  const nr = (() => { try { return JSON.parse(sync("nightRunInfo") || "{}"); } catch (e) { return {}; } })();
  const shotsJob = Shots.job && !Shots.job.finished;
  const tile = (id, icon, label, href) => href ? `<a class="tile-btn" id="${id}" href="${href}">${icon}<span>${label}</span></a>`
    : `<button class="tile-btn" id="${id}">${icon}<span>${label}</span></button>`;
  $app.innerHTML = `
    ${igWaitingCard()}
    ${running ? `<a class="card accent" href="#/run">${UI.play}<span class="grow stack" style="gap:2px"><strong>${run.i + 1} / ${run.codes.length}</strong><span class="bar"><span style="width:${Math.round(((run.i) / Math.max(1, run.codes.length)) * 100)}%"></span></span></span></a>` : ""}
    ${shotsJob ? `<a class="card" href="#/shots">${UI.image}<span class="grow">${Shots.job.i || 0} / ${Shots.job.total || "…"}</span></a>` : ""}
    <div class="tiles">
      ${running ? tile("goRun", UI.play, "Working", "#/run") : todo.length ? tile("start", UI.play, `Start ${todo.length}`) : tile("goRun", UI.play, "Start", "#/run")}
      ${!running && todo.length > 5 ? tile("try5", UI.five, "Try 5") : ""}
      ${tile("shots", UI.image, "Screenshots", "#/shots")}
      ${tile("comments", UI.comment, "Comments")}
      ${tile("add", UI.plus, "Add", "#/add")}
    </div>
    ${nr.on !== undefined ? `<a class="list-item" href="#/settings" style="align-items:center">${UI.moon}<span class="grow small">${nr.on ? `${String(nr.hour).padStart(2, "0")}:00 · ${nr.chargingOnly !== false ? "charging" : `>${nr.minBattery}%`} · ≤ ${settings.nightMax || 200}` : "Off"}</span></a>` : ""}
    ${Verify.cardHtml()}
    ${(db.inbox || []).length ? `<a class="card accent" href="#/file"><span class="grow"><strong>${plural(db.inbox.length, "Meta AI answer")}</strong></span>${ICON.chev}</a>` : ""}
    ${failed.length ? `<details class="stack"><summary class="label">Could not finish · ${failed.length}</summary><div class="stack" style="margin-top:8px">${failed.slice(0, 40).map(reelRow).join("")}</div></details>` : ""}
    ${settings.metaAi && forMeta().length > 1 && !running ? `<button class="btn block" id="batch">Ask Meta AI · ${Math.min(BATCH, forMeta().length)}</button>` : ""}
    ${today.length ? `<div class="label">Today · ${today.length}</div><div class="stack">${today.slice(0, 50).map(reelRow).join("")}</div>` : ""}
    ${titlesToday.length ? `<div class="label">New titles · ${titlesToday.length}</div><div class="stack">${titlesToday.slice(0, 20).map(titleRow).join("")}</div>` : ""}
    ${!today.length && !titlesToday.length && !db.reels.length ? emptyShelf() : ""}`;
  bindIgWaiting();
  bind("#start", "click", () => { settings.rereadOk = true; saveSettings(); startRun(); });
  bind("#try5", "click", () => startRun(todo.slice().sort(byUsefulThenNewest).slice(0, 5).map((r) => r.code)));
  bind("#comments", "click", commentsFromPictures);
  bind("#batch", "click", askMetaBatch);
}

/** Comment screenshots: choose them, they are read on the phone and filed under the reel they belong to. */
function commentsFromPictures() {
  phone("addShotPictures").then((n) => {
    toast(`${plural(Number(n) || 0, "picture")} added`);
    location.hash = "#/shots";
    Shots.process();
  }).catch((e) => { if (e.message !== "cancelled") toast(e.message); });
}

function paintTabs(tab) {
  document.querySelectorAll("nav.tabs a").forEach((a) => (a.dataset.tab === tab ? a.setAttribute("aria-current", "page") : a.removeAttribute("aria-current")));
  const badge = document.getElementById("ibadge");
  if (badge) { const n = inboxCount(); badge.textContent = n > 99 ? "99+" : String(n); badge.hidden = !n; }
}
