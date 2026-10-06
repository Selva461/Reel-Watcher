/* Reel Shelf phone app. Plain JavaScript, no build step. Every screen is a function that renders into #app. */
"use strict";

const $app = document.getElementById("app");
const $toast = document.getElementById("toast");
const $dlg = document.getElementById("dlg");
let timers = [];
let toastTimer = null;

// ------------------------------------------------------------------ helpers

function esc(v) {
  return String(v == null ? "" : v).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}
const enc = encodeURIComponent;
const TYPE_LABEL = { movie: "Movie", series: "Series", anime: "Anime", manga: "Manga", book: "Book", game: "Game", other: "Other" };
const SOURCE_LABEL = { text: "On-screen text", speech: "Said in the reel", caption: "Caption", comment: "Comment", scene: "Screenshot match", ai: "AI guess", user: "You" };
const CONF = { confirmed: ["Confirmed", "ok"], matched: ["Matched from screenshot", "ok"], check: ["Check this", "warn"] };
const TINTS = ["#F2B544", "#7FB7E8", "#E89A7F", "#B6A3E8", "#E8D27F", "#9CCB8E", "#E8A3C4", "#8FD3CF"];
const ICON = {
  back: '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" aria-hidden="true"><path d="M15 6l-6 6 6 6"/></svg>',
  chev: '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="#8E8B85" stroke-width="2" stroke-linecap="round" aria-hidden="true"><path d="M9 6l6 6-6 6"/></svg>',
  check: '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="#15161A" stroke-width="3" stroke-linecap="round" aria-hidden="true"><path d="M5 12l4 4L19 6"/></svg>',
  folder: '<svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" aria-hidden="true"><path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/></svg>',
  scan: '<svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" aria-hidden="true"><path d="M4 8V5a1 1 0 0 1 1-1h3M16 4h3a1 1 0 0 1 1 1v3M20 16v3a1 1 0 0 1-1 1h-3M8 20H5a1 1 0 0 1-1-1v-3"/><circle cx="12" cy="12" r="3"/></svg>',
  filter: '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" aria-hidden="true"><path d="M4 6h16M7 12h10M10 18h4"/></svg>',
  heart: (on) => `<svg width="20" height="20" viewBox="0 0 24 24" fill="${on ? "#F2B544" : "none"}" stroke="#F2B544" stroke-width="2" aria-hidden="true"><path d="M12 20s-7-4.5-7-10a4 4 0 0 1 7-2.6A4 4 0 0 1 19 10c0 5.5-7 10-7 10z"/></svg>`,
  upload: '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" aria-hidden="true"><path d="M12 16V4M7 9l5-5 5 5M5 20h14"/></svg>',
};

function toast(msg) {
  $toast.textContent = msg;
  $toast.classList.add("show");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => $toast.classList.remove("show"), 3200);
}

async function api(path, opts = {}) {
  const o = { method: opts.method || "GET", headers: {} };
  if (opts.body instanceof Blob) {
    o.body = opts.body;
    o.headers["Content-Type"] = "application/octet-stream";
    o.headers["X-Filename"] = enc(opts.filename || "file");
  } else if (opts.body !== undefined) {
    o.body = JSON.stringify(opts.body);
    o.headers["Content-Type"] = "application/json";
  }
  const r = await fetch(path, o);
  let data = null;
  try { data = await r.json(); } catch (e) { data = null; }
  if (!r.ok) throw new Error((data && data.error) || `Request failed (${r.status})`);
  return data;
}

function store(key, val) {
  try {
    if (val === undefined) return JSON.parse(localStorage.getItem("rs." + key) || "null");
    localStorage.setItem("rs." + key, JSON.stringify(val));
  } catch (e) { /* private mode: keep going without remembering */ }
  return val;
}

function every(ms, fn) { timers.push(setInterval(fn, ms)); }
function header(title, back, right = "") {
  return `<div class="row between"><div class="row">${back ? `<a class="icon-btn" href="${back}" aria-label="Back">${ICON.back}</a>` : ""}<h1>${esc(title)}</h1></div>${right}</div>`;
}
function tint(name) { let h = 0; for (const c of name) h = (h * 31 + c.charCodeAt(0)) >>> 0; return TINTS[h % TINTS.length]; }
function thumb(name, cls = "thumb") { return name ? `<img class="${cls}" src="/media/${enc(name)}" alt="" loading="lazy">` : `<span class="${cls}" aria-hidden="true"></span>`; }
function confTag(c) { const [l, k] = CONF[c] || CONF.check; return `<span class="tag ${k}">${l}</span>`; }
function meta(t) { return [t.year, TYPE_LABEL[t.type] || t.type, (t.genres || []).slice(0, 2).join(", ")].filter(Boolean).join(" · "); }
function pct(a, b) { return b ? Math.round((a / b) * 100) : 0; }
function fmtN(n) { return Number(n || 0).toLocaleString("en-US"); }
function bind(sel, ev, fn) { $app.querySelectorAll(sel).forEach((el) => el.addEventListener(ev, (e) => fn(e, el))); }

// ------------------------------------------------------------------ filters state (search screen + filter sheet)

const FILTER_GROUPS = [
  ["type", "Type", "", ["movie", "series", "anime", "manga", "book", "game"]],
  ["language", "Title language", "(original)", ["English", "Japanese", "Korean", "Hindi", "Tamil", "Telugu", "Malayalam", "Spanish", "French", "German", "Chinese"]],
  ["reel_language", "Reel language", "(spoken in the reel)", ["English", "Hindi", "Tamil", "Telugu", "Japanese", "Korean", "Spanish"]],
  ["genre", "Genre", "", ["Action", "Thriller", "Romance", "Comedy", "Fantasy", "Sci-Fi", "Horror", "Drama", "Slice of Life", "Sports"]],
  ["status", "Status", "", ["to_watch", "watching", "watched", "favorites"]],
  ["found_from", "Found from", "", ["Reel", "Screenshot", "Comment"]],
  ["confidence", "Confidence", "", ["confirmed", "matched", "check"]],
];
const VALUE_LABEL = { to_watch: "To watch", watching: "Watching", watched: "Watched", favorites: "Favorites", confirmed: "Confirmed", matched: "Matched from screenshot", check: "Check this", ...TYPE_LABEL };
let filters = store("filters") || {};
function saveFilters() { store("filters", filters); }
function activeCount() { return Object.entries(filters).reduce((n, [k, v]) => n + (Array.isArray(v) ? v.length : (k === "year_from" || k === "year_to") && v ? 1 : 0), 0); }
function filterQuery(extra = {}) {
  const p = new URLSearchParams();
  for (const [k, v] of Object.entries({ ...filters, ...extra })) {
    if (Array.isArray(v) ? v.length : v) p.set(k, Array.isArray(v) ? v.join(",") : v);
  }
  return p.toString();
}
function toggleIn(key, val) {
  const cur = filters[key] || [];
  filters[key] = cur.includes(val) ? cur.filter((x) => x !== val) : [...cur, val];
  saveFilters();
}

// ------------------------------------------------------------------ screens

async function homeScreen() {
  const d = await api("/api/home");
  const active = d.jobs.filter((j) => !j.finished);
  const cols = d.collections;
  $app.innerHTML = `
    <div class="brand">Reel Shelf</div>
    <h1>What did you save?</h1>
    <a class="search" href="#/search">${ICON.filter.replace("currentColor", "#A3A09A")}<span class="grow">Search titles, language, genre</span></a>
    <a class="card accent" href="#/identify"><span class="coll-icon" style="background:#15161A;color:#F2B544">${ICON.scan}</span>
      <span class="stack" style="gap:2px"><strong style="font-size:17px">Identify something</strong><span>From a screenshot, a folder or a reel link</span></span></a>
    ${active.map((j) => `<a class="card" href="#/progress"><span class="coll-icon" style="background:#2C2D34;color:#F2B544">${ICON.folder}</span>
      <span class="stack grow" style="gap:6px"><strong>${esc(j.name)}</strong><span class="bar"><span style="width:${pct(j.done, j.total)}%"></span></span>
      <span class="small muted">${j.scanning ? "Finding images..." : `${fmtN(j.done)} of ${fmtN(j.total)}`} · ${j.state === "paused" ? "paused" : "running in background"}</span></span></a>`).join("")}
    ${d.check ? `<a class="card" href="#/check"><span class="dot" style="background:var(--accent)"></span><span class="grow"><strong>Check this</strong><br><span class="small muted">${d.check} unsure ${d.check === 1 ? "guess" : "guesses"} to confirm</span></span>${ICON.chev}</a>` : ""}
    <div class="stack"><div class="row between"><h2>Collections</h2><a class="small" href="#/import">Import from Instagram</a></div>
      ${cols.length ? `<div class="grid2">${cols.map((c) => `
        <a class="card" style="flex-direction:column;align-items:flex-start;gap:10px" href="#/c/${enc(c.name)}">
          <span class="coll-icon" style="background:${tint(c.name)}">${esc(c.name.trim()[0] || "?").toUpperCase()}</span>
          <span><strong>${esc(c.name)}</strong><br><span class="small muted">${c.kind === "quote" ? `${c.quotes} clips` : `${c.titles} titles`} · ${c.items} saved</span></span>
        </a>`).join("")}</div>`
        : `<div class="empty">No collections yet.<br><br><a class="btn primary" href="#/import">Import your Instagram saves</a><br><br><a class="btn" href="#/folder">Scan a folder of screenshots</a></div>`}
    </div>
    ${d.recent.length ? `<div class="stack"><h2>Recently identified</h2>${d.recent.map((r) => `
      <a class="list-item" href="#/t/${r.id}">${thumb(r.thumb, "thumb sm")}<span class="grow stack" style="gap:3px"><span class="title">${esc(r.name)}</span>
      <span class="small muted">${esc(meta(r))}${r.detail ? " · " + esc(r.detail) : ""}</span></span><span class="tag">${r.item_kind === "image" ? "Screenshot" : esc(SOURCE_LABEL[r.source] || "Reel")}</span></a>`).join("")}</div>` : ""}
    <a class="small muted" href="#/settings">Settings</a>`;
}

async function importScreen() {
  $app.innerHTML = `${header("Import from Instagram", "#/")}
    <ol class="stack soft" style="padding-left:20px;margin:0;line-height:1.5">
      <li>In Instagram: Settings, Accounts Center, Your information and permissions, Download your information.</li>
      <li>Choose <strong>Some of your information</strong>, tick <strong>Saved</strong>, format <strong>JSON</strong>, then export.</li>
      <li>When the email arrives, download the ZIP and choose it below.</li>
    </ol>
    <label class="btn primary block" for="zip">${ICON.upload}<span>Choose the ZIP file</span></label>
    <input id="zip" class="sr" type="file" accept=".zip,.json,application/zip,application/json">
    <div id="result"></div>`;
  bind("#zip", "change", async (e, el) => {
    const f = el.files[0];
    if (!f) return;
    document.getElementById("result").innerHTML = `<div class="empty">Reading ${esc(f.name)}...</div>`;
    try {
      const r = await api("/api/import", { method: "POST", body: f, filename: f.name });
      const rows = Object.entries(r.collections);
      document.getElementById("result").innerHTML = `<div class="stack"><h2>Found ${rows.length} collections</h2>
        ${rows.map(([n, c]) => `<div class="card row between"><span><strong>${esc(n)}</strong><br><span class="small muted">${c} saved</span></span>
          <button class="btn primary" data-read="${esc(n)}" ${c ? "" : "disabled"}>Read</button></div>`).join("")}
        <p class="small muted">Reading downloads each reel for free and runs in the background. Start one collection at a time, or all.</p></div>`;
      bind("[data-read]", "click", async (ev, b) => { await readCollection(b.dataset.read); b.textContent = "Started"; b.disabled = true; });
    } catch (err) {
      document.getElementById("result").innerHTML = `<div class="empty">${esc(err.message)}</div>`;
    }
  });
}

async function readCollection(name) {
  const r = await api(`/api/collections/${enc(name)}/read`, { method: "POST", body: {} });
  toast(r.queued ? `Reading ${r.queued} reels in the background` : "Nothing new to read in this collection");
  return r;
}

async function collectionScreen(name) {
  const cols = (await api("/api/collections")).collections;
  const c = cols.find((x) => x.name === name);
  if (!c) { $app.innerHTML = `${header(name, "#/")}<div class="empty">This collection is empty.</div>`; return; }
  if (c.kind === "quote") return quotesScreen(c);
  const st = store("coll." + name) || { f: "All" };
  const typeOf = { Movie: "movie", Series: "series", Anime: "anime", Manga: "manga" };
  const extra = { collection: [name] };
  if (st.f === "To watch") extra.status = ["to_watch", "watching"];
  if (st.f === "Watched") extra.status = ["watched"];
  if (typeOf[st.f]) extra.type = [typeOf[st.f]];
  const qs = new URLSearchParams();
  for (const [k, v] of Object.entries(extra)) qs.set(k, v.join(","));
  const res = (await api("/api/search?" + qs)).results;
  const readBtn = c.idle ? `<button class="btn primary block" id="read">Read this collection (${c.idle} reels)</button>` : "";
  $app.innerHTML = `${header(name, "#/", `<a class="btn" href="/api/export.csv?collection=${enc(name)}">Export</a>`)}
    <span class="muted">${res.length} titles from ${c.items} saved${c.working ? ` · reading ${c.working} more` : ""}</span>
    ${readBtn}
    <div class="chips">${["All", "To watch", "Watched", "Movie", "Series", "Anime", "Manga"].map((f) => `<button class="chip" data-f="${f}" aria-pressed="${st.f === f}">${f}</button>`).join("")}</div>
    <div class="stack">${res.length ? res.map(titleRow).join("") : `<div class="empty">${c.done ? "No titles match this filter." : "Nothing read yet. Tap Read this collection."}</div>`}</div>`;
  bind("[data-f]", "click", (e, b) => { store("coll." + name, { f: b.dataset.f }); collectionScreen(name); });
  bind("#read", "click", async () => { await readCollection(name); collectionScreen(name); });
  bindWatchToggles(() => collectionScreen(name));
}

function titleRow(t) {
  const watched = t.watch === "watched";
  return `<div class="list-item">
    ${thumb(t.thumb)}
    <a class="grow stack" style="gap:4px;color:var(--text)" href="#/t/${t.id}">
      <span class="title">${esc(t.name)}</span><span class="small muted">${esc(meta(t))}</span>
      <span class="row wrap" style="gap:6px">${t.language ? `<span class="tag">${esc(t.language)}</span>` : ""}
        <span class="tag">${t.n_reels} ${t.kinds.includes("image") && !t.kinds.includes("reel") ? "screenshot" : "save"}${t.n_reels === 1 ? "" : "s"}</span>${t.confidence !== "confirmed" ? confTag(t.confidence) : ""}</span>
    </a>
    <button class="check-btn" data-watch="${t.id}" aria-pressed="${watched}" aria-label="${watched ? "Mark " + esc(t.name) + " as not watched" : "Mark " + esc(t.name) + " as watched"}">${watched ? ICON.check : ""}</button>
  </div>`;
}

function bindWatchToggles(after) {
  bind("[data-watch]", "click", async (e, b) => {
    const on = b.getAttribute("aria-pressed") !== "true";
    await api(`/api/titles/${b.dataset.watch}`, { method: "PATCH", body: { watch: on ? "watched" : "to_watch" } });
    toast(on ? "Marked as watched" : "Moved back to To watch");
    after();
  });
}

async function titleScreen(id) {
  const t = await api(`/api/titles/${id}`);
  const back = history.length > 1 ? "javascript:history.back()" : "#/";
  const ex = t.extra || {};
  const why = t.finds.find((f) => f.evidence)?.evidence || "";
  $app.innerHTML = `${header("", back, `<button class="icon-btn" id="fav" aria-label="${t.favorite ? "Remove from favorites" : "Add to favorites"}" aria-pressed="${!!t.favorite}">${ICON.heart(t.favorite)}</button>`)}
    <div class="row" style="align-items:flex-start">${t.cover ? `<img class="thumb" src="${esc(t.cover)}" alt="">` : ""}
      <div class="stack" style="gap:8px"><h1>${esc(t.name)}</h1>
        <div class="row wrap" style="gap:8px">${[t.year, TYPE_LABEL[t.type], t.language, ...(t.genres || []).slice(0, 3), ex.episodes ? ex.episodes + " episodes" : "", ex.chapters ? ex.chapters + " chapters" : ""]
          .filter(Boolean).map((x) => `<span class="tag">${esc(x)}</span>`).join("")}</div></div></div>
    <div class="seg" role="group" aria-label="Status">${[["to_watch", "To watch"], ["watching", "Watching"], ["watched", "Watched"]].map(([v, l]) => `<button data-w="${v}" aria-pressed="${t.watch === v}">${l}</button>`).join("")}</div>
    ${why ? `<div class="card stack"><span class="label">Why it was saved</span><span>${esc(why)}</span></div>` : ""}
    <div class="stack"><h2>Found in ${t.finds.length} ${t.finds.length === 1 ? "save" : "saves"}</h2>
      ${t.finds.map((f) => `<div class="list-item">${thumb(f.thumb)}<div class="grow stack" style="gap:6px">
        <span class="row wrap" style="gap:6px"><strong>${esc(f.author ? "@" + f.author : f.item_kind === "image" ? "Your screenshot" : "Reel")}</strong>${confTag(f.confidence)}</span>
        ${f.evidence ? `<span class="soft small">${esc(f.evidence)}</span>` : ""}
        <span class="small muted">${esc(SOURCE_LABEL[f.source] || f.source)}${f.detail ? " · " + esc(f.detail) : ""} · ${esc((f.collections || []).join(", "))}</span>
        <span class="row wrap" style="gap:14px">${f.url ? `<a href="${esc(f.url)}" target="_blank" rel="noopener">Open reel</a>` : ""}
          <button class="btn" style="min-height:36px" data-fix="${f.id}">Wrong name?</button>
          ${f.confidence === "check" ? `<button class="btn" style="min-height:36px" data-ok="${f.id}">It is right</button>` : ""}</span>
      </div></div>`).join("")}</div>
    <label class="field" for="notes">My notes<textarea id="notes" class="input" placeholder="Add a note, e.g. watch with friends">${esc(t.notes || "")}</textarea></label>`;
  bind("[data-w]", "click", async (e, b) => { await api(`/api/titles/${id}`, { method: "PATCH", body: { watch: b.dataset.w } }); titleScreen(id); });
  bind("#fav", "click", async () => { await api(`/api/titles/${id}`, { method: "PATCH", body: { favorite: !t.favorite } }); titleScreen(id); });
  bind("#notes", "change", async (e, el) => { await api(`/api/titles/${id}`, { method: "PATCH", body: { notes: el.value } }); toast("Note saved"); });
  bind("[data-ok]", "click", async (e, b) => { await api(`/api/finds/${b.dataset.ok}/confirm`, { method: "POST", body: {} }); toast("Confirmed"); titleScreen(id); });
  bind("[data-fix]", "click", (e, b) => renameDialog(b.dataset.fix, (it) => { const f = it.finds[0]; location.hash = f && f.title_id ? `#/t/${f.title_id}` : "#/"; }));
}

function renameDialog(findId, after) {
  $dlg.innerHTML = `<form method="dialog" class="stack" id="rf"><h2>Type the right name</h2>
    <label class="field">Name<input class="input" id="rn" required placeholder="e.g. Vinland Saga"></label>
    <label class="field">Type<select class="input" id="rt"><option value="">Not sure</option>${Object.entries(TYPE_LABEL).map(([v, l]) => `<option value="${v}">${l}</option>`).join("")}</select></label>
    <div class="row"><button class="btn grow" value="cancel" type="button" id="rc">Cancel</button><button class="btn primary grow" type="submit">Save</button></div></form>`;
  $dlg.showModal();
  $dlg.querySelector("#rc").onclick = () => $dlg.close();
  $dlg.querySelector("#rf").onsubmit = async (e) => {
    e.preventDefault();
    try {
      const it = await api(`/api/finds/${findId}/rename`, { method: "POST", body: { name: $dlg.querySelector("#rn").value, type: $dlg.querySelector("#rt").value } });
      $dlg.close();
      toast("Name saved");
      after(it);
    } catch (err) { toast(err.message); }
  };
  setTimeout(() => $dlg.querySelector("#rn").focus(), 30);
}

async function quotesScreen(c) {
  const st = store("quotes." + c.name) || { grid: true, fav: false };
  const qs = (await api(`/api/quotes?collection=${enc(c.name)}${st.fav ? "&favorites=1" : ""}`)).quotes;
  store("quoteList", qs.map((q) => q.id));
  $app.innerHTML = `${header(c.name, "#/", `<button class="btn" id="view" aria-label="${st.grid ? "Switch to list view" : "Switch to grid view"}">${st.grid ? "Grid" : "List"}</button>`)}
    <span class="muted">${qs.length} captioned clips from ${c.items} saved${c.working ? ` · reading ${c.working} more` : ""}</span>
    ${c.idle ? `<button class="btn primary block" id="read">Read this collection (${c.idle} reels)</button>` : ""}
    <div class="chips"><button class="chip" id="all" aria-pressed="${!st.fav}">All</button><button class="chip" id="favs" aria-pressed="${st.fav}">Favorites</button>
      <button class="chip" id="rand" ${qs.length ? "" : "disabled"}>Random quote</button></div>
    ${!qs.length ? `<div class="empty">${st.fav ? "No favorites yet." : "No clips yet. Tap Read this collection."}</div>` : st.grid
      ? `<div class="grid2">${qs.map((q) => `<a class="tile" href="#/q/${q.id}"><span class="shot">${q.media ? `<img src="/media/${enc(q.media)}" alt="${esc(q.quote)}" loading="lazy">` : thumb(q.thumb, "")}
          <span class="badge">GIF</span></span><span class="small muted">${esc(q.author ? "@" + q.author : "")}</span></a>`).join("")}</div>`
      : `<div class="stack">${qs.map((q) => `<a class="list-item" href="#/q/${q.id}">${thumb(q.thumb)}<span class="stack" style="gap:6px"><span class="quote-text" style="font-size:16px">${esc(q.quote)}</span>
          <span class="small muted">${esc(q.author ? "@" + q.author : "")}</span></span></a>`).join("")}</div>`}`;
  bind("#view", "click", () => { store("quotes." + c.name, { ...st, grid: !st.grid }); quotesScreen(c); });
  bind("#all", "click", () => { store("quotes." + c.name, { ...st, fav: false }); quotesScreen(c); });
  bind("#favs", "click", () => { store("quotes." + c.name, { ...st, fav: true }); quotesScreen(c); });
  bind("#rand", "click", () => { location.hash = `#/q/${qs[Math.floor(Math.random() * qs.length)].id}`; });
  bind("#read", "click", async () => { await readCollection(c.name); collectionScreen(c.name); });
}

async function quoteScreen(id) {
  const all = (await api("/api/quotes")).quotes;
  const q = all.find((x) => String(x.id) === String(id));
  if (!q) { $app.innerHTML = `${header("Quote", "#/")}<div class="empty">Not found.</div>`; return; }
  const list = store("quoteList") || all.map((x) => x.id);
  const i = list.indexOf(q.id);
  const prev = i > 0 ? list[i - 1] : null;
  const next = i >= 0 && i < list.length - 1 ? list[i + 1] : null;
  const st = store("quoteStyle") || { style: "bold", format: "gif" };
  let media = q.media;
  $app.innerHTML = `${header("", "javascript:history.back()", `<button class="icon-btn" id="fav" aria-pressed="${!!q.favorite}" aria-label="${q.favorite ? "Remove from favorites" : "Add to favorites"}">${ICON.heart(q.favorite)}</button>`)}
    <figure class="stack" style="margin:0;align-items:center"><div class="media-frame" id="mf"></div>
      <figcaption class="small muted" id="mcap"></figcaption></figure>
    <div class="card stack"><span class="label">Caption style</span>
      <div class="grid3">${[["bold", "Bold"], ["clean", "Clean"], ["typewriter", "Typewriter"]].map(([v, l]) => `<button class="chip" data-style="${v}" aria-pressed="${st.style === v}">${l}</button>`).join("")}</div>
      <span class="label">Format</span>
      <div class="grid2">${[["gif", "GIF"], ["mp4", "Video with sound"]].map(([v, l]) => `<button class="chip" data-format="${v}" aria-pressed="${st.format === v}">${l}</button>`).join("")}</div></div>
    <blockquote class="card stack" style="margin:0"><p class="quote-text">"${esc(q.quote)}"</p><span class="small muted">${esc(q.author ? "Shared by @" + q.author : "")}</span></blockquote>
    <div class="grid3"><a class="btn primary" id="save" download>Save</a><button class="btn" id="share">Share</button><button class="btn" id="copy">Copy text</button></div>
    <div class="row">${prev ? `<a class="btn grow" href="#/q/${prev}">Previous</a>` : ""}<a class="btn grow" href="${esc(q.url)}" target="_blank" rel="noopener">Open reel</a>${next ? `<a class="btn grow" href="#/q/${next}">Next</a>` : ""}</div>`;
  const show = (name) => {
    media = name;
    const mf = document.getElementById("mf");
    if (!name) { mf.innerHTML = `<div class="empty">The clip could not be made for this reel.</div>`; return; }
    mf.innerHTML = name.endsWith(".mp4") ? `<video src="/media/${enc(name)}" controls autoplay loop playsinline></video>` : `<img src="/media/${enc(name)}" alt="${esc(q.quote)}">`;
    const a = document.getElementById("save");
    a.href = `/media/${enc(name)}`;
    a.setAttribute("download", name);
    document.getElementById("mcap").textContent = name.endsWith(".mp4") ? "Video with sound" : "GIF";
  };
  const rerender = async () => {
    const s = store("quoteStyle") || st;
    if (s.style === "bold" && s.format === "gif" && q.media) return show(q.media);
    document.getElementById("mf").innerHTML = `<div class="empty">Making the ${s.format === "gif" ? "GIF" : "video"}...</div>`;
    try { show((await api(`/api/quotes/${q.id}/render`, { method: "POST", body: s })).media); } catch (err) { toast(err.message); show(q.media); }
  };
  rerender();
  bind("[data-style]", "click", (e, b) => { const s = { ...(store("quoteStyle") || st), style: b.dataset.style }; store("quoteStyle", s);
    $app.querySelectorAll("[data-style]").forEach((x) => x.setAttribute("aria-pressed", x === b)); rerender(); });
  bind("[data-format]", "click", (e, b) => { const s = { ...(store("quoteStyle") || st), format: b.dataset.format }; store("quoteStyle", s);
    $app.querySelectorAll("[data-format]").forEach((x) => x.setAttribute("aria-pressed", x === b)); rerender(); });
  bind("#fav", "click", async () => { await api(`/api/quotes/${q.id}/favorite`, { method: "POST", body: { on: !q.favorite } }); quoteScreen(id); });
  bind("#copy", "click", async () => {
    try { await navigator.clipboard.writeText(q.quote); toast("Quote copied"); } catch (e) { toast("Copy is not allowed here; long-press the quote to copy"); }
  });
  bind("#share", "click", async () => {
    try {
      const blob = await (await fetch(`/media/${enc(media)}`)).blob();
      const file = new File([blob], media, { type: blob.type });
      if (navigator.canShare && navigator.canShare({ files: [file] })) await navigator.share({ files: [file], text: q.quote });
      else if (navigator.share) await navigator.share({ text: q.quote });
      else { await navigator.clipboard.writeText(q.quote); toast("Sharing is not available here, so the quote was copied"); }
    } catch (e) { if (e.name !== "AbortError") toast("Could not share: " + e.message); }
  });
}

async function identifyScreen() {
  const tab = store("idTab") || "shot";
  const cols = (await api("/api/collections")).collections.map((c) => c.name);
  $app.innerHTML = `${header("Identify", "")}
    <div class="seg" role="tablist"><button role="tab" data-tab="shot" aria-pressed="${tab === "shot"}" aria-selected="${tab === "shot"}">Screenshot</button>
      <button role="tab" data-tab="reel" aria-pressed="${tab === "reel"}" aria-selected="${tab === "reel"}">Reel link</button></div>
    ${tab === "shot" ? `
      <label class="btn primary block" for="pic">${ICON.upload}<span>Pick a screenshot</span></label>
      <input id="pic" class="sr" type="file" accept="image/*">
      <a class="card" href="#/folder"><span class="coll-icon" style="background:#2C2D34;color:#F2B544">${ICON.folder}</span><span class="grow"><strong>Scan a whole folder</strong><br>
        <span class="small muted">Thousands of screenshots, in the background</span></span>${ICON.chev}</a>
      <p class="small muted">Reads the text in the image, searches anime scenes and manga panels, then checks the name. All free.</p>`
    : `<form class="stack" id="rf"><label class="field">Reel or post link<input class="input" id="url" type="url" required placeholder="https://www.instagram.com/reel/..."></label>
        <label class="field">Save to collection<input class="input" id="col" list="cols" placeholder="e.g. Movies"><datalist id="cols">${cols.map((c) => `<option value="${esc(c)}">`).join("")}</datalist></label>
        <span class="small muted">Comments are read too, in case the name is there.</span>
        <button class="btn primary block" type="submit">Identify</button></form>`}`;
  bind("[data-tab]", "click", (e, b) => { store("idTab", b.dataset.tab); identifyScreen(); });
  bind("#pic", "change", async (e, el) => {
    const f = el.files[0];
    if (!f) return;
    try { const r = await api("/api/identify/image", { method: "POST", body: f, filename: f.name }); location.hash = `#/item/${r.item}`; } catch (err) { toast(err.message); }
  });
  bind("#rf", "submit", async (e) => {
    e.preventDefault();
    try { const r = await api("/api/identify/reel", { method: "POST", body: { url: document.getElementById("url").value, collection: document.getElementById("col").value } }); location.hash = `#/item/${r.item}`; }
    catch (err) { toast(err.message); }
  });
}

const IMG_STEPS = [["reading text", "Reading text in the image"], ["checking names", "Checking the name (AniList, Wikidata)"], ["AI looking at the picture", "AI looking at the picture"],
  ["searching anime scenes", "Searching anime scenes (trace.moe)"], ["searching manga panels", "Searching manga panels (SauceNAO)"]];
const REEL_STEPS = [["downloading", "Downloading the reel and comments"], ["watching and listening", "Reading text, speech and caption"], ["names", "Checking names"]];

async function itemScreen(id) {
  const it = await api(`/api/items/${id}`);
  const busy = ["waiting", "working"].includes(it.status);
  const steps = it.kind === "image" ? IMG_STEPS : REEL_STEPS;
  const at = steps.findIndex(([k]) => k === it.stage);
  const best = it.finds[0];
  const alts = it.finds.filter((f) => f.kind === "title");
  const statusText = { waiting_quota: "Waiting for the free search limit; it continues automatically", other: "This does not look like a movie, show, anime or manga", skipped: it.error || "No name found",
    failed: it.error || "Something went wrong", duplicate: "Same picture as one you already have" }[it.status];
  $app.innerHTML = `${header(busy ? "Identifying..." : best ? "Match found" : "No match yet", "#/identify")}
    <div class="row" style="align-items:flex-start">${thumb(it.meta.thumb, "thumb big")}
      <div class="stack grow" style="gap:8px">${best && best.kind === "title" ? `<span class="label">${esc(TYPE_LABEL[best.type] || "")}</span><h1 style="font-size:26px">${esc(best.name)}</h1>
        <span class="soft">${esc([best.year, best.extra && best.extra.episodes ? best.extra.episodes + " episodes" : ""].filter(Boolean).join(" · "))}</span>
        ${best.detail ? `<strong style="color:var(--accent)">${esc(best.detail)}</strong>` : ""}${confTag(best.confidence)}`
        : best && best.kind === "quote" ? `<p class="quote-text">"${esc(best.quote)}"</p>` : `<span class="muted">${esc(statusText || "Working on it...")}</span>`}</div></div>
    ${busy ? `<div class="card steps">${steps.map(([k, l], n) => `<div class="step ${n < at ? "done" : n === at ? "now" : "todo"}"><span class="ring">${n < at ? ICON.check.replace('width="20" height="20"', 'width="14" height="14"') : ""}</span><span>${l}</span></div>`).join("")}</div>` : ""}
    ${!busy && best && best.kind === "title" ? `<div class="grid2">
      <div class="card"><span class="small muted">Original language</span><br><strong>${esc(best.language || "Unknown")}</strong></div>
      <div class="card"><span class="small muted">Genre</span><br><strong>${esc((best.genres || []).slice(0, 2).join(", ") || "Unknown")}</strong></div>
      <div class="card"><span class="small muted">Found by</span><br><strong>${esc(SOURCE_LABEL[best.source] || best.source)}</strong></div>
      <div class="card"><span class="small muted">Match</span><br><strong>${esc(best.evidence && /%/.test(best.evidence) ? best.evidence.match(/\d+%/)[0] : best.confidence === "check" ? "Unsure" : "Strong")}</strong></div></div>` : ""}
    ${statusText && best ? `<span class="small muted">${esc(statusText)}</span>` : ""}
    ${!busy && alts.length ? `<div class="stack"><strong>${alts.length > 1 ? "Not right? Pick another" : "Is this right?"}</strong>
      ${alts.map((f, n) => `<div class="card row between"><span><strong>${esc(f.name || f.name_raw)}</strong><br><span class="small muted">${esc(TYPE_LABEL[f.type] || "")} · ${esc(CONF[f.confidence][0])}</span></span>
        <button class="btn ${n === 0 ? "primary" : ""}" data-pick="${f.id}">${f.confidence === "check" ? "This one" : "Keep"}</button></div>`).join("")}</div>` : ""}
    ${!busy && it.kind === "image" ? `<button class="btn block" id="fix" ${alts.length ? "" : 'data-new="1"'}>Type the name myself</button>` : ""}
    ${!busy && best && best.title_id ? `<a class="btn primary block" href="#/t/${best.title_id}">Open in my list</a>` : ""}`;
  if (busy) every(1500, () => { if (location.hash === `#/item/${id}`) itemScreen(id); });
  bind("[data-pick]", "click", async (e, b) => { const r = await api(`/api/finds/${b.dataset.pick}/confirm`, { method: "POST", body: {} }); toast("Saved to your list"); location.hash = `#/t/${r.finds[0].title_id}`; });
  bind("#fix", "click", () => {
    if (alts.length) renameDialog(alts[0].id, (r) => { location.hash = `#/t/${r.finds[0].title_id}`; });
    else toast("Pick one of the guesses first, or wait for the search to finish");
  });
}

async function searchScreen() {
  const facets = await api("/api/facets");
  const langs = [...new Set(["English", "Japanese", "Korean", "Hindi", "Tamil", ...facets.languages])];
  const q = store("q") || "";
  const res = (await api("/api/search?" + filterQuery({ q }))).results;
  const n = activeCount();
  $app.innerHTML = `<div class="row"><label class="search grow"><span class="sr">Search</span><input id="q" type="search" value="${esc(q)}" placeholder="Title, creator, genre" autocomplete="off"></label>
      <a class="icon-btn" href="#/filters" aria-label="All filters${n ? ", " + n + " active" : ""}" style="position:relative">${ICON.filter}${n ? `<span class="tag" style="position:absolute;top:-4px;right:-4px;background:var(--accent);color:var(--on-accent);font-weight:700">${n}</span>` : ""}</a></div>
    <div class="stack" style="gap:8px"><span class="label">Language</span><div class="chips" id="langs">
      <button class="chip" data-lang="" aria-pressed="${!(filters.language || []).length}">All</button>${langs.map((l) => `<button class="chip" data-lang="${esc(l)}" aria-pressed="${(filters.language || []).includes(l)}">${esc(l)}</button>`).join("")}</div>
    <span class="label">Type</span><div class="chips"><button class="chip" data-type="" aria-pressed="${!(filters.type || []).length}">All</button>${["movie", "series", "anime", "manga", "book"].map((t) => `<button class="chip" data-type="${t}" aria-pressed="${(filters.type || []).includes(t)}">${TYPE_LABEL[t]}</button>`).join("")}</div></div>
    <span class="small muted" id="count">${res.length} ${res.length === 1 ? "result" : "results"}</span>
    <div class="stack" id="results">${res.length ? res.map(titleRow).join("") : `<div class="empty">Nothing matches. Try another language, type or word.</div>`}</div>`;
  let t = null;
  bind("#q", "input", (e, el) => { clearTimeout(t); t = setTimeout(async () => { store("q", el.value); await searchScreen(); const i = document.getElementById("q"); i.focus(); i.setSelectionRange(i.value.length, i.value.length); }, 300); });
  bind("[data-lang]", "click", (e, b) => { if (!b.dataset.lang) filters.language = []; else toggleIn("language", b.dataset.lang); saveFilters(); searchScreen(); });
  bind("[data-type]", "click", (e, b) => { if (!b.dataset.type) filters.type = []; else toggleIn("type", b.dataset.type); saveFilters(); searchScreen(); });
  bindWatchToggles(searchScreen);
}

async function filtersScreen() {
  const facets = await api("/api/facets");
  const groups = FILTER_GROUPS.map(([k, n, hint, opts]) => {
    let o = opts;
    if (k === "language") o = [...new Set([...opts, ...facets.languages])];
    if (k === "genre") o = [...new Set([...opts, ...facets.genres])].slice(0, 24);
    if (k === "reel_language") o = [...new Set([...opts, ...facets.reel_languages])];
    return [k, n, hint, o];
  });
  groups.push(["collection", "Collection", "", facets.collections]);
  const count = (await api("/api/search?" + filterQuery({ q: store("q") || "" }))).count;
  $app.innerHTML = `${header("Filters", "#/search", `<button class="btn" id="reset">Reset</button>`)}
    ${groups.map(([k, n, hint, opts]) => opts.length ? `<fieldset class="stack" style="border:0;margin:0;padding:0"><legend style="padding:0;margin-bottom:8px;font-weight:600">${n} <span class="muted" style="font-weight:400">${hint}</span></legend>
      <div class="chips wrap">${opts.map((v) => `<button class="chip" data-k="${k}" data-v="${esc(v)}" aria-pressed="${(filters[k] || []).includes(v)}">${esc(VALUE_LABEL[v] || v)}</button>`).join("")}</div></fieldset>` : "").join("")}
    <fieldset class="grid2" style="border:0;margin:0;padding:0"><legend style="padding:0;margin-bottom:8px;font-weight:600">Year</legend>
      <label class="field small muted">From<input class="input" id="yf" type="number" inputmode="numeric" value="${esc(filters.year_from || "")}" placeholder="1990"></label>
      <label class="field small muted">To<input class="input" id="yt" type="number" inputmode="numeric" value="${esc(filters.year_to || "")}" placeholder="2026"></label></fieldset>
    <label class="field">Sort by<select class="input" id="sort">${[["recent", "Recently saved"], ["most", "Most recommended (most saves)"], ["az", "Title A to Z"], ["newest", "Newest release"]]
      .map(([v, l]) => `<option value="${v}" ${filters.sort === v ? "selected" : ""}>${l}</option>`).join("")}</select></label>
    <a class="btn primary block" href="#/search" id="show">Show ${count} ${count === 1 ? "result" : "results"}</a>`;
  bind("[data-k]", "click", (e, b) => { toggleIn(b.dataset.k, b.dataset.v); filtersScreen(); });
  bind("#reset", "click", () => { filters = {}; saveFilters(); filtersScreen(); });
  bind("#yf", "change", (e, el) => { filters.year_from = el.value; saveFilters(); filtersScreen(); });
  bind("#yt", "change", (e, el) => { filters.year_to = el.value; saveFilters(); filtersScreen(); });
  bind("#sort", "change", (e, el) => { filters.sort = el.value; saveFilters(); });
}

let picked = store("pickedFolders") || [];
let folderOpts = store("folderOpts") || { skip_dupes: true, watch: true, collection: "Screenshots" };
async function folderScreen(path) {
  let d;
  try { d = await api("/api/fs" + (path ? "?path=" + enc(path) : "")); } catch (err) { toast(err.message); d = await api("/api/fs"); }
  const opts = [["skip_dupes", "Skip duplicate images", "Same picture saved twice is scanned once"], ["watch", "Watch these folders", "New screenshots are scanned automatically"]];
  $app.innerHTML = `${header("Scan a folder", "#/identify")}
    <div class="stack"><span class="label">Selected folders</span>
      ${picked.length ? picked.map((p, n) => `<div class="card row">${ICON.folder}<span class="grow" style="word-break:break-all">${esc(p)}</span><button class="icon-btn" data-rm="${n}" aria-label="Remove ${esc(p)}">✕</button></div>`).join("")
        : `<span class="small muted">None yet. Open a folder below and tap Select.</span>`}</div>
    <div class="card stack"><div class="row between"><span class="small muted" style="word-break:break-all">${esc(d.path || "Choose where to look")}</span>
      ${d.parent ? `<button class="btn" data-open="${esc(d.parent)}">Up</button>` : d.path ? `<button class="btn" data-open="">Top</button>` : ""}</div>
      ${d.path ? `<button class="btn primary" id="sel" ${picked.includes(d.path) ? "disabled" : ""}>${picked.includes(d.path) ? "Selected" : `Select this folder (${fmtN(d.images)} images here)`}</button>` : ""}
      <div class="stack" style="gap:4px;max-height:320px;overflow:auto">${d.dirs.map((x) => `<button class="btn" style="justify-content:flex-start" data-open="${esc(x.path)}">${ICON.folder}<span>${esc(x.name)}</span></button>`).join("") || `<span class="small muted">No folders inside.</span>`}</div></div>
    <div class="card"><label class="field">Collection name<input class="input" id="colname" value="${esc(folderOpts.collection)}"></label>
      ${opts.map(([k, l, n]) => `<div class="opt"><span class="grow"><span>${l}</span><br><span class="small muted">${n}</span></span>
        <button class="switch" role="switch" aria-label="${l}" aria-checked="${!!folderOpts[k]}" data-opt="${k}"><span></span></button></div>`).join("")}
      <p class="small muted">Chats, memes and receipts are put aside in "Other". Most names are read from the image text with no limit; the free scene search has a daily cap and continues the next day by itself.</p></div>
    <button class="btn primary block" id="start" ${picked.length ? "" : "disabled"}>Start scanning in background</button>`;
  bind("[data-open]", "click", (e, b) => { store("lastFolder", b.dataset.open); folderScreen(b.dataset.open); });
  bind("#sel", "click", () => { picked = [...picked, d.path]; store("pickedFolders", picked); folderScreen(d.path); });
  bind("[data-rm]", "click", (e, b) => { picked = picked.filter((_, n) => n !== Number(b.dataset.rm)); store("pickedFolders", picked); folderScreen(d.path); });
  bind("[data-opt]", "click", (e, b) => { folderOpts[b.dataset.opt] = !folderOpts[b.dataset.opt]; store("folderOpts", folderOpts); b.setAttribute("aria-checked", folderOpts[b.dataset.opt]); });
  bind("#colname", "change", (e, el) => { folderOpts.collection = el.value || "Screenshots"; store("folderOpts", folderOpts); });
  bind("#start", "click", async () => {
    try {
      await api("/api/folders", { method: "POST", body: { folders: picked, ...folderOpts } });
      picked = []; store("pickedFolders", picked);
      toast("Scanning in the background");
      location.hash = "#/progress";
    } catch (err) { toast(err.message); }
  });
}

async function progressScreen() {
  const d = await api("/api/jobs");
  const visible = d.jobs.slice(0, 12);
  const anyRunning = d.active.some((j) => j.state === "running");
  const groups = (c) => [["Names found", c.done || 0, "#9CCB8E", "#/search"], ["Check this", c.check || 0, "#F2B544", "#/check"],
    ["Waiting for free limit", c.waiting_quota || 0, "#7FB7E8", ""], ["Duplicates skipped", c.duplicate || 0, "#8E8B85", ""],
    ["Other (chats, memes)", c.other || 0, "#B6A3E8", ""], ["No name found", (c.skipped || 0) + (c.failed || 0), "#6E6B66", ""]].filter((g) => g[1]);
  $app.innerHTML = `${header("Running in background", "")}
    ${!d.engine ? `<div class="empty">The engine is off (started with --no-engine).</div>` : ""}
    ${d.warnings.map((w) => `<div class="card small" style="background:var(--warn-bg);color:var(--warn-fg)">${esc(w)}</div>`).join("")}
    ${d.active.length ? `<button class="btn block" id="all">${anyRunning ? "Pause all" : "Resume all"}</button>` : ""}
    ${visible.length ? visible.map((j) => `<div class="card stack">
        <div class="row between"><span class="label">${j.kind === "folder" ? "Screenshots" : j.kind === "quick" ? "Quick identify" : "Reels"}</span>
          <span class="small soft">${j.finished ? "Done" : j.scanning ? "Finding images" : j.state === "paused" ? "Paused" : "Running"}</span></div>
        <strong>${esc(j.name)}</strong>
        <div class="row" style="align-items:baseline;gap:8px"><span class="display" style="font-size:28px;font-weight:700">${fmtN(j.done)}</span><span class="muted">of ${fmtN(j.total)}</span></div>
        <div class="bar"><span style="width:${pct(j.done, j.total)}%"></span></div>
        <div class="stack" style="gap:2px">${groups(j.counts).map(([l, n, c, href]) => `<${href ? `a href="${href}"` : "div"} class="row" style="min-height:36px;color:var(--text)"><span class="dot" style="background:${c}"></span><span class="grow">${l}</span><strong>${fmtN(n)}</strong></${href ? "a" : "div"}>`).join("")}</div>
        ${j.finished ? "" : `<button class="btn" data-job="${j.id}" data-act="${j.state === "paused" ? "resume" : "pause"}">${j.state === "paused" ? "Resume" : "Pause"}</button>`}
      </div>`).join("") : `<div class="empty">Nothing is running. Start reading a collection, or scan a folder.<br><br><a class="btn" href="#/folder">Scan a folder</a></div>`}
    ${d.stages.length ? `<div class="small muted">${d.stages.map((s) => esc(s.worker.startsWith("image") ? "Screenshot: " + s.stage : "Reel: " + s.stage)).join("<br>")}</div>` : ""}
    <p class="small muted">You can close the app. Both jobs run side by side, keep going, and pick up where they stopped after a restart.</p>`;
  bind("[data-job]", "click", async (e, b) => { await api(`/api/jobs/${b.dataset.job}/${b.dataset.act}`, { method: "POST", body: {} }); progressScreen(); });
  bind("#all", "click", async () => { await api(`/api/jobs/all/${anyRunning ? "pause" : "resume"}`, { method: "POST", body: {} }); progressScreen(); });
  every(2500, () => { if (location.hash === "#/progress") progressScreen(); });
}

async function checkScreen() {
  const d = await api("/api/check");
  const byItem = {};
  for (const f of d.finds) (byItem[f.item_id] = byItem[f.item_id] || []).push(f);
  const items = Object.values(byItem);
  $app.innerHTML = `${header("Check this", "#/")}
    <span class="muted">Unsure guesses. Confirm the right one, fix the name, or remove it.</span>
    ${items.length ? items.map((fs) => `<div class="card stack"><div class="row" style="align-items:flex-start">${thumb(fs[0].thumb)}<div class="stack grow" style="gap:8px">
      ${fs.map((f) => `<div class="row between wrap"><span><strong>${esc(f.name || f.name_raw)}</strong><br><span class="small muted">${esc([TYPE_LABEL[f.type], f.year, SOURCE_LABEL[f.source]].filter(Boolean).join(" · "))}</span></span>
        <span class="row"><button class="btn" data-ok="${f.id}">Right</button><button class="btn danger" data-rm="${f.id}" aria-label="Not ${esc(f.name || f.name_raw)}">Not it</button></span></div>`).join("")}
      <button class="btn" data-fix="${fs[0].id}">Type the name myself</button></div></div></div>`).join("")
    : `<div class="empty">Nothing to check. Nice.</div>`}`;
  bind("[data-ok]", "click", async (e, b) => { await api(`/api/finds/${b.dataset.ok}/confirm`, { method: "POST", body: {} }); toast("Confirmed"); checkScreen(); });
  bind("[data-rm]", "click", async (e, b) => { await api(`/api/finds/${b.dataset.rm}`, { method: "DELETE", body: {} }); toast("Removed"); checkScreen(); });
  bind("[data-fix]", "click", (e, b) => renameDialog(b.dataset.fix, () => checkScreen()));
}

async function settingsScreen() {
  const s = await api("/api/settings");
  $app.innerHTML = `${header("Settings", "#/")}
    <div class="card"><div class="opt"><span class="grow"><span>Online lookups</span><br><span class="small muted">AniList, Wikidata, trace.moe, SauceNAO. All free; needed to confirm names.</span></span>
      <button class="switch" role="switch" aria-label="Online lookups" aria-checked="${!!s.online}" id="online"><span></span></button></div></div>
    <div class="card stack"><strong>Use it on your phone</strong>
      <span class="small soft">Phone only: install it on the phone (see README, "Phone without a PC") and open http://localhost:8765.<br>
      With your PC: run <code>reel-watcher app --lan</code> on the PC and scan the QR code it shows. Then use your browser's "Add to Home screen".</span></div>
    <a class="btn" href="/api/export.csv">Export everything (CSV)</a>`;
  bind("#online", "click", async (e, b) => { const on = b.getAttribute("aria-checked") !== "true"; await api("/api/settings", { method: "POST", body: { online: on } }); b.setAttribute("aria-checked", on); toast(on ? "Online lookups on" : "Online lookups off"); });
}

// ------------------------------------------------------------------ router

const ROUTES = [
  [/^#?\/?$/, homeScreen, "home"], [/^#\/import$/, importScreen, "home"], [/^#\/c\/(.+)$/, (m) => collectionScreen(decodeURIComponent(m[1])), "home"],
  [/^#\/t\/(\d+)$/, (m) => titleScreen(m[1]), "search"], [/^#\/q\/(\d+)$/, (m) => quoteScreen(m[1]), "home"],
  [/^#\/identify$/, identifyScreen, "identify"], [/^#\/item\/(\d+)$/, (m) => itemScreen(m[1]), "identify"], [/^#\/folder$/, () => folderScreen(store("lastFolder")), "identify"],
  [/^#\/search$/, searchScreen, "search"], [/^#\/filters$/, filtersScreen, "search"], [/^#\/progress$/, progressScreen, "progress"],
  [/^#\/check$/, checkScreen, "home"], [/^#\/settings$/, settingsScreen, "home"],
];

async function render() {
  timers.forEach(clearInterval);
  timers = [];
  const h = location.hash || "#/";
  for (const [rx, fn, tab] of ROUTES) {
    const m = h.match(rx);
    if (!m) continue;
    document.querySelectorAll("nav.tabs a").forEach((a) => (a.dataset.tab === tab ? a.setAttribute("aria-current", "page") : a.removeAttribute("aria-current")));
    try { await fn(m); } catch (err) { $app.innerHTML = `<div class="empty">${esc(err.message)}<br><br><a class="btn" href="#/">Back to Shelf</a></div>`; }
    return;
  }
  location.hash = "#/";
}

window.addEventListener("hashchange", () => { render(); window.scrollTo(0, 0); });
render();
if ("serviceWorker" in navigator && (location.protocol === "https:" || location.hostname === "localhost" || location.hostname === "127.0.0.1")) {
  navigator.serviceWorker.register("/sw.js").catch(() => {});
}
