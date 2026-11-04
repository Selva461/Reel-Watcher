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

  /** Every Instagram post or reel in a text, once each, in order: [{code, url}] */
  function links(text) {
    const out = [];
    const seen = new Set();
    for (const m of String(text || "").matchAll(IG)) {
      const code = m[2];
      if (seen.has(code)) continue;
      seen.add(code);
      out.push({ code, url: `https://www.instagram.com/${m[1].toLowerCase() === "p" ? "p" : "reel"}/${code}/` });
    }
    return out;
  }

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

  function clean(s) { return String(s || "").replace(/\*\*|__|`/g, "").replace(/^\s*[*_]+|[*_]+\s*$/g, "").replace(/\s+/g, " ").trim(); }
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
        parts.push(cur.join("\n"));
        cur = [];
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
    return t.includes("{link}") ? t.split("{link}").join(link) : `${t.trim()}\n\nReel: ${link}`;
  }

  function localPrompt(reel, extra) {
    const parts = ["Here is what could be read from an Instagram reel."];
    if (reel.url) parts.push(`Link: ${reel.url}`);
    if (reel.author) parts.push(`Creator: @${reel.author}`);
    if (reel.caption) parts.push(`Caption:\n${reel.caption.slice(0, 4000)}`);
    if (reel.extra) parts.push(`What the reel says (typed by me):\n${reel.extra.slice(0, 6000)}`);
    parts.push(`Write notes in exactly this format:\n\n${FORMAT}`);
    if (extra && extra.trim()) parts.push(`Also: ${extra.trim()}`);
    return parts.join("\n\n");
  }

  /** How much there is to write notes from (the phone's AI cannot watch the video). */
  function material(reel) { return ((reel.caption || "") + " " + (reel.extra || "")).replace(/#\S+/g, "").trim().length; }

  // ---------------------------------------------------------------- reading a reel's public page (caption, creator)

  function embedUrl(code) { return `https://www.instagram.com/p/${code}/embed/captioned/`; }

  /** Caption and creator from the embed page, or from the page's description tags. {} when there is nothing. */
  function readPage(html) {
    const doc = new DOMParser().parseFromString(String(html || ""), "text/html");  // inert: nothing in it runs
    const out = {};
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

  return { FORMAT, META_PROMPT, LOCAL_SYSTEM, links, parse, splitAnswers, format, metaPrompt, localPrompt, material, embedUrl, readPage,
    exportRows, exportJson, exportMarkdown, exportFile, readZip, KEYS };
})();
