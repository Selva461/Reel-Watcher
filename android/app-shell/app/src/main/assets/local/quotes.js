/* Reel Shelf: quotes kept from your screenshots (movie and series lines, sayings, anything worth keeping).
   When a screenshot is read (Process, Overnight run or the nightly run), its text is split into sentences and the
   ones that read like a quote are kept: quoted text first, otherwise full sentences of 5 to 60 words that are not app
   buttons, counts, times or links. If the screenshot also names a title, the quote is filed under it.
   Plain rules, no AI. Stored in the library file as db.quotes: [{id, text, from, src, at}]. */
"use strict";

const Quotes = (() => {
  const NOISE = /(https?:\/\/|www\.|@\w|#\w|\b\d{1,2}:\d{2}\b|\b\d+(\.\d+)?\s?[kKmM]?\s?(likes?|views?|followers?|following|comments?|replies|shares?)\b|\b(reply|follow|subscribe|see translation|view all|add a comment|liked by|sponsored|original audio|send message|tap to)\b|%)/i;
  const fold = (s) => String(s || "").toLowerCase().normalize("NFKD").replace(/[̀-ͯ]/g, "").replace(/[^\p{L}\p{N} ]/gu, " ").replace(/\s+/g, " ").trim();

  function words(s) { return String(s).trim().split(/\s+/).filter(Boolean); }

  /** Does this read like a sentence somebody said or wrote (not an app button, a count or a name)? */
  function sentenceLike(s) {
    const w = words(s);
    if (w.length < 5 || w.length > 60 || NOISE.test(s)) return false;
    const letters = (s.match(/\p{L}/gu) || []).length;
    if (letters < s.replace(/\s/g, "").length * 0.75) return false;           // mostly letters, not numbers or symbols
    const lower = w.filter((x) => /^\p{Ll}/u.test(x)).length;
    return lower >= w.length * 0.4;                                             // not a list of names or a title card
  }

  /** The quotes in one screenshot's text (lines as read on the phone). Best first, at most 3. */
  function pick(text) {
    const lines = String(text || "").split(/\n+/).map((l) => l.trim()).filter(Boolean);
    const out = [];
    const seen = new Set();
    const keep = (q, quoted) => {
      q = q.replace(/\s+/g, " ").replace(/^[-–•*\s]+/, "").trim();
      const k = fold(q);
      if (!k || seen.has(k) || [...seen].some((x) => k.includes(x) || x.includes(k)) || !(quoted ? words(q).length >= 3 && words(q).length <= 60 && !NOISE.test(q) : sentenceLike(q))) return;
      seen.add(k);
      out.push(q);
    };
    // lines that run on (a sentence broken over several lines) are joined first
    const paras = [];
    for (const l of lines) {
      const prev = paras[paras.length - 1];
      if (prev && !/[.!?"”]$/.test(prev) && /^\p{Ll}/u.test(l) && !NOISE.test(l)) paras[paras.length - 1] = prev + " " + l;
      else paras.push(l);
    }
    const all = paras.join("\n");
    for (const m of all.matchAll(/[“"]([^”"\n]{12,400})[”"]/g)) keep(m[1], true);   // text in quote marks
    for (const p of paras) for (const s of p.split(/(?<=[.!?])\s+(?=[\p{Lu}"“])/u)) keep(s, false);
    return out.slice(0, 3);
  }

  /** Adds the quotes of one read screenshot to the library. Returns how many are new. */
  function addFrom(db, res, src) {
    const list = db.quotes || (db.quotes = []);
    const have = new Set(list.map((q) => fold(q.text)));
    const top = (res.candidates || []).find((c) => c.score >= 0.5);
    let n = 0;
    for (const t of pick(res.text)) {
      const k = fold(t);
      if (have.has(k)) continue;
      have.add(k);
      list.unshift({ id: "q" + Date.now().toString(36) + n, text: t, from: top ? top.title : "", src: src || "", at: Date.now() });
      n++;
    }
    return n;
  }

  /** Quotes containing every word you typed (accents and case ignored), most matching first. */
  function find(db, query) {
    const list = db.quotes || [];
    const q = fold(query).split(" ").filter(Boolean);
    if (!q.length) return list;
    return list.map((x) => {
      const t = fold(x.text + " " + x.from);
      return { x, hit: q.every((w) => t.includes(w)) ? q.reduce((s, w) => s + t.split(w).length - 1, 0) : 0 };
    }).filter((o) => o.hit).sort((a, b) => b.hit - a.hit).map((o) => o.x);
  }

  // ---------------------------------------------------------------- screen (#/quotes)

  let query = "";
  function screen() {
    const list = find(db, query);
    $app.innerHTML = `${header("Quotes", "#/")}
      <label class="search">${ICON.search}<input id="qq" type="search" placeholder="Search quotes" value="${esc(query)}" aria-label="Search quotes"></label>
      <p class="hint">${plural((db.quotes || []).length, "quote")} kept from your screenshots. New screenshots are read when you tap Process, and every night.</p>
      <div class="stack" id="qlist">${listHtml(list)}</div>`;
    bind("#qq", "input", (e, el) => { query = el.value; document.getElementById("qlist").innerHTML = listHtml(find(db, query)); bindList(); });
    bindList();
  }
  function listHtml(list) {
    if (!list.length) return `<div class="empty">${query ? "No quote has those words." : "No quotes yet. Read your screenshots (Start, Screenshots to watchlist) and lines worth keeping show up here."}</div>`;
    return list.slice(0, 200).map((q) => `<div class="card stack" data-q="${esc(q.id)}"><span>“${esc(q.text)}”</span>
      ${q.from ? `<span class="small muted">${esc(q.from)}</span>` : ""}
      <div class="grid2"><button class="btn" data-copy="${esc(q.id)}">Copy</button><button class="btn danger" data-del="${esc(q.id)}">Remove</button></div></div>`).join("");
  }
  function bindList() {
    const get = (id) => (db.quotes || []).find((q) => q.id === id);
    bind("[data-copy]", "click", (e, b) => { const q = get(b.dataset.copy); if (q) { sync("copy", `"${q.text}"${q.from ? " (" + q.from + ")" : ""}`); toast("Copied"); } });
    bind("[data-del]", "click", (e, b) => { db.quotes = (db.quotes || []).filter((q) => q.id !== b.dataset.del); saveDb(); screen(); });
  }

  return { pick, addFrom, find, sentenceLike, screen };
})();
