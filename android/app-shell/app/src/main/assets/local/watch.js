/* Reel Shelf watchlist screens: every movie, series, drama, anime, manga (and more) found in your screenshots and reels,
   in one list you can filter by category, language, genre, year and whether it was checked online.
   Storage and dedupe live in catalog.js; this file is only the screens. Uses the helpers in local.js. */
"use strict";

const TYPE_COLORS = { watch: "#F2B544", read: "#7FB7E8", other: "#CFCBC3" };

/** For the extraction step (and anything else): add one title, save, and refresh the list if it is open. */
const Watch = {
  addCandidate(c) { const r = Catalog.add(db, c); if (r) { saveDb(); refreshWatch(); } return r; },
  addMany(list) { const r = Catalog.addMany(db, list); saveDb(); refreshWatch(); return r; },
};
window.Watch = Watch;
function refreshWatch() { if (/^#?\/?$|^#\/m\//.test(location.hash)) render(); }

function posterHtml(m, cls = "thumb") {
  const t = Catalog.typeInfo(db, m.type);
  if (m.poster && /^https:\/\//.test(m.poster)) return `<img class="${cls}" src="${esc(m.poster)}" alt="" loading="lazy" referrerpolicy="no-referrer">`;
  return `<span class="${cls} poster-ph" style="--ph:${TYPE_COLORS[t.group] || TYPE_COLORS.other}" aria-hidden="true">${esc((m.title || "?").trim().charAt(0).toUpperCase())}</span>`;
}

function verifiedTag(m) {
  const v = m.verified || "unverified";
  if (v === "unverified" && m.checked_at) return `<span class="tag">Not found online yet</span>`;  // tried again later, by itself
  const kind = v === "verified" ? "ok" : "";
  return `<span class="tag ${kind}">${esc(Catalog.VERIFIED[v] || v)}</span>`;
}

/** "1h 34m", or "45m × 16" for a series (one episode × episodes). */
function lengthText(m) {
  if (!(m.runtime > 0)) return "";
  const t = Search.fmtMin(m.runtime);
  return m.episodes > 1 ? `${t} × ${m.episodes}` : t;
}

/** "★ 8.2 IMDb": the rating, and where it is from. */
function ratingText(m) {
  return m.rating && m.rating.score > 0 ? `★ ${m.rating.score.toFixed(1)} ${m.rating.by}` : "";
}

/** "3 seasons · 66 eps" for the list; the detail screen shows each season. */
function seasonsText(m) {
  const s = m.seasons || [];
  if (s.length < 2) return "";
  const eps = s.reduce((a, x) => a + (x.episodes || 0), 0);
  return `${s.length} seasons${eps ? ` · ${eps} eps` : ""}`;
}

function titleRow(m) {
  const t = Catalog.typeInfo(db, m.type);
  const n = (m.sources || []).length;
  const meta = [ratingText(m), t.label, m.year, m.language ? Catalog.langName(m.language) : "", seasonsText(m) || lengthText(m)].filter(Boolean).join(" · ");
  return `<a class="list-item" href="#/m/${enc(m.id)}">${posterHtml(m, "thumb sm")}
    <span class="grow stack" style="gap:4px"><span class="title clamp">${esc(m.title)}</span>
      <span class="small muted">${esc(meta)}</span>
      <span class="tagrow">${verifiedTag(m)}${m.status && m.status !== "want" ? `<span class="tag">${esc(Catalog.STATUS[m.status])}</span>` : ""}${n > 1 ? `<span class="tag">Seen ${n} times</span>` : ""}${(m.genres || []).slice(0, 2).map((g) => `<span class="tag">${esc(g)}</span>`).join("")}</span></span></a>`;
}

function titleScreen(id) {
  const m = Catalog.get(db, id);
  if (!m) { $app.innerHTML = `${header("Not found", "#/")}<div class="empty">This title is no longer in your watchlist.</div>`; return; }
  const t = Catalog.typeInfo(db, m.type);
  const src = (m.sources || []).slice().sort((a, b) => (b.at || 0) - (a.at || 0));
  const srcRow = (s) => {
    const what = { screenshot: "Screenshot", reel: "Reel", manual: "Added by you" }[s.kind] || s.kind;
    const how = s.method ? ` · ${s.method.replace(/[-_]/g, " ")}` : "";
    const body = `<span class="grow stack" style="gap:2px"><strong class="small">${esc(what)}${esc(how)}</strong>${s.text ? `<span class="small muted clamp">${esc(s.text)}</span>` : ""}<span class="small muted">${day(s.at)}</span></span>`;
    return s.kind === "reel" && s.ref && reel(s.ref) ? `<a class="list-item" href="#/r/${enc(s.ref)}">${body}${ICON.chev}</a>` : `<div class="list-item">${body}</div>`;
  };
  const firstReel = src.map((s) => s.kind === "reel" && s.ref && reel(s.ref)).find((r) => r && r.url);
  $app.innerHTML = `${header(t.label, "#/")}
    <div class="row" style="align-items:flex-start;gap:14px">${posterHtml(m, "thumb big poster")}
      <div class="stack grow" style="gap:6px"><h2 style="font-size:22px">${esc(m.title)}</h2>
        ${m.original_title && m.original_title !== m.title ? `<span class="small soft">${esc(m.original_title)}</span>` : ""}
        ${m.rating && m.rating.score > 0 ? `<span class="rating"><strong>★ ${esc(m.rating.score.toFixed(1))}</strong><span class="small muted">/10 ${esc(m.rating.by)}${m.rating.votes ? ` · ${esc(m.rating.votes.toLocaleString("en"))} votes` : ""}</span></span>` : ""}
        <span class="small muted">${esc([t.label, m.year, m.language ? Catalog.langName(m.language) : "", m.country, lengthText(m)].filter(Boolean).join(" · "))}</span>
        <span class="tagrow">${verifiedTag(m)}${(m.genres || []).map((g) => `<span class="tag">${esc(g)}</span>`).join("")}</span>
        ${m.confidence && m.verified !== "verified" ? `<span class="small muted">Sure: ${Math.round(m.confidence * 100)}%</span>` : ""}</div></div>
    ${m.overview ? `<p class="soft" style="margin:0;line-height:1.5">${esc(m.overview)}</p>` : ""}
    ${(m.seasons || []).length ? `<div class="stack" style="gap:6px"><h2>${plural(m.seasons.length, "season")}</h2>${m.seasons.map((x) => `<div class="list-item season">
      <strong>S${x.n}</strong><span class="grow stack" style="gap:2px"><span>${x.episodes ? `${x.episodes} eps` : "Episodes not known yet"}${x.year ? ` · ${x.year}` : ""}</span>${x.title && x.title !== m.title ? `<span class="small muted clamp">${esc(x.title)}</span>` : ""}</span></div>`).join("")}</div>` : ""}
    <div class="seg" role="group" aria-label="Status">${Object.entries(Catalog.STATUS).map(([k, l]) => `<button data-st="${k}" aria-pressed="${(m.status || "want") === k}">${esc(t.group === "read" ? ({ want: "Want", watching: "Reading", done: "Finished", dropped: "Dropped" })[k] : ({ want: "Want", watching: "Watching", done: "Finished", dropped: "Dropped" })[k])}</button>`).join("")}</div>
    ${firstReel ? `<button class="btn primary block" id="openig">${UI.insta} Instagram</button>` : ""}
    <div class="grid2">
      <button class="btn" id="edit">Edit</button>
      ${m.ext && /^tt\d+$/.test(m.ext.imdb || "") ? `<button class="btn" id="imdb">IMDb</button>` : `<button class="btn" id="look">Look it up</button>`}
    </div>
    ${(m.aka || []).length ? `<div class="card stack" style="gap:6px"><span class="label">Also known as</span><p class="small soft" style="margin:0">${esc(m.aka.join(" · "))}</p></div>` : ""}
    <div class="stack"><h2>Found in ${plural(src.length, "place")}</h2>${src.length ? src.map(srcRow).join("") : `<div class="empty small">No sources yet.</div>`}</div>
    <label class="field">Your note<textarea class="input" id="mnote" placeholder="e.g. a friend recommended it">${esc(m.note || "")}</textarea></label>
    <button class="btn block danger" id="mdel">Remove from watchlist</button>`;
  bind("[data-st]", "click", (e, b) => { Catalog.update(db, m.id, { status: b.dataset.st }); saveDb(); titleScreen(m.id); });
  bind("#edit", "click", () => titleDialog(m));
  bind("#openig", "click", () => { firstReel.opened_at = Date.now(); saveDb(); sync("openUrl", firstReel.url); });
  bind("#look", "click", () => sync("openUrl", "https://www.google.com/search?q=" + enc([m.title, m.year, t.label].filter(Boolean).join(" "))));
  bind("#imdb", "click", () => sync("openUrl", `https://www.imdb.com/title/${m.ext.imdb}/`));
  bind("#mnote", "change", (e, el) => { Catalog.update(db, m.id, { note: el.value }); saveDb(); toast("Saved"); });
  bind("#mdel", "click", () => { if (confirm(`Remove "${m.title}" from your watchlist?`)) { Catalog.remove(db, m.id); saveDb(); location.hash = "#/"; } });
}

/** Add or edit a title. fromReel: the reel code it came from (adds a reel source). */
function titleDialog(m, fromReel) {
  const types = Catalog.types(db);
  const opts = Object.entries(Catalog.GROUPS).map(([g, gl]) => `<optgroup label="${esc(gl)}">${types.filter((t) => t.group === g)
    .map((t) => `<option value="${esc(t.id)}" ${(m ? m.type : "movie") === t.id ? "selected" : ""}>${esc(t.label)}</option>`).join("")}</optgroup>`).join("");
  const langs = Object.entries(Catalog.LANGS).sort((a, b) => a[1].localeCompare(b[1]));
  $dlg.innerHTML = `<form method="dialog" class="stack"><h2>${m ? "Edit title" : "Add a title"}</h2>
    <label class="field">Name<input class="input" id="tt" value="${esc(m ? m.title : "")}" placeholder="e.g. Parasite" required></label>
    <label class="field">Kind<select class="input" id="tk">${opts}<option value="__new">New kind...</option></select></label>
    <div class="grid2"><label class="field">Year<input class="input" id="ty" inputmode="numeric" maxlength="4" value="${esc(m && m.year ? m.year : "")}" placeholder="2019"></label>
      <label class="field">Language<select class="input" id="tl"><option value="">Unknown</option>${langs.map(([c, n]) => `<option value="${c}" ${m && m.language === c ? "selected" : ""}>${esc(n)}</option>`).join("")}</select></label></div>
    <label class="field">Genres<input class="input" id="tg" value="${esc(m ? (m.genres || []).join(", ") : "")}" placeholder="Thriller, Drama"></label>
    <div class="grid2"><button class="btn" value="cancel">Cancel</button><button class="btn primary" id="tok" value="ok">Save</button></div></form>`;
  $dlg.showModal();
  $dlg.querySelector("#tk").addEventListener("change", (e) => {
    if (e.target.value !== "__new") return;
    const name = (prompt("Name of the new kind (e.g. Thai drama, Podcast)") || "").trim();
    if (!name) { e.target.value = m ? m.type : "movie"; return; }
    const id = Catalog.addType(db, name, "watch");
    saveDb();
    const o = document.createElement("option");
    o.value = id; o.textContent = Catalog.typeInfo(db, id).label; o.selected = true;
    e.target.insertBefore(o, e.target.lastElementChild);
  });
  $dlg.querySelector("#tok").addEventListener("click", (e) => {
    const title = $dlg.querySelector("#tt").value.trim();
    if (!title) { e.preventDefault(); toast("Type the name first"); return; }
    const f = { title, type: $dlg.querySelector("#tk").value, year: $dlg.querySelector("#ty").value, language: $dlg.querySelector("#tl").value,
      genres: $dlg.querySelector("#tg").value.split(",").map((s) => s.trim()).filter(Boolean) };
    if (f.type === "__new") f.type = "other";
    let id;
    if (m) { Catalog.update(db, m.id, f); id = m.id; }
    else {
      const r = Catalog.add(db, { ...f, confidence: 1, source: fromReel ? { kind: "reel", ref: fromReel, method: "you" } : { kind: "manual", ref: "", method: "you" } });
      id = r.entry.id;
      toast(r.created ? "Added to your watchlist" : "Already in your watchlist, so it was merged");
    }
    saveDb();
    setTimeout(() => { if (fromReel) reelScreen(fromReel); else location.hash === `#/m/${enc(id)}` ? titleScreen(id) : (location.hash = `#/m/${enc(id)}`); }, 0);
  });
}

/** On a reel's page: the titles that came from it. */
function reelTitlesHtml(r) {
  const list = Catalog.fromSource(db, "reel", r.code).filter((m) => m.verified !== "rejected");
  return `<div class="stack"><div class="row between"><h2>Titles in this reel</h2><button class="btn" id="addrt" style="min-height:40px">Add title</button></div>
    ${list.length ? list.map(titleRow).join("") : `<p class="hint">Movies, series or manga this reel talks about. Add one and it joins your watchlist.</p>`}</div>`;
}
