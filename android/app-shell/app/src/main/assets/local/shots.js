/* Reel Shelf (built in): movie, series, anime and manga names from your screenshots and reel captions.
   The phone reads the text in each screenshot (Google ML Kit, inside the app, offline), Titles.read picks the names
   with fixed rules (no AI), and Catalog.add puts them in the watchlist as "unverified" for the online check.
   Only folders you pick are read. It runs only while this screen is open and you tap Process; leaving the app stops
   it, and the next Process carries on where it stopped (pictures already read are skipped). */
"use strict";

const Shots = (() => {
  const BATCH = 6;            // pictures per call to the phone
  const SAVE_EVERY = 60;      // pictures between saves
  const LOW_BATTERY = 15;     // pause below this, unless charging
  let state = { v: 1, seen: {}, reels: {} };  // seen[key] = {m, st, n, f, c: [titles], x: short text}
  let loaded = false;
  let job = null;             // {phase, total, i, found, added, started, stop, finished, paused, why, recent}

  function load() {
    if (loaded) return;
    loaded = true;
    try {
      const t = sync("loadShots");
      if (t) { const d = JSON.parse(t); state = { v: 1, seen: d.seen || {}, reels: d.reels || {} }; }
    } catch (e) { toast("The screenshot list could not be read; it will be rebuilt"); }
  }
  function save() {
    if (sync("storeShots", JSON.stringify(state)) === false) toast("Could not save. Is the phone's storage full?");
  }
  function folders() { try { return JSON.parse(sync("shotFolders") || "[]"); } catch (e) { return []; } }
  function battery() { try { return JSON.parse(sync("battery") || "{}"); } catch (e) { return {}; } }

  /** Candidates worth putting in the watchlist: sure ones, or weaker ones when the picture says what kind it is. */
  function keep(res) {
    const many = res.candidates.filter((c) => c.why === "list-item").length >= 2;
    return res.candidates.filter((c) => c.score >= 0.6 || (c.score >= 0.45 && (c.kind || res.kind)))
      .slice(0, many ? 12 : 3);
  }
  function toCatalog(c, kind, ref) {
    const r = Catalog.add(db, {
      title: c.title, type: c.kind || "", year: c.year || null, language: c.lang || "", confidence: c.score,
      source: { kind, ref, method: c.why, text: c.snippet, confidence: c.score },
    });
    return r && r.created ? 1 : 0;
  }

  // ---------------------------------------------------------------- the run

  async function process() {
    if (job && !job.finished) return;
    load();
    job = { phase: "list", total: 0, i: 0, found: 0, added: 0, started: Date.now(), stop: false, finished: false, paused: false, why: "", recent: [], pics: 0 };
    sync("keepAwake", true);
    paint();
    try {
      fromReels();
      if (folders().length) await fromScreenshots();
    } catch (e) {
      if (!job.stop) job.why = e.message;
    }
    job.finished = true;
    sync("keepAwake", false);
    saveDb();
    save();
    paint();
  }

  /** Reel captions (and YouTube transcripts): the same rules, only for reels that look like they are about a title. */
  function fromReels() {
    job.phase = "reels";
    for (const r of db.reels || []) {
      const text = [r.title, r.caption, r.transcript && r.transcript.slice(0, 3000), ((r.notes || {}).tags || []).map((t) => "#" + t).join(" ")].filter(Boolean).join("\n");
      if (!text) continue;
      const sig = text.length + ":" + (r.notes_at || 0);
      if (state.reels[r.code] === sig) continue;
      const res = Titles.read(text.split(/\n+/), { folder: (r.collections || []).join(" ") });
      state.reels[r.code] = sig;
      if (!res.kind && !(r.collections || []).some((c) => Titles.kindOf(c.replace(/\s/g, "")))) continue;  // not about a movie/anime/...
      for (const c of keep(res)) { job.found++; job.added += toCatalog(c, "reel", r.code); job.recent.unshift(c.title); }
    }
    job.recent = job.recent.slice(0, 8);
  }

  async function fromScreenshots() {
    job.phase = "list";
    paint();
    const pics = JSON.parse(await phone("listShots") || "[]");
    const todo = pics.filter((p) => { const s = state.seen[p.k]; return !s || s.m !== p.m; }).sort((a, b) => b.m - a.m);  // newest first
    job.pics = pics.length;
    job.total = todo.length;
    job.phase = "read";
    paint();
    let since = 0;
    for (let i = 0; i < todo.length && !job.stop; i += BATCH) {
      const b = battery();
      if (b.level >= 0 && b.level < LOW_BATTERY && !b.charging) { job.paused = true; job.why = `Battery at ${b.level}%. Plug in the charger and tap Process to carry on.`; break; }
      const part = todo.slice(i, i + BATCH);
      let got;
      try { got = JSON.parse(await phone("readShots", JSON.stringify(part.map((p) => p.k))) || "[]"); } catch (e) { if (e.message === "stopped" || job.stop) break; throw e; }
      for (const g of got) {
        const p = part.find((x) => x.k === g.k);
        if (!p) continue;
        job.i++;
        since++;
        if (!g.ok) { state.seen[p.k] = { m: p.m, st: "error", n: p.n, f: p.f, c: [], x: String(g.error || "").slice(0, 120) }; continue; }
        const res = Titles.read(g.lines, { W: g.W, H: g.H, name: p.n, folder: p.f });
        const st = Titles.verdict(res);
        const kept = keep(res);
        for (const c of kept) { job.found++; job.added += toCatalog(c, "screenshot", p.k); job.recent.unshift(c.title); }
        job.quotes = (job.quotes || 0) + Quotes.addFrom(db, res, p.k);  // lines worth keeping go to Quotes
        state.seen[p.k] = { m: p.m, st: kept.length ? st : (st === "found" || st === "several" ? "unsure" : st), n: p.n, f: p.f,
          c: res.candidates.slice(0, 5).map((c) => c.title), x: res.text.slice(0, 300) };
      }
      job.recent = job.recent.slice(0, 8);
      if (since >= SAVE_EVERY) { since = 0; saveDb(); save(); }
      paint();
    }
  }

  function stop() {
    if (!job || job.finished) return;
    job.stop = true;
    sync("stopShots");
  }

  // ---------------------------------------------------------------- screens

  function counts() {
    const n = { all: 0, found: 0, several: 0, unsure: 0, none: 0, no_text: 0, error: 0, done: 0 };
    for (const s of Object.values(state.seen)) { n.all++; n[s.st] = (n[s.st] || 0) + 1; }
    return n;
  }

  function screen() {
    load();
    if (job && !job.finished) { paint(); return; }
    const fs = folders();
    const n = counts();
    const b = battery();
    $app.innerHTML = `${header("Screenshots to watchlist", "#/run")}
      <p class="soft" style="margin:0">Reads the text in your screenshots on the phone (nothing is uploaded), finds the movie, series, anime and manga names, and puts them in your watchlist to be checked online.</p>
      <div class="stack"><h2>Folders</h2>
        ${fs.length ? fs.map((f) => `<div class="card row between"><span class="grow small">${esc(f.name || f.uri)}</span><button class="btn" data-rm="${esc(f.uri)}">Remove</button></div>`).join("")
          : `<div class="empty small">Pick your Screenshots folder (and folders like Movies, Anime or Manga: the folder name tells the kind).</div>`}
        <button class="btn block" id="addf">Add a folder</button></div>
      ${n.all ? `<div class="card stack"><strong>${plural(n.all, "picture")} read</strong>
        <span class="small">${n.found + n.several} with names, ${n.unsure} unsure, ${n.none + n.no_text} with no name in the text${n.error ? `, ${n.error} could not be opened` : ""}</span>
        ${n.unsure + n.none + n.no_text ? `<a class="btn block" href="#/shots/review">Look at the ones without a sure name</a>` : ""}</div>` : ""}
      <button class="btn primary block" id="go">Process${fs.length ? "" : " reel captions"}</button>
      <p class="hint">Only new screenshots are read each time. You can leave the app while it runs (a notification shows it, with Stop).
        ${b.level >= 0 ? ` Battery ${b.level}%${b.charging ? ", charging" : ""}. A big first run is best done on the charger.` : ""}</p>
      ${job && job.finished ? doneHtml() : ""}`;
    bind("#addf", "click", () => phone("addShotFolder").then(() => { toast("Folder added"); screen(); }).catch((e) => { if (e.message !== "cancelled") toast(e.message); }));
    bind("[data-rm]", "click", (e, el) => { if (confirm("Stop reading this folder? Names already found stay in the watchlist.")) { sync("removeShotFolder", el.dataset.rm); screen(); } });
    bind("#go", "click", () => process());
  }

  function doneHtml() {
    return `<div class="card stack"><strong>${job.paused || job.stop ? "Paused" : "Done"}</strong>
      <span class="small">${plural(job.i, "new screenshot")} read, ${plural(job.found, "name")} found, ${plural(job.added, "new title")} in the watchlist.</span>
      ${job.why ? `<span class="small">${esc(job.why)}</span>` : ""}
      ${job.recent.length ? `<span class="small muted">${job.recent.map(esc).join(" · ")}</span>` : ""}</div>`;
  }

  function paint() {
    if (!location.hash.startsWith("#/shots") || location.hash.startsWith("#/shots/review")) return;
    if (!job || job.finished) { if (job && job.finished && location.hash === "#/shots") screen(); return; }
    const pct = job.total ? Math.round((job.i / job.total) * 100) : 0;
    const mins = (Date.now() - job.started) / 60000;
    const rate = mins > 0.2 && job.i ? job.i / mins : 0;
    const left = rate ? Math.ceil((job.total - job.i) / rate) : 0;
    $app.innerHTML = `${header("Working...", "")}
      <div class="card stack"><div class="row between"><strong>${job.phase === "list" ? "Listing your screenshots..." : job.phase === "reels" ? "Reel captions..." : `${job.i} of ${job.total}`}</strong><span class="small muted">${pct}%</span></div>
        <span class="bar"><span style="width:${pct}%"></span></span>
        <span class="small">${plural(job.found, "name")} found, ${plural(job.added, "new title")}${rate ? ` · about ${Math.round(rate)} a minute${left ? `, ${left < 90 ? left + " min" : Math.round(left / 60) + " h"} left` : ""}` : ""}</span></div>
      ${job.recent.length ? `<div class="card small muted">${job.recent.map(esc).join(" · ")}</div>` : ""}
      <p class="hint">You can leave the app: it keeps going, with a notification to stop it.</p>
      <button class="btn block" id="stop">Stop</button>`;
    bind("#stop", "click", () => stop());
  }

  /** Screenshots without a sure name: see the picture, pick a guess, type the name, or search it with Google Lens. */
  function review(page = 0) {
    load();
    const list = Object.entries(state.seen).filter(([, s]) => ["unsure", "none", "no_text"].includes(s.st)).sort((a, b) => b[1].m - a[1].m);
    const per = 12;
    const part = list.slice(page * per, page * per + per);
    $app.innerHTML = `${header("Without a sure name", "#/shots")}
      <p class="soft" style="margin:0">${plural(list.length, "screenshot")}. Tap a guess to add it, type the name, or open the picture in Google Lens.</p>
      ${part.map(([k, s], i) => `<div class="card stack" data-i="${i}">
        <img alt="" data-thumb="${esc(k)}" style="max-width:100%;max-height:260px;object-fit:contain;border-radius:8px;background:#0c0d10">
        <span class="small muted">${esc(s.f)} · ${esc(s.n)}</span>
        ${s.c.length ? `<div class="row" style="flex-wrap:wrap;gap:6px">${s.c.map((t) => `<button class="btn" data-pick="${esc(t)}">${esc(t)}</button>`).join("")}</div>` : ""}
        <form class="row" data-form><input class="grow" placeholder="Type the name" aria-label="Name"><button class="btn">Add</button></form>
        <div class="row" style="gap:6px"><button class="btn" data-lens>Google Lens</button><button class="btn" data-skip>Not a title</button></div></div>`).join("")}
      <div class="row between">${page ? `<button class="btn" id="prev">Back</button>` : "<span></span>"}${(page + 1) * per < list.length ? `<button class="btn" id="next">More</button>` : ""}</div>`;
    $app.querySelectorAll("img[data-thumb]").forEach((img) => { const u = sync("shotThumb", img.dataset.thumb, 480); if (u && u.startsWith("data:image/")) img.src = u; else img.remove(); });
    const done = (k, title, how) => {
      if (title) { Catalog.add(db, { title, confidence: 0.9, source: { kind: "screenshot", ref: k, method: how, text: title, confidence: 0.9 } }); saveDb(); toast(`Added ${title}`); }
      state.seen[k].st = title ? "done" : "skipped";
      save();
      review(page);
    };
    $app.querySelectorAll("[data-i]").forEach((card) => {
      const [k] = part[Number(card.dataset.i)];
      card.querySelectorAll("[data-pick]").forEach((b) => b.addEventListener("click", () => done(k, b.dataset.pick, "picked")));
      card.querySelector("[data-form]").addEventListener("submit", (e) => { e.preventDefault(); const v = e.target.querySelector("input").value.trim(); if (v) done(k, v, "typed"); });
      card.querySelector("[data-lens]").addEventListener("click", () => sync("shotToLens", k));
      card.querySelector("[data-skip]").addEventListener("click", () => done(k, "", ""));
    });
    bind("#prev", "click", () => { review(page - 1); window.scrollTo(0, 0); });
    bind("#next", "click", () => { review(page + 1); window.scrollTo(0, 0); });
  }

  function pause() { if (job && !job.finished) { job.paused = true; stop(); } }

  return { screen, review, process, stop, pause, keep, get job() { return job; } };
})();
