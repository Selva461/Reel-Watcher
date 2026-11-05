/* Reel Shelf watchlist: movies, series, dramas, anime, manga and every other kind of title, from screenshots and reels.
   No AI and no network here: this file only stores, merges (dedupes), filters and counts titles.
   Other parts of the app write into it through Catalog.add(db, candidate) and Catalog.verify(db, id, facts).
   Stored inside the same library file as the reels: db.media (titles) and db.mediaTypes (categories you added). */
"use strict";

const Catalog = (() => {
  // ---------------------------------------------------------------- categories (extensible)
  // group: "watch" (screen) or "read" (page) or "other". aliases are words that mean the same category.
  // New categories can be added at run time (addType); unknown ids are kept and shown as they are, never dropped.
  const BASE_TYPES = [
    { id: "movie", label: "Movie", plural: "Movies", group: "watch", aliases: ["film", "feature", "cinema"] },
    { id: "series", label: "Series", plural: "Series", group: "watch", aliases: ["tv", "tv series", "web series", "show", "tv show", "netflix series", "miniseries", "limited series", "sitcom"] },
    { id: "kdrama", label: "K-drama", plural: "K-dramas", group: "watch", aliases: ["korean drama", "k drama", "korean series"] },
    { id: "drama", label: "Asian drama", plural: "Asian dramas", group: "watch", aliases: ["cdrama", "c-drama", "chinese drama", "jdrama", "j-drama", "japanese drama", "thai drama", "lakorn", "turkish drama", "dizi", "taiwanese drama", "telenovela"] },
    { id: "anime", label: "Anime", plural: "Anime", group: "watch", aliases: ["anime series", "ova", "ona"] },
    { id: "anime_movie", label: "Anime movie", plural: "Anime movies", group: "watch", aliases: ["anime film"] },
    { id: "animation", label: "Animation", plural: "Animation", group: "watch", aliases: ["cartoon", "animated", "animated movie", "animated series", "donghua", "pixar", "disney animation"] },
    { id: "documentary", label: "Documentary", plural: "Documentaries", group: "watch", aliases: ["docuseries", "docu", "documentary series"] },
    { id: "reality", label: "Reality / variety", plural: "Reality and variety", group: "watch", aliases: ["reality show", "variety show", "game show", "talk show"] },
    { id: "short", label: "Short film", plural: "Short films", group: "watch", aliases: ["short film", "short"] },
    { id: "standup", label: "Stand-up", plural: "Stand-up specials", group: "watch", aliases: ["stand up", "comedy special"] },
    { id: "manga", label: "Manga", plural: "Manga", group: "read", aliases: ["japanese comic"] },
    { id: "manhwa", label: "Manhwa", plural: "Manhwa", group: "read", aliases: ["korean comic"] },
    { id: "manhua", label: "Manhua", plural: "Manhua", group: "read", aliases: ["chinese comic"] },
    { id: "webtoon", label: "Webtoon", plural: "Webtoons", group: "read", aliases: ["webcomic", "web comic"] },
    { id: "comic", label: "Comic", plural: "Comics", group: "read", aliases: ["graphic novel", "comic book", "marvel comic", "dc comic"] },
    { id: "light_novel", label: "Light novel", plural: "Light novels", group: "read", aliases: ["ln", "web novel", "webnovel"] },
    { id: "book", label: "Book", plural: "Books", group: "read", aliases: ["novel"] },
    { id: "game", label: "Game", plural: "Games", group: "other", aliases: ["video game"] },
    { id: "other", label: "Other", plural: "Other", group: "other", aliases: [] },
  ];
  const GROUPS = { watch: "To watch", read: "To read", other: "Other" };

  function types(db) {
    const extra = (db && db.mediaTypes) || [];
    const out = BASE_TYPES.slice();
    for (const t of extra) if (t && t.id && !out.some((x) => x.id === t.id)) out.push({ group: "other", aliases: [], plural: t.label, ...t, custom: true });
    return out;
  }
  function typeInfo(db, id) {
    return types(db).find((t) => t.id === id) || { id: id || "other", label: prettyId(id || "other"), plural: prettyId(id || "other"), group: "other", aliases: [] };
  }
  function prettyId(id) { return String(id).replace(/[_-]+/g, " ").replace(/^./, (c) => c.toUpperCase()); }

  /** Any word for a category ("Netflix series", "K drama", "donghua", "film") to its id. Unknown words become a new id. */
  function typeId(db, word) {
    const w = String(word || "").toLowerCase().replace(/[^a-z0-9]+/g, " ").trim();
    if (!w) return "other";
    for (const t of types(db)) {
      if (t.id === w.replace(/ /g, "_") || t.label.toLowerCase().replace(/[^a-z0-9]+/g, " ").trim() === w) return t.id;
      if (t.plural && t.plural.toLowerCase().replace(/[^a-z0-9]+/g, " ").trim() === w) return t.id;
      if ((t.aliases || []).some((x) => x.replace(/[^a-z0-9]+/g, " ").trim() === w)) return t.id;
    }
    return w.replace(/ /g, "_").slice(0, 40);
  }

  /** Add your own category. Returns its id. */
  function addType(db, label, group) {
    const id = typeId(db, label);
    if (types(db).some((t) => t.id === id)) return id;
    (db.mediaTypes = db.mediaTypes || []).push({ id, label: String(label).trim().slice(0, 40), plural: String(label).trim().slice(0, 40), group: GROUPS[group] ? group : "other" });
    return id;
  }

  // ---------------------------------------------------------------- languages (ISO 639-1 codes)
  const LANGS = {
    en: "English", ko: "Korean", ja: "Japanese", zh: "Chinese", hi: "Hindi", ta: "Tamil", te: "Telugu", ml: "Malayalam", kn: "Kannada",
    bn: "Bengali", mr: "Marathi", pa: "Punjabi", gu: "Gujarati", ur: "Urdu", es: "Spanish", fr: "French", de: "German", it: "Italian",
    pt: "Portuguese", ru: "Russian", tr: "Turkish", ar: "Arabic", fa: "Persian", th: "Thai", id: "Indonesian", ms: "Malay", tl: "Filipino",
    vi: "Vietnamese", pl: "Polish", nl: "Dutch", sv: "Swedish", da: "Danish", no: "Norwegian", fi: "Finnish", he: "Hebrew", el: "Greek",
    cs: "Czech", hu: "Hungarian", ro: "Romanian", uk: "Ukrainian", xx: "No language",
  };
  const LANG_WORDS = { english: "en", hollywood: "en", korean: "ko", kdrama: "ko", japanese: "ja", chinese: "zh", mandarin: "zh", cantonese: "zh",
    hindi: "hi", bollywood: "hi", tamil: "ta", kollywood: "ta", telugu: "te", tollywood: "te", malayalam: "ml", mollywood: "ml", kannada: "kn",
    sandalwood: "kn", spanish: "es", french: "fr", german: "de", italian: "it", portuguese: "pt", russian: "ru", turkish: "tr", arabic: "ar", thai: "th" };
  function langCode(v) {
    const s = String(v || "").toLowerCase().trim();
    if (!s) return "";
    if (LANGS[s]) return s;
    const base = s.split(/[-_]/)[0];
    if (LANGS[base] && base.length === 2) return base;
    if (LANG_WORDS[s]) return LANG_WORDS[s];
    for (const [c, n] of Object.entries(LANGS)) if (n.toLowerCase() === s) return c;
    return s.slice(0, 20);
  }
  function langName(code) { return LANGS[code] || (code ? prettyId(code) : "Unknown"); }

  // ---------------------------------------------------------------- titles and the dedupe key

  const ROMAN = { i: "1", ii: "2", iii: "3", iv: "4", v: "5", vi: "6", vii: "7", viii: "8", ix: "9", x: "10" };
  /** "The Lord of the Rings: The Two Towers (2002)" and "lord of the rings the two towers" give the same key. */
  function normTitle(t) {
    let s = String(t || "").normalize("NFKD").replace(/[̀-ͯ]/g, "").toLowerCase();
    s = s.replace(/&/g, " and ").replace(/['’`]/g, "").replace(/\((19|20)\d\d\)/g, " ");
    s = s.replace(/[^\p{L}\p{N}]+/gu, " ").trim();
    s = s.split(" ").map((w) => ROMAN[w] || w).join(" ");
    s = s.replace(/^(the|a|an) /, "").replace(/ (season|part|vol|volume) 1$/, "");
    return s.trim();
  }
  const groupOf = (db, type) => typeInfo(db, type).group;
  function yearsMatch(a, b) { return !a || !b || Math.abs(Number(a) - Number(b)) <= 1; }
  function idsMatch(a, b) {
    const ea = a.ext || {};
    const eb = b.ext || {};
    let same = false;
    for (const k of Object.keys(ea)) {
      if (!ea[k] || !eb[k]) continue;
      if (String(ea[k]) !== String(eb[k])) return false;  // the same database says these are two different titles
      same = true;
    }
    return same ? true : null;
  }

  /** The stored entry a candidate is the same title as, or null. Same database id wins; else same title + same group
      (watch/read) + years within one + not two different languages. Anime and its manga stay separate on purpose. */
  function findSame(db, c) {
    const list = db.media || [];
    const key = normTitle(c.title);
    const g = groupOf(db, c.type);
    let best = null;
    for (const m of list) {
      const ids = idsMatch(c, m);
      if (ids === true) return m;
      if (ids === false) continue;
      if (groupOf(db, m.type) !== g) continue;
      const names = [m.title, m.original_title, ...(m.aka || [])].map(normTitle);
      if (!key || !names.includes(key)) continue;
      if (!yearsMatch(c.year, m.year)) continue;
      if (c.language && m.language && c.language !== m.language) continue;
      if (!best || (m.verified === "verified" && best.verified !== "verified")) best = m;
    }
    return best;
  }

  // ---------------------------------------------------------------- writing (the API other parts of the app use)

  const STATUS = { want: "Want to watch", watching: "Watching", done: "Finished", dropped: "Dropped" };
  const VERIFIED = { unverified: "Not checked", verified: "Checked online", conflict: "Needs a look", rejected: "Not a real title" };
  const clean = (v, n = 300) => String(v == null ? "" : v).replace(/\s+/g, " ").trim().slice(0, n);
  const uniq = (a) => [...new Set((a || []).map((x) => clean(x, 60)).filter(Boolean))];

  function sourceKey(s) { return `${s.kind}|${s.ref || ""}`; }

  /** Add one title (or one more sighting of a title already stored).
      candidate: { title (required), type, year, language, original_title, aka[], genres[], country, poster, overview, ext{},
                   confidence 0..1, source: { kind: "screenshot"|"reel"|"manual", ref, method, text, confidence } }
      Returns { entry, created, merged } or null when there is no title. Does not save: call saveDb() after a batch. */
  function add(db, c) {
    let title = clean(c && c.title, 200);
    const inTitle = title.match(/\s*[([]((?:18|19|20)\d\d)[)\]]\s*$/);  // "Dune (2021)": the year belongs in year
    if (inTitle) title = title.slice(0, inTitle.index).trim();
    if (!title) return null;
    db.media = db.media || [];
    const cand = { ...c, title, type: typeId(db, c.type || "movie"), language: langCode(c.language), year: toYear(c.year) || (inTitle ? Number(inTitle[1]) : null) };
    const now = Date.now();
    const src = c.source ? { kind: c.source.kind || "manual", ref: clean(c.source.ref, 500), method: clean(c.source.method, 40),
      text: clean(c.source.text, 500), confidence: num01(c.source.confidence, c.confidence), at: c.source.at || now } : null;
    let m = findSame(db, cand);
    const created = !m;
    if (!m) {
      m = { id: newId(db, title), title, type: cand.type, year: cand.year || null, language: cand.language || "", original_title: "", aka: [],
        genres: [], country: "", poster: "", overview: "", ext: {}, status: "want", verified: "unverified", confidence: 0, sources: [],
        added_at: now, updated_at: now };
      db.media.unshift(m);
    }
    // fill what is missing; never overwrite facts that were checked online with unchecked guesses
    const locked = m.verified === "verified";
    if (!locked) {
      if (!m.year && cand.year) m.year = cand.year;
      if (!m.language && cand.language) m.language = cand.language;
      if (m.type === "other" && cand.type !== "other") m.type = cand.type;
    }
    if (cand.original_title && !m.original_title) m.original_title = clean(cand.original_title, 200);
    if (!created && normTitle(title) !== normTitle(m.title)) m.aka = uniq([...(m.aka || []), title]);
    m.aka = uniq([...(m.aka || []), ...(cand.aka || [])]).filter((a) => normTitle(a) !== normTitle(m.title));
    m.genres = uniq([...(m.genres || []), ...(cand.genres || []).map(genreName)]);
    if (!m.country && cand.country) m.country = clean(cand.country, 60);
    if (!m.poster && cand.poster) m.poster = clean(cand.poster, 2000);
    if (!m.overview && cand.overview) m.overview = clean(cand.overview, 1500);
    for (const [k, v] of Object.entries(cand.ext || {})) if (v && !(m.ext || {})[k]) (m.ext = m.ext || {})[k] = String(v);
    if (src && !m.sources.some((s) => sourceKey(s) === sourceKey(src))) m.sources.push(src);
    m.confidence = Math.max(m.confidence || 0, num01(cand.confidence, src && src.confidence));
    m.updated_at = now;
    return { entry: m, created, merged: !created };
  }

  /** Add many candidates; returns { created, merged, skipped }. */
  function addMany(db, list) {
    const r = { created: 0, merged: 0, skipped: 0 };
    for (const c of list || []) { const x = add(db, c); if (!x) r.skipped++; else if (x.created) r.created++; else r.merged++; }
    return r;
  }

  /** The online check's answer for one entry. facts may correct title/type/year/language/genres/poster/ext.
      verified: "verified" | "conflict" | "rejected". If the corrected title now equals another entry, the two are merged. */
  function verify(db, id, facts = {}, verified = "verified", by = "") {
    const m = get(db, id);
    if (!m) return null;
    const oldTitle = m.title;
    if (facts.title && clean(facts.title, 200) !== m.title) {  // the official spelling, even when only the capitals differ ("DUNE")
      if (normTitle(facts.title) !== normTitle(m.title)) m.aka = uniq([...(m.aka || []), m.title]);
      m.title = clean(facts.title, 200);
    }
    if (facts.type) m.type = typeId(db, facts.type);
    if (facts.year) m.year = toYear(facts.year);
    if (facts.language) m.language = langCode(facts.language);
    for (const k of ["original_title", "country", "poster", "overview"]) if (facts[k]) m[k] = clean(facts[k], k === "overview" ? 1500 : k === "poster" ? 2000 : 200);
    if (facts.genres && facts.genres.length) m.genres = uniq(facts.genres.map(genreName));
    if (Number(facts.runtime) > 0) m.runtime = Math.round(Number(facts.runtime));
    if (Number(facts.episodes) > 0) m.episodes = Math.round(Number(facts.episodes));
    setDetails(m, facts);
    if (facts.aka) m.aka = uniq([...(m.aka || []), ...facts.aka]);
    m.aka = (m.aka || []).filter((a) => normTitle(a) !== normTitle(m.title));
    m.ext = { ...(m.ext || {}), ...Object.fromEntries(Object.entries(facts.ext || {}).filter(([, v]) => v).map(([k, v]) => [k, String(v)])) };
    m.verified = VERIFIED[verified] ? verified : "verified";
    m.verified_by = clean(by, 60);
    m.verified_at = Date.now();
    m.updated_at = Date.now();
    if (oldTitle !== m.title || facts.ext || facts.year) {  // it may now be a duplicate of another entry
      const rest = { ...db, media: db.media.filter((x) => x !== m) };
      const twin = findSame(rest, m);
      if (twin) return merge(db, twin.id, m.id);
    }
    return m;
  }

  /** Rating {score 0..10, by, votes} and seasons [{n, episodes, year, title}] from the online check (like a movie app). */
  function setDetails(m, d) {
    const r = d && d.rating;
    if (r && Number(r.score) > 0 && Number(r.score) <= 10) m.rating = { score: Math.round(Number(r.score) * 10) / 10, by: clean(r.by || "", 30), votes: Math.max(0, Math.round(Number(r.votes) || 0)) };
    if (d && Array.isArray(d.seasons) && d.seasons.length) {
      m.seasons = d.seasons.slice(0, 40).map((x) => ({ n: Math.round(Number(x.n) || 0), episodes: Math.max(0, Math.round(Number(x.episodes) || 0)),
        year: toYear(x.year) || null, title: clean(x.title || "", 120) })).filter((x) => x.n > 0);
    }
    if (d && /^tt\d+$/.test(d.imdb || "")) m.ext = { ...(m.ext || {}), imdb: d.imdb };
  }

  /** Fold entry `fromId` into `intoId` (sources, names, genres). Returns the kept entry. */
  function merge(db, intoId, fromId) {
    const a = get(db, intoId);
    const b = get(db, fromId);
    if (!a || !b || a === b) return a || b;
    const keep = b.verified === "verified" && a.verified !== "verified" ? b : a;
    const drop = keep === a ? b : a;
    for (const s of drop.sources || []) if (!keep.sources.some((x) => sourceKey(x) === sourceKey(s))) keep.sources.push(s);
    keep.aka = uniq([...(keep.aka || []), drop.title, ...(drop.aka || [])]).filter((t) => normTitle(t) !== normTitle(keep.title));
    keep.genres = uniq([...(keep.genres || []), ...(drop.genres || [])]);
    for (const k of ["year", "language", "original_title", "country", "poster", "overview", "runtime", "episodes", "rating", "seasons", "details_at"]) if (!keep[k] && drop[k]) keep[k] = drop[k];
    keep.ext = { ...(drop.ext || {}), ...(keep.ext || {}) };
    keep.confidence = Math.max(keep.confidence || 0, drop.confidence || 0);
    if (drop.status && drop.status !== "want" && keep.status === "want") keep.status = drop.status;
    keep.updated_at = Date.now();
    db.media = db.media.filter((x) => x !== drop);
    return keep;
  }

  function update(db, id, patch) {
    const m = get(db, id);
    if (!m) return null;
    if (patch.title != null && clean(patch.title, 200)) m.title = clean(patch.title, 200);
    if (patch.type != null) m.type = typeId(db, patch.type);
    if (patch.year !== undefined) m.year = toYear(patch.year) || null;
    if (patch.language != null) m.language = langCode(patch.language);
    if (patch.genres) m.genres = uniq(patch.genres.map(genreName));
    if (patch.status && STATUS[patch.status]) m.status = patch.status;
    if (patch.note != null) m.note = clean(patch.note, 2000);
    m.updated_at = Date.now();
    return m;
  }
  function remove(db, id) { db.media = (db.media || []).filter((m) => m.id !== id); }
  function get(db, id) { return (db.media || []).find((m) => m.id === id) || null; }

  /** Entries the online check should look at: never checked (or changed since), newest first. */
  function toVerify(db, since = 0) {
    return (db.media || []).filter((m) => (m.verified === "unverified" || !m.verified) && (m.updated_at || 0) >= since)
      .sort((a, b) => (b.updated_at || 0) - (a.updated_at || 0));
  }
  /** Entries that came from one screenshot or reel. */
  function fromSource(db, kind, ref) { return (db.media || []).filter((m) => (m.sources || []).some((s) => s.kind === kind && s.ref === ref)); }

  // ---------------------------------------------------------------- reading: filters, search, counts

  /** f: { q, group, type, language, genre, year ("2020" or "2010s"), verified, status, source }. Empty values mean "any". */
  function filter(db, f = {}) {
    let list = (db.media || []).filter((m) => m.verified !== "rejected" || f.verified === "rejected");
    if (f.group) list = list.filter((m) => groupOf(db, m.type) === f.group);
    if (f.type) list = list.filter((m) => m.type === f.type);
    if (f.language) list = list.filter((m) => (m.language || "") === (f.language === "unknown" ? "" : f.language));
    if (f.genre) list = list.filter((m) => (m.genres || []).some((g) => g.toLowerCase() === f.genre.toLowerCase()));
    if (f.year) {
      const y = String(f.year);
      list = /s$/.test(y) ? list.filter((m) => m.year && Math.floor(m.year / 10) * 10 === Number(y.slice(0, -1)))
        : y === "unknown" ? list.filter((m) => !m.year) : list.filter((m) => String(m.year) === y);
    }
    if (f.verified) list = list.filter((m) => (m.verified || "unverified") === f.verified);
    if (f.status) list = list.filter((m) => (m.status || "want") === f.status);
    if (f.source) list = list.filter((m) => (m.sources || []).some((s) => s.kind === f.source));
    const q = normTitle(f.q || "");
    if (q) {
      const words = q.split(" ");
      const scored = [];
      for (const m of list) {
        const names = [m.title, m.original_title, ...(m.aka || [])].map(normTitle).join(" | ");
        const hay = `${names} ${(m.genres || []).join(" ").toLowerCase()} ${langName(m.language).toLowerCase()} ${m.year || ""} ${typeInfo(db, m.type).label.toLowerCase()}`;
        let s = 0;
        for (const w of words) { if (names.split(/[ |]+/).includes(w)) s += 3; else if (hay.includes(w)) s += 1; else if (w.length > 3 && fuzzyIn(w, hay)) s += 0.5; else { s = -1; break; } }
        if (s > 0) { if (names.split(" | ").includes(q)) s += 10; else if (names.includes(q)) s += 4; scored.push([s, m]); }
      }
      return scored.sort((a, b) => b[0] - a[0]).map((x) => x[1]);
    }
    return list.slice().sort((a, b) => (b.added_at || 0) - (a.added_at || 0));
  }

  /** Counts for the filter menus, from a list (usually filter(db, {...}) without the menu's own filter). */
  function facets(db, list) {
    const count = (fn) => { const c = {}; for (const m of list) for (const k of [].concat(fn(m))) if (k !== undefined) c[k] = (c[k] || 0) + 1; return c; };
    return {
      group: count((m) => groupOf(db, m.type)),
      type: count((m) => m.type),
      language: count((m) => m.language || "unknown"),
      genre: count((m) => m.genres || []),
      decade: count((m) => (m.year ? Math.floor(m.year / 10) * 10 + "s" : "unknown")),
      verified: count((m) => m.verified || "unverified"),
      status: count((m) => m.status || "want"),
      source: count((m) => [...new Set((m.sources || []).map((s) => s.kind))]),
    };
  }

  // ---------------------------------------------------------------- export

  function exportCsv(db) {
    const cols = ["title", "type", "year", "language", "genres", "status", "verified", "sources", "aka", "imdb", "tmdb", "anilist"];
    const q = (v) => /[",\n]/.test(v) ? `"${v.replace(/"/g, '""')}"` : v;
    const rows = (db.media || []).map((m) => [m.title, typeInfo(db, m.type).label, m.year || "", langName(m.language), (m.genres || []).join("; "),
      STATUS[m.status] || "", VERIFIED[m.verified] || "", (m.sources || []).length, (m.aka || []).join("; "),
      (m.ext || {}).imdb || "", (m.ext || {}).tmdb || "", (m.ext || {}).anilist || ""].map((v) => q(String(v))).join(","));
    return [cols.join(","), ...rows].join("\n") + "\n";
  }

  // ---------------------------------------------------------------- small helpers

  const GENRE_FIX = { "sci fi": "Science fiction", "scifi": "Science fiction", "sci-fi": "Science fiction", "science fiction": "Science fiction",
    "rom com": "Romantic comedy", "romcom": "Romantic comedy", "slice of life": "Slice of life", "isekai": "Isekai" };
  function genreName(g) {
    const s = clean(g, 40).replace(/^#/, "");
    const k = s.toLowerCase().replace(/[-_]+/g, " ");
    return GENRE_FIX[k] || GENRE_FIX[s.toLowerCase()] || s.replace(/^./, (c) => c.toUpperCase());
  }
  function toYear(v) { const m = String(v || "").match(/(18|19|20)\d\d/); return m ? Number(m[0]) : null; }
  function num01(...vs) { for (const v of vs) { const n = Number(v); if (v != null && v !== "" && isFinite(n)) return Math.max(0, Math.min(1, n)); } return 0; }
  function newId(db, title) {
    const base = "m-" + (normTitle(title).replace(/ /g, "-").slice(0, 40) || "title");
    let id = base;
    for (let i = 2; (db.media || []).some((m) => m.id === id); i++) id = `${base}-${i}`;
    return id;
  }
  function fuzzyIn(w, hay) {  // one typo allowed
    for (const h of hay.split(/[^\p{L}\p{N}]+/u)) if (Math.abs(h.length - w.length) <= 1 && edits(w, h) <= 1) return true;
    return false;
  }
  function edits(a, b) {
    const d = Array.from({ length: a.length + 1 }, (_, i) => [i]);
    for (let j = 1; j <= b.length; j++) d[0][j] = j;
    for (let i = 1; i <= a.length; i++) for (let j = 1; j <= b.length; j++) d[i][j] = Math.min(d[i - 1][j] + 1, d[i][j - 1] + 1, d[i - 1][j - 1] + (a[i - 1] === b[j - 1] ? 0 : 1));
    return d[a.length][b.length];
  }

  return { BASE_TYPES, GROUPS, LANGS, STATUS, VERIFIED, types, typeInfo, typeId, addType, langCode, langName, normTitle, genreName,
    setDetails, findSame, add, addMany, verify, merge, update, remove, get, toVerify, fromSource, filter, facets, exportCsv };
})();

if (typeof module !== "undefined") module.exports = Catalog;
