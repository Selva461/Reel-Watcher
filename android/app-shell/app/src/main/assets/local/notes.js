/* Reel Shelf (built in): pure helpers, no screen code. Reading reel links, reading and writing the notes format
   (TOPIC, POINTS, MEANING, USE IT FOR, TOOLS, TAKEAWAY, TAGS), prompts, exports, and Instagram's data download. */
"use strict";

const Notes = (() => {
  const FORMAT = [
    "TOPIC: one short line",
    "POINTS:",
    "1. every point in the order it comes, with the names, numbers, tools and steps it mentions",
    "2. ...",
    "MEANING: what it means, in simple words",
    "USE IT FOR: when and how I can use this",
    "TOOLS: every tool, app, website or product named, separated by commas (or none)",
    "TAKEAWAY: the one thing to remember",
    "TAGS: 5 to 8 short tags, separated by commas",
  ].join("\n");

  const META_PROMPT = "Break down this Instagram reel for my notes: {link}\n\n" +
    "Watch the whole reel: what is said, the text on screen and the caption. Do not skip any point. " +
    "Answer in plain text in exactly this format:\n\n" + FORMAT;

  const LOCAL_SYSTEM = "You write short, accurate notes about Instagram reels. Use only the text you are given. " +
    "If something is not in the text, leave it out instead of guessing. Answer in English.";

  // ---------------------------------------------------------------- reel links

  const IG = /(?:https?:\/\/)?(?:www\.|m\.)?instagram\.com\/(?:[A-Za-z0-9_.]+\/)?(reels?|p|tv)\/([A-Za-z0-9_-]{5,40})/gi;

  const YT = /(?:https?:\/\/)?(?:www\.|m\.)?(?:youtube\.com\/(?:shorts\/|live\/|embed\/|watch\?(?:[^\s#]*?&)?v=)|youtu\.be\/)([A-Za-z0-9_-]{11})(?![A-Za-z0-9_-])/gi;

  /** Every Instagram reel/post and YouTube Short/video in a text, once each, in order: [{code, url, source}] */
  function links(text) {
    const found = [];
    const s = String(text || "");
    for (const m of s.matchAll(IG)) {
      found.push({ at: m.index, code: m[2], source: "instagram", url: `https://www.instagram.com/${m[1].toLowerCase() === "p" ? "p" : "reel"}/${m[2]}/` });
    }
    for (const m of s.matchAll(YT)) found.push({ at: m.index, code: "yt-" + m[1], source: "youtube", url: `https://www.youtube.com/shorts/${m[1]}` });
    found.sort((a, b) => a.at - b.at);
    const seen = new Set();
    const out = [];
    for (const f of found) {
      if (seen.has(f.code)) continue;
      seen.add(f.code);
      out.push({ code: f.code, url: f.url, source: f.source });
    }
    return out;
  }
  function isYoutube(r) { return /^yt-/.test(r.code || ""); }

  // ---------------------------------------------------------------- the notes format

  const KEYS = [["topic", "TOPIC"], ["points", "POINTS"], ["meaning", "MEANING"], ["use", "USE IT FOR"], ["tools", "TOOLS"],
    ["takeaway", "TAKEAWAY"], ["tags", "TAGS"]];
  const ALIASES = { topic: "topic", title: "topic", points: "points", point: "points", "key points": "points", "main points": "points",
    meaning: "meaning", "what it means": "meaning", "use it for": "use", "use for": "use", "uses": "use", "use cases": "use",
    tools: "tools", tool: "tools", "tools mentioned": "tools", takeaway: "takeaway", takeaways: "takeaway", "key takeaway": "takeaway",
    tags: "tags", tag: "tags", hashtags: "tags" };
  // a heading starts the line (markdown # > * _ allowed, a list dash is not, so "- Tools: x" inside POINTS stays a point)
  const HEAD = new RegExp("^[\\s>#*_]*(" + Object.keys(ALIASES).sort((a, b) => b.length - a.length).map((k) => k.replace(/ /g, "\\s+")).join("|") +
    ")\\s*[*_]*\\s*(?:[:\\uFF1A\\u2013-]\\s*[*_]*\\s*(.*)|$)", "i");

  function clean(s) {
    return String(s || "").replace(/\*\*|`/g, "").replace(/(^|\s)__(\S[^_]*?)__(?=\s|$)/g, "$1$2").replace(/^\s*[*_]+(?=\S)|(?<=\S)[*_]+\s*$/g, "")
      .replace(/\s+/g, " ").trim();
  }
  function bulletless(s) { return clean(String(s).replace(/^\s*(?:[-*•▪◦‣]+|\d{1,3}[.)])\s*/, "")); }
  function lines(arr) { return arr.map(bulletless).filter(Boolean); }
  function para(arr) { return clean(arr.join(" ")); }
  function list(arr) {
    return arr.join("\n").split(/[,;\n]|\s\/\s/).map(bulletless).filter((x) => x && !/^(none|n\/a|na|nothing|-)\.?$/i.test(x));
  }

  /** Reads an answer in the notes format (from Meta AI, the phone's AI, or pasted). null when it is not one. */
  function parse(text) {
    const raw = {};
    let cur = null;
    for (const line of String(text || "").replace(/\r/g, "").split("\n")) {
      const m = line.match(HEAD);
      if (m) {
        cur = ALIASES[m[1].toLowerCase().replace(/\s+/g, " ")];
        if (!raw[cur]) raw[cur] = [];
        if (m[2] && m[2].trim()) raw[cur].push(m[2]);
        continue;
      }
      if (cur) raw[cur].push(line);
    }
    const found = Object.keys(raw).filter((k) => raw[k].some((x) => x.trim()));
    if (found.length < 2 || !(raw.topic || raw.points)) return null;
    const n = {
      topic: para(raw.topic || []),
      points: lines(raw.points || []),
      meaning: para(raw.meaning || []),
      use: lines(raw.use || []),
      tools: list(raw.tools || []),
      takeaway: para(raw.takeaway || []),
      tags: [...new Set(list(raw.tags || []).flatMap((t) => t.split(/\s+/)).map((t) => t.replace(/^#+/, "").toLowerCase().replace(/[^\p{L}\p{N}_-]/gu, ""))
        .filter(Boolean))].slice(0, 12),
    };
    n.topic = n.topic.replace(/^["']|["']$/g, "").slice(0, 200);
    return n;
  }

  /** Several answers pasted together: split at each TOPIC line. */
  function splitAnswers(text) {
    const parts = [];
    let cur = [];
    for (const line of String(text || "").replace(/\r/g, "").split("\n")) {
      const m = line.match(HEAD);
      if (m && ALIASES[m[1].toLowerCase().replace(/\s+/g, " ")] === "topic" && cur.some((l) => l.match(HEAD))) {
        // a "REEL: <link>" line (or a heading with the link) just before TOPIC belongs to the next answer
        const carry = [];
        while (cur.length && (!cur[cur.length - 1].trim() || (links(cur[cur.length - 1]).length && !cur[cur.length - 1].match(HEAD)))) carry.unshift(cur.pop());
        parts.push(cur.join("\n"));
        cur = carry.some((l) => l.trim()) ? carry : [];
      }
      cur.push(line);
    }
    if (cur.length) parts.push(cur.join("\n"));
    return parts.map((t) => ({ text: t, notes: parse(t), links: links(t) })).filter((p) => p.notes);
  }

  /** The notes back as text, in the same format (to copy or export). */
  function format(n) {
    if (!n) return "";
    const out = [`TOPIC: ${n.topic || ""}`, "POINTS:"];
    (n.points || []).forEach((p, i) => out.push(`${i + 1}. ${p}`));
    out.push(`MEANING: ${n.meaning || ""}`);
    if ((n.use || []).length > 1) { out.push("USE IT FOR:"); n.use.forEach((u) => out.push(`- ${u}`)); } else out.push(`USE IT FOR: ${(n.use || [])[0] || ""}`);
    out.push(`TOOLS: ${(n.tools || []).join(", ") || "none"}`);
    out.push(`TAKEAWAY: ${n.takeaway || ""}`);
    out.push(`TAGS: ${(n.tags || []).join(", ")}`);
    return out.join("\n");
  }

  function metaPrompt(template, reel) {
    const t = String(template || META_PROMPT);
    const link = reel.url || "";
    let out = t.includes("{link}") ? t.split("{link}").join(link) : `${t.trim()}\n\nReel: ${link}`;
    if (reel.transcript) out += `\n\nWhat is said in it (transcript):\n${reel.transcript.slice(0, 12000)}`;
    return out;
  }

  const BATCH_HEAD = "Break down each of these {n} Instagram reels for my notes. Watch each whole reel: what is said, the text on " +
    "screen and the caption. Do not skip any point. Do them one by one, in this order. Start each one with a line " +
    "\"REEL: <its link>\", then answer in plain text in exactly this format:";

  /** One message for Meta AI about several reels; its single answer is split back per reel by the REEL: lines. */
  function batchPrompt(reels) {
    const head = BATCH_HEAD.replace("{n}", reels.length);
    return `${head}\n\n${FORMAT}\n\nThe reels:\n${reels.map((r, i) => `${i + 1}. ${r.url}`).join("\n")}`;
  }

  function localPrompt(reel, extra) {
    const yt = isYoutube(reel);
    const parts = [yt ? "Here is a YouTube video (title, description and what is said in it)." : "Here is what could be read from an Instagram reel."];
    if (reel.url) parts.push(`Link: ${reel.url}`);
    if (reel.title) parts.push(`Title: ${reel.title}`);
    if (reel.author) parts.push(`Creator: ${yt ? "" : "@"}${reel.author}`);
    if (reel.caption) parts.push(`${yt ? "Description" : "Caption"}:\n${reel.caption.slice(0, 3000)}`);
    if (reel.transcript) parts.push(`What is said (transcript):\n${reel.transcript.slice(0, 7000)}`);
    if (reel.extra) parts.push(`What the reel says (typed by me):\n${reel.extra.slice(0, 6000)}`);
    parts.push(`Write notes in exactly this format:\n\n${FORMAT}`);
    if (extra && extra.trim()) parts.push(`Also: ${extra.trim()}`);
    return parts.join("\n\n");
  }

  /** How much there is to write notes from (the phone's AI cannot watch the video). */
  function material(reel) {
    return ((reel.title || "") + " " + (reel.caption || "") + " " + (reel.transcript || "") + " " + (reel.extra || "")).replace(/#\S+/g, "").trim().length;
  }

  // ---------------------------------------------------------------- YouTube: title, description, transcript (no key, no login)

  function ytId(r) { return String(r.code || "").replace(/^yt-/, ""); }
  function ytWatchUrl(r) { return `https://www.youtube.com/watch?v=${ytId(r)}`; }
  function ytKey(html) { const m = String(html || "").match(/"INNERTUBE_API_KEY":\s*"([a-zA-Z0-9_-]+)"/); return m ? m[1] : ""; }
  function ytPlayerUrl(key) { return `https://www.youtube.com/youtubei/v1/player${key ? "?key=" + key : ""}`; }
  function ytPlayerBody(r) { return JSON.stringify({ context: { client: { clientName: "ANDROID", clientVersion: "20.10.38", hl: "en" } }, videoId: ytId(r) }); }

  /** From the player answer: {title, author, description, track, blocked, why} */
  function ytPick(json) {
    let j = json;
    if (typeof j === "string") { try { j = JSON.parse(j); } catch (e) { return { why: "YouTube sent an answer that could not be read" }; } }
    const out = {};
    const v = (j && j.videoDetails) || {};
    if (v.title) out.title = String(v.title);
    if (v.author) out.author = String(v.author);
    if (v.shortDescription) out.description = String(v.shortDescription);
    const st = (j && j.playabilityStatus) || {};
    if (st.status && st.status !== "OK") out.why = `YouTube: ${st.reason || st.status}`;
    const tracks = (((j || {}).captions || {}).playerCaptionsTracklistRenderer || {}).captionTracks || [];
    const score = (t) => (/^en/.test(t.languageCode || "") ? 2 : 0) + (t.kind === "asr" ? 0 : 1);
    const best = tracks.slice().sort((a, b) => score(b) - score(a))[0];
    if (best && best.baseUrl) {
      if (String(best.baseUrl).includes("&exp=xpe")) out.blocked = true;
      out.track = String(best.baseUrl).replace("&fmt=srv3", "");
      out.language = best.languageCode || "";
    } else if (!out.why) out.why = "This video has no captions";
    return out;
  }

  /** Caption file (XML) to plain text. */
  function ytCaptions(xml) {
    const doc = new DOMParser().parseFromString(String(xml || ""), "text/xml");
    if (doc.querySelector("parsererror")) return "";
    const lines = [...doc.querySelectorAll("text, p")].map((e) => {
      const d = document.createElement("textarea");
      d.innerHTML = e.textContent || "";  // captions are HTML-escaped twice; a textarea only decodes, never runs anything
      return d.value.replace(/<[^>]*>/g, "").replace(/\s+/g, " ").trim();
    }).filter(Boolean);
    return lines.join(" ").replace(/\s+([.,!?])/g, "$1").trim();
  }

  // ---------------------------------------------------------------- the library as a search engine

  // ---------------------------------------------------------------- the library: search without AI
  // Plain maths, no model: word stems, a small synonym list, typo-tolerant matching, BM25 ranking, TF-IDF keywords,
  // cosine similarity for related reels, and extractive notes (the best sentences of the caption or transcript).

  const STOP = new Set(("a an the and or but if of to in on at by for with from as is are was were be been being it its this that these those i you he " +
    "she we they me my your our their them him her us what which who whom how why when where do does did done can could should would will shall may might " +
    "must about into over than then so not no yes just also very more most some any all each here there out up down get got like one two make made use " +
    "using used want need know thing things really going gonna way lot lots even only much many every new now time see look let am im dont its youre " +
    "follow link bio comment save share subscribe video reel reels shorts watch day today").split(" "));

  /** A light English stemmer: "passwords", "hashing", "hashed" all become "password" / "hash". */
  function stem(w) {
    if (w.length <= 3 || /\d/.test(w)) return w;
    let s = w;
    if (/ies$/.test(s) && s.length > 4) s = s.slice(0, -3) + "y";
    else if (/(ss|us|is)$/.test(s)) { /* keep: class, status, analysis */ }
    else if (/(ches|shes|xes|zes|sses)$/.test(s)) s = s.slice(0, -2);
    else if (/s$/.test(s)) s = s.slice(0, -1);
    if (/ing$/.test(s) && s.length > 5) s = s.slice(0, -3);
    else if (/ed$/.test(s) && s.length > 4) s = s.slice(0, -2);
    else if (/ly$/.test(s) && s.length > 4) s = s.slice(0, -2);
    if (/(.)\1$/.test(s) && !/(ll|ss|zz)$/.test(s) && s.length > 3) s = s.slice(0, -1);  // "hashing" > "hash", "running" > "run"
    return s;
  }
  function tokens(s) { return (String(s || "").toLowerCase().match(/[\p{L}\p{N}][\p{L}\p{N}+#.-]*/gu) || []).map((w) => w.replace(/[.-]+$/, "")).filter((w) => w && w.length > 1 && !STOP.has(w)); }
  function words(s) { return tokens(s).map(stem); }

  // words people use for the same thing; a search for one also finds the others (at a lower score)
  const SYN = [
    "ai artificial-intelligence llm gpt chatgpt claude gemini model chatbot", "password secret credential key token apikey", "phone mobile android iphone smartphone app",
    "money finance cash income salary earn invest investing stock", "fitness workout exercise gym training", "diet food nutrition meal eating protein",
    "code coding programming developer software dev", "hack breach leak attack vulnerability exploit", "security cybersecurity infosec privacy",
    "study learn learning exam school college", "job career interview resume cv hiring work", "sleep rest insomnia", "photo picture image camera",
    "video film edit editing", "business startup company entrepreneur", "marketing ads advertising brand growth", "productivity focus habit routine",
    "website web site page", "database db sql", "free cheap budget", "fast quick speed", "tip trick hack advice", "health medical doctor",
  ].map((g) => g.split(" ").map((w) => stem(w.replace(/-/g, ""))));
  function synonyms(t) {
    const out = new Set();
    for (const g of SYN) if (g.includes(t)) for (const w of g) if (w !== t) out.add(w);
    return [...out];
  }

  /** Edit distance up to 1 (a typo: one letter added, missing, changed or swapped). */
  function near(a, b) {
    if (a === b) return true;
    if (Math.abs(a.length - b.length) > 1 || Math.min(a.length, b.length) < 5) return false;
    let i = 0;
    while (i < a.length && a[i] === b[i]) i++;
    if (a.length === b.length) return a.slice(i + 1) === b.slice(i + 1) || (a[i] === b[i + 1] && a[i + 1] === b[i] && a.slice(i + 2) === b.slice(i + 2));
    const [s, l] = a.length < b.length ? [a, b] : [b, a];
    return s.slice(i) === l.slice(i + 1);
  }

  function fieldsOf(r) {
    const n = r.notes || {};
    return [[n.topic, 3], [(n.tags || []).join(" "), 3], [(n.tools || []).join(" "), 2], [r.title, 2], [(n.points || []).join(" "), 1.5],
      [n.meaning, 1], [(n.use || []).join(" "), 1], [n.takeaway, 1.5], [r.caption, 0.6], [r.transcript, 0.4], [r.extra, 0.6],
      [(r.collections || []).join(" "), 1], [(r.keywords || []).join(" "), 1.5], [r.author, 0.5]];
  }
  // Each reel's words are kept until its text changes, and the whole index until any reel changes,
  // so typing in a search box or opening a reel does not re-read the library every time.
  const docCache = new WeakMap();
  let lastIx = null;
  function docOf(r) {
    const f = fieldsOf(r);
    const sig = f.map((x) => x[0] || "").join("\u0001");
    const hit = docCache.get(r);
    if (hit && hit.sig === sig) return hit.d;
    const tf = new Map();
    let len = 0;
    for (const [text, w] of f) for (const t of words(text)) { tf.set(t, (tf.get(t) || 0) + w); len += w; }
    const d = { r, tf, len };
    docCache.set(r, { sig, d });
    return d;
  }
  function index(reels) {
    const docs = reels.map(docOf);
    if (lastIx && lastIx.docs.length === docs.length && lastIx.docs.every((d, i) => d === docs[i])) return lastIx;
    const df = new Map();
    for (const d of docs) for (const t of d.tf.keys()) df.set(t, (df.get(t) || 0) + 1);
    const avg = docs.reduce((a, d) => a + d.len, 0) / Math.max(1, docs.length) || 1;
    lastIx = { docs, df, avg, N: docs.length };
    return lastIx;
  }
  function idfOf(ix, t) { const n = ix.df.get(t) || 0; return Math.log(1 + (ix.N - n + 0.5) / (n + 0.5)); }

  /** Ranks reels for a question, like a small search engine. [{reel, score, lines}] */
  function search(reels, query, limit = 20) {
    const q = [...new Set(words(query))];
    if (!q.length) return [];
    const ix = index(reels);
    const vocab = [...ix.df.keys()];
    // each query word also matches: longer words that start with it, its typos, and its synonyms (each at a lower weight)
    const expand = new Map(q.map((t) => {
      const m = new Map([[t, 1]]);
      for (const k of vocab) {
        if (m.has(k)) continue;
        if (t.length >= 4 && (k.startsWith(t) || (k.length >= 4 && t.startsWith(k)))) m.set(k, 0.7);
        else if (near(t, k)) m.set(k, 0.6);
      }
      for (const s of synonyms(t)) if (!m.has(s)) m.set(s, 0.5);
      return [t, m];
    }));
    const out = [];
    for (const d of ix.docs) {
      let s = 0;
      let matched = 0;
      for (const t of q) {
        let best = 0;
        for (const [k, w] of expand.get(t)) {
          const f = d.tf.get(k);
          if (!f) continue;
          const v = w * idfOf(ix, k) * ((f * 2.2) / (f + 1.2 * (0.25 + 0.75 * (d.len / ix.avg))));
          if (v > best) best = v;
        }
        if (best) { matched++; s += best; }
      }
      if (!s) continue;
      s *= 0.5 + matched / q.length;  // reels that match more of the question come first
      const want = new Set([...expand.values()].flatMap((m) => [...m.keys()]));
      const n = d.r.notes || {};
      const cands = [...(n.points || []), n.takeaway, n.meaning, ...(n.use || [])].filter(Boolean);
      if (!cands.length) cands.push(...sentences([d.r.transcript, d.r.caption, d.r.extra].filter(Boolean).join("\n")));
      const lines = cands.map((l) => ({ l, k: new Set(words(l).filter((w) => want.has(w))).size }))
        .filter((x) => x.k).sort((a, b) => b.k - a.k).slice(0, 3).map((x) => x.l);
      out.push({ reel: d.r, score: s, lines });
    }
    return out.sort((a, b) => b.score - a.score).slice(0, limit);
  }

  /** Reels about the same thing (TF-IDF vectors, cosine similarity). [{reel, score}] */
  function related(reels, target, limit = 5) {
    const ix = index(reels);
    const groups = (d) => { const g = new Map(); for (const [t, f] of d.tf) SYN.forEach((s, i) => { if (s.includes(t)) g.set("~" + i, (g.get("~" + i) || 0) + f); }); return g; };
    const gdf = new Map();
    const gs = new Map(ix.docs.map((d) => { const g = groups(d); for (const k of g.keys()) gdf.set(k, (gdf.get(k) || 0) + 1); return [d, g]; }));
    // words plus their synonym groups (so "password" and "API key" reels are related), each weighted by rarity
    const vec = (d) => {
      const v = new Map();
      let norm = 0;
      for (const [t, f] of d.tf) { const x = (1 + Math.log(f)) * idfOf(ix, t); v.set(t, x); norm += x * x; }
      for (const [k, f] of gs.get(d)) { const n = gdf.get(k); const x = 0.7 * (1 + Math.log(f)) * Math.log(1 + (ix.N - n + 0.5) / (n + 0.5)); v.set(k, x); norm += x * x; }
      return { v, norm: Math.sqrt(norm) || 1 };
    };
    const me = ix.docs.find((d) => d.r === target);
    if (!me || !me.tf.size) return [];
    const a = vec(me);
    return ix.docs.filter((d) => d !== me && d.tf.size).map((d) => {
      const b = vec(d);
      let dot = 0;
      for (const [t, x] of a.v) { const y = b.v.get(t); if (y) dot += x * y; }
      return { reel: d.r, score: dot / (a.norm * b.norm) };
    }).filter((x) => x.score > 0.05).sort((x, y) => y.score - x.score).slice(0, limit);
  }

  function sentences(text) {
    // split at line ends and sentence ends, but not after a list number ("1. Obsidian" stays one line)
    return String(text || "").replace(/#[\p{L}\p{N}_]+/gu, " ").split(/(?<=[^\d\s][.!?])\s+|\n+/u).map((s) => s.replace(/\s+/g, " ").trim())
      .filter((s) => (s.length >= 12 || /^\d{1,2}[.)]\s*\p{L}{3}/u.test(s)) && /\p{L}/u.test(s));
  }

  const WEAK = new Set("step steps ask tell show try start stop best good great first last next part guys people thing someone something always never better still actually".split(" "));
  /** The words that matter in a text (RAKE/YAKE style: frequent, early, not common), as tags. */
  function keywords(text, limit = 8, ix = null) {
    const s = String(text || "");
    const hash = (s.match(/#([\p{L}\p{N}_]{3,30})/gu) || []).map((h) => h.slice(1).toLowerCase());
    const toks = tokens(s.replace(/#[\p{L}\p{N}_]+/gu, " ").replace(/https?:\/\/\S+/g, " "));
    const score = new Map();
    const shown = new Map();
    toks.forEach((w, i) => {
      if (w.length < 3 || /^\d+$/.test(w) || WEAK.has(w)) return;
      const k = stem(w);
      const pos = 1 / (1 + Math.log(1 + i / 20));  // earlier words count more
      score.set(k, (score.get(k) || 0) + pos);
      if (!shown.has(k) || w.length < shown.get(k).length) shown.set(k, w);
    });
    // two-word phrases that repeat ("password manager") beat single words
    for (let i = 0; i + 1 < toks.length; i++) {
      const p = `${toks[i]} ${toks[i + 1]}`;
      if (toks[i].length < 3 || toks[i + 1].length < 3) continue;
      const k = stem(toks[i]) + " " + stem(toks[i + 1]);
      score.set(k, (score.get(k) || 0) + 0.6);
      if (!shown.has(k)) shown.set(k, p);
    }
    const ranked = [...score.entries()].map(([k, v]) => {
      const rare = ix ? idfOf(ix, k.split(" ")[0]) / Math.log(1 + ix.N + 0.5) : 1;
      const isPhrase = k.includes(" ");
      return [k, (isPhrase ? (v > 1.2 ? v * 1.5 : 0) : v) * (0.4 + rare)];
    }).filter(([, v]) => v > 0).sort((a, b) => b[1] - a[1]);
    const out = [...new Set(hash)];
    for (const [k] of ranked) {
      if (out.length >= limit) break;
      const w = shown.get(k);
      if (out.some((o) => o.includes(w) || w.includes(o))) continue;
      out.push(w);
    }
    return out.slice(0, limit);
  }

  /** Notes made without any AI: the most informative sentences, in order, from the caption, transcript and your text. */
  function autoNotes(r, reels = []) {
    const text = [r.title, r.extra, r.transcript, r.caption].filter(Boolean).join("\n");
    const sents = [...new Set(sentences(text))];
    if (!sents.length) return null;
    const freq = new Map();
    for (const w of words(text)) freq.set(w, (freq.get(w) || 0) + 1);
    const ranked = sents.map((s, i) => {
      const ws = words(s);
      const v = ws.reduce((a, w) => a + Math.log(1 + (freq.get(w) || 0)), 0) / Math.sqrt(ws.length || 1);
      const numbers = /\d/.test(s) ? 0.3 : 0;  // steps, amounts and years are worth keeping
      return { s, i, v: v + numbers + (i === 0 ? 0.4 : 0) };
    });
    const best = ranked.slice().sort((a, b) => b.v - a.v).slice(0, 7).sort((a, b) => a.i - b.i).map((x) => x.s.slice(0, 300));
    const ix = reels.length ? index(reels) : null;
    const tags = keywords(text, 8, ix).map((t) => t.replace(/\s+/g, ""));
    const tools = [...new Set((text.match(/\b(?:[A-Z][a-z]+[A-Z][A-Za-z]*|[A-Z]{2,}[a-z]*|[A-Z][a-z]{2,}(?:\.(?:ai|io|com|app)))\b/g) || []))]
      .filter((t) => !/^(I|OK|AM|PM|DM|USA|UK)$/.test(t)).slice(0, 8);
    const topic = (r.title || sents[0]).replace(/\s+/g, " ").slice(0, 120);
    return { topic, points: best, meaning: "", use: [], tools, takeaway: ranked.slice().sort((a, b) => b.v - a.v)[0].s.slice(0, 300), tags };
  }

  /** A question answered only from your own notes, citing them as [1], [2]... */
  function answerPrompt(question, results) {
    const src = results.map((x, i) => `[${i + 1}] ${format(x.reel.notes || {}) || (x.reel.caption || "").slice(0, 800)}`).join("\n\n");
    return `Answer my question using only my notes below (from reels I watched). Be specific: give the steps, names, numbers ` +
      `and tools from the notes. After each fact, write the note number like [1]. If the notes do not answer it, say so.\n\n` +
      `Question: ${question}\n\nMy notes:\n\n${src}`;
  }

  // ---------------------------------------------------------------- reading a reel's public page (caption, creator)

  function embedUrl(code) { return `https://www.instagram.com/p/${code}/embed/captioned/`; }

  /** Caption and creator from the embed page, or from the page's description tags. {} when there is nothing. */
  function readPage(html) {
    const doc = new DOMParser().parseFromString(String(html || ""), "text/html");  // inert: nothing in it runs
    const out = {};
    doc.querySelectorAll("script, style, noscript, template").forEach((x) => x.remove());
    const cap = doc.querySelector(".Caption");
    if (cap) {
      const user = cap.querySelector(".CaptionUsername");
      if (user) out.author = clean(user.textContent).replace(/^@/, "");
      cap.querySelectorAll(".CaptionUsername, .CaptionComments").forEach((x) => x.remove());
      cap.querySelectorAll("br").forEach((b) => b.replaceWith("\n"));
      const t = cap.textContent.replace(/[ \t]+/g, " ").replace(/\n\s+/g, "\n").trim();
      if (t) out.caption = t;
    }
    if (!out.author) {
      const u = doc.querySelector(".UsernameText, .Username");
      if (u) out.author = clean(u.textContent).replace(/^@/, "");
    }
    if (!out.caption) {
      const d = doc.querySelector('meta[property="og:description"], meta[name="description"]');
      const v = d ? d.getAttribute("content") || "" : "";
      const m = v.match(/^[\d.,KkMm]+\s+likes?,.*?-\s*([A-Za-z0-9_.]+)\s+on\s+[^:]+:\s*["“]([\s\S]*)["”]\.?\s*$/);
      if (m) { out.author = out.author || m[1]; out.caption = m[2].trim(); } else if (v && !/^(see instagram|instagram)/i.test(v)) out.caption = v.trim();
    }
    return out;
  }

  // ---------------------------------------------------------------- exports

  function exportRows(reels) {
    return reels.map((r) => ({
      code: r.code, url: r.url || "", author: r.author || "", added_at: new Date(r.added_at || 0).toISOString(),
      collections: r.collections || [], caption: r.caption || "", what_it_says: r.extra || "", notes_by: r.notes_by || "",
      topic: (r.notes || {}).topic || "", points: (r.notes || {}).points || [], meaning: (r.notes || {}).meaning || "",
      use_it_for: (r.notes || {}).use || [], tools: (r.notes || {}).tools || [], takeaway: (r.notes || {}).takeaway || "",
      tags: (r.notes || {}).tags || [],
    }));
  }

  function exportJson(reels) {
    return JSON.stringify({ app: "Reel Shelf", exported_at: new Date().toISOString(), count: reels.length, reels: exportRows(reels) }, null, 2);
  }

  function exportMarkdown(reels) {
    const out = [`# Reel notes`, ``, `${reels.length} reels, exported ${new Date().toISOString().slice(0, 10)}`, ``];
    for (const r of reels) {
      const n = r.notes || {};
      out.push(`## ${n.topic || (r.author ? "@" + r.author : r.code)}`);
      out.push([r.url, r.author ? "@" + r.author : "", (n.tags || []).map((t) => "#" + t).join(" ")].filter(Boolean).join(" · "));
      out.push("");
      if (r.notes) out.push(format(n)); else out.push(`(no notes yet)${r.caption ? "\n\nCaption: " + r.caption : ""}`);
      out.push("");
    }
    return out.join("\n");
  }

  // ---------------------------------------------------------------- Instagram's "Download your information"

  function isLink(s) { return typeof s === "string" && /instagram\.com\/(?:[A-Za-z0-9_.]+\/)?(?:reels?|p|tv)\//i.test(s); }

  function entryName(e) {
    if (!e || typeof e !== "object" || Array.isArray(e)) return null;
    const smd = e.string_map_data;
    if (smd && typeof smd === "object") {
      for (const [k, v] of Object.entries(smd)) {
        if (/name/i.test(k) && v && typeof v.value === "string" && !v.href && !isLink(v.value)) return v.value.trim() || null;
      }
    }
    for (const lv of e.label_values || []) {
      if (lv && /name/i.test(String(lv.label || "")) && typeof lv.value === "string" && !lv.href && !isLink(lv.value)) return lv.value.trim() || null;
    }
    for (const k of ["collection_name", "name"]) if (typeof e[k] === "string" && e[k].trim() && !isLink(e[k])) return e[k].trim();
    return null;
  }

  function hasOwnLink(e) { return JSON.stringify(e.string_map_data || e.label_values || {}).match(/instagram\.com\/(?:[A-Za-z0-9_.]+\/)?(?:reels?|p|tv)\//i); }

  /** Saved reels from one export file: [{code, url, collection, author}] */
  function exportFile(name, text) {
    const rows = [];
    const push = (s, collection, author) => { for (const l of links(s)) rows.push({ ...l, collection: collection || "", author: author || "" }); };
    let j = null;
    if (/\.json$/i.test(name)) { try { j = JSON.parse(text); } catch (e) { j = null; } }
    if (j === null) { push(text, "", ""); return dedupe(rows); }
    const collFile = /collection/i.test(name);
    const walk = (node, title, coll) => {
      if (Array.isArray(node)) {
        let c = coll;
        for (const el of node) {
          const nm = collFile ? entryName(el) : null;
          if (nm && !hasOwnLink(el)) { c = nm; walk(el, title, c); continue; }
          walk(el, title, c);
        }
      } else if (node && typeof node === "object") {
        const t = typeof node.title === "string" && node.title ? node.title : title;
        for (const v of Object.values(node)) {
          if (typeof v === "string") { if (isLink(v)) push(v, coll, t); } else walk(v, t, coll);
        }
      }
    };
    walk(j, "", "");
    return dedupe(rows);
  }

  function dedupe(rows) {
    const by = new Map();
    for (const r of rows) {
      const cur = by.get(r.code);
      if (!cur) by.set(r.code, { ...r, collections: r.collection ? [r.collection] : [] });
      else if (r.collection && !cur.collections.includes(r.collection)) cur.collections.push(r.collection);
    }
    return [...by.values()];
  }

  /** Reads the saved-posts files out of the export ZIP (only those entries, so a big export is fine). [{name, text}] */
  async function readZip(file) {
    const u32 = (b, o) => (b[o] | (b[o + 1] << 8) | (b[o + 2] << 16) | (b[o + 3] << 24)) >>> 0;
    const u16 = (b, o) => b[o] | (b[o + 1] << 8);
    const bytes = async (from, to) => new Uint8Array(await file.slice(from, to).arrayBuffer());
    const tailLen = Math.min(file.size, 66000);
    const tail = await bytes(file.size - tailLen, file.size);
    let eocd = -1;
    for (let i = tail.length - 22; i >= 0; i--) if (u32(tail, i) === 0x06054b50) { eocd = i; break; }
    if (eocd < 0) throw new Error("This is not a ZIP file");
    const cdSize = u32(tail, eocd + 12) >>> 0;
    const cdOff = u32(tail, eocd + 16) >>> 0;
    if (cdOff === 0xffffffff) throw new Error("This ZIP is too big to read here. Unzip it and choose saved_posts.json and saved_collections.json");
    const cd = await bytes(cdOff, cdOff + cdSize);
    const out = [];
    let p = 0;
    while (p + 46 <= cd.length && u32(cd, p) === 0x02014b50) {
      const method = u16(cd, p + 10);
      const csize = u32(cd, p + 20) >>> 0;
      const nlen = u16(cd, p + 28);
      const elen = u16(cd, p + 30);
      const clen = u16(cd, p + 32);
      const loff = u32(cd, p + 42) >>> 0;
      const name = new TextDecoder().decode(cd.subarray(p + 46, p + 46 + nlen));
      p += 46 + nlen + elen + clen;
      if (!/saved[^/]*\.(json|html)$/i.test(name) || csize > 60e6) continue;
      const lh = await bytes(loff, loff + 30);
      const start = loff + 30 + u16(lh, 26) + u16(lh, 28);
      let data = await bytes(start, start + csize);
      if (method === 8) data = new Uint8Array(await new Response(new Blob([data]).stream().pipeThrough(new DecompressionStream("deflate-raw"))).arrayBuffer());
      else if (method !== 0) continue;
      out.push({ name: name.split("/").pop(), text: new TextDecoder().decode(data) });
    }
    return out;
  }

  return { FORMAT, META_PROMPT, LOCAL_SYSTEM, links, isYoutube, parse, splitAnswers, format, metaPrompt, batchPrompt, localPrompt, material, embedUrl, readPage,
    ytWatchUrl, ytKey, ytPlayerUrl, ytPlayerBody, ytPick, ytCaptions, search, answerPrompt, words, stem, near, related, keywords, autoNotes, sentences, index, idfOf, tokens, synonyms, fieldsOf,
    exportRows, exportJson, exportMarkdown, exportFile, readZip, KEYS };
})();
