/* Reel Shelf (built in): finds movie, series, anime and manga names in text, with no AI.
   Input is what the phone's text reader (Google ML Kit, on the phone) saw in a screenshot, line by line with where
   each line sits, or a reel's caption. Output is a ranked list of title candidates, each with why it was picked,
   plus hints for the kind (movie, anime, manga...) and the language. Checking the names online is a later step.
   Pure functions only: no screen code, no network. */
"use strict";

const Titles = (() => {
  // ---------------------------------------------------------------- word lists

  // Kinds of things you watch or read. The key is the catalog's kind; the words point to it.
  const KIND_WORDS = {
    movie: ["movie", "movies", "film", "films", "cinema", "moviescenes", "movieclips", "moviescene", "filmmaking", "boxoffice",
      "hollywood", "bollywood", "kollywood", "tollywood", "mollywood", "sandalwood", "blockbuster", "trailer", "imdb", "letterboxd"],
    series: ["series", "webseries", "tvseries", "tvshow", "tvshows", "netflixseries", "season", "episode", "episodes", "sitcom", "miniseries", "showrunner"],
    kdrama: ["kdrama", "kdramas", "koreandrama", "kdramaedit", "kdramalover", "kdramas"],
    cdrama: ["cdrama", "cdramas", "chinesedrama", "cdramaedit"],
    jdrama: ["jdrama", "japanesedrama"],
    drama: ["drama", "dramas", "asiandrama", "thaidrama", "lakorn", "turkishdrama", "dizi"],
    anime: ["anime", "animes", "animeedit", "animeedits", "animescene", "animescenes", "otaku", "crunchyroll", "animelover", "weeb", "myanimelist", "isekai", "shonen", "shounen", "seinen", "shoujo", "shojo"],
    manga: ["manga", "mangas", "mangapanel", "mangapanels", "mangaedit", "mangarecommendation", "mangadex", "tachiyomi", "mihon", "mangaka"],
    manhwa: ["manhwa", "manhwas", "manhwaedit", "manhwarecommendation", "webtoon", "webtoons", "webcomic"],
    manhua: ["manhua", "manhuas", "donghua"],
    documentary: ["documentary", "documentaries", "docuseries", "docu"],
    cartoon: ["cartoon", "cartoons", "animation", "animated", "pixar", "disneyanimation", "ghibli", "studioghibli", "dreamworks"],
    book: ["book", "books", "novel", "novels", "booktok", "bookstagram", "lightnovel", "webnovel"],
  };
  // Words that point to a language. Industry names count: kollywood is Tamil cinema.
  const LANG_WORDS = {
    tamil: ["tamil", "kollywood", "tamilmovie", "tamilmovies", "tamilcinema", "thalapathy", "tamildubbed"],
    telugu: ["telugu", "tollywood", "telugumovie", "telugumovies"],
    malayalam: ["malayalam", "mollywood", "malayalammovie", "malayalammovies"],
    kannada: ["kannada", "sandalwood", "kannadamovie"],
    hindi: ["hindi", "bollywood", "hindimovie", "hindimovies", "hindidubbed"],
    english: ["english", "hollywood", "englishmovie", "englishmovies"],
    korean: ["korean", "kdrama", "kdramas", "koreandrama", "kmovie", "manhwa", "manhwas", "kfilm"],
    japanese: ["japanese", "jdrama", "japanesemovie", "anime", "manga"],
    chinese: ["chinese", "cdrama", "cdramas", "manhua", "donghua", "cmovie"],
    spanish: ["spanish", "spanishmovie", "spanishseries"],
    french: ["french", "frenchmovie", "frenchfilm"],
    turkish: ["turkish", "dizi", "turkishdrama"],
    thai: ["thai", "thaidrama", "lakorn"],
  };
  // Apps a screenshot can come from (from the file name, e.g. Screenshot_..._com.netflix.mediaclient.jpg).
  const APPS = [
    [/instagram/, "instagram", ""], [/youtube/, "youtube", ""], [/facebook|katana/, "facebook", ""], [/twitter|com\.x\./, "x", ""],
    [/reddit/, "reddit", ""], [/whatsapp/, "whatsapp", ""], [/telegram/, "telegram", ""], [/chrome|browser|firefox|opera|brave|edge/, "browser", ""],
    [/googlequicksearch|google\.android\.apps\.search/, "google", ""], [/netflix/, "netflix", ""], [/primevideo|amazon\.avod/, "prime", ""],
    [/hotstar|jiocinema|jiohotstar/, "hotstar", ""], [/imdb/, "imdb", ""], [/letterboxd/, "letterboxd", "movie"],
    [/crunchyroll/, "crunchyroll", "anime"], [/myanimelist|\.mal\b/, "myanimelist", ""], [/anilist/, "anilist", ""],
    [/tachiyomi|mihon|mangadex|kotatsu|manga/, "manga-reader", "manga"], [/webtoon|naver\.linewebtoon|tapas/, "webtoon", "manhwa"],
    [/mxplayer|vlc|mx\.player/, "video-player", ""], [/sunnxt|aha|zee5|sonyliv/, "streaming", ""],
  ];

  // Text that apps put on every screen (buttons, menus, counters). Never a title.
  const CHROME = new Set([
    "follow", "following", "followers", "message", "reply", "replies", "see translation", "see more", "more", "less", "liked by", "like", "likes", "comment",
    "comments", "share", "send", "save", "saved", "remix", "sponsored", "suggested for you", "original audio", "reels", "reel", "home", "search", "explore",
    "profile", "add a comment", "add a comment...", "view replies", "hide replies", "view all comments", "translate", "audio", "edited", "author", "pinned",
    "subscribe", "subscribed", "shorts", "dislike", "remix this", "join", "new", "live", "posts", "tagged", "notifications", "activity", "create",
    "play", "resume", "download", "downloads", "my list", "rate", "episodes", "more like this", "trailers & more", "trailers and more", "watch now", "start watching",
    "watchlist", "add to watchlist", "trailer", "trailers", "details", "cast", "crew", "reviews", "ratings", "overview", "synopsis", "storyline", "genres", "genre",
    "chapters", "chapter list", "read", "start reading", "continue reading", "library", "updates", "history", "browse", "bookmarks",
    "official trailer", "watch", "watched", "rent", "buy", "free", "premium", "subscribe now", "sign in", "log in", "sign up", "skip", "next", "previous",
    "people also search for", "people also ask", "about", "top stories", "images", "videos", "news", "all", "shopping", "maps", "books", "web", "sort by",
    "newest first", "top comments", "most relevant", "write a comment", "reply to", "translated", "show more", "show less", "read more", "view all",
    "today", "yesterday", "now", "ago", "you", "me", "and", "the", "for you", "following feed", "back", "close", "done", "cancel", "ok", "menu",
    "movie", "movies", "film", "films", "anime", "manga", "series", "drama", "kdrama", "manhwa", "webtoon", "show", "shows", "tv", "tv show", "tv shows",
    "movie name", "movie name?", "name", "name?", "title", "what movie is this", "which movie", "what anime is this", "sauce", "source",
  ]);
  // Hashtags that only say what kind of post it is, never which title.
  const GENERIC_TAGS = new Set([
    "fyp", "foryou", "foryoupage", "viral", "trending", "explore", "explorepage", "reels", "reel", "reelsinstagram", "instagram", "instareels", "instagood",
    "love", "edit", "edits", "edited", "aesthetic", "shorts", "short", "ytshorts", "youtubeshorts", "tiktok", "meme", "memes", "funny", "comedy", "sad",
    "romance", "romantic", "action", "thriller", "horror", "scifi", "sciencefiction", "fantasy", "mystery", "crime", "adventure", "drama", "comedy",
    "psychological", "psychologicalthriller", "mindblowing", "mustwatch", "watchlist", "recommendation", "recommendations", "suggestion", "suggestions",
    "review", "reviews", "explained", "explanation", "ending", "endingexplained", "plottwist", "scene", "scenes", "clip", "clips", "4k", "hd", "fullmovie",
    "movierecommendation", "movierecommendations", "movietime", "movielover", "movielovers", "moviebuff", "movienight", "movieaddict", "movieclip",
    "film", "films", "filmmaker", "cinematic", "cinematography", "cinephile", "cinema", "netflix", "primevideo", "amazonprime", "hotstar", "disneyplus",
    "hbo", "hbomax", "hulu", "appletv", "ott", "webseries", "series", "tvseries", "tvshow", "kdrama", "cdrama", "anime", "manga", "manhwa", "manhua",
    "webtoon", "otaku", "weeb", "animeedit", "animeedits", "mangapanel", "mangapanels", "fypシ", "fypage", "trend", "follow", "like", "likes", "share",
    "music", "song", "songs", "bgm", "status", "whatsappstatus", "quotes", "motivation", "life", "sigma", "attitude", "india", "usa", "bollywood",
    "hollywood", "kollywood", "tollywood", "mollywood", "tamil", "telugu", "hindi", "malayalam", "kannada", "english", "korean", "japanese", "chinese",
    "movies", "movie", "animes", "dramas", "kdramas", "cdramas", "series", "documentary", "cartoon", "animation", "netflixseries", "moviescene",
    "moviescenes", "movieclips", "filmedit", "movieedit", "movieedits", "seriesedit", "tvedit", "fanedit", "fanart", "art", "cosplay", "dubbed",
    "tamildubbed", "hindidubbed", "trailer", "teaser", "newmovie", "latest", "upcoming", "2024", "2025", "2026", "oldisgold", "classic", "classics",
    "bestmovies", "topmovies", "top10", "top5", "mustwatchmovies", "underrated", "underratedmovies", "hiddengems", "masterpiece",
  ]);
  for (const words of Object.values(KIND_WORDS)) for (const w of words) GENERIC_TAGS.add(w);
  for (const words of Object.values(LANG_WORDS)) for (const w of words) GENERIC_TAGS.add(w);

  // Small words that are lower case inside a title ("Lord of the Rings").
  const SMALL = new Set(["a", "an", "the", "of", "in", "on", "at", "to", "and", "or", "for", "with", "from", "by", "vs", "is", "de", "la", "le", "no", "wa", "ga"]);
  // Words that make a line a sentence rather than a name.
  const SENTENCE = /\b(i|i'm|im|you|your|you're|we|they|he|she|my|me|this|that|these|those|was|were|are|is|be|been|have|has|had|do|does|did|can|could|would|should|will|just|so|very|really|when|what|why|how|who|if|because|but|like|lol|bro|guys|watch(ed|ing)?|must|best|top|list|recommend\w*|anyone|someone|please|pls|plz)\b/gi;
  const LABEL = /^\s*(?:[^\p{L}\p{N}]{0,3})\s*(movie|movie name|film|film name|film title|anime|anime name|manga|manga name|manhwa|manhwa name|manhua|webtoon|series|series name|show|show name|tv show|drama|drama name|kdrama|k-drama|cdrama|documentary|title|name|source|sauce|cartoon|novel|book)\s*(?:is|=|:|-|–|\u2014|›|»|->|=>)\s*(.+)$/iu;
  const ASK = /\b(movie|film|anime|manga|manhwa|series|show|drama|song)\s*(name|title)\b|\bname\s*(of|pls|please|plz|\?)|\bwhat(?:'s| is)\s+(?:the\s+)?(movie|film|anime|manga|show|series|name)\b|\bwhich\s+(movie|film|anime|manga|show|series)\b|\bsauce\b|\bsource\s*\?/i;
  const YEAR = /(?:^|[^\d])((?:19[2-9]\d|20[0-3]\d))(?:[^\d]|$)/;
  const META_LINE = /(\b(19[2-9]\d|20[0-3]\d)\b.*(·|•|‧|\||-|,).*(\d+\s?h|\d+\s?min|\d+\s?m\b|season|seasons|episodes?|u\/a|\bua\b|\bpg|tv-|\b[0-9]{1,2}\+|\bA\b|\bU\b|hd|4k|movie|film|series|drama|anime|action|comedy|thriller|horror|romance|sci-?fi|fantasy|crime|mystery|adventure|animation|documentary))|(^\s*(19[2-9]\d|20[0-3]\d)\s*(·|•|‧|\|)\s*)|(\b\d+\s?h\s?\d+\s?m(in)?\b)|(\b\d+\s+seasons?\b)|(^\s*(tv-\w+|u\/a\s*\d+\+|pg-?13|r\b|[0-9]{1,2}\+)\s*(·|•|‧|\||$))/i;
  const CHAPTER = /\b(?:ch(?:apter)?|ep(?:isode)?|vol(?:ume)?|season|s\d{1,2}\s?e\d{1,3})\.?\s*\d+/i;
  const NOISE = /^(?:[\d\s:.,%+\-/|]+|[\d.,]+\s*[kKmM]?\s*(likes?|views?|comments?|replies|followers|following|shares|plays)?|\d+\s*(s|m|h|d|w|y|sec|min|hr|hrs|days?|weeks?|months?|years?)\s*(ago)?|@[\w.]+|#\S+|https?:\/\/\S+|www\.\S+|[\w.-]+\.(com|in|net|org|io|tv|me)\S*)$/i;
  const ORDINAL = /^\s*(?:#?\s*(\d{1,2})\s*[.)\-:–]|(\d{1,2})\s*[⃣️]+|[①②③④⑤⑥⑦⑧⑨⑩]|[•●▪◦\-–]\s)\s*(.+)$/u;
  const EMOJI_MARK = /^\s*(?:🎬|🎥|📽️?|🍿|📺|🎞️?|📖|📚|🎌|⛩️?)\s*(.+)$/u;

  // ---------------------------------------------------------------- small helpers

  const lower = (s) => String(s || "").toLowerCase();
  function strip(s) {  // keeps letters, digits, spaces and the punctuation titles use
    return String(s || "").replace(/[​-‏﻿]/g, "").replace(/\p{Extended_Pictographic}|️|⃣/gu, " ")
      .replace(/[“”«»„]/g, '"').replace(/[‘’`´]/g, "'").replace(/\s+/g, " ").trim();
  }
  /** One title, cleaned: no quotes around it, no "(2014)", no "Official Trailer", no trailing dots. Returns {title, year, lang, kind}. */
  function clean(raw) {
    let t = strip(raw);
    let year = null;
    let lang = "";
    let kind = "";
    const tags = [];
    t = t.replace(/#([\p{L}\p{N}_]+)/gu, (m, w) => { tags.push(lower(w)); return " "; });
    // "Watch this kdrama: Move to Heaven" -> "Move to Heaven" (a lead-in that names the kind, then a colon)
    t = t.replace(/^.{0,40}?\b(movies?|films?|animes?|mangas?|manhwas?|manhuas?|k-?dramas?|dramas?|series|shows?|webtoons?|documentar(y|ies))\s*[:\-–\u2014]\s+(?=\S)/i,
      (m, w) => { kind = kind || kindOf(w.replace(/s$|-/g, "")) || kindOf(w); return ""; });
    t = t.replace(/\s*[([]\s*((?:19|20)\d\d)\s*[)\]]\s*/g, (m, y) => { year = Number(y); return " "; });
    t = t.replace(/\s*[-–\u2014|:,]\s*((?:19|20)\d\d)\s*$/g, (m, y) => { year = Number(y); return ""; });
    const dub = t.match(/\b(tamil|telugu|hindi|malayalam|kannada|english|korean|japanese)\s*(dub(bed)?|version|audio)\b/i);
    if (dub) { lang = lower(dub[1]); t = t.replace(dub[0], " "); }
    t = t.replace(/\b(official\s+)?(hd\s+)?(trailer|teaser|full\s+movie|full\s+film|movie\s+clip|scene|explained|ending\s+explained|review|recap|edit|status|bgm|ost|4k|hd|1080p|720p)\b.*$/i, "");
    t = t.replace(/\b(season|s)\s*\d+\b.*$|\bs\d{1,2}\s?e\d{1,3}\b.*$|\b(episode|ep)\.?\s*\d+\b.*$/i, (m) => { kind = kind || "series"; return ""; });
    t = t.replace(/\b(chapter|ch)\.?\s*\d+.*$/i, (m) => { kind = kind || "manga"; return ""; });
    t = t.replace(/\b(movie|film|anime|manga|manhwa|series|kdrama|k-drama)\s*$/i, (m) => { kind = kind || lower(m.trim()).replace("k-drama", "kdrama").replace("film", "movie"); return ""; });
    t = t.replace(/^[\s"'*_~.,:;!?>\-–\u2014|]+|[\s"'*_~.,:;!?<\-–\u2014|]+$/g, "").replace(/\s+/g, " ").trim();
    for (const w of tags) { lang = lang || langOf(w); kind = kind || kindOf(w); }
    return { title: t, year, lang, kind };
  }
  function kindOf(word) {
    const w = lower(word).replace(/[^a-z]/g, "");
    for (const [k, words] of Object.entries(KIND_WORDS)) if (words.includes(w)) return k;
    return "";
  }
  function langOf(word) {
    const w = lower(word).replace(/[^a-z]/g, "");
    for (const [k, words] of Object.entries(LANG_WORDS)) if (words.includes(w)) return k;
    return "";
  }
  /** The comparison key: lower case, letters and digits only, "the" in front dropped. Same key = same title. */
  function key(title, year) {
    const k = lower(title).normalize("NFKD").replace(/[̀-ͯ]/g, "").replace(/&/g, "and").replace(/[^\p{L}\p{N}]+/gu, " ").trim().replace(/^(the|a|an)\s+/, "");
    return k + (year ? "|" + year : "");
  }
  /** How much a cleaned line looks like a name (0..1): short, mostly capitalised words, few sentence words. */
  function nameLike(t) {
    if (!t || t.length < 2 || t.length > 70) return 0;
    if (NOISE.test(t)) return 0;
    if (CHROME.has(lower(t)) || CHROME.has(lower(t).replace(/[?.!]+$/, ""))) return 0;
    const words = t.split(/\s+/);
    if (words.length > 9) return 0;
    const letters = (t.match(/\p{L}/gu) || []).length;
    if (letters < 2 || letters / t.length < 0.5) return 0;
    let caps = 0;
    let counted = 0;
    for (const w of words) {
      const first = w.replace(/^[^\p{L}\p{N}]+/u, "")[0];
      if (!first) continue;
      if (SMALL.has(lower(w))) continue;
      counted++;
      if (/\p{Lu}|\p{N}/u.test(first)) caps++;
    }
    const capShare = counted ? caps / counted : 0;
    const sentence = (t.match(SENTENCE) || []).length;
    let s = 0.35 + 0.45 * capShare - 0.25 * sentence - (words.length > 6 ? 0.15 : 0);
    if (/[.!?]\s+\p{L}/u.test(t)) s -= 0.3;  // two sentences
    if (/^\p{Ll}+$/u.test(t.replace(/\s/g, "")) && words.length > 2) s -= 0.2;
    if (t === t.toUpperCase() && letters >= 3 && words.length <= 6) s += 0.1;  // poster style: ALL CAPS
    return Math.max(0, Math.min(1, s));
  }
  /** Splits a run-together hashtag into words when it is written in CamelCase (#ShutterIsland). */
  function tagTitle(tag) {
    const t = tag.replace(/_/g, " ").replace(/([\p{Ll}\d])(\p{Lu})/gu, "$1 $2").replace(/(\p{Lu})(\p{Lu}\p{Ll})/gu, "$1 $2").trim();
    return t;
  }

  // ---------------------------------------------------------------- context: where the picture came from

  /** {app, kind, lang} from the file name and folder (a folder named "anime" means anime). */
  function context(name, folder) {
    const n = lower(name);
    const f = lower(folder);
    let app = "";
    let kind = "";
    for (const [re, a, k] of APPS) if (re.test(n)) { app = a; kind = k; break; }
    for (const part of f.split(/[\/\\_\-\s.]+/)) {
      kind = kindOf(part) || kind;
      if (/^(k|korean)?dramas?$/.test(part)) kind = part.startsWith("k") ? "kdrama" : "drama";
    }
    let lang = "";
    for (const part of f.split(/[\/\\_\-\s.]+/)) lang = langOf(part) || lang;
    return { app, kind, lang };
  }

  // ---------------------------------------------------------------- the reader

  /**
   * Title candidates in one piece of text. lines: [{t, x, y, w, h}] in picture pixels (from the text reader), or
   * plain strings (a caption). opts: {W, H, name, folder, source}. Returns
   * {candidates: [{title, year, kind, lang, score, why, snippet}], kind, lang, app, text}.
   */
  function read(lines, opts = {}) {
    const W = opts.W || 0;
    const H = opts.H || 0;
    const ctx = context(opts.name || "", opts.folder || "");
    // plain text (a caption): one row per sentence too, so "Loved it. Movie name: Arrival" is read like two lines
    let rows = (lines || []).flatMap((l) => typeof l === "string" ? l.split(/(?<=\p{Ll}{2}[.!?])\s+(?=\p{Lu})/u).map((t) => ({ t })) : [{ ...l }]);
    rows = rows.map((r, i) => ({ ...r, i }));
    rows = rows.map((r) => ({ ...r, t: strip(r.t) })).filter((r) => r.t);
    // the phone's status bar (time, battery) and navigation bar are never part of the post
    if (H) rows = rows.filter((r) => r.y == null || (r.y > H * 0.035 && r.y + (r.h || 0) < H * 0.97));
    const all = rows.map((r) => r.t).join("\n");
    const found = new Map();
    const add = (raw, base, why, snippet, extra = {}) => {
      const c = clean(raw);
      if (!c.title) return;
      let like = nameLike(c.title);
      if (why === "labelled" || why === "title-year" || why === "hashtag") like = Math.max(like, 0.5);
      if (!like) return;
      const score = Math.max(0, Math.min(0.99, base * (0.55 + 0.45 * like)));
      const k = key(c.title, null);
      if (!k || k.length < 2) return;
      const cur = found.get(k);
      const cand = { title: c.title, year: c.year || extra.year || null, kind: c.kind || extra.kind || "", lang: c.lang || extra.lang || "",
        score, why, snippet: String(snippet || raw).slice(0, 200) };
      if (!cur) { found.set(k, cand); return; }
      cur.score = Math.min(0.99, Math.max(cur.score, score) + 0.1 * Math.min(cur.score, score));  // seen twice: surer
      if (score > cur.score - 0.1 && why !== cur.why) cur.why = cur.score >= score ? cur.why : why;
      cur.year = cur.year || cand.year;
      cur.kind = cur.kind || cand.kind;
      cur.lang = cur.lang || cand.lang;
      if (cand.title.length > cur.title.length && key(cand.title) === key(cur.title)) cur.title = cand.title;
    };

    // 1. labelled: "Movie: Interstellar", "Anime name - Mushishi", "🎬 Prisoners"
    for (const r of rows) {
      const m = r.t.match(LABEL);
      if (m) add(m[2], 0.92, "labelled", r.t, { kind: kindOf(m[1].split(/\s/)[0].replace("-", "")) });
      const e = r.t.match(EMOJI_MARK);
      if (e) add(e[1], 0.8, "labelled", r.t);
    }
    // 2. "Name (2014)" or "Name - 2014"
    for (const r of rows) {
      const m = r.t.match(/^(.{2,70}?)\s*[([]\s*((?:19[2-9]|20[0-3])\d)\s*[)\]]/);
      if (m) add(m[1].replace(LABEL, "$2").replace(ORDINAL, "$3"), 0.88, "title-year", r.t, { year: Number(m[2]) });
      const n = r.t.match(/^(?!.*\d{4}.*\d{4})(.{2,60}?)\s+[-–\u2014|·•]\s+((?:19[2-9]|20[0-3])\d)\s*$/);
      if (n) add(n[1].replace(ORDINAL, "$3"), 0.8, "title-year", r.t, { year: Number(n[2]) });
    }
    // 3. numbered or bulleted lists ("1. Prisoners", "2) Gone Girl") under a heading about movies, anime...
    const listy = /movie|film|anime|manga|manhwa|series|show|drama|watch|read|recommend|must|top|best|underrated/i.test(all);
    let listRun = 0;
    for (const r of rows) {
      const m = r.t.match(ORDINAL);
      if (!m) { listRun = 0; continue; }
      listRun++;
      const body = m[3];
      if (!body) continue;
      add(body.replace(LABEL, "$2"), listy ? 0.82 : 0.6, "list-item", r.t);
    }
    // 4. streaming, Google and IMDb pages: the name sits right above "2014 · Sci-fi · 2h 49m"
    for (let i = 0; i < rows.length; i++) {
      if (!META_LINE.test(rows[i].t)) continue;
      const year = (rows[i].t.match(YEAR) || [])[1];
      for (let j = i - 1; j >= Math.max(0, i - 3); j--) {
        const t = rows[j].t;
        if (nameLike(clean(t).title) >= 0.4) {
          add(t, 0.86, "metadata-line", t + " / " + rows[i].t, { year: year ? Number(year) : null, kind: /season|episode/i.test(rows[i].t) ? "series" : "" });
          break;
        }
      }
    }
    // 5. a manga or episode page: "Solo Leveling Chapter 110", "Chapter 45" under the title
    for (let i = 0; i < rows.length; i++) {
      const m = rows[i].t.match(new RegExp("^(.{2,60}?)\\s*[-–:|]?\\s*" + CHAPTER.source, "i"));
      if (m && nameLike(clean(m[1]).title) >= 0.4) add(m[1], 0.75, "chapter-line", rows[i].t, { kind: /ch/i.test(rows[i].t) ? "manga" : "series" });
      else if (CHAPTER.test(rows[i].t) && i > 0 && rows[i].t.replace(CHAPTER, "").trim().length < 4) {
        add(rows[i - 1].t, 0.62, "chapter-line", rows[i - 1].t + " / " + rows[i].t, { kind: /ch/i.test(rows[i].t) ? "manga" : "series" });
      }
    }
    // 6. comments that answer "movie name?": the short name-like line in the reply
    for (let i = 0; i < rows.length; i++) {
      if (!ASK.test(rows[i].t)) continue;
      for (let j = i + 1; j < Math.min(rows.length, i + 6); j++) {
        let t = rows[j].t.replace(/^@[\w.]+\s*/, "").replace(/^(it'?s|its|it is|this is|that'?s|movie is|name is|called)\s+/i, "");
        if (ASK.test(t)) continue;
        if (nameLike(clean(t).title) >= 0.55 && t.split(/\s+/).length <= 7) { add(t, 0.7, "comment", rows[i].t + " / " + rows[j].t); break; }
      }
    }
    // 7. hashtags: #Interstellar, #shutterisland (generic ones like #movie only tell the kind)
    const hints = { kind: [], lang: [] };
    for (const m of all.matchAll(/#([\p{L}\p{N}_]{3,40})/gu)) {
      const w = lower(m[1]);
      const k = kindOf(w);
      const l = langOf(w);
      if (k) hints.kind.push(k);
      if (l) hints.lang.push(l);
      if (GENERIC_TAGS.has(w) || /^\d+$/.test(w) || /(edit|edits|fan|fans|lover|lovers|scenes?|clips?|status|memes?|official|reels?|daily|world|club|page|hub|zone|vibes?|fyp|trending|viral)$/.test(w) && w.length > 8) continue;
      const looks = tagTitle(m[1]);
      add(looks.length > 1 && /\s/.test(looks) ? looks : m[1].replace(/_/g, " "), 0.55, "hashtag", m[0]);
    }
    // 8. the biggest text on the picture (a poster, a title card, the name on a page) when the reader gave sizes
    if (H && rows.some((r) => r.h)) {
      const hs = rows.filter((r) => r.h).map((r) => r.h).sort((a, b) => a - b);
      const median = hs[Math.floor(hs.length / 2)] || 1;
      const big = rows.filter((r) => r.h && r.h >= median * 1.7 && r.h >= H * 0.018).sort((a, b) => b.h - a.h).slice(0, 2);
      for (const r of big) {
        const c = clean(r.t);
        if (nameLike(c.title) >= 0.5) add(r.t, 0.5 + Math.min(0.2, (r.h / median - 1.7) * 0.05), "big-text", r.t);
      }
    }
    // words anywhere that say the kind or language ("anime", "Tamil movie", "season 2")
    for (const w of lower(all).split(/[^\p{L}]+/u)) {
      if (!w) continue;
      const k = kindOf(w);
      const l = langOf(w);
      if (k && !["trailer", "imdb", "letterboxd", "season", "episode", "episodes", "animated"].includes(w)) hints.kind.push(k);
      if (l && w.length > 4) hints.lang.push(l);
    }
    const kind = ctx.kind || most(hints.kind);
    const lang = ctx.lang || most(hints.lang);
    // "#shutterisland" and "Shutter Island" are the same: keep one, a bit surer
    const squash = (t) => key(t).replace(/\s+/g, "");
    for (const [k, c] of [...found.entries()]) {
      if (c.why !== "hashtag") continue;
      const twin = [...found.values()].find((o) => o !== c && squash(o.title) === squash(c.title));
      if (twin) { twin.score = Math.min(0.99, twin.score + 0.08); found.delete(k); }
    }
    const candidates = [...found.values()]
      .filter((c) => c.score >= 0.3 && !(c.why === "hashtag" && kindOf(c.title.replace(/\s/g, ""))))
      .map((c) => {
        const k = c.kind || kind;
        const l = c.lang || (k === kind ? lang : "") || kindHomeLang[k] || "";
        return { ...c, kind: k, lang: l };
      })
      .sort((a, b) => b.score - a.score)
      .slice(0, 15);
    return { candidates, kind, lang, app: ctx.app, text: all.slice(0, 4000) };
  }
  const kindHomeLang = { anime: "japanese", manga: "japanese", manhwa: "korean", kdrama: "korean", manhua: "chinese", cdrama: "chinese", jdrama: "japanese" };
  function most(list) {
    const n = {};
    let best = "";
    for (const x of list) { n[x] = (n[x] || 0) + 1; if (!best || n[x] > n[best]) best = x; }
    return best;
  }

  /** The verdict for one picture: "found" (one clear name), "several" (a list), "unsure" (weak guesses), "none" or "no_text". */
  function verdict(res) {
    if (!res.text || res.text.replace(/\s/g, "").length < 3) return "no_text";
    const c = res.candidates;
    if (!c.length) return "none";
    const strong = c.filter((x) => x.score >= 0.6);
    if (strong.length >= 2 && strong.filter((x) => x.why === "list-item").length >= 2) return "several";
    if (strong.length) return "found";
    return "unsure";
  }

  return { read, clean, key, nameLike, context, verdict, kindOf, langOf, tagTitle, KIND_WORDS, LANG_WORDS };
})();

if (typeof module !== "undefined") module.exports = Titles;
