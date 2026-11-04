/* Reel Shelf watchlist screens: every movie, series, drama, anime, manga (and more) found in your screenshots and reels,
   in one list you can filter by category, language, genre, year and whether it was checked online.
   Storage and dedupe live in catalog.js; this file is only the screens. Uses the helpers in local.js. */
"use strict";

let wf = { q: "", group: "", type: "", language: "", genre: "", year: "", verified: "", status: "", source: "" };
const TYPE_COLORS = { watch: "#F2B544", read: "#7FB7E8", other: "#CFCBC3" };

/** For the extraction step (and anything else): add one title, save, and refresh the list if it is open. */
const Watch = {
  addCandidate(c) { const r = Catalog.add(db, c); if (r) { saveDb(); refreshWatch(); } return r; },
  addMany(list) { const r = Catalog.addMany(db, list); saveDb(); refreshWatch(); return r; },
};
window.Watch = Watch;
function refreshWatch() { if (/^#\/(watch|m\/)/.test(location.hash)) render(); }

function posterHtml(m, cls = "thumb") {
  const t = Catalog.typeInfo(db, m.type);
  if (m.poster && /^https:\/\//.test(m.poster)) return `<img class="${cls}" src="${esc(m.poster)}" alt="" loading="lazy" referrerpolicy="no-referrer">`;
  return `<span class="${cls} poster-ph" style="--ph:${TYPE_COLORS[t.group] || TYPE_COLORS.other}" aria-hidden="true">${esc((m.title || "?").trim().charAt(0).toUpperCase())}</span>`;
}

function verifiedTag(m) {
  const v = m.verified || "unverified";
  const kind = v === "verified" ? "ok" : v === "conflict" ? "warn" : "";
  return `<span class="tag ${kind}">${esc(Catalog.VERIFIED[v] || v)}</span>`;
}

function titleRow(m) {
  const t = Catalog.typeInfo(db, m.type);
  const n = (m.sources || []).length;
  const meta = [t.label, m.year, m.language ? Catalog.langName(m.language) : ""].filter(Boolean).join(" · ");
  return `<a class="list-item" href="#/m/${enc(m.id)}">${posterHtml(m, "thumb sm")}
    <span class="grow stack" style="gap:4px"><span class="title clamp">${esc(m.title)}</span>
      <span class="small muted">${esc(meta)}</span>
      <span class="tagrow">${verifiedTag(m)}${m.status && m.status !== "want" ? `<span class="tag">${esc(Catalog.STATUS[m.status])}</span>` : ""}${n > 1 ? `<span class="tag">Seen ${n} times</span>` : ""}${(m.genres || []).slice(0, 2).map((g) => `<span class="tag">${esc(g)}</span>`).join("")}</span></span></a>`;
}

function watchScreen() {
  const all = (db.media || []).filter((m) => m.verified !== "rejected");
  // menus count what the other filters leave, so each choice shows how many you will get
  const without = (k) => Catalog.facets(db, Catalog.filter(db, { ...wf, [k]: "", q: wf.q }));
  const fType = without("type").type;
  const fGroup = without("group").group;
  const sel = (key, label, counts, name, order) => {
    const keys = Object.keys(counts).sort(order || ((a, b) => counts[b] - counts[a] || String(a).localeCompare(String(b))));
    if (wf[key] && !keys.includes(wf[key])) keys.unshift(wf[key]);
    return `<label class="field small-field"><span class="label">${label}</span><select class="input" data-wf="${key}">
      <option value="">Any</option>${keys.map((k) => `<option value="${esc(k)}" ${wf[key] === k ? "selected" : ""}>${esc(name(k))} (${counts[k] || 0})</option>`).join("")}</select></label>`;
  };
  const decades = (a, b) => (a === "unknown") - (b === "unknown") || String(b).localeCompare(String(a));
  const types = Object.keys(fType).filter((id) => !wf.group || Catalog.typeInfo(db, id).group === wf.group)
    .sort((a, b) => fType[b] - fType[a]);
  const shown = Catalog.filter(db, wf);
  const any = Object.entries(wf).some(([k, v]) => k !== "q" && v);
  $app.innerHTML = `
    <div class="brand">Reel Shelf</div>
    <div class="row between"><h1>Watchlist</h1><button class="btn primary" id="addt">Add</button></div>
    <label class="search">${ICON.search}<input id="wq" type="search" placeholder="Search titles, other names, genres" value="${esc(wf.q)}" aria-label="Search titles"></label>
    ${Verify.cardHtml()}
    ${all.length ? `<div class="seg" role="group" aria-label="Watch or read">${[["", "All", all.length], ["watch", "To watch", fGroup.watch || 0], ["read", "To read", fGroup.read || 0]]
      .concat(fGroup.other ? [["other", "Other", fGroup.other]] : []).map(([v, l, c]) => `<button data-group="${v}" aria-pressed="${wf.group === v}">${l} ${c}</button>`).join("")}</div>
    ${types.length > 1 || wf.type ? `<div class="chips"><button class="chip" data-type="" aria-pressed="${!wf.type}">All kinds</button>${types.map((id) => `<button class="chip" data-type="${esc(id)}" aria-pressed="${wf.type === id}">${esc(Catalog.typeInfo(db, id).plural)} ${fType[id]}</button>`).join("")}</div>` : ""}
    <div class="grid2">
      ${sel("language", "Language", without("language").language, (k) => k === "unknown" ? "Unknown" : Catalog.langName(k))}
      ${sel("genre", "Genre", without("genre").genre, (k) => k)}
      ${sel("year", "Years", without("year").decade, (k) => k === "unknown" ? "Unknown" : k, decades)}
      ${sel("status", "Status", without("status").status, (k) => Catalog.STATUS[k] || k)}
      ${sel("verified", "Checked online", without("verified").verified, (k) => Catalog.VERIFIED[k] || k)}
      ${sel("source", "Found in", without("source").source, (k) => ({ screenshot: "Screenshots", reel: "Reels", manual: "Added by you" }[k] || k))}
    </div>
    <div class="row between"><span class="small muted" id="wcount">${plural(shown.length, "title")}${any || wf.q ? ` of ${all.length}` : ""}</span>${any ? `<button class="btn" id="wclear" style="min-height:36px">Clear filters</button>` : ""}</div>` : ""}
    <div class="stack" id="wlist">${watchListHtml(shown, all.length)}</div>`;
  bind("#wq", "input", (e, el) => {
    wf.q = el.value;
    const list = Catalog.filter(db, wf);
    document.getElementById("wlist").innerHTML = watchListHtml(list, all.length);
    const c = document.getElementById("wcount");
    if (c) c.textContent = plural(list.length, "title") + (wf.q || any ? ` of ${all.length}` : "");
  });
  bind("[data-wf]", "change", (e, el) => { wf[el.dataset.wf] = el.value; watchScreen(); });
  bind("[data-group]", "click", (e, b) => { wf.group = b.dataset.group; if (wf.type && Catalog.typeInfo(db, wf.type).group !== wf.group && wf.group) wf.type = ""; watchScreen(); });
  bind("[data-type]", "click", (e, b) => { wf.type = b.dataset.type; watchScreen(); });
  bind("#wclear", "click", () => { wf = { ...wf, group: "", type: "", language: "", genre: "", year: "", verified: "", status: "", source: "" }; watchScreen(); });
  bind("#addt", "click", () => titleDialog(null));
}

function watchListHtml(list, total) {
  if (!total) return `<div class="empty stack" style="text-align:left"><strong style="color:var(--text)">No titles yet</strong>
    <span>Movies, series, K-dramas, anime, manga and more found in your screenshots and reels show up here, each one only once, however many times it was saved.</span>
    <span>You can also <a href="#" id="addt2">add a title yourself</a>.</span></div>`;
  if (!list.length) return `<div class="empty">Nothing matches these filters.</div>`;
  return list.slice(0, 400).map(titleRow).join("") + (list.length > 400 ? `<div class="empty small">Showing 400 of ${list.length}. Narrow the filters to see the rest.</div>` : "");
}
document.addEventListener("click", (e) => { if (e.target && e.target.id === "addt2") { e.preventDefault(); titleDialog(null); } });

function titleScreen(id) {
  const m = Catalog.get(db, id);
  if (!m) { $app.innerHTML = `${header("Not found", "#/watch")}<div class="empty">This title is no longer in your watchlist.</div>`; return; }
  const t = Catalog.typeInfo(db, m.type);
  const src = (m.sources || []).slice().sort((a, b) => (b.at || 0) - (a.at || 0));
  const srcRow = (s) => {
    const what = { screenshot: "Screenshot", reel: "Reel", manual: "Added by you" }[s.kind] || s.kind;
    const how = s.method ? ` · ${s.method.replace(/[-_]/g, " ")}` : "";
    const body = `<span class="grow stack" style="gap:2px"><strong class="small">${esc(what)}${esc(how)}</strong>${s.text ? `<span class="small muted clamp">${esc(s.text)}</span>` : ""}<span class="small muted">${day(s.at)}</span></span>`;
    return s.kind === "reel" && s.ref && reel(s.ref) ? `<a class="list-item" href="#/r/${enc(s.ref)}">${body}${ICON.chev}</a>` : `<div class="list-item">${body}</div>`;
  };
  $app.innerHTML = `${header(t.label, "#/watch")}
    <div class="row" style="align-items:flex-start;gap:14px">${posterHtml(m, "thumb big poster")}
      <div class="stack grow" style="gap:6px"><h2 style="font-size:22px">${esc(m.title)}</h2>
        ${m.original_title && m.original_title !== m.title ? `<span class="small soft">${esc(m.original_title)}</span>` : ""}
        <span class="small muted">${esc([t.label, m.year, m.language ? Catalog.langName(m.language) : "", m.country].filter(Boolean).join(" · "))}</span>
        <span class="tagrow">${verifiedTag(m)}${(m.genres || []).map((g) => `<span class="tag">${esc(g)}</span>`).join("")}</span>
        ${m.confidence && m.verified !== "verified" ? `<span class="small muted">Sure: ${Math.round(m.confidence * 100)}%</span>` : ""}</div></div>
    ${m.overview ? `<p class="soft" style="margin:0;line-height:1.5">${esc(m.overview)}</p>` : ""}
    <div class="seg" role="group" aria-label="Status">${Object.entries(Catalog.STATUS).map(([k, l]) => `<button data-st="${k}" aria-pressed="${(m.status || "want") === k}">${esc(t.group === "read" ? ({ want: "Want", watching: "Reading", done: "Finished", dropped: "Dropped" })[k] : ({ want: "Want", watching: "Watching", done: "Finished", dropped: "Dropped" })[k])}</button>`).join("")}</div>
    <div class="grid2">
      <button class="btn" id="edit">Edit</button>
      <button class="btn" id="look">Look it up</button>
      ${m.verified !== "verified" ? `<button class="btn" id="okv">It is right</button>` : ""}
      <button class="btn" id="wrong">Not a real title</button>
    </div>
    ${(m.aka || []).length ? `<div class="card stack" style="gap:6px"><span class="label">Also known as</span><p class="small soft" style="margin:0">${esc(m.aka.join(" · "))}</p></div>` : ""}
    <div class="stack"><h2>Found in ${plural(src.length, "place")}</h2>${src.length ? src.map(srcRow).join("") : `<div class="empty small">No sources yet.</div>`}</div>
    <label class="field">Your note<textarea class="input" id="mnote" placeholder="e.g. a friend recommended it">${esc(m.note || "")}</textarea></label>
    <button class="btn block danger" id="mdel">Remove from watchlist</button>`;
  bind("[data-st]", "click", (e, b) => { Catalog.update(db, m.id, { status: b.dataset.st }); saveDb(); titleScreen(m.id); });
  bind("#edit", "click", () => titleDialog(m));
  bind("#look", "click", () => sync("openUrl", "https://www.google.com/search?q=" + enc([m.title, m.year, t.label].filter(Boolean).join(" "))));
  bind("#okv", "click", () => { Catalog.verify(db, m.id, {}, "verified", "you"); saveDb(); toast("Marked as checked"); titleScreen(m.id); });
  bind("#wrong", "click", () => { Catalog.verify(db, m.id, {}, "rejected", "you"); saveDb(); toast("Hidden from your watchlist"); location.hash = "#/watch"; });
  bind("#mnote", "change", (e, el) => { Catalog.update(db, m.id, { note: el.value }); saveDb(); toast("Saved"); });
  bind("#mdel", "click", () => { if (confirm(`Remove "${m.title}" from your watchlist?`)) { Catalog.remove(db, m.id); saveDb(); location.hash = "#/watch"; } });
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
