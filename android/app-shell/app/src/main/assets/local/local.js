/* Reel Shelf, built into the Android app: no Termux, no PC, nothing else to install.
   Sharing a reel only saves it. Work happens only while this screen is open and you tap Start:
   the caption is read from the reel's public page, then the AI model on the phone writes the notes.
   Or tap Ask Meta AI and share its answer back. Leaving the app stops everything (onAppPause). */
"use strict";

const $app = document.getElementById("app");
const $toast = document.getElementById("toast");
const $dlg = document.getElementById("dlg");
const RN = window.RN || null;
let toastTimer = null;

// ------------------------------------------------------------------ helpers (same look as the old app)

function esc(v) {
  return String(v == null ? "" : v).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}
const enc = encodeURIComponent;
function toast(msg) {
  $toast.textContent = msg;
  $toast.classList.add("show");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => $toast.classList.remove("show"), 3600);
}
function bind(sel, ev, fn) { $app.querySelectorAll(sel).forEach((el) => el.addEventListener(ev, (e) => fn(e, el))); }
const ICON = {
  back: '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" aria-hidden="true"><path d="M15 6l-6 6 6 6"/></svg>',
  chev: '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="#8E8B85" stroke-width="2" stroke-linecap="round" aria-hidden="true"><path d="M9 6l6 6-6 6"/></svg>',
  check: '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#15161A" stroke-width="3" stroke-linecap="round" aria-hidden="true"><path d="M5 12l4 4L19 6"/></svg>',
  play: '<svg width="22" height="22" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><path d="M7 5l12 7-12 7z"/></svg>',
  search: '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="#A3A09A" stroke-width="2" stroke-linecap="round" aria-hidden="true"><circle cx="11" cy="11" r="7"/><path d="M20 20l-3.5-3.5"/></svg>',
};
function header(title, back) {
  return `<div class="row">${back ? `<a class="icon-btn" href="${esc(back)}" aria-label="Back">${ICON.back}</a>` : ""}<h1>${esc(title)}</h1></div>`;
}
function mb(n) { return n > 0 ? (n / 1048576 >= 1024 ? (n / 1073741824).toFixed(2) + " GB" : Math.round(n / 1048576) + " MB") : "0 MB"; }
function day(ts) { return new Date(ts || 0).toLocaleDateString(undefined, { day: "numeric", month: "short" }); }
function plural(n, one, many) { return `${n} ${n === 1 ? one : many || one + "s"}`; }

// ------------------------------------------------------------------ the phone (window.RN), with promises

let seq = 0;
const waits = {};
const onProgress = {};
window.rnDone = (id, ok, text) => {
  const w = waits[id];
  if (!w) return;
  delete waits[id];
  if (ok) w.res(text); else w.rej(new Error(text));
};
window.rnProgress = (kind, done, total) => { (onProgress[kind] || (() => {}))(done, total); };
function phone(method, ...args) {
  return new Promise((res, rej) => {
    if (!RN || typeof RN[method] !== "function") { rej(new Error("Open this inside the Reel Shelf app")); return; }
    const id = ++seq;
    waits[id] = { res, rej };
    try { RN[method](id, ...args); } catch (e) { delete waits[id]; rej(e); }
  });
}
function sync(method, ...args) {
  if (!RN || typeof RN[method] !== "function") return null;
  try { return RN[method](...args); } catch (e) { return null; }
}

// ------------------------------------------------------------------ library and settings

let db = { reels: [], inbox: [] };
function loadDb() {
  const t = sync("load");
  if (t) {
    try {
      const d = JSON.parse(t);
      db = { reels: d.reels || [], inbox: d.inbox || [] };
      for (const r of db.reels) if (r.status === "working") r.status = r.notes ? "done" : "new";  // the app was closed mid-way
    } catch (e) { toast("Your library file could not be read"); } }
}
function saveDb() { if (sync("store", JSON.stringify(db)) === false) toast("Could not save. Is the phone's storage full?"); }
function reel(code) { return db.reels.find((r) => r.code === code); }

const MODELS = [
  { id: "qwen", name: "Qwen2.5 1.5B", file: "Qwen2.5-1.5B-Instruct_multi-prefill-seq_q8_ekv4096.litertlm",
    url: "https://huggingface.co/litert-community/Qwen2.5-1.5B-Instruct/resolve/main/Qwen2.5-1.5B-Instruct_multi-prefill-seq_q8_ekv4096.litertlm",
    size: 1.6e9, note: "Free, about 1.6 GB, good for English notes. Needs a phone with 6 GB of RAM or more." },
  { id: "gemma4", name: "Gemma 4 E2B (better notes)", file: "gemma-4-E2B-it.litertlm",
    url: "https://huggingface.co/litert-community/gemma-4-E2B-it-litert-lm/resolve/main/gemma-4-E2B-it.litertlm",
    size: 2.58e9, note: "Free, about 2.6 GB. Google's on-phone model, tuned for summarizing and rewriting; follows the notes format better. Slower to download, uses more battery per reel." },
];
const DEFAULTS = { modelFile: MODELS[0].file, gpu: true, maxTokens: 800, temperature: 0.3, prompt: Notes.META_PROMPT, localExtra: "" };
let settings = { ...DEFAULTS };
function loadSettings() { try { settings = { ...DEFAULTS, ...JSON.parse(sync("getSettings") || "{}") }; } catch (e) { settings = { ...DEFAULTS }; } }
function saveSettings() { sync("setSettings", JSON.stringify(settings)); }
function modelInfo() { try { return JSON.parse(sync("modelInfo", settings.modelFile) || "{}"); } catch (e) { return {}; } }

// ------------------------------------------------------------------ adding reels and answers

function addReels(found, how) {
  let added = 0;
  for (const f of found) {
    const cur = reel(f.code);
    if (cur) {
      for (const c of f.collections || []) if (!(cur.collections || []).includes(c)) (cur.collections = cur.collections || []).push(c);
      continue;
    }
    db.reels.unshift({ code: f.code, url: f.url, author: f.author || "", collections: f.collections || [], status: "new", added_at: Date.now(), added_by: how });
    added++;
  }
  saveDb();
  return added;
}

/** An answer in the notes format: filed under the reel it names, else the reel you last asked Meta AI about. */
function fileAnswer(text, by = "meta", target = null, standalone = false) {
  const parts = Notes.splitAnswers(text);
  if (!parts.length) return { filed: 0, inbox: 0 };
  let filed = 0;
  let inbox = 0;
  for (const p of parts) {
    let r = target ? reel(target) : null;
    if (!r && p.links.length) {
      r = reel(p.links[0].code);
      if (!r) { addReels([p.links[0]], "answer"); r = reel(p.links[0].code); }
    }
    if (!r && parts.length === 1 && !standalone) {
      const asked = db.reels.filter((x) => x.asked_at && !(x.notes && x.notes_by === "meta")).sort((a, b) => b.asked_at - a.asked_at)[0];
      if (asked && Date.now() - asked.asked_at < 3 * 86400e3) r = asked;
    }
    if (!r && (parts.length > 1 || standalone)) {  // pasted answers without links: keep each one as its own note
      const code = "note-" + Date.now().toString(36) + "-" + filed;
      db.reels.unshift({ code, url: "", author: "", collections: [], status: "new", added_at: Date.now(), added_by: "paste" });
      r = reel(code);
    }
    if (!r) { db.inbox.push({ text: p.text, at: Date.now() }); inbox++; continue; }
    setNotes(r, p.notes, by, p.text);
    filed++;
  }
  saveDb();
  return { filed, inbox };
}

function setNotes(r, notes, by, raw) {
  r.notes = notes;
  r.notes_by = by;
  r.notes_at = Date.now();
  r.status = "done";
  r.error = "";
  if (raw) r.raw = String(raw).slice(0, 20000);
}

/** Things shared to Reel Shelf while it was closed (reel links, Meta AI answers). */
function takeShared() {
  let items = [];
  try { items = JSON.parse(sync("takeShared") || "[]"); } catch (e) { items = []; }
  let reels = 0;
  let answers = 0;
  let waiting = 0;
  let other = 0;
  for (const it of items) {
    const text = String(it.text || "");
    if (Notes.parse(text)) { const r = fileAnswer(text, "meta"); answers += r.filed; waiting += r.inbox; continue; }
    const found = Notes.links(text);
    if (found.length) reels += addReels(found, "share"); else other++;
  }
  const msg = [reels && `${plural(reels, "new reel")} saved`, answers && `${plural(answers, "Meta AI answer")} filed`,
    waiting && `${plural(waiting, "answer")} to file`, other && `${plural(other, "share")} had no reel link`].filter(Boolean).join(", ");
  if (msg) toast(msg);
  return items.length;
}

/** Saved-posts files from Instagram's data download ([{name, text}]): every reel, with collections as labels. */
function importParts(parts) {
  parts = parts.slice().sort((a, b) => /collection/i.test(a.name) - /collection/i.test(b.name));  // labels last
  let rows = [];
  for (const p of parts) rows = rows.concat(Notes.exportFile(p.name, p.text));
  return { found: rows.length, added: addReels(rows, "export") };
}

/** The export the in-app Instagram page downloaded, if it just came back. */
function takeInstagramExport() {
  let parts = [];
  try { parts = JSON.parse(sync("takeInstagramExport") || "[]"); } catch (e) { parts = []; }
  if (!Array.isArray(parts) || !parts.length) return false;
  const r = importParts(parts.filter((p) => p && typeof p.name === "string" && typeof p.text === "string"));
  toast(`From Instagram: ${plural(r.added, "new reel")} saved (${r.found} in your saved posts). Tap Start when you want notes.`);
  return true;
}

// ------------------------------------------------------------------ Start: work only while the app is open

let run = null;  // {codes, i, step, stop, done, failed, current}

function needsWork(r, ready) {
  if (r.notes && !(r.notes_by === "auto" && ready)) return false;
  if (!r.url) return false;
  if (!r.caption_read) return true;
  return ready && Notes.material(r) >= 30 && r.status !== "ready_no_text";
}

/** A YouTube Short or video: title, description and the spoken words (its captions), with no key and no login. */
async function readYoutube(r) {
  const key = Notes.ytKey(await phone("fetchPage", Notes.ytWatchUrl(r)));
  const got = Notes.ytPick(JSON.parse(await phone("postJson", Notes.ytPlayerUrl(key), Notes.ytPlayerBody(r)) || "{}"));
  if (got.title) r.title = got.title.slice(0, 300);
  if (got.author) r.author = got.author;
  if (got.description) r.caption = got.description.slice(0, 8000);
  if (got.track && !got.blocked) {
    const said = Notes.ytCaptions(await phone("fetchPage", got.track));
    if (said) r.transcript = said.slice(0, 40000);
  }
  if (!r.transcript) r.error = got.why || "YouTube did not give the spoken words for this video.";
}

async function readCaption(r) {
  if (!r.url) return;
  if (Notes.isYoutube(r)) {
    try { await readYoutube(r); } catch (e) { r.error = e.message; }
    r.caption_read = Date.now();
    r.keywords = Notes.keywords([r.title, r.caption, r.transcript].join("\n"), 10);
    return;
  }
  try {
    const html = await phone("fetchPage", Notes.embedUrl(r.code));
    const got = Notes.readPage(html);
    if (got.caption) r.caption = got.caption.slice(0, 8000);
    if (got.author) r.author = got.author;
  } catch (e) {
    r.error = e.message;
  }
  if (!r.caption) {  // the embed page did not have it: the reel's own page sometimes has it in its description
    try {
      const got = Notes.readPage(await phone("fetchPage", r.url));
      if (got.caption) r.caption = got.caption.slice(0, 8000);
      if (got.author && !r.author) r.author = got.author;
    } catch (e) { /* offline or refused: keep going */ }
  }
  r.caption_read = Date.now();
  r.keywords = Notes.keywords(r.caption || "", 10);
}

/** Notes without any AI (the best sentences, keywords as tags), so every reel can be found in the library. */
function writeWithoutAi(r) {
  const n = Notes.autoNotes(r, db.reels);
  if (!n) return false;
  setNotes(r, n, "auto");
  return true;
}

async function writeWithPhoneAi(r) {
  const out = JSON.parse(await phone("generate", Notes.localPrompt(r, settings.localExtra),
    JSON.stringify({ file: settings.modelFile, gpu: settings.gpu, system: Notes.LOCAL_SYSTEM, maxTokens: settings.maxTokens, temperature: settings.temperature })));
  const notes = Notes.parse(out.text);
  if (!notes) throw new Error("The on-phone AI's answer was not in the notes format. Try again, or Ask Meta AI.");
  setNotes(r, notes, "phone", out.text);
  return out;
}

async function startRun(codes) {
  if (run && !run.finished) { location.hash = "#/run"; return; }
  const ready = !!modelInfo().ready;
  const list = (codes || db.reels.filter((r) => needsWork(r, ready)).map((r) => r.code)).filter((c) => reel(c));
  run = { codes: list, i: 0, step: "", stop: false, done: 0, failed: 0, current: "", finished: false, log: [], ready };
  sync("allowWork");
  location.hash = "#/run";
  render();
  for (; run.i < run.codes.length && !run.stop; run.i++) {
    const r = reel(run.codes[run.i]);
    if (!r) continue;
    run.current = r.code;
    r.status = "working";
    r.error = "";
    try {
      if (!r.caption_read) {
        run.step = "caption";
        paintRun();
        await readCaption(r);
        saveDb();
      }
      if (run.stop) { r.status = r.notes ? "done" : "new"; break; }
      if (run.ready && (!r.notes || r.notes_by === "auto")) {
        if (Notes.material(r) < 30) {
          r.status = "ready_no_text";
          r.error = "Instagram did not give enough text to work from. Ask Meta AI, or type what the reel says.";
        } else {
          run.step = "ai";
          paintRun();
          await writeWithPhoneAi(r);
          run.done++;
        }
      } else if (!r.notes) {
        if (Notes.material(r) >= 30) writeWithoutAi(r);
        else r.status = Notes.isYoutube(r) ? "ready_no_text" : "ready";
      }
      if (r.notes) r.status = "done";
    } catch (e) {
      if (run.stop || e.message === "stopped") { r.status = "new"; break; }
      r.status = "failed";
      r.error = e.message;
      run.failed++;
    }
    run.log.unshift({ code: r.code, ok: r.status === "done", text: r.status === "done" ? (r.notes.topic || "Notes written") : r.error || "Caption read" });
    saveDb();
    paintRun();
  }
  run.finished = true;
  run.step = "";
  sync("stopModel");  // free the model's memory as soon as the work is done
  saveDb();
  paintRun();
}

function stopRun() {
  if (!run || run.finished) return;
  run.stop = true;
  sync("stopModel");
}

window.onAppPause = () => {  // the app left the screen: nothing keeps running
  if (run && !run.finished) { run.paused = true; stopRun(); }
};
window.onAppResume = () => {
  const fromIg = takeInstagramExport();
  if (takeShared() || fromIg) render();
  else if (location.hash === "#/settings") render();
};

// ------------------------------------------------------------------ screens

const STATUS = {
  new: ["Not read yet", ""], working: ["Working...", "warn"], ready: ["Ready for Meta AI", "warn"], ready_no_text: ["Needs Meta AI", "warn"],
  failed: ["Could not finish", "warn"], done: ["Notes", "ok"],
};
const BY = { meta: "Notes by Meta AI", phone: "Notes by the on-phone AI (from the caption)", you: "Your notes",
  auto: "Quick notes without AI: the key sentences of the caption or transcript" };
let filter = { q: "", tag: "" };

function homeScreen() {
  const ready = !!modelInfo().ready;
  const todo = db.reels.filter((r) => needsWork(r, ready));
  const tags = {};
  for (const r of db.reels) for (const t of (r.notes || {}).tags || []) tags[t] = (tags[t] || 0) + 1;
  const top = Object.entries(tags).sort((a, b) => b[1] - a[1]).slice(0, 14).map(([t]) => t);
  const running = run && !run.finished;
  $app.innerHTML = `
    <div class="brand">Reel Shelf</div>
    <h1>Your reel notes</h1>
    <label class="search">${ICON.search}<input id="q" type="search" placeholder="Search topics, points, tools, tags" value="${esc(filter.q)}" aria-label="Search"></label>
    ${db.inbox.length ? `<a class="card accent" href="#/inbox"><span class="grow"><strong>${plural(db.inbox.length, "Meta AI answer")} to file</strong><br><span>Pick the reel each one belongs to</span></span></a>` : ""}
    ${running ? `<a class="card accent" href="#/run"><span class="coll-icon" style="background:#15161A;color:#F2B544">${ICON.play}</span><span class="grow"><strong>Working: ${run.i + 1} of ${run.codes.length}</strong><br><span>Keep the app open</span></span></a>`
      : todo.length ? `<button class="card accent" id="start"><span class="coll-icon" style="background:#15161A;color:#F2B544">${ICON.play}</span><span class="stack grow" style="gap:2px">
        <strong style="font-size:17px">Start: ${plural(todo.length, "reel")}</strong><span>${ready ? "Reads each caption and writes the notes on this phone" : "Reads each caption. Download the AI model in Settings to write notes too"}</span></span></button>` : ""}
    ${forMeta().length > 1 && !running ? `<button class="card" id="batch"><span class="grow stack" style="gap:2px"><strong>Ask Meta AI about ${Math.min(BATCH, forMeta().length)} reels at once</strong><span class="small muted">One message instead of ${Math.min(BATCH, forMeta().length)}. Share its answer back and each part is filed.</span></span>${ICON.chev}</button>` : ""}
    ${top.length ? `<div class="chips"><button class="chip" data-tag="" aria-pressed="${!filter.tag}">All</button>${top.map((t) => `<button class="chip" data-tag="${esc(t)}" aria-pressed="${filter.tag === t}">#${esc(t)}</button>`).join("")}</div>` : ""}
    <div class="stack" id="list">${listHtml()}</div>`;
  bind("#q", "input", (e, el) => { filter.q = el.value; document.getElementById("list").innerHTML = listHtml(); });
  bind("[data-tag]", "click", (e, b) => { filter.tag = b.dataset.tag; homeScreen(); });
  bind("#start", "click", () => startRun());
  bind("#batch", "click", askMetaBatch);
}


function listHtml() {
  const q = filter.q.trim();
  let shown = db.reels.filter((r) => !filter.tag || ((r.notes || {}).tags || []).includes(filter.tag));
  if (q) {  // ranked like a search engine: best match first, typos and similar words allowed
    const plain = q.toLowerCase();
    const hits = Lib.find(shown, q, 200);
    const seen = new Set(hits.map((h) => h.reel));
    // a name or link typed exactly also counts
    const exact = shown.filter((r) => !seen.has(r) && [r.author, r.url, r.code].join(" ").toLowerCase().includes(plain));
    shown = [...hits.map((h) => h.reel), ...exact];
  }
  return db.reels.length ? (shown.length ? shown.map(reelRow).join("") : `<div class="empty">Nothing matches. Try other words, or <a href="#/ask?q=${enc(q)}">ask your library</a>.</div>`) : emptyShelf();
}

/** Instagram reels Meta AI has not done yet (YouTube is read on the phone instead). */
function forMeta() {
  return db.reels.filter((r) => r.url && !Notes.isYoutube(r) && (!r.notes || r.notes_by === "auto") && !(r.asked_at && Date.now() - r.asked_at < 86400e3));
}
const BATCH = 5;
function askMetaBatch() {
  const list = forMeta().slice(0, BATCH);
  if (!list.length) return;
  if (list.length === 1) { askMeta(list[0]); return; }
  const text = Notes.batchPrompt(list);
  sync("copy", text);
  for (const r of list) r.asked_at = Date.now();
  saveDb();
  sync("shareText", text, "Ask Meta AI");
  toast(`Asked about ${list.length} reels in one message. Share Meta AI's whole answer back to Reel Shelf: each part is filed under its reel.`);
}

function emptyShelf() {
  return `<div class="empty stack" style="text-align:left">
    <strong style="color:var(--text)">Share a reel to start</strong>
    <span>In Instagram, tap the share arrow on a reel, then <strong>Reel Shelf</strong>. It is saved here; nothing runs until you open the app and tap Start.</span>
    <span>Have many saved reels? <a href="#/add">Add them in one go</a>.</span></div>`;
}

function reelRow(r) {
  const n = r.notes || {};
  const [label, kind] = STATUS[r.status] || STATUS.new;
  const title = n.topic || (r.caption ? r.caption.split("\n")[0].slice(0, 90) : r.author ? `Reel by @${r.author}` : r.url ? "Reel " + r.code : "Note");
  return `<a class="list-item" href="#/r/${enc(r.code)}"><span class="grow stack" style="gap:4px"><span class="title clamp">${esc(title)}</span>
    <span class="small muted">${esc([r.author ? "@" + r.author : "", day(r.added_at), ...(r.collections || []).slice(0, 1)].filter(Boolean).join(" · "))}</span>
    ${(n.tags || []).length ? `<span class="tagrow">${n.tags.slice(0, 4).map((t) => `<span class="tag">#${esc(t)}</span>`).join("")}</span>` : ""}</span>
    <span class="tag ${kind}">${esc(label)}</span></a>`;
}

function notesHtml(n) {
  const sec = (label, body) => body ? `<div class="note-block"><span class="label">${label}</span>${body}</div>` : "";
  const ol = (a) => a && a.length ? `<ol>${a.map((x) => `<li>${esc(x)}</li>`).join("")}</ol>` : "";
  const ul = (a) => a && a.length ? (a.length === 1 ? `<p>${esc(a[0])}</p>` : `<ul>${a.map((x) => `<li>${esc(x)}</li>`).join("")}</ul>`) : "";
  return `<div class="card stack" style="gap:14px">
    ${sec("Topic", n.topic ? `<p><strong>${esc(n.topic)}</strong></p>` : "")}
    ${sec("Points", ol(n.points))}
    ${sec("Meaning", n.meaning ? `<p>${esc(n.meaning)}</p>` : "")}
    ${sec("Use it for", ul(n.use))}
    ${sec("Tools", (n.tools || []).length ? `<p>${esc(n.tools.join(", "))}</p>` : "")}
    ${sec("Takeaway", n.takeaway ? `<p>${esc(n.takeaway)}</p>` : "")}
    ${sec("Tags", (n.tags || []).length ? `<span class="tagrow">${n.tags.map((t) => `<span class="tag">#${esc(t)}</span>`).join("")}</span>` : "")}</div>`;
}

function reelScreen(code) {
  const r = reel(code);
  if (!r) { $app.innerHTML = `${header("Not found", "#/")}<div class="empty">This reel is no longer in your shelf.</div>`; return; }
  const ready = !!modelInfo().ready;
  const n = r.notes;
  const [label, kind] = STATUS[r.status] || STATUS.new;
  $app.innerHTML = `${header(n && n.topic ? "Reel notes" : "Reel", "#/")}
    <div class="stack" style="gap:6px"><span class="row wrap" style="gap:8px"><span class="tag ${kind}">${esc(label)}</span>${n ? `<span class="small muted">${esc(BY[r.notes_by] || "")}</span>` : ""}</span>
      <span class="small muted">${esc([r.author ? "@" + r.author : "", "saved " + day(r.added_at), ...(r.collections || [])].filter(Boolean).join(" · "))}</span></div>
    ${r.error && !n ? `<div class="card small">${esc(r.error)}</div>` : ""}
    ${n ? notesHtml(n) : `<div class="card stack"><strong>No notes yet</strong><span class="small muted">Ask Meta AI (best: it watches the whole reel), or ${ready ? "let the on-phone AI write them from the caption" : "download the on-phone AI in Settings"}.</span></div>`}
    <div class="grid2">
      ${r.url ? `<button class="btn ${n && r.notes_by !== "auto" ? "" : "primary"}" id="meta">Ask Meta AI</button>` : ""}
      <button class="btn" id="paste">Paste an answer</button>
      ${r.url ? `<button class="btn" id="open">Open in ${Notes.isYoutube(r) ? "YouTube" : "Instagram"}</button>` : ""}
      ${n ? `<button class="btn" id="copy">Copy notes</button>` : ""}
      ${ready && r.url ? `<button class="btn" id="phoneai">${n ? "Redo with phone AI" : "Write with phone AI"}</button>` : ""}
    </div>
    ${r.asked_at && !(n && r.notes_by === "meta") ? `<p class="hint">When Meta AI answers, tap Share on its answer and choose Reel Shelf. It will be filed here.</p>` : ""}
    ${r.caption ? `<details class="card"><summary><strong>${Notes.isYoutube(r) ? "Description" : "Caption"}</strong></summary><p class="pre small" style="margin-top:8px">${esc(r.caption)}</p></details>` : ""}
    ${r.transcript ? `<details class="card"><summary><strong>What is said (from YouTube's captions)</strong></summary><p class="pre small" style="margin-top:8px">${esc(r.transcript)}</p></details>` : ""}
    ${relatedHtml(r)}
    <details class="card" ${r.extra ? "open" : ""}><summary><strong>What the reel says (optional)</strong></summary>
      <div class="stack" style="margin-top:8px"><p class="hint">The phone's AI cannot watch the video. Type or paste what is said or shown, and it will use it.</p>
      <textarea class="input" id="extra" placeholder="e.g. the steps shown on screen">${esc(r.extra || "")}</textarea>
      <button class="btn" id="saveExtra">Save</button></div></details>
    <button class="btn block danger" id="del">Remove from shelf</button>`;
  bind("#meta", "click", () => askMeta(r));
  bind("#open", "click", () => sync("openUrl", r.url));
  bind("#copy", "click", () => { sync("copy", Notes.format(n) + (r.url ? `\n\nReel: ${r.url}` : "")); toast("Notes copied"); });
  bind("#paste", "click", () => pasteDialog(r));
  bind("#saveExtra", "click", () => { r.extra = document.getElementById("extra").value.slice(0, 10000); if (!r.notes && r.status === "ready_no_text") r.status = "ready"; saveDb(); toast("Saved"); reelScreen(code); });
  bind("#phoneai", "click", () => startRun([r.code]).then(() => {}));
  bind("#del", "click", () => { if (confirm("Remove this reel and its notes from Reel Shelf?")) { db.reels = db.reels.filter((x) => x !== r); saveDb(); location.hash = "#/"; } });
}

function relatedHtml(r) {
  const rel = Notes.related(db.reels, r, 4);
  const t = Lib.topics(db.reels).find((x) => x.reels.includes(r));
  const topicLink = t ? `<a class="chip" href="#/topic/${enc(t.key)}">Topic: ${esc(t.label)} (${t.reels.length})</a>` : "";
  return rel.length || t ? `<div class="stack"><h2>Related reels</h2>${topicLink ? `<div class="chips">${topicLink}</div>` : ""}${rel.map((x) => reelRow(x.reel)).join("")}</div>` : "";
}

// ------------------------------------------------------------------ topics: reels grouped by what they are about (no AI)

function titleOf(r) { const n = r.notes || {}; return n.topic || r.title || (r.caption || "").split("\n")[0].slice(0, 90) || r.code; }

function libraryOverview() {
  const groups = Lib.topics(db.reels).slice(0, 12);
  const tl = Lib.tools(db.reels).filter((t) => t.count > 1).slice(0, 16);
  return `${groups.length ? `<div class="stack"><h2>Topics you learned</h2>${groups.map((g) => `<a class="list-item" href="#/topic/${enc(g.key)}"><span class="grow stack" style="gap:4px">
      <span class="title">${esc(g.label)}</span><span class="small muted clamp">${esc(g.reels.slice(0, 3).map(titleOf).join(" · "))}</span></span>
      <span class="tag">${g.reels.length}</span></a>`).join("")}</div>` : ""}
    ${tl.length ? `<div class="stack"><h2>Tools you saw most</h2><div class="chips wrap">${tl.map((t) => `<a class="chip" href="#/ask?q=${enc('"' + t.name + '"')}">${esc(t.name)} ${t.count}</a>`).join("")}</div></div>` : ""}`;
}

function topicScreen(key) {
  const g = Lib.topic(db.reels, key);
  if (!g) { $app.innerHTML = `${header("Topic", "#/ask")}<div class="empty">This topic changed as your library grew. <a href="#/ask">See all topics</a>.</div>`; return; }
  const takeaways = g.reels.filter((r) => (r.notes || {}).takeaway);
  const tl = Lib.tools(g.reels).slice(0, 12);
  $app.innerHTML = `${header(g.label, "#/ask")}
    <p class="hint">${plural(g.reels.length, "reel")} about the same thing, grouped by the words they share. No AI.</p>
    <div class="chips wrap">${g.words.map((w) => `<a class="chip" href="#/ask?q=${enc(w)}">${esc(w)}</a>`).join("")}</div>
    ${takeaways.length ? `<div class="card stack" style="gap:8px"><span class="label">What you learned</span><ul style="margin:0;padding-left:18px;line-height:1.5">${takeaways.map((r) => `<li><a href="#/r/${enc(r.code)}">${esc(r.notes.takeaway)}</a></li>`).join("")}</ul></div>` : ""}
    ${tl.length ? `<div class="card stack" style="gap:8px"><span class="label">Tools</span><p style="margin:0">${esc(tl.map((t) => t.name + (t.count > 1 ? ` (${t.count})` : "")).join(", "))}</p></div>` : ""}
    <div class="stack">${g.reels.map(reelRow).join("")}</div>`;
}

// ------------------------------------------------------------------ Ask: your library answers

let lastAsk = { q: "", answer: null, results: [] };

function askScreen() {
  const fromUrl = (location.hash.match(/[?&]q=([^&]*)/) || [])[1];
  if (fromUrl !== undefined) { const q = decodeURIComponent(fromUrl); if (q !== lastAsk.q) lastAsk = { q, answer: null, results: [] }; }
  const ready = !!modelInfo().ready;
  const q = lastAsk.q;
  const results = q ? Lib.find(db.reels, q, 8) : [];
  const fix = q && results.length < 3 ? Lib.didYouMean(db.reels, q) : null;
  lastAsk.results = results;
  const mark = (s) => Lib.highlight(s, q);
  $app.innerHTML = `${header("Ask your library", "")}
    <form class="stack" id="askf"><label class="search">${ICON.search}<input id="aq" type="search" enterkeyhint="search" placeholder="e.g. how do I keep API keys safe?" value="${esc(q)}" aria-label="Question"></label></form>
    ${!q ? `<p class="hint">Search everything you saved, like a search engine for what you learned. It works without any AI: it ranks your notes by the words you type, allows typos and similar words (phone, mobile, android), and shows the lines that answer it. Use "exact words", -word to leave a word out, and #tag to keep one tag.</p>${libraryOverview()}` : ""}
    ${fix ? `<p class="small">Did you mean <a href="#/ask?q=${enc(fix)}" id="fix">${esc(fix)}</a>?</p>` : ""}
    ${q && !results.length ? `<div class="empty">Nothing in your library about that yet.</div>` : ""}
    ${lastAsk.answer ? `<div class="card stack"><span class="label">Answer from your notes${lastAsk.answer.by ? ` (${esc(lastAsk.answer.by)})` : ""}</span><p class="pre">${esc(lastAsk.answer.text).replace(/\[(\d{1,2})\]/g, (m, i) => results[i - 1] ? `<a href="#/r/${enc(results[i - 1].reel.code)}">[${i}]</a>` : m)}</p></div>` : ""}
    ${results.length ? `<div class="grid2">${ready ? `<button class="btn primary" id="aiAns">Answer with phone AI</button>` : ""}<button class="btn" id="copyAsk">Ask any AI with these notes</button></div>` : ""}
    <div class="stack">${results.map((x, i) => {
      const r = x.reel;
      const n = r.notes || {};
      const title = n.topic || r.title || (r.caption || "").split("\n")[0].slice(0, 90) || r.code;
      return `<a class="card stack" href="#/r/${enc(r.code)}" style="gap:6px"><span class="row between"><strong class="clamp">[${i + 1}] ${esc(title)}</strong>${ICON.chev}</span>
        ${x.lines.length ? `<ul class="small" style="margin:0;padding-left:18px">${x.lines.map((l) => `<li>${mark(l)}</li>`).join("")}</ul>` : ""}
        <span class="small muted">${esc([r.author ? "@" + r.author : "", (n.tags || []).slice(0, 3).map((t) => "#" + t).join(" ")].filter(Boolean).join(" · "))}</span></a>`;
    }).join("")}</div>`;
  const input = document.getElementById("aq");
  document.getElementById("askf").addEventListener("submit", (e) => { e.preventDefault(); const nq = input.value.trim(); lastAsk = { q: nq, answer: null, results: [] }; if (location.hash === `#/ask?q=${enc(nq)}`) askScreen(); else location.hash = `#/ask?q=${enc(nq)}`; });
  bind("#copyAsk", "click", () => { const t = Notes.answerPrompt(q, results.slice(0, 6)); sync("copy", t); sync("shareText", t, "Ask an AI"); toast("Question and your notes copied"); });
  bind("#aiAns", "click", async (e, b) => {
    b.disabled = true;
    b.textContent = "Thinking... keep the app open";
    sync("allowWork");
    try {
      const out = JSON.parse(await phone("generate", Notes.answerPrompt(q, results.slice(0, 5)),
        JSON.stringify({ file: settings.modelFile, gpu: settings.gpu, system: "You answer only from the notes you are given, briefly, citing them like [1].", maxTokens: settings.maxTokens, temperature: 0.1 })));
      lastAsk.answer = { text: out.text, by: "on-phone AI" };
    } catch (err) { toast(err.message === "stopped" ? "Stopped" : err.message); }
    sync("stopModel");
    if (location.hash.startsWith("#/ask")) askScreen();
  });
}

function askMeta(r) {
  const text = Notes.metaPrompt(settings.prompt, r);
  sync("copy", text);
  r.asked_at = Date.now();
  saveDb();
  sync("shareText", text, "Ask Meta AI");
  toast("Prompt copied. Pick Meta AI (or paste it there). Then share its answer back to Reel Shelf.");
}

function pasteDialog(r) {
  $dlg.innerHTML = `<form method="dialog" class="stack"><h2>Paste the answer</h2>
    <p class="hint">Paste Meta AI's answer (TOPIC, POINTS, ...). It is filed under this reel.</p>
    <textarea class="input tall" id="ans" placeholder="TOPIC: ..."></textarea>
    <div class="grid2"><button class="btn" value="cancel">Cancel</button><button class="btn primary" id="ok" value="ok">Save</button></div></form>`;
  $dlg.showModal();
  $dlg.querySelector("#ok").addEventListener("click", (e) => {
    const t = $dlg.querySelector("#ans").value;
    const notes = Notes.parse(t);
    if (!notes) { e.preventDefault(); toast("That does not look like the notes format (TOPIC, POINTS, ...)"); return; }
    setNotes(r, notes, "meta", t);
    saveDb();
    toast("Saved");
    setTimeout(() => reelScreen(r.code), 0);
  });
}

function addScreen() {
  $app.innerHTML = `${header("Add reels", "")}
    <div class="card stack"><strong>Paste links or answers</strong>
      <p class="hint">Reel links (one or many, any text around them is fine), or Meta AI answers in the notes format. Several answers at once are split up.</p>
      <textarea class="input tall" id="paste" placeholder="https://www.instagram.com/reel/..."></textarea>
      <button class="btn primary block" id="add">Save to shelf</button></div>
    <div class="card stack"><strong>All your saved reels, straight from Instagram</strong>
      <p class="hint">Opens Instagram's own "Download your information" page inside Reel Shelf. You sign in and tap the buttons yourself, like in a browser, so it is safe for your account. Tick <strong>Saved</strong>, format <strong>JSON</strong>. When Meta says the file is ready (it emails you), open this again and tap Download: your reels and collections come straight in.</p>
      <button class="btn primary block" id="ig">Get my saved reels from Instagram</button>
      ${RN && RN.openInstagram ? "" : `<p class="hint">Only in the Android app.</p>`}</div>
    <div class="card stack"><strong>Or choose an export you already downloaded</strong>
      <ol class="hint" style="padding-left:18px">
        <li>Instagram: Settings, Accounts Center, Your information and permissions, Download your information.</li>
        <li>Some of your information, tick <strong>Saved</strong>, format <strong>JSON</strong>, export to device.</li>
        <li>Choose the ZIP here (or saved_posts.json and saved_collections.json). Your collections become labels.</li></ol>
      <label class="btn block" for="zip">Choose the export</label>
      <input id="zip" class="sr" type="file" multiple accept=".zip,.json,.html,application/zip,application/json,text/html">
      <div id="result"></div></div>
    <p class="hint">Saving does nothing else. Tap Start when you want the notes.</p>`;
  bind("#add", "click", () => {
    const t = document.getElementById("paste").value;
    const answers = Notes.splitAnswers(t);
    let msg;
    if (answers.length) {
      const r = fileAnswer(t, "meta", null, true);
      msg = `${plural(r.filed, "answer")} saved` + (r.inbox ? `, ${r.inbox} to file` : "");
    } else {
      const found = Notes.links(t);
      if (!found.length) { toast("No reel links or answers found in that text"); return; }
      const n = addReels(found, "paste");
      msg = n ? `${plural(n, "reel")} saved` : "Those reels are already on your shelf";
    }
    toast(msg);
    location.hash = "#/";
  });
  bind("#ig", "click", () => sync("openInstagram"));
  bind("#zip", "change", async (e, el) => {
    const out = document.getElementById("result");
    const files = [...el.files];
    if (!files.length) return;
    let parts = [];
    const skipped = [];
    for (const f of files) {
      out.innerHTML = `<p class="hint">Reading ${esc(f.name)}...</p>`;
      try {
        const got = /\.zip$/i.test(f.name) ? await Notes.readZip(f) : [{ name: f.name, text: await f.text() }];
        if (!got.length) skipped.push(`${f.name}: no saved posts inside`);
        parts = parts.concat(got);
      } catch (err) { skipped.push(`${f.name}: ${err.message}`); }
    }
    const { found, added } = importParts(parts);
    out.innerHTML = `<div class="stack"><strong>${plural(added, "new reel")} saved</strong><span class="hint">${found} found in the export${skipped.length ? `; ${esc(skipped.join("; "))}` : ""}</span>
      ${added ? `<button class="btn primary block" id="go">Start now</button>` : ""}</div>`;
    const go = document.getElementById("go");
    if (go) go.addEventListener("click", () => startRun());
    el.value = "";
  });
}

function inboxScreen() {
  if (!db.inbox.length) { location.hash = "#/"; return; }
  const a = db.inbox[0];
  const n = Notes.parse(a.text) || {};
  const choices = db.reels.filter((r) => r.url && !(r.notes && r.notes_by === "meta")).slice(0, 30);
  $app.innerHTML = `${header("File this answer", "#/")}
    <div class="card"><strong>${esc(n.topic || "Meta AI answer")}</strong><br><span class="small muted">${esc((n.tags || []).map((t) => "#" + t).join(" "))}</span></div>
    <h2>Which reel is it about?</h2>
    <div class="stack">${choices.map((r) => `<button class="list-item" style="border:0;text-align:left" data-pick="${esc(r.code)}"><span class="grow stack" style="gap:3px"><span class="title clamp">${esc(r.caption ? r.caption.split("\n")[0] : r.author ? "@" + r.author : r.code)}</span><span class="small muted">${esc(day(r.added_at))}</span></span>${ICON.chev}</button>`).join("")}</div>
    <button class="btn block" id="alone">Keep it as a note on its own</button>
    <button class="btn block danger" id="drop">Throw it away</button>`;
  const done = () => { db.inbox.shift(); saveDb(); location.hash = db.inbox.length ? "#/inbox" : "#/"; render(); };
  bind("[data-pick]", "click", (e, b) => { setNotes(reel(b.dataset.pick), n, "meta", a.text); done(); });
  bind("#alone", "click", () => {
    const code = "note-" + Date.now().toString(36);
    db.reels.unshift({ code, url: "", author: "", collections: [], status: "done", added_at: Date.now(), added_by: "answer" });
    setNotes(reel(code), n, "meta", a.text);
    done();
  });
  bind("#drop", "click", done);
}

const RUN_STEPS = [["caption", "Reading the caption (and, for YouTube, the spoken words)"], ["ai", "Writing the notes with the on-phone AI"]];

function runScreen() {
  if (!run) {
    const ready = !!modelInfo().ready;
    const todo = db.reels.filter((r) => needsWork(r, ready));
    $app.innerHTML = `${header("Start", "")}
      <p class="soft" style="margin:0">Reel Shelf works only while this screen is open. Leaving the app stops it; tap Start again to continue.</p>
      ${todo.length ? `<button class="btn primary block" id="start">Start: ${plural(todo.length, "reel")}</button>` : `<div class="empty">Nothing waiting. Share a reel to Reel Shelf first.</div>`}
      ${ready ? "" : `<a class="card" href="#/settings"><span class="grow"><strong>Download the on-phone AI</strong><br><span class="small muted">Without it, Start only reads the captions; use Ask Meta AI for the notes</span></span>${ICON.chev}</a>`}`;
    bind("#start", "click", () => startRun());
    return;
  }
  paintRun(true);
}

function paintRun(force) {
  if (!force && location.hash !== "#/run") return;
  if (location.hash !== "#/run") return;
  const r = run.current ? reel(run.current) : null;
  const at = RUN_STEPS.findIndex(([k]) => k === run.step);
  const total = run.codes.length;
  const pct = total ? Math.round((Math.min(run.i, total) / total) * 100) : 100;
  $app.innerHTML = `${header(run.finished ? (run.paused ? "Paused" : "Done") : "Working...", "")}
    <div class="card stack"><div class="row between"><strong>${run.finished ? `${Math.min(run.i, total)} of ${total}` : `Reel ${Math.min(run.i + 1, total)} of ${total}`}</strong><span class="small muted">${pct}%</span></div>
      <span class="bar"><span style="width:${pct}%"></span></span>
      ${run.paused ? `<span class="small">You left the app, so it stopped. Tap Start again to continue.</span>` : ""}</div>
    ${!run.finished && r ? `<div class="card steps"><span class="small muted clamp">${esc(r.caption ? r.caption.split("\n")[0] : r.url)}</span>
      ${RUN_STEPS.filter(([k]) => k !== "ai" || run.ready).map(([k, l], n) => `<div class="step ${n < at ? "done" : n === at ? "now" : "todo"}"><span class="ring">${n < at ? ICON.check : ""}</span><span>${l}</span></div>`).join("")}</div>` : ""}
    ${!run.finished ? `<p class="hint">${run.step === "ai" ? "The AI on your phone can take a minute per reel. Keep the app open." : "Keep the app open."}</p><button class="btn block" id="stop">Stop</button>`
      : `<button class="btn primary block" id="again">${run.paused ? "Continue" : "Back to the shelf"}</button>`}
    ${run.log.length ? `<div class="stack"><h2>Results</h2>${run.log.slice(0, 40).map((l) => `<a class="list-item" href="#/r/${enc(l.code)}"><span aria-hidden="true">${l.ok ? "✓" : "–"}</span><span class="grow small">${esc(l.text)}</span>${ICON.chev}</a>`).join("")}</div>` : ""}`;
  bind("#stop", "click", () => { stopRun(); });
  bind("#again", "click", () => { const p = run.paused; run = null; if (p) startRun(); else location.hash = "#/"; });
}

function settingsScreen() {
  const info = modelInfo();
  const m = MODELS.find((x) => x.file === settings.modelFile);
  const others = (info.installed || []).filter((f) => !MODELS.some((x) => x.file === f));
  const dl = !!info.downloading;
  const pct = m && info.partial ? Math.round((info.partial / m.size) * 100) : 0;
  const seg = (key, opts) => `<div class="seg">${opts.map(([v, l]) => `<button data-set="${key}" data-val="${esc(JSON.stringify(v))}" aria-pressed="${settings[key] === v}">${l}</button>`).join("")}</div>`;
  $app.innerHTML = `${header("Settings", "")}
    <div class="stack"><h2>On-phone AI</h2>
      <div class="card stack">
        <div class="row between"><strong>${esc(m ? m.name : settings.modelFile)}</strong><span class="tag ${info.ready ? "ok" : "warn"}" id="mstate">${info.ready ? "Ready" : dl ? "Downloading" : info.partial ? "Paused" : "Not downloaded"}</span></div>
        <span class="small muted">${esc(m ? m.note : "Your own model file")}</span>
        ${!info.ready && m ? `<span class="bar"><span id="mbar" style="width:${pct}%"></span></span><span class="small muted" id="mtext">${info.partial ? `${mb(info.partial)} of ${mb(m.size)}` : `${mb(m.size)} to download. Use Wi-Fi.`}</span>` : ""}
        ${info.ready ? `<span class="small muted">${mb(info.bytes)} on this phone${info.backend ? ` · running on ${info.backend.toUpperCase()}` : ""}</span>` : ""}
        ${!info.ready && m ? (dl ? `<button class="btn block" id="pause">Pause download</button>` : `<button class="btn primary block" id="dl">${info.partial ? "Continue download" : "Download model"}</button>`) : ""}
        ${info.ready || info.partial ? `<button class="btn block danger" id="delm">Delete the model</button>` : ""}
        <p class="hint">The download only runs while Reel Shelf is open. If you leave, it pauses and continues from where it stopped.</p>
      </div>
      ${others.length || MODELS.length > 1 ? `<label class="field">Model to use<select class="input" id="pickm">${[...MODELS.map((x) => [x.file, x.name]), ...others.map((f) => [f, f])].map(([f, l]) => `<option value="${esc(f)}" ${settings.modelFile === f ? "selected" : ""}>${esc(l)}</option>`).join("")}</select></label>` : ""}
      <button class="btn block" id="own">Use my own model file (.litertlm)</button>
      <div class="stack"><span class="label">Processor</span>${seg("gpu", [[true, "GPU (faster)"], [false, "CPU"]])}</div>
      <div class="stack"><span class="label">Answer length</span>${seg("maxTokens", [[400, "Short"], [800, "Normal"], [1500, "Long"]])}</div>
      <div class="stack"><span class="label">Style</span>${seg("temperature", [[0.1, "Exact"], [0.3, "Balanced"], [0.7, "Free"]])}</div>
      <label class="field">Extra instructions for the on-phone AI<textarea class="input" id="lextra" placeholder="e.g. keep every number and step">${esc(settings.localExtra)}</textarea></label>
    </div>
    <div class="stack"><h2>Meta AI</h2>
      <label class="field">Your prompt ({link} is replaced by the reel link)<textarea class="input tall" id="prompt">${esc(settings.prompt)}</textarea></label>
      <div class="grid2"><button class="btn" id="savep">Save prompt</button><button class="btn" id="resetp">Reset</button></div>
    </div>
    <div class="stack"><h2>Export (${plural(db.reels.length, "reel")})</h2>
      <div class="grid2"><button class="btn" id="exjson">Save JSON</button><button class="btn" id="exmd">Save Markdown</button></div>
      <div class="grid2"><button class="btn" id="exshare">Share notes</button><button class="btn" id="excopy">Copy all</button></div>
      <p class="hint">Files go to Downloads/ReelShelf. Send the JSON to Claude to analyze all your reels together.</p>
    </div>
    <div class="stack"><h2>Instagram</h2>
      <button class="btn block" id="igsignout">Sign Reel Shelf out of Instagram</button>
      <p class="hint">Only signs out the page Reel Shelf opens for your saved-reels export. Your Instagram app stays signed in.</p></div>
    <p class="hint">Reel Shelf does nothing in the background. Sharing a reel only saves it; leaving the app stops the AI and any download.</p>
    <button class="btn block link" id="old">Use the old Reel Shelf on a PC or Termux</button>
    <button class="btn block danger" id="wipe">Delete all reels and notes</button>`;
  bind("[data-set]", "click", (e, b) => { settings[b.dataset.set] = JSON.parse(b.dataset.val); saveSettings(); settingsScreen(); });
  bind("#dl", "click", () => {
    onProgress.download = (d, t) => {
      const bar = document.getElementById("mbar");
      const txt = document.getElementById("mtext");
      const tot = t > 0 ? t : m.size;
      if (bar) bar.style.width = Math.round((d / tot) * 100) + "%";
      if (txt) txt.textContent = `${mb(d)} of ${mb(tot)}`;
    };
    phone("downloadModel", m.url, m.file).then(() => { toast("The AI model is ready"); if (location.hash === "#/settings") settingsScreen(); })
      .catch((err) => { if (err.message !== "paused") toast(err.message); if (location.hash === "#/settings") settingsScreen(); });
    setTimeout(() => { if (location.hash === "#/settings") settingsScreen(); }, 300);
  });
  bind("#pause", "click", () => { sync("stopModel"); setTimeout(settingsScreen, 400); });
  bind("#delm", "click", () => { if (confirm("Delete the AI model from this phone? You can download it again later.")) { sync("deleteModel", settings.modelFile); settingsScreen(); } });
  bind("#own", "click", () => {
    onProgress.import = (d, t) => { toast(`Copying the model: ${mb(d)}${t > 0 ? " of " + mb(t) : ""}`); };
    phone("pickModel").then((name) => { settings.modelFile = name; saveSettings(); toast("Model ready: " + name); settingsScreen(); })
      .catch((err) => { if (err.message !== "cancelled") toast(err.message); });
  });
  bind("#pickm", "change", (e, el) => { settings.modelFile = el.value; saveSettings(); settingsScreen(); });
  bind("#lextra", "change", (e, el) => { settings.localExtra = el.value.slice(0, 2000); saveSettings(); toast("Saved"); });
  bind("#savep", "click", () => { settings.prompt = document.getElementById("prompt").value.slice(0, 8000) || Notes.META_PROMPT; saveSettings(); toast("Prompt saved"); });
  bind("#resetp", "click", () => { settings.prompt = Notes.META_PROMPT; saveSettings(); settingsScreen(); toast("Prompt reset"); });
  const stamp = () => new Date().toISOString().slice(0, 10);
  bind("#exjson", "click", () => phone("saveFile", `reel-notes-${stamp()}.json`, "application/json", Notes.exportJson(db.reels)).then((w) => toast("Saved to " + w)).catch((e) => toast(e.message)));
  bind("#exmd", "click", () => phone("saveFile", `reel-notes-${stamp()}.md`, "text/markdown", Notes.exportMarkdown(db.reels)).then((w) => toast("Saved to " + w)).catch((e) => toast(e.message)));
  bind("#exshare", "click", () => sync("shareText", Notes.exportMarkdown(db.reels), "Share your reel notes"));
  bind("#excopy", "click", () => { sync("copy", Notes.exportMarkdown(db.reels)); toast("All notes copied"); });
  bind("#old", "click", () => sync("openServerMode"));
  bind("#igsignout", "click", () => { if (confirm("Sign Reel Shelf's Instagram page out?")) { sync("signOutInstagram"); toast("Signed out"); } });
  bind("#wipe", "click", () => { if (confirm(`Delete all ${db.reels.length} reels and their notes? This cannot be undone.`)) { db = { reels: [], inbox: [] }; saveDb(); toast("Deleted"); settingsScreen(); } });
}

// ------------------------------------------------------------------ router

const ROUTES = [
  [/^#?\/?$/, homeScreen, "home"], [/^#\/r\/(.+)$/, (m) => reelScreen(decodeURIComponent(m[1])), "home"], [/^#\/inbox$/, inboxScreen, "home"],
  [/^#\/ask(\?.*)?$/, askScreen, "ask"], [/^#\/topic\/(.+)$/, (m) => topicScreen(decodeURIComponent(m[1])), "ask"],
  [/^#\/add$/, addScreen, "add"], [/^#\/run$/, runScreen, "run"], [/^#\/settings$/, settingsScreen, "settings"],
];

function render() {
  const h = location.hash || "#/";
  for (const [rx, fn, tab] of ROUTES) {
    const m = h.match(rx);
    if (!m) continue;
    document.querySelectorAll("nav.tabs a").forEach((a) => (a.dataset.tab === tab ? a.setAttribute("aria-current", "page") : a.removeAttribute("aria-current")));
    try { fn(m); } catch (err) { $app.innerHTML = `<div class="empty">${esc(err.message)}<br><br><a class="btn" href="#/">Back to Shelf</a></div>`; }
    return;
  }
  location.hash = "#/";
}

window.addEventListener("hashchange", () => { render(); window.scrollTo(0, 0); });
loadSettings();
loadDb();
takeShared();
render();
