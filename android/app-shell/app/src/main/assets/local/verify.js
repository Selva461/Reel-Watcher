/* Reel Shelf: checking watchlist titles online (stage 3). The phone (Java) does the lookups in free databases:
   TMDB (movies and series, with your own free key) or Wikidata (no key), AniList and Jikan (anime), MangaDex (manga).
   Answers wait in a file until this page applies them with Catalog.verify, so nothing is ever overwritten.
   Runs when you tap Process (app open), or at night if you switch that on (Wi-Fi + charging + phone not in use).
   Nothing waits for you: the phone picks the best match itself and its official name replaces the one read from the
   screenshot. Titles no source matches closely enough keep their name and are tried again later. */
"use strict";

const Verify = (() => {
  const NOT_FOUND_RETRY = 30 * 86400e3;

  // ---------------------------------------------------------------- pure part (tested in node and Chromium)

  /** Applies the phone's answers {id: result} to the watchlist. Returns counts. Does not save. */
  function apply(db, results) {
    const n = { verified: 0, review: 0, notFound: 0, skipped: 0 };
    for (const [id, r] of Object.entries(results || {})) {
      const m = Catalog.get(db, id);
      if (m && r && r.verdict === "details") {  // only the length of a title checked before
        if (Number(r.runtime) > 0) m.runtime = Math.round(Number(r.runtime));
        if (Number(r.episodes) > 0 && !m.episodes) m.episodes = Math.round(Number(r.episodes));
        m.runtime_tried = r.checked_at || Date.now();
        n.lengths = (n.lengths || 0) + 1;
        continue;
      }
      if (!m || !r || (m.verified && m.verified !== "unverified")) { n.skipped++; continue; }  // gone, or you decided already
      const check = { verdict: r.verdict, confidence: Number(r.confidence) || 0, by: String(r.by || ""), note: String(r.note || ""), at: r.checked_at || Date.now() };
      if (r.verdict === "verified" && r.facts) {
        const kept = Catalog.verify(db, id, r.facts, "verified", r.by || "online");
        if (kept) { kept.check = check; delete kept.review; }
        n.verified++;
      } else if (r.verdict === "conflict") {  // an answer from before 1.3.3: asked again under the automatic rules
        delete m.checked_at;
        n.skipped++;
      } else {
        m.checked_at = check.at;  // stays "unverified"; tried again in 30 days or when it is seen again
        m.check = check;
        n.notFound++;
      }
    }
    return n;
  }

  /** Once, on the update to 1.3.3: titles that waited for you to pick, or were not found under the old rules, are
      checked again (now with Wikipedia and automatic picking). Returns how many. Does not save. */
  function migrate(db) {
    if ((db.verify_rules || 0) >= 2) return 0;
    let n = 0;
    for (const m of db.media || []) {
      if (m.verified === "conflict" || ((!m.verified || m.verified === "unverified") && m.checked_at)) {
        m.verified = "unverified";
        delete m.checked_at;
        delete m.review;
        n++;
      }
    }
    db.verify_rules = 2;
    return n;
  }

  function counts(db, now = Date.now()) {
    const list = db.media || [];
    const waiting = list.filter((m) => (!m.verified || m.verified === "unverified") && !(m.checked_at && (m.updated_at || 0) <= m.checked_at && now - m.checked_at < NOT_FOUND_RETRY));
    return {
      waiting: waiting.length,
      notFound: list.filter((m) => (!m.verified || m.verified === "unverified") && m.checked_at).length,
      verified: list.filter((m) => m.verified === "verified").length,
      // checked before lengths were kept: the next Process looks up how long they are (for "under 1.5 hours")
      lengths: list.filter((m) => m.verified === "verified" && !(m.runtime > 0) && !m.runtime_tried && m.ext && (m.ext.tmdb || m.ext.anilist || m.ext.mal)
        && (typeof Catalog === "undefined" || Catalog.typeInfo(db, m.type).group === "watch")).length,
    };
  }

  // ---------------------------------------------------------------- the screen (uses local.js: db, saveDb, phone, sync...)

  let job = null;  // {done, total, sum, error}
  const TYPE = (t) => (typeof Catalog !== "undefined" ? Catalog.typeInfo(db, t).label : t);
  const LANG = (l) => (l ? Catalog.langName(l) : "");

  /** Called when the page opens or comes back: applies answers from Process or the night. */
  function onOpen(quiet) {
    const rules = db.verify_rules;
    if (migrate(db) || rules !== db.verify_rules) saveDb();
    let got = {};
    try { got = JSON.parse(sync("takeVerified") || "{}"); } catch (e) { got = {}; }
    if (!Object.keys(got).length) return null;
    const n = apply(db, got);
    saveDb();
    if (!quiet) {
      const parts = [n.verified && `${n.verified} verified`, n.notFound && `${n.notFound} not found`].filter(Boolean);
      if (parts.length) toast(`Titles checked online: ${parts.join(", ")}`);
    }
    return n;
  }

  function start() {
    if (job && !job.finished) return;
    if (!settings.tmdbKey) toast("No TMDB key: movies are checked on Wikidata. Add a free key in Settings for posters and genres.");
    const c0 = counts(db);
    job = { done: 0, total: c0.waiting || c0.lengths, finished: false };
    onProgress.verify = (d, t) => { job.done = d; job.total = t; paint(); };
    phone("verifyNow").then((s) => { job.sum = JSON.parse(s || "{}"); })
      .catch((e) => { job.error = e.message; })
      .finally(() => { job.finished = true; const n = onOpen(true); job.applied = n; paint(); });
    paint();
  }

  function screen() {
    const c = counts(db);
    const running = job && !job.finished;
    const pct = running && job.total ? Math.round((job.done / job.total) * 100) : 0;
    const night = (() => { try { return JSON.parse(sync("nightlyInfo") || "{}"); } catch (e) { return {}; } })();
    $app.innerHTML = `${header("Check titles online", "#/inbox")}
      <div class="grid3">
        <div class="card stack" style="gap:2px"><strong style="font-size:22px">${c.waiting}</strong><span class="small muted">to check</span></div>
        <div class="card stack" style="gap:2px"><strong style="font-size:22px">${c.verified}</strong><span class="small muted">verified</span></div>
        <div class="card stack" style="gap:2px"><strong style="font-size:22px">${c.notFound}</strong><span class="small muted">not found yet</span></div>
      </div>
      ${running ? `<div class="card stack"><strong>Checking ${Math.min(job.done + 1, job.total)} of ${job.total}</strong><span class="bar"><span style="width:${pct}%"></span></span>
          <span class="small muted">You can leave the app: it keeps checking, with a notification to stop it.</span><button class="btn block" id="vstop">Stop</button></div>`
        : `<button class="btn primary block" id="vgo" ${c.waiting || c.lengths ? "" : "disabled"}>${c.waiting ? `Process: check ${plural(c.waiting, "title")} online` : c.lengths ? `Process: find how long ${plural(c.lengths, "title")} run` : "Nothing new to check"}</button>`}
      ${job && job.finished ? `<div class="card stack"><strong>${job.error ? esc(job.error) : job.sum && job.sum.offline ? "No internet: try again on Wi-Fi or mobile data" : job.sum && job.sum.stopped ? "Paused" : "Done"}</strong>
          ${job.applied ? `<span class="small muted">${job.applied.verified} verified and renamed, ${job.applied.notFound} not found</span>` : ""}</div>` : ""}
      <p class="hint">Movies and series: ${settings.tmdbKey ? "TMDB (your key) and Wikidata" : "Wikidata (add a free TMDB key in Settings for posters and genres)"}. Anime: AniList and MyAnimeList. Manga: AniList and MangaDex. Names none of them find are searched on Wikipedia.
        The best match is picked for you and the title takes its official name. It is verified when a second source agrees, or the name is a close match on its own; anything less keeps the name read and is tried again in 30 days.</p>
      <p class="hint">Nightly check: ${night.on ? "on (Wi-Fi, charging, phone not in use)" : "off"}${night.last ? ` · last night: ${night.last.checked || 0} checked` : ""}. Change it in <a href="#/settings">Settings</a>.</p>
`;
    bind("#vgo", "click", start);
    bind("#vstop", "click", () => sync("stopVerify"));
  }

  /** The card on the Watchlist screen that leads to the check. */
  function cardHtml() {
    const v = counts(db);
    if (!v.waiting) return "";
    return `<a class="card" href="#/check"><span class="grow stack" style="gap:2px"><strong>Look up online</strong><span class="small muted">${v.waiting} new</span></span>${ICON.chev}</a>`;
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

  return { cardHtml, apply, migrate, counts, onOpen, screen, settingsHtml, bindSettings, start, get job() { return job; } };
})();

if (typeof module !== "undefined") module.exports = Verify;
