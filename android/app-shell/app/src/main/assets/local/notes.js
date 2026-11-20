/* Reel Shelf (built in): pure helpers, no screen code. Reading reel links, reading and writing the notes format
   (TOPIC, POINTS, MEANING, USE IT FOR, TOOLS, TAKEAWAY, TAGS), prompts, exports, and Instagram's data download. */
"use strict";

const Notes = (() => {
  const FORMAT = [
    "TOPIC: one short line",
    "INTENT: what the creator is really trying to say or get you to do (the goal behind the reel)",
    "TONE: sincere, sarcastic, joking or mixed, and why; if sarcastic or joking, what they actually mean",
    "POINTS:",
    "1. every useful point in the order it comes, as the creator really means it (turn sarcasm or a bad example into the real advice), with the names, numbers, tools and steps it mentions",
    "2. ...",
    "MEANING: what it means, in simple words",
    "USE IT FOR: when and how I can use this",
    "TOOLS: every tool, app, website or product named, separated by commas (or none)",
    "PRODUCTS: every physical product shown or named, as brand and name (like CeraVe Foaming Cleanser), separated by commas (or none)",
    "INGREDIENTS: only for a cooking reel, one per line starting with -, with the amount only if it is said (leave this out for other reels)",
    "STEPS: only for a cooking reel, each cooking step in order, numbered (leave this out for other reels)",
    "TAKEAWAY: the one thing to remember",
    "TAGS: 5 to 8 short tags, separated by commas",
  ].join("\n");

  const META_PROMPT = "Break down this Instagram reel for my notes: {link}\n\n" +
    "Watch the whole reel: what is said, the text on screen and the caption. Do not skip any point. " +
    "Answer in plain text in exactly this format:\n\n" + FORMAT;

  const LOCAL_SYSTEM = "You write short, accurate notes about Instagram reels. Use only the text you are given. " +
    "Creators often use sarcasm, irony or act out a bad example to make a point: work out what they really mean and " +
    "write the real message, not the joke. If the reel is just a joke or meme, explain the joke in one or two lines in INTENT. " +
    "Comments from viewers can explain what the reel means. If something is not in what you are given, leave it out " +
    "instead of guessing. Answer in English.";

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
  const ALIASES = { topic: "topic", title: "topic", intent: "intent", goal: "intent", purpose: "intent", "real message": "intent",
    tone: "tone", points: "points", point: "points", "key points": "points", "main points": "points",
    meaning: "meaning", "what it means": "meaning", "use it for": "use", "use for": "use", "uses": "use", "use cases": "use",
    tools: "tools", tool: "tools", "tools mentioned": "tools", takeaway: "takeaway", takeaways: "takeaway", "key takeaway": "takeaway",
    tags: "tags", tag: "tags", hashtags: "tags", products: "products", product: "products", "products shown": "products",
    ingredients: "ingredients", ingredient: "ingredients", steps: "steps", method: "steps", instructions: "steps", "recipe steps": "steps" };
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
      intent: para(raw.intent || []),
      tone: para(raw.tone || []),
      points: lines(raw.points || []),
      meaning: para(raw.meaning || []),
      use: lines(raw.use || []),
      tools: list(raw.tools || []),
      takeaway: para(raw.takeaway || []),
      tags: [...new Set(list(raw.tags || []).flatMap((t) => t.split(/\s+/)).map((t) => t.replace(/^#+/, "").toLowerCase().replace(/[^\p{L}\p{N}_-]/gu, ""))
        .filter(Boolean))].slice(0, 12),
    };
    n.topic = n.topic.replace(/^["']|["']$/g, "").slice(0, 200);
    const products = list(raw.products || []);
    const ingredients = lines(raw.ingredients || []).filter((x) => !/^(none|n\/a|-)\.?$/i.test(x) && !/^leave/i.test(x));
    const steps = lines(raw.steps || []).filter((x) => !/^(none|n\/a|-)\.?$/i.test(x) && !/^leave/i.test(x));
    if (products.length) n.products = products.slice(0, 12);
    if (ingredients.length) n.ingredients = ingredients.slice(0, 40);
    if (steps.length) n.steps = steps.slice(0, 40);
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
    const out = [`TOPIC: ${n.topic || ""}`];
    if (n.intent) out.push(`INTENT: ${n.intent}`);
    if (n.tone) out.push(`TONE: ${n.tone}`);
    out.push("POINTS:");
    (n.points || []).forEach((p, i) => out.push(`${i + 1}. ${p}`));
    out.push(`MEANING: ${n.meaning || ""}`);
    if ((n.use || []).length > 1) { out.push("USE IT FOR:"); n.use.forEach((u) => out.push(`- ${u}`)); } else out.push(`USE IT FOR: ${(n.use || [])[0] || ""}`);
    out.push(`TOOLS: ${(n.tools || []).join(", ") || "none"}`);
    if ((n.products || []).length) out.push(`PRODUCTS: ${n.products.join(", ")}`);
    if ((n.ingredients || []).length) { out.push("INGREDIENTS:"); n.ingredients.forEach((x) => out.push(`- ${x}`)); }
    if ((n.steps || []).length) { out.push("STEPS:"); n.steps.forEach((x, i) => out.push(`${i + 1}. ${x}`)); }
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

  // ---------------------------------------------------------------- the prompt for the on-phone AI, and its budget
  // The model has a window (prompt and answer together). A prompt that fits it is sent as it is; a longer one is shortened in a
  // fixed order, by an estimate of its size in tokens (design: docs/design/A3-prompt-budget.md).

  const SHORT = " [shortened]";  // how a text that was cut to fit ends

  const tokensOf = (ascii, other) => Math.ceil(ascii / 3) + 2 * other;
  /** [ASCII characters, other characters (code points)] of a text. */
  function counts(text) {
    let ascii = 0, other = 0;
    for (const ch of String(text == null ? "" : text)) { if (ch.charCodeAt(0) < 128) ascii++; else other++; }
    return [ascii, other];
  }
  /** A deliberately pessimistic size in tokens (no tokenizer is available): ASCII characters / 3, plus 2 for every other character. */
  function estTokens(text) { return tokensOf(...counts(text)); }

  /** Tokens left for the whole prompt: the window less the answer (clamped as LocalModel.java clamps it), the system text, the
   *  reserve for pictures and sound, and 5% of the window for the chat template. An unknown window counts as 4096. */
  function promptBudget(o = {}) {
    const ctx = o.ctx > 0 ? Math.floor(o.ctx) : 4096;
    const asked = Math.trunc(+o.answer);
    const answer = Math.max(64, Math.min(Number.isFinite(asked) ? asked : 800, 3000));
    return Math.max(0, ctx - answer - estTokens(o.system) - (o.media > 0 ? Math.ceil(o.media) : 0) - Math.ceil(ctx / 20));
  }

  /** The first `max` UTF-16 units of a text, without half of an emoji (a surrogate pair) at the end. */
  function plainStart(text, max) {
    const t = String(text);
    let end = Math.max(0, Math.min(max, t.length));
    if (end > 0 && end < t.length && (t.charCodeAt(end - 1) & 0xFC00) === 0xD800) end--;
    return t.slice(0, end);
  }

  /** The start of a text that `ok(ASCII characters, other characters, UTF-16 length)` still allows (`ok` counts the marker too),
   *  followed by " [shortened]": cut at the last space, or where the limit falls when no space comes before it (between code
   *  points, never inside an emoji); "" when not even one character fits. */
  function cutStart(text, ok) {
    const t = String(text);
    let ascii = 0, other = 0, end = 0, space = -1;
    for (const ch of t) {
      const a = ch.charCodeAt(0) < 128;
      if (!ok(ascii + (a ? 1 : 0), other + (a ? 0 : 1), end + ch.length)) break;
      if (a) ascii++; else other++;
      if (/\s/.test(ch)) space = end;
      end += ch.length;
    }
    if (end < t.length && /\s/.test(t[end])) space = end;
    const body = t.slice(0, space > 0 ? space : end).trimEnd();
    return body ? body + SHORT : "";
  }

  /** The prompt for the phone's AI and the names of the texts that were shortened or left out to fit `opts.budget` (tokens; no
   *  budget: no limit). A prompt that already fits is exactly the prompt built without a budget. Otherwise the part that is always
   *  kept (the first lines, link, creator, the format with its line, the picture sentence) is counted first; if it is over the
   *  budget, your 'Also:' text is cut, then the title. Then each text takes the tokens that are left, in this order: typed
   *  text, transcript, the first 1,000 characters of the caption, text on screen, the rest of the caption, comments. */
  function localPromptInfo(reel, extra, opts = {}) {
    const yt = isYoutube(reel);
    const budget = Number.isFinite(opts.budget) ? opts.budget : Infinity;
    const label = { title: "Title: ", caption: yt ? "Description:\n" : "Caption:\n", transcript: "What is said (transcript):\n",
      onscreen: "Text shown on screen in the reel:\n", comments: "Top comments from viewers:\n", typed: "What the reel says (typed by me):\n", also: "Also: " };
    const build = (v) => {  // a part whose text is undefined is left out
      const parts = [yt ? "Here is a YouTube video (title, description and what is said in it)." : "Here is what could be read from an Instagram reel."];
      if (opts.media) parts.push("You also get pictures from the reel (key frames) and its first 30 seconds of sound: use them.");
      if (reel.url) parts.push(`Link: ${reel.url}`);
      if (v.title !== undefined) parts.push(label.title + v.title);
      if (reel.author) parts.push(`Creator: ${yt ? "" : "@"}${reel.author}`);
      for (const k of ["caption", "transcript", "onscreen", "comments", "typed"]) if (v[k] !== undefined) parts.push(label[k] + v[k]);
      parts.push(`Write notes in exactly this format:\n\n${FORMAT}`);
      if (v.also !== undefined) parts.push(label.also + v.also);
      return parts.join("\n\n");
    };
    const want = {  // every text as it goes in when there is room: the fixed caps of each source
      title: reel.title || undefined,
      caption: reel.caption ? reel.caption.slice(0, 3000) : undefined,
      transcript: reel.transcript ? condense(reel.transcript, 7000) : undefined,
      onscreen: reel.onscreen ? reel.onscreen.slice(0, 2000) : undefined,
      comments: reel.comments ? reel.comments.slice(0, 2500) : undefined,
      typed: reel.extra ? reel.extra.slice(0, 6000) : undefined,
      also: extra && extra.trim() ? extra.trim() : undefined,
    };
    const full = build(want);
    if (!(estTokens(full) > budget)) return { prompt: full, shortened: [] };

    const got = { title: want.title, also: want.also };
    // what is in the prompt now, plus the label and separator of the part `k` that comes next ([ASCII, other] counts)
    const baseFor = (k) => { const [a, o] = counts(build(got)), [la, lo] = counts("\n\n" + label[k]); return [a + la, o + lo]; };
    const cost = (b, text) => { const [a, o] = counts(text); return tokensOf(b[0] + a, b[1] + o); };
    // a text that goes after `b`: whole, or its start cut at a word (with the marker), or "" when not even a word of it fits
    const place = (text, b, limit = budget) => {
      if (cost(b, text) <= limit) return text;
      const [ma, mo] = counts(SHORT);
      return cutStart(text, (a, o) => tokensOf(b[0] + ma + a, b[1] + mo + o) <= limit);
    };
    // the transcript in what is left: its most informative sentences (condense), narrowed until they fit
    const placeTranscript = (b) => {
      if (cost(b, want.transcript) <= budget) return want.transcript;
      const room = budget - tokensOf(b[0], b[1]);
      let max = Math.min(7000, Math.max(0, room * 3));
      for (let i = 0; i < 10 && max > SHORT.length; i++) {
        let out = condense(reel.transcript, max);
        if (!out) break;
        if (!out.endsWith(SHORT)) out += SHORT;
        if (cost(b, out) <= budget) return out;
        max = Math.floor(max * Math.min(0.95, room / estTokens(out)));
      }
      return place(want.transcript, b);
    };
    const put = (k, text, reserve = 0) => {
      const b = baseFor(k);
      got[k] = (k === "transcript" ? placeTranscript(b) : place(text, b, budget - reserve)) || undefined;
    };

    // 1. the part that is always kept: when it is over the budget, your 'Also:' text is cut first, then the title
    if (estTokens(build(got)) > budget) {
      if (got.also !== undefined) { got.also = undefined; got.also = place(want.also, baseFor("also")) || undefined; }
      if (got.title !== undefined && estTokens(build(got)) > budget) { got.title = undefined; got.title = place(want.title, baseFor("title")) || undefined; }
    }
    // 2. the texts, each in what is left of the budget
    if (want.typed !== undefined) put("typed", want.typed);
    if (want.transcript !== undefined) put("transcript");
    const first = want.caption === undefined ? "" : want.caption.slice(0, 1000);
    if (want.caption !== undefined) put("caption", first);
    const more = want.caption !== undefined && got.caption === first && want.caption.length > 1000;  // the rest of the caption is still to come
    if (want.onscreen !== undefined) put("onscreen", want.onscreen, more ? estTokens(SHORT) : 0);  // keeps room to mark a cut caption
    if (more) { got.caption = undefined; put("caption", want.caption); }
    if (want.comments !== undefined) put("comments", want.comments);
    return { prompt: build(got), shortened: Object.keys(want).filter((k) => want[k] !== undefined && got[k] !== want[k]) };
  }

  function localPrompt(reel, extra, opts = {}) { return localPromptInfo(reel, extra, opts).prompt; }

  /** How much there is to write notes from (the phone's AI cannot watch the video). */
  function material(reel) {
    return ((reel.title || "") + " " + (reel.caption || "") + " " + (reel.transcript || "") + " " + (reel.onscreen || "") + " " + (reel.comments || "") + " " + (reel.extra || "")).replace(/#\S+/g, "").trim().length;
  }

  // ---------------------------------------------------------------- retries: a reel that keeps failing is parked
  const RETRY_CAP = 3;
  const BACKOFF_H = [12, 72];  // hours to wait after the 1st and the 2nd failure
  /** Milliseconds to wait before the next try after `tries` failures in a row; null when the reel is parked (no automatic try). */
  function retryAfter(tries) {
    return tries >= RETRY_CAP ? null : (BACKOFF_H[Math.max(1, tries) - 1] || BACKOFF_H[BACKOFF_H.length - 1]) * 3600e3;
  }

  // ---------------------------------------------------------------- your own edits (K1): what you typed is never overwritten by an AI answer
  // A reel you edited has notes_by "you" and notes_edit {was_by (who wrote the notes before, "" when you wrote them from
  // scratch), at (the first edit), fields (the edited ones), ai (the AI's text of each edited field, written once)}.
  // notes_next {meta, phone, you} holds versions set aside by setNotes (local.js). Nothing else about the reel changes shape.
  const EDITABLE = ["topic", "points", "takeaway", "tags"];
  const LIMIT = { topic: 200, takeaway: 1000, tags: 12, points: 40, point: 500 };  // for text you type, in letters (points: how many, and how long)
  const copy = (v) => (v == null ? v : JSON.parse(JSON.stringify(v)));
  const blank = (v) => ![].concat(v == null ? [] : v).map(bulletless).some(Boolean);
  /** The tags of a typed list (a text, or an array), by the rule of `parse`: lowercase, letters, digits, _ and -, once each. */
  function tagList(v) {
    return [...new Set(list([].concat(v == null ? [] : v)).flatMap((t) => t.split(/\s+/)).map((t) => t.replace(/^#+/, "").toLowerCase().replace(/[^\p{L}\p{N}_-]/gu, "")).filter(Boolean))];
  }

  /**
   * What you typed in one editable field (topic, points, takeaway, tags), written the way `parse` writes AI notes,
   * and whether it may be saved: {value, error, changed}. A points value is a text with one point per line (or an array),
   * tags a text with commas (or an array).
   * Only a field that CHANGED is checked: "changed" means the cleaned new value differs from the cleaned stored value
   * (points and tags item by item, in order). An unchanged field comes back as stored, even past the limits, because `parse`
   * lets AI notes go past them. A changed field may be as long as the larger of its limit and what is stored now (a point:
   * a line that is not already a stored point is held to the larger of 500 and the longest stored point). With
   * more than the allowed tags the first ones are in `value` and `error` says so. `other` (optional) is what the other of
   * topic and points will hold: a topic and points both empty are refused.
   */
  function cleanField(f, value, old, other) {
    const num = (n) => n.toLocaleString("en-US");
    const one = (v, empty) => (v == null ? empty : v);
    if (f === "points" || f === "tags") {
      const read = f === "points" ? (v) => lines(typeof v === "string" ? v.split("\n") : [].concat(one(v, []))) : tagList;
      const next = read(value), prev = read(one(old, []));
      if (next.length === prev.length && next.every((x, i) => x === prev[i])) return { value: copy(one(old, [])), error: "", changed: false };
      let error = "", out = next;
      if (f === "points") {
        const count = Math.max(LIMIT.points, prev.length), long = prev.reduce((m, p) => Math.max(m, p.length), LIMIT.point), known = new Set(prev);
        if (next.length > count || next.some((p) => p.length > long && !known.has(p))) error = `Keep at most ${count} points, each under ${num(long)} letters.`;
        else if (!next.length && other !== undefined && blank(other)) error = "Write a topic or at least one point.";
      } else {
        const count = Math.max(LIMIT.tags, prev.length);
        if (next.length > count) { error = `Only the first ${count} tags are kept.`; out = next.slice(0, count); }
      }
      return { value: out, error, changed: true };
    }
    const next = clean(value), prev = clean(one(old, ""));
    if (next === prev) return { value: one(old, ""), error: "", changed: false };
    let error = "";
    const bound = Math.max(LIMIT[f], prev.length);
    if (next.length > bound) error = `The ${f} can be at most ${num(bound)} letters.`;
    else if (f === "topic" && !next && other !== undefined && blank(other)) error = "Write a topic or at least one point.";
    return { value: next, error, changed: true };
  }

  /** A reel whose notes you edited. */
  function isEdited(r) { return !!r && r.notes_by === "you"; }
  /** Anything of yours on the reel: an edit, a stale notes_edit (an older build wrote over the notes), or a version kept aside. Such a reel is never deleted or merged away without asking. */
  function hasUserData(r) { return isEdited(r) || !!r.notes_edit || Object.values(r.notes_next || {}).some(Boolean); }

  /**
   * Puts what you typed in one field into the reel's notes. The first edit makes the reel yours (notes_by "you") and keeps
   * who wrote the notes before; the AI's text of the field is kept once, for "Use the AI text". The reel counts as done,
   * its retry fields go (as a success does), and notes_at moves so the screenshots' tags are read again.
   * False when nothing was applied: not an editable field, not changed, or not allowed (see cleanField). `now` is a time in ms.
   */
  function applyEdit(r, f, value, now) {
    if (!EDITABLE.includes(f)) return false;
    const had = r.notes, n = had || {};
    const c = cleanField(f, value, n[f], f === "topic" ? n.points || [] : f === "points" ? n.topic || "" : undefined);
    if (c.error || !c.changed) return false;
    if (!had) r.notes = { topic: "", intent: "", tone: "", points: [], meaning: "", use: [], tools: [], takeaway: "", tags: [] };
    if (!isEdited(r)) {  // the first edit; a stale notes_edit is replaced
      r.notes_edit = { was_by: had ? r.notes_by || "" : "", at: now, fields: [], ai: {} };
      r.notes_by = "you";
    }
    const e = r.notes_edit;
    if (e.was_by && !(f in e.ai)) e.ai[f] = copy(r.notes[f]);
    if (!e.fields.includes(f)) e.fields.push(f);
    r.notes[f] = c.value;
    if (f === "points") delete r.notes.unbacked;  // "N lines were left out" is about the AI's points, not yours
    r.notes_at = now;
    r.status = "done";
    r.error = "";
    delete r.tries; delete r.next_try_at; delete r.last_fail; delete r.last_fail_at;
    return true;
  }

  /** Puts the AI's text back in one edited field. Reverting the last edited field gives the notes back to whoever wrote them (notes_by = was_by) and drops notes_edit. False when that field was not edited or has no AI text. */
  function revertField(r, f) {
    const e = r.notes_edit;
    if (!isEdited(r) || !e || !(e.fields || []).includes(f) || !e.ai || !(f in e.ai)) return false;
    r.notes[f] = copy(e.ai[f]);
    e.fields = e.fields.filter((x) => x !== f);
    delete e.ai[f];
    r.notes_at = Date.now();
    if (!e.fields.length) { r.notes_by = e.was_by; delete r.notes_edit; }
    return true;
  }

  // ---------------------------------------------------------------- YouTube: title, description, transcript (no key, no login)

  function ytId(r) { return String(r.code || "").replace(/^yt-/, ""); }
  function ytWatchUrl(r) { return `https://www.youtube.com/watch?v=${ytId(r)}`; }
  function ytKey(html) { const m = String(html || "").match(/"INNERTUBE_API_KEY":\s*"([a-zA-Z0-9_-]+)"/); return m ? m[1] : ""; }
  function ytPlayerUrl(key) { return `https://www.youtube.com/youtubei/v1/player${key ? "?key=" + key : ""}`; }

  // YouTube's own apps, tried in this order. When YouTube blocks one (no captions, an empty caption file, a bot check),
  // the next one is tried. The phone sends the matching app name (LocalBridge.postYoutube); no account, no cookies.
  const YT_CLIENTS = [
    { id: "ios", name: "IOS", version: "20.10.38", extra: { deviceMake: "Apple", deviceModel: "iPhone16,2", osName: "iPhone", osVersion: "17.5.1.21F90" } },
    { id: "android", name: "ANDROID", version: "20.10.38", extra: { androidSdkVersion: 34, osName: "Android", osVersion: "14" } },
  ];
  function ytPlayerBody(r, client = YT_CLIENTS[1], lang = "en") {
    const c = typeof client === "string" ? YT_CLIENTS.find((x) => x.id === client) || YT_CLIENTS[1] : client;
    return JSON.stringify({ context: { client: { clientName: c.name, clientVersion: c.version, hl: lang || "en", ...(c.extra || {}) } },
      videoId: ytId(r), contentCheckOk: true, racyCheckOk: true });
  }

  /** A JSON object written into a page's script after `marker` (balanced braces, strings respected). null if none. */
  function jsonAfter(html, marker) {
    const s = String(html || "");
    const at = s.indexOf(marker);
    if (at < 0) return null;
    const start = s.indexOf("{", at + marker.length);
    if (start < 0 || start - at - marker.length > 20) return null;
    let depth = 0;
    let str = false;
    for (let i = start; i < s.length && i - start < 3e6; i++) {
      const ch = s[i];
      if (str) { if (ch === "\\") i++; else if (ch === '"') str = false; continue; }
      if (ch === '"') str = true;
      else if (ch === "{") depth++;
      else if (ch === "}" && --depth === 0) { try { return JSON.parse(s.slice(start, i + 1)); } catch (e) { return null; } }
    }
    return null;
  }

  /** What the watch page itself carries: {key, version, visitor, player, transcriptParams}. */
  function ytPage(html) {
    const s = String(html || "");
    const get = (rx) => { const m = s.match(rx); return m ? m[1] : ""; };
    let params = get(/"getTranscriptEndpoint":\s*\{\s*"params":\s*"([^"]+)"/);
    try { params = decodeURIComponent(params); } catch (e) { /* keep as it is */ }
    return {
      key: ytKey(s),
      version: get(/"INNERTUBE_CONTEXT_CLIENT_VERSION":\s*"([\d.]+)"/) || get(/"clientVersion":\s*"(2\.[\d.]+)"/),
      visitor: get(/"VISITOR_DATA":\s*"([^"]+)"/),
      player: jsonAfter(s, "ytInitialPlayerResponse = ") || jsonAfter(s, "ytInitialPlayerResponse="),
      transcriptParams: params,
    };
  }

  /**
   * From a player answer: {title, author, description, track, language, translated, original, why}.
   * pref "en": an English track, else another language translated to English by YouTube (original kept as a fallback).
   * pref "orig": the language the video is spoken in.
   */
  function ytPick(json, pref = "en") {
    let j = json;
    if (typeof j === "string") { try { j = JSON.parse(j); } catch (e) { return { why: "YouTube sent an answer that could not be read" }; } }
    const out = {};
    const v = (j && j.videoDetails) || {};
    if (v.title) out.title = String(v.title);
    if (v.author) out.author = String(v.author);
    if (v.shortDescription) out.description = String(v.shortDescription);
    const st = (j && j.playabilityStatus) || {};
    if (st.status && st.status !== "OK") {
      out.why = `YouTube: ${st.reason || st.status}`;
      if (/LOGIN_REQUIRED/.test(st.status) || /bot|sign in/i.test(st.reason || "")) out.botCheck = true;
    }
    const tracks = ((((j || {}).captions || {}).playerCaptionsTracklistRenderer || {}).captionTracks || []).filter((t) => t && t.baseUrl);
    if (!tracks.length) { if (!out.why) out.why = "This video has no captions"; return out; }
    const spoken = (tracks.find((t) => t.kind === "asr") || {}).languageCode || "";  // auto captions are in the spoken language
    const lang = (t) => String(t.languageCode || "");
    const score = (t) => (pref === "orig" ? (spoken && lang(t) === spoken ? 4 : 0) : (/^en/.test(lang(t)) ? 4 : 0)) +
      (t.kind === "asr" ? 0 : 1) + (lang(t) === spoken ? 0.5 : 0);
    const best = tracks.slice().sort((a, b) => score(b) - score(a))[0];
    const url = (t) => String(t.baseUrl).replace(/&fmt=[a-z0-9]+/g, "");
    out.track = url(best);
    out.language = lang(best);
    if (String(best.baseUrl).includes("&exp=xpe")) out.blocked = true;  // may come back empty; it is still tried
    if (pref !== "orig" && !/^en/.test(lang(best)) && best.isTranslatable !== false) {
      out.original = out.track;
      out.track += "&tlang=en";
      out.translated = true;
    }
    return out;
  }

  function unescapeHtml(s) {
    const d = document.createElement("textarea");
    d.innerHTML = s || "";  // captions are HTML-escaped twice; a textarea only decodes, never runs anything
    return d.value.replace(/<[^>]*>/g, "").replace(/\s+/g, " ").trim();
  }

  /**
   * A caption file (XML in any of YouTube's formats, or json3) to plain text. Auto captions often have no full stops:
   * then a new line starts at each pause (or every 30 words), so the notes can still pick out sentences.
   */
  function ytCaptions(file) {
    const s = String(file || "").trim();
    let cues = [];
    if (s.startsWith("{")) {
      try {
        for (const e of JSON.parse(s).events || []) {
          const t = (e.segs || []).map((x) => x.utf8 || "").join("");
          if (t.trim()) cues.push({ t: (e.tStartMs || 0) / 1000, d: (e.dDurationMs || 0) / 1000, text: t.replace(/\s+/g, " ").trim() });
        }
      } catch (e) { return ""; }
    } else {
      const doc = new DOMParser().parseFromString(s, "text/xml");
      if (doc.querySelector("parsererror")) return "";
      cues = [...doc.querySelectorAll("text, p")].map((e) => {
        const ms = e.tagName === "p";
        const t = parseFloat(e.getAttribute(ms ? "t" : "start")) || 0;
        const d = parseFloat(e.getAttribute(ms ? "d" : "dur")) || 0;
        return { t: ms ? t / 1000 : t, d: ms ? d / 1000 : d, text: unescapeHtml(e.textContent) };
      }).filter((c) => c.text);
    }
    return joinCues(cues);
  }

  function joinCues(cues) {
    const all = cues.map((c) => c.text).join(" ");
    const wordsN = all.split(/\s+/).filter(Boolean).length;
    const stops = (all.match(/[.!?](?:\s|$)/g) || []).length;
    if (!wordsN) return "";
    if (stops * 40 >= wordsN) return all.replace(/\s+/g, " ").replace(/\s+([.,!?])/g, "$1").trim();
    const out = [];
    let line = [];
    let n = 0;
    cues.forEach((c, i) => {
      line.push(c.text);
      n += c.text.split(/\s+/).length;
      const next = cues[i + 1];
      const gap = next ? next.t - (c.t + c.d) : 1;
      if (gap >= 0.6 || n >= 30 || /[.!?]$/.test(c.text)) { out.push(line.join(" ")); line = []; n = 0; }
    });
    if (line.length) out.push(line.join(" "));
    return out.map((l) => l.replace(/\s+/g, " ").trim()).filter(Boolean).join("\n");
  }

  /** The web "Show transcript" request (last resort, uses the watch page's own values). */
  function ytTranscriptBody(page, lang = "en") {
    return JSON.stringify({ context: { client: { clientName: "WEB", clientVersion: page.version || "2.20251101.01.00", hl: lang || "en",
      visitorData: page.visitor || undefined } }, params: page.transcriptParams });
  }
  function ytTranscriptUrl(key) { return `https://www.youtube.com/youtubei/v1/get_transcript${key ? "?key=" + key : ""}`; }
  /** The "Show transcript" answer to plain text. */
  function ytTranscriptText(json) {
    let j = json;
    if (typeof j === "string") { try { j = JSON.parse(j); } catch (e) { return ""; } }
    const cues = [];
    const walk = (o) => {
      if (Array.isArray(o)) { o.forEach(walk); return; }
      if (!o || typeof o !== "object") return;
      const seg = o.transcriptSegmentRenderer;
      if (seg) {
        const text = ((seg.snippet || {}).runs || []).map((x) => x.text || "").join("") || (seg.snippet || {}).simpleText || "";
        const t = (+seg.startMs || 0) / 1000;
        if (text.trim()) cues.push({ t, d: Math.max(0, (+seg.endMs || 0) / 1000 - t), text: text.replace(/\s+/g, " ").trim() });
        return;
      }
      Object.values(o).forEach(walk);
    };
    walk(j);
    return joinCues(cues);
  }

  /** A long transcript cut to fit the phone AI: the most informative sentences, kept in their order. */
  function condense(text, max) {
    const s = String(text || "");
    if (s.length <= max) return s;
    const sents = sentences(s);
    const freq = new Map();
    for (const w of words(s)) freq.set(w, (freq.get(w) || 0) + 1);
    const ranked = sents.map((x, i) => ({ x, i, v: words(x).reduce((a, w) => a + Math.log(1 + (freq.get(w) || 0)), 0) / Math.sqrt(words(x).length || 1) }));
    const keep = new Set();
    let len = 0;
    for (const r of ranked.slice().sort((a, b) => b.v - a.v)) {
      if (len + r.x.length + 1 > max) continue;
      keep.add(r.i);
      len += r.x.length + 1;
    }
    // no sentence short enough (a text with no sentence end or line break, or only tiny lines): its start, cut at a word
    return ranked.filter((r) => keep.has(r.i)).map((r) => r.x).join("\n") || cutStart(s, (a, o, n) => n + SHORT.length <= max) || plainStart(s, max).trim();
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

  /** Keeps only the points (and recipe lines and products) the reel itself backs up: each has to share real words with
   *  what the reel shows or says (caption, text on screen, speech, comments). Short ones need one shared word, longer
   *  ones two. With too little reel text to judge (under 30 letters), nothing is dropped. Returns how many were left out. */
  function keepBacked(notes, reel) {
    const text = ["title", "caption", "transcript", "onscreen", "comments", "extra"].map((k) => reel[k] || "").join(" ").replace(/#\S+/g, "");
    if (!notes || text.trim().length < 30) return 0;
    const have = new Set(words(text));
    const backed = (p) => {
      const own = [...new Set(words(p))];
      const shared = own.filter((w) => have.has(w)).length;
      return shared >= (own.length <= 3 ? 1 : 2);
    };
    let left = 0;
    for (const k of ["points", "ingredients", "steps", "products"]) {
      if (!notes[k]) continue;
      const before = notes[k].length;
      notes[k] = notes[k].filter(backed);
      left += before - notes[k].length;
      if (k !== "points" && !notes[k].length) delete notes[k];
    }
    notes.unbacked = left;
    return left;
  }

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
      [n.meaning, 1], [(n.use || []).join(" "), 1], [n.takeaway, 1.5], [r.caption, 0.6], [r.transcript, 0.4], [r.onscreen, 0.5], [r.extra, 0.6],
      [(r.collections || []).join(" "), 1], [(r.keywords || []).join(" "), 1.5], [r.author, 0.5]];
  }
  // Each reel's words are kept until its text changes, and the whole index until any reel changes,
  // so typing in a search box or opening a reel does not re-read the library every time.
  const docCache = new WeakMap();
  let lastIx = null;
  function sameTexts(texts, f) {
    for (let i = 0; i < texts.length; i++) if (texts[i] !== (f[i][0] || "")) return false;
    return true;
  }
  function docOf(r) {
    const f = fieldsOf(r);
    const hit = docCache.get(r);
    // the fields' texts are compared one by one (the same strings are not copied or joined again: that was most of a warm call)
    if (hit && sameTexts(hit.texts, f)) return hit.d;
    const tf = new Map();
    let len = 0;
    for (const [text, w] of f) for (const t of words(text)) { tf.set(t, (tf.get(t) || 0) + w); len += w; }
    const d = { r, tf, len, g: null };
    docCache.set(r, { texts: f.map((x) => x[0] || ""), d });
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

  // Small things worked out once for one version of the index (Notes.index gives the same object until a reel changes).
  const perIx = new WeakMap();
  function cacheOf(ix) {
    let c = perIx.get(ix);
    if (!c) { c = { expand: new Map(), rel: null }; perIx.set(ix, c); }
    return c;
  }

  /** What a question word also matches in this library: longer words that start with it, its typos, and its synonyms (each at a lower weight). */
  function expandOf(ix, t) {
    const kept = cacheOf(ix).expand;
    let m = kept.get(t);
    if (m) return m;
    m = new Map([[t, 1]]);
    for (const k of ix.df.keys()) {
      if (m.has(k)) continue;
      if (t.length >= 4 && (k.startsWith(t) || (k.length >= 4 && t.startsWith(k)))) m.set(k, 0.7);
      else if (near(t, k)) m.set(k, 0.6);
    }
    for (const s of synonyms(t)) if (!m.has(s)) m.set(s, 0.5);
    if (kept.size >= 200) kept.clear();
    kept.set(t, m);
    return m;
  }

  /** The lines of a reel that answer the question: those with most of the matching words, three at most. */
  function linesOf(r, want) {
    const n = r.notes || {};
    const cands = [...(n.points || []), n.takeaway, n.meaning, ...(n.use || [])].filter(Boolean);
    if (!cands.length) cands.push(...sentences([r.transcript, r.caption, r.onscreen, r.extra].filter(Boolean).join("\n")));
    return cands.map((l) => ({ l, k: new Set(words(l).filter((w) => want.has(w))).size }))
      .filter((x) => x.k).sort((a, b) => b.k - a.k).slice(0, 3).map((x) => x.l);
  }

  /** Ranks reels for a question, like a small search engine. [{reel, score, lines}]
   *  accept(reel), when given, keeps only the reels it says yes to; the cut to `limit` comes after it. The lines are only
   *  worked out for the reels that are returned (in a library of thousands a common word matches most reels). */
  function search(reels, query, limit = 20, accept = null) {
    const q = [...new Set(words(query))];
    if (!q.length) return [];
    const ix = index(reels);
    const expand = q.map((t) => expandOf(ix, t));
    const weighed = expand.map((m) => [...m].map(([k, w]) => [k, w * idfOf(ix, k)]));  // each word's weight times its rarity, once
    const scored = [];
    for (const d of ix.docs) {
      const lenNorm = 0.25 + 0.75 * (d.len / ix.avg);
      let s = 0;
      let matched = 0;
      for (const list of weighed) {
        let best = 0;
        for (const [k, wi] of list) {
          const f = d.tf.get(k);
          if (!f) continue;
          const v = wi * ((f * 2.2) / (f + 1.2 * lenNorm));
          if (v > best) best = v;
        }
        if (best) { matched++; s += best; }
      }
      if (!s) continue;
      s *= 0.5 + matched / q.length;  // reels that match more of the question come first
      scored.push({ d, s });
    }
    scored.sort((a, b) => b.s - a.s);
    const want = new Set(expand.flatMap((m) => [...m.keys()]));
    const out = [];
    for (const { d, s } of scored) {
      if (out.length >= limit) break;
      if (accept && !accept(d.r)) continue;
      out.push({ reel: d.r, score: s, lines: linesOf(d.r, want) });
    }
    return out;
  }

  // the synonym groups each word is in (ascending), and how often each group occurs in a reel (kept with the reel's words)
  const SYN_OF = new Map();
  SYN.forEach((g, i) => { for (const w of g) { const a = SYN_OF.get(w); if (!a) SYN_OF.set(w, [i]); else if (a[a.length - 1] !== i) a.push(i); } });
  const GKEY = SYN.map((_, i) => "~" + i);
  function groupsOf(d) {
    if (d.g) return d.g;
    const g = new Map();
    for (const [t, f] of d.tf) { const a = SYN_OF.get(t); if (a) for (const i of a) g.set(GKEY[i], (g.get(GKEY[i]) || 0) + f); }
    d.g = g;
    return g;
  }
  /** For one index version: how rare each synonym group is, and each reel's vector length (worked out when first needed). */
  function relatedState(ix) {
    const c = cacheOf(ix);
    if (c.rel) return c.rel;
    const gdf = new Map();
    for (const d of ix.docs) for (const k of groupsOf(d).keys()) gdf.set(k, (gdf.get(k) || 0) + 1);
    const gl = new Map();
    for (const [k, n] of gdf) gl.set(k, Math.log(1 + (ix.N - n + 0.5) / (n + 0.5)));
    c.rel = { gl, norms: new Float64Array(ix.docs.length) };
    return c.rel;
  }

  /** Reels about the same thing (TF-IDF vectors, cosine similarity). [{reel, score}] */
  function related(reels, target, limit = 5) {
    const ix = index(reels);
    const me = ix.docs.find((d) => d.r === target);
    if (!me || !me.tf.size) return [];
    const { gl, norms } = relatedState(ix);
    // words plus their synonym groups (so "password" and "API key" reels are related), each weighted by rarity
    const termX = (f, idf) => (1 + Math.log(f)) * idf;
    const groupX = (f, l) => 0.7 * (1 + Math.log(f)) * l;
    const normOf = (d) => {
      let norm = 0;
      for (const [t, f] of d.tf) { const x = termX(f, idfOf(ix, t)); norm += x * x; }
      for (const [k, f] of groupsOf(d)) { const x = groupX(f, gl.get(k)); norm += x * x; }
      return Math.sqrt(norm) || 1;
    };
    const aT = [], aX = [], aI = [], aG = [], aGX = [], aL = [];
    for (const [t, f] of me.tf) { const idf = idfOf(ix, t); aT.push(t); aI.push(idf); aX.push(termX(f, idf)); }
    for (const [k, f] of groupsOf(me)) { const l = gl.get(k); aG.push(k); aL.push(l); aGX.push(groupX(f, l)); }
    const normA = normOf(me);
    const out = [];
    for (let i = 0; i < ix.docs.length; i++) {
      const d = ix.docs[i];
      if (d === me || !d.tf.size) continue;
      let dot = 0;
      for (let j = 0; j < aT.length; j++) { const f = d.tf.get(aT[j]); if (f) { const y = termX(f, aI[j]); if (y) dot += aX[j] * y; } }
      const g = groupsOf(d);
      for (let j = 0; j < aG.length; j++) { const f = g.get(aG[j]); if (f) { const y = groupX(f, aL[j]); if (y) dot += aGX[j] * y; } }
      const normB = norms[i] || (norms[i] = normOf(d));
      const score = dot / (normA * normB);
      if (score > 0.05) out.push({ reel: d.r, score });
    }
    return out.sort((x, y) => y.score - x.score).slice(0, limit);
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
    const text = [r.title, r.extra, r.transcript, r.caption, r.onscreen].filter(Boolean).join("\n");
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

  // ---------------------------------------------------------------- the Ask prompts, and their budget
  // What the phone's AI is told besides the prompt (LocalModel's system text): counted in the budget, so the page uses these.
  const ASK_SYSTEM = "You answer only from the notes you are given, briefly, citing them like [1].";
  const WEB_ASK_SYSTEM = "You answer only from the notes and web results you are given, briefly, citing them like [1] or [W1].";

  /** The note as the Ask prompts show it: its number and its notes (a reel with no notes: the start of its caption). */
  const askNote = (x, i) => `[${i + 1}] ${format(x.reel.notes || {}) || (x.reel.caption || "").slice(0, 800)}`;

  const askText = (question, notes) =>
    `Answer my question using only my notes below (from reels I watched). Be specific: give the steps, names, numbers ` +
    `and tools from the notes. After each fact, write the note number like [1]. If the notes do not answer it, say so.\n\n` +
    `Question: ${question}\n\nMy notes:\n\n${notes.join("\n\n")}`;

  const webAskText = (question, notes, found) =>
    `Answer my question briefly and accurately. Use my notes first; use the web results only for what my notes do not ` +
    `cover. After each fact, write where it came from, like [1] or [W1]. A fact from the web needs two web results that both ` +
    `say it: cite both, like [W1][W2]. If only one says it, still cite it. If neither answers it, say so; do not guess.\n\n` +
    `Question: ${question}\n\n${notes.length ? `My notes:\n\n${notes.join("\n\n")}\n\n` : ""}Web results:\n\n${found.join("\n\n")}`;

  /** Fills an Ask prompt for `budget` tokens (no budget: no limit). `build(question, notes, found)` makes the text from the question,
   *  the notes ("[1] ...") and the web results ("[W1] ..."). A prompt that already fits is built whole, exactly as it was before
   *  there was a budget. Otherwise the instructions are kept; the question is cut (at a word, ending " [shortened]") only when it does
   *  not fit with them; then the notes go in WHOLE, in the order given (best match first), while the next one fits (a note that does
   *  not fit whole is left out, and so are all after it, so the numbers [1].. stay those of the screen); then the web results the same
   *  way in what is left. Nothing is cut in the middle. When not even a word of the question fits, it is kept whole. */
  function askFill(build, question, notes, found, budget) {
    const limit = Number.isFinite(budget) ? budget : Infinity;
    const full = build(question, notes, found);
    const done = (q, n, w) => ({ prompt: n === notes.length && w === found.length && q === question ? full : build(q, notes.slice(0, n), found.slice(0, w)),
      used: n, total: notes.length, webUsed: w, webTotal: found.length, questionCut: q !== question });
    if (!(estTokens(full) > limit)) return done(question, notes.length, found.length);
    let q = question;
    if (estTokens(build(q, [], [])) > limit) {
      const [ba, bo] = counts(build("", [], [])), [ma, mo] = counts(SHORT);
      q = cutStart(question, (a, o) => tokensOf(ba + ma + a, bo + mo + o) <= limit) || question;
    }
    let n = 0, w = 0;
    while (n < notes.length && !(estTokens(build(q, notes.slice(0, n + 1), [])) > limit)) n++;
    while (w < found.length && !(estTokens(build(q, notes.slice(0, n), found.slice(0, w + 1))) > limit)) w++;
    return done(q, n, w);
  }

  /** A question answered only from your own notes, citing them as [1], [2]... With `opts.budget` (tokens) the prompt and what went in. */
  function answerPromptInfo(question, results, opts = {}) {
    return askFill((q, notes) => askText(q, notes), question, results.map(askNote), [], opts.budget);
  }
  function answerPrompt(question, results) { return answerPromptInfo(question, results).prompt; }

  /** The question with your notes [1].. and what the web lookup found [W1].. (Wikipedia, DuckDuckGo). */
  function webAnswerPromptInfo(question, results, web, opts = {}) {
    return askFill(webAskText, question, results.map(askNote), web.map((w, i) => `[W${i + 1}] ${w.title} (${w.source}): ${w.text}`), opts.budget);
  }
  function webAnswerPrompt(question, results, web) { return webAnswerPromptInfo(question, results, web).prompt; }

  /** Each sentence of a web answer that rests on a single web page (one [Wn], no note [n]) is marked "(one source)". */
  function markOneSource(text, web) {
    return String(text || "").replace(/[^.!?\n]*\[W\d{1,2}\][^.!?\n]*[.!?]?/g, (s) => {
      if (/\[\d{1,2}\]/.test(s) || /\(one source\)/.test(s)) return s;
      const pages = new Set((s.match(/\[W(\d{1,2})\]/g) || []).map((m) => { const w = (web || [])[Number(m.slice(2, -1)) - 1]; return w ? w.url || w.title : m; }));
      if (pages.size >= 2) return s;
      const end = s.match(/[.!?]?\s*$/)[0];
      return s.slice(0, s.length - end.length) + " (one source)" + end;
    });
  }

  // ---------------------------------------------------------------- reading a reel's public page (caption, creator)

  function embedUrl(code) { return `https://www.instagram.com/p/${code}/embed/captioned/`; }

  /** Caption and creator from the embed page, or from the page's description tags. {} when there is nothing. */
  function readPage(html) {
    const doc = new DOMParser().parseFromString(String(html || ""), "text/html");  // inert: nothing in it runs
    const out = {};
    doc.querySelectorAll("script, style, noscript, template").forEach((x) => x.remove());
    // the reel's video file, when Instagram puts it in the page for logged-out visitors
    const raw = String(html || "");
    const vm = raw.match(/\\?"video_url\\?"\s*:\s*\\?"(https:[^"\\]*(?:\\.[^"\\]*)*)/) || raw.match(/<video[^>]+src="(https:[^"]+)"/);
    if (vm) {
      const u = vm[1].replace(/\\u0026/g, "&").replace(/\\\//g, "/").replace(/\\/g, "").replace(/&amp;/g, "&");
      if (/^https:\/\/[^/]+\.(cdninstagram\.com|fbcdn\.net)\//.test(u)) out.video = u;
    }
    const img = doc.querySelector("img.EmbeddedMediaImage, .EmbeddedMedia img");
    if (img) {
      const src = img.getAttribute("src") || "";
      if (/^https:\/\/[^/]+\.(cdninstagram\.com|fbcdn\.net)\//.test(src)) out.cover = src;
      const alt = clean(img.getAttribute("alt") || "");
      // Instagram's own picture description: "Photo by X on May 1, 2024. May be an image of text that says '...'"
      const said = alt.match(/may be (?:an? )?(?:image|graphic|video|meme)[^.]*?(?:that says|with the text)\s*['"“‘]([\s\S]+?)['"”’]\s*\.?\s*$/i);
      if (said) out.alt = said[1].trim();
    }
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

  /** An Instagram username, not one of the export's own labels ("Media", "Saved on", "Owner"...). */
  const LABELS = /^(media|saved ?on|saved|owner|author|username|user|url|uri|href|link|title|name|value|timestamp|data|string_map_data|label_values|posts?|reels?|collection)$/i;
  function username(t) {
    const u = String(t || "").trim().replace(/^@/, "");
    return /^[A-Za-z0-9._]{1,30}$/.test(u) && !LABELS.test(u) ? u : "";
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
        // the creator: an entry's "title" in the old export, a "Username"/"Owner" label in the newer one
        let t = username(node.title) || title;
        for (const lv of Array.isArray(node.label_values) ? node.label_values : []) {
          if (lv && /user ?name|owner|author/i.test(String(lv.label || "")) && username(lv.value)) t = username(lv.value);
        }
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
    let cdSize = u32(tail, eocd + 12);
    let cdOff = u32(tail, eocd + 16);
    const u64 = (b, o) => u32(b, o) + u32(b, o + 4) * 4294967296;
    if (cdOff === 0xffffffff || cdSize === 0xffffffff) {  // ZIP64 (big exports): the real numbers sit in the ZIP64 record
      const loc = eocd - 20;
      if (loc < 0 || u32(tail, loc) !== 0x07064b50) throw new Error("This ZIP could not be read. Unzip it and choose saved_posts.json and saved_collections.json");
      const recOff = u64(tail, loc + 8);
      const rec = await bytes(recOff, recOff + 56);
      if (u32(rec, 0) !== 0x06064b50) throw new Error("This ZIP could not be read. Unzip it and choose saved_posts.json and saved_collections.json");
      cdSize = u64(rec, 40);
      cdOff = u64(rec, 48);
    }
    if (cdSize > 200e6) throw new Error("This ZIP's table of contents is too big. Ask Instagram for only Saved");
    const cd = await bytes(cdOff, cdOff + cdSize);
    const out = [];
    let p = 0;
    while (p + 46 <= cd.length && u32(cd, p) === 0x02014b50) {
      const method = u16(cd, p + 10);
      let csize = u32(cd, p + 20);
      let usize = u32(cd, p + 24);
      const nlen = u16(cd, p + 28);
      const elen = u16(cd, p + 30);
      const clen = u16(cd, p + 32);
      let loff = u32(cd, p + 42);
      const name = new TextDecoder().decode(cd.subarray(p + 46, p + 46 + nlen));
      // ZIP64 extra field: the sizes and offset that did not fit, in this order, only for those set to 0xffffffff
      for (let x = p + 46 + nlen, xe = x + elen; x + 4 <= xe;) {
        const id = u16(cd, x);
        const sz = u16(cd, x + 2);
        if (id === 1) {
          let q = x + 4;
          if (usize === 0xffffffff) { usize = u64(cd, q); q += 8; }
          if (csize === 0xffffffff) { csize = u64(cd, q); q += 8; }
          if (loff === 0xffffffff) { loff = u64(cd, q); q += 8; }
        }
        x += 4 + sz;
      }
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

  // ---------------------------------------------------------------- useful or fun (keywords, no AI)
  const USEFUL = /\b(how to|how i|tips?|steps?|guide|tutorial|learn|lesson|explained?|hack|tool|app|website|free|ai|chatgpt|code|coding|python|excel|money|invest|finance|budget|career|interview|resume|job|business|marketing|health|workout|exercise|diet|protein|recipe|study|productiv\w*|habit|mistakes?|avoid|don'?t|should|must|best way|secret|framework|checklist|save this|bookmark|book|course|skill|science|fact|psychology|mindset|advice|lifehack|setup|settings|feature|shortcut|prompt|security|privacy)\b|\b\d+\s+(ways|things|tips|steps|tools|apps|books|mistakes|habits|rules)\b|^\s*\d+[.)]\s/gim;
  const FUN = /\b(lol|lmao|haha+|funny|meme|memes|prank|relatable|pov|comedy|comedian|joke|jokes|skit|dance|dancing|vibe|vibes|trend|trending|song|music|edit|edits|fyp|cute|aesthetic|bestie|couple|crush|savage|cringe|roast|fail|fails)\b|😂|🤣|💀|😭/gi;
  /** "useful" (advice, how-to, facts, tools) or "fun" (jokes, memes, music, edits) from the caption and text, no AI. */
  function reelKind(r) {
    const t = [r.caption, r.onscreen, r.transcript, (r.collections || []).join(" ")].filter(Boolean).join("\n");
    if (!t.trim()) return "useful";  // nothing to go on: read it to find out
    const u = (t.match(USEFUL) || []).length;
    const f = (t.match(FUN) || []).length;
    return f > u ? "fun" : "useful";
  }

  // ---------------------------------------------------------------- comments (from your screenshots)
  const COMMENT_NOISE = /^(reply|replies|see translation|view \d+ more repl\w*|view replies.*|hide replies|liked by.*|add a comment.*|comments?|\d+[smhdw]|\d+\s*(likes?|replies)|author|pinned|edited|top comments?|newest|for you)$/i;
  /** Is this text an Instagram comment screen? */
  function isCommentScreen(lines) {
    const t = lines.join("\n");
    return (/(^|\n)\s*comments?\s*($|\n)/i.test(t) || /add a comment/i.test(t)) && (t.match(/(^|\n)\s*reply\s*($|\n)/gi) || []).length >= 2;
  }
  /** The comments themselves from a comment screen's lines (buttons, times and counts dropped). */
  function commentLines(lines) {
    return lines.map((l) => String(l).trim()).filter((l) => l.length > 2 && !COMMENT_NOISE.test(l) && !/^\d+[smhdw]\b/.test(l) && !/^@?[a-z0-9_.]{3,30}$/i.test(l));
  }

  return { keepBacked, username, reelKind, isCommentScreen, commentLines, FORMAT, META_PROMPT, LOCAL_SYSTEM, links, isYoutube, parse, splitAnswers, format, metaPrompt, batchPrompt, localPrompt, localPromptInfo, estTokens, promptBudget, material, RETRY_CAP, retryAfter, embedUrl, readPage,
    ytWatchUrl, ytKey, ytPlayerUrl, ytPlayerBody, ytPick, ytCaptions, ytPage, ytTranscriptBody, ytTranscriptUrl, ytTranscriptText,
    YT_CLIENTS, condense, search, answerPrompt, answerPromptInfo, webAnswerPrompt, webAnswerPromptInfo, ASK_SYSTEM, WEB_ASK_SYSTEM, markOneSource, words, stem, near, related, keywords, autoNotes, sentences, index, idfOf, tokens, synonyms, fieldsOf,
    exportRows, exportJson, exportMarkdown, exportFile, readZip, KEYS, cleanField, applyEdit, revertField, isEdited, hasUserData };
})();
