/* Reel Shelf: checking watchlist titles online (stage 3). The phone (Java) does the lookups in free databases:
   TMDB (movies and series, with your own free key) or Wikidata (no key), AniList and Jikan (anime), MangaDex (manga).
   Answers wait in a file until this page applies them with Catalog.verify, so nothing is ever overwritten.
   Runs when you tap Process (app open), or at night if you switch that on (Wi-Fi + charging + phone not in use).
   Unsure titles (remakes, two close names) are shown to you with posters to pick; nothing is guessed silently. */
"use strict";

const Verify = (() => {
  const NOT_FOUND_RETRY = 30 * 86400e3;

  // ---------------------------------------------------------------- pure part (tested in node and Chromium)

  /** Applies the phone's answers {id: result} to the watchlist. Returns counts. Does not save. */
  function apply(db, results) {
    const n = { verified: 0, review: 0, notFound: 0, skipped: 0 };
    for (const [id, r] of Object.entries(results || {})) {
      const m = Catalog.get(db, id);
      if (!m || !r || (m.verified && m.verified !== "unverified")) { n.skipped++; continue; }  // gone, or you decided already
      const check = { verdict: r.verdict, confidence: Number(r.confidence) || 0, by: String(r.by || ""), note: String(r.note || ""), at: r.checked_at || Date.now() };
      if (r.verdict === "verified" && r.facts) {
        const kept = Catalog.verify(db, id, r.facts, "verified", r.by || "online");
        if (kept) { kept.check = check; delete kept.review; }
        n.verified++;
      } else if (r.verdict === "conflict") {
        const kept = Catalog.verify(db, id, {}, "conflict", r.by || "online");  // your reading stays until you pick
        if (kept) { kept.check = check; kept.review = { choices: (r.choices || []).slice(0, 4), note: check.note }; }
        n.review++;
      } else {
        m.checked_at = check.at;  // stays "unverified"; tried again in 30 days or when it is seen again
        m.check = check;
        if ((r.choices || []).length) m.review = { choices: r.choices.slice(0, 3), note: check.note };
        n.notFound++;
      }
    }
    return n;
  }

  /** You picked one of the choices: it becomes the verified title. */
  function choose(db, id, i) {
    const m = Catalog.get(db, id);
    const c = m && m.review && m.review.choices[i];
    if (!c) return null;
    const kept = Catalog.verify(db, id, c.facts || {}, "verified", "you");
    if (kept) { delete kept.review; kept.check = { ...(kept.check || {}), verdict: "verified", by: "you", note: `You picked it (${c.source})`, at: Date.now() }; }
    return kept;
  }
  /** It is right as it was read, even if no database has it. */
  function keep(db, id) { const m = Catalog.verify(db, id, {}, "verified", "you"); if (m) delete m.review; return m; }
  /** Not a title (a random screenshot): hidden from the watchlist, not deleted. */
  function reject(db, id) { const m = Catalog.verify(db, id, {}, "rejected", "you"); if (m) delete m.review; return m; }
  /** You typed the right name: it is looked up again on the next Process. */
  function retitle(db, id, title) {
    const m = Catalog.get(db, id);
    if (!m || !String(title || "").trim()) return null;
    if (Catalog.normTitle(title) !== Catalog.normTitle(m.title)) m.aka = [...new Set([...(m.aka || []), m.title])];
    Catalog.update(db, id, { title });
    m.verified = "unverified";
    delete m.checked_at;
    delete m.review;
    delete m.check;
    m.updated_at = Date.now();
    return m;
  }

  function counts(db, now = Date.now()) {
    const list = db.media || [];
    const waiting = list.filter((m) => (!m.verified || m.verified === "unverified") && !(m.checked_at && (m.updated_at || 0) <= m.checked_at && now - m.checked_at < NOT_FOUND_RETRY));
    return {
      waiting: waiting.length,
      review: list.filter((m) => m.verified === "conflict").length,
      notFound: list.filter((m) => (!m.verified || m.verified === "unverified") && m.checked_at).length,
      verified: list.filter((m) => m.verified === "verified").length,
    };
  }

  // ---------------------------------------------------------------- the screen (uses local.js: db, saveDb, phone, sync...)

  let job = null;  // {done, total, sum, error}
  const TYPE = (t) => (typeof Catalog !== "undefined" ? Catalog.typeInfo(db, t).label : t);
  const LANG = (l) => (l ? Catalog.langName(l) : "");

  /** Called when the page opens or comes back: applies answers from Process or the night. */
  function onOpen(quiet) {
    let got = {};
    try { got = JSON.parse(sync("takeVerified") || "{}"); } catch (e) { got = {}; }
    if (!Object.keys(got).length) return null;
    const n = apply(db, got);
    saveDb();
    if (!quiet) {
      const parts = [n.verified && `${n.verified} verified`, n.review && `${n.review} to pick`, n.notFound && `${n.notFound} not found`].filter(Boolean);
      if (parts.length) toast(`Titles checked online: ${parts.join(", ")}`);
    }
    return n;
  }

  function start() {
    if (job && !job.finished) return;
    if (!settings.tmdbKey) toast("No TMDB key: movies are checked on Wikidata. Add a free key in Settings for posters and genres.");
    job = { done: 0, total: counts(db).waiting, finished: false };
    onProgress.verify = (d, t) => { job.done = d; job.total = t; paint(); };
    phone("verifyNow").then((s) => { job.sum = JSON.parse(s || "{}"); })
      .catch((e) => { job.error = e.message; })
      .finally(() => { job.finished = true; const n = onOpen(true); job.applied = n; paint(); });
    paint();
  }

  function choiceHtml(m, c, i) {
    return `<button class="list-item" data-pick="${esc(m.id)}" data-i="${i}">
      ${c.poster ? `<img class="thumb sm" src="${esc(c.poster)}" alt="" loading="lazy" referrerpolicy="no-referrer">` : `<span class="thumb sm"></span>`}
      <span class="grow stack" style="gap:2px"><strong class="clamp">${esc(c.title)}</strong>
      <span class="small muted">${esc([c.year || "", TYPE(c.type), LANG(c.language)].filter(Boolean).join(" · "))}</span>
      <span class="small muted">${esc(c.source)} · match ${Math.round((Number(c.score) || 0) * 100)}%</span></span>${ICON.chev}</button>`;
  }

  function reviewHtml(m) {
    const ch = (m.review && m.review.choices) || [];
    const seen = (m.sources || [])[0];
    return `<div class="card stack" data-entry="${esc(m.id)}">
      <div class="row between"><strong class="clamp">${esc(m.title)}${m.year ? ` (${m.year})` : ""}</strong><span class="tag warn">${m.verified === "conflict" ? "Pick one" : "Not found"}</span></div>
      ${seen && seen.text ? `<span class="small muted clamp">Seen as: ${esc(seen.text)}</span>` : ""}
      ${m.review && m.review.note ? `<span class="small muted">${esc(m.review.note)}</span>` : ""}
      ${ch.map((c, i) => choiceHtml(m, c, i)).join("")}
      <form class="row" data-retitle="${esc(m.id)}" style="gap:8px"><input class="input grow" name="t" placeholder="Type the right name" aria-label="Right name for ${esc(m.title)}"><button class="btn">Search again</button></form>
      <div class="grid2"><button class="btn" data-keep="${esc(m.id)}">It is right as read</button><button class="btn danger" data-reject="${esc(m.id)}">Not a title</button></div>
    </div>`;
  }

  function screen() {
    const c = counts(db);
    const running = job && !job.finished;
    const pct = running && job.total ? Math.round((job.done / job.total) * 100) : 0;
    const todo = (db.media || []).filter((m) => m.verified === "conflict" || ((!m.verified || m.verified === "unverified") && m.checked_at));
    const night = (() => { try { return JSON.parse(sync("nightlyInfo") || "{}"); } catch (e) { return {}; } })();
    $app.innerHTML = `${header("Check titles online", "#/watch")}
      <div class="grid3">
        <div class="card stack" style="gap:2px"><strong style="font-size:22px">${c.waiting}</strong><span class="small muted">to check</span></div>
        <div class="card stack" style="gap:2px"><strong style="font-size:22px">${c.verified}</strong><span class="small muted">verified</span></div>
        <div class="card stack" style="gap:2px"><strong style="font-size:22px">${c.review + c.notFound}</strong><span class="small muted">need you</span></div>
      </div>
      ${running ? `<div class="card stack"><strong>Checking ${Math.min(job.done + 1, job.total)} of ${job.total}</strong><span class="bar"><span style="width:${pct}%"></span></span>
          <span class="small muted">Keep the app open. Leaving it pauses the check; it continues next time.</span><button class="btn block" id="vstop">Stop</button></div>`
        : `<button class="btn primary block" id="vgo" ${c.waiting ? "" : "disabled"}>${c.waiting ? `Process: check ${plural(c.waiting, "title")} online` : "Nothing new to check"}</button>`}
      ${job && job.finished ? `<div class="card stack"><strong>${job.error ? esc(job.error) : job.sum && job.sum.offline ? "No internet: try again on Wi-Fi or mobile data" : job.sum && job.sum.stopped ? "Paused" : "Done"}</strong>
          ${job.applied ? `<span class="small muted">${job.applied.verified} verified, ${job.applied.review} to pick, ${job.applied.notFound} not found</span>` : ""}</div>` : ""}
      <p class="hint">Movies and series: ${settings.tmdbKey ? "TMDB (your key) and Wikidata" : "Wikidata (add a free TMDB key in Settings for posters and genres)"}. Anime: AniList and MyAnimeList. Manga: AniList and MangaDex.
        A title is marked verified only when the name matches and a second source agrees, or the name is an exact, unique match.</p>
      <p class="hint">Nightly check: ${night.on ? "on (Wi-Fi, charging, phone not in use)" : "off"}${night.last ? ` · last night: ${night.last.checked || 0} checked` : ""}. Change it in <a href="#/settings">Settings</a>.</p>
      ${todo.length ? `<h2>Need you (${todo.length})</h2><div class="stack">${todo.slice(0, 60).map(reviewHtml).join("")}</div>` : ""}`;
    bind("#vgo", "click", start);
    bind("#vstop", "click", () => sync("stopVerify"));
    bind("[data-pick]", "click", (e, b) => { choose(db, b.dataset.pick, Number(b.dataset.i)); saveDb(); toast("Saved"); screen(); });
    bind("[data-keep]", "click", (e, b) => { keep(db, b.dataset.keep); saveDb(); screen(); });
    bind("[data-reject]", "click", (e, b) => { reject(db, b.dataset.reject); saveDb(); toast("Hidden from the watchlist"); screen(); });
    bind("[data-retitle]", "submit", (e, f) => { e.preventDefault(); if (retitle(db, f.dataset.retitle, f.t.value)) { saveDb(); toast("It will be looked up on the next Process"); screen(); } });
  }

  /** The card on the Watchlist screen that leads to the check. */
  function cardHtml() {
    const v = counts(db);
    if (!v.waiting && !v.review) return "";
    const bits = [v.waiting && `${v.waiting} new`, v.review && `${v.review} for you to pick`].filter(Boolean).join(" · ");
    return `<a class="card" href="#/check"><span class="grow stack" style="gap:2px"><strong>Look up online</strong><span class="small muted">${bits}</span></span>${ICON.chev}</a>`;
  }

  function paint() { if (location.hash === "#/check") screen(); }

  /** The Settings section: your own TMDB key (stays on this phone) and the nightly switch. */
  function settingsHtml() {
    const night = (() => { try { return JSON.parse(sync("nightlyInfo") || "{}"); } catch (e) { return {}; } })();
    return `<div class="stack"><h2>Watchlist online check</h2>
      <label class="field">TMDB API key (free, optional)<input class="input" id="tmdbkey" type="password" autocomplete="off" spellcheck="false" value="${esc(settings.tmdbKey || "")}" placeholder="Paste your key or read access token"></label>
      <div class="grid2"><button class="btn" id="tmdbsave">Save key</button><button class="btn" id="tmdbget">Get a free key</button></div>
      <p class="hint">Without a key, movies and series are checked on Wikidata (no posters or genres). The key stays on this phone and is only sent to TMDB.</p>
      <div class="opt"><span class="grow stack" style="gap:2px"><strong>Check new titles every night</strong><span class="small muted">Only on Wi-Fi, while charging and not in use, like a WhatsApp backup. Only new titles. Off by default.</span></span>
        <button class="switch" role="switch" id="nightly" aria-checked="${!!night.on}" aria-label="Check new titles every night"><span></span></button></div>
      ${night.last ? `<p class="hint">Last night: ${night.last.checked || 0} checked, ${night.last.verified || 0} verified${night.last.left ? `, ${night.last.left} left for the next night` : ""}.</p>` : ""}
      <a class="btn block" href="#/check">Check titles now</a></div>`;
  }
  function bindSettings(redraw) {
    bind("#tmdbsave", "click", () => { settings.tmdbKey = document.getElementById("tmdbkey").value.trim().slice(0, 400); saveSettings(); toast(settings.tmdbKey ? "Key saved on this phone" : "Key removed"); });
    bind("#tmdbget", "click", () => sync("openUrl", "https://www.themoviedb.org/settings/api"));
    bind("#nightly", "click", (e, b) => { const on = b.getAttribute("aria-checked") !== "true"; sync("setNightly", on); toast(on ? "Nightly check on" : "Nightly check off"); redraw(); });
  }

  return { cardHtml, apply, choose, keep, reject, retitle, counts, onOpen, screen, settingsHtml, bindSettings, start };
})();

if (typeof module !== "undefined") module.exports = Verify;
