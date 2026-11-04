/* Reel Shelf (built in): the library layer on top of Notes.search. Plain maths, no AI, no screen code.
   - find: search with operators: "exact words", -leave-out, #tag
   - didYouMean: spelling fixes from the words in your own library (edit distance)
   - highlight: the words that matched, marked (the text is escaped first)
   - topics: reels grouped by what they are about (TF-IDF vectors, cosine similarity, one-pass leader clustering)
   - tools: every tool and app your reels name, counted
   Everything is worked out only when a screen asks for it and kept until the library changes. Nothing runs in the background. */
"use strict";

const Lib = (() => {
  const N = Notes;

  function fold(s) { return String(s || "").toLowerCase().normalize("NFKD").replace(/[̀-ͯ]/g, "").replace(/\s+/g, " ").trim(); }
  function escHtml(v) { return String(v == null ? "" : v).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c])); }

  // small caches, each tied to one version of the index (Notes.index returns the same object until a reel changes)
  const perIx = new WeakMap();
  function memo(ix, key, fn) {
    let m = perIx.get(ix);
    if (!m) { m = {}; perIx.set(ix, m); }
    if (!(key in m)) m[key] = fn();
    return m[key];
  }
  const textCache = new WeakMap();
  function fullText(r) {
    const sig = N.fieldsOf(r).map((x) => x[0] || "").join("\u0001");
    const hit = textCache.get(r);
    if (hit && hit.sig === sig) return hit.t;
    const t = fold(sig.replace(/\u0001/g, " "));
    textCache.set(r, { sig, t });
    return t;
  }
  function tagsOf(r) { return [...((r.notes || {}).tags || []), ...(r.keywords || [])].map((t) => fold(t).replace(/^#+/, "").replace(/\s+/g, "")); }

  // ---------------------------------------------------------------- the question

  /** "exact words", -word or -"some words" to leave out, #tag to keep only that tag; the rest is ranked. */
  function parseQuery(q) {
    const out = { words: [], phrases: [], exclude: [], tags: [] };
    String(q || "").replace(/[“”]/g, '"').replace(/(^|\s)(-?)"([^"]+)"?|(\S+)/g, (m, sp, neg, ph, w) => {
      if (ph !== undefined) { if (fold(ph)) (neg ? out.exclude : out.phrases).push(fold(ph)); return m; }
      if (/^#[\p{L}\p{N}_-]+$/u.test(w)) out.tags.push(fold(w.slice(1)));
      else if (/^-[\p{L}\p{N}]/u.test(w)) out.exclude.push(fold(w.slice(1)));
      else out.words.push(w);
      return m;
    });
    out.text = [...out.words, ...out.phrases].join(" ").trim();
    return out;
  }

  /** Ranked results for a question, with the operators applied. [{reel, score, lines}] */
  function find(reels, query, limit = 20) {
    const p = parseQuery(query);
    const ix = N.index(reels);
    const tfOf = memo(ix, "tf", () => new Map(ix.docs.map((d) => [d.r, d.tf])));
    const ok = (r) => {
      if (p.tags.length) { const t = tagsOf(r); if (!p.tags.every((x) => t.includes(x))) return false; }
      if (p.phrases.length) { const t = fullText(r); if (!p.phrases.every((x) => t.includes(x))) return false; }
      for (const x of p.exclude) {
        if (x.includes(" ")) { if (fullText(r).includes(x)) return false; continue; }
        const tf = tfOf.get(r) || new Map();
        if (N.words(x).some((w) => tf.has(w))) return false;
      }
      return true;
    };
    let hits;
    if (p.text) hits = N.search(reels, p.text, reels.length).filter((h) => ok(h.reel));
    else if (p.tags.length || p.exclude.length) hits = reels.filter(ok).map((r) => ({ reel: r, score: 0, lines: [] }));
    else return [];
    if (p.phrases.length) {  // the lines that hold the exact words come first
      for (const h of hits) {
        const n = h.reel.notes || {};
        const all = [...(n.points || []), n.takeaway, n.meaning, ...(n.use || [])].filter(Boolean);
        const exact = all.filter((l) => p.phrases.some((x) => fold(l).includes(x)));
        h.lines = [...new Set([...exact, ...h.lines])].slice(0, 3);
      }
    }
    return hits.slice(0, limit);
  }

  // ---------------------------------------------------------------- spelling

  /** Edit distance with swapped letters (optimal string alignment), stops early once it passes max. */
  function distance(a, b, max = 2) {
    if (a === b) return 0;
    if (Math.abs(a.length - b.length) > max) return max + 1;
    let prev2 = null;
    let prev = Array.from({ length: b.length + 1 }, (_, j) => j);
    for (let i = 1; i <= a.length; i++) {
      const cur = [i];
      let low = i;
      for (let j = 1; j <= b.length; j++) {
        const cost = a[i - 1] === b[j - 1] ? 0 : 1;
        let v = Math.min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + cost);
        if (prev2 && i > 1 && j > 1 && a[i - 1] === b[j - 2] && a[i - 2] === b[j - 1]) v = Math.min(v, prev2[j - 2] + 1);
        cur.push(v);
        if (v < low) low = v;
      }
      if (low > max) return max + 1;
      prev2 = prev;
      prev = cur;
    }
    return prev[b.length];
  }

  /** The word people see for each stem ("password" for "password", not "passwords"). */
  function surfaces(ix) {
    return memo(ix, "surface", () => {
      const count = new Map();
      for (const d of ix.docs) for (const [text] of N.fieldsOf(d.r)) for (const w of N.tokens(text)) {
        const k = N.stem(w);
        let m = count.get(k);
        if (!m) { m = new Map(); count.set(k, m); }
        m.set(w, (m.get(w) || 0) + 1);
      }
      const out = new Map();
      for (const [k, m] of count) out.set(k, [...m].sort((a, b) => b[1] - a[1] || a[0].length - b[0].length)[0][0]);
      return out;
    });
  }
  function shown(ix, stem) { return surfaces(ix).get(stem) || stem; }

  /** A better spelling of the question, using only words that are in your library. null when it looks right. */
  function didYouMean(reels, query) {
    const ix = N.index(reels);
    if (!ix.N) return null;
    const vocab = memo(ix, "vocab", () => [...ix.df.keys()].filter((k) => !/^~/.test(k)));
    const p = parseQuery(query);
    let changed = false;
    const fixed = p.words.map((raw) => {
      const toks = N.tokens(raw);
      if (toks.length !== 1) return raw;
      const st = N.stem(toks[0]);
      if (ix.df.has(st) || st.length < 4 || /\d/.test(st)) return raw;
      if (vocab.some((k) => k.startsWith(st))) return raw;  // still typing a longer word
      const max = st.length >= 7 ? 2 : 1;
      let best = null;
      for (const k of vocab) {
        if (Math.abs(k.length - st.length) > max) continue;
        const d = distance(st, k, max);
        if (d > max) continue;
        const df = ix.df.get(k);
        if (!best || d < best.d || (d === best.d && df > best.df)) best = { k, d, df };
      }
      if (!best) return raw;
      changed = true;
      return shown(ix, best.k);
    });
    if (!changed) return null;
    return [...fixed, ...p.phrases.map((x) => `"${x}"`), ...p.exclude.map((x) => (x.includes(" ") ? `-"${x}"` : "-" + x)), ...p.tags.map((t) => "#" + t)].join(" ");
  }

  // ---------------------------------------------------------------- marking the words that matched

  /** Escaped HTML of text with the words that answer the question in <mark>. */
  function highlight(text, query) {
    const s = String(text || "");
    const p = parseQuery(query);
    const want = [...new Set(N.words(p.text))];
    const syn = new Set(want.flatMap((t) => N.synonyms(t)));
    const hit = (k) => want.some((t) => k === t || (t.length >= 4 && k.startsWith(t)) || N.near(t, k)) || syn.has(k);
    const spans = [];
    for (const m of s.matchAll(/[\p{L}\p{N}][\p{L}\p{N}+#.-]*/gu)) {
      const w = N.words(m[0]);
      if (w.length && hit(w[0])) spans.push([m.index, m.index + m[0].replace(/[.-]+$/, "").length]);
    }
    const low = fold(s).length === s.length ? s.toLowerCase() : null;  // exact words: only when folding kept the positions
    if (low) for (const ph of p.phrases) for (let i = low.indexOf(ph); i >= 0; i = low.indexOf(ph, i + 1)) spans.push([i, i + ph.length]);
    if (!spans.length) return escHtml(s);
    spans.sort((a, b) => a[0] - b[0]);
    const merged = [];
    for (const sp of spans) { const last = merged[merged.length - 1]; if (last && sp[0] <= last[1]) last[1] = Math.max(last[1], sp[1]); else merged.push([...sp]); }
    let out = "";
    let at = 0;
    for (const [a, b] of merged) { out += escHtml(s.slice(at, a)) + "<mark>" + escHtml(s.slice(a, b)) + "</mark>"; at = b; }
    return out + escHtml(s.slice(at));
  }

  // ---------------------------------------------------------------- topics: reels that belong together

  /** Groups of reels about the same thing. [{key, label, words, reels}] biggest first, 2 reels or more. */
  function topics(reels, threshold = 0.3) {
    const ix = N.index(reels);
    return memo(ix, "topics" + threshold, () => {
      // vectors: words found in at least 2 reels but not in most of them, plus synonym groups, weighted by TF-IDF
      const common = Math.max(3, ix.N * 0.5);
      const vecs = ix.docs.map((d) => {
        const v = new Map();
        for (const [t, f] of d.tf) {
          const df = ix.df.get(t);
          if (df < 2 || df > common) continue;
          v.set(t, (1 + Math.log(f)) * N.idfOf(ix, t));
          for (const g of N.synonyms(t)) if (ix.df.has(g) && !d.tf.has(g)) v.set(g, Math.max(v.get(g) || 0, 0.5 * (1 + Math.log(f)) * N.idfOf(ix, g)));
        }
        let norm = 0;
        for (const x of v.values()) norm += x * x;
        norm = Math.sqrt(norm);
        if (norm) for (const [t, x] of v) v.set(t, x / norm);
        return v;
      });
      // one pass of leader clustering against group centres (the sum of their reels' vectors): each reel joins the
      // group it is most like (cosine similarity), or starts a new one. Dot products go through shared words only,
      // so this stays fast with thousands of reels. Then reels left alone get a second chance at the final groups.
      const cents = [];
      const byTerm = new Map();
      const closest = (v, skip) => {
        const dots = new Map();
        for (const [t, x] of v) for (const c of byTerm.get(t) || []) if (c !== skip) dots.set(c, (dots.get(c) || 0) + x * cents[c].v.get(t));
        let best = -1;
        let bs = 0;
        for (const [c, d] of dots) { const s = d / Math.sqrt(cents[c].norm2); if (s > bs || (s === bs && c < best)) { bs = s; best = c; } }
        return [best, bs];
      };
      const join = (c, i) => {
        const g = cents[c];
        g.members.push(i);
        for (const [t, x] of vecs[i]) {
          const old = g.v.get(t) || 0;
          g.v.set(t, old + x);
          g.norm2 += (old + x) * (old + x) - old * old;
          if (!byTerm.has(t)) byTerm.set(t, new Set());
          byTerm.get(t).add(c);
        }
      };
      vecs.forEach((v, i) => {
        if (!v.size) return;
        const [c, s] = closest(v, -1);
        if (c >= 0 && s >= threshold) join(c, i);
        else { cents.push({ v: new Map(), norm2: 0, members: [] }); join(cents.length - 1, i); }
      });
      for (let c = 0; c < cents.length; c++) {
        if (cents[c].members.length !== 1) continue;
        const i = cents[c].members[0];
        const [to, s] = closest(vecs[i], c);
        if (to >= 0 && cents[to].members.length > 1 && s >= threshold) { cents[c].members = []; join(to, i); }
      }
      const groups = cents.map((g) => g.members).filter((m) => m.length >= 2);
      return groups.map((members) => {
        // the label: the words that most of the group shares
        const score = new Map();
        for (const m of members) for (const [t, x] of vecs[m]) if (!/^~/.test(t)) score.set(t, (score.get(t) || 0) + x);
        const share = (t) => members.filter((m) => ix.docs[m].tf.has(t)).length;
        const top = [...score].filter(([t]) => share(t) >= Math.min(2, members.length)).sort((a, b) => b[1] - a[1] || (a[0] < b[0] ? -1 : 1));
        const picked = [];
        for (const [t] of top) {
          if (picked.length >= 3) break;
          if (picked.some((x) => x.startsWith(t) || t.startsWith(x) || N.near(x, t))) continue;
          picked.push(t);
        }
        const wordsShown = picked.map((t) => shown(ix, t));
        return { key: picked.join("+") || "group" + members[0], label: wordsShown.join(", "), words: wordsShown, reels: members.map((m) => ix.docs[m].r) };
      }).sort((a, b) => b.reels.length - a.reels.length || (a.label < b.label ? -1 : 1));
    });
  }

  function topic(reels, key) { return topics(reels).find((t) => t.key === key) || null; }

  /** Every tool or app the notes name, with how many reels name it. [{name, count}] */
  function tools(reels) {
    const ix = N.index(reels);
    return memo(ix, "tools", () => {
      const by = new Map();
      for (const d of ix.docs) {
        const seen = new Set();
        for (const t of (d.r.notes || {}).tools || []) {
          const name = String(t).trim().replace(/\s+/g, " ");
          const k = fold(name);
          if (!k || k.length > 40 || seen.has(k)) continue;
          seen.add(k);
          const cur = by.get(k) || { name, count: 0 };
          cur.count++;
          by.set(k, cur);
        }
      }
      return [...by.values()].sort((a, b) => b.count - a.count || a.name.localeCompare(b.name));
    });
  }

  return { parseQuery, find, distance, didYouMean, highlight, topics, topic, tools, fold };
})();
