/* Reel Shelf: one search box for everything (reels, quotes, movies, series, anime, manga).
   Plain words are ranked like a search engine (BM25). Questions in everyday words are understood without AI:
   "horror movie under 1.5 hours", "korean drama i haven't watched", "anime from the 2010s", "funny reels about money".
   Search.parse turns the words into filters (kind, genre, length, language, status, years) and the rest is ranked.
   Search.run applies them to the library. Search.fromAi reads the optional on-phone AI's JSON when the words were unclear.
   No network. Pure functions over db (tested in Chromium). */
"use strict";

const Search = (() => {
  const fold = (s) => String(s || "").toLowerCase().normalize("NFKD").replace(/[̀-ͯ]/g, "").replace(/[’']/g, "").replace(/\s+/g, " ").trim();

  // ---------------------------------------------------------------- what words mean

  // kinds of things: each word gives the catalog types it can mean; two words keep what both mean ("anime movie")
  const MOVIE = ["movie", "anime_movie", "short", "standup", "documentary", "animation"];
  const SHOW = ["series", "kdrama", "drama", "anime", "reality", "documentary", "animation"];
  const READ = ["manga", "manhwa", "manhua", "webtoon", "comic", "light_novel", "book"];
  const KIND_WORDS = [
    [/\b(k ?dramas?|korean (dramas?|series|shows?))\b/, ["kdrama"]],
    [/\b(c ?dramas?|j ?dramas?|chinese dramas?|japanese dramas?|thai dramas?|turkish (dramas?|series)|asian dramas?)\b/, ["drama"]],
    [/\b(anime ?(movies?|films?))\b/, ["anime_movie"]],
    [/\b(documentar(y|ies)|docuseries|docs?)\b/, ["documentary"]],
    [/\b(stand ?up|comedy specials?)\b/, ["standup"]],
    [/\b(short films?)\b/, ["short"]],
    [/\b(cartoons?|animated|donghua)\b/, ["animation", "anime", "anime_movie"]],
    [/\b(movies?|films?|flicks?|cinema)\b/, MOVIE],
    [/\b(series|tv ?shows?|shows?|tv|web ?series|sitcoms?|seasons?|episodes?)\b/, SHOW],
    [/\b(animes?)\b/, ["anime", "anime_movie"]],
    [/\b(manhwas?)\b/, ["manhwa"]],
    [/\b(manhuas?)\b/, ["manhua"]],
    [/\b(webtoons?|webcomics?)\b/, ["webtoon", "manhwa"]],
    [/\b(mangas?)\b/, ["manga", "manhwa", "manhua"]],
    [/\b(light novels?|web ?novels?)\b/, ["light_novel"]],
    [/\b(comics?|graphic novels?)\b/, ["comic", "manga", "manhwa", "manhua", "webtoon"]],
    [/\b(books?|novels?)\b/, ["book", "light_novel"]],
    [/\b(games?)\b/, ["game"]],
  ];
  const REEL_WORDS = /\b(reels?|videos?|clips?|shorts?(?! films?)|memes?|posts?)\b/;
  const QUOTE_WORDS = /\b(quotes?|quotations?|sayings?|lines?)\b/;
  const PRODUCT_WORDS = /\b(products?|things? to buy|shopping|buy list)\b/;

  // genres: the words people say, and what the databases call them (TMDB, AniList, MangaDex, Wikidata)
  const GENRES = [
    ["Horror", /\b(horror|scary|spooky|creepy|frightening|terrifying)\b/, ["horror"]],
    ["Comedy", /\b(comedy|comedies|comedic|funny|hilarious|laugh|romcoms?)\b/, ["comedy"]],
    ["Romance", /\b(romance|romantic|romcoms?|love stor(y|ies))\b/, ["romance", "romantic"]],
    ["Thriller", /\b(thrillers?|suspense|suspenseful|edge of (my|the) seat)\b/, ["thriller", "suspense"]],
    ["Action", /\b(action)\b/, ["action"]],
    ["Drama", /\b(drama|dramatic|emotional)\b(?! ?series)/, ["drama"]],
    ["Science fiction", /\b(sci[ -]?fi|science fiction|space|futuristic)\b/, ["science fiction", "sci-fi"]],
    ["Fantasy", /\b(fantasy|magic|magical)\b/, ["fantasy"]],
    ["Mystery", /\b(myster(y|ies)|whodunn?it|detective)\b/, ["mystery"]],
    ["Crime", /\b(crime|gangsters?|heist|mafia)\b/, ["crime"]],
    ["Adventure", /\b(adventures?)\b/, ["adventure"]],
    ["Family", /\b(family|kids|children)\b/, ["family", "kids"]],
    ["War", /\b(war)\b/, ["war"]],
    ["History", /\b(histor(y|ical)|period)\b/, ["history", "historical"]],
    ["Music", /\b(music|musical|musicals)\b/, ["music"]],
    ["Western", /\b(westerns?|cowboys?)\b/, ["western"]],
    ["Slice of life", /\b(slice of life|wholesome|cozy|cosy|feel ?good)\b/, ["slice of life"]],
    ["Sports", /\b(sports?)\b/, ["sports", "sport"]],
    ["Psychological", /\b(psychological|mind ?bending|mind ?fuck|twisty)\b/, ["psychological"]],
    ["Supernatural", /\b(supernatural|ghosts?|demons?|paranormal)\b/, ["supernatural"]],
    ["Isekai", /\b(isekai)\b/, ["isekai"]],
    ["Mecha", /\b(mecha|robots?)\b/, ["mecha"]],
    ["Animation", /\b(animation)\b/, ["animation"]],
    ["Zombie", /\b(zombies?)\b/, ["zombie"]],
  ];

  const NUM = { a: 1, an: 1, one: 1, two: 2, three: 3, four: 4, five: 5, six: 6, half: 0.5, ninety: 90, forty: 40, thirty: 30, twenty: 20, sixty: 60, hundred: 100 };
  const UNIT = "(h|hr|hrs|hour|hours|m|min|mins|minute|minutes)";
  const STOP = new Set(("i im ive id me my we us you your a an the to of for in on at by with and or is are was be it its this that these those there " +
    "what whats which who where when how any some something anything one ones thing things stuff kind type sort genre genres please can could would should " +
    "want wanna need like looking look find show give get recommend suggest list see watch read play good great best nice cool really very " +
    "just also only about from into than then so do does did dont have has had more most less least much many lot lots time tonight today now " +
    "long length duration runtime hours hour minutes minute mins min hrs hr").split(" "));

  function minutes(n, unit) { return /^h/.test(unit) ? Math.round(n * 60) : Math.round(n); }
  function numOf(w) { if (w == null) return NaN; const n = Number(w); return isFinite(n) ? n : NUM[w] != null ? NUM[w] : NaN; }

  /** "1.5 hours", "90 min", "an hour and a half", "1h30", "1:45": minutes, with the text it came from. */
  function durations(q) {
    const out = [];
    const add = (m, mins) => { if (mins > 0 && mins < 1000) out.push({ at: m.index, end: m.index + m[0].length, mins }); };
    let m;
    const rxs = [
      [/\b(\d{1,2})\s*h(?:r|rs|ours?)?\s*(?:and\s*)?(\d{1,2})\s*m(?:in|ins|inutes?)?\b/g, (x) => Number(x[1]) * 60 + Number(x[2])],
      [/\b(\d{1,2})h(\d{2})\b/g, (x) => Number(x[1]) * 60 + Number(x[2])],
      [/\b(\d{1,2}):([0-5]\d)\s*(?:h|hrs?|hours?)?\b/g, (x) => Number(x[1]) * 60 + Number(x[2])],
      [/\b(an?|one|two|three)\s+(?:and\s+a\s+half\s+hours?|hours?\s+and\s+a\s+half)\b/g, (x) => (numOf(x[1]) + 0.5) * 60],
      [/\b(an?|one|two|three)\s+and\s+a\s+quarter\s+hours?\b/g, (x) => (numOf(x[1]) + 0.25) * 60],
      [/\bhalf\s+an?\s+hour\b/g, () => 30],
      [new RegExp(`\\b(\\d+(?:\\.\\d+)?|an?|one|two|three|four|five|six|ninety|sixty|forty|thirty|twenty|hundred)\\s*${UNIT}\\b`, "g"), (x) => minutes(numOf(x[1]), x[2])],
    ];
    const taken = [];
    for (const [rx, fn] of rxs) {
      while ((m = rx.exec(q))) {
        const a = m.index, b = a + m[0].length;
        if (taken.some(([x, y]) => a < y && b > x)) continue;
        taken.push([a, b]);
        add(m, fn(m));
      }
    }
    return out.sort((x, y) => x.at - y.at);
  }

  // ---------------------------------------------------------------- the question to filters

  /** Everyday words to filters. Returns {types, kinds, genres, maxMin, minMin, language, status, yearFrom, yearTo, text, understood[]}. */
  function parse(query, now = new Date()) {
    const raw = String(query || "");
    const OPS = /"[^"]+"|#[\p{L}\p{N}_-]+|(?:^|\s)-[\p{L}\p{N}]\S*/gu;  // "exact words", #tag, -leave out: passed through as they are
    const ops = (raw.match(OPS) || []).map((x) => x.trim());
    let q = " " + fold(raw.replace(OPS, " ")).replace(/[^\p{L}\p{N}:.\s-]/gu, " ").replace(/\s+/g, " ") + " ";
    const p = { types: null, kinds: null, genres: [], maxMin: 0, minMin: 0, language: "", status: "", yearFrom: 0, yearTo: 0, text: "", understood: [] };
    const cut = (rx) => { q = q.replace(rx, " "); };
    const say = (kind, label, key) => p.understood.push({ kind, label, key: key || kind });

    // how long
    const ds = durations(q);
    const before = (d) => q.slice(Math.max(0, d.at - 28), d.at);
    const after = (d) => q.slice(d.end, d.end + 16);
    let between = q.match(new RegExp(`\\bbetween\\s+(\\d+(?:\\.\\d+)?)\\s*${UNIT}?\\s+(?:and|to|-)\\s+(\\d+(?:\\.\\d+)?)\\s*${UNIT}\\b`));
    if (between) {
      const u2 = between[4];
      p.minMin = minutes(Number(between[1]), between[2] || u2);
      p.maxMin = minutes(Number(between[3]), u2);
      cut(between[0]);
    } else {
      for (const d of ds) {
        const b = before(d), a = after(d);
        if (/(under|less than|shorter than|below|at most|max(imum)?|within|no (more|longer) than|up to|not more than|<|lesser than|not over)\s*(about|around|like)?\s*$/.test(b) || /^\s*(or (less|shorter|under)|max(imum)?|tops|at most)\b/.test(a)) p.maxMin = d.mins;
        else if (/(over|more than|longer than|above|at least|min(imum)?|>|not under|not less than)\s*(about|around|like)?\s*$/.test(b) || /^\s*(or (more|longer)|plus|\+|minimum)\b/.test(a)) p.minMin = d.mins;
        else if (/(about|around|roughly|approximately|like|~)\s*$/.test(b)) { p.minMin = Math.round(d.mins * 0.85); p.maxMin = Math.round(d.mins * 1.15); }
        else continue;
      }
      for (const d of ds) q = q.slice(0, d.at) + " ".repeat(d.end - d.at) + q.slice(d.end);
      cut(/\b(under|less than|shorter than|below|at most|maximum|max|within|no more than|no longer than|up to|not more than|lesser than|over|more than|longer than|above|at least|minimum|about|around|roughly|approximately|or less|or shorter|or more|or longer|tops)\b(?=\s*(\s|$))/g);
    }
    if (!p.maxMin && /\b(quick|short)\s+(movie|film|watch|one)s?\b/.test(q)) { p.maxMin = 100; cut(/\b(quick|short)\b/); }
    if (!p.minMin && /\b(long|epic)\s+(movie|film)s?\b/.test(q)) { p.minMin = 150; cut(/\b(long|epic)\b/); }
    if (p.maxMin && p.minMin) say("length", `${fmtMin(p.minMin)}–${fmtMin(p.maxMin)}`);
    else if (p.maxMin) say("length", `≤ ${fmtMin(p.maxMin)}`);
    else if (p.minMin) say("length", `≥ ${fmtMin(p.minMin)}`);

    // watched or not ("i want to watch" alone is not a filter)
    if (/\b(not (yet )?(watched|seen|finished|read)|unwatched|unseen|havent (watched|seen|read|finished)|didnt (watch|see|finish)|never (watched|seen)|new to me|on my (watch ?)?list|to ?watch list|watchlist)\b/.test(q)) {
      p.status = "want"; cut(/\b(not (yet )?(watched|seen|finished|read)|unwatched|unseen|havent (watched|seen|read|finished)|didnt (watch|see|finish)|never (watched|seen)|new to me|on my (watch ?)?list|to ?watch list|watchlist)\b/g);
    } else if (/\b(currently watching|still watching|watching now|in progress|halfway|started)\b/.test(q)) {
      p.status = "watching"; cut(/\b(currently watching|still watching|watching now|in progress|halfway|started)\b/g);
    } else if (/\b(already (watched|seen|read)|i (watched|saw|finished)|ive (watched|seen|finished|read)|finished|completed|watched|seen)\b/.test(q)) {
      p.status = "done"; cut(/\b(already (watched|seen|read)|i (watched|saw|finished)|ive (watched|seen|finished|read)|finished|completed|watched|seen)\b/g);
    } else if (/\bdropped\b/.test(q)) { p.status = "dropped"; cut(/\bdropped\b/g); }
    if (p.status) say("status", { want: "Not watched", watching: "Watching", done: "Watched", dropped: "Dropped" }[p.status]);

    // kind of thing
    let types = null;
    const kindLabels = [];
    for (const [rx, ts] of KIND_WORDS) {
      const m = q.match(rx);
      if (!m) continue;
      types = types ? types.filter((t) => ts.includes(t)) : ts.slice();
      if (!types.length) types = ts.slice();  // "movie series": the later word wins rather than nothing
      kindLabels.push(m[0].trim());
      cut(new RegExp(rx.source, "g"));
    }
    if (types) { p.types = types; say("type", kindLabels.join(" ")); }
    const wantsReels = REEL_WORDS.test(q), wantsQuotes = QUOTE_WORDS.test(q), wantsProducts = PRODUCT_WORDS.test(q);
    if (wantsReels || wantsQuotes || wantsProducts) {
      p.kinds = [...(types ? ["media"] : []), ...(wantsReels ? ["reels"] : []), ...(wantsQuotes ? ["quotes"] : []), ...(wantsProducts ? ["products"] : [])];
      if (wantsProducts) { say("kind", "Products", "products"); cut(new RegExp(PRODUCT_WORDS.source, "g")); }
      if (wantsReels) { say("kind", "Reels", "reels"); cut(new RegExp(REEL_WORDS.source, "g")); }
      if (wantsQuotes) { say("kind", "Quotes", "quotes"); cut(new RegExp(QUOTE_WORDS.source, "g")); }
    }

    // genres (kept as words too, so a reel or quote about "horror" is still found)
    const genreWords = [];
    for (const [label, rx, names] of GENRES) {
      const m = q.match(rx);
      if (!m) continue;
      p.genres.push({ label, names });
      genreWords.push(m[0].trim());
      say("genre", label, "genre:" + label);
    }
    for (const [label, rx] of GENRES) if (p.genres.some((g) => g.label === label)) cut(new RegExp(rx.source, "g"));  // after all, so "romcom" is both
    p.genreWords = genreWords;

    // language ("korean", "in hindi", "tamil movie")
    const langs = (typeof Catalog !== "undefined" && Catalog.LANGS) || {};
    for (const [code, name] of Object.entries(langs)) {
      if (code === "xx") continue;
      const rx = new RegExp(`\\b(in\\s+)?${name.toLowerCase()}\\b`, "g");
      if (!rx.test(q)) continue;
      p.language = code;
      say("language", name);
      cut(rx);
      break;
    }
    if (!p.language && /\b(bollywood)\b/.test(q)) { p.language = "hi"; say("language", "Hindi"); cut(/\bbollywood\b/g); }
    if (!p.language && /\b(kollywood)\b/.test(q)) { p.language = "ta"; say("language", "Tamil"); cut(/\bkollywood\b/g); }
    if (!p.language && /\b(tollywood)\b/.test(q)) { p.language = "te"; say("language", "Telugu"); cut(/\btollywood\b/g); }
    if (!p.language && /\b(mollywood)\b/.test(q)) { p.language = "ml"; say("language", "Malayalam"); cut(/\bmollywood\b/g); }

    // years
    const year = now.getFullYear();
    let m;
    if ((m = q.match(/\bbetween\s+((?:19|20)\d\d)\s+(?:and|to|-)\s+((?:19|20)\d\d)\b/))) { p.yearFrom = Number(m[1]); p.yearTo = Number(m[2]); cut(m[0]); }
    else if ((m = q.match(/\b((?:19|20)\d\d)\s*(?:-|to)\s*((?:19|20)\d\d)\b/))) { p.yearFrom = Number(m[1]); p.yearTo = Number(m[2]); cut(m[0]); }
    else if ((m = q.match(/\b(after|since|from|newer than|post)\s+((?:19|20)\d\d)\b/))) { p.yearFrom = Number(m[2]) + (m[1] === "after" || m[1] === "newer than" || m[1] === "post" ? 1 : 0); cut(m[0]); }
    else if ((m = q.match(/\b(before|until|till|older than|pre)\s+((?:19|20)\d\d)\b/))) { p.yearTo = Number(m[2]) - (m[1] === "before" || m[1] === "older than" || m[1] === "pre" ? 1 : 0); cut(m[0]); }
    else if ((m = q.match(/\b(?:the\s+)?(?:(19|20)?(\d)0s|(nineteen|twenty)?\s*(eighties|nineties|seventies|sixties|fifties))\b/))) {
      let dec;
      if (m[2] !== undefined) dec = m[1] ? Number(m[1] + m[2] + "0") : Number(m[2]) >= 3 ? 1900 + Number(m[2]) * 10 : 2000 + Number(m[2]) * 10;
      else dec = 1900 + { fifties: 50, sixties: 60, seventies: 70, eighties: 80, nineties: 90 }[m[4]];
      p.yearFrom = dec; p.yearTo = dec + 9; cut(m[0]);
    } else if ((m = q.match(/\b(?:from|in|of)?\s*((?:19|20)\d\d)\b/))) { p.yearFrom = p.yearTo = Number(m[1]); cut(m[0]); }
    else if (/\b(recent|latest|newest|new releases?|this year)\b/.test(q)) { p.yearFrom = /this year/.test(q) ? year : year - 3; cut(/\b(recent|latest|newest|new releases?|this year)\b/g); }
    else if (/\b(last year)\b/.test(q)) { p.yearFrom = p.yearTo = year - 1; cut(/\blast year\b/g); }
    else if (/\b(old|classic|classics|retro|vintage)\b/.test(q)) { p.yearTo = 1995; cut(/\b(old|classic|classics|retro|vintage)\b/g); }
    if (p.yearFrom && p.yearTo && p.yearFrom === p.yearTo) say("year", String(p.yearFrom));
    else if (p.yearFrom && p.yearTo) say("year", `${p.yearFrom}–${p.yearTo}`);
    else if (p.yearFrom) say("year", `${p.yearFrom}+`);
    else if (p.yearTo) say("year", `≤ ${p.yearTo}`);

    // what is left is ranked as words; quoted phrases and #tags pass through
    const quoted = ops.join(" ");
    p.exclude = ops.filter((x) => x.startsWith("-")).map((x) => fold(x.slice(1).replace(/"/g, "")));
    const rest = q.split(" ").filter((w) => w && !STOP.has(w) && !/^[.:-]+$/.test(w) && !/^\d+(\.\d+)?$/.test(w));
    p.text = [quoted, ...rest].join(" ").trim();
    p.structured = !!(p.types || p.kinds || p.genres.length || p.maxMin || p.minMin || p.language || p.status || p.yearFrom || p.yearTo);
    return p;
  }

  function fmtMin(n) { const h = Math.floor(n / 60), m = n % 60; return h ? `${h}h${m ? " " + m + "m" : ""}` : `${m}m`; }

  // ---------------------------------------------------------------- ranking titles by words (BM25)

  function mediaText(m) {
    const t = typeof Catalog !== "undefined" ? Catalog.typeInfo({}, m.type).label : m.type;
    return [[m.title, 3], [m.original_title, 2], [(m.aka || []).join(" "), 2], [(m.genres || []).join(" "), 2], [t, 1], [m.overview, 1], [m.note, 1.5]];
  }
  const tokens = (s) => fold(s).split(/[^\p{L}\p{N}]+/u).filter((w) => w.length > 1 || /\d/.test(w));
  function rankMedia(list, text) {
    const words = [...new Set(tokens(text))];
    if (!words.length) return list.map((m) => ({ m, score: 0 }));
    const docs = list.map((m) => {
      const tf = new Map();
      let len = 0;
      for (const [s, w] of mediaText(m)) for (const t of tokens(s)) { tf.set(t, (tf.get(t) || 0) + w); len += w; }
      return { m, tf, len };
    });
    const avg = docs.reduce((s, d) => s + d.len, 0) / Math.max(1, docs.length);
    const df = (w) => docs.filter((d) => hasWord(d.tf, w)).length;
    const idf = Object.fromEntries(words.map((w) => { const n = df(w); return [w, Math.log(1 + (docs.length - n + 0.5) / (n + 0.5))]; }));
    const out = [];
    for (const d of docs) {
      let s = 0, hit = 0;
      for (const w of words) {
        const f = tfOf(d.tf, w);
        if (!f) continue;
        hit++;
        s += idf[w] * (f * 2.2) / (f + 1.2 * (0.25 + 0.75 * d.len / avg));
      }
      if (!hit) continue;
      if (hit < words.length) s *= hit / words.length;  // every word counts, but one miss does not hide a title
      const title = fold([d.m.title, ...(d.m.aka || [])].join(" | "));
      if (title.includes(fold(text))) s += 5;
      out.push({ m: d.m, score: s });
    }
    return out.sort((a, b) => b.score - a.score);
  }
  function hasWord(tf, w) { return tfOf(tf, w) > 0; }
  function tfOf(tf, w) {  // the word, or a longer form of it ("zombie" finds "zombies"), or one typo in long words
    if (tf.has(w)) return tf.get(w);
    let best = 0;
    for (const [t, n] of tf) {
      if (t.length > w.length && t.startsWith(w) && t.length - w.length <= 3) best = Math.max(best, n * 0.8);
      else if (w.length > 4 && Math.abs(t.length - w.length) <= 1 && typeof Lib !== "undefined" && Lib.distance(t, w, 1) <= 1) best = Math.max(best, n * 0.6);
    }
    return best;
  }

  // ---------------------------------------------------------------- running a search

  const ORDER = { watching: 0, want: 1, dropped: 2, done: 3 };
  const genreOk = (m, g) => (m.genres || []).some((x) => g.names.some((n) => fold(x).includes(n)));

  /** The search. f: the screen's own filters {kind: all|reels|quotes|movies|series|anime|manga, status, language, genre, year, maxMin}.
      Returns {p, media, reels, quotes, noLength} (noLength: titles that fit everything but have no known length). */
  function run(db, query, f = {}, now = new Date()) {
    const p = parse(query, now);
    const kind = f.kind || "all";
    const want = (k) => {
      if (kind !== "all") return k === "media" ? ["movies", "series", "anime", "manga"].includes(kind) : k === kind;
      if (p.kinds) return p.kinds.includes(k);
      const mediaOnly = p.types || p.maxMin || p.minMin || p.status || f.status || f.maxMin || f.language || f.genre || f.year || f.verified || f.source;
      return k === "media" || !mediaOnly;
    };
    const out = { p, media: [], reels: [], quotes: [], products: [], noLength: [] };

    const onlyTags = query.trim() && !p.structured && p.text && p.text.split(/\s+/).every((w) => w.startsWith("#"));
    if (want("media") && !onlyTags) {
      let list = (db.media || []).filter((m) => m.verified !== "rejected");
      if (kind !== "all") list = list.filter((m) => kindOf(m) === kind);
      if (p.types) list = list.filter((m) => p.types.includes(m.type));
      for (const g of p.genres) list = list.filter((m) => genreOk(m, g));
      const lang = f.language || p.language;
      if (lang) list = list.filter((m) => (m.language || "") === (lang === "unknown" ? "" : lang));
      const st = f.status || p.status;
      if (st) list = list.filter((m) => (m.status || "want") === st);
      if (f.genre) list = list.filter((m) => (m.genres || []).some((g) => fold(g) === fold(f.genre)));
      const yf = p.yearFrom, yt = p.yearTo;
      if (yf || yt) list = list.filter((m) => m.year && (!yf || m.year >= yf) && (!yt || m.year <= yt));
      if (f.verified) list = list.filter((m) => (m.verified || "unverified") === f.verified);
      if (f.source) list = list.filter((m) => (m.sources || []).some((s) => s.kind === f.source));
      if (f.year === "unknown") list = list.filter((m) => !m.year);
      else if (f.year) list = list.filter((m) => m.year && String(Math.floor(m.year / 10) * 10) + "s" === f.year);
      const maxMin = f.maxMin || p.maxMin, minMin = p.minMin;
      if (maxMin || minMin) {
        const fits = (m) => m.runtime > 0 && (!maxMin || m.runtime <= maxMin) && (!minMin || m.runtime >= minMin);
        out.noLength = list.filter((m) => !(m.runtime > 0));
        list = list.filter(fits);
      }
      if (p.exclude.length) list = list.filter((m) => { const t = fold(mediaText(m).map((x) => x[0] || "").join(" ")); return !p.exclude.some((x) => t.includes(x)); });
      const phrases = (p.text.match(/"[^"]+"/g) || []).map((x) => fold(x.slice(1, -1)));
      if (phrases.length) list = list.filter((m) => { const t = fold(mediaText(m).map((x) => x[0] || "").join(" ")); return phrases.every((x) => t.includes(x)); });
      const mtext = p.text.replace(/"[^"]+"|#\S+|(?:^|\s)-\S+/g, (x) => (x.startsWith('"') ? x.slice(1, -1) : " ")).trim();
      let ranked = rankMedia(list, mtext);
      if (!mtext) ranked.sort((a, b) => (ORDER[a.m.status || "want"] - ORDER[b.m.status || "want"]) || ((b.m.added_at || 0) - (a.m.added_at || 0)));
      else ranked.sort((a, b) => b.score - a.score || (ORDER[a.m.status || "want"] - ORDER[b.m.status || "want"]));
      out.media = ranked.map((x) => x.m);
      if (mtext) out.noLength = rankMedia(out.noLength, mtext).map((x) => x.m);
    }
    const words = [p.text, ...p.genreWords].join(" ").trim();
    if (want("reels") && words && typeof Lib !== "undefined") out.reels = Lib.find(db.reels || [], words, 200);
    else if (want("reels") && !query.trim()) out.reels = (db.reels || []).map((r) => ({ reel: r, score: 0, lines: [] }));
    if (want("quotes") && typeof Quotes !== "undefined") {
      if (words) {
        out.quotes = Quotes.find(db, words);
        if (!out.quotes.length && words.split(" ").length > 1) {  // any of the words, when all of them find nothing
          const seen = new Set();
          for (const w of words.split(" ")) for (const x of Quotes.find(db, w)) if (!seen.has(x)) { seen.add(x); out.quotes.push(x); }
        }
      } else if (!query.trim()) out.quotes = (db.quotes || []).slice();
    }
    if (want("products") && typeof Products !== "undefined") {
      if (words) {
        out.products = Products.find(db, words);
        if (!out.products.length && words.split(" ").length > 1) {
          const seen = new Set();
          for (const w of words.split(" ")) for (const x of Products.find(db, w)) if (!seen.has(x)) { seen.add(x); out.products.push(x); }
        }
      } else if (!query.trim()) out.products = (db.products || []).slice();
    }
    return out;
  }

  /** Library chip a title belongs to. */
  function kindOf(m) {
    const t = m.type || "other";
    if (t === "anime" || t === "anime_movie") return "anime";
    if (READ.includes(t)) return "manga";
    if (t === "movie" || t === "short" || t === "standup") return "movies";
    if (SHOW.includes(t)) return "series";
    return "other";
  }

  // ---------------------------------------------------------------- the optional AI, only when the words were unclear

  const AI_PROMPT = (q) => `Turn this search into JSON with only these keys (leave out what is not said):
{"kind":"movie|series|anime|manga|reel|quote","genres":["horror"],"max_minutes":90,"min_minutes":0,"language":"ko","status":"want|watching|done","year_from":2010,"year_to":2019,"words":"other important words"}
Search: ${q}
JSON:`;

  /** The AI's JSON answer to a search string the parser understands ("horror movie under 90 minutes"). */
  function fromAi(text) {
    const m = String(text || "").match(/\{[\s\S]*\}/);
    if (!m) return "";
    let o;
    try { o = JSON.parse(m[0]); } catch (e) { return ""; }
    const bits = [];
    if (Array.isArray(o.genres)) bits.push(...o.genres.map(String).slice(0, 4));
    if (o.language) bits.push(Catalog.langName(Catalog.langCode(o.language)));
    if (o.kind) bits.push(String(o.kind));
    if (Number(o.max_minutes) > 0) bits.push(`under ${Math.round(o.max_minutes)} min`);
    if (Number(o.min_minutes) > 0) bits.push(`over ${Math.round(o.min_minutes)} min`);
    if (o.status === "want") bits.push("not watched"); else if (o.status === "watching") bits.push("currently watching"); else if (o.status === "done") bits.push("already watched");
    if (Number(o.year_from) && Number(o.year_to)) bits.push(`between ${o.year_from} and ${o.year_to}`);
    else if (Number(o.year_from)) bits.push(`since ${o.year_from}`);
    else if (Number(o.year_to)) bits.push(`until ${o.year_to}`);
    if (o.words) bits.push(String(o.words).slice(0, 120));
    return bits.join(" ").replace(/\s+/g, " ").trim();
  }

  return { parse, run, kindOf, rankMedia, fromAi, AI_PROMPT, durations, fmtMin, fold };
})();

if (typeof module !== "undefined") module.exports = Search;
