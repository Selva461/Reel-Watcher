"""The watchlist at scale (assets/local/catalog.js): adding a title and checking a title online used to read the whole list again for
every title (and clean every stored name again), so adding 5,000 titles took about 24 seconds. Now an index in memory finds the
few entries that can be the same title. These tests pin three things, in the phone harness (Chromium at phone size, no network):

1. the answers are the old answers: the same questions put to the new Catalog and to a frozen copy of the old one
   (tests/catalog_before_index.js) on generated lists full of near-duplicates give the same answer every time;
2. the index is never stale: after add, merge, rename, remove, details, a different list loaded, a stale reload, "delete all" and
   an empty library, every answer is what a fresh read of the whole list gives;
3. it is fast: adding N titles and checking N titles stays within a budget the old code missed by a wide margin, and a lookup no
   longer cleans every stored name (counted, so this part does not depend on the speed of the machine).

The lists are generated here from a fixed seed (placeholder words, the same every run); no real titles."""
from pathlib import Path

import pytest

from test_phone_app import phone, site  # noqa: F401  (pytest fixtures)

REFERENCE = (Path(__file__).resolve().parent / "catalog_before_index.js").read_text(encoding="utf-8")

# genTitles(n, seed, dupRate): n candidates for Catalog.add. A share of them (dupRate) are deliberate near-duplicates of an earlier
# one: the same title with another year, kind, language or spelling, a title that lists an old one as another name, the same
# database id under another name, the same name with another id, accents, other scripts, names with nothing left once cleaned.
GEN_JS = r"""function genTitles(n, seed, dupRate) {
  let s = seed | 0;
  const rnd = () => { s = (s + 0x6D2B79F5) | 0; let t = Math.imul(s ^ (s >>> 15), 1 | s); t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t; return ((t ^ (t >>> 14)) >>> 0) / 4294967296; };
  const pick = (a) => a[Math.floor(rnd() * a.length)];
  const syl = "ba be bi bo bu ka ke ki ko ku ma me mi mo mu ra re ri ro ru sa se si so su ta te ti to tu na ne ni no nu la le li lo lu".split(" ");
  const word = () => { let w = ""; const k = 2 + Math.floor(rnd() * 2); for (let i = 0; i < k; i++) w += pick(syl); return w[0].toUpperCase() + w.slice(1); };
  const KINDS = ["movie", "movie", "series", "series", "kdrama", "drama", "anime", "anime_movie", "animation", "documentary", "manga", "manhwa", "webtoon", "comic", "light_novel", "book", "game", "film", "tv show", "Netflix series", "k drama", "other"];
  const WATCH = ["movie", "series", "kdrama", "anime", "film", "tv show"], READ = ["manga", "manhwa", "book", "comic"];
  const LANGS = ["en", "en", "ko", "ja", "hi", "ta", "", "", "korean", "Japanese", "fr", "es", "xx"];
  const GENRES = ["Drama", "Thriller", "sci-fi", "romcom", "Action", "Horror", "slice of life", "Comedy"];
  // accents, other scripts, full-width letters, a ligature; and names that have nothing left once cleaned
  const UNI = ["Amélie", "Pokémon", "Naïve", "Ångström", "Crème Brûlée", "Ёлки", "Люди", "進撃の巨人", "千と千尋",
    "한강", "Ｔｏｋｙｏ", "Cañón", "Åsa", "Zażółć", "ﬁlm"];
  const EMPTY = ["!!!", "...", "🎬", "?!", "（）", " - "];
  const out = [];
  let tm = 100000, an = 900000;
  const base = (i) => {
    let t = Array.from({ length: 1 + Math.floor(rnd() * 3) }, word).join(" ");
    const r = rnd();
    if (r < 0.08) t = "The " + t; else if (r < 0.11) t = t + " Part II"; else if (r < 0.14) t = t + " & " + word(); else if (r < 0.16) t = pick(UNI) + " " + word();
    const c = { title: t, type: pick(KINDS), year: rnd() < 0.7 ? 1960 + Math.floor(rnd() * 65) : null, language: pick(LANGS), confidence: Math.round(rnd() * 100) / 100,
      source: { kind: pick(["screenshot", "reel", "manual"]), ref: "ref-" + i, method: "m", text: t, confidence: 0.8 } };
    if (rnd() < 0.2) c.original_title = word() + " " + word();
    if (rnd() < 0.25) c.aka = Array.from({ length: 1 + Math.floor(rnd() * 2) }, () => word() + " " + word());
    if (rnd() < 0.3) c.genres = [pick(GENRES), pick(GENRES)];
    if (rnd() < 0.18) c.ext = { tmdb: String(tm++) };
    else if (rnd() < 0.1) c.ext = { anilist: String(an++) };
    else if (rnd() < 0.05) c.ext = { imdb: "tt" + (7000000 + tm++) };
    return c;
  };
  for (let i = 0; i < n; i++) {
    if (i < 8 || rnd() >= dupRate) { out.push(base(i)); continue; }
    // a near-duplicate of an earlier one: mostly a recent one, sometimes any
    const p = out[Math.max(0, out.length - 1 - Math.floor(rnd() * Math.min(out.length, rnd() < 0.5 ? 40 : 4000)))];
    const c = { ...p, ext: p.ext ? { ...p.ext } : undefined, aka: p.aka ? p.aka.slice() : undefined, source: { ...p.source, kind: pick(["screenshot", "reel"]), ref: "ref-" + i } };
    const yr = p.year || 2000;
    switch (Math.floor(rnd() * 22)) {
      case 0: c.year = yr; break;                                           // the same title and year
      case 1: c.year = yr + (rnd() < 0.5 ? 1 : -1); break;                  // one year apart: still the same
      case 2: c.year = yr + 2 + Math.floor(rnd() * 5); break;              // a remake: separate
      case 3: c.year = null; break;                                         // no year: matches any
      case 4: c.type = pick(WATCH); break;                                  // another watch kind: same group
      case 5: c.type = pick(READ); break;                                   // a book or comic: another group
      case 6: c.language = pick(["en", "ko", "ja", "", "hindi"]); break;    // another language, or none
      case 7: c.title = p.title.toUpperCase() + "!"; break;                 // capitals and punctuation
      case 8: c.title = "The " + p.title + " (" + yr + ")"; break;          // an article and a year in the name
      case 9: c.title = p.title.replace(/ ii\b/i, " 2").replace(/ 2$/, " II").replace(/ & /, " and "); break;  // roman numerals, "&"
      case 10: c.title = word() + " " + word(); c.aka = [p.title]; c.ext = undefined; break;                // a new title that lists the old one as another name
      case 11: c.title = word(); c.original_title = p.title; c.ext = undefined; break;                      // its original title is the old name
      case 12: c.title = (p.aka && p.aka[0]) || p.original_title || p.title + " Season 1"; break;           // the old one's other name
      case 13: c.title = word() + " " + word(); c.ext = p.ext ? { ...p.ext } : { tmdb: "t" + (tm++) }; break;  // the same database id under another spelling
      case 14: c.ext = { tmdb: String(tm++) }; break;                       // the same title with another database id: two titles
      case 15: c.ext = { ...(p.ext || { tmdb: String(tm++) }), imdb: "tt" + (8000000 + tm++) }; break;     // one id shared, one id that differs
      case 16: c.ext = { imdb: "tt" + (9000000 + tm++) }; break;            // an id the other has no value for
      case 17: c.title = pick(UNI) + (rnd() < 0.5 ? "" : " " + word()); break;
      case 18: c.title = pick(EMPTY); c.ext = rnd() < 0.5 ? { tmdb: String(tm++) } : undefined; break;     // nothing left after cleaning
      case 19: c.title = p.title + (rnd() < 0.5 ? " (" + (yr + 1) + ")" : " [" + yr + "]"); break;         // the year inside the name
      case 20: c.title = "A " + p.title.toLowerCase().replace(/e/g, "é"); break;                       // accents on the same letters
      default: c.title = p.title + " Volume 1";
    }
    out.push(c);
  }
  return out;
}
"""

# equivalence(New, Ref, genTitles, n, seed, probesPer): the same operations (add, online-check answers, details, remove, merge,
# update, a list read again, an emptied list) on a list kept by the new Catalog and one kept by the old one, with questions put to
# findSame in between. The clock is the same for both, so the stored times agree. bad is empty when the two always agree.
EQUIV_JS = r"""// equivalence(New, Ref, genTitles, n, seed, probesPer): the same operations on two lists, one with the new Catalog and one with
// the old one. Returns { ops, probes, found, size, peak, bad }: bad holds the first differences (empty when the two always agree).
function equivalence(New, Ref, genTitles, n, seed, probesPer) {
  let s = (seed ^ 0x9e3779b9) | 0;
  const rnd = () => { s = (s + 0x6D2B79F5) | 0; let t = Math.imul(s ^ (s >>> 15), 1 | s); t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t; return ((t ^ (t >>> 14)) >>> 0) / 4294967296; };
  const below = (k) => Math.floor(rnd() * k);
  const clone = (v) => JSON.parse(JSON.stringify(v));
  const yearOf = (v) => { const m = String(v || "").match(/(18|19|20)\d\d/); return m ? Number(m[0]) : null; };
  const cands = genTitles(n, seed, 0.34);
  const A = { media: [] }, B = { media: [] };  // A: the new code, B: the old code
  for (const db of [A, B]) Ref.addType(db, "Thai BL", "watch");
  const out = { ops: 0, probes: 0, found: 0, size: 0, peak: 0, bad: [] };
  const differ = (what, x, y) => { if (JSON.stringify(x) !== JSON.stringify(y) && out.bad.length < 8) out.bad.push({ what, op: out.ops, new: x, ref: y }); };
  const real = Date.now;
  let clock = 1.7e12;
  // one operation on both lists; the clock is the same for both, so the stored times agree too
  const both = (fn) => { clock += 1000; out.ops++; const x = fn(New, A); const y = fn(Ref, B); return [x, y]; };
  const probe = (c) => {  // the same question to both findSame
    out.probes++;
    const ask = (C, db) => { const r = C.findSame(db, { ...clone(c), type: C.typeId(db, c.type || "movie"), language: C.langCode(c.language), year: yearOf(c.year) }); return r && r.id; };
    const [x, y] = [ask(New, A), ask(Ref, B)];
    differ("findSame", x, y);
    if (y) out.found++;
  };
  Date.now = () => clock;
  try {
    for (let i = 0; i < cands.length; i++) {
      const c = cands[i];
      differ("add", ...both((C, db) => { const r = C.add(db, clone(c)); return r && { id: r.entry.id, created: r.created, merged: r.merged }; }));
      out.peak = Math.max(out.peak, B.media.length);
      for (let k = 0; k < probesPer; k++) {
        probe(cands[Math.min(cands.length - 1, i + 1 + below(3))]);  // titles not added yet, some of them near-duplicates of stored ones
        if (A.media.length) {  // spellings of a stored title: capitals, another name, a year apart, another language, only its database id
          const a = A.media[below(A.media.length)];
          probe([{ title: a.title.toUpperCase(), type: a.type, year: a.year, language: a.language }, { title: (a.aka || [])[0] || a.original_title || a.title, type: a.type, year: (a.year || 2000) + 1 },
            { title: a.title, type: a.type, year: (a.year || 2000) + 2 }, { title: a.title, type: "manga", language: a.language }, { title: "No such " + i, ext: a.ext }][below(5)]);
        }
      }
      if (!A.media.length) continue;
      const a = A.media[below(A.media.length)], o = A.media[below(A.media.length)], o2 = A.media[below(A.media.length)];
      const roll = rnd();
      if (roll < 0.2) {  // the online check's answer: a rename (maybe onto another entry's title or id), a year, a kind, other names, details
        const facts = [
          { title: o.title, year: o.year, language: o.language, ext: o.ext, genres: ["Drama"] },
          { title: a.title.toUpperCase() },
          { ext: { tmdb: (o.ext || {}).tmdb || "x" + i } },
          { year: (a.year || 2000) + below(4) },
          { type: ["series", "movie", "manga", "anime"][below(4)], title: "The " + a.title },
          { aka: [o.title, "Alt " + i], original_title: "Orig " + i, runtime: 100 + i, episodes: 3 },
          { ext: { imdb: "tt" + (1000000 + below(40)) }, rating: { score: 7.5, by: "tmdb", votes: 10 }, seasons: [{ n: 1, episodes: 8, year: 2020 }] },
          { title: (o.aka || [])[0] || o.original_title || o.title + " Season 1", ext: { anilist: (o.ext || {}).anilist || "z" + i } },
        ][below(8)];
        const verdict = ["verified", "verified", "verified", "conflict", "rejected"][below(5)];
        differ("verify", ...both((C, db) => { const r = C.verify(db, a.id, clone(facts), verdict, "tmdb"); return r && { id: r.id, size: db.media.length }; }));
      } else if (roll < 0.26) {  // seasons and an imdb id for a title checked before: Verify.apply calls setDetails on the entry itself
        const imdb = "tt" + (1000000 + below(40));
        both((C, db) => C.setDetails(db.media.find((m) => m.id === a.id), { imdb }));
        probe({ title: "No such " + i, ext: { imdb } });
      } else if (roll < 0.31) {
        differ("remove", ...both((C, db) => { C.remove(db, a.id); return db.media.length; }));
      } else if (roll < 0.37 && a !== o) {
        differ("merge", ...both((C, db) => { const r = C.merge(db, a.id, o.id); return r && { id: r.id, size: db.media.length }; }));
      } else if (roll < 0.43) {
        const patch = [{ title: a.title + " Redux" }, { title: o.title }, { type: "manga", year: 1999 }, { language: "ko" }, { status: "done", note: "n" }][below(5)];
        differ("update", ...both((C, db) => { const r = C.update(db, a.id, patch); return r && r.id; }));
      }
      if (i === Math.floor(n / 3)) { const copy = JSON.stringify(B.media); A.media = JSON.parse(copy); B.media = JSON.parse(copy); }  // the list is read from the file again
      if (i === Math.floor(0.85 * n)) { A.media = []; B.media = []; }                                                                   // an empty list
      if (i % 50 === 0) { differ("list", A.media, B.media); differ("toVerify", New.toVerify(A).map((m) => m.id), Ref.toVerify(B).map((m) => m.id)); }
    }
    differ("final list", A.media, B.media);
    for (const m of B.media.slice(0, 100)) { differ("get", (New.get(A, m.id) || {}).id, (Ref.get(B, m.id) || {}).id); probe(m); }
  } finally { Date.now = real; }
  out.size = B.media.length;
  return out;
}
"""

# agree(db, extra): every question about the entries of db (their names, other names, ids, years) and the extra ones, put to the new
# findSame and to the old one on the very same list. The old one reads the whole list every time, so it is the oracle for a stale index.
AGREE_JS = r"""
window.agree = (db, extra) => {
  const probes = (extra || []).slice();
  for (const m of db.media) {
    probes.push({ title: m.title, type: m.type, year: m.year, language: m.language }, { title: m.title.toUpperCase(), type: m.type, year: (m.year || 2000) + 2 },
      { title: "No such title", ext: m.ext || {} });
    if ((m.aka || [])[0]) probes.push({ title: m.aka[0], type: m.type });
    if (m.original_title) probes.push({ title: m.original_title, type: m.type });
  }
  const bad = [];
  let found = 0, stale = 0;
  for (const p of probes) {
    const c = { ...p, type: Catalog.typeId(db, p.type || "movie"), language: Catalog.langCode(p.language), year: p.year || null };
    const x = Catalog.findSame(db, c), y = CatalogRef.findSame(db, c);
    if (x !== y) bad.push([p.title, x && x.id, y && y.id]);
    if (y) found++;
    if (x && !db.media.includes(x)) stale++;  // an answer that is not in the list any more
  }
  return { probes: probes.length, found, stale, bad };
};
window.ask = (db, c) => Catalog.findSame(db, { ...c, type: Catalog.typeId(db, c.type || "movie"), language: Catalog.langCode(c.language), year: c.year || null });
"""


def _ready(pg):
    """The app, plus the old Catalog as CatalogRef and the helpers above."""
    pg.open_with()
    pg.evaluate("(() => { window.CatalogRef = (() => {" + REFERENCE + "\nreturn Catalog; })(); })()")
    pg.evaluate("(() => {" + GEN_JS + EQUIV_JS + "window.genTitles = genTitles; window.equivalence = equivalence; })()")
    pg.evaluate("(() => {" + AGREE_JS + "})()")


# ---------------------------------------------------------------- 1. the same answers as before

@pytest.mark.parametrize("n, seed", [(50, 1), (50, 2), (400, 3), (400, 4), (1500, 5)])
def test_the_indexed_lookup_gives_the_old_answers_on_generated_lists(phone, n, seed):
    _ready(phone)
    r = phone.evaluate("([n, seed, per]) => equivalence(Catalog, CatalogRef, genTitles, n, seed, per)", [n, seed, 2 if n < 1000 else 1])
    assert r["bad"] == []
    assert r["probes"] >= 2 * n and r["ops"] >= n   # a lot was asked and done
    assert r["found"] >= 0.2 * r["probes"]           # and many of the questions had an entry for an answer, not only "none"
    assert r["peak"] >= 0.4 * n                      # the list grew to a real size before it was emptied


# What the old code decided, written out. Both the new Catalog and the old copy must give exactly these answers. (The old code
# compares cleaned names for equality only: a spelling mistake is a different title, there is no edit distance in findSame.)
RULES_JS = r"""(C) => {
  const db = {};
  const label = {};
  const add = (name, c) => { const e = C.add(db, c).entry; label[e.id] = name; return e; };
  add("dune84", { title: "Dune", type: "film", year: 1984, language: "en" });
  add("dune21", { title: "Dune", type: "film", year: 2021, language: "en" });
  add("sl-manhwa", { title: "Solo Leveling", type: "manhwa", language: "ko" });
  add("sl-anime", { title: "Solo Leveling", type: "anime", language: "ja" });
  add("dri-ml", { title: "Drishyam", language: "ml" });
  add("dri-hi", { title: "Drishyam", language: "hi" });
  add("parasite", { title: "Parasite", year: 2019, language: "ko", original_title: "Gisaengchung" });
  add("leon", { title: "Leon", year: 1994, aka: ["Léon: The Professional"] });
  add("oldboy", { title: "Oldboy", year: 2003, ext: { tmdb: "670" } });
  add("rocky2", { title: "Rocky II", year: 1979 });
  add("ff", { title: "Fast and Furious", year: 2001 });
  add("alpha", { title: "Alpha", ext: { tmdb: "5", imdb: "tt5" } });
  add("matrix", { title: "The Matrix", year: 1999 });
  add("foo", { title: "Foo", type: "series" });
  add("amelie", { title: "Amélie", year: 2001 });
  const k1 = add("kingdom-1", { title: "Kingdom", type: "series", year: 2019 });
  C.verify(db, k1.id, { ext: { tmdb: "k1" } }, "verified", "tmdb");   // checked, and older in the list than kingdom-2
  add("kingdom-2", { title: "Kingdom", type: "series", year: 2019, ext: { tmdb: "k2" } });
  add("fringe-a", { title: "Fringe", type: "series", ext: { tmdb: "f1" } });
  add("fringe-b", { title: "Fringe", type: "series", ext: { tmdb: "f2" } });
  const typo = add("misread", { title: "0ldboy" });
  const got = {};
  const q = (name, c) => {
    const r = C.findSame(db, { ...c, type: C.typeId(db, c.type || "movie"), language: C.langCode(c.language), year: c.year || null });
    got[name] = r ? label[r.id] || r.title : null;
  };
  q("year one apart", { title: "dune", year: 1985, type: "film" });
  q("years far apart", { title: "Dune", year: 2002 });
  q("no year: the first in the list", { title: "DUNE!" });
  q("another kind in the same group", { title: "Dune", type: "series", year: 2021 });
  q("a book is another group", { title: "Dune", type: "book" });
  q("a manga kind next to a manhwa", { title: "Solo Leveling", type: "webtoon" });
  q("the anime stays the anime", { title: "Solo Leveling", type: "anime movie" });
  q("the other group of kinds", { title: "Solo Leveling", type: "other" });
  q("two languages disagree", { title: "Drishyam", language: "ta" });
  q("the language agrees", { title: "Drishyam", language: "hi" });
  q("no language: the first in the list", { title: "Drishyam" });
  q("original title", { title: "Gisaengchung", year: 2019 });
  q("original title, another year", { title: "Gisaengchung", year: 2015 });
  q("other name, accents cleaned", { title: "Leon: The Professional" });
  q("a spelling mistake is another title", { title: "Parasyte", year: 2019 });
  q("one letter more is another title", { title: "Dunee", year: 1984 });
  q("same database id wins over name, year and kind", { title: "Something else", type: "manga", year: 1990, ext: { tmdb: "670" } });
  q("another database id beats the same name", { title: "Oldboy", ext: { tmdb: "999" } });
  q("ids with no key in common: the name decides", { title: "Oldboy", ext: { imdb: "tt1" } });
  q("one id shared, the other has no value", { title: "Nothing", ext: { tmdb: "670", imdb: "tt0" } });
  q("two ids disagree", { title: "Alpha", ext: { tmdb: "5", imdb: "tt6" } });
  q("one id of two shared", { title: "Alpha", ext: { tmdb: "5" } });
  q("the second id alone", { title: "Zzz", ext: { imdb: "tt5" } });
  q("nothing left of the name", { title: "!!!" });
  q("nothing left of the name, a known id", { title: "!!!", ext: { tmdb: "670" } });
  q("roman numeral", { title: "rocky 2", year: 1980 });
  q("roman numeral and a year in the name", { title: "Rocky 2 (1979)" });
  q("and, ampersand", { title: "Fast & Furious" });
  q("an article is dropped", { title: "Matrix" });
  q("another article", { title: "A Matrix" });
  q("season 1 is dropped", { title: "Foo Season 1", type: "series" });
  q("accents", { title: "AMELIE" });
  q("checked beats earlier in the list", { title: "Kingdom", type: "series" });
  q("unchecked: the first in the list", { title: "Fringe", type: "series" });
  q("the misread title is its own entry", { title: "0ldboy" });
  // the online check corrects the misread name: it is now the same title as oldboy, so the two become one
  const before = db.media.length;
  const kept = C.verify(db, typo.id, { title: "Oldboy", year: 2003, ext: { tmdb: "670" } }, "verified", "tmdb");
  got["a renamed entry folds into the twin"] = [label[kept.id], before - db.media.length];  // the checked one is kept, the older one goes
  q("and its old name now points at the kept one", { title: "0ldboy" });
  q("the name of the one that went", { title: "Oldboy" });
  return Object.entries(got);
}"""

RULES = {
    "year one apart": "dune84",
    "years far apart": None,
    "no year: the first in the list": "dune21",
    "another kind in the same group": "dune21",
    "a book is another group": None,
    "a manga kind next to a manhwa": "sl-manhwa",
    "the anime stays the anime": "sl-anime",
    "the other group of kinds": None,
    "two languages disagree": None,
    "the language agrees": "dri-hi",
    "no language: the first in the list": "dri-hi",
    "original title": "parasite",
    "original title, another year": None,
    "other name, accents cleaned": "leon",
    "a spelling mistake is another title": None,
    "one letter more is another title": None,
    "same database id wins over name, year and kind": "oldboy",
    "another database id beats the same name": None,
    "ids with no key in common: the name decides": "oldboy",
    "one id shared, the other has no value": "oldboy",
    "two ids disagree": None,
    "one id of two shared": "alpha",
    "the second id alone": "alpha",
    "nothing left of the name": None,
    "nothing left of the name, a known id": "oldboy",
    "roman numeral": "rocky2",
    "roman numeral and a year in the name": "rocky2",
    "and, ampersand": "ff",
    "an article is dropped": "matrix",
    "another article": "matrix",
    "season 1 is dropped": "foo",
    "accents": "amelie",
    "checked beats earlier in the list": "kingdom-1",
    "unchecked: the first in the list": "fringe-b",
    "the misread title is its own entry": "misread",
    "a renamed entry folds into the twin": ["misread", 1],
    "and its old name now points at the kept one": "misread",
    "the name of the one that went": "misread",
}


@pytest.mark.parametrize("which", ["Catalog", "CatalogRef"])
def test_the_matching_rules_are_the_ones_the_old_code_had(phone, which):
    _ready(phone)
    got = dict(phone.evaluate("(which) => (" + RULES_JS + ")(which === 'Catalog' ? Catalog : CatalogRef)", which))
    assert got == RULES


# ---------------------------------------------------------------- 2. the index is never stale

def test_the_index_follows_add_merge_rename_update_remove_and_details(phone):
    _ready(phone)
    r = phone.evaluate(r"""() => {
      const db = { media: [] };
      Catalog.addMany(db, genTitles(150, 11, 0.34));
      const out = { steps: {}, facts: {} };
      const step = (name, extra) => { const a = agree(db, extra); out.steps[name] = { probes: a.probes, found: a.found, stale: a.stale, bad: a.bad }; };
      step("built");
      // add: a title that was not there is found at once; adding it again only merges
      out.facts.before = ask(db, { title: "Qzxv Brand New" });
      const x = Catalog.add(db, { title: "Qzxv Brand New", aka: ["Qzxv Other Name"], ext: { tmdb: "q-1" } });
      out.facts.afterAdd = [x.created, ask(db, { title: "Qzxv Brand New" }) === x.entry];
      const again = Catalog.add(db, { title: "qzxv brand new!", ext: { anilist: "q-2" }, original_title: "Qzxv Original" });
      out.facts.merged = [again.merged, again.entry === x.entry];
      out.facts.newNames = [ask(db, { title: "Qzxv Other Name" }) === x.entry, ask(db, { title: "Qzxv Original" }) === x.entry, ask(db, { title: "?", ext: { anilist: "q-2" } }) === x.entry];
      step("added", [{ title: "Qzxv Other Name" }, { title: "Qzxv Original" }, { title: "?", ext: { anilist: "q-2" } }]);
      // update: the old name is gone, the new one is found
      Catalog.update(db, x.entry.id, { title: "Qzxv Renamed" });
      out.facts.updated = [ask(db, { title: "Qzxv Brand New" }), ask(db, { title: "Qzxv Renamed" }) === x.entry];
      step("updated", [{ title: "Qzxv Brand New" }, { title: "Qzxv Renamed" }]);
      // verify: a correction that makes it the twin of another entry folds the two into one (the checked one is kept), and both names find it
      const twin = Catalog.add(db, { title: "Wplk Official Name", year: 2001, ext: { tmdb: "w-1" } }).entry;
      const misread = Catalog.add(db, { title: "Wp1k Official Name", year: 2001 }).entry;
      const size = db.media.length;
      const kept = Catalog.verify(db, misread.id, { title: "Wplk Official Name", year: 2001, ext: { tmdb: "w-1" } }, "verified", "tmdb");
      out.facts.folded = [kept === misread, size - db.media.length, Catalog.get(db, twin.id), ask(db, { title: "Wp1k Official Name" }) === misread, ask(db, { title: "Wplk Official Name" }) === misread];
      step("folded", [{ title: "Wp1k Official Name" }, { title: "Wplk Official Name" }]);
      // merge by the API
      const a = db.media[4], b = db.media[20];
      const droppedId = Catalog.merge(db, a.id, b.id) === a ? b.id : a.id;
      out.facts.mergedGone = Catalog.get(db, droppedId);
      step("merged");
      // remove: gone from every answer; the same title can be added again
      Catalog.remove(db, x.entry.id);
      out.facts.removed = [ask(db, { title: "Qzxv Renamed" }), ask(db, { title: "Qzxv Other Name" }), ask(db, { title: "?", ext: { tmdb: "q-1" } }), Catalog.get(db, x.entry.id)];
      step("removed", [{ title: "Qzxv Renamed" }, { title: "Qzxv Other Name" }, { title: "?", ext: { tmdb: "q-1" } }]);
      out.facts.addedAgain = Catalog.add(db, { title: "Qzxv Renamed" }).created;
      // details: an imdb id from the online check (verify.js calls setDetails on the entry itself, and Verify.apply with "details")
      const e1 = db.media[7], e2 = db.media[30];
      Catalog.setDetails(e1, { imdb: "tt7654321" });
      Verify.apply(db, { [e2.id]: { verdict: "details", imdb: "tt7654322", checked_at: 1 } });
      out.facts.details = [ask(db, { title: "?", ext: { imdb: "tt7654321" } }) === e1, ask(db, { title: "?", ext: { imdb: "tt7654322" } }) === e2];
      step("details", [{ title: "?", ext: { imdb: "tt7654321" } }, { title: "?", ext: { imdb: "tt7654322" } }]);
      return out;
    }""")
    for name, s in r["steps"].items():
        assert s["bad"] == [] and s["stale"] == 0 and s["found"] > 100, name
    f = r["facts"]
    assert f["before"] is None and f["afterAdd"] == [True, True] and f["merged"] == [True, True]
    assert f["newNames"] == [True, True, True]
    assert f["updated"] == [None, True]
    assert f["folded"] == [True, 1, None, True, True]
    assert f["mergedGone"] is None
    assert f["removed"] == [None, None, None, None] and f["addedAgain"] is True
    assert f["details"] == [True, True]


def test_the_index_is_dropped_when_the_list_is_replaced(phone):
    _ready(phone)
    r = phone.evaluate(r"""() => {
      const mk = (seed) => { const d = { media: [] }; Catalog.addMany(d, genTitles(90, seed, 0.3)); return JSON.stringify({ reels: [], inbox: [], media: d.media, mediaTypes: [] }); };
      const libA = mk(21), libB = mk(22);
      // a title with nothing left once cleaned ("!!!") cannot be found by name, so it is not asked about
      const own = (lib) => JSON.parse(lib).media.filter((m) => Catalog.normTitle(m.title)).map((m) => ({ title: m.title, type: m.type, year: m.year, language: m.language }));
      const out = {};
      const look = (name, lib) => {  // the oracle agrees, no answer is an entry of another list, and the titles of `lib` are all found
        const a = agree(db, own(lib));
        const mine = own(lib).filter((p) => ask(db, p)).length;
        out[name] = { bad: a.bad, stale: a.stale, mine, of: own(lib).length, size: db.media.length };
      };
      window.__rn.db = libA; loadDb();
      look("loaded A", libA);
      window.__rn.db = libB; loadDb();             // another list is read (the app starts, or a stale page reads again)
      look("loaded B", libB);
      out.aInB = own(libA).filter((p) => ask(db, p)).length;
      // a stale copy: another page saved library A while this page held B; this page's save is refused and the app reads again
      Catalog.add(db, { title: "Only In The Stale Copy" });
      window.__rn.db = libA; window.__rn.rev = (window.__rn.rev || 0) + 1;
      out.saved = saveDb();
      out.staleCopyAnswer = ask(db, { title: "Only In The Stale Copy" });
      look("stale reload", libA);
      out.bInA = own(libB).filter((p) => ask(db, p)).length;
      // a new, empty library (nothing stored): the app starts with an empty list
      window.__rn.db = ""; loadDb();
      look("empty", libA);
      out.emptyFound = own(libA).filter((p) => ask(db, p)).length;
      Catalog.add(db, { title: "First Title Of A New Library" });
      out.firstFound = ask(db, { title: "First Title Of A New Library" }) !== null;
      window.__rn.db = libA; loadDb();
      look("back to A", libA);
      return out;
    }""")
    for name in ("loaded A", "loaded B", "stale reload", "empty", "back to A"):
        assert r[name]["bad"] == [] and r[name]["stale"] == 0, name
    assert r["loaded A"]["mine"] == r["loaded A"]["of"] > 50 and r["loaded B"]["mine"] == r["loaded B"]["of"] > 50
    assert r["aInB"] <= 2 and r["bInA"] <= 2     # titles of the other list are gone (a chance word may repeat)
    assert r["saved"] is False and r["staleCopyAnswer"] is None
    assert r["stale reload"]["mine"] == r["stale reload"]["of"]
    assert r["empty"]["size"] == 0 and r["emptyFound"] == 0 and r["firstFound"] is True
    assert r["back to A"]["mine"] == r["back to A"]["of"]


def test_delete_all_keeps_the_watchlist_and_it_is_still_found(phone):
    _ready(phone)
    lib = phone.evaluate("() => { const d = { media: [] }; Catalog.addMany(d, genTitles(90, 31, 0.3)); return JSON.stringify({ reels: [{ code: 'R1', url: 'https://www.instagram.com/reel/R1/', status: 'new', added_at: 1 }], inbox: [], media: d.media, mediaTypes: [] }); }")
    phone.evaluate("(lib) => { window.__rn.db = lib; loadDb(); }", lib)
    before = phone.evaluate("() => ({ ...agree(db), size: db.media.length })")
    assert before["bad"] == [] and before["found"] > 100 and before["size"] > 50
    phone.evaluate("() => { location.hash = '#/settings'; }")
    phone.click("#wipe")                                  # Delete all reels and notes (the dialog is accepted by the harness)
    phone.wait_for_function("() => db.reels.length === 0")
    after = phone.evaluate("() => ({ ...agree(db), size: db.media.length })")
    assert after["bad"] == [] and after["found"] == before["found"] and after["size"] == before["size"]   # the watchlist is kept, and found as before


def test_other_code_that_changes_the_list_in_place_makes_the_index_start_again(phone):
    _ready(phone)
    r = phone.evaluate(r"""() => {
      const db = { media: [] };
      Catalog.addMany(db, genTitles(120, 41, 0.3));
      const out = {};
      const look = (name) => { const a = agree(db); out[name] = { bad: a.bad, stale: a.stale, size: db.media.length }; };
      look("built");
      db.media = db.media.filter((m, i) => i % 3);                       // a new array, like Verify.migrate's filter
      look("filtered");
      const taken = db.media.splice(2, 3);                               // entries taken out in place
      look("spliced out");
      db.media.push(...taken);                                           // and put back at the end
      look("pushed");
      db.media.unshift({ ...taken[0], id: "m-copy", title: "A Copy Put In Front" });
      look("unshifted");
      out.copyFound = ask(db, { title: "A Copy Put In Front" }) === db.media[0];
      db.media.length = 0;                                               // emptied in place
      look("emptied");
      return out;
    }""")
    for name in ("built", "filtered", "spliced out", "pushed", "unshifted", "emptied"):
        assert r[name]["bad"] == [] and r[name]["stale"] == 0, name
    assert r["copyFound"] is True and r["emptied"]["size"] == 0


# ---------------------------------------------------------------- 3. fast, and no longer reading the whole list

# Budgets for adding N titles (Catalog.addMany) and then checking N of them (Catalog.verify), in milliseconds. Desktop Chromium on the
# machine these were set on measured MEASURED; the old code took about 1 s and 20 s to add, and 0.9 s and 30 s to check.
BUDGET_MS = {1000: (1000, 1000), 5000: (5000, 5000)}


@pytest.mark.parametrize("n", [1000, 5000])
def test_adding_and_checking_n_titles_stays_within_budget(phone, n):
    _ready(phone)
    r = phone.evaluate(r"""(n) => {
      const db = { media: [] };
      const list = genTitles(n, 51, 0.02);
      let t = performance.now();
      Catalog.addMany(db, list);
      const addMs = performance.now() - t;
      const ids = db.media.map((m) => m.id);
      t = performance.now();
      let checked = 0;
      for (let i = 0; i < n; i++) {   // the online check's answer: the official name (same words), a year and a database id
        const m = Catalog.get(db, ids[(i * 7919) % ids.length]);
        if (!m) continue;
        Catalog.verify(db, m.id, { title: m.title, year: m.year || 2000, ext: { tmdb: "v" + i }, genres: ["Drama"] }, "verified", "tmdb");
        checked++;
      }
      return { size: db.media.length, addMs, checked, verifyMs: performance.now() - t };
    }""", n)
    print(f"n={n}: add {r['addMs']:.0f} ms, check {r['checked']} {r['verifyMs']:.0f} ms, list {r['size']}")
    add_budget, verify_budget = BUDGET_MS[n]
    assert r["size"] >= 0.9 * n and r["checked"] >= 0.9 * r["size"]
    assert r["addMs"] < add_budget and r["verifyMs"] < verify_budget


def test_a_lookup_no_longer_cleans_every_stored_name(phone):
    """Counted, not timed: cleaning a name calls String.prototype.normalize once, and the old scan cleaned every name of every entry
    for every title (about 3 x 1,500 calls per add). The index cleans the names of a list once, when it first needs them."""
    _ready(phone)
    r = phone.evaluate(r"""() => {
      const db = { media: [] };
      Catalog.addMany(db, genTitles(1500, 61, 0.02));
      const more = genTitles(60, 62, 0.3), probes = genTitles(40, 63, 0.3);
      let calls = 0;
      const real = String.prototype.normalize;
      String.prototype.normalize = function (...a) { calls++; return real.apply(this, a); };
      const count = (fn) => { calls = 0; fn(); return calls; };
      try {
        const out = { size: db.media.length };
        out.add = count(() => { for (const c of more) Catalog.add(db, c); }) / more.length;
        out.find = count(() => { for (const c of probes) Catalog.findSame(db, { ...c, type: "movie", year: null }); }) / probes.length;
        const ids = db.media.slice(0, 40).map((m) => m.id);
        out.verify = count(() => { for (const id of ids) Catalog.verify(db, id, { title: Catalog.get(db, id).title, ext: { tmdb: "n" + id } }, "verified", "tmdb"); }) / ids.length;
        out.remove = count(() => { for (const id of ids.slice(0, 10)) Catalog.remove(db, id); });          // taking entries out reads nothing
        out.afterRemove = count(() => { Catalog.add(db, { title: "After the removals" }); });              // and the index was not built again
        out.merge = count(() => { Catalog.merge(db, db.media[5].id, db.media[9].id); });
        out.afterMerge = count(() => { Catalog.add(db, { title: "After the merge" }); });
        db.media = db.media.slice();                                                                        // a new array: one new index
        out.rebuild = count(() => { Catalog.findSame(db, { title: "After the new array", type: "movie" }); });
        out.afterRebuild = count(() => { Catalog.findSame(db, { title: "Once more", type: "movie" }); });
        out.left = db.media.length;
        return out;
      } finally { String.prototype.normalize = real; }
    }""")
    assert r["size"] >= 1450
    assert r["add"] < 60 and r["find"] < 10 and r["verify"] < 60   # about 10 names cleaned per title (the old scan: more than 4,000)
    assert r["remove"] < 5 and r["afterRemove"] < 60 and r["merge"] < 60 and r["afterMerge"] < 60
    assert r["rebuild"] > 1000                       # the names of the whole list, once, for a list that is new
    assert r["afterRebuild"] < 10
