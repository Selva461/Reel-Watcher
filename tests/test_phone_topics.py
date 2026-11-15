"""Topics (assets/local/library.js): reels grouped by what they are about. They are worked out only when the Ask screen or a
topic page needs them, a few milliseconds at a time, and never when a reel is opened (a library of thousands of reels used to
freeze the app for minutes). Placeholder text only: the reels are generated here, the same ones every run."""
import json

import pytest

from test_phone_app import phone, site  # noqa: F401  (pytest fixtures)
from test_phone_search import _library

# n reels about `kinds` different subjects, built in the page from a fixed seed (the same reels every run). Each reel is about
# 4 KB of text like a real one: a caption, a transcript, text on screen and the notes. 70% of its words belong to its subject
# (neighbouring subjects share some), 20% are everyday words every subject uses, 10% are anything. Returns {reels, kind}:
# kind[i] is the subject reel i was generated from, to check that the groups found are the real ones.
GEN_JS = r"""([n, kinds]) => {
  let s = 20261114;
  const rnd = () => { s |= 0; s = s + 0x6D2B79F5 | 0; let t = Math.imul(s ^ s >>> 15, 1 | s); t = t + Math.imul(t ^ t >>> 7, 61 | t) ^ t; return ((t ^ t >>> 14) >>> 0) / 4294967296; };
  const syl = "ba be bi bo bu ka ke ki ko ku ma me mi mo mu ra re ri ro ru sa se si so su ta te ti to tu na ne ni no nu la le li lo lu".split(" ");
  const V = 40000, vocab = [];
  for (let i = 0; i < V; i++) { let w = ""; const k = 2 + (i % 3); for (let j = 0; j < k; j++) w += syl[Math.floor(rnd() * syl.length)]; vocab.push(w + (i % 7 === 0 ? "s" : "")); }
  const reels = [], kind = [];
  for (let i = 0; i < n; i++) {
    const k = Math.floor(rnd() * kinds);
    const text = (len) => { let o = ""; while (o.length < len) { const u = rnd(); o += (u < 0.7 ? vocab[(k * 257 + Math.floor(300 * Math.pow(rnd(), 2))) % V] : u < 0.9 ? vocab[Math.floor(2000 * Math.pow(rnd(), 2))] : vocab[Math.floor(rnd() * V)]) + " "; } return o.trim(); };
    const code = "R" + String(i).padStart(6, "0");
    reels.push({ code, url: "https://www.instagram.com/reel/" + code + "/", author: "creator" + (i % 900), collections: ["c" + (i % 9)], status: "done",
      added_at: 1.7e12 + i * 1000, caption: text(700), transcript: text(2500), onscreen: text(400), caption_read: 1, video_tried: 1, notes_by: "phone", notes_at: 1.7e12,
      notes: { topic: text(60), points: [text(120), text(120), text(120)], meaning: text(100), use: [text(60), text(60)], tools: [text(8), text(8)], takeaway: text(100), tags: [text(8), text(8), text(8), text(8)] } });
    kind.push(k);
  }
  return { reels, kind };
}"""

# A probe for the main thread: startProbe() ticks all the time, stopProbe() gives the longest time between two ticks (ms), so
# the longest stretch the screen could not draw or listen. Desktop Chromium, so only the relative size means anything.
PROBE_JS = r"""
window.sleep = (ms) => new Promise((r) => setTimeout(r, ms));
window.__probe = { last: 0, gap: 0, iv: null };
window.startProbe = () => { const p = window.__probe; p.gap = 0; p.last = performance.now(); p.iv = setInterval(() => { const n = performance.now(); p.gap = Math.max(p.gap, n - p.last); p.last = n; }, 0); };
window.stopProbe = () => { const p = window.__probe; clearInterval(p.iv); return Math.round(Math.max(p.gap, performance.now() - p.last)); };
"""


def _generated(pg, n, kinds=150):
    """The generated library, built in the page (thousands of reels do not go through Python) and opened as the app's library."""
    pg.open_with()
    pg.evaluate("() => {" + PROBE_JS + "}")
    pg.evaluate("(a) => { const g = (" + GEN_JS + ")(a); window.__kind = g.kind; window.__json = JSON.stringify({ reels: g.reels, inbox: [] }); }", [n, kinds])
    pg.evaluate("() => { RN.load = () => window.__json; RN.store = () => true; loadDb(); }")


def _go(pg, route):
    pg.evaluate("(h) => { location.hash = h; }", route)


def test_opening_a_reel_never_starts_the_topics(phone):
    phone.open_with({"db": json.dumps(_library())}, "#/r/GYM002")
    phone.get_by_role("heading", name="Related reels").wait_for()
    assert phone.evaluate("() => Lib.topicsReady(db.reels)") is None   # the reel opened, and no topic work was done for it
    assert phone.locator("a.chip", has_text="Topic:").count() == 0
    # the Ask screen works them out (a small library: at once, nothing left saying "Working out topics...")
    _go(phone, "#/ask")
    phone.get_by_role("heading", name="Topics you learned").wait_for()
    assert phone.locator("#topicsBox .hint").count() == 0
    assert phone.evaluate("() => Lib.topicsReady(db.reels) !== null")
    # and then a reel points to its topic, which opens
    _go(phone, "#/r/GYM002")
    phone.locator("a.chip", has_text="Topic:").click()
    # Wait for the topic page itself. "Squats first" is on the reel page too, and the click changes the address before the
    # page is drawn again: until then the page is still the reel page, with its two related reels as .list-item (what the
    # first version of this test counted on a slow runner: 2).
    phone.get_by_text("3 reels about the same thing").wait_for()
    assert phone.locator(".list-item").count() == 3
    assert phone.locator("#app li a", has_text="Squats first").count() == 1


# The page handles an address change 300 ms late, like a slow runner does: the address is already the topic's while the screen
# is still the reel's.
SLOW_REDRAW_JS = "(() => { const add = window.addEventListener.bind(window); window.addEventListener = (t, f, o) => add(t, t === 'hashchange' ? (e) => setTimeout(() => f(e), 300) : f, o); })();"


def test_a_topic_page_lists_the_whole_group_even_when_the_page_redraws_late(phone):
    phone.context.add_init_script(SLOW_REDRAW_JS)
    phone.open_with({"db": json.dumps(_library())}, "#/r/GYM002")
    phone.get_by_role("heading", name="Related reels").wait_for()
    _go(phone, "#/ask")
    phone.get_by_role("heading", name="Topics you learned").wait_for()
    _go(phone, "#/r/GYM002")
    phone.locator("a.chip", has_text="Topic:").click()
    # in the 300 ms before the redraw the address is the topic's and the screen is the reel's: it has "Squats first" and its two
    # related reels as .list-item, so neither tells the topic page from the reel page. Only the topic page counts its reels.
    phone.get_by_text("3 reels about the same thing").wait_for()
    assert phone.locator(".list-item").count() == 3
    assert phone.evaluate("() => location.hash") == "#/topic/workout%2Bgym%2Bset"


def test_opening_a_reel_in_a_library_of_a_thousand_does_not_freeze(phone):
    _generated(phone, 1000)
    out = phone.evaluate("""async () => {
      Notes.index(db.reels);   // the index is built by any search or related-reels lookup too: not what is measured here
      const code = db.reels[500].code;
      await sleep(30); startProbe(); await sleep(30);
      const t = performance.now();
      reelScreen(code);
      const ms = performance.now() - t;
      await sleep(30);
      return { ms: Math.round(ms), block: stopProbe(), shown: !!document.querySelector("#app h2") };
    }""")
    assert out["shown"]
    assert out["ms"] < 1000, out    # the groups took about 2 s here before: the reel opened only when they were done
    assert phone.evaluate("() => Lib.topicsReady(db.reels)") is None


def test_ask_screen_and_topic_page_wait_for_the_topics_without_freezing(phone):
    _generated(phone, 1000)
    phone.evaluate("() => Notes.index(db.reels)")
    _go(phone, "#/ask")
    phone.locator("#topicsBox h2", has_text="Topics you learned").wait_for(timeout=30000)
    assert phone.locator("#topicsBox a.list-item").count() == 12
    assert phone.locator("#topicsBox .hint").count() == 0
    # a topic opens (the groups are kept: at once), and a reel there points back to it
    phone.locator("#topicsBox a.list-item").first.click()
    phone.get_by_text("grouped by the words they share").wait_for()
    first = phone.locator(".stack a.list-item").first
    first.wait_for()
    first.click()
    phone.locator("a.chip", has_text="Topic:").wait_for()


def test_leaving_the_topic_page_while_it_waits_shows_nothing_stale(phone):
    _generated(phone, 1000)
    key = phone.evaluate("() => { Notes.index(db.reels); const k = Lib.topics(db.reels)[0].key; db.reels[0].caption += ' '; Notes.index(db.reels); return k; }")
    # the change dropped the groups: the topic page has to wait for them
    _go(phone, "#/topic/" + phone.evaluate("(k) => encodeURIComponent(k)", key))
    phone.locator("#topicWait").wait_for()
    _go(phone, "#/ask?q=zzzzzz")
    phone.get_by_role("heading", name="Ask your library").wait_for()
    phone.wait_for_timeout(2500)   # long enough for the work to finish if it were still going
    assert phone.locator("#topicWait").count() == 0
    assert "grouped by the words they share" not in phone.locator("#app").inner_text()
    # coming back to it works
    _go(phone, "#/topic/" + phone.evaluate("(k) => encodeURIComponent(k)", key))
    phone.get_by_text("grouped by the words they share").wait_for(timeout=30000)


@pytest.mark.parametrize("n", [1000, 5000])
def test_topics_of_a_big_library_are_worked_out_in_small_steps(phone, n):
    _generated(phone, n)
    out = phone.evaluate("""async (check) => {
      const rs = db.reels;
      Notes.index(rs);   // built (and paid for) by any search too; not what is measured here
      await sleep(30); startProbe(); await sleep(30);
      const t0 = performance.now();
      let got = null;
      const done = new Promise((res) => Lib.topicsSoon(rs, (g) => { got = g; res(); }, () => true));
      const returned = performance.now() - t0, atOnce = got !== null;
      await done;
      const total = performance.now() - t0;
      const block = stopProbe();
      // the groups found against the subjects the reels were made from
      const kind = new Map(rs.map((r, i) => [r.code, window.__kind[i]]));
      let inGroups = 0, pure = 0;
      for (const g of got) { const c = new Map(); for (const r of g.reels) c.set(kind.get(r.code), (c.get(kind.get(r.code)) || 0) + 1); inGroups += g.reels.length; pure += Math.max(...c.values()); }
      const out = { atOnce, returned: Math.round(returned), total: Math.round(total), block, groups: got.length, inGroups, purity: pure / inGroups, same: null };
      if (check) {   // in small steps or all at once, the same groups (a copy of the reels, so nothing is kept from the first run)
        const copy = JSON.parse(JSON.stringify(rs));
        const sig = (gs) => JSON.stringify(gs.map((g) => [g.key, g.label, g.reels.map((r) => r.code)]));
        out.same = sig(Lib.topics(copy)) === sig(got);
      }
      return out;
    }""", n == 1000)
    assert not out["atOnce"], out          # more than one step: the screen was handed back in between
    assert out["returned"] < 300, out      # the first call returns after one step
    assert out["block"] < 300, out         # the longest time the screen could not draw or listen (about 70 ms here at 5000 reels; before, one block of seconds)
    assert out["total"] < 60000, out
    assert out["groups"] >= 100 and out["inGroups"] >= 0.95 * n, out   # the generated reels are about 150 subjects
    assert out["purity"] >= 0.98, out      # and the groups hold reels of one subject
    if n == 1000:
        assert out["same"], out


def test_topics_are_kept_until_a_reel_changes(phone):
    phone.open_with({"db": json.dumps(_library())})
    r = phone.evaluate("""() => {
      const rs = JSON.parse(window.__rn.db).reels;
      const codes = (gs, c) => gs.find((g) => g.reels.some((x) => x.code === c)).reels.map((x) => x.code).sort();
      const out = {};
      out.cold = Lib.topicsReady(rs);
      const a = Lib.topics(rs);
      out.kept = Lib.topics(rs) === a && Lib.topicsReady(rs) === a;
      Lib.countTools(rs.slice(0, 3));            // what the topic page does for one group: must not drop the library's topics
      out.keptAfterTools = Lib.topicsReady(rs) === a;
      rs[0].status = "other";                    // not part of the words
      out.keptAfterStatus = Lib.topicsReady(rs) === a;
      out.foodBefore = codes(Lib.topics(rs), "SEC001").includes("FOOD01");
      Object.assign(rs[6].notes, { topic: "Hardcoded passwords leak user data", points: ["Never hardcode a password in the app", "Rotate any leaked password"], tags: ["security", "passwords"] });
      out.droppedAfterEdit = Lib.topicsReady(rs) === null;
      out.foodAfter = codes(Lib.topics(rs), "SEC001").includes("FOOD01");
      rs.push(Object.assign({}, rs[3], { code: "GYM004" }));
      out.droppedAfterAdd = Lib.topicsReady(rs) === null;
      out.gymAfterAdd = codes(Lib.topics(rs), "GYM001");
      rs.pop();
      out.droppedAfterRemove = Lib.topicsReady(rs) === null;
      out.gymAfterRemove = codes(Lib.topics(rs), "GYM001");
      return out;
    }""")
    assert r["cold"] is None and r["kept"] and r["keptAfterTools"] and r["keptAfterStatus"]
    assert r["foodBefore"] is False and r["droppedAfterEdit"] and r["foodAfter"] is True
    assert r["droppedAfterAdd"] and r["gymAfterAdd"] == ["GYM001", "GYM002", "GYM003", "GYM004"]
    assert r["droppedAfterRemove"] and r["gymAfterRemove"] == ["GYM001", "GYM002", "GYM003"]


@pytest.mark.parametrize("n,kinds,cap", [(100, 12, 30), (1000, 150, None)])
def test_every_topic_key_names_exactly_one_group(phone, n, kinds, cap):
    # A topic page is found by its key (the words of the group), so two groups must never share one. They can have the same
    # words: with the cap (a forced 30 words here; the real 40 above 500 reels) one subject is cut into a big group and a
    # small piece.
    phone.open_with()
    out = phone.evaluate("""([n, k, cap]) => {
      const rs = (""" + GEN_JS + """)([n, k]).reels;
      const gs = Lib.topics(rs, 0.3, cap === null ? undefined : cap);
      const twins = gs.filter((g, i) => gs.findIndex((t) => t.label === g.label) !== i).length;   // called by the same words as an earlier group
      return { groups: gs.length, keys: new Set(gs.map((g) => g.key)).size, twins, reachable: gs.every((g) => gs.find((t) => t.key === g.key) === g) };
    }""", [n, kinds, cap])
    assert out["twins"] >= 1, out   # the generated library does have such groups (else this checks nothing)
    assert out["keys"] == out["groups"] and out["reachable"], out


def test_the_topic_link_of_a_reel_in_a_cut_group_opens_that_group(phone):
    _generated(phone, 1000)
    pick = phone.evaluate("""() => {
      Notes.index(db.reels);
      const gs = Lib.topics(db.reels);                                              // kept: the reel page links to its topic
      const g = gs.find((x, i) => gs.findIndex((t) => t.label === x.label) !== i);  // the second group called by the same words
      return g && { code: g.reels[0].code, size: g.reels.length };
    }""")
    assert pick, "the generated library has no two groups with the same words any more"
    _go(phone, "#/r/" + pick["code"])
    chip = phone.locator("a.chip", has_text="Topic:")
    chip.wait_for()
    assert chip.inner_text().endswith(f"({pick['size']})")
    chip.click()
    # the topic page says how many reels it holds (the reel page has no such line): it must be the group the link counted
    phone.get_by_text(f"{pick['size']} reels about the same thing").wait_for(timeout=10000)
    assert phone.locator("#app .list-item").count() == pick["size"]
    assert phone.locator(f'#app .list-item[href="#/r/{pick["code"]}"]').count() == 1   # and it holds the reel the link was on


def test_a_failed_attempt_is_not_kept(phone):
    phone.open_with({"db": json.dumps(_library())})
    r = phone.evaluate("""() => {
      const rs = JSON.parse(window.__rn.db).reels;
      const real = Notes.synonyms;
      Notes.synonyms = () => { throw new Error("boom"); };   // something goes wrong half way through
      let failed = false;
      try { Lib.topics(rs); } catch (e) { failed = e.message === "boom"; }
      Notes.synonyms = real;
      return { failed, ready: Lib.topicsReady(rs), groups: Lib.topics(rs).length };   // the next try starts over (and does not hang)
    }""")
    assert r == {"failed": True, "ready": None, "groups": 2}


def test_a_change_while_the_topics_are_being_worked_out_starts_them_again(phone):
    _generated(phone, 1000)
    out = phone.evaluate("""async () => {
      const rs = db.reels;
      Notes.index(rs);
      let got = null, calls = 0;
      Lib.topicsSoon(rs, (g) => { got = g; calls++; }, () => true);
      const early = got !== null;                                      // one step does not finish 1000 reels
      rs.push(Object.assign({}, rs[5], { code: "COPY001" }));          // a reel with the same words as reel 5: it joins that reel's group
      for (let i = 0; i < 4000 && got === null; i++) await sleep(5);
      return { early, calls, copyGrouped: !!got && got.some((g) => g.reels.some((r) => r.code === "COPY001")),
               ready: Lib.topicsReady(rs) === got };
    }""")
    assert out == {"early": False, "calls": 1, "copyGrouped": True, "ready": True}, out


def test_topics_wait_when_nobody_wants_them_and_go_on_when_asked_again(phone):
    _generated(phone, 1000)
    out = phone.evaluate("""async () => {
      const rs = db.reels;
      Notes.index(rs);
      let calls = 0, got = null;
      Lib.topicsSoon(rs, () => { calls++; }, () => false);             // nobody waits: nothing is done and nothing is reported
      await sleep(300);
      const idle = { calls, ready: Lib.topicsReady(rs) };
      Lib.topicsSoon(rs, (g) => { got = g; }, () => true);
      for (let i = 0; i < 4000 && got === null; i++) await sleep(5);
      return { idle, done: got !== null && Lib.topicsReady(rs) === got };
    }""")
    assert out == {"idle": {"calls": 0, "ready": None}, "done": True}, out


# Signatures (number of groups, a hash of their keys, labels and reels) of the groups the code made before the topics were
# worked out in steps (1.3.8), for the generated libraries (n reels, kinds subjects). Libraries of up to 500 reels are grouped
# exactly as they were.
GOLDEN = [(40, 8, 8, 2927789391), (150, 25, 25, 2111211709), (300, 40, 40, 3610189692), (500, 60, 59, 1339501572)]


def test_libraries_up_to_500_reels_are_grouped_exactly_as_before(phone):
    phone.open_with()
    got = phone.evaluate("""(sizes) => sizes.map(([n, k]) => {
      const rs = (""" + GEN_JS + """)([n, k]).reels;
      const sig = (gs) => { const s = JSON.stringify(gs.map((g) => [g.key, g.label, g.reels.map((r) => r.code)])); let h = 5381; for (let i = 0; i < s.length; i++) h = ((h * 33) ^ s.charCodeAt(i)) >>> 0; return [n, k, gs.length, h]; };
      const a = sig(Lib.topics(rs)), b = sig(Lib.topics(rs, 0.3, Infinity));   // as the screens do, and with every word
      return JSON.stringify(a) === JSON.stringify(b) ? a : ["differs", a, b];
    })""", [[n, k] for n, k, _, _ in GOLDEN])
    assert got == [list(g) for g in GOLDEN]


def test_the_ask_screen_of_an_empty_library_does_not_wait_for_topics(phone):
    phone.open_with({"db": json.dumps({"reels": [], "inbox": []})}, "#/ask")
    phone.get_by_role("heading", name="Ask your library").wait_for()
    assert phone.locator("#topicsBox .hint").count() == 0
    assert phone.locator("#topicsBox h2").count() == 0
