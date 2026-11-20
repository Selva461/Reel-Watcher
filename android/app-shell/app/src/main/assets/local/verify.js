/* Reel Shelf: checking watchlist titles online (stage 3). The phone (Java) does the lookups in free databases:
   TMDB (movies and series, with your own free key) or Wikidata (no key), AniList and Jikan (anime), MangaDex (manga).
   Answers wait in a file until this page applies them with Catalog.verify, so nothing is ever overwritten.
   Runs when you tap Process (app open), or at night if you switch that on (phone not in use, battery at 40% or more, any internet).
   Nothing waits for you: the phone picks the best match itself and its official name replaces the one read from the
   screenshot. When no source matches closely enough, the phone AI (if downloaded) reads the closest matches and a web
   search for the name, and picks one or none. Titles still not found keep their name and are tried again later.
   Each title also gets what a movie app shows: seasons with their episodes, and a rating. */
"use strict";

const Verify = (() => {
  const NOT_FOUND_RETRY = 30 * 86400e3;
  const AI_PER_RUN = 20;

  // ---------------------------------------------------------------- pure part (tested in node and Chromium)

  /** Applies the phone's answers {id: result} to the watchlist. Returns counts. Does not save. */
  function apply(db, results) {
    const n = { verified: 0, review: 0, notFound: 0, skipped: 0 };
    for (const [id, r] of Object.entries(results || {})) {
      const m = Catalog.get(db, id);
      if (m && r && r.verdict === "details") {  // seasons, rating and length of a title checked before
        if (Number(r.runtime) > 0) m.runtime = Math.round(Number(r.runtime));
        if (Number(r.episodes) > 0 && !m.episodes) m.episodes = Math.round(Number(r.episodes));
        Catalog.setDetails(m, r);
        m.details_at = r.checked_at || Date.now();
        n.lengths = (n.lengths || 0) + 1;
        continue;
      }
      if (!m || !r || (m.verified && m.verified !== "unverified")) { n.skipped++; continue; }  // gone, or you decided already
      const check = { verdict: r.verdict, confidence: Number(r.confidence) || 0, by: String(r.by || ""), note: String(r.note || ""), at: r.checked_at || Date.now() };
      if (r.verdict === "verified" && r.facts) {
        const kept = Catalog.verify(db, id, r.facts, "verified", r.by || "online");
        if (kept) { kept.check = check; delete kept.review; kept.details_at = check.at; }
        n.verified++;
      } else if (r.verdict === "conflict") {  // an answer from before 1.3.3: asked again under the automatic rules
        delete m.checked_at;
        n.skipped++;
      } else {
        m.checked_at = check.at;  // stays "unverified"; tried again in 30 days or when it is seen again
        // close matches that two independent sources have, for the phone AI to pick from (one source is never enough)
        m.check = { ...check, choices: (r.choices || []).filter((c) => c && c.facts && Number(c.sources) >= 2).slice(0, 3) };
        delete m.ai_at;
        n.notFound++;
      }
    }
    return n;
  }

  /** Once per change of rules. 2 (1.3.3): titles that waited for you to pick, or were not found under the old rules,
      are checked again (now with Wikipedia and automatic picking). 3 (1.3.4): comment lines saved as titles ("View 4
      replies", "12 likes Reply", usernames) are deleted. 4 (1.3.5): titles confirmed by one source only are checked
      again, since two independent sources must agree now. Returns how many changed. Does not save. */
  function migrate(db) {
    const rules = db.verify_rules || 0;
    if (rules >= 4) return 0;
    let n = 0;
    if (rules < 2) for (const m of db.media || []) {
      if (m.verified === "conflict" || ((!m.verified || m.verified === "unverified") && m.checked_at)) {
        m.verified = "unverified";
        delete m.checked_at;
        delete m.review;
        n++;
      }
    }
    if (rules < 4) for (const m of db.media || []) {
      const by = String(m.verified_by || "");
      if (m.verified === "verified" && by && !/\+/.test(by) && !["you", "phone AI"].includes(by)) {
        m.verified = "unverified";
        delete m.checked_at;
        delete m.check;
        n++;
      }
      if ((m.seasons || []).length && !m.seasons_by) delete m.details_at;  // seasons looked up again, checked with a second source
    }
    if (rules < 3 && typeof Titles !== "undefined") {
      const before = (db.media || []).length;
      db.media = (db.media || []).filter((m) => m.verified === "verified" || !Titles.isChrome(m.title));
      n += before - db.media.length;
    }
    db.verify_rules = 4;
    return n;
  }

  /** Titles not found that have close matches, not yet shown to the phone AI. */
  function aiTodo(db) {
    return (db.media || []).filter((m) => (!m.verified || m.verified === "unverified") && m.check && m.check.verdict === "not_found"
      && (m.check.choices || []).length && !m.ai_at);
  }

  /** The question for the phone AI: the name as read, the closest matches online, and what a web search says. */
  function aiPrompt(m, web) {
    const seen = ((m.sources || [])[0] || {}).text || "";
    const typ = typeof Catalog !== "undefined" ? Catalog.typeInfo(db, m.type).label : m.type;
    const lines = (m.check.choices || []).map((c, i) => `${i + 1}. ${c.title} (${[c.year, c.type, c.language].filter(Boolean).join(", ")})`);
    const w = (web || []).slice(0, 3).map((x) => `- ${x.source}: ${x.title}: ${String(x.text || "").slice(0, 240)}`);
    return `A name was read from a screenshot: "${m.title}".${seen && seen !== m.title ? `\nText around it: "${seen.slice(0, 200)}"` : ""}
It was guessed to be: ${typ}.
Which of these real titles is it?
${lines.join("\n")}${w.length ? `\nWeb search for the name:\n${w.join("\n")}` : ""}
Answer with the number of the right title, or 0 if none of them is it. Answer with the number only.`;
  }

  /** The phone AI's number: 1..n, or 0 for none / an answer it could not give. */
  function aiNumber(text, n) {
    const k = parseInt((String(text || "").match(/\d+/) || ["0"])[0], 10);
    return k >= 1 && k <= n ? k : 0;
  }

  /** Lets the phone AI pick for titles no database matched closely. Quiet: nothing is asked. Returns how many it renamed. */
  async function aiPick() {
    if (typeof modelInfo !== "function" || !modelInfo().ready) return 0;
    const list = aiTodo(db).slice(0, AI_PER_RUN);
    if (!list.length) return 0;
    let n = 0;
    sync("allowWork");
    for (const m of list) {
      let web = [];
      try { web = JSON.parse(await phone("webSearch", `${m.title} ${Catalog.typeInfo(db, m.type).label}`) || "[]"); } catch (e) { web = []; }
      let text = "";
      try {
        text = JSON.parse(await phone("generate", aiPrompt(m, web), JSON.stringify({ file: settings.modelFile, gpu: settings.gpu,
          system: "You match a name read from a screenshot to a real movie, series, anime or manga. Answer with one number only.", maxTokens: 6, temperature: 0 }))).text;
      } catch (e) { if (e.message === "stopped") break; continue; }
      m.ai_at = Date.now();
      const c = m.check.choices[aiNumber(text, m.check.choices.length) - 1];
      if (!c) continue;
      const kept = Catalog.verify(db, m.id, c.facts, "verified", "phone AI");
      if (kept) { kept.check = { verdict: "verified", by: "phone AI", note: `Picked by the phone AI from ${c.source}${web.length ? " and a web search" : ""}`, at: Date.now() }; n++; }
    }
    sync("stopModel");
    saveDb();
    return n;
  }

  function counts(db, now = Date.now()) {
    const list = db.media || [];
    const waiting = list.filter((m) => (!m.verified || m.verified === "unverified") && !(m.checked_at && (m.updated_at || 0) <= m.checked_at && now - m.checked_at < NOT_FOUND_RETRY));
    return {
      waiting: waiting.length,
      notFound: list.filter((m) => (!m.verified || m.verified === "unverified") && m.checked_at).length,
      verified: list.filter((m) => m.verified === "verified").length,
      // checked before seasons and ratings were kept: the next Process looks them up once
      lengths: list.filter((m) => m.verified === "verified" && !m.details_at && m.ext && (m.ext.tmdb || m.ext.anilist || m.ext.mal)
        && (typeof Catalog === "undefined" || Catalog.typeInfo(db, m.type).group === "watch")).length,
      quotes: typeof Quotes === "undefined" ? 0 : Quotes.unchecked(db, now).length,
      products: typeof Products === "undefined" ? 0 : Products.unchecked(db, now).length,
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
    settings.verifyRunning = true;  // if the app is closed mid-way (an update, the phone restarting) it carries on next time
    saveSettings();
    onProgress.verify = (d, t) => { job.done = d; job.total = t; paint(); };
    phone("verifyNow").then((s) => { job.sum = JSON.parse(s || "{}"); })
      .catch((e) => { job.error = e.message; })
      .finally(async () => {
        job.applied = onOpen(true);
        try { job.ai = await aiPick(); } catch (e) { job.ai = 0; }
        if (typeof Quotes !== "undefined" && Quotes.unchecked(db).length && !(job.sum && job.sum.offline)) {
          job.step = "quotes";
          paint();
          job.quotes = await Quotes.checkOnline(db, (t) => phone("quoteCheck", t), { stop: () => !!(job.sum && job.sum.stopped) });
          saveDb();
        }
        if (typeof Products !== "undefined" && Products.unchecked(db).length && !(job.sum && job.sum.offline)) {
          job.step = "products";
          paint();
          job.products = await Products.checkOnline(db, (t) => phone("productCheck", t), { stop: () => !!(job.sum && job.sum.stopped) });
          saveDb();
        }
        job.finished = true;
        settings.verifyRunning = false;
        saveSettings();
        paint();
      });
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
      ${running ? `<div class="card stack"><strong>${job.step === "quotes" ? "Looking up quotes on Wikiquote" : job.step === "products" ? "Looking up products" : `Checking ${Math.min(job.done + 1, job.total)} of ${job.total}`}</strong><span class="bar"><span style="width:${pct}%"></span></span>
          <span class="small muted">You can leave the app: it keeps checking, with a notification to stop it.</span><button class="btn block" id="vstop">Stop</button></div>`
        : `<button class="btn primary block" id="vgo" ${c.waiting || c.lengths || c.quotes || c.products ? "" : "disabled"}>${c.waiting ? `Process: check ${plural(c.waiting, "title")} online` : c.lengths ? `Process: seasons and ratings for ${plural(c.lengths, "title")}` : c.quotes ? `Process: look up ${plural(c.quotes, "quote")} online` : c.products ? `Process: look up ${plural(c.products, "product")} online` : "Nothing new to check"}</button>`}
      ${job && job.finished ? `<div class="card stack"><strong>${job.error ? esc(job.error) : job.sum && job.sum.offline ? "No internet: try again on Wi-Fi or mobile data" : job.sum && job.sum.stopped ? "Paused" : "Done"}</strong>
          ${job.applied ? `<span class="small muted">${job.applied.verified} verified and renamed${job.ai ? `, ${job.ai} picked by the phone AI` : ""}, ${Math.max(0, job.applied.notFound - (job.ai || 0))} not found</span>` : ""}
          ${job.quotes !== undefined ? `<span class="small muted">Quotes: ${job.quotes} found on Wikiquote</span>` : ""}
          ${job.products !== undefined ? `<span class="small muted">Products: ${job.products} confirmed in a product database</span>` : ""}</div>` : ""}
      <p class="hint">Movies and series: ${settings.tmdbKey ? "TMDB (your key) and Wikidata" : "Wikidata (add a free TMDB key in Settings for posters and genres)"}. Anime: AniList and MyAnimeList. Manga: AniList and MangaDex. Names none of them find are searched on Wikipedia. Quotes from your screenshots are looked up on Wikiquote (only their first words are sent). Products: their names go to Open Beauty Facts, Open Food Facts and Open Products Facts, and count as confirmed only when the brand and name there match the label.
        The best match is picked for you and the title takes its official name, but only when two independent sources agree on its name, year and kind. One source is never enough: the name read stays and it is tried again in 30 days.${settings.tmdbKey ? "" : " Without a TMDB key, movies and series have only one source (Wikidata), so they cannot be confirmed."}</p>
      <p class="hint">Nightly check: ${night.on ? "on (phone not in use, battery 40%+)" : "off"}${night.last ? ` · last night: ${night.last.checked || 0} checked` : ""}. Change it in <a href="#/settings">Settings</a>.</p>
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

  /** The app was closed while checking (an update installs by closing it): carries on by itself. */
  function resume() {
    if (settings.verifyRunning && !(job && !job.finished) && (counts(db).waiting || counts(db).lengths)) { start(); return true; }
    return false;
  }

  /** The Settings section: your own TMDB key (stays on this phone) and the nightly switch. */
  function settingsHtml() {
    const night = (() => { try { return JSON.parse(sync("nightlyInfo") || "{}"); } catch (e) { return {}; } })();
    return `<div class="stack"><h2>Watchlist online check</h2>
      <label class="field">TMDB API key (free, optional)<input class="input" id="tmdbkey" type="password" autocomplete="off" spellcheck="false" value="${esc(settings.tmdbKey || "")}" placeholder="Paste your key or read access token"></label>
      <div class="grid2"><button class="btn" id="tmdbsave">Save key</button><button class="btn" id="tmdbget">Get a free key</button></div>
      <p class="hint">Without a key, movies and series are checked on Wikidata (no posters or genres). The key stays on this phone and is only sent to TMDB.</p>
      <label class="field">OMDb API key, for IMDb ratings (free, optional)<input class="input" id="omdbkey" type="password" autocomplete="off" spellcheck="false" value="${esc(settings.omdbKey || "")}" placeholder="Paste your OMDb key"></label>
      <div class="grid2"><button class="btn" id="omdbsave" aria-label="Save OMDb key">Save key</button><button class="btn" id="omdbget">Get a free key</button></div>
      <p class="hint">IMDb has no free way to read its ratings; OMDb gives them with a free key (1,000 titles a day). Without it, movies show the TMDB score and anime the MyAnimeList score. The key stays on this phone and is only sent to OMDb.</p>
      <div class="opt"><span class="grow stack" style="gap:2px"><strong>Check new titles every night</strong><span class="small muted">When the phone is not in use and the battery is at 40% or more. Mobile data is fine. Only new titles. Off by default.</span></span>
        <button class="switch" role="switch" id="nightly" aria-checked="${!!night.on}" aria-label="Check new titles every night"><span></span></button></div>
      ${night.last ? `<p class="hint">Last night: ${night.last.checked || 0} checked, ${night.last.verified || 0} verified${night.last.left ? `, ${night.last.left} left for the next night` : ""}.</p>` : ""}
      <a class="btn block" href="#/check">Check titles now</a></div>`;
  }
  function bindSettings(redraw) {
    bind("#tmdbsave", "click", () => { settings.tmdbKey = document.getElementById("tmdbkey").value.trim().slice(0, 400); saveSettings(); toast(settings.tmdbKey ? "Key saved on this phone" : "Key removed"); });
    bind("#tmdbget", "click", () => sync("openUrl", "https://www.themoviedb.org/settings/api"));
    bind("#omdbsave", "click", () => { settings.omdbKey = document.getElementById("omdbkey").value.trim().slice(0, 100); saveSettings(); toast(settings.omdbKey ? "Key saved on this phone" : "Key removed"); });
    bind("#omdbget", "click", () => sync("openUrl", "https://www.omdbapi.com/apikey.aspx"));
    bind("#nightly", "click", (e, b) => { const on = b.getAttribute("aria-checked") !== "true"; sync("setNightly", on); toast(on ? "Nightly check on" : "Nightly check off"); redraw(); });
  }

  return { resume, cardHtml, apply, migrate, aiPrompt, aiNumber, aiTodo, counts, onOpen, screen, settingsHtml, bindSettings, start, get job() { return job; } };
})();

if (typeof module !== "undefined") module.exports = Verify;
