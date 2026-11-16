"""Search, the index and related reels at scale (assets/local/notes.js, library.js): a library of thousands of reels has to answer
a search and open a reel quickly, and the answers must not change. Placeholder text only: the reels are generated here, the same
ones every run (GEN_JS of test_phone_topics.py).

REF below is the code as it was before the speed-up (P2: Notes.search, Notes.related and Lib.find, with an index built from
scratch every call), copied word for word. Every test that says "the same as before" compares the page's code with it: the same
reels in the same order with the same scores (exactly, not nearly) and the same lines."""
import json
import re

import pytest

from test_phone_app import LOCAL, phone, site  # noqa: F401  (pytest fixtures)
from test_phone_search import _library
from test_phone_topics import GEN_JS, _generated

# The synonym groups are read from notes.js itself (so a new group there does not need a change here): the reference only keeps
# the old algorithm, not the old data.
_SYN_LIST = re.search(r"const SYN = (\[.*?\])\.map\(", (LOCAL / "notes.js").read_text(encoding="utf-8"), re.S).group(1)

REF_JS = r"""
window.REF = (() => {
  const N = Notes;
  const SYN = (__SYN__).map((g) => g.split(" ").map((w) => N.stem(w.replace(/-/g, ""))));
  function docOf(r) {
    const tf = new Map();
    let len = 0;
    for (const [text, w] of N.fieldsOf(r)) for (const t of N.words(text)) { tf.set(t, (tf.get(t) || 0) + w); len += w; }
    return { r, tf, len };
  }
  function build(reels) {
    const docs = reels.map(docOf);
    const df = new Map();
    for (const d of docs) for (const t of d.tf.keys()) df.set(t, (df.get(t) || 0) + 1);
    const avg = docs.reduce((a, d) => a + d.len, 0) / Math.max(1, docs.length) || 1;
    return { docs, df, avg, N: docs.length };
  }
  // the old code built the index again from scratch for every call; pin() keeps one (for reels nobody changes meanwhile) so a test of a big library is not all index building
  let pinned = null;
  const index = (reels) => (pinned && pinned.reels === reels ? pinned.ix : build(reels));
  const pin = (reels) => { pinned = { reels, ix: build(reels) }; };
  const unpin = () => { pinned = null; };
  function idfOf(ix, t) { const n = ix.df.get(t) || 0; return Math.log(1 + (ix.N - n + 0.5) / (n + 0.5)); }

  function search(reels, query, limit = 20) {
    const q = [...new Set(N.words(query))];
    if (!q.length) return [];
    const ix = index(reels);
    const vocab = [...ix.df.keys()];
    const expand = new Map(q.map((t) => {
      const m = new Map([[t, 1]]);
      for (const k of vocab) {
        if (m.has(k)) continue;
        if (t.length >= 4 && (k.startsWith(t) || (k.length >= 4 && t.startsWith(k)))) m.set(k, 0.7);
        else if (N.near(t, k)) m.set(k, 0.6);
      }
      for (const s of N.synonyms(t)) if (!m.has(s)) m.set(s, 0.5);
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
      s *= 0.5 + matched / q.length;
      const want = new Set([...expand.values()].flatMap((m) => [...m.keys()]));
      const n = d.r.notes || {};
      const cands = [...(n.points || []), n.takeaway, n.meaning, ...(n.use || [])].filter(Boolean);
      if (!cands.length) cands.push(...N.sentences([d.r.transcript, d.r.caption, d.r.onscreen, d.r.extra].filter(Boolean).join("\n")));
      const lines = cands.map((l) => ({ l, k: new Set(N.words(l).filter((w) => want.has(w))).size }))
        .filter((x) => x.k).sort((a, b) => b.k - a.k).slice(0, 3).map((x) => x.l);
      out.push({ reel: d.r, score: s, lines });
    }
    return out.sort((a, b) => b.score - a.score).slice(0, limit);
  }

  function related(reels, target, limit = 5) {
    const ix = index(reels);
    const groups = (d) => { const g = new Map(); for (const [t, f] of d.tf) SYN.forEach((s, i) => { if (s.includes(t)) g.set("~" + i, (g.get("~" + i) || 0) + f); }); return g; };
    const gdf = new Map();
    const gs = new Map(ix.docs.map((d) => { const g = groups(d); for (const k of g.keys()) gdf.set(k, (gdf.get(k) || 0) + 1); return [d, g]; }));
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

  const fold = Lib.fold;
  const tagsOf = (r) => [...((r.notes || {}).tags || []), ...(r.keywords || [])].map((t) => fold(t).replace(/^#+/, "").replace(/\s+/g, ""));
  const fullText = (r) => fold(N.fieldsOf(r).map((x) => x[0] || "").join("\u0001").replace(/\u0001/g, " "));
  function find(reels, query, limit = 20) {
    const p = Lib.parseQuery(query);
    const ix = index(reels);
    const tfOf = new Map(ix.docs.map((d) => [d.r, d.tf]));
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
    if (p.text) hits = search(reels, p.text, reels.length).filter((h) => ok(h.reel));
    else if (p.tags.length || p.exclude.length) hits = reels.filter(ok).map((r) => ({ reel: r, score: 0, lines: [] }));
    else return [];
    if (p.phrases.length) {
      for (const h of hits) {
        const n = h.reel.notes || {};
        const all = [...(n.points || []), n.takeaway, n.meaning, ...(n.use || [])].filter(Boolean);
        const exact = all.filter((l) => p.phrases.some((x) => fold(l).includes(x)));
        h.lines = [...new Set([...exact, ...h.lines])].slice(0, 3);
      }
    }
    return hits.slice(0, limit);
  }
  return { search, related, find, index: build, pin, unpin };
})();

// null when the two lists are the same: the same reels (the very same objects) in the same order, the same scores to the last
// digit, the same lines, and nothing else on the results; else what differs first
window.sameHits = (a, b) => {
  if (a.length !== b.length) return "length " + a.length + " against " + b.length;
  for (let i = 0; i < a.length; i++) {
    if (a[i].reel !== b[i].reel) return "#" + i + " is " + a[i].reel.code + ", was " + b[i].reel.code;
    if (a[i].score !== b[i].score) return "#" + i + " (" + a[i].reel.code + ") score " + a[i].score + ", was " + b[i].score;
    if (JSON.stringify(Object.keys(a[i])) !== JSON.stringify(Object.keys(b[i]))) return "#" + i + " has other keys";
    if (JSON.stringify(a[i].lines) !== JSON.stringify(b[i].lines)) return "#" + i + " (" + a[i].reel.code + ") lines " + JSON.stringify(a[i].lines) + ", was " + JSON.stringify(b[i].lines);
  }
  return null;
};

// the index itself: the same words, weights, lengths and document frequencies, in the same order
window.sameIndex = (a, b) => {
  if (a.N !== b.N || a.avg !== b.avg || a.docs.length !== b.docs.length) return "N or avg";
  if (JSON.stringify([...a.df]) !== JSON.stringify([...b.df])) return "df";
  for (let i = 0; i < a.docs.length; i++) {
    if (a.docs[i].r !== b.docs[i].r || a.docs[i].len !== b.docs[i].len || JSON.stringify([...a.docs[i].tf]) !== JSON.stringify([...b.docs[i].tf])) return "doc " + i;
  }
  return null;
};

// the page's search, find and related-reels against REF: every question, at several limits, twice (the second time with what the
// first one kept), and every reel in `targets`
window.battery = (reels, queries, targets) => {
  const bad = [];
  let checked = 0, nonEmpty = 0;
  const check = (what, got, was) => { checked++; if (was.length) nonEmpty++; const m = sameHits(got, was); if (m) bad.push(what + ": " + m); };
  REF.pin(reels);
  try {
    const ix = Notes.index(reels), why = sameIndex(ix, REF.index(reels));
    if (why) bad.push("index: " + why);
    const N = reels.length;
    const accept = (r) => /[0-4]$/.test(r.code);
    for (const q of queries) {
      const s = REF.search(reels, q, N), f = REF.find(reels, q, N);
      for (const lim of [1, 8, 20, 200, N]) {
        for (let again = 0; again < 2; again++) {
          check("find " + JSON.stringify(q) + " limit " + lim, Lib.find(reels, q, lim), f.slice(0, lim));
          check("search " + JSON.stringify(q) + " limit " + lim, Notes.search(reels, q, lim), s.slice(0, lim));
        }
      }
      check("search " + JSON.stringify(q) + " with a filter", Notes.search(reels, q, 8, (r) => accept(r)), s.filter((h) => accept(h.reel)).slice(0, 8));
      check("search " + JSON.stringify(q) + " default limit", Notes.search(reels, q), s.slice(0, 20));
    }
    for (const t of targets) {
      const rel = REF.related(reels, t, N);
      for (const lim of [1, 4, 5, N]) for (let again = 0; again < 2; again++) check("related " + (t.code || "?") + " limit " + lim, Notes.related(reels, t, lim), rel.slice(0, lim));
    }
  } finally { REF.unpin(); }
  return { checked, nonEmpty, nBad: bad.length, bad: bad.slice(0, 8) };
};

// What the generated reels do not have: words of the synonym groups, reels without notes (their lines come from the speech and
// the caption), a reel with no words, and reels with exactly the same words as another (equal scores: the order of ties).
window.decorate = (rs) => {
  const W = ["password", "secret", "phone", "mobile", "money", "invest", "workout", "gym", "code", "hack", "security", "study", "job", "sleep",
    "photo", "video", "business", "marketing", "website", "database", "free", "fast", "health", "ai", "tip", "exercise", "apikey"];
  rs.forEach((r, i) => {
    if (i % 4 === 0) r.notes.tags.push(W[i % W.length]);
    if (i % 3 === 0) r.onscreen += " " + W[(i * 7) % W.length] + " " + W[(i * 5 + 1) % W.length];
    if (i % 9 === 0) r.caption += " " + W[(i * 3) % W.length] + "s";
    if (i % 11 === 5) {
      r.notes = null;
      r.transcript = r.transcript.split(" ").map((w, j) => (j % 7 === 6 ? w + ". " : w + " ")).join("").trim() + " Use a password manager. Keep it free.";
    }
  });
  const n = rs.length;
  rs.push(JSON.parse(JSON.stringify(rs[10])), JSON.parse(JSON.stringify(rs[20])), JSON.parse(JSON.stringify(rs[10])));
  rs[n].code = "TIE001"; rs[n + 1].code = "TIE002"; rs[n + 2].code = "TIE003";
  rs.push({ code: "EMPTY1", url: "", notes: {} });
  rs.push({ code: "SYN001", url: "", notes: { topic: "password secret credential", tags: ["security"], points: ["Never share a token"] } });
  return rs;
};

// questions worked out from the reels themselves: common, middling and rare words, typos, prefixes, synonyms, and every operator
window.questions = (rs) => {
  const ix = REF.index(rs);
  const byDf = [...ix.df].sort((a, b) => b[1] - a[1]);
  const at = (f) => byDf[Math.min(byDf.length - 1, Math.floor(byDf.length * f))][0];
  const common = byDf[0][0], second = byDf[2][0], mid = at(0.05), mid2 = at(0.08), rare = byDf[byDf.length - 1][0];
  const long = byDf.filter(([w, n]) => w.length >= 6 && n > 2).map((x) => x[0]);
  const w1 = long[0], w2 = long[Math.floor(long.length / 3)], w3 = long[Math.floor(long.length * 2 / 3)];
  const swap = (w) => w.slice(0, 2) + w[3] + w[2] + w.slice(4), drop = (w) => w.slice(0, 3) + w.slice(4);
  const tag = Lib.fold(rs[7].notes.tags[0]).replace(/\s+/g, "");
  const words = rs[3].caption.split(" ");
  const phrase = words[2] + " " + words[3];
  return [common, second, mid, mid2, rare, mid + " " + mid2, common + " " + mid + " " + rare, swap(w1), drop(w2), w3.slice(0, 4), w3 + "s", w1 + "ing",
    "password", "secret", "mobile phone", "gym", "workout", "money", "marketing", "ai", "tips", "password manager free", "hakc",
    '"' + phrase + '"', '"' + phrase + '" ' + mid, mid + " -" + mid2, mid + ' -"' + phrase + '"', "-" + common, "#" + tag, mid + " #" + tag, '#security "password"',
    '"zzzz qqqq"', "zzzqqq", "#nosuchtag", "", "   "];
};
"""


def _with_ref(pg):
    pg.evaluate("() => {" + REF_JS.replace("__SYN__", _SYN_LIST) + "}")


def _decorated(pg, n):
    """The generated library as the app's library, with the extra reels of decorate()."""
    _generated(pg, n)
    _with_ref(pg)
    pg.evaluate("() => decorate(db.reels)")


# ---------------------------------------------------------------- 1. the same answers as before

SMALL_QUESTIONS = ["password", "passwords leak", "pasword", "gitleks scan", "workot", "mobile", "phone app", "exercise", "gym sets", "protein",
                   "rest between sets", "two factor", '"password manager"', "password -manager", 'password -"two factor"', "#workout",
                   "sets #workout", "#passwords", "#nosuchtag password", "zzzzzzzz", "api key", "keys", "secret", "ai", "the", "", "   ",
                   "-password", '"nothing like this"', "quinoa", "workout gym", "tips", "hack"]


def test_the_small_library_gives_the_same_answers_as_before(phone):
    phone.open_with({"db": json.dumps(_library())})
    _with_ref(phone)
    out = phone.evaluate("""(qs) => { const rs = JSON.parse(window.__rn.db).reels; return battery(rs, qs, [...rs, { code: "not in the library", notes: { topic: "x" } }]); }""", SMALL_QUESTIONS)
    assert out["nBad"] == 0, out
    assert out["checked"] > 500 and out["nonEmpty"] > 250, out    # not empty answers all the way


@pytest.mark.parametrize("n", [60, 300, 1000])
def test_generated_libraries_give_the_same_answers_as_before(phone, n):
    _decorated(phone, n)
    out = phone.evaluate("""() => {
      const rs = db.reels, last = rs.length;
      const targets = [rs[0], rs[Math.floor(last / 3)], rs[Math.floor(last / 2)], rs[5], rs[10], rs[last - 5], rs[last - 4], rs[last - 3], rs[last - 2], rs[last - 1], rs[last - 6]];
      return battery(rs, questions(rs), targets);
    }""")
    assert out["nBad"] == 0, out
    assert out["nonEmpty"] > 0.4 * out["checked"], out      # most of the questions find something


def test_ties_keep_the_order_of_the_library(phone):
    _decorated(phone, 300)
    out = phone.evaluate("""() => {
      const rs = db.reels;
      const a = rs.findIndex((r) => r.code === "R000010"), b = rs.findIndex((r) => r.code === "TIE001"), c = rs.findIndex((r) => r.code === "TIE003");
      const rel = Notes.related(rs, rs[a], rs.length), pos = (code) => rel.findIndex((x) => x.reel.code === code);
      const hits = Lib.find(rs, db.reels[10].notes.topic, rs.length), at = (code) => hits.findIndex((x) => x.reel.code === code);
      return { sameScore: rel[pos("TIE001")].score === rel[pos("TIE003")].score, order: pos("TIE001") < pos("TIE003"),
               hitSame: hits[at("R000010")].score === hits[at("TIE001")].score, hitOrder: at("R000010") < at("TIE001") && at("TIE001") < at("TIE003"), a, b, c };
    }""")
    assert out["sameScore"] and out["order"] and out["hitSame"] and out["hitOrder"], out


def test_the_search_of_the_library_screens_still_finds_the_same_reels(phone):
    # the three places that ask: the shelf's search box (Search.run), the Ask screen and the reel screen
    _generated(phone, 300, 20)   # 20 subjects: every reel has more than four reels about the same thing
    _with_ref(phone)
    out = phone.evaluate("""() => {
      const q = questions(db.reels)[2];
      const want = REF.find(db.reels, q, 200).map((h) => h.reel.code);
      const got = Search.run(db, q, { kind: "all" }).reels.map((h) => h.reel.code);
      const rel = REF.related(db.reels, db.reels[40], 4).map((x) => x.reel.code);
      return { q, want, got, rel, again: Notes.related(db.reels, db.reels[40], 4).map((x) => x.reel.code) };
    }""")
    assert out["want"] and out["got"][:len(out["want"])] == out["want"], out
    assert out["rel"] == out["again"] and len(out["rel"]) == 4, out
    phone.evaluate("(q) => { location.hash = '#/ask?q=' + encodeURIComponent(q); }", out["q"])
    phone.locator("#app a.card").first.wait_for()
    assert phone.locator("#app a.card").count() == min(8, len(out["want"]))
    phone.evaluate("() => { location.hash = '#/r/' + db.reels[40].code; }")
    phone.get_by_role("heading", name="Related reels").wait_for()
    assert phone.locator("#app a.list-item").count() == 4


# ---------------------------------------------------------------- 2. what is kept follows the library

def test_what_is_kept_follows_the_changes_of_the_library(phone):
    phone.open_with({"db": json.dumps(_library())})
    _with_ref(phone)
    out = phone.evaluate("""(qs) => {
      const rs = JSON.parse(window.__rn.db).reels, out = {}, bad = [];
      const same = (what) => { const r = battery(rs, qs, rs); if (r.nBad) bad.push(what + ": " + r.bad.join(" | ")); };
      const codes = (q) => Lib.find(rs, q).map((h) => h.reel.code);
      const ix0 = Notes.index(rs);
      Lib.find(rs, "password"); Notes.related(rs, rs[0]);       // everything is warm now
      same("warm");

      // changes that are not about words keep the index (and what is kept for it)
      rs[0].status = "watched"; rs[0].added_at = 99; rs[1].url = "https://example.com/x"; rs[2].notes.unbacked = 3; rs[3].extra_flag = true;
      out.keptIx = Notes.index(rs) === ix0;
      same("status and others");
      out.keptAfterQuery = Notes.index(rs) === ix0;

      // an edit of a word: the new word is found, and the reels related to it follow
      out.quinoaBefore = codes("quinoa");
      rs[6].notes.topic = "Quinoa bowl";
      const ix1 = Notes.index(rs);
      out.rebuilt = ix1 !== ix0 && ix1.N === 7;
      out.quinoa = codes("quinoa");
      same("topic edited");

      // an edit inside a list, in place
      rs[3].notes.points[0] = "Never share a password with anyone";
      out.inList = codes("password").includes("GYM001");
      same("point edited");

      // a reel added: found at once, and it is related to the reels about the same thing
      out.typoBefore = codes("quinoo");
      rs.push(Object.assign({}, rs[6], { code: "FOOD02", notes: { topic: "Quinoa salad", points: ["Cook quinoa in water"], tags: ["diet"] } }));
      const ix2 = Notes.index(rs);
      out.added = ix2 !== ix1 && ix2.N === 8;
      out.quinoaAdded = codes("quinoa");
      out.typoAfter = codes("quinoo");
      out.relatedAdded = Notes.related(rs, rs[6]).map((x) => x.reel.code);
      same("reel added");

      // a reel removed: gone from every answer
      const gone = rs.splice(0, 1)[0];
      const ix3 = Notes.index(rs);
      out.removed = ix3 !== ix2 && ix3.N === 7;
      out.goneFromSearch = !codes("password").includes(gone.code);
      out.goneFromRelated = !Notes.related(rs, rs[0], 20).some((x) => x.reel === gone) && Notes.related(rs, gone).length === 0;
      same("reel removed");

      // the same reels in another order are another library: the same answers, in that order
      rs.reverse();
      same("reversed");
      out.bad = bad;
      return out;
    }""", SMALL_QUESTIONS + ["quinoa", "quinoo", "salad", "bowl"])
    assert out["bad"] == [], out
    assert out["keptIx"] and out["keptAfterQuery"]
    assert out["quinoaBefore"] == [] and out["rebuilt"] and out["quinoa"] == ["FOOD01"]
    assert out["inList"]
    assert out["typoBefore"] == ["FOOD01"] and out["added"] and out["quinoaAdded"][:2] in (["FOOD01", "FOOD02"], ["FOOD02", "FOOD01"])
    assert out["typoAfter"] and "FOOD02" in out["typoAfter"]        # the typo's matches are worked out again for the new words
    assert "FOOD02" in out["relatedAdded"]
    assert out["removed"] and out["goneFromSearch"] and out["goneFromRelated"]


def test_a_word_added_by_one_reel_is_found_through_a_typo_of_it(phone):
    # the words a question word can mean are kept for one version of the index only: a new word in the library counts at once
    _decorated(phone, 60)
    out = phone.evaluate("""() => {
      const rs = db.reels;
      const before = Lib.find(rs, "zorbulax").map((h) => h.reel.code);      // nothing: warms what is kept for this word
      const typoBefore = Lib.find(rs, "zorbulex").map((h) => h.reel.code);
      rs[3].notes.takeaway = "A zorbulax is a fine thing";
      const after = Lib.find(rs, "zorbulax").map((h) => h.reel.code);
      const typoAfter = Lib.find(rs, "zorbulex").map((h) => h.reel.code);
      const prefixAfter = Lib.find(rs, "zorbul").map((h) => h.reel.code);
      rs[3].notes.takeaway = "";
      const back = Lib.find(rs, "zorbulax").map((h) => h.reel.code);
      return { code: rs[3].code, before, typoBefore, after, typoAfter, prefixAfter, back, bad: battery(rs, ["zorbulax", "zorbulex", "zorbul"], [rs[3]]).nBad };
    }""")
    assert out["before"] == [] and out["typoBefore"] == [] and out["back"] == []
    assert out["after"] == [out["code"]] and out["typoAfter"] == [out["code"]] and out["prefixAfter"] == [out["code"]]
    assert out["bad"] == 0


# ---------------------------------------------------------------- 3. fast enough, with room for a slow runner

# Best of five warm calls on 1,000 and 5,000 generated reels, desktop Chromium (not a phone), a loaded 4-core machine. Measured here
# first, as [before the speed-up, after]: ask a common word at 5,000: [190-240 ms, 12-20]; related reels at 5,000: [570-600, 50-90];
# at 1,000: ask [45-55, 2-6], related [120, 8]. A budget is several times what the new code took, and below what the old code took.
BUDGET_MS = {1000: {"find": 30, "related": 60, "index": 20}, 5000: {"find": 100, "related": 250, "index": 60}}


@pytest.mark.parametrize("n", [1000, 5000])
def test_a_search_and_related_reels_are_fast_in_a_big_library(phone, n):
    _generated(phone, n)
    _with_ref(phone)
    out = phone.evaluate("""() => {
      const rs = db.reels;
      const best = (fn, times = 5) => { let b = Infinity; for (let i = 0; i < times; i++) { const t = performance.now(); fn(i); b = Math.min(b, performance.now() - t); } return Math.round(b * 10) / 10; };
      const cold = Math.round((() => { const t = performance.now(); Notes.index(rs); return performance.now() - t; })());
      const ix = Notes.index(rs);
      const byDf = [...ix.df].sort((a, b) => b[1] - a[1]);
      const common = byDf[0][0], second = byDf[3][0];          // words most reels have: the most lines to find
      const mid = Math.floor(rs.length / 2);
      const got = {
        cold,
        index: best(() => Notes.index(rs)),
        find: best(() => Lib.find(rs, common, 8)),
        findTwo: best(() => Lib.find(rs, common + " " + second, 8)),
        related: best((i) => Notes.related(rs, rs[mid + i], 4)),
      };
      // the same answers as the old code on these (and its time, for the ratio below)
      REF.pin(rs);
      const slow = {
        find: best(() => REF.find(rs, common, 8), 2),
        related: best((i) => REF.related(rs, rs[mid + i], 4), 2),
      };
      const bad = [sameHits(Lib.find(rs, common, 8), REF.find(rs, common, 8)), sameHits(Lib.find(rs, common + " " + second, 200), REF.find(rs, common + " " + second, 200)),
                   sameHits(Notes.related(rs, rs[mid], 4), REF.related(rs, rs[mid], 4)), sameHits(Notes.related(rs, rs[7], 30), REF.related(rs, rs[7], 30))].filter(Boolean);
      REF.unpin();
      return { got, slow, bad, hits: Lib.find(rs, common, 8).length };
    }""")
    budget = BUDGET_MS[n]
    assert out["bad"] == [] and out["hits"] == 8, out
    got = out["got"]
    assert got["index"] < budget["index"], out        # an index that is current is only checked, not built again
    assert got["find"] < budget["find"] and got["findTwo"] < budget["find"], out
    assert got["related"] < budget["related"], out
    # and on whatever machine this runs, far faster than the old code on it (it was 5 to 12 times slower here)
    assert got["find"] * 3 < out["slow"]["find"] and got["related"] * 3 < out["slow"]["related"], out
